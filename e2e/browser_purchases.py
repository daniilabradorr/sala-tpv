"""Browser coverage for the complete FE-17 purchase and supplier workflow."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import re

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.business_config.models import POSSettings
from apps.catalog.models import Product
from apps.core.models import Business
from apps.inventory.models import InventoryItem, StockMovement
from apps.purchases.models import (
    Purchase,
    PurchaseReceipt,
    PurchaseStatusChoices,
    Supplier,
)
from apps.purchases.services import add_purchase_line
from apps.stores.models import Store
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class PurchasesBrowserTests(StaticLiveServerTestCase):
    password = "Purchases-E2E-123!"

    @staticmethod
    def _db_value(operation):
        """Evaluate one eager ORM value outside Playwright's asyncio context."""

        def worker():
            connections.close_all()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(worker).result()

    def setUp(self):
        self.business = Business.objects.create(
            name="Purchases browser", slug="purchases-browser"
        )
        self.owner = create_user(
            business=self.business,
            email="owner@purchases.test",
            password=self.password,
            role=RoleChoices.OWNER,
        )
        self.store = Store.objects.create(
            business=self.business,
            name="Centro",
            code="CENTRO",
            is_default=True,
        )
        POSSettings.objects.create(business=self.business, enable_stock_control=True)
        self.product = Product.objects.create(
            business=self.business,
            name="Café Browser",
            sku="CAFE-E2E",
            barcode="8412345678901",
            base_price=Decimal("4.00"),
            cost_price=Decimal("2.00"),
            unit=Product.UNIT_UNIDAD,
            track_stock=True,
        )
        InventoryItem.objects.create(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("4.000"),
        )
        Supplier.objects.create(business=self.business, name="Proveedor Browser")

    def login(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.owner.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()

    def test_complete_purchase_receipt_and_supplier_flow(self):
        store_pk = self.store.pk
        product_pk = self.product.pk
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            self.login(page)
            page.goto(f"{self.live_server_url}/purchases/")
            page.get_by_role("link", name="Nueva compra").click()

            page.get_by_role("button", name="Nuevo proveedor").click()
            modal = page.locator("#quick-supplier")
            expect(modal).to_have_attribute("open", "")
            modal.locator("input[name=name]").fill("Proveedor E2E")
            modal.get_by_role("button", name="Crear y seleccionar").click()
            expect(modal).not_to_have_attribute("open", "")
            supplier_value = page.locator(
                "#id_supplier option", has_text="Proveedor E2E"
            ).get_attribute("value")
            expect(page.locator("#id_supplier")).to_have_value(supplier_value)
            page.locator("input[name=reference]").fill("PUR-E2E")
            page.get_by_role("button", name="Crear borrador").click()
            expect(page.get_by_role("heading", name="Compra PUR-E2E")).to_be_visible()

            page.evaluate(
                """() => {
                    window.__purchaseLineModalSettled = false;
                    const handler = (event) => {
                        if (event.detail.target?.id === "purchase-line-modal-body") {
                            window.__purchaseLineModalSettled = true;
                            document.body.removeEventListener("htmx:afterSettle", handler);
                        }
                    };
                    document.body.addEventListener("htmx:afterSettle", handler);
                }"""
            )
            with page.expect_response(
                lambda response: (
                    "/lines/create/" in response.url and response.status == 200
                )
            ):
                page.get_by_role("button", name="Añadir producto").click()
            page.wait_for_function("window.__purchaseLineModalSettled === true")
            line_modal = page.locator("#purchase-line-modal")
            search = line_modal.get_by_label("Buscar producto")
            page.evaluate(
                """() => {
                    window.__productSearchSwapCount = 0;
                    document.body.addEventListener("htmx:afterSwap", (event) => {
                        if (event.detail.target?.id === "product-results") {
                            window.__productSearchSwapCount += 1;
                        }
                    });
                }"""
            )
            swap_count = page.evaluate("window.__productSearchSwapCount")
            with page.expect_response(
                lambda response: (
                    "/products/search/" in response.url
                    and "product_query=CAFE-E2E" in response.url
                    and response.status == 200
                )
            ) as response_info:
                search.fill("CAFE-E2E")
            response = response_info.value
            body = response.text()
            assert "Café Browser" in body
            assert "CAFE-E2E" in body
            page.wait_for_function(
                "previous => window.__productSearchSwapCount > previous",
                arg=swap_count,
            )
            result = line_modal.locator("#product-results").get_by_role(
                "button", name=re.compile("Café Browser.*CAFE-E2E")
            )
            expect(result).to_be_visible()
            swap_count = page.evaluate("window.__productSearchSwapCount")
            with page.expect_response(
                lambda response: (
                    "/products/search/" in response.url
                    and "product_query=" in response.url
                    and response.status == 200
                )
            ):
                search.fill("")
            page.wait_for_function(
                "previous => window.__productSearchSwapCount > previous",
                arg=swap_count,
            )
            expect(line_modal.locator("#product-results")).to_contain_text(
                "Escribe para buscar productos"
            )
            swap_count = page.evaluate("window.__productSearchSwapCount")
            with page.expect_response(
                lambda response: (
                    "/products/search/" in response.url
                    and "product_query=CAFE-E2E" in response.url
                    and response.status == 200
                )
            ):
                search.fill("CAFE-E2E")
            page.wait_for_function(
                "previous => window.__productSearchSwapCount > previous",
                arg=swap_count,
            )
            expect(result).to_be_visible()
            result.click()
            expect(line_modal.locator("input[name=product]")).to_have_value(
                str(product_pk)
            )
            line_modal.locator("input[name=unit_cost]").fill("2")
            line_modal.locator("input[name=tax_rate]").fill("10")
            line_modal.get_by_role("button", name="Guardar producto").click()
            expect(line_modal).to_have_attribute("open", "")
            expect(line_modal.locator(".field-errors")).to_be_visible()
            expect(page.locator("#purchase-workspace")).to_have_count(1)
            expect(page.get_by_role("link", name="Resumen")).to_be_visible()
            line_modal.locator("input[name=quantity]").fill("5")
            line_modal.get_by_role("button", name="Guardar producto").click()
            expect(line_modal).not_to_have_attribute("open", "")
            totals = page.locator("#purchase-lines .totals")
            expect(totals).to_contain_text("Subtotal")
            expect(totals).to_contain_text("10,00 €")
            expect(totals).to_contain_text("Impuestos")
            expect(totals).to_contain_text("1,00 €")
            expect(totals).to_contain_text("Total")
            expect(totals).to_contain_text("11,00 €")

            purchase_pk, subtotal, tax, total = self._db_value(
                lambda: Purchase.objects.values_list(
                    "pk", "subtotal_amount", "tax_amount", "total_amount"
                ).get(reference="PUR-E2E")
            )
            self.assertEqual(subtotal, Decimal("10.00"))
            self.assertEqual(tax, Decimal("1.00"))
            self.assertEqual(total, Decimal("11.00"))

            page.get_by_role("link", name="Realizar pedido").click()
            expect(page.get_by_text("Esta acción no cambia el stock.")).to_be_visible()
            page.get_by_role("button", name="Realizar pedido").click()
            expect(page.get_by_text("Pedida", exact=True)).to_be_visible()
            stock = self._db_value(
                lambda: InventoryItem.objects.values_list(
                    "current_stock", flat=True
                ).get(store_id=store_pk, product_id=product_pk)
            )
            self.assertEqual(stock, Decimal("4.000"))

            page.get_by_role("link", name="Registrar recepción").click()
            page.locator("input[name^=line_]").fill("2")
            page.locator("textarea[name=notes]").fill("Entrega 1")
            receipt_key = page.locator("input[name=idempotency_key]").input_value()
            page.get_by_role("button", name="Revisar recepción").click()
            expect(
                page.get_by_role("heading", name="Revisar recepción")
            ).to_be_visible()
            expect(page.locator("input[name=idempotency_key]")).to_have_value(
                receipt_key
            )
            page.get_by_role("button", name="Volver").click()
            expect(page.locator("input[name^=line_]")).to_have_value("2")
            expect(page.locator("textarea[name=notes]")).to_have_value("Entrega 1")
            expect(page.locator("input[name=idempotency_key]")).to_have_value(
                receipt_key
            )
            page.get_by_role("button", name="Revisar recepción").click()
            page.get_by_role("button", name="Registrar recepción").click()
            expect(page.get_by_text("RECEPCIÓN REGISTRADA")).to_be_visible()
            expect(
                page.get_by_text("Recibida parcialmente", exact=True)
            ).to_be_visible()
            stock = self._db_value(
                lambda: InventoryItem.objects.values_list(
                    "current_stock", flat=True
                ).get(store_id=store_pk, product_id=product_pk)
            )
            self.assertEqual(stock, Decimal("6.000"))
            self.assertEqual(self._db_value(StockMovement.objects.count), 1)
            self.assertEqual(self._db_value(PurchaseReceipt.objects.count), 1)

            page.get_by_role("link", name="Registrar recepción").click()
            page.locator("input[name^=line_]").fill("3")
            page.get_by_role("button", name="Revisar recepción").click()
            page.get_by_role("button", name="Registrar recepción").click()
            expect(page.get_by_text("Recibida", exact=True)).to_be_visible()
            expect(page.get_by_role("link", name="Registrar recepción")).to_have_count(
                0
            )
            stock = self._db_value(
                lambda: InventoryItem.objects.values_list(
                    "current_stock", flat=True
                ).get(store_id=store_pk, product_id=product_pk)
            )
            self.assertEqual(stock, Decimal("9.000"))
            self.assertEqual(self._db_value(StockMovement.objects.count), 2)
            purchase_status = self._db_value(
                lambda: Purchase.objects.values_list("status", flat=True).get(
                    pk=purchase_pk
                )
            )
            self.assertEqual(purchase_status, PurchaseStatusChoices.RECEIVED)

            page.get_by_role("link", name="Recepciones").click()
            page.get_by_role("link", name="Resumen").click()
            page.get_by_label("Detalle de compra").get_by_role(
                "link", name="Productos", exact=True
            ).click()
            page.get_by_role("link", name="Recepciones").click()
            page.get_by_role("link", name="Resumen").click()
            expect(page.locator("#purchase-workspace")).to_have_count(1)
            page.get_by_role("link", name="Recepciones").click()
            movement_link = page.locator(".stock-impact a")
            expect(movement_link).to_have_count(2)
            movement_pk = self._db_value(
                lambda: (
                    StockMovement.objects.order_by("pk")
                    .values_list("pk", flat=True)
                    .first()
                )
            )
            page.locator(
                f'.stock-impact a[href="/inventory/movements/{movement_pk}/"]'
            ).click()
            expect(page).to_have_url(re.compile(r"/inventory/movements/\d+/$"))
            page.goto(f"{self.live_server_url}/purchases/{purchase_pk}/")
            page.get_by_role("link", name="Proveedor E2E").click()
            page.get_by_role("link", name="Compras").click()
            expect(page.get_by_role("link", name="Compra PUR-E2E")).to_be_visible()
            page.get_by_role("link", name="Resumen").click()
            page.get_by_role("link", name="Compras").click()
            expect(page.locator("#supplier-workspace")).to_have_count(1)
            browser.close()

    def test_responsive_surfaces_have_no_horizontal_overflow(self):
        supplier = Supplier.objects.get(name="Proveedor Browser")
        purchase = Purchase.objects.create(
            business=self.business,
            store=self.store,
            supplier=supplier,
            created_by=self.owner,
            reference="RESPONSIVE-LINES",
        )
        add_purchase_line(
            business=self.business,
            purchase=purchase,
            product=self.product,
            quantity=5,
            unit_cost=2,
            tax_rate=10,
            user=self.owner,
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width in (375, 767, 768):
                page = browser.new_page(viewport={"width": width, "height": 812})
                self.login(page)
                page.goto(f"{self.live_server_url}/purchases/")
                ids_are_unique = page.evaluate(
                    """() => { const ids = [...document.querySelectorAll('[id]')]
                        .map((node) => node.id); return new Set(ids).size === ids.length; }"""
                )
                assert ids_are_unique
                if width <= 767:
                    page.get_by_role("button", name="Filtros").click()
                    expect(page.locator("#purchase-filters")).to_have_attribute(
                        "open", ""
                    )
                    page.locator("#purchase-filters").get_by_role(
                        "button", name="×"
                    ).click()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                page.get_by_role("link", name="Proveedores", exact=True).click()
                if width <= 767:
                    expect(
                        page.locator(".purchase-cards").get_by_text(
                            "Proveedor Browser", exact=True
                        )
                    ).to_be_visible()
                else:
                    expect(
                        page.locator(".purchase-table table").get_by_text(
                            "Proveedor Browser", exact=True
                        )
                    ).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                page.goto(f"{self.live_server_url}/purchases/{purchase.pk}/")
                page.get_by_label("Detalle de compra").get_by_role(
                    "link", name="Productos", exact=True
                ).click()
                if width <= 767:
                    card = page.locator(".purchase-line-card")
                    expect(card).to_be_visible()
                    expect(card).to_contain_text("Pedida")
                    expect(card).to_contain_text("Recibida")
                    expect(card).to_contain_text("Pendiente")
                    expect(card.get_by_role("button", name="Editar")).to_be_visible()
                else:
                    expect(page.locator(".purchase-line-table")).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                page.close()
            browser.close()
