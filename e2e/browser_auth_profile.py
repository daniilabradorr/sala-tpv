"""Real Chromium coverage for FE-06 access, profile, and standalone errors."""

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.users.tests.factories import create_business, create_user


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserAuthProfileTests(StaticLiveServerTestCase):
    email = "auth.e2e@example.com"
    password = "Auth-E2E-Password-123!"

    def setUp(self):
        business = create_business("Auth E2E", "auth-e2e")
        self.user = create_user(
            business, email=self.email, password=self.password, first_name="Ada"
        )
        self.user.set_pin("2468")
        self.user.save()

    def test_login_profile_security_expiry_and_404(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            try:
                page.goto(f"{self.live_server_url}/users/login/")
                expect(
                    page.get_by_role("heading", name="Bienvenido de nuevo")
                ).to_be_visible()
                expect(page.locator("[data-app-shell]")).to_have_count(0)
                password = page.get_by_label("Contraseña")
                password.fill("wrong")
                page.get_by_role("button", name="Mostrar").click()
                expect(password).to_have_attribute("type", "text")
                page.get_by_label("Correo electrónico").fill(self.email)
                page.get_by_role("button", name="Iniciar sesión").click()
                expect(
                    page.get_by_text("No hemos podido iniciar sesión")
                ).to_be_visible()
                password.fill(self.password)
                page.get_by_role("button", name="Iniciar sesión").click()
                page.goto(f"{self.live_server_url}/users/profile/")
                expect(page.get_by_role("heading", name="Mi perfil")).to_be_visible()
                page.get_by_role("link", name="Seguridad").click()
                expect(page.get_by_role("heading", name="Configurado")).to_be_visible()

                context.clear_cookies()
                page.evaluate(
                    "htmx.ajax('GET', '/users/profile/', {target:'#main-content'})"
                )
                page.wait_for_url("**/users/login/?**expired=1**")
                expect(
                    page.get_by_role("heading", name="Tu sesión ha caducado")
                ).to_be_visible()

                page.set_viewport_size({"width": 375, "height": 812})
                page.goto(f"{self.live_server_url}/users/login/")
                self.assertEqual(
                    page.evaluate("document.documentElement.scrollWidth"), 375
                )
                page.goto(f"{self.live_server_url}/missing-fe06-resource/")
                expect(
                    page.get_by_role("heading", name="No encontramos lo que buscas")
                ).to_be_visible()
                expect(page.locator("[data-app-shell]")).to_have_count(0)
            finally:
                browser.close()
