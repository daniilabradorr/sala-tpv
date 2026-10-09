"""Final physical-cash semantics, HTTP recovery and conditional session policy."""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import BillingDocument
from apps.business_config.models import POSSettings
from apps.cash_register.models import CashMovement, CashSession
from apps.payments.models import Payment, PaymentMethod
from apps.sales.checkout import CheckoutConflict
from apps.sales.tests.integration import test_checkout as checkout_fixtures


class CheckoutCashTests(TestCase):
    setUp = checkout_fixtures.CheckoutIntegrationTests.setUp
    sale = checkout_fixtures.CheckoutIntegrationTests.sale
    series = checkout_fixtures.CheckoutIntegrationTests.series
    intent = checkout_fixtures.CheckoutIntegrationTests.intent
    _run_checkout = checkout_fixtures.CheckoutIntegrationTests._run_checkout
    checkout_url = checkout_fixtures.CheckoutIntegrationTests.checkout_url
    assert_pristine = checkout_fixtures.CheckoutIntegrationTests.assert_pristine

    def post_data(self, method, **extra):
        return {
            "mode": "single",
            "method": method.pk,
            "payment_idempotency_key": uuid.uuid4(),
            "billing_idempotency_key": uuid.uuid4(),
            **extra,
        }

    def test_blank_cash_exact_and_change_use_payment_amount_for_physical_balance(self):
        self.product.base_price = Decimal("10.90")
        self.product.save()
        self.session.opening_amount = self.session.expected_cash_amount = Decimal(
            "100.00"
        )
        self.session.save()
        self.series()
        for hx in (False, True):
            for tender, change in (("", "0.00"), ("20.00", "9.10")):
                with self.subTest(hx=hx, tender=tender):
                    sale = self.sale()
                    before = CashSession.objects.get(
                        pk=self.session.pk
                    ).expected_cash_amount
                    data = self.post_data(self.cash, cash_received=tender)
                    response = self.client.post(
                        self.checkout_url(sale),
                        data,
                        **({"HTTP_HX_REQUEST": "true"} if hx else {}),
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context["cash_change"], Decimal(change))
                    payment = Payment.objects.get(sale=sale)
                    movement = CashMovement.objects.get(payment=payment)
                    self.assertEqual(payment.amount, Decimal("10.90"))
                    self.assertEqual(movement.amount, payment.amount)
                    self.session.refresh_from_db()
                    self.assertEqual(
                        self.session.expected_cash_amount, before + payment.amount
                    )
                    repeated = self.client.post(
                        self.checkout_url(sale), data, HTTP_HX_REQUEST="true"
                    )
                    self.assertEqual(repeated.status_code, 200)
                    self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
                    self.assertEqual(
                        CashMovement.objects.filter(payment=payment).count(), 1
                    )
                    self.assertEqual(
                        BillingDocument.objects.filter(sale=sale).count(), 1
                    )

    def test_insufficient_cash_keeps_open_sale_errors_keys_and_no_economic_effect(self):
        sale = self.sale()
        self.series()
        data = self.post_data(self.cash, cash_received="10.00")
        response = self.client.post(
            self.checkout_url(sale), data, HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, "efectivo entregado", status_code=422)
        for name in ("payment_idempotency_key", "billing_idempotency_key"):
            self.assertContains(response, str(data[name]), status_code=422)
        self.assert_pristine(sale)
        self.assertFalse(CashMovement.objects.filter(sale=sale).exists())

    def test_completion_cash_session_matrix_and_all_mvp_methods(self):
        self.series()
        for code in ("bizum", "transfer"):
            PaymentMethod.objects.create(business=self.business, name=code, code=code)
        for required in (False, True):
            POSSettings.objects.filter(business=self.business).update(
                require_open_cash_register=required
            )
            for method in PaymentMethod.objects.filter(business=self.business):
                for has_session in (False, True):
                    with self.subTest(
                        required=required, method=method.code, session=has_session
                    ):
                        sale = self.sale()
                        if not has_session:
                            sale.cash_register = sale.cash_session = None
                            sale.save()
                        allowed = has_session or (
                            not required and not method.affects_cash_register
                        )
                        if not allowed:
                            with self.assertRaises(ValidationError):
                                self._run_checkout(sale, [self.intent(method)])
                            self.assert_pristine(sale)
                        else:
                            state = self._run_checkout(sale, [self.intent(method)])
                            self.assertTrue(state["complete"])
                            payment = Payment.objects.get(sale=sale)
                            self.assertEqual(
                                payment.cash_session_id,
                                self.session.pk if has_session else None,
                            )
                            self.assertEqual(
                                CashMovement.objects.filter(payment=payment).count(),
                                int(method.affects_cash_register),
                            )

    def test_closed_session_returns_contextual_409_without_payment(self):
        sale = self.sale()
        self.series()
        # Model-level close is fixture setup; concurrency tests use the service.
        self.session.status = CashSession.Status.CLOSED
        self.session.closed_at = timezone.now()
        self.session.counted_cash_amount = self.session.expected_cash_amount
        self.session.closed_by = self.user
        self.session.save()
        data = self.post_data(self.cash)
        response = self.client.post(
            self.checkout_url(sale), data, HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, "se ha cerrado", status_code=409)
        self.assertEqual(response["X-Netxodo-Allow-Error-Swap"], "true")
        self.assert_pristine(sale)
        with self.assertRaises(CheckoutConflict):
            self._run_checkout(sale, [self.intent(self.cash)])

    def test_split_blank_and_change_sum_assigned_amounts_and_keep_references(self):
        self.product.base_price = Decimal("30.00")
        self.product.save()
        self.series()
        for tender in (None, Decimal("20.00")):
            sale = self.sale()
            parts = [
                self.intent(self.cash, Decimal("10.00"), received=tender),
                self.intent(self.card, Decimal("20.00")),
            ]
            self.assertTrue(self._run_checkout(sale, parts)["complete"])
            self.assertEqual(
                sorted(
                    Payment.objects.filter(sale=sale).values_list("amount", flat=True)
                ),
                [Decimal("10.00"), Decimal("20.00")],
            )
            self.assertEqual(
                CashMovement.objects.get(sale=sale).amount, Decimal("10.00")
            )

    def test_cash_fields_expose_the_authoritative_method_flag(self):
        self.series()
        response = self.client.get(
            self.checkout_url(self.sale()), HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, 'data-method-code="cash" data-method-cash="true"')
        self.assertContains(
            response, 'data-method-code="card" data-method-cash="false"'
        )

    def test_one_active_method_preselected_but_multiple_have_no_arbitrary_default(self):
        sale = self.sale()
        self.series()
        self.assertIsNone(
            self.client.get(self.checkout_url(sale)).context["form"]["method"].value()
        )
        PaymentMethod.objects.filter(pk=self.card.pk).update(is_active=False)
        response = self.client.get(self.checkout_url(sale))
        self.assertEqual(response.context["form"]["method"].value(), self.cash.pk)
        self.assertFalse(response.context["allow_split"])

    def test_cash_billing_failure_shows_change_and_retry_emits_without_second_charge(
        self,
    ):
        sale = self.sale()
        self.series()
        data = self.post_data(self.cash, cash_received="50.00")
        with patch(
            "apps.sales.checkout.issue_sale_document",
            side_effect=ValidationError("Emisión temporalmente indisponible"),
        ):
            response = self.client.post(
                self.checkout_url(sale), data, HTTP_HX_REQUEST="true"
            )
        self.assertContains(response, "El cobro se ha registrado correctamente")
        self.assertContains(response, "REINTENTAR EMISIÓN")
        self.assertEqual(response.context["cash_change"], Decimal("10.00"))
        response = self.client.post(
            self.checkout_url(sale), data, HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, "VENTA COMPLETADA")
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
        self.assertEqual(CashMovement.objects.filter(sale=sale).count(), 1)
        self.assertEqual(BillingDocument.objects.filter(sale=sale).count(), 1)
