"""Real Chromium coverage for the FE-11 modal checkout."""

import re
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashSession
from apps.catalog.models import Category
from apps.onboarding.services import OnboardingService
from apps.payments.models import Payment
from apps.sales.tests.factories import create_sales_inventory_item, create_sales_product


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserCheckoutTests(StaticLiveServerTestCase):
    email = "checkout.e2e@example.com"
    password = "E2E-Checkout-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Checkout E2E SL",
            trade_name="Checkout E2E",
            tax_identifier="B12345678",
            phone="923111111",
            email="checkout@e2e.test",
            address_line_1="Calle Caja 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Centro",
            owner_first_name="Eva",
            owner_last_name="Checkout",
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
        category = Category.objects.create(
            business=result.business, name="Caja", is_active=True
        )
        product = create_sales_product(
            business=result.business,
            name="Producto checkout",
            sku="CHECKOUT-1",
            base_price=Decimal("10.90"),
            track_stock=True,
        )
        product.category = category
        product.save(update_fields=["category", "updated_at"])
        create_sales_inventory_item(
            business=result.business,
            store=result.store,
            product=product,
            current_stock=Decimal("50.000"),
        )
        self.store_id = result.store.pk
        self.session_id = self.session.pk

    def _login_and_sale(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.goto(
            f"{self.live_server_url}/sales/stores/{self.store_id}/"
            f"cash-sessions/{self.session_id}/sales/open/"
        )
        page.get_by_role("button", name="Iniciar venta").click()
        page.get_by_role("button", name=re.compile("Producto checkout")).click()

    def _open_checkout(self, page, width):
        if width < 1200:
            page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
        page.get_by_role("link", name=re.compile("COBRAR")).click()
        dialog = page.locator("#checkout-dialog")
        expect(dialog).to_have_attribute("open", "")
        expect(dialog.get_by_role("heading", name="COBRAR")).to_be_visible()
        return dialog

    def test_card_checkout_completes_with_dominant_new_sale_action(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login_and_sale(page)
            dialog = self._open_checkout(page, 1440)
            dialog.get_by_role("radio", name=re.compile("Tarjeta")).check()
            dialog.get_by_role("button", name=re.compile("CONFIRMAR COBRO")).click()
            expect(
                dialog.get_by_role("heading", name="VENTA COMPLETADA")
            ).to_be_visible()
            expect(dialog.get_by_role("button", name="NUEVA VENTA")).to_be_visible()
            expect(dialog.get_by_role("link", name="Ver documento")).to_be_visible()
            browser.close()
        self.assertEqual(Payment.objects.filter(method__code="card").count(), 1)

    def test_cash_split_and_responsive_previews(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for viewport in (
                {"width": 900, "height": 900},
                {"width": 375, "height": 812},
            ):
                with self.subTest(viewport=viewport):
                    page = browser.new_page(viewport=viewport)
                    self._login_and_sale(page)
                    dialog = self._open_checkout(page, viewport["width"])
                    dialog.get_by_role("radio", name=re.compile("Efectivo")).check()
                    dialog.get_by_role("button", name="EXACTO").click()
                    expect(dialog.locator("[data-cash-change]")).to_have_text("0,00 €")
                    dialog.get_by_label("Entregado por el cliente").fill("20")
                    expect(dialog.locator("[data-cash-change]")).to_have_text("9,10 €")
                    dialog.get_by_role("radio", name="Pago dividido").check()
                    expect(dialog.locator("[data-split-part]:visible")).to_have_count(2)
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                    )
                    page.close()
            browser.close()
