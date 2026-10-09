"""Real checkout races: durable steps, idempotency and physical session closing."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.billing.models import BillingDocument
from apps.cash_register.models import CashCount, CashMovement
from apps.cash_register.services import CashRegisterService
from apps.inventory.models import StockMovement
from apps.payments.models import Payment
from apps.sales.checkout import PaymentIntent, run_checkout
from apps.sales.models import Sale, SaleStatusChoices
from tests.performance.dataset import Dataset


@skipUnlessDBFeature("has_select_for_update")
class CheckoutPostgreSQLConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.dataset = Dataset(3, label="checkout-concurrency")
        self.sale, self.lines = self.dataset.sale(1)
        self.cash = next(
            method for method in self.dataset.methods if method.affects_cash_register
        )
        self.billing_key = uuid.uuid4()

    def run_threads(self, *operations):
        barrier = Barrier(len(operations))

        def execute(operation):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                operation()
                return True
            except ValidationError:
                return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(execute, operations))

    def checkout(self, key):
        sale = Sale.objects.get(pk=self.sale.pk)
        return run_checkout(
            business=self.dataset.business,
            sale=sale,
            user=self.dataset.user,
            intents=[
                PaymentIntent(
                    self.cash.pk, self.sale.total_amount, key, Decimal("20.00")
                )
            ],
            series_id=None,
            billing_key=self.billing_key,
            allow_split=True,
        )

    def assert_single_completion(self):
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, SaleStatusChoices.COMPLETED)
        self.assertEqual(self.sale.pending_amount, Decimal("0.00"))
        payment = Payment.objects.get(sale=self.sale)
        self.assertEqual(payment.amount, self.sale.total_amount)
        self.assertEqual(
            CashMovement.objects.get(payment=payment).amount, payment.amount
        )
        self.assertEqual(BillingDocument.objects.filter(sale=self.sale).count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(
                sale=self.sale, movement_type=StockMovement.TYPE_SALE
            ).count(),
            1,
        )
        inventory = self.dataset.products[0].inventory_items.get(
            store=self.dataset.store
        )
        self.assertEqual(inventory.current_stock, Decimal("999.000"))
        self.dataset.session.refresh_from_db()
        self.assertEqual(self.dataset.session.expected_cash_amount, payment.amount)

    def test_concurrent_same_keys_and_timeout_replay_complete_once(self):
        key = uuid.uuid4()
        outcomes = self.run_threads(
            lambda: self.checkout(key), lambda: self.checkout(key)
        )
        self.assertTrue(any(outcomes), outcomes)
        self.checkout(key)
        self.assert_single_completion()

    def test_concurrent_distinct_keys_never_overpay_or_repeat_stock(self):
        outcomes = self.run_threads(
            lambda: self.checkout(uuid.uuid4()), lambda: self.checkout(uuid.uuid4())
        )
        self.assertTrue(any(outcomes), outcomes)
        self.assert_single_completion()

    def test_close_session_racing_cash_checkout_is_serialized(self):
        key = uuid.uuid4()
        outcomes = self.run_threads(
            lambda: self.checkout(key),
            lambda: CashRegisterService().close_cash_session(
                business=self.dataset.business,
                store_id=self.dataset.store.pk,
                cash_register_id=self.dataset.register.pk,
                cash_session_id=self.dataset.session.pk,
                user=self.dataset.user,
                counted_cash_amount=Decimal("0.00"),
            ),
        )
        self.assertTrue(outcomes[1], outcomes)
        self.dataset.session.refresh_from_db()
        closing = CashCount.objects.get(
            cash_session=self.dataset.session, count_type=CashCount.CountType.CLOSING
        )
        payment = Payment.objects.filter(sale=self.sale).first()
        if payment:
            self.assertTrue(outcomes[0])
            self.assertEqual(
                CashMovement.objects.get(payment=payment).amount, payment.amount
            )
            self.assertEqual(self.dataset.session.expected_cash_amount, payment.amount)
            self.assertEqual(closing.expected_amount, payment.amount)
        else:
            self.assertFalse(outcomes[0])
            self.assertFalse(CashMovement.objects.filter(sale=self.sale).exists())
            self.assertEqual(self.dataset.session.expected_cash_amount, Decimal("0.00"))
            self.assertEqual(closing.expected_amount, Decimal("0.00"))
