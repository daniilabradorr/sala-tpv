"""Real Chromium coverage for the FE-08 operational dashboard."""

import re

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserDashboardTests(StaticLiveServerTestCase):
    EMAIL = "dashboard.e2e@example.com"
    PASSWORD = "E2E-Dashboard-Password-123!"

    def setUp(self):
        OnboardingService.create_business(
            legal_name="Dashboard E2E SL",
            trade_name="Dashboard E2E",
            tax_identifier="B87654321",
            phone="923111111",
            email="business-dashboard@example.com",
            address_line_1="Calle E2E 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro E2E",
            owner_first_name="Daniel",
            owner_last_name="E2E",
            owner_email=self.EMAIL,
            owner_phone="600000000",
            owner_password=self.PASSWORD,
            owner_pin="1234",
        )

    def test_dashboard_period_history_and_responsive_layout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport in (
                    {"width": 1440, "height": 900},
                    {"width": 900, "height": 900},
                    {"width": 375, "height": 812},
                ):
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(f"{self.live_server_url}/users/login/")
                        page.get_by_label("Correo electrónico").fill(self.EMAIL)
                        page.get_by_label("Contraseña").fill(self.PASSWORD)
                        page.get_by_role("button", name="Entrar").click()

                        expect(page.locator("[data-app-shell]")).to_be_visible()
                        expect(
                            page.get_by_role("heading", name="Resumen de Centro E2E")
                        ).to_be_visible()
                        expect(page.locator(".dashboard-kpi")).to_have_count(4)
                        expect(
                            page.locator("[data-dashboard-chart] svg")
                        ).to_be_visible()
                        expect(page.get_by_role("heading", name="Caja")).to_be_visible()
                        expect(
                            page.get_by_role("heading", name="Stock crítico")
                        ).to_be_visible()
                        expect(
                            page.get_by_role("heading", name="Compras pendientes")
                        ).to_be_visible()
                        expect(
                            page.get_by_role("heading", name="Actividad reciente")
                        ).to_be_visible()

                        dashboard = page.locator("#dashboard-content")
                        page.locator("[data-app-shell]").evaluate(
                            "element => element.dataset.dashboardShell = 'stable'"
                        )
                        page.get_by_label("Periodo").select_option("7d")
                        expect(page).to_have_url(re.compile(r"[?&]period=7d(?:&|$)"))
                        expect(page.locator("#dashboard-period")).to_have_value("7d")
                        expect(
                            page.locator('[data-dashboard-shell="stable"]')
                        ).to_have_count(1)
                        page.go_back()
                        expect(page.locator("#dashboard-period")).to_have_value("today")
                        page.go_forward()
                        expect(page.locator("#dashboard-period")).to_have_value("7d")
                        expect(dashboard).to_have_count(1)
                        self.assertLessEqual(
                            page.evaluate("document.documentElement.scrollWidth"),
                            viewport["width"],
                        )
                        self.assertEqual(errors, [])
                        context.close()
            finally:
                browser.close()
