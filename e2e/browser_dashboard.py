"""Real Chromium coverage for the FE-08 operational dashboard."""

import re
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from apps.audit.models import AuditEvent
from apps.cash_register.models import CashSession
from apps.inventory.models import InventoryItem
from apps.onboarding.services import OnboardingService
from apps.purchases.models import Purchase, PurchaseStatusChoices, Supplier
from apps.sales.models import SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sales_product,
)


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
        result = OnboardingService.create_business(
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
        CashSession.objects.create(
            business=result.business,
            store=result.store,
            cash_register=result.cash_register,
            opened_by=result.owner,
            opening_amount=Decimal("50.00"),
            expected_cash_amount=Decimal("50.00"),
        )
        product = create_sales_product(
            business=result.business,
            name="Café Dashboard E2E",
            base_price=Decimal("100.00"),
        )
        sale = create_sale(
            business=result.business,
            store=result.store,
            opened_by=result.owner,
            status=SaleStatusChoices.COMPLETED,
        )
        create_sale_line(
            business=result.business,
            sale=sale,
            product=product,
            unit_base_price=Decimal("100.00"),
            tax_rate=Decimal("0.00"),
        )
        InventoryItem.objects.create(
            business=result.business,
            store=result.store,
            product=product,
            current_stock=Decimal("1.000"),
            minimum_stock=Decimal("2.000"),
        )
        supplier = Supplier.objects.create(
            business=result.business, name="Proveedor Dashboard E2E"
        )
        Purchase.objects.create(
            business=result.business,
            store=result.store,
            supplier=supplier,
            created_by=result.owner,
            status=PurchaseStatusChoices.ORDERED,
            reference="PED-E2E-001",
            ordered_at=timezone.now(),
        )
        AuditEvent.objects.create(
            business=result.business,
            store=result.store,
            user=None,
            event_type="dashboard.e2e",
            module="core",
            message="Actividad Dashboard E2E",
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
                        page.get_by_role("button", name="Iniciar sesión").click()

                        expect(page.locator("[data-app-shell]")).to_be_visible()
                        expect(
                            page.get_by_role("heading", name="Resumen de Centro E2E")
                        ).to_be_visible()
                        expect(page.locator(".dashboard-kpi")).to_have_count(4)
                        expect(page.get_by_text("100,00 €").first).to_be_visible()
                        expect(
                            page.locator("[data-dashboard-chart] svg")
                        ).to_be_visible()
                        expect(
                            page.get_by_role("heading", name="Caja", exact=True)
                        ).to_be_visible()
                        expect(page.get_by_text("Sesión abierta")).to_be_visible()
                        expect(
                            page.get_by_role("heading", name="Stock crítico")
                        ).to_be_visible()
                        expect(page.get_by_text("Café Dashboard E2E")).to_be_visible()
                        expect(
                            page.get_by_role("heading", name="Compras pendientes")
                        ).to_be_visible()
                        expect(page.get_by_text("PED-E2E-001")).to_be_visible()
                        expect(
                            page.get_by_role("heading", name="Actividad reciente")
                        ).to_be_visible()
                        expect(
                            page.get_by_text("Actividad Dashboard E2E")
                        ).to_be_visible()
                        expect(page.get_by_text("Sistema")).to_be_visible()

                        dashboard = page.locator("#dashboard-content")
                        page.locator("[data-app-shell]").evaluate(
                            "element => element.dataset.dashboardShell = 'stable'"
                        )
                        period_select = page.locator("#dashboard-period")
                        period_select.select_option("7d")
                        expect(page).to_have_url(re.compile(r"[?&]period=7d(?:&|$)"))
                        expect(page.locator("#dashboard-period")).to_have_value("7d")
                        expect(
                            page.locator("[data-dashboard-chart] svg")
                        ).to_have_count(1)
                        expect(
                            page.locator('[data-dashboard-shell="stable"]')
                        ).to_have_count(1)

                        period_select.select_option("30d")
                        expect(page).to_have_url(re.compile(r"[?&]period=30d(?:&|$)"))
                        expect(page.locator("#dashboard-period")).to_have_value("30d")
                        expect(
                            page.locator("[data-dashboard-chart] svg")
                        ).to_have_count(1)

                        page.go_back()
                        expect(page.locator("#dashboard-period")).to_have_value("7d")
                        expect(
                            page.locator("[data-dashboard-chart] svg")
                        ).to_have_count(1)
                        page.go_back()
                        expect(page.locator("#dashboard-period")).to_have_value("today")
                        expect(
                            page.locator("[data-dashboard-chart] svg")
                        ).to_have_count(1)
                        page.go_forward()
                        expect(page.locator("#dashboard-period")).to_have_value("7d")
                        expect(
                            page.locator("[data-dashboard-chart] svg")
                        ).to_have_count(1)
                        expect(dashboard).to_have_count(1)
                        self.assertLessEqual(
                            page.evaluate("document.documentElement.scrollWidth"),
                            viewport["width"],
                        )
                        self.assertEqual(errors, [])
                        context.close()
            finally:
                browser.close()
