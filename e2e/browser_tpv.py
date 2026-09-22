"""Real Chromium coverage for the FE-10 TPV catalogue and server cart."""

import re
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashSession
from apps.catalog.models import Category
from apps.onboarding.services import OnboardingService
from apps.sales.tests.factories import (
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
    viewports = (
        {"width": 1440, "height": 900},
        {"width": 900, "height": 900},
        {"width": 375, "height": 812},
    )

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
        self.category = Category.objects.create(
            business=result.business, name="Bebidas TPV", is_active=True
        )
        self.product = create_sales_product(
            business=result.business,
            name="Café especial",
            sku="CAFE-10",
            barcode="8410000000010",
            base_price=Decimal("2.00"),
            track_stock=True,
        )
        self.product.category = self.category
        self.product.save(update_fields=["category", "updated_at"])
        create_sales_inventory_item(
            business=result.business,
            store=result.store,
            product=self.product,
            current_stock=Decimal("50.000"),
        )
        self.customer = create_sales_customer(
            business=result.business, name="Cliente TPV"
        )
        # All ORM setup happens before Playwright enters its event-loop context.
        self.store_id = result.store.pk
        self.session_id = self.session.pk
        self.customer_id = self.customer.pk
        self.category_id = self.category.pk

    def _login(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_url(f"{self.live_server_url}/")

    def _open_sale(self, page):
        page.goto(
            f"{self.live_server_url}/sales/stores/{self.store_id}/"
            f"cash-sessions/{self.session_id}/sales/open/"
        )
        expect(page.get_by_role("heading", name="Nueva venta")).to_be_visible()
        expect(page.get_by_text("Tienda Centro", exact=True).first).to_be_visible()
        expect(page.get_by_text("Caja principal", exact=True)).to_be_visible()
        expect(page.get_by_text(f"#{self.session_id}", exact=True)).to_be_visible()
        page.get_by_role("button", name="Iniciar venta").click()
        expect(page).to_have_url(re.compile(r"/sales/stores/\d+/sales/\d+/$"))

    def _open_ticket_if_needed(self, page, width):
        if width >= 1200:
            expect(page.locator("#sale-cart")).to_be_visible()
            return
        trigger = page.locator('[data-nx-drawer-trigger="sale-cart"]')
        expect(trigger).to_be_visible()
        trigger.click()
        expect(page.locator("#sale-cart")).to_have_attribute("open", "")
        expect(page.locator("#sale-cart [data-nx-drawer-close]")).to_be_focused()

    def test_catalogue_ticket_and_responsive_surfaces(self):
        # IDs and all other ORM-derived data are materialised before sync_playwright.
        scenarios = tuple(dict(viewport) for viewport in self.viewports)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport in scenarios:
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        self._login(page)
                        self._open_sale(page)

                        heading = page.get_by_role(
                            "heading", name=re.compile(r"Venta #\d+ · Tienda Centro")
                        )
                        expect(heading).to_be_visible()
                        if viewport["width"] >= 1200:
                            expect(page.locator(".app-sidebar")).to_have_css(
                                "width", "76px"
                            )
                            expect(page.locator(".erp-workspace")).to_have_css(
                                "margin-left", "76px"
                            )

                        search = page.locator("#product-search")
                        if viewport["width"] >= 768:
                            expect(search).to_be_focused()
                        category_chip = page.locator("#category-chips").get_by_role(
                            "button", name="Bebidas TPV", exact=True
                        )
                        category_chip.click()
                        expect(category_chip).to_have_attribute("aria-pressed", "true")

                        with page.expect_request(
                            lambda request: (
                                "q=CAFE-10" in request.url
                                and f"category={self.category_id}" in request.url
                            )
                        ):
                            search.fill("CAFE-10")
                        product_button = page.get_by_role(
                            "button", name=re.compile("Café especial")
                        )
                        expect(product_button).to_be_visible()
                        expect(category_chip).to_have_attribute("aria-pressed", "true")
                        expect(product_button).to_be_visible()
                        product_button.click()

                        self._open_ticket_if_needed(page, viewport["width"])
                        cart = page.locator("#sale-cart")
                        expect(cart.get_by_text("Café especial")).to_be_visible()
                        quantity = cart.get_by_label("Cantidad")
                        expect(quantity).to_have_value("1.000")
                        with page.expect_response(
                            lambda response: (
                                "/quantity/" in response.url
                                and response.request.method == "POST"
                            )
                        ):
                            cart.get_by_label("Aumentar Café especial").click()
                        if viewport["width"] < 1200:
                            expect(cart).to_have_attribute("open", "")
                            expect(cart.get_by_label("Cantidad")).to_be_visible()
                        expect(cart.get_by_label("Cantidad")).to_have_value("2.000")
                        with page.expect_response(
                            lambda response: (
                                "/quantity/" in response.url
                                and response.request.method == "POST"
                            )
                        ):
                            cart.get_by_label("Reducir Café especial").click()
                        if viewport["width"] < 1200:
                            expect(cart).to_have_attribute("open", "")
                            expect(cart.get_by_label("Cantidad")).to_be_visible()
                        expect(cart.get_by_label("Cantidad")).to_have_value("1.000")
                        cart.get_by_label("Cantidad").fill("1.500")
                        with page.expect_response(
                            lambda response: (
                                "/quantity/" in response.url
                                and response.request.method == "POST"
                            )
                        ):
                            cart.get_by_role("button", name="Actualizar").click()
                        if viewport["width"] < 1200:
                            expect(cart).to_have_attribute("open", "")
                            expect(cart.get_by_label("Cantidad")).to_be_visible()
                        expect(cart.get_by_label("Cantidad")).to_have_value("1.500")

                        cart.get_by_role("link", name="Editar").click()
                        editor = page.locator("#line-editor-dialog")
                        expect(editor).to_have_attribute("open", "")
                        page.get_by_role("button", name="Guardar cambios").click()
                        expect(editor).not_to_have_attribute("open", "")
                        expect(page.locator("#line-editor-panel")).to_have_count(1)
                        cart.get_by_role("link", name="Editar").click()
                        expect(editor).to_have_attribute("open", "")
                        page.get_by_role("button", name="Cerrar editor").click()

                        cart.get_by_role("button", name="Eliminar").click()
                        expect(cart.get_by_text("Café especial")).to_have_count(0)
                        if viewport["width"] < 1200:
                            expect(cart).to_have_attribute("open", "")
                            cart.get_by_role("button", name="Cerrar ticket").click()
                            expect(cart).not_to_have_attribute("open", "")
                        page.get_by_role(
                            "button", name=re.compile("Café especial")
                        ).click()
                        if viewport["width"] < 1200:
                            page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
                        expect(cart.get_by_text("Café especial")).to_be_visible()
                        if viewport["width"] < 1200:
                            cart.get_by_role("button", name="Cerrar ticket").click()

                        page.get_by_role("radio", name="Factura", exact=True).check()
                        page.get_by_role("button", name="Actualizar cabecera").click()
                        expect(
                            page.get_by_text("Debes seleccionar un cliente")
                        ).to_be_visible()
                        page.get_by_role("radio", name="Cliente", exact=True).check()
                        page.locator("#id_customer").select_option(
                            str(self.customer_id)
                        )
                        page.get_by_role("button", name="Actualizar cabecera").click()
                        expect(page.locator("#id_customer")).to_have_value(
                            str(self.customer_id)
                        )
                        page.get_by_role("radio", name="Ticket", exact=True).check()
                        page.get_by_role("button", name="Actualizar cabecera").click()
                        if viewport["width"] < 1200:
                            page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
                        expect(
                            cart.get_by_role("link", name=re.compile(r"^COBRAR"))
                        ).to_be_visible()

                        if viewport["width"] < 1200:
                            trigger = page.locator(
                                '[data-nx-drawer-trigger="sale-cart"]'
                            )
                            if not cart.get_attribute("open"):
                                trigger.click()
                            page.keyboard.press("Escape")
                            expect(cart).not_to_have_attribute("open", "")
                            expect(trigger).to_be_focused()
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                        )
                        assert errors == []
                        context.close()
            finally:
                browser.close()
