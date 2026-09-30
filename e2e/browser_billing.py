"""Real Chromium coverage for the FE-18 Billing workspace."""

import re
import uuid

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from apps.billing.models import BillingDocumentTypeChoices, BillingSeries
from apps.billing.services import issue_sale_document
from apps.onboarding.services import OnboardingService
from apps.sales.models import SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sales_customer,
    create_sales_product,
    create_sales_tax,
)


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserBillingTests(StaticLiveServerTestCase):
    email = "billing.e2e@example.com"
    password = "E2E-Billing-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Facturación E2E SL",
            trade_name="Facturación E2E",
            tax_identifier="B11223344",
            phone="923111111",
            email="billing-business@example.com",
            address_line_1="Calle Fiscal 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Billing E2E",
            owner_first_name="Ana",
            owner_last_name="Fiscal",
            owner_email=self.email,
            owner_phone="600000000",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.store_id = result.store.pk
        customer = create_sales_customer(
            business=result.business,
            name="Cliente snapshot E2E",
            legal_name="Cliente Fiscal Snapshot SL",
            tax_identifier="B55667788",
        )
        tax = create_sales_tax(business=result.business, rate="21.00")
        product = create_sales_product(
            business=result.business,
            tax=tax,
            name="Producto fiscal snapshot",
            base_price="10.00",
        )
        sale = create_sale(
            business=result.business,
            store=result.store,
            opened_by=result.owner,
            customer=customer,
            status=SaleStatusChoices.COMPLETED,
        )
        create_sale_line(
            business=result.business,
            sale=sale,
            product=product,
            unit_base_price="10.00",
        )
        f2_series = BillingSeries.objects.create(
            business=result.business,
            store=result.store,
            name="Tickets E2E",
            document_type=BillingDocumentTypeChoices.F2,
            prefix="TICKET-E2E",
            year=timezone.localdate().year,
            padding=5,
        )
        BillingSeries.objects.create(
            business=result.business,
            store=result.store,
            name="Sustitutivas E2E",
            document_type=BillingDocumentTypeChoices.F3,
            prefix="F3-E2E",
            year=timezone.localdate().year,
            padding=5,
        )
        document = issue_sale_document(
            business=result.business,
            sale_id=sale.pk,
            series_id=f2_series.pk,
            issued_by=result.owner,
            idempotency_key=uuid.uuid4(),
        )
        product.name = "Producto actual modificado"
        product.save()
        tax.rate = "10.00"
        tax.save()
        self.document_number = document.full_number
        self.document_id = document.pk
        self.customer_id = customer.pk
        self.operation_date = str(document.operation_date)

    def login(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_url(f"{self.live_server_url}/")

    def install_workspace_settle_counter(self, page):
        page.evaluate(
            """() => {
                window.__billingWorkspaceSettledCount = 0;
                document.body.addEventListener("htmx:afterSettle", (event) => {
                    if (event.detail.target?.id === "billing-document-workspace") {
                        window.__billingWorkspaceSettledCount += 1;
                    }
                });
            }"""
        )

    def open_workspace_tab(self, page, tab):
        settled_count = page.evaluate("window.__billingWorkspaceSettledCount")
        page.get_by_role("link", name=tab, exact=True).click()
        page.wait_for_function(
            "previous => window.__billingWorkspaceSettledCount > previous",
            arg=settled_count,
        )

    def test_series_workspace_create_edit_and_responsive(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 375, "height": 812})
                self.login(page)
                page.goto(
                    f"{self.live_server_url}/billing/stores/{self.store_id}/series/"
                )
                expect(
                    page.get_by_role("heading", name="Series de facturación")
                ).to_be_visible()
                page.get_by_role("link", name="Nueva serie").click()
                page.get_by_label("Tipo de documento").select_option("F1")
                page.get_by_label("Nombre").fill("Serie completa E2E")
                page.get_by_label("Prefijo").fill("E2E-F1")
                page.get_by_label("Dígitos").fill("5")
                page.get_by_role("button", name="Guardar serie").click()
                expect(page.get_by_text("Último número emitido")).to_be_visible()
                expect(page.get_by_text("Siguiente número previsto")).to_be_visible()
                expect(page.locator("#billing-series-results")).to_have_count(0)
                page.get_by_role("link", name="Editar").click()
                page.get_by_label("Nombre").fill("Serie completa editada")
                page.get_by_label("Prefijo").fill("E2E-F1-EDIT")
                page.get_by_label("Dígitos").fill("6")
                page.get_by_role("button", name="Guardar serie").click()
                expect(page.get_by_text("E2E-F1-EDIT")).to_be_visible()
                page.get_by_role("link", name="Series").click()
                page.get_by_role("link", name="TICKET-E2E").click()
                expect(page.get_by_text("Identidad fiscal protegida")).to_be_visible()
                expect(page.get_by_text("1", exact=True)).to_be_visible()
                expect(page.get_by_text("2", exact=True)).to_be_visible()
                page.get_by_role("link", name="Editar").click()
                expect(page.get_by_label("Nombre")).to_be_visible()
                expect(page.get_by_label("Prefijo")).to_have_count(0)
                expect(page.get_by_label("Dígitos")).to_have_count(0)
                page.get_by_label("Nombre").fill("Tickets usados editados")
                page.get_by_role("button", name="Guardar serie").click()
                page.get_by_role("button", name="Desactivar").click()
                expect(page.get_by_text("Inactiva", exact=True)).to_be_visible()
                page.get_by_role("button", name="Reactivar").click()
                expect(page.get_by_text("Activa", exact=True)).to_be_visible()
                series_url = (
                    f"{self.live_server_url}/billing/stores/{self.store_id}/series/"
                )
                for width in (375, 767, 768, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.goto(series_url)
                    if width < 768:
                        expect(page.locator(".billing-cards")).to_be_visible()
                        expect(page.locator(".billing-table")).to_be_hidden()
                    else:
                        expect(page.locator(".billing-table")).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
            finally:
                browser.close()

    def test_documents_filters_snapshot_tabs_substitution_and_responsive(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                self.login(page)
                documents_url = (
                    f"{self.live_server_url}/billing/stores/{self.store_id}/documents/"
                )
                page.goto(documents_url)
                billing_header = page.locator(".billing-page > .erp-header")
                expect(billing_header.locator(".erp-subtitle")).to_contain_text(
                    "Tienda Billing E2E"
                )
                filters = page.locator("#billing-document-filters")
                search = filters.get_by_role("textbox", name="Buscar", exact=True)
                with page.expect_response(
                    lambda response: (
                        "/billing/stores/" in response.url
                        and "/documents/" in response.url
                        and "q=" in response.url
                        and response.status == 200
                    )
                ):
                    search.fill(self.document_number)
                expect(
                    page.get_by_role("link", name=self.document_number, exact=True)
                ).to_be_visible()
                with page.expect_response(
                    lambda response: (
                        "/billing/stores/" in response.url
                        and "/documents/" in response.url
                        and "q=" in response.url
                        and response.status == 200
                    )
                ):
                    search.fill("Cliente Fiscal Snapshot")
                expect(
                    page.get_by_role("link", name=self.document_number, exact=True)
                ).to_be_visible()
                page.get_by_label("Tipo de documento").select_option("F2")
                page.get_by_label("Estado").select_option("issued")
                page.get_by_label("Desde").fill(self.operation_date)
                page.get_by_label("Hasta").fill(self.operation_date)
                page.get_by_role("link", name=self.document_number).click()
                expect(
                    page.locator(".billing-detail-header .status-issued")
                ).to_have_text("Emitido")
                expect(page.locator(".billing-total")).to_contain_text("10,00")
                self.install_workspace_settle_counter(page)
                for tab in ("Resumen", "Líneas", "Fiscal", "Relaciones", "Resumen"):
                    self.open_workspace_tab(page, tab)
                    expect(page.locator("#billing-document-workspace")).to_have_count(1)
                self.open_workspace_tab(page, "Líneas")
                expect(page.get_by_text("Producto fiscal snapshot")).to_be_visible()
                expect(page.get_by_text("Producto actual modificado")).to_have_count(0)
                self.open_workspace_tab(page, "Fiscal")
                expect(page.get_by_text("Facturación E2E SL")).to_be_visible()
                expect(page.get_by_text("IVA")).to_be_visible()
                self.open_workspace_tab(page, "Resumen")
                page.get_by_role("link", name="Sustituir por factura completa").click()
                expect(page.get_by_text(self.document_number)).to_be_visible()
                command_form = page.locator("#billing-command-form")
                customer = command_form.get_by_role(
                    "combobox", name="Cliente", exact=True
                )
                customer.select_option(str(self.customer_id))
                series_select = command_form.locator('select[name="series"]')
                if series_select.count():
                    series_select.select_option(index=1)
                else:
                    hidden_series = command_form.locator(
                        'input[type="hidden"][name="series"]'
                    )
                    expect(hidden_series).to_have_count(1)
                    expect(hidden_series).not_to_have_value("")
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and "/substitute/" in response.url
                    )
                ) as response_info:
                    page.get_by_role("button", name="Emitir factura completa").click()
                response = response_info.value
                self.assertEqual(response.status, 204)
                redirect = response.headers.get("hx-redirect")
                self.assertIsNotNone(redirect)
                self.assertRegex(redirect, r"/billing/stores/\d+/documents/\d+/$")
                page.wait_for_url(re.compile(r"/billing/stores/\d+/documents/\d+/$"))
                self.install_workspace_settle_counter(page)
                self.open_workspace_tab(page, "Relaciones")
                expect(page.get_by_text("Sustituye a")).to_be_visible()
                page.get_by_role("link", name=self.document_number).click()
                self.install_workspace_settle_counter(page)
                self.open_workspace_tab(page, "Relaciones")
                expect(page.get_by_text("Sustituida por")).to_be_visible()
                expect(page.locator("#billing-document-workspace")).to_have_count(1)

                for width in (375, 767, 768, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.goto(documents_url)
                    if width < 768:
                        expect(page.locator(".billing-cards")).to_be_visible()
                    else:
                        expect(page.locator(".billing-table")).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
            finally:
                browser.close()
