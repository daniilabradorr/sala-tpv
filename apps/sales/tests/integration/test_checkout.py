"""Integration coverage for the durable Sales -> Payments -> Billing checkout."""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import BillingDocument, BillingSeries
from apps.business_config.services import create_business_configuration
from apps.cash_register.models import CashRegister, CashSession
from apps.payments.models import Payment, PaymentMethod
from apps.sales.checkout import PaymentIntent, checkout_state, run_checkout
from apps.sales.models import (
    PaymentStatusChoices,
    RequestedDocumentTypeChoices,
    SaleStatusChoices,
)
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sales_business,
    create_sales_customer,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


class CheckoutIntegrationTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.other_business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.other_store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.client.force_login(self.user)
        _profile, settings = create_business_configuration(
            business=self.business,
            legal_name="Netxodo Checkout SL",
            tax_identifier="B12345678",
            phone="600000000",
            email="checkout@example.test",
            address_line_1="Calle Mayor 1",
            postal_code="28001",
            city="Madrid",
            province="Madrid",
        )
        settings.enable_stock_control = False
        settings.require_pin_for_sensitive_actions = False
        settings.save()
        tax = create_sales_tax(business=self.business, rate=Decimal("0.00"))
        self.product = create_sales_product(
            business=self.business,
            tax=tax,
            base_price=Decimal("40.00"),
            track_stock=False,
        )
        self.customer = create_sales_customer(
            business=self.business,
            legal_name="Cliente Checkout SL",
            tax_identifier="B87654321",
        )
        self.register = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Principal",
            code="CHECKOUT",
        )
        self.session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.register,
            opened_by=self.user,
        )
        self.cash = PaymentMethod.objects.create(
            business=self.business, name="Efectivo", code="cash"
        )
        self.card = PaymentMethod.objects.create(
            business=self.business, name="Tarjeta", code="card"
        )

    def sale(
        self,
        *,
        requested=RequestedDocumentTypeChoices.TICKET,
        customer=None,
        lines=True,
    ):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            document_type_requested=requested,
            customer=customer,
            cash_register=self.register,
            cash_session=self.session,
        )
        if lines:
            create_sale_line(
                business=self.business,
                sale=sale,
                product=self.product,
                tax_rate=Decimal("0.00"),
            )
        return sale

    def series(self, kind="F2", **overrides):
        values = {
            "business": self.business,
            "store": self.store,
            "name": f"Serie {uuid.uuid4().hex[:6]}",
            "document_type": kind,
            "prefix": f"{kind}-{uuid.uuid4().hex[:6]}",
            "year": timezone.localdate().year,
        }
        values.update(overrides)
        return BillingSeries.objects.create(**values)

    def intent(self, method=None, amount=Decimal("40.00"), key=None, received=None):
        return PaymentIntent(
            method_id=(method or self.card).pk,
            amount=amount,
            idempotency_key=key or uuid.uuid4(),
            cash_received=received,
        )

    def run(self, sale, intents, series=None, billing_key=None, allow_split=True):
        return run_checkout(
            business=self.business,
            sale=sale,
            user=self.user,
            intents=intents,
            series_id=getattr(series, "pk", series),
            billing_key=billing_key or uuid.uuid4(),
            allow_split=allow_split,
        )

    def assert_pristine(self, sale):
        sale.refresh_from_db()
        self.assertEqual(sale.status, SaleStatusChoices.OPEN)
        self.assertFalse(Payment.objects.filter(sale=sale).exists())
        self.assertFalse(BillingDocument.objects.filter(sale=sale).exists())

    def test_preflight_rejects_missing_lines_none_invoice_customer_and_series(self):
        valid_series = self.series()
        cases = [
            (self.sale(lines=False), valid_series, "sin líneas"),
            (self.sale(), valid_series, "Ticket o Factura"),
            (self.sale(), valid_series, "requiere un cliente"),
            (
                self.sale(
                    requested=RequestedDocumentTypeChoices.INVOICE,
                    customer=self.customer,
                ),
                None,
                "No existe una serie",
            ),
        ]
        type(cases[1][0]).objects.filter(pk=cases[1][0].pk).update(
            document_type_requested=RequestedDocumentTypeChoices.NONE
        )
        cases[1][0].refresh_from_db()
        type(cases[2][0]).objects.filter(pk=cases[2][0].pk).update(
            document_type_requested=RequestedDocumentTypeChoices.INVOICE
        )
        cases[2][0].refresh_from_db()
        for sale, series, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesMessage(ValidationError, message),
            ):
                self.run(sale, [self.intent()], series)
            self.assert_pristine(sale)

    def test_one_series_is_automatic_but_multiple_require_selection(self):
        sale = self.sale()
        only = self.series()
        state = self.run(sale, [self.intent()], series=None)
        self.assertTrue(state["complete"])
        self.assertEqual(state["document"].series, only)

        second_sale = self.sale()
        self.series()
        with self.assertRaisesMessage(ValidationError, "Selecciona una serie"):
            self.run(second_sale, [self.intent()], series=None)
        self.assert_pristine(second_sale)

    def test_series_isolation_rejects_tenant_store_register_and_type(self):
        sale = self.sale()
        other_register = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Secundaria",
            code="OTHER",
        )
        invalid = [
            self.series(business=self.other_business, store=None),
            self.series(store=self.other_store),
            self.series(cash_register=other_register),
            self.series(kind="F1"),
        ]
        for candidate in invalid:
            with (
                self.subTest(series=candidate),
                self.assertRaisesMessage(ValidationError, "no es válida"),
            ):
                self.run(sale, [self.intent()], candidate)
            self.assert_pristine(sale)

    def test_simple_cash_and_card_complete_pay_and_issue(self):
        for method in (self.cash, self.card):
            with self.subTest(method=method.code):
                sale = self.sale()
                state = self.run(
                    sale,
                    [
                        self.intent(
                            method,
                            received=Decimal("50.00") if method == self.cash else None,
                        )
                    ],
                    self.series(),
                )
                sale.refresh_from_db()
                payment = Payment.objects.get(sale=sale)
                self.assertTrue(state["complete"])
                self.assertEqual(sale.status, SaleStatusChoices.COMPLETED)
                self.assertEqual(sale.payment_status, PaymentStatusChoices.PAID)
                self.assertEqual(sale.pending_amount, Decimal("0.00"))
                self.assertEqual(payment.method, method)
                self.assertEqual(payment.cash_session, sale.cash_session)

    def test_inactive_and_cross_tenant_methods_are_rejected(self):
        inactive = PaymentMethod.objects.create(
            business=self.business, name="Bizum", code="bizum", is_active=False
        )
        foreign = PaymentMethod.objects.create(
            business=self.other_business, name="Transferencia", code="transfer"
        )
        for method in (inactive, foreign):
            sale = self.sale()
            with (
                self.subTest(method=method),
                self.assertRaisesMessage(
                    ValidationError, "inactivo o pertenece a otro negocio"
                ),
            ):
                self.run(sale, [self.intent(method)], self.series())
            self.assert_pristine(sale)

    def test_cash_received_is_operational_and_insufficient_cash_is_preflight_error(
        self,
    ):
        self.product.base_price = Decimal("12.50")
        self.product.save()
        sale = self.sale()
        self.run(
            sale,
            [self.intent(self.cash, Decimal("12.50"), received=Decimal("20.00"))],
            self.series(),
        )
        self.assertEqual(Payment.objects.get(sale=sale).amount, Decimal("12.50"))

        insufficient = self.sale()
        with self.assertRaisesMessage(ValidationError, "efectivo entregado"):
            self.run(
                insufficient,
                [self.intent(self.cash, Decimal("12.50"), received=Decimal("10.00"))],
                self.series(),
            )
        self.assert_pristine(insufficient)

    def test_split_success_disabled_and_invalid_sums(self):
        intents = [
            self.intent(self.cash, Decimal("15.00"), received=Decimal("20.00")),
            self.intent(self.card, Decimal("25.00")),
        ]
        sale = self.sale()
        self.run(sale, intents, self.series())
        sale.refresh_from_db()
        self.assertCountEqual(
            Payment.objects.filter(sale=sale).values_list("amount", flat=True),
            [Decimal("15.00"), Decimal("25.00")],
        )
        self.assertEqual(sale.payment_status, PaymentStatusChoices.PAID)

        for amounts, allowed in [((15, 25), False), ((20, 15), True), ((20, 25), True)]:
            candidate = self.sale()
            parts = [
                self.intent(self.cash, Decimal(amounts[0]), received=Decimal("30")),
                self.intent(self.card, Decimal(amounts[1])),
            ]
            with (
                self.subTest(amounts=amounts, allowed=allowed),
                self.assertRaises(ValidationError),
            ):
                self.run(candidate, parts, self.series(), allow_split=allowed)
            self.assert_pristine(candidate)

    def test_payment_idempotency_and_partial_split_recovery(self):
        sale = self.sale()
        series = self.series()
        keys = uuid.uuid4(), uuid.uuid4()
        intents = [
            self.intent(self.cash, Decimal("15"), keys[0], Decimal("20")),
            self.intent(self.card, Decimal("25"), keys[1]),
        ]
        from apps.sales import checkout

        real_register = checkout.register_sale_payment
        calls = 0

        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValidationError("Datáfono temporalmente no disponible")
            return real_register(**kwargs)

        with patch(
            "apps.sales.checkout.register_sale_payment", side_effect=fail_second
        ):
            with self.assertRaises(ValidationError):
                self.run(sale, intents, series)
        sale.refresh_from_db()
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
        self.assertEqual(sale.payment_status, PaymentStatusChoices.PARTIAL)
        self.assertEqual(sale.pending_amount, Decimal("25.00"))

        self.run(sale, intents, series)
        self.run(sale, intents, series)
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 2)

    def test_payment_and_billing_failures_are_durable_and_recoverable(self):
        sale = self.sale()
        series = self.series()
        intent = self.intent()
        with patch(
            "apps.sales.checkout.register_sale_payment",
            side_effect=ValidationError("Fallo de cobro"),
        ):
            with self.assertRaises(ValidationError):
                self.run(sale, [intent], series)
        sale.refresh_from_db()
        self.assertEqual(sale.status, SaleStatusChoices.COMPLETED)
        self.assertEqual(sale.payment_status, PaymentStatusChoices.UNPAID)
        self.assertFalse(BillingDocument.objects.filter(sale=sale).exists())
        self.run(sale, [intent], series)
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)

        billing_sale = self.sale()
        billing_series = self.series()
        billing_intent = self.intent()
        with patch(
            "apps.sales.checkout.issue_sale_document",
            side_effect=ValidationError("Fallo fiscal"),
        ):
            with self.assertRaises(ValidationError):
                self.run(billing_sale, [billing_intent], billing_series)
        billing_sale.refresh_from_db()
        self.assertEqual(billing_sale.payment_status, PaymentStatusChoices.PAID)
        self.assertEqual(Payment.objects.filter(sale=billing_sale).count(), 1)
        self.assertFalse(BillingDocument.objects.filter(sale=billing_sale).exists())
        self.run(billing_sale, [], billing_series)
        self.assertEqual(Payment.objects.filter(sale=billing_sale).count(), 1)
        self.assertEqual(BillingDocument.objects.filter(sale=billing_sale).count(), 1)

    def test_checkout_state_requires_document_type_matching_sale_request(self):
        for requested, expected, wrong in [
            (RequestedDocumentTypeChoices.TICKET, "F2", "F1"),
            (RequestedDocumentTypeChoices.INVOICE, "F1", "F2"),
        ]:
            sale = self.sale(
                requested=requested,
                customer=self.customer
                if requested == RequestedDocumentTypeChoices.INVOICE
                else None,
            )
            self.run(sale, [self.intent()], self.series(expected))
            BillingDocument.objects.filter(sale=sale).update(document_type=wrong)
            self.assertFalse(
                checkout_state(business=self.business, sale=sale)["complete"]
            )

    def checkout_url(self, sale):
        return reverse("sales:sale_checkout", args=(self.store.pk, sale.pk))

    def test_http_progressive_enhancement_cash_change_and_card_tampering(self):
        self.product.base_price = Decimal("12.50")
        self.product.save()
        sale = self.sale()
        key, billing_key = uuid.uuid4(), uuid.uuid4()
        response = self.client.post(
            self.checkout_url(sale),
            {
                "mode": "single",
                "method": self.cash.pk,
                "cash_received": "20.00",
                "series": self.series().pk,
                "payment_idempotency_key": key,
                "billing_idempotency_key": billing_key,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cash_change"], Decimal("7.50"))

        card_sale = self.sale()
        response = self.client.post(
            self.checkout_url(card_sale),
            {
                "mode": "single",
                "method": self.card.pk,
                "cash_received": "100.00",
                "series": self.series().pk,
                "payment_idempotency_key": uuid.uuid4(),
                "billing_idempotency_key": uuid.uuid4(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["cash_change"])

    def test_get_has_two_split_rows_and_invalid_bound_split_preserves_values(self):
        sale = self.sale()
        series = self.series()
        response = self.client.get(self.checkout_url(sale))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["payment_formset"]), 2)
        self.assertTemplateUsed(response, "sales/checkout.html")
        htmx = self.client.get(self.checkout_url(sale), HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(htmx, "sales/partials/_checkout.html")

        keys = uuid.uuid4(), uuid.uuid4()
        response = self.client.post(
            self.checkout_url(sale),
            {
                "mode": "split",
                "series": series.pk,
                "payment_idempotency_key": uuid.uuid4(),
                "billing_idempotency_key": uuid.uuid4(),
                "payments-TOTAL_FORMS": "2",
                "payments-INITIAL_FORMS": "0",
                "payments-MIN_NUM_FORMS": "2",
                "payments-MAX_NUM_FORMS": "1000",
                "payments-0-method": self.cash.pk,
                "payments-0-amount": "10.00",
                "payments-0-cash_received": "10.00",
                "payments-0-idempotency_key": keys[0],
                "payments-1-method": self.card.pk,
                "payments-1-amount": "10.00",
                "payments-1-idempotency_key": keys[1],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="split" checked')
        self.assertContains(response, 'value="10.00"', count=3)
        for key in keys:
            self.assertContains(response, str(key))
        self.assertContains(response, "La suma de los pagos")
        self.assert_pristine(sale)

    def test_empty_cart_checkout_cta_is_a_disabled_button_not_a_link(self):
        sale = self.sale(lines=False)
        response = self.client.get(
            reverse("sales:sale_detail", args=(self.store.pk, sale.pk))
        )
        self.assertContains(response, 'checkout-open" disabled')
        self.assertNotContains(response, f'href="{self.checkout_url(sale)}"')
