"""Real Chromium coverage for the FE-14 inventory workspace."""

from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.inventory.models import StockAdjustment
from apps.inventory.tests.factories import (
    create_business,
    create_inventory_item,
    create_inventory_owner,
    create_inventory_product,
    create_inventory_store,
)


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class InventoryBrowserTests(StaticLiveServerTestCase):
    password = "Inventory-E2E-123!"

    def test_workspace_filters_detail_quick_adjustment_and_responsive(self):
        business = create_business("Inventory Browser", "inventory-browser")
        store = create_inventory_store(business=business, name="Centro", code="CENTRO")
        other_store = create_inventory_store(
            business=business, name="Norte", code="NORTE"
        )
        owner = create_inventory_owner(business=business, password=self.password)
        product = create_inventory_product(business=business, name="Agua 50cl")
        product.sku = "AG-001"
        product.save(update_fields=["sku", "updated_at"])
        item = create_inventory_item(
            business=business,
            store=store,
            product=product,
            current_stock=Decimal("3"),
            minimum_stock=Decimal("5"),
        )
        create_inventory_item(
            business=business,
            store=other_store,
            product=product,
            current_stock=Decimal("10"),
            minimum_stock=Decimal("2"),
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{self.live_server_url}/users/login/")
            page.get_by_label("Correo electrónico").fill(owner.email)
            page.get_by_label("Contraseña").fill(self.password)
            page.get_by_role("button", name="Iniciar sesión").click()
            page.goto(f"{self.live_server_url}/inventory/?store={store.pk}")
            expect(page.get_by_role("heading", name="Inventario")).to_be_visible()
            expect(page.get_by_text("Productos controlados")).to_be_visible()
            page.get_by_label("Buscar producto o SKU").fill("AG-001")
            page.get_by_role("button", name="Filtrar").click()
            expect(page.get_by_text("Agua 50cl")).to_be_visible()
            page.get_by_text("Agua 50cl").click()
            page.get_by_role("tab", name="Movimientos").click()
            page.get_by_role("tab", name="Ajustes").click()
            page.get_by_role("tab", name="Resumen").click()
            page.get_by_role("link", name="Ajustar stock").click()
            page.get_by_label("Stock contado físicamente").fill("6")
            expect(page.locator("#difference-preview")).to_have_text("+3.000")
            page.get_by_role("button", name="Preparar ajuste").click()
            expect(page.get_by_text("El stock todavía no ha cambiado.")).to_be_visible()
            expect(page.get_by_text("Confirmar modificará el stock")).to_be_visible()
            for width, height in ((1440, 900), (900, 900), (375, 812)):
                page.set_viewport_size({"width": width, "height": height})
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"),
                    page.evaluate("document.documentElement.clientWidth"),
                )
            browser.close()

        item.refresh_from_db()
        self.assertEqual(item.current_stock, Decimal("3"))
        self.assertEqual(
            StockAdjustment.objects.get().status, StockAdjustment.STATUS_DRAFT
        )
