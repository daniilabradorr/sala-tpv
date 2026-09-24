"""Browser coverage for the FE-16 customer workspace and TPV quick create."""

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.customers.tests.factories import create_account
from apps.sales.services import open_sale
from apps.sales.tests.factories import create_pos_settings
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_store, create_user


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class CustomerBrowserTests(StaticLiveServerTestCase):
    password = "Customers-E2E-123!"

    def test_workspace_mobile_drawer_tabs_and_tpv_quick_create(self):
        business = create_business(name="Customers Browser", slug="customers-browser")
        owner = create_user(
            business=business,
            email="owner@customers.test",
            password=self.password,
            role=RoleChoices.OWNER,
        )
        store = create_store(business=business, name="Centro", code="CENTRO")
        create_pos_settings(business=business, require_open_cash_register=False)
        account = create_account(business=business)
        account.customer.name = "Ana Browser"
        account.customer.save()
        sale = open_sale(business=business, store=store, opened_by=owner)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 375, "height": 812})
            page.goto(f"{self.live_server_url}/users/login/")
            page.get_by_label("Correo electrónico").fill(owner.email)
            page.get_by_label("Contraseña").fill(self.password)
            page.get_by_role("button", name="Iniciar sesión").click()
            page.goto(f"{self.live_server_url}/customers/")
            expect(page.locator(".customer-cards")).to_be_visible()
            page.get_by_role("button", name="Filtros").click()
            expect(page.locator("#customer-filters")).to_have_attribute("open", "")
            page.get_by_role("button", name="Cerrar filtros").click()
            page.get_by_text("Ana Browser").first.click()
            page.get_by_role("tab", name="Cuenta").click()
            expect(page.get_by_role("tab", name="Cuenta")).to_have_attribute(
                "aria-selected", "true"
            )
            self.assertTrue(
                page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            )

            page.goto(
                f"{self.live_server_url}/sales/stores/{store.pk}/sales/{sale.pk}/"
            )
            page.get_by_role("button", name="Nuevo cliente").click()
            expect(page.get_by_role("heading", name="Nuevo cliente")).to_be_visible()
            page.get_by_label("Nombre").fill("Cliente E2E rápido")
            page.get_by_role("button", name="Crear y seleccionar").click()
            expect(page.get_by_text("Cliente E2E rápido")).to_be_visible()
            browser.close()
