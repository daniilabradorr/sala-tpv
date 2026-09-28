"""Browser coverage for the FE-16 customer workspace and TPV quick create."""

import re
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.customers.tests.factories import create_account
from apps.sales.services import open_sale
from apps.sales.tests.factories import create_pos_settings
from apps.sales.tests.factories import create_sale
from apps.sales.models import SaleStatusChoices
from apps.payments.services import register_sale_on_account
from apps.payments.models import PaymentMethod
from apps.cash_register.models import CashRegister, CashSession
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
        debt_sale = create_sale(
            business=business,
            store=store,
            opened_by=owner,
            customer=account.customer,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("100.00"),
        )
        register_sale_on_account(business=business, sale_id=debt_sale.pk, user=owner)
        method = PaymentMethod.objects.create(
            business=business, name="Tarjeta E2E", code="card"
        )
        register = CashRegister.objects.create(
            business=business, store=store, name="Caja E2E", code="E2E"
        )
        cash_session = CashSession.objects.create(
            business=business,
            store=store,
            cash_register=register,
            opened_by=owner,
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 375, "height": 812})
            page.goto(f"{self.live_server_url}/users/login/")
            page.get_by_label("Correo electrónico").fill(owner.email)
            page.get_by_label("Contraseña").fill(self.password)
            page.get_by_role("button", name="Iniciar sesión").click()
            page.goto(f"{self.live_server_url}/customers/")
            expect(page.locator(".customer-cards")).to_be_visible()
            customer_actions = page.locator(".customer-cards").get_by_role(
                "button", name="Acciones para Ana Browser", exact=True
            )
            expect(customer_actions).to_be_visible()
            customer_actions.click()
            actions_drawer = page.locator(f"#customer-actions-{account.customer_id}")
            expect(actions_drawer).to_have_attribute("open", "")
            expect(actions_drawer).to_be_visible()
            expect(actions_drawer.get_by_role("link", name="Editar")).to_be_visible()
            expect(
                actions_drawer.get_by_role("button", name="Desactivar")
            ).to_be_visible()
            actions_drawer.get_by_role("button", name="Cerrar acciones").click()
            page.get_by_role("button", name="Filtros").click()
            expect(page.locator("#customer-filters")).to_have_attribute("open", "")
            page.get_by_role("button", name="Cerrar filtros").click()
            page.set_viewport_size({"width": 767, "height": 812})
            expect(page.locator(".customer-cards")).to_be_visible()
            self.assertTrue(
                page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            )
            page.set_viewport_size({"width": 768, "height": 812})
            expect(page.locator(".customer-cards")).to_be_hidden()
            expect(page.locator(".customer-table")).to_be_visible()
            page.set_viewport_size({"width": 375, "height": 812})
            page.locator(".customer-cards").get_by_role(
                "link", name="Ana Browser", exact=False
            ).click()
            detail_actions = page.get_by_role(
                "button", name="Más acciones para Ana Browser", exact=True
            )
            expect(detail_actions).to_be_visible()
            detail_actions.click()
            detail_drawer = page.locator("#customer-detail-actions")
            expect(detail_drawer).to_have_attribute("open", "")
            expect(
                detail_drawer.get_by_role("button", name="Desactivar")
            ).to_be_visible()
            detail_drawer.get_by_role("button", name="Cerrar acciones").click()
            self.assertTrue(
                page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            )
            page.get_by_role("tab", name="Cuenta").click()
            expect(page.get_by_role("tab", name="Cuenta")).to_have_attribute(
                "aria-selected", "true"
            )
            expect(page.get_by_text("Pendiente: 100,00 €")).to_be_visible()
            page.get_by_role("link", name="Cobrar esta venta").click()
            page.locator('[name="amount"]').fill("30.00")
            page.locator('[name="method"]').select_option(str(method.pk))
            page.locator('[name="cash_session"]').select_option(str(cash_session.pk))
            page.get_by_role("button", name="Cobrar").click()
            expect(page).to_have_url(
                re.compile(rf"/customers/{account.customer_id}/\?tab=account$")
            )
            expect(page.get_by_text("Debe 70,00 €")).to_be_visible()
            expect(page.get_by_text("Pendiente: 70,00 €")).to_be_visible()
            expect(page.get_by_text("Pago #")).to_be_visible()
            self.assertTrue(
                page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            )

            page.goto(
                f"{self.live_server_url}/sales/stores/{store.pk}/sales/{sale.pk}/"
            )
            page.get_by_role("button", name="Nuevo cliente").click()
            expect(page.get_by_role("heading", name="Nuevo cliente")).to_be_visible()
            quick_customer = page.locator("#quick-customer-panel")
            quick_customer.locator('input[name="name"]').fill("Cliente E2E rápido")
            page.get_by_role("button", name="Crear y seleccionar").click()
            customer_select = page.locator('#workspace-header select[name="customer"]')
            expect(customer_select.locator("option:checked")).to_have_text(
                "Cliente E2E rápido"
            )
            expect(
                page.locator(
                    '#workspace-header input[name="customer_mode"][value="customer"]'
                )
            ).to_be_checked()
            browser.close()
