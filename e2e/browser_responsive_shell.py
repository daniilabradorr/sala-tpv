"""Focused mobile shell, keyboard and accessibility browser coverage.

Run explicitly with::

    python manage.py test e2e.browser_responsive_shell
"""

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class BrowserResponsiveShellTests(StaticLiveServerTestCase):
    email = "responsive.e2e@example.com"
    password = "Responsive-E2E-Password-123!"

    def setUp(self):
        OnboardingService.create_business(
            legal_name="Responsive E2E SL",
            trade_name="Responsive E2E",
            tax_identifier="B12345679",
            phone="923222222",
            email="responsive-business@example.com",
            address_line_1="Calle Responsive 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Responsive",
            owner_first_name="Responsive",
            owner_last_name="Owner",
            owner_email=self.email,
            owner_phone="600000001",
            owner_password=self.password,
            owner_pin="4321",
        )

    def test_mobile_sidebar_keyboard_focus_and_semantics(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 375, "height": 812})
            page = context.new_page()
            javascript_errors = []
            page.on("pageerror", lambda error: javascript_errors.append(str(error)))
            try:
                page.goto(f"{self.live_server_url}/users/login/")
                expect(page.locator('a.skip-link[href="#main-content"]')).to_have_count(
                    1
                )
                expect(page.locator("main#main-content")).to_have_count(1)
                page.get_by_label("Correo electrónico").fill(self.email)
                page.get_by_label("Contraseña").fill(self.password)
                page.get_by_role("button", name="Iniciar sesión").click()
                page.wait_for_url(f"{self.live_server_url}/")

                toggle = page.get_by_role("button", name="Abrir menú")
                sidebar = page.locator("#app-sidebar")
                overlay = page.locator("[data-sidebar-overlay]")
                expect(toggle).to_be_visible()
                expect(toggle).to_have_attribute("aria-expanded", "false")
                expect(sidebar).to_have_attribute("inert", "")
                expect(overlay).to_be_hidden()
                expect(page.locator("main#main-content")).to_have_count(1)
                expect(page.locator('[aria-current="page"]')).to_have_text("Inicio")

                toggle.click()
                expect(toggle).to_have_attribute("aria-expanded", "true")
                expect(sidebar).not_to_have_attribute("inert", "")
                expect(sidebar.locator("a").first).to_be_focused()
                expect(page.get_by_role("link", name="Catálogo")).to_be_visible()

                page.keyboard.press("Shift+Tab")
                expect(
                    sidebar.get_by_role("button", name="Cerrar sesión")
                ).to_be_focused()
                page.keyboard.press("Tab")
                expect(sidebar.locator("a").first).to_be_focused()

                page.keyboard.press("Escape")
                expect(toggle).to_have_attribute("aria-expanded", "false")
                expect(toggle).to_be_focused()
                expect(overlay).to_be_hidden()

                toggle.click()
                page.get_by_role("link", name="Catálogo").click()
                page.wait_for_url(f"{self.live_server_url}/catalog/")
                expect(page.locator('[aria-current="page"]')).to_have_text("Catálogo")
                self.assertTrue(
                    page.evaluate(
                        "document.documentElement.scrollWidth <= "
                        "document.documentElement.clientWidth"
                    )
                )
                self.assertEqual(javascript_errors, [])
            finally:
                context.close()
                browser.close()
