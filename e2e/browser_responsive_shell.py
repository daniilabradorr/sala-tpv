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

                toggle = page.locator("[data-sidebar-toggle]")
                sidebar = page.locator("#app-sidebar")
                catalog_link = sidebar.get_by_role("link", name="Productos")
                overlay = page.locator("[data-sidebar-overlay]")
                expect(toggle).to_be_visible()
                expect(toggle).to_have_attribute("aria-expanded", "false")
                expect(toggle).to_have_attribute("aria-label", "Abrir menú")
                expect(sidebar).to_have_attribute("inert", "")
                expect(overlay).to_be_hidden()
                expect(page.locator("main#main-content")).to_have_count(1)
                expect(page.locator('[aria-current="page"]')).to_have_text("Inicio")

                toggle.click()
                expect(toggle).to_have_attribute("aria-expanded", "true")
                expect(toggle).to_have_attribute("aria-label", "Cerrar menú")
                expect(sidebar).not_to_have_attribute("inert", "")
                expect(sidebar.locator("a").first).to_be_focused()
                expect(catalog_link).to_be_visible()

                page.keyboard.press("Shift+Tab")
                expect(
                    sidebar.get_by_role("link", name="Responsive Owner")
                ).to_be_focused()
                page.keyboard.press("Tab")
                expect(sidebar.locator("a").first).to_be_focused()

                page.keyboard.press("Escape")
                expect(toggle).to_have_attribute("aria-expanded", "false")
                expect(toggle).to_have_attribute("aria-label", "Abrir menú")
                expect(toggle).to_be_focused()
                expect(overlay).to_be_hidden()

                toggle.click()
                catalog_link.click()
                page.wait_for_url(f"{self.live_server_url}/catalog/products/")
                expect(catalog_link).to_have_attribute("aria-current", "page")
                catalog_tabs = page.get_by_role(
                    "navigation", name="Secciones del catálogo"
                )
                expect(
                    catalog_tabs.get_by_role("link", name="Productos")
                ).to_have_attribute("aria-current", "page")
                page.keyboard.press("Control+k")
                command_trigger = page.locator("[data-command-trigger]")
                palette = page.locator("[data-command-dialog]")
                expect(palette).to_be_visible()
                expect(page.locator("[data-command-input]")).to_be_focused()
                page.locator("[data-command-input]").fill("invent")
                expect(palette.get_by_role("link", name="Inventario")).to_be_visible()
                page.keyboard.press("Escape")
                expect(palette).to_be_hidden()
                expect(command_trigger).to_be_focused()
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

    def test_desktop_and_tablet_sidebar_breakpoint(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 800})
            page = context.new_page()
            try:
                page.goto(f"{self.live_server_url}/users/login/")
                page.get_by_label("Correo electrónico").fill(self.email)
                page.get_by_label("Contraseña").fill(self.password)
                page.get_by_role("button", name="Iniciar sesión").click()
                page.wait_for_url(f"{self.live_server_url}/")
                sidebar = page.locator("#app-sidebar")
                expect(sidebar).to_be_visible()
                expect(sidebar).not_to_have_attribute("inert", "")
                expect(page.locator("[data-sidebar-toggle]")).to_be_hidden()
                self.assertTrue(
                    page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                )
                page.set_viewport_size({"width": 1200, "height": 800})
                expect(page.locator("[data-sidebar-toggle]")).to_be_hidden()
                page.set_viewport_size({"width": 1199, "height": 800})
                expect(page.locator("[data-sidebar-toggle]")).to_be_visible()
                expect(sidebar).to_have_attribute("inert", "")
                page.set_viewport_size({"width": 768, "height": 800})
                page.locator("[data-sidebar-toggle]").click()
                expect(sidebar).not_to_have_attribute("inert", "")
                expect(page.locator("[data-sidebar-overlay]")).to_be_visible()
                page.keyboard.press("Escape")
                page.set_viewport_size({"width": 767, "height": 800})
                expect(sidebar).to_have_attribute("inert", "")
                expect(page.locator("[data-sidebar-toggle]")).to_be_visible()
                self.assertTrue(
                    page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                )
            finally:
                context.close()
                browser.close()
