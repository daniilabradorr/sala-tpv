"""Real Chromium coverage for the FE-19 Reports surface."""

import re

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService
from apps.stores.models import Store


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserReportsTests(StaticLiveServerTestCase):
    EMAIL = "reports.e2e@example.com"
    PASSWORD = "E2E-Reports-Password-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Reports E2E SL",
            trade_name="Reports E2E",
            tax_identifier="B10000005",
            phone="923000005",
            email="reports-e2e-business@example.com",
            address_line_1="Calle Cinco",
            postal_code="37005",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro E2E",
            owner_first_name="Reports",
            owner_last_name="E2E",
            owner_email=self.EMAIL,
            owner_phone="600000005",
            owner_password=self.PASSWORD,
            owner_pin="1234",
        )
        Store.objects.create(
            business=result.business, name="Norte E2E", code="NORTH-E2E"
        )

    def test_reports_navigation_filters_tabs_and_responsive_layout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(f"{self.live_server_url}/users/login/")
                page.get_by_label("Correo electrónico").fill(self.EMAIL)
                page.get_by_label("Contraseña").fill(self.PASSWORD)
                page.get_by_role("button", name="Iniciar sesión").click()
                page.get_by_role("navigation", name="Navegación principal").get_by_role(
                    "link", name="Informes", exact=True
                ).click()
                expect(page).to_have_url(re.compile(r"/reports/"))
                expect(page.get_by_role("heading", name="Informes")).to_be_visible()
                expect(
                    page.get_by_role("navigation", name="Informes").get_by_role("link")
                ).to_have_count(7)
                reports_workspace = page.locator("#reports-workspace")
                expect(reports_workspace).to_have_count(1)
                for tab, key in (
                    ("Ventas", "sales"),
                    ("Pagos", "payments"),
                    ("Caja", "cash"),
                    ("Fiscal", "tax"),
                    ("Inventario", "inventory"),
                    ("Compras", "purchases"),
                    ("General", "general"),
                ):
                    page.get_by_role("navigation", name="Informes").get_by_role(
                        "link", name=tab, exact=True
                    ).click()
                    expect(reports_workspace).to_have_attribute("data-active-tab", key)
                page.get_by_role("navigation", name="Informes").get_by_role(
                    "link", name="Ventas", exact=True
                ).click()
                expect(reports_workspace).to_have_attribute("data-active-tab", "sales")
                expect(
                    page.get_by_role("link", name="Descargar informe")
                ).to_have_attribute("href", re.compile(r"period=30d.*store="))
                page.get_by_label("Periodo").select_option("7d")
                page.get_by_role("button", name="Aplicar").click()
                expect(page).to_have_url(re.compile(r"period=7d"))
                page.go_back()
                expect(page).to_have_url(re.compile(r"period=30d"))
                for width in (375, 767, 768, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
            finally:
                browser.close()
