"""Browser coverage for the complete FE-17 purchase and supplier workflow."""

from decimal import Decimal
import re

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
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

            page.get_by_role("button", name="Añadir producto").click()
            line_modal = page.locator("#purchase-line-modal")
            line_modal.get_by_label("Buscar producto").fill("CAFE-E2E")
            result = line_modal.locator("#product-results").get_by_role(
                "button", name="Café Browser CAFE-E2E · 8412345678901"
            )
            expect(result).to_be_visible()
            result.click()
            line_modal.locator("input[name=quantity]").fill("5")
            line_modal.locator("input[name=unit_cost]").fill("2")
            line_modal.locator("input[name=tax_rate]").fill("10")
            line_modal.get_by_role("button", name="Guardar producto").click()
            expect(page.locator("#purchase-lines")).to_contain_text("11.00 €")

            page.get_by_role("link", name="Realizar pedido").click()
            expect(page.get_by_text("Esta acción no cambia el stock.")).to_be_visible()
            page.get_by_role("button", name="Realizar pedido").click()
            expect(page.get_by_text("Pedida", exact=True)).to_be_visible()
            self.assertEqual(
                InventoryItem.objects.get(
                    store=self.store, product=self.product
                ).current_stock,
                Decimal("4.000"),
            )

            page.get_by_role("link", name="Registrar recepción").click()
            page.locator("input[name^=line_]").fill("2")
            page.get_by_role("button", name="Revisar recepción").click()
            expect(
                page.get_by_role("heading", name="Revisar recepción")
            ).to_be_visible()
            page.get_by_role("button", name="Registrar recepción").click()
            expect(page.get_by_text("RECEPCIÓN REGISTRADA")).to_be_visible()
            expect(
                page.get_by_text("Recibida parcialmente", exact=True)
            ).to_be_visible()
            self.assertEqual(
                InventoryItem.objects.get(
                    store=self.store, product=self.product
                ).current_stock,
                Decimal("6.000"),
            )
            self.assertEqual(StockMovement.objects.count(), 1)
            self.assertEqual(PurchaseReceipt.objects.count(), 1)

            page.get_by_role("link", name="Registrar recepción").click()
            page.locator("input[name^=line_]").fill("3")
            page.get_by_role("button", name="Revisar recepción").click()
            page.get_by_role("button", name="Registrar recepción").click()
            expect(page.get_by_text("Recibida", exact=True)).to_be_visible()
            expect(page.get_by_role("link", name="Registrar recepción")).to_have_count(
                0
            )
            self.assertEqual(
                InventoryItem.objects.get(
                    store=self.store, product=self.product
                ).current_stock,
                Decimal("9.000"),
            )
            self.assertEqual(StockMovement.objects.count(), 2)
            purchase = Purchase.objects.get(reference="PUR-E2E")
            self.assertEqual(purchase.status, PurchaseStatusChoices.RECEIVED)

            page.get_by_role("link", name="Recepciones").click()
            movement_link = page.locator(".stock-impact a")
            expect(movement_link).to_have_count(2)
            movement_pk = StockMovement.objects.order_by("pk").values_list(
                "pk", flat=True
            )[0]
            page.locator(
                f'.stock-impact a[href="/inventory/movements/{movement_pk}/"]'
            ).click()
            expect(page).to_have_url(re.compile(r"/inventory/movements/\d+/$"))
            page.goto(f"{self.live_server_url}/purchases/{purchase.pk}/")
            page.get_by_role("link", name="Proveedor E2E").click()
            page.get_by_role("link", name="Compras").click()
            expect(page.get_by_role("link", name="Compra PUR-E2E")).to_be_visible()
            browser.close()

    def test_responsive_surfaces_have_no_horizontal_overflow(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width in (375, 767, 768):
                page = browser.new_page(viewport={"width": width, "height": 812})
                self.login(page)
                page.goto(f"{self.live_server_url}/purchases/")
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
                page.close()
            browser.close()
