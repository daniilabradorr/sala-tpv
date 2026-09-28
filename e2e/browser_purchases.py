"""Browser smoke coverage for the FE-17 purchases workspace."""

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.core.models import Business
from apps.purchases.models import Supplier
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

    def test_purchase_and_supplier_workspaces_are_responsive(self):
        business = Business.objects.create(
            name="Purchases browser", slug="purchases-browser"
        )
        owner = create_user(
            business=business,
            email="owner@purchases.test",
            password=self.password,
            role=RoleChoices.OWNER,
        )
        Store.objects.create(
            business=business, name="Centro", code="CENTRO", is_default=True
        )
        Supplier.objects.create(business=business, name="Proveedor Browser")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width in (375, 767, 768):
                page = browser.new_page(viewport={"width": width, "height": 812})
                page.goto(f"{self.live_server_url}/users/login/")
                page.get_by_label("Correo electrónico").fill(owner.email)
                page.get_by_label("Contraseña").fill(self.password)
                page.get_by_role("button", name="Iniciar sesión").click()
                page.goto(f"{self.live_server_url}/purchases/")
                expect(page.get_by_role("heading", name="Compras")).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                page.get_by_role("link", name="Proveedores", exact=True).click()
                expect(
                    page.get_by_text("Proveedor Browser", exact=True)
                ).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                page.close()
            browser.close()
