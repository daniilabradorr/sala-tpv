"""Real Chromium coverage for the FE-11 modal checkout."""

import re
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.billing.models import BillingDocument
from apps.cash_register.models import CashSession
from apps.catalog.models import Category
from apps.onboarding.services import OnboardingService
from apps.payments.models import Payment, PaymentStatusChoices
from apps.sales.models import PaymentStatusChoices as SalePaymentStatus
from apps.sales.models import Sale
from apps.sales.tests.factories import create_sales_inventory_item, create_sales_product


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserCheckoutTests(StaticLiveServerTestCase):
    email = "checkout.e2e@example.com"
    password = "E2E-Checkout-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Checkout E2E SL",
            trade_name="Checkout E2E",
            tax_identifier="B12345678",
            phone="923111111",
            email="checkout@e2e.test",
            address_line_1="Calle Caja 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Centro",
            owner_first_name="Eva",
            owner_last_name="Checkout",
            owner_email=self.email,
            owner_phone="600000000",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.result = result
        self.session = CashSession.objects.create(
            business=result.business,
            store=result.store,
            cash_register=result.cash_register,
            opened_by=result.owner,
        )
        category = Category.objects.create(
            business=result.business, name="Caja", is_active=True
        )
        product = create_sales_product(
            business=result.business,
            name="Producto checkout",
            sku="CHECKOUT-1",
            base_price=Decimal("10.90"),
            track_stock=True,
        )
        product.category = category
        product.save(update_fields=["category", "updated_at"])
        create_sales_inventory_item(
            business=result.business,
            store=result.store,
            product=product,
            current_stock=Decimal("50.000"),
        )
        self.store_id = result.store.pk
        self.session_id = self.session.pk

    def _login(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_url(f"{self.live_server_url}/")

    def _login_and_sale(self, page):
        self._login(page)
        page.goto(
            f"{self.live_server_url}/cash-register/stores/{self.store_id}/sessions/{self.session_id}/"
        )
        page.locator(".cash-session-header").get_by_role(
            "button", name="Nueva venta"
        ).click()
        expect(page.get_by_role("heading", name=re.compile(r"Venta #"))).to_be_visible()
        expect(page.get_by_role("button", name="Iniciar venta")).to_have_count(0)
        page.get_by_role("button", name=re.compile("Producto checkout")).click()

    def test_global_start_is_direct_responsive_and_safe_to_refresh_or_go_back(self):
        sale_ids = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width in (1440, 390):
                page = browser.new_page(viewport={"width": width, "height": 900})
                self._login(page)
                start = page.locator("main").get_by_role(
                    "button", name="Nueva venta", exact=True
                )
                expect(start).to_be_visible()
                if width == 1440:
                    # Two synchronous submit events represent one duplicated interaction.
                    start.evaluate(
                        "button => { const form = button.form; form.requestSubmit(); form.requestSubmit(); }"
                    )
                else:
                    start.click()
                expect(page).to_have_url(re.compile(r"/sales/stores/\d+/sales/\d+/$"))
                sale_id = int(re.search(r"/sales/(\d+)/$", page.url).group(1))
                sale_ids.append(sale_id)
                expect(page.locator("#product-search")).to_be_visible()
                expect(page.locator("#product-grid")).to_be_visible()
                expect(page.get_by_role("button", name="Iniciar venta")).to_have_count(
                    0
                )
                expect(page.locator("#workspace-header")).to_be_visible()
                page.wait_for_load_state("load")
                page.evaluate("document.fonts.ready")
                self.assertTrue(
                    page.evaluate(
                        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                    ),
                    f"Workspace overflow at viewport width {width}",
                )
                page.reload()
                expect(page).to_have_url(re.compile(rf"/sales/{sale_id}/$"))
                if width < 1200:
                    page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
                expect(page.locator("#sale-cart")).to_be_visible()
                page.go_back()
                expect(page).to_have_url(f"{self.live_server_url}/")
                expect(
                    page.locator("main").get_by_role(
                        "button", name="Nueva venta", exact=True
                    )
                ).to_be_enabled()
                page.close()
            browser.close()
        self.assertEqual(Sale.objects.count(), 2)
        for sale in Sale.objects.filter(pk__in=sale_ids):
            self.assertEqual(sale.cash_session_id, self.session_id)
            self.assertIsNone(sale.customer_id)
            self.assertEqual(sale.document_type_requested, "ticket")

    def test_palette_start_by_keyboard(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            self._login(page)
            page.keyboard.press("Control+k")
            page.locator("[data-command-input]").fill("Nueva venta")
            expect(
                page.locator("[data-command-dialog]").get_by_role(
                    "button", name="Nueva venta", exact=True
                )
            ).to_be_visible()
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            expect(page).to_have_url(re.compile(r"/sales/stores/\d+/sales/\d+/$"))
            expect(page.locator("#product-grid")).to_be_visible()
            browser.close()
        self.assertEqual(Sale.objects.count(), 1)

    def test_global_start_works_without_javascript(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                java_script_enabled=False, viewport={"width": 1440, "height": 900}
            )
            self._login(page)
            page.locator(".topbar-sale").click()
            expect(page).to_have_url(re.compile(r"/sales/stores/\d+/sales/\d+/$"))
            expect(page.locator("#product-grid")).to_be_visible()
            expect(page.locator("#sale-cart")).to_be_visible()
            browser.close()
        self.assertEqual(Sale.objects.count(), 1)

    def _open_checkout(self, page, width):
        if width < 1200:
            page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
        page.get_by_role("link", name=re.compile("COBRAR")).click()
        dialog = page.locator("#checkout-dialog")
        expect(dialog).to_have_attribute("open", "")
        expect(dialog.get_by_role("heading", name="COBRAR")).to_be_visible()
        return dialog

    def _pending_amount(self, dialog):
        raw_amount = dialog.locator("[data-checkout]").get_attribute("data-pending")
        self.assertIsNotNone(raw_amount)
        return Decimal(raw_amount.replace(",", "."))

    @staticmethod
    def _money(value):
        amount = value.quantize(Decimal("0.01"))
        return f"{amount:.2f}".replace(".", ",") + " €"

    def test_card_checkout_completes_with_dominant_new_sale_action(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login_and_sale(page)
            dialog = self._open_checkout(page, 1440)
            dialog.get_by_role("radio", name=re.compile("Tarjeta")).check()
            dialog.get_by_role("button", name=re.compile("CONFIRMAR COBRO")).click()
            expect(
                dialog.get_by_role("heading", name="VENTA COMPLETADA")
            ).to_be_visible()
            expect(dialog.get_by_role("button", name="NUEVA VENTA")).to_be_visible()
            expect(dialog.get_by_role("link", name="Ver documento")).to_be_visible()
            browser.close()
        self.assertEqual(Payment.objects.filter(method__code="card").count(), 1)
        payment = Payment.objects.get(method__code="card")
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        self.assertTrue(BillingDocument.objects.filter(sale=payment.sale).exists())

    def test_print_opens_fiscal_document_and_preserves_tpv(self):
        self._assert_checkout_print_flow()

    def _assert_checkout_print_flow(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_init_script(
                "window.printCalls = 0; window.print = () => { window.printCalls += 1; };"
            )
            page = context.new_page()
            self._login_and_sale(page)
            dialog = self._open_checkout(page, 1440)
            expect(
                dialog.get_by_role("link", name=re.compile("IMPRIMIR"))
            ).to_have_count(0)
            dialog.get_by_role("radio", name=re.compile("Tarjeta")).check()
            dialog.get_by_role("button", name=re.compile("CONFIRMAR COBRO")).click()
            expect(
                dialog.get_by_role("heading", name="VENTA COMPLETADA")
            ).to_be_visible()
            original_url = page.url
            preview = dialog.locator(".checkout-document-preview")
            expect(preview).to_contain_text("Checkout E2E SL")
            expect(preview).to_contain_text("Factura simplificada")
            expect(preview.locator("dd").nth(1)).to_have_text("1")
            for width in (375, 900, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                expect(preview).to_be_visible()
                self.assertTrue(
                    preview.evaluate(
                        "element => element.scrollWidth <= element.clientWidth"
                    )
                )
            page.evaluate("window.tpvPrintMarker = 'preserved'")
            panel_before = page.locator("#checkout-panel").inner_html()
            with page.expect_popup() as popup_info:
                dialog.get_by_role("link", name=re.compile("IMPRIMIR")).click()
            popup = popup_info.value
            popup.wait_for_load_state("load")
            popup.wait_for_function("window.printCalls === 1")
            self.assertIn("/print/?autoprint=1", popup.url)
            self.assertIsNone(popup.evaluate("window.opener"))
            expect(
                popup.get_by_role("heading", name="FACTURA SIMPLIFICADA")
            ).to_be_visible()
            expect(popup.locator(".app-sidebar, .app-topbar")).to_have_count(0)
            popup.emulate_media(media="print")
            expect(popup.locator(".document-print-controls")).not_to_be_visible()
            expect(popup.locator(".document-print")).to_be_visible()
            popup.emulate_media(media="screen")
            popup.get_by_role("button", name="IMPRIMIR").click()
            self.assertEqual(popup.evaluate("window.printCalls"), 2)
            popup.goto(popup.url.split("?")[0])
            self.assertEqual(popup.evaluate("window.printCalls"), 0)
            popup.get_by_role("button", name="IMPRIMIR").click()
            self.assertEqual(popup.evaluate("window.printCalls"), 1)
            popup.close()
            self.assertEqual(page.url, original_url)
            self.assertEqual(page.evaluate("window.tpvPrintMarker"), "preserved")
            self.assertEqual(page.locator("#checkout-panel").inner_html(), panel_before)
            expect(dialog).to_have_attribute("open", "")
            expect(dialog.get_by_role("button", name="NUEVA VENTA")).to_be_visible()
            browser.close()

    def test_cash_checkout_and_change_preview(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login_and_sale(page)
            dialog = self._open_checkout(page, 1440)
            pending = self._pending_amount(dialog)
            received = Decimal("20.00")
            dialog.get_by_role("radio", name=re.compile("Efectivo")).check()
            cash_received = dialog.get_by_label("Entregado por el cliente")
            cash_received.fill(f"{received:.2f}")
            expect(dialog.locator("[data-cash-change]")).to_have_text(
                self._money(received - pending)
            )
            dialog.get_by_role("button", name="EXACTO").click()
            expect(cash_received).to_have_value(f"{pending:.2f}")
            expect(dialog.locator("[data-cash-change]")).to_have_text("0,00 €")
            dialog.get_by_role("button", name=re.compile("CONFIRMAR COBRO")).click()
            expect(
                dialog.get_by_role("heading", name="VENTA COMPLETADA")
            ).to_be_visible()
            browser.close()
        payment = Payment.objects.get(method__code="cash")
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        self.assertTrue(BillingDocument.objects.filter(sale=payment.sale).exists())

    def test_split_checkout_creates_two_completed_payments(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login_and_sale(page)
            dialog = self._open_checkout(page, 1440)
            pending = self._pending_amount(dialog)
            first_amount = Decimal("5.00")
            second_amount = pending - first_amount
            dialog.get_by_role("radio", name="Pago dividido").check()
            parts = dialog.locator("[data-split-part]:visible")
            expect(parts).to_have_count(2)
            parts.nth(0).get_by_label("Método").select_option(label="Efectivo")
            parts.nth(0).get_by_label("Importe").fill(f"{first_amount:.2f}")
            parts.nth(0).get_by_label("Entregado (efectivo)").fill("10.00")
            parts.nth(1).get_by_label("Método").select_option(label="Tarjeta")
            parts.nth(1).get_by_label("Importe").fill(f"{second_amount:.2f}")
            expect(dialog.locator("[data-split-assigned]")).to_have_text(
                self._money(pending)
            )
            expect(dialog.locator("[data-split-remaining]")).to_have_text("0,00 €")
            dialog.get_by_role("button", name=re.compile("CONFIRMAR COBRO")).click()
            expect(
                dialog.get_by_role("heading", name="VENTA COMPLETADA")
            ).to_be_visible()
            browser.close()
        sale = Sale.objects.get()
        self.assertEqual(sale.pending_amount, Decimal("0.00"))
        self.assertEqual(sale.payment_status, SalePaymentStatus.PAID)
        payments = Payment.objects.filter(sale=sale)
        self.assertEqual(payments.count(), 2)
        self.assertEqual(
            set(payments.values_list("method__code", flat=True)), {"cash", "card"}
        )
        self.assertFalse(
            payments.exclude(status=PaymentStatusChoices.COMPLETED).exists()
        )
        self.assertTrue(BillingDocument.objects.filter(sale=sale).exists())

    def test_invalid_split_stays_open_and_preserves_idempotency_keys(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login_and_sale(page)
            dialog = self._open_checkout(page, 1440)
            dialog.get_by_role("radio", name="Pago dividido").check()
            parts = dialog.locator("[data-split-part]:visible")
            parts.nth(0).get_by_label("Método").select_option(label="Efectivo")
            parts.nth(0).get_by_label("Importe").fill("5.00")
            parts.nth(0).get_by_label("Entregado (efectivo)").fill("10.00")
            parts.nth(1).get_by_label("Método").select_option(label="Tarjeta")
            parts.nth(1).get_by_label("Importe").fill("4.00")
            dialog.locator("[data-add-part]").click()
            expect(parts).to_have_count(3)
            parts.nth(2).get_by_label("Método").select_option(label="Bizum")
            parts.nth(2).get_by_label("Importe").fill("1.00")
            keys_before = dialog.locator('[name$="idempotency_key"]').evaluate_all(
                "elements => elements.map(element => element.value)"
            )
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.status == 422
                    and "/checkout/" in response.url
                )
            ):
                dialog.get_by_role("button", name=re.compile("CONFIRMAR COBRO")).click()
            expect(dialog).to_have_attribute("open", "")
            expect(dialog.get_by_text("La suma de los pagos")).to_be_visible()
            expect(dialog.locator('[name="payments-0-amount"]')).to_have_value("5.00")
            expect(dialog.locator('[name="payments-1-amount"]')).to_have_value("4.00")
            expect(dialog.locator("[data-split-part]:visible")).to_have_count(3)
            expect(dialog.locator('[name="payments-2-amount"]')).to_have_value("1.00")
            expect(dialog.locator('[name="payments-2-DELETE"]')).not_to_be_checked()
            keys_after = dialog.locator('[name$="idempotency_key"]').evaluate_all(
                "elements => elements.map(element => element.value)"
            )
            self.assertEqual(keys_after, keys_before)
            browser.close()
        self.assertFalse(Payment.objects.exists())

    def test_checkout_responsive_escape_and_focus_contract(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for viewport in (
                {"width": 1440, "height": 900},
                {"width": 900, "height": 900},
                {"width": 375, "height": 812},
            ):
                with self.subTest(viewport=viewport):
                    page = browser.new_page(viewport=viewport)
                    self._login_and_sale(page)
                    dialog = self._open_checkout(page, viewport["width"])
                    expect(
                        dialog.get_by_role("radio", name=re.compile("Efectivo"))
                    ).to_be_visible()
                    dialog.get_by_role("radio", name=re.compile("Efectivo")).check()
                    expect(
                        dialog.get_by_label("Entregado por el cliente")
                    ).to_be_visible()
                    dialog.get_by_role("radio", name="Pago dividido").check()
                    expect(dialog.locator("[data-split-part]:visible")).to_have_count(2)
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                    )
                    page.keyboard.press("Escape")
                    expect(dialog).not_to_have_attribute("open", "")
                    expect(
                        page.get_by_role("link", name=re.compile("COBRAR"))
                    ).to_be_focused()
                    page.close()
            browser.close()
