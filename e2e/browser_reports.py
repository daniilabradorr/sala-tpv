"""Real Chromium coverage for the FE-19 Reports surface."""

import re
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService
from apps.inventory.tests.factories import (
    create_inventory_item,
    create_inventory_product,
)
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
        product = create_inventory_product(
            business=result.business, name="Producto bajo E2E"
        )
        create_inventory_item(
            business=result.business,
            store=result.store,
            product=product,
            current_stock=Decimal("1"),
            minimum_stock=Decimal("5"),
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
                expect(reports_workspace).to_have_attribute("data-active-tab", "sales")
                page.get_by_role("navigation", name="Informes").get_by_role(
                    "link", name="Inventario", exact=True
                ).click()
                expect(reports_workspace).to_have_attribute(
                    "data-active-tab", "inventory"
                )
                responsive_table = page.locator(
                    ".report-card", has_text="Necesitan atención"
                ).locator("table")
                expect(
                    responsive_table.get_by_text("Producto bajo E2E")
                ).to_be_visible()
                for width, expected_display in (
                    (375, "block"),
                    (767, "block"),
                    (768, "table"),
                    (1280, "table"),
                ):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertEqual(
                        responsive_table.evaluate(
                            "element => getComputedStyle(element).display"
                        ),
                        expected_display,
                    )
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
            finally:
                browser.close()
