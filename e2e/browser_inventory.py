"""Real Chromium coverage for the FE-14 inventory workspace."""

from decimal import Decimal
import re

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.inventory.models import StockAdjustment, StockMovement
from apps.inventory.services import increase_stock
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

    def _login(self, page, owner):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(owner.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()

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
            self._login(page, owner)
            page.goto(f"{self.live_server_url}/inventory/?store={store.pk}")
            expect(page.get_by_role("heading", name="Inventario")).to_be_visible()
            expect(page.get_by_text("Productos controlados")).to_be_visible()
            page.get_by_label("Buscar producto o SKU").fill("AG-001")
            page.evaluate(
                """() => {
                  window.__inventoryFilterSwapped = false;
                  document.body.addEventListener("htmx:afterSwap", (event) => {
                    if (event.detail.target?.id === "inventory-workspace") {
                      window.__inventoryFilterSwapped = true;
                    }
                  });
                }"""
            )
            with page.expect_response(
                lambda response: (
                    "/inventory/" in response.url and "search=AG-001" in response.url
                )
            ) as filter_response:
                page.get_by_role("button", name="Filtrar").click()
            self.assertEqual(filter_response.value.status, 200)
            expect(page).to_have_url(re.compile(r"search=AG-001"))
            page.wait_for_function("window.__inventoryFilterSwapped === true")
            expect(page.get_by_text("Agua 50cl")).to_be_visible()
            sync_values = page.locator(
                '[hx-target="#inventory-workspace"]'
            ).evaluate_all(
                """elements => elements.map((element) =>
                  element.closest("#inventory-workspace")?.getAttribute("hx-sync"))"""
            )
            self.assertTrue(sync_values)
            self.assertTrue(
                all(value == "#inventory-workspace:replace" for value in sync_values)
            )
            page.evaluate(
                """() => {
                  window.__inventoryWorkspaceSwapped = false;
                  document.body.addEventListener("htmx:afterSwap", (event) => {
                    if (event.detail.target?.id === "inventory-workspace") {
                      window.__inventoryWorkspaceSwapped = true;
                    }
                  });
                }"""
            )
            with page.expect_response(
                lambda response: (
                    "/inventory/" in response.url and "store=all" in response.url
                )
            ) as response_info:
                page.get_by_label("Ámbito de tienda").select_option("all")
            response = response_info.value
            self.assertEqual(response.status, 200)
            body = response.text()
            self.assertIn('id="inventory-workspace"', body)
            self.assertIn("Todas las tiendas", body)
            self.assertIn('scope="col">Tienda', body)
            self.assertIn("Centro", body)
            self.assertIn("Norte", body)
            expect(page).to_have_url(re.compile(r"store=all"))
            page.wait_for_function("window.__inventoryWorkspaceSwapped === true")
            self.assertEqual(page.locator("#inventory-workspace").count(), 1)
            expect(
                page.locator("#inventory-workspace th", has_text="Tienda")
            ).to_be_visible()
            expect(page.get_by_role("columnheader", name="Tienda")).to_be_visible()
            expect(page.get_by_label("Ámbito de tienda")).to_have_value("all")
            expect(
                page.locator("#inventory-workspace .inventory-header > div > p")
            ).to_have_text("Todas las tiendas")
            expect(page.get_by_role("cell", name="Centro")).to_be_visible()
            expect(page.get_by_role("cell", name="Norte")).to_be_visible()
            page.go_back()
            expect(page).to_have_url(re.compile(rf"store={store.pk}"))
            expect(page.get_by_label("Ámbito de tienda")).to_have_value(str(store.pk))
            expect(page.get_by_role("columnheader", name="Tienda")).to_have_count(0)
            expect(
                page.locator("#inventory-workspace tbody a", has_text="Agua 50cl")
            ).to_have_count(1)
            expect(page.get_by_role("cell", name="Norte")).to_have_count(0)
            page.go_forward()
            expect(page).to_have_url(re.compile(r"store=all"))
            expect(page.get_by_label("Ámbito de tienda")).to_have_value("all")
            expect(page.get_by_label("Buscar producto o SKU")).to_have_value("AG-001")
            expect(page.get_by_role("columnheader", name="Tienda")).to_be_visible()
            expect(page.get_by_role("cell", name="Centro")).to_be_visible()
            expect(page.get_by_role("cell", name="Norte")).to_be_visible()
            expect(
                page.locator("#inventory-workspace tbody a", has_text="Agua 50cl")
            ).to_have_count(2)
            page.get_by_text("Agua 50cl").first.click()
            page.get_by_role("tab", name="Movimientos").click()
            page.get_by_role("tab", name="Ajustes").click()
            page.get_by_role("tab", name="Resumen").click()
            page.get_by_role("link", name="Ajustar stock").click()
            page.get_by_label("Stock contado físicamente").fill("6")
            expect(page.locator("#difference-preview")).to_have_text("+3.000")
            page.get_by_role("button", name="Preparar ajuste").click()
            expect(page.get_by_text("El stock todavía no ha cambiado.")).to_be_visible()
            expect(page.get_by_text("Confirmar modificará el stock")).to_be_visible()
            page.get_by_label(
                "Confirmo que quiero aplicar este ajuste de stock"
            ).check()
            page.get_by_role("button", name="Confirmar ajuste").click()
            expect(page.get_by_text("Confirmado", exact=True)).to_be_visible()
            expect(page.get_by_role("link", name="Añadir producto")).to_have_count(0)
            browser.close()

        item.refresh_from_db()
        movement = StockMovement.objects.select_related(
            "stock_adjustment_line__adjustment"
        ).get(inventory_item=item)
        adjustment = movement.stock_adjustment_line.adjustment
        adjustment_detail_url = reverse(
            "inventory:stock_adjustment_detail", kwargs={"pk": adjustment.pk}
        )
        movement_detail_url = reverse(
            "inventory:stock_movement_detail", kwargs={"pk": movement.pk}
        )
        self.assertEqual(item.current_stock, Decimal("6"))
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_CONFIRMED)
        self.assertEqual(movement.movement_type, StockMovement.TYPE_ADJUSTMENT_IN)
        self.assertEqual(movement.stock_before, Decimal("3"))
        self.assertEqual(movement.stock_after, Decimal("6"))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login(page, owner)
            page.goto(
                f"{self.live_server_url}/inventory/?store={store.pk}&tab=movements"
            )
            expect(page.get_by_text("+3,000")).to_be_visible()
            expect(page.get_by_text("3,000 → 6,000")).to_be_visible()
            origin_link = page.get_by_role(
                "link", name=f"Ajuste {adjustment.code}", exact=True
            )
            expect(origin_link).to_be_visible()
            expect(origin_link).to_have_attribute("href", adjustment_detail_url)
            origin_link.click()
            expect(page.get_by_role("heading", name=adjustment.code)).to_be_visible()
            expect(page.get_by_text("Confirmado", exact=True)).to_be_visible()
            expect(page.get_by_text(product.name, exact=True)).to_be_visible()
            page.go_back()
            movement_link = page.locator(f'a[href="{movement_detail_url}"]')
            expect(movement_link).to_be_visible()
            movement_link.click()
            expect(page.get_by_text("Stock anterior", exact=True)).to_be_visible()
            expect(page.get_by_text("Stock posterior", exact=True)).to_be_visible()
            expect(page.get_by_text("Cambio", exact=True)).to_be_visible()
            expect(page.get_by_text("Origen", exact=True)).to_be_visible()
            expect(page.get_by_text("Usuario", exact=True)).to_be_visible()
            expect(page.get_by_role("heading", name=product.name)).to_be_visible()
            expect(
                page.locator(".page-heading > div > p:not(.erp-eyebrow)")
            ).to_have_text(store.name)
            expect(page.locator('dt:has-text("Stock anterior") + dd')).to_have_text(
                "3,000"
            )
            expect(page.locator('dt:has-text("Stock posterior") + dd')).to_have_text(
                "6,000"
            )
            for width, height in ((1440, 900), (900, 900), (375, 812)):
                page.set_viewport_size({"width": width, "height": height})
                if width == 375:
                    page.goto(f"{self.live_server_url}/inventory/?store={store.pk}")
                    filters = page.get_by_role("button", name="Filtros")
                    expect(filters).to_be_visible()
                    filters.click()
                    expect(page.get_by_role("dialog")).to_be_visible()
                    page.get_by_label("Buscar producto o SKU").fill("NO-RESULT")
                    with page.expect_response(
                        lambda response: (
                            "/inventory/" in response.url
                            and "search=NO-RESULT" in response.url
                        )
                    ):
                        page.get_by_role("button", name="Filtrar").click()
                    expect(page).to_have_url(re.compile(r"search=NO-RESULT"))
                    expect(
                        page.get_by_text("No hay resultados con estos filtros.")
                    ).to_be_visible()
                    expect(page.get_by_role("dialog")).not_to_be_visible()
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"),
                    page.evaluate("document.documentElement.clientWidth"),
                )
            browser.close()

    def test_initial_stock_flow(self):
        business = create_business("Initial Browser", "initial-browser")
        store = create_inventory_store(business=business, name="Centro", code="INITIAL")
        owner = create_inventory_owner(business=business, password=self.password)
        product = create_inventory_product(business=business, name="Producto nuevo")
        item = create_inventory_item(
            business=business,
            store=store,
            product=product,
            current_stock=Decimal("0"),
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login(page, owner)
            page.goto(f"{self.live_server_url}/inventory/items/{item.pk}/")
            page.get_by_role("link", name="Cargar stock inicial").click()
            page.get_by_label("Cantidad inicial").fill("48")
            page.get_by_label("Motivo").fill("Apertura")
            page.get_by_role("button", name="Cargar stock inicial").click()
            expect(
                page.get_by_text("Stock inicial cargado correctamente.")
            ).to_be_visible()
            expect(page.get_by_role("link", name="Cargar stock inicial")).to_have_count(
                0
            )
            browser.close()

        item.refresh_from_db()
        movement = StockMovement.objects.get(inventory_item=item)
        self.assertEqual(item.current_stock, Decimal("48"))
        self.assertEqual(movement.movement_type, StockMovement.TYPE_INITIAL)

    def test_stale_stock_full_page_conflict(self):
        business = create_business("Conflict Browser", "conflict-browser")
        store = create_inventory_store(
            business=business, name="Centro", code="CONFLICT"
        )
        owner = create_inventory_owner(business=business, password=self.password)
        product = create_inventory_product(business=business, name="Producto conflicto")
        item = create_inventory_item(
            business=business,
            store=store,
            product=product,
            current_stock=Decimal("10"),
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login(page, owner)
            page.goto(f"{self.live_server_url}/inventory/items/{item.pk}/adjust/")
            page.get_by_label("Stock contado físicamente").fill("12")
            page.get_by_role("button", name="Preparar ajuste").click()
            expect(page.get_by_text("Confirmar modificará el stock")).to_be_visible()
            review_url = page.url
            browser.close()

        adjustment = StockAdjustment.objects.get(business=business)
        increase_stock(
            inventory_item=item,
            quantity=Decimal("2"),
            movement_type=StockMovement.TYPE_ADJUSTMENT_IN,
            user=owner,
            reason="Operación concurrente real",
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login(page, owner)
            page.goto(review_url)
            page.get_by_label(
                "Confirmo que quiero aplicar este ajuste de stock"
            ).check()
            with page.expect_response(
                lambda response: response.status == 409 and "/confirm/" in response.url
            ):
                page.get_by_role("button", name="Confirmar ajuste").click()
            expect(
                page.get_by_role(
                    "heading",
                    name="El stock ha cambiado desde que preparaste este ajuste.",
                )
            ).to_be_visible()
            expect(page.get_by_text("preparado con 10,000")).to_be_visible()
            expect(page.get_by_text("stock actual 12,000")).to_be_visible()
            expect(page.locator("[data-app-shell]")).to_be_visible()
            browser.close()

        item.refresh_from_db()
        adjustment.refresh_from_db()
        self.assertEqual(item.current_stock, Decimal("12"))
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_DRAFT)
        self.assertEqual(
            StockMovement.objects.filter(inventory_item=item).count(),
            1,
        )
