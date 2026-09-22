"""Real Chromium coverage for the FE-10 TPV catalogue and server cart."""

from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashSession
from apps.onboarding.services import OnboardingService
from apps.sales.tests.factories import (
    create_sale,
    create_sales_customer,
    create_sales_inventory_item,
    create_sales_product,
)


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserTPVTests(StaticLiveServerTestCase):
    email = "tpv.e2e@example.com"
    password = "E2E-TPV-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="TPV E2E SL",
            trade_name="TPV E2E",
            tax_identifier="B12345678",
            phone="923111111",
            email="business-tpv@example.com",
            address_line_1="Calle TPV 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Centro",
            owner_first_name="Eva",
            owner_last_name="TPV",
            owner_email=self.email,
            owner_phone="600000000",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.result = result
        self.session = CashSession.objects.create(
            business=result.business,
            store=result.store,
            cash_register=result.cash_register,
            opened_by=result.owner,
        )
        self.product = create_sales_product(
            business=result.business,
            name="Café especial",
            sku="CAFE-10",
            barcode="8410000000010",
            base_price=Decimal("2.00"),
            track_stock=True,
        )
        create_sales_inventory_item(
            business=result.business,
            store=result.store,
            product=self.product,
            current_stock=Decimal("50.000"),
        )
        self.customer = create_sales_customer(
            business=result.business, name="Cliente TPV"
        )

    def _login(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_url(f"{self.live_server_url}/")

    def test_catalogue_ticket_and_responsive_surfaces(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport in (
                    {"width": 1440, "height": 900},
                    {"width": 900, "height": 900},
                    {"width": 375, "height": 812},
                ):
                    with self.subTest(viewport=viewport):
                        sale = create_sale(
                            business=self.result.business,
                            store=self.result.store,
                            opened_by=self.result.owner,
                            cash_register=self.result.cash_register,
                            cash_session=self.session,
                        )
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        self._login(page)
                        page.goto(
                            f"{self.live_server_url}/sales/stores/{self.result.store.pk}/sales/{sale.pk}/"
                        )
                        expect(
                            page.get_by_role(
                                "heading", name=f"Venta #{sale.pk} · Tienda Centro"
                            )
                        ).to_be_visible()
                        search = page.locator("#product-search")
                        if viewport["width"] >= 768:
                            expect(search).to_be_focused()
                        search.fill("CAFE-10")
                        expect(
                            page.get_by_role("button", name="Café especial")
                        ).to_be_visible()
                        page.get_by_role("button", name="Café especial").click()
                        expect(
                            page.locator("#sale-cart").get_by_text("Café especial")
                        ).to_be_visible()
                        if viewport["width"] < 900:
                            expect(page.locator(".mobile-cart-bar")).to_be_visible()
                            page.locator("[data-ticket-open]").click()
                            expect(page.locator("#sale-cart")).to_be_visible()
                        page.get_by_label("Aumentar Café especial").click()
                        expect(page.locator('[name="quantity"]')).to_have_value("2.000")
                        page.locator('[name="quantity"]').fill("1.500")
                        page.get_by_role("button", name="Aplicar").click()
                        expect(page.locator('[name="quantity"]')).to_have_value("1.500")
                        expect(
                            page.get_by_role("link", name="Cobrar", exact=False)
                        ).to_be_visible()
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                        )
                        assert errors == []
                        context.close()
            finally:
                browser.close()
