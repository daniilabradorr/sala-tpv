"""Full browser gate for the core pre-VeriFactu ERP workflow.

This module deliberately does not match Django/pytest's normal discovery patterns.
Run it explicitly after installing Chromium with::

    python manage.py test e2e.browser_full_flow
"""

import json
import re
from decimal import Decimal
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import expect, sync_playwright

from apps.billing.models import (
    BillingDocument,
    BillingDocumentRelation,
    BillingDocumentRelationTypeChoices,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
)
from apps.cash_register.models import CashMovement, CashSession
from apps.catalog.models import Product
from apps.inventory.models import InventoryItem, StockMovement
from apps.onboarding.demo_seed import DemoBusinessSeeder
from apps.onboarding.services import OnboardingService
from apps.payments.models import (
    Payment,
    PaymentMethodCodeChoices,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.sales.models import (
    PaymentStatusChoices as SalePaymentStatusChoices,
    RequestedDocumentTypeChoices,
    Sale,
    SaleReturn,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)


class BrowserFullFlowTests(StaticLiveServerTestCase):
    """Drive every commercial command through real pages and CSRF-protected forms."""

    OWNER_EMAIL = "owner.e2e@example.com"
    OWNER_PASSWORD = "E2E-Test-Password-123!"
    OWNER_PIN = "1234"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
            cls.context = cls.browser.new_context()
            cls.page = cls.context.new_page()
        except Exception:
            cls.playwright.stop()
            super().tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            cls.page.close()
            cls.context.close()
            cls.browser.close()
        finally:
            cls.playwright.stop()
            super().tearDownClass()

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Netxodo E2E Demo SL",
            trade_name="Netxodo E2E",
            tax_identifier="B87654321",
            phone="923111111",
            email="e2e@example.com",
            address_line_1="Calle E2E 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda E2E",
            owner_first_name="Owner",
            owner_last_name="E2E",
            owner_email=self.OWNER_EMAIL,
            owner_phone="600000000",
            owner_password=self.OWNER_PASSWORD,
            owner_pin=self.OWNER_PIN,
        )
        DemoBusinessSeeder.seed(business=result.business)
        self.business = result.business
        self.store = result.store
        self.cash_register = result.cash_register
        self.console_messages = []
        self.javascript_errors = []
        self.step = "setup"
        self.page.on("console", self._record_console)
        self.page.on("pageerror", self._record_page_error)

    def tearDown(self):
        self.page.remove_listener("console", self._record_console)
        self.page.remove_listener("pageerror", self._record_page_error)
        self.context.clear_cookies()

    def _record_console(self, message):
        self.console_messages.append(f"{message.type}: {message.text}")

    def _record_page_error(self, error):
        self.javascript_errors.append(str(error))

    def _url(self, path):
        return f"{self.live_server_url}{path}"

    def _goto(self, path):
        response = self.page.goto(self._url(path))
        self.assertIsNotNone(response)
        self.assertLess(response.status, 400)

    def _id_from_url(self, pattern):
        match = re.search(pattern, self.page.url)
        self.assertIsNotNone(match, f"Unexpected URL: {self.page.url}")
        return int(match.group(1))

    def _open_cash_session(self):
        self.step = "open cash session"
        self.page.get_by_role("link", name="Caja").click()
        expect(self.page.get_by_text("Caja principal (CAJA-01)")).to_be_visible()
        # The cash-register endpoints predate navigation actions in their minimal UI.
        self._goto(f"/cash-register/stores/{self.store.pk}/open/")
        self.page.get_by_label("Cash register").select_option(
            label="Caja principal (CAJA-01)"
        )
        self.page.get_by_label("Opening amount").fill("100.00")
        self.page.get_by_role("button", name="Guardar").click()
        expect(self.page.get_by_text("Operación de caja completada.")).to_be_visible()
        session = CashSession.objects.get(business=self.business)
        self.assertEqual(session.status, CashSession.Status.OPEN)
        return session.pk

    def _open_sale(self, *, customer, document_type):
        self.step = f"open {document_type} sale"
        self._goto(f"/sales/stores/{self.store.pk}/sales/")
        self.page.get_by_role("link", name="Abrir nueva venta").click()
        if customer:
            self.page.get_by_label("Cliente").select_option(label=customer)
        self.page.get_by_label("Caja").select_option(label="Caja principal (CAJA-01)")
        self.page.get_by_label("Sesión de caja").select_option(index=1)
        self.page.get_by_label("Documento solicitado").select_option(document_type)
        self.page.get_by_role("button", name="Guardar").click()
        return self._id_from_url(r"/sales/(\d+)/$")

    def _add_product(self, product_name, quantity):
        self.step = f"add {product_name}"
        self.page.get_by_role("link", name="Anadir linea").click()
        self.page.get_by_label("Producto o servicio").select_option(label=product_name)
        self.page.get_by_label("Cantidad").fill(str(quantity))
        self.page.get_by_role("button", name="Guardar").click()
        expect(self.page.get_by_text(product_name, exact=False)).to_be_visible()

    def _complete_sale(self):
        self.step = "complete sale"
        self.page.get_by_role("button", name="Completar venta").click()
        expect(self.page.get_by_text("Completada", exact=True)).to_be_visible()

    def _pay_sale(self, method):
        self.step = f"pay sale by {method}"
        sale_id = self._id_from_url(r"/sales/(\d+)/$")
        sale = Sale.objects.get(pk=sale_id)
        amount = sale.pending_amount
        self.page.get_by_role("link", name="Registrar cobro").click()
        self.page.get_by_label("Method").select_option(label=method)
        self.page.get_by_label("Amount").fill(str(amount))
        self.page.get_by_label("Cash session").select_option(index=1)
        self.page.get_by_role("button", name="Registrar cobro").click()
        expect(self.page.get_by_text("Pago: Pagada")).to_be_visible()
        return amount

    def _issue_document(self, expected_type):
        self.step = f"issue {expected_type}"
        self.page.get_by_role("link", name="Emitir documento fiscal").click()
        self.page.get_by_label("Series").select_option(index=1)
        self.page.get_by_role("button", name="Emitir", exact=True).click()
        expect(
            self.page.get_by_text("Estado").locator("xpath=following-sibling::dd[1]")
        ).to_have_text("Emitido")
        document_id = self._id_from_url(r"/documents/(\d+)/$")
        document = BillingDocument.objects.get(pk=document_id)
        self.assertEqual(document.document_type, expected_type)
        return document

    def _create_return(self, *, sale_id, product_name, reason):
        self.step = f"create return for {product_name}"
        self._goto(f"/sales/stores/{self.store.pk}/sales/{sale_id}/")
        self.page.get_by_role("link", name="Crear devolucion").click()
        self.page.get_by_label("Motivo de la devolución").fill(reason)
        self.page.get_by_role("button", name="Guardar").click()
        return_id = self._id_from_url(r"/returns/(\d+)/$")
        self.page.get_by_role("link", name="Añadir línea").click()
        original_line = self.page.get_by_label("Línea original")
        option_value = (
            original_line.locator("option")
            .filter(has_text=product_name)
            .get_attribute("value")
        )
        self.assertIsNotNone(option_value)
        original_line.select_option(option_value)
        self.page.get_by_label("Cantidad a devolver").fill("1")
        self.page.get_by_label("Devolver al stock disponible").check()
        self.page.get_by_role("button", name="Guardar").click()
        self.page.get_by_label("PIN de seguridad").fill(self.OWNER_PIN)
        self.page.get_by_role("button", name="Completar devolución").click()
        expect(self.page.get_by_text("Estado: Completada")).to_be_visible()
        return return_id

    def _refund_return(self, method):
        self.step = f"refund return by {method}"
        return_id = self._id_from_url(r"/returns/(\d+)/$")
        returned = SaleReturn.objects.get(pk=return_id)
        self.page.get_by_role("link", name="Registrar reembolso").click()
        self.page.get_by_label("Method").select_option(label=method)
        self.page.get_by_label("Amount").fill(str(returned.total_amount))
        self.page.get_by_label("Cash session").select_option(index=1)
        self.page.get_by_label("Pin").fill(self.OWNER_PIN)
        self.page.get_by_role("button", name="Registrar reembolso").click()
        expect(
            self.page.get_by_text("Reembolso registrado correctamente.")
        ).to_be_visible()
        return returned.total_amount

    def _issue_rectification(self, expected_type):
        self.step = f"issue {expected_type}"
        self.page.get_by_role("link", name="Emitir rectificativa").click()
        self.page.get_by_label("Series").select_option(index=1)
        self.page.get_by_role("button", name="Emitir rectificativa").click()
        document_id = self._id_from_url(r"/documents/(\d+)/$")
        document = BillingDocument.objects.get(pk=document_id)
        self.assertEqual(document.document_type, expected_type)
        return document

    def _close_cash_session(self, session_id, expected_cash):
        self.step = "review and close cash session"
        base = f"/cash-register/stores/{self.store.pk}/sessions/{session_id}"
        self._goto(f"{base}/review/")
        self.page.get_by_label("Counted amount").fill(str(expected_cash))
        self.page.get_by_role("button", name="Guardar").click()
        self._goto(f"{base}/close/")
        self.page.get_by_label("Counted amount").fill(str(expected_cash))
        self.page.get_by_label("Pin").fill(self.OWNER_PIN)
        self.page.get_by_role("button", name="Guardar").click()
        expect(self.page.get_by_text(f"Esperado: {expected_cash}")).to_be_visible()

    def test_full_browser_erp_happy_path(self):
        try:
            self.step = "login"
            response = self.page.goto(self._url("/users/login/"))
            self.assertEqual(response.status, 200)
            expect(self.page).to_have_title(re.compile("Netxodo"))
            self.page.get_by_label("Correo electrónico").fill(self.OWNER_EMAIL)
            self.page.get_by_label("Contraseña").fill(self.OWNER_PASSWORD)
            self.page.get_by_role("button", name="Iniciar sesión").click()
            self.page.wait_for_url(self._url("/"))
            expect(self.page.get_by_role("heading", name="Netxodo E2E")).to_be_visible()
            expect(self.page.get_by_text("Tienda E2E", exact=True)).to_be_visible()

            session_id = self._open_cash_session()

            f2_sale_id = self._open_sale(
                customer="Cliente Mostrador DEMO",
                document_type=RequestedDocumentTypeChoices.TICKET,
            )
            self._add_product("Agua mineral 500 ml", 2)
            self._add_product("Envoltorio para regalo", 1)
            self._complete_sale()
            cash_payment_amount = self._pay_sale("Efectivo")
            f2 = self._issue_document(BillingDocumentTypeChoices.F2)
            f2_return_id = self._create_return(
                sale_id=f2_sale_id,
                product_name="Agua mineral 500 ml",
                reason="Devolución E2E F2",
            )
            cash_refund_amount = self._refund_return("Efectivo")
            r5 = self._issue_rectification(BillingDocumentTypeChoices.R5)

            f1_sale_id = self._open_sale(
                customer="Empresa Demo Netxodo SL",
                document_type=RequestedDocumentTypeChoices.INVOICE,
            )
            self._add_product("Refresco cola 330 ml", 2)
            self._complete_sale()
            card_payment_amount = self._pay_sale("Tarjeta")
            f1 = self._issue_document(BillingDocumentTypeChoices.F1)
            f1_return_id = self._create_return(
                sale_id=f1_sale_id,
                product_name="Refresco cola 330 ml",
                reason="Devolución E2E F1",
            )
            card_refund_amount = self._refund_return("Tarjeta")
            r1 = self._issue_rectification(BillingDocumentTypeChoices.R1)

            expected_cash = Decimal("100.00") + cash_payment_amount - cash_refund_amount
            self._close_cash_session(session_id, expected_cash)
            self._assert_database_state(
                session_id=session_id,
                f2_sale_id=f2_sale_id,
                f1_sale_id=f1_sale_id,
                f2_return_id=f2_return_id,
                f1_return_id=f1_return_id,
                documents=(f2, r5, f1, r1),
                amounts=(
                    cash_payment_amount,
                    cash_refund_amount,
                    card_payment_amount,
                    card_refund_amount,
                ),
                expected_cash=expected_cash,
            )
            self.assertEqual(self.javascript_errors, [])
        except Exception:
            self._capture_failure()
            raise

    def _assert_database_state(
        self,
        *,
        session_id,
        f2_sale_id,
        f1_sale_id,
        f2_return_id,
        f1_return_id,
        documents,
        amounts,
        expected_cash,
    ):
        f2_sale = Sale.objects.get(pk=f2_sale_id)
        f1_sale = Sale.objects.get(pk=f1_sale_id)
        self.assertEqual(
            SaleReturn.objects.get(pk=f2_return_id).status,
            SaleReturnStatusChoices.COMPLETED,
        )
        self.assertEqual(
            SaleReturn.objects.get(pk=f1_return_id).status,
            SaleReturnStatusChoices.COMPLETED,
        )
        for sale in (f2_sale, f1_sale):
            self.assertEqual(sale.status, SaleStatusChoices.COMPLETED)
            self.assertEqual(sale.payment_status, SalePaymentStatusChoices.PAID)
            self.assertEqual(sale.pending_amount, Decimal("0.00"))
        self.assertEqual(
            f2_sale.document_type_requested, RequestedDocumentTypeChoices.TICKET
        )
        self.assertEqual(
            f1_sale.document_type_requested, RequestedDocumentTypeChoices.INVOICE
        )

        water = Product.objects.get(business=self.business, name="Agua mineral 500 ml")
        cola = Product.objects.get(business=self.business, name="Refresco cola 330 ml")
        wrapping = Product.objects.get(
            business=self.business, name="Envoltorio para regalo"
        )
        self.assertEqual(
            InventoryItem.objects.get(product=water).current_stock, Decimal("47.000")
        )
        self.assertEqual(
            InventoryItem.objects.get(product=cola).current_stock, Decimal("35.000")
        )
        self.assertFalse(InventoryItem.objects.filter(product=wrapping).exists())
        for product, sale_id, return_id in (
            (water, f2_sale_id, f2_return_id),
            (cola, f1_sale_id, f1_return_id),
        ):
            self.assertEqual(
                StockMovement.objects.filter(
                    product=product,
                    sale_id=sale_id,
                    movement_type=StockMovement.TYPE_SALE,
                ).count(),
                1,
            )
            self.assertEqual(
                StockMovement.objects.filter(
                    product=product,
                    sale_return_id=return_id,
                    movement_type=StockMovement.TYPE_SALE_RETURN,
                ).count(),
                1,
            )

        cash_paid, cash_refunded, card_paid, card_refunded = amounts
        payments = Payment.objects.filter(
            business=self.business, status=PaymentStatusChoices.COMPLETED
        )
        self.assertEqual(payments.count(), 4)
        for payment_type, method_code, amount in (
            (PaymentTypeChoices.SALE_PAYMENT, PaymentMethodCodeChoices.CASH, cash_paid),
            (PaymentTypeChoices.REFUND, PaymentMethodCodeChoices.CASH, cash_refunded),
            (PaymentTypeChoices.SALE_PAYMENT, PaymentMethodCodeChoices.CARD, card_paid),
            (PaymentTypeChoices.REFUND, PaymentMethodCodeChoices.CARD, card_refunded),
        ):
            self.assertTrue(
                payments.filter(
                    payment_type=payment_type, method__code=method_code, amount=amount
                ).exists()
            )

        session = CashSession.objects.get(pk=session_id)
        self.assertEqual(session.status, CashSession.Status.CLOSED)
        self.assertEqual(session.opening_amount, Decimal("100.00"))
        self.assertEqual(session.expected_cash_amount, expected_cash)
        self.assertEqual(session.counted_cash_amount, expected_cash)
        self.assertEqual(session.difference_amount, Decimal("0.00"))
        self.assertEqual(
            session.movements.filter(
                movement_type=CashMovement.MovementType.SALE_CASH
            ).count(),
            1,
        )
        self.assertEqual(
            session.movements.filter(
                movement_type=CashMovement.MovementType.REFUND_CASH
            ).count(),
            1,
        )

        f2, r5, f1, r1 = [BillingDocument.objects.get(pk=item.pk) for item in documents]
        self.assertEqual(
            BillingDocument.objects.filter(business=self.business).count(), 4
        )
        for document, expected_type in zip(
            (f2, r5, f1, r1),
            (
                BillingDocumentTypeChoices.F2,
                BillingDocumentTypeChoices.R5,
                BillingDocumentTypeChoices.F1,
                BillingDocumentTypeChoices.R1,
            ),
            strict=True,
        ):
            self.assertEqual(document.status, BillingDocumentStatusChoices.ISSUED)
            self.assertEqual(document.document_type, expected_type)
            self.assertEqual(document.business_id, self.business.pk)
            self.assertEqual(document.store_id, self.store.pk)
            self.assertEqual(document.series.document_type, expected_type)
            self.assertIsNotNone(document.number)
            self.assertIsNotNone(document.issued_at)
        self.assertEqual(f2.sale_id, f2_sale_id)
        self.assertEqual(f1.sale_id, f1_sale_id)
        self.assertEqual(r5.sale_return_id, f2_return_id)
        self.assertEqual(r1.sale_return_id, f1_return_id)
        self.assertTrue(
            BillingDocumentRelation.objects.filter(
                source_document=r5,
                target_document=f2,
                relation_type=BillingDocumentRelationTypeChoices.RECTIFIES,
            ).exists()
        )
        self.assertTrue(
            BillingDocumentRelation.objects.filter(
                source_document=r1,
                target_document=f1,
                relation_type=BillingDocumentRelationTypeChoices.RECTIFIES,
            ).exists()
        )
        self.assertEqual(f1.issuer_legal_name, "Netxodo E2E Demo SL")
        self.assertEqual(f1.issuer_tax_identifier, "B87654321")
        self.assertEqual(f1.recipient_legal_name, "Empresa Demo Netxodo SL")
        self.assertEqual(f1.recipient_tax_identifier, "B12345678")

    def _capture_failure(self):
        artifact_dir = Path("artifacts/e2e")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(artifact_dir / "failure.png"), full_page=True)
        (artifact_dir / "failure.html").write_text(
            self.page.content(), encoding="utf-8"
        )
        (artifact_dir / "failure.json").write_text(
            json.dumps(
                {
                    "step": self.step,
                    "url": self.page.url,
                    "title": self.page.title(),
                    "console": self.console_messages,
                    "page_errors": self.javascript_errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
