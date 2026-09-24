"""Browser coverage for the FE-15 catalog workspace."""

from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.catalog.tests.factories import create_category, create_product, create_tax
from apps.inventory.tests.factories import create_inventory_item
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_store, create_user


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class CatalogBrowserTests(StaticLiveServerTestCase):
    password = "Catalog-E2E-123!"

    def test_catalog_navigation_filters_inventory_and_mobile(self):
        business = create_business(name="Catalog Browser", slug="catalog-browser")
        owner = create_user(
            business=business,
            email="owner@catalog-browser.test",
            password=self.password,
            role=RoleChoices.OWNER,
        )
        store = create_store(business=business, name="Centro", code="CENTRO")
        category = create_category(business=business, name="Bebidas")
        child = create_category(
            business=business,
            name="Refrescos",
            slug="refrescos",
            parent=category,
            sort_order=1,
        )
        tax = create_tax(business=business, name="IVA 21%", is_default=True)
        product = create_product(
            business=business,
            category=child,
            tax=tax,
            name="Cola E2E",
            sku="COLA-E2E",
            track_stock=True,
        )
        create_inventory_item(
            business=business,
            store=store,
            product=product,
            current_stock=Decimal("8"),
            reserved_stock=Decimal("2"),
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{self.live_server_url}/users/login/")
            page.get_by_label("Correo electrónico").fill(owner.email)
            page.get_by_label("Contraseña").fill(self.password)
            page.get_by_role("button", name="Iniciar sesión").click()
            page.goto(f"{self.live_server_url}/catalog/products/")
            expect(
                page.get_by_role("navigation", name="Secciones del catálogo")
            ).to_be_visible()
            page.get_by_label("Buscar productos").fill("COLA-E2E")
            expect(page.get_by_text("Cola E2E").first).to_be_visible()
            page.get_by_text("Cola E2E").first.click()
            expect(page.get_by_role("heading", name="Inventario")).to_be_visible()
            expect(page.get_by_role("cell", name="Centro")).to_be_visible()
            expect(page.get_by_role("cell", name="6.000")).to_be_visible()
            page.get_by_role("link", name="Categorías").click()
            expect(page.get_by_text("Refrescos").first).to_be_visible()
            page.get_by_role("link", name="Impuestos").click()
            expect(page.get_by_text("Predeterminado").first).to_be_visible()

            page.set_viewport_size({"width": 375, "height": 812})
            page.goto(f"{self.live_server_url}/catalog/products/")
            expect(page.locator(".catalog-mobile-list")).to_be_visible()
            self.assertEqual(
                page.evaluate("document.documentElement.scrollWidth <= innerWidth"),
                True,
            )
            browser.close()
