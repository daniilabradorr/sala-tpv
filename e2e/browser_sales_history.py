"""Real Chromium coverage for the FE-09 sales history surface."""

import re
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService
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
class BrowserSalesHistoryTests(StaticLiveServerTestCase):
    email = "sales-history.e2e@example.com"
    password = "E2E-Sales-History-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Histórico E2E SL",
            trade_name="Histórico E2E",
            tax_identifier="B87654321",
            phone="923111111",
            email="history-business@example.com",
            address_line_1="Calle Historia 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro Histórico E2E",
            owner_first_name="Ana",
            owner_last_name="Historia",
            owner_email=self.email,
            owner_phone="600000000",
            owner_password=self.password,
            owner_pin="1234",
        )
        product = create_sales_product(
            business=result.business,
            name="Producto snapshot E2E",
            base_price=Decimal("10.00"),
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
            unit_base_price=Decimal("10.00"),
        )

    def test_history_htmx_detail_and_responsive_layout(self):
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
                        page.get_by_label("Correo electrónico").fill(self.email)
                        page.get_by_label("Contraseña").fill(self.password)
                        page.get_by_role("button", name="Iniciar sesión").click()
                        page.get_by_role("link", name="Ventas", exact=True).click()

                        shell = page.locator("[data-app-shell]")
                        expect(shell).to_be_visible()
                        shell.evaluate(
                            "element => element.dataset.historyShell = 'stable'"
                        )
                        expect(
                            page.get_by_role("heading", name="Ventas")
                        ).to_be_visible()
                        page.get_by_role("link", name="7 días", exact=True).click()
                        expect(page).to_have_url(re.compile(r"[?&]period=7d(?:&|$)"))
                        expect(
                            page.locator('[data-history-shell="stable"]')
                        ).to_have_count(1)
                        expect(page.locator("#sales-history-content")).to_have_count(1)

                        page.get_by_label("Estado").select_option("completed")
                        page.get_by_role("button", name="Aplicar filtros").click()
                        expect(page).to_have_url(re.compile(r"[?&]period=7d(?:&|$)"))
                        expect(page).to_have_url(
                            re.compile(r"[?&]status=completed(?:&|$)")
                        )

                        if viewport["width"] <= 650:
                            expect(page.locator(".sale-mobile-card")).to_be_visible()
                            page.locator(".sale-mobile-card").first.click()
                        else:
                            expect(page.locator(".sales-table")).to_be_visible()
                            page.locator(".sales-table tbody a").first.click()
                        expect(
                            page.get_by_text("Producto snapshot E2E")
                        ).to_be_visible()
                        page.go_back()
                        expect(page).to_have_url(re.compile(r"[?&]period=7d(?:&|$)"))
                        self.assertEqual(errors, [])
                        overflow = page.evaluate(
                            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                        )
                        self.assertFalse(overflow)
                        context.close()
            finally:
                browser.close()
