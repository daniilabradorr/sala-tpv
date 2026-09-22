"""Real Chromium coverage for the FE-09 sales history surface."""

import re
import uuid
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from apps.billing.models import (
    BillingDocument,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingSeries,
)
from apps.cash_register.models import CashSession
from apps.onboarding.services import OnboardingService
from apps.payments.models import (
    Payment,
    PaymentMethodCodeChoices,
    PaymentStatusChoices,
)
from apps.sales.models import SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sales_product,
)


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserSalesHistoryTests(StaticLiveServerTestCase):
    email = "sales-history.e2e@example.com"
    password = "E2E-Sales-History-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Histórico E2E SL",
            trade_name="Histórico E2E",
            tax_identifier="B87654321",
            phone="923111111",
            email="history-business@example.com",
            address_line_1="Calle Historia 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro Histórico E2E",
            owner_first_name="Ana",
            owner_last_name="Historia",
            owner_email=self.email,
            owner_phone="600000000",
            owner_password=self.password,
            owner_pin="1234",
        )
        product = create_sales_product(
            business=result.business,
            name="Producto snapshot E2E",
            base_price=Decimal("10.00"),
        )
        sale = create_sale(
            business=result.business,
            store=result.store,
            opened_by=result.owner,
            status=SaleStatusChoices.COMPLETED,
        )
        create_sale_line(
            business=result.business,
            sale=sale,
            product=product,
            unit_base_price=Decimal("10.00"),
        )
        method = next(
            method
            for method in result.payment_methods
            if method.code == PaymentMethodCodeChoices.CARD
        )
        self.payment_method_name = method.name
        cash_session = CashSession.objects.create(
            business=result.business,
            store=result.store,
            cash_register=result.cash_register,
            opened_by=result.owner,
        )
        Payment.objects.create(
            business=result.business,
            store=result.store,
            sale=sale,
            method=method,
            cash_session=cash_session,
            amount=sale.total_amount,
            status=PaymentStatusChoices.COMPLETED,
            processed_by=result.owner,
            idempotency_key=uuid.uuid4(),
        )
        series = BillingSeries.objects.create(
            business=result.business,
            store=result.store,
            name="Serie E2E",
            document_type=BillingDocumentTypeChoices.F2,
            prefix="E2E",
            year=timezone.localdate().year,
        )
        self.document = BillingDocument.objects.create(
            business=result.business,
            store=result.store,
            sale=sale,
            series=series,
            issued_by=result.owner,
            series_text="E2E/2026",
            number=1,
            document_type=BillingDocumentTypeChoices.F2,
            status=BillingDocumentStatusChoices.ISSUED,
            issued_at=timezone.now(),
            operation_date=timezone.localdate(),
            idempotency_key=uuid.uuid4(),
            idempotency_fingerprint="b" * 64,
            description="Venta E2E",
            issuer_legal_name="Histórico E2E SL",
            issuer_tax_identifier="B87654321",
            issuer_address_line_1="Calle Historia 1",
            issuer_postal_code="37001",
            issuer_city="Salamanca",
            issuer_province="Salamanca",
            issuer_country_code="ES",
            subtotal_amount=sale.subtotal_amount,
            discount_amount=sale.discount_amount,
            tax_amount=sale.tax_amount,
            total_amount=sale.total_amount,
        )

    def test_history_htmx_detail_and_responsive_layout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport in (
                    {"width": 1440, "height": 900},
                    {"width": 900, "height": 900},
                    {"width": 375, "height": 812},
                ):
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(f"{self.live_server_url}/users/login/")
                        page.get_by_label("Correo electrónico").fill(self.email)
                        page.get_by_label("Contraseña").fill(self.password)
                        page.get_by_role("button", name="Iniciar sesión").click()
                        page.wait_for_url(f"{self.live_server_url}/")
                        sidebar = page.locator("#app-sidebar")
                        sales_link = sidebar.get_by_role(
                            "link", name="Ventas", exact=True
                        )
                        sidebar_toggle = page.locator("[data-sidebar-toggle]")
                        if sidebar_toggle.is_visible():
                            expect(sidebar).to_have_attribute("inert", "")
                            sidebar_toggle.click()
                            expect(sidebar_toggle).to_have_attribute(
                                "aria-expanded", "true"
                            )
                            expect(sidebar).not_to_have_attribute("inert", "")
                            expect(sales_link).to_be_visible()
                        sales_link.click()

                        shell = page.locator("[data-app-shell]")
                        expect(shell).to_be_visible()
                        shell.evaluate(
                            "element => element.dataset.historyShell = 'stable'"
                        )
                        expect(
                            page.get_by_role("heading", name="Ventas")
                        ).to_be_visible()
                        page.get_by_role("link", name="7 días", exact=True).click()
                        expect(page).to_have_url(re.compile(r"[?&]period=7d(?:&|$)"))
                        expect(
                            page.locator('[data-history-shell="stable"]')
                        ).to_have_count(1)
                        expect(page.locator("#sales-history-content")).to_have_count(1)

                        status_select = page.locator("#id_status")
                        status_select.select_option("completed")
                        expect(status_select).to_have_value("completed")
                        page.get_by_role("button", name="Aplicar filtros").click()
                        expect(page).to_have_url(re.compile(r"[?&]period=7d(?:&|$)"))
                        expect(page).to_have_url(
                            re.compile(r"[?&]status=completed(?:&|$)")
                        )

                        if viewport["width"] <= 767:
                            expect(page.locator(".sales-table-wrap")).to_be_hidden()
                            expect(page.locator(".sales-table")).to_be_hidden()
                            expect(page.locator(".sale-mobile-card")).to_be_visible()
                            page.locator(".sale-mobile-card").first.click()
                        else:
                            expect(page.locator(".sales-table")).to_be_visible()
                            page.locator(".sales-table tbody a").first.click()
                        expect(
                            page.get_by_text("Producto snapshot E2E")
                        ).to_be_visible()
                        payments_section = page.locator(
                            'section[aria-labelledby="payments-title"]'
                        )
                        expect(
                            payments_section.get_by_text(
                                self.payment_method_name, exact=True
                            )
                        ).to_be_visible()
                        document_link = page.get_by_role(
                            "link", name=re.compile(r"Factura simplificada.*000001")
                        )
                        expect(document_link).to_be_visible()
                        expect(document_link).to_have_attribute(
                            "href", re.compile(rf"/{self.document.pk}/")
                        )
                        page.go_back()
                        expect(page).to_have_url(re.compile(r"[?&]period=7d(?:&|$)"))
                        expect(page).to_have_url(
                            re.compile(r"[?&]status=completed(?:&|$)")
                        )
                        page.go_forward()
                        expect(
                            page.get_by_text("Producto snapshot E2E")
                        ).to_be_visible()
                        page.go_back()
                        expect(page).to_have_url(re.compile(r"[?&]period=7d(?:&|$)"))
                        expect(page).to_have_url(
                            re.compile(r"[?&]status=completed(?:&|$)")
                        )
                        expect(page.locator("#sales-history-content")).to_be_visible()
                        if viewport["width"] <= 767:
                            self.assertTrue(
                                page.evaluate(
                                    "window.matchMedia('(max-width: 767px)').matches"
                                )
                            )
                            expect(page.locator(".sales-mobile-list")).to_be_visible()
                            expect(
                                page.locator(".sale-mobile-card").first
                            ).to_be_visible()
                            expect(page.locator(".sales-table-wrap")).to_be_hidden()
                            expect(page.locator(".sales-table")).to_be_hidden()
                            self.assertEqual(
                                page.locator(".sales-table-wrap").evaluate(
                                    "element => getComputedStyle(element).display"
                                ),
                                "none",
                            )
                        else:
                            expect(page.locator(".sales-table-wrap")).to_be_visible()
                            expect(page.locator(".sales-table")).to_be_visible()
                        self.assertEqual(errors, [])
                        overflow = page.evaluate(
                            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                        )
                        offenders = []
                        if overflow:
                            offenders = page.evaluate(
                                """() => {
                                    const width = document.documentElement.clientWidth;
                                    return [...document.querySelectorAll("body *")]
                                        .map((element) => {
                                            const rect = element.getBoundingClientRect();
                                            return {
                                                tag: element.tagName,
                                                cls: String(element.className),
                                                id: element.id,
                                                left: rect.left,
                                                right: rect.right,
                                                width: rect.width,
                                            };
                                        })
                                        .filter((item) => item.right > width + 1 || item.left < -1);
                                }"""
                            )
                        self.assertFalse(
                            overflow, f"Horizontal overflow elements: {offenders}"
                        )
                        context.close()
            finally:
                browser.close()
