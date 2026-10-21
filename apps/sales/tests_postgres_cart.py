"""Real row-lock races for cart receipts and the checkout version boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connections, connection
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.sales.cart import mutate, mutate_batch
from apps.sales.checkout import PaymentIntent, run_checkout
from apps.sales.models import CartOperation, Sale
from apps.payments.models import Payment
from apps.sales.services import update_sale_line
from tests.performance.dataset import Dataset


@skipUnlessDBFeature("has_select_for_update")
class CartPostgreSQLTests(TransactionTestCase):
    def setUp(self):
        self.d = Dataset(1, label="pg-cart")
        self.sale, self.lines = self.d.sale(1)

    def mutation(self, data):
        return mutate(
            business=self.d.business,
            store=self.d.store,
            sale_id=self.sale.pk,
            user=self.d.user,
            data=data,
        )

    def threads(self, *operations):
        barrier = Barrier(len(operations))

        def execute(operation):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return operation()
            except ValidationError:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(execute, operations))

    def payload(self, **extra):
        return dict(
            key=str(uuid4()),
            version=0,
            kind="add",
            product=self.d.products[0].pk,
            quantity="1.000",
            **extra,
        )

    def test_same_operation_concurrently_has_one_effect_and_one_receipt(self):
        data = self.payload()
        outcomes = self.threads(
            lambda: self.mutation(data), lambda: self.mutation(data)
        )
        self.assertNotIn("conflict", outcomes)
        self.assertEqual(sorted(x["replayed"] for x in outcomes), [False, True])
        self.assertEqual(self.sale.lines.count(), 2)
        self.assertEqual(CartOperation.objects.count(), 1)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 1)

    def test_two_tabs_same_version_one_accepts_other_conflicts(self):
        a, b = self.payload(), self.payload()
        outcomes = self.threads(lambda: self.mutation(a), lambda: self.mutation(b))
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(self.sale.lines.count(), 2)
        self.assertEqual(CartOperation.objects.count(), 1)

    def checkout(self, expected=0):
        sale = Sale.objects.get(pk=self.sale.pk)
        return run_checkout(
            business=self.d.business,
            sale=sale,
            user=self.d.user,
            intents=[
                PaymentIntent(
                    self.d.methods[0].pk, self.sale.total_amount, self.payment_key
                )
            ],
            series_id=None,
            billing_key=self.billing_key,
            allow_split=True,
            expected_version=expected,
        )

    def test_edit_racing_checkout_never_charges_an_unvalidated_cart(self):
        self.payment_key, self.billing_key = uuid4(), uuid4()
        data = self.payload()
        outcomes = self.threads(lambda: self.mutation(data), self.checkout)
        self.assertEqual(outcomes.count("conflict"), 1)
        self.sale.refresh_from_db()
        if self.sale.status == "completed":
            self.assertEqual(self.sale.lines.count(), 1)
            self.assertEqual(
                Payment.objects.get(sale=self.sale).amount, self.sale.total_amount
            )
        else:
            self.assertEqual(self.sale.lines.count(), 2)
            self.assertFalse(Payment.objects.filter(sale=self.sale).exists())

    def test_legacy_edit_uses_same_sale_lock_as_checkout(self):
        self.payment_key, self.billing_key = uuid4(), uuid4()
        outcomes = self.threads(
            lambda: update_sale_line(
                business=self.d.business,
                sale=self.sale,
                line=self.lines[0],
                quantity="2",
                user=self.d.user,
            ),
            self.checkout,
        )
        self.assertEqual(outcomes.count("conflict"), 1)
        self.sale.refresh_from_db()
        self.assertEqual(
            Payment.objects.filter(sale=self.sale).exists(),
            self.sale.status == "completed",
        )

    def test_payment_is_outside_completion_transaction(self):
        self.payment_key, self.billing_key = uuid4(), uuid4()
        from apps.payments.services import register_sale_payment

        def inspect(**kwargs):
            self.assertFalse(connection.in_atomic_block)
            return register_sale_payment(**kwargs)

        with patch("apps.sales.checkout.register_sale_payment", side_effect=inspect):
            self.assertTrue(self.checkout()["complete"])

    def test_double_confirm_same_version_preserves_payment_and_stock_once(self):
        self.payment_key, self.billing_key = uuid4(), uuid4()
        outcomes = self.threads(self.checkout, self.checkout)
        self.assertTrue(any(isinstance(x, dict) and x["complete"] for x in outcomes))
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), 1)
        self.assertEqual(
            self.d.products[0].inventory_items.get(store=self.d.store).current_stock,
            Decimal("999.000"),
        )

    def batch(self, payload):
        return mutate_batch(
            business=self.d.business,
            store=self.d.store,
            sale_id=self.sale.pk,
            user=self.d.user,
            data=payload,
        )

    def test_same_batch_concurrent_replay_is_atomic(self):
        payload = dict(version=0, operations=[self.payload(), self.payload()])
        outcomes = self.threads(
            lambda: self.batch(payload), lambda: self.batch(payload)
        )
        self.assertNotIn("conflict", outcomes)
        self.assertEqual(self.sale.lines.count(), 3)
        self.assertEqual(CartOperation.objects.count(), 2)
        self.assertEqual(
            sorted(x["results"][0]["replayed"] for x in outcomes), [False, True]
        )

    def test_two_batches_same_revision_one_conflicts(self):
        a = dict(version=0, operations=[self.payload(), self.payload()])
        b = dict(version=0, operations=[self.payload(), self.payload()])
        outcomes = self.threads(lambda: self.batch(a), lambda: self.batch(b))
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(self.sale.lines.count(), 3)
        self.assertEqual(CartOperation.objects.count(), 2)

    def test_batch_racing_checkout_never_charges_stale_total(self):
        self.payment_key, self.billing_key = uuid4(), uuid4()
        payload = dict(version=0, operations=[self.payload(), self.payload()])
        outcomes = self.threads(lambda: self.batch(payload), self.checkout)
        self.assertEqual(outcomes.count("conflict"), 1)
        self.sale.refresh_from_db()
        if self.sale.status == "completed":
            self.assertEqual(self.sale.lines.count(), 1)
            self.assertEqual(
                Payment.objects.get(sale=self.sale).amount, self.sale.total_amount
            )
        else:
            self.assertEqual(self.sale.lines.count(), 3)
            self.assertFalse(Payment.objects.filter(sale=self.sale).exists())
