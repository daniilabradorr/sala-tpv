"""Transport batching preserves existing Sales effects and independent receipts."""

import json
from io import StringIO
from uuid import uuid4
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from apps.sales.models import CartOperation
from tests.performance.dataset import Dataset


class CartBatchTests(TestCase):
    def setUp(self):
        self.d = Dataset(50, label="cart-batch")
        self.sale, _ = self.d.sale(0)
        self.client.force_login(self.d.user)
        self.url = reverse("sales:sale_cart_sync", args=[self.d.store.pk, self.sale.pk])

    def add(self, index=0):
        return dict(
            key=str(uuid4()),
            kind="add",
            product=self.d.products[index].pk,
            quantity="1.000",
        )

    def post(self, operations, version=0):
        return self.client.post(
            self.url,
            json.dumps(dict(version=version, operations=operations)),
            content_type="application/json",
        )

    def test_one_twenty_fifty_separate_snapshots_receipts_and_replay(self):
        for count in (1, 20, 50):
            with self.subTest(count=count):
                self.sale.refresh_from_db()
                version = self.sale.cart_version
                before = self.sale.lines.count()
                ops = [self.add(i) for i in range(count)]
                result = self.post(ops, version)
                self.assertEqual(result.status_code, 200, result.content)
                self.assertEqual(self.sale.lines.count(), before + count)
                self.assertEqual(len(result.json()["results"]), count)
                self.assertTrue(
                    all(not x["replayed"] for x in result.json()["results"])
                )
                replay = self.post(ops, version)
                self.assertEqual(replay.status_code, 200)
                self.assertTrue(all(x["replayed"] for x in replay.json()["results"]))
                self.assertEqual(self.sale.lines.count(), before + count)
                self.sale.refresh_from_db()
                self.assertEqual(self.sale.cart_version, version + count)
        self.assertEqual(CartOperation.objects.count(), 71)

    def test_provisional_dependencies_add_quantity_delete(self):
        add = self.add()
        ops = [
            add,
            dict(
                key=str(uuid4()), kind="quantity", line_ref=add["key"], quantity="2.125"
            ),
            dict(key=str(uuid4()), kind="delete", line_ref=add["key"]),
        ]
        self.assertEqual(self.post(ops).status_code, 200)
        self.assertFalse(self.sale.lines.exists())
        self.assertEqual(CartOperation.objects.count(), 3)
        self.assertEqual(self.post(ops).status_code, 200)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 3)

    def test_middle_rejection_rolls_back_every_effect(self):
        ops = [self.add(), {**self.add(), "quantity": "-1"}]
        self.assertEqual(self.post(ops).status_code, 422)
        self.assertFalse(self.sale.lines.exists())
        self.assertFalse(CartOperation.objects.exists())
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 0)
        ops[1]["quantity"] = "1"
        self.assertEqual(self.post(ops).status_code, 200)

    def test_changed_content_replay_cannot_mutate(self):
        ops = [self.add(), self.add()]
        self.assertEqual(self.post(ops).status_code, 200)
        ops[1]["quantity"] = "2"
        self.assertEqual(self.post(ops).status_code, 409)
        self.assertEqual(self.sale.lines.count(), 2)

    def test_mixed_accepted_and_new_is_not_partially_committed(self):
        first = self.add()
        self.assertEqual(self.post([first]).status_code, 200)
        response = self.post([first, self.add()])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "key")
        self.assertEqual(self.sale.lines.count(), 1)
        self.assertEqual(CartOperation.objects.count(), 1)

    def test_stale_version_and_invalid_batches_have_no_effects(self):
        self.assertEqual(self.post([self.add()], 1).status_code, 409)
        for ops in ([], [self.add()] * 2, [self.add() for _ in range(51)], [None]):
            self.assertEqual(self.post(ops).status_code, 422)
        self.assertFalse(CartOperation.objects.exists())

    def test_foreign_sale_reference_rejected_and_rolled_back(self):
        other, _ = self.d.sale(0)
        key = str(uuid4())
        from apps.sales.cart import mutate

        receipt = mutate(
            business=self.d.business,
            store=self.d.store,
            sale_id=other.pk,
            user=self.d.user,
            data={**self.add(), "key": key, "version": 0},
        )
        self.assertIsNotNone(receipt["line"])
        self.assertEqual(
            self.post(
                [self.add(), dict(key=str(uuid4()), kind="delete", line_ref=key)]
            ).status_code,
            422,
        )
        self.assertFalse(self.sale.lines.exists())

    def test_noop_receipt_replays_without_increment(self):
        add = self.add()
        ops = [
            add,
            dict(
                key=str(uuid4()), kind="quantity", line_ref=add["key"], quantity="1.000"
            ),
        ]
        self.assertEqual(self.post(ops).status_code, 200)
        self.assertEqual(self.post(ops).status_code, 200)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 1)
        self.assertEqual(CartOperation.objects.count(), 2)

    def test_protocol_and_session_identity_are_checked_before_effects(self):
        response = self.client.get(self.url)
        self.assertEqual(response.json()["protocol"], 2)
        self.assertEqual(response.json()["user_id"], self.d.user.pk)
        response = self.client.post(
            self.url,
            json.dumps(dict(version=0, operations=[self.add()])),
            content_type="application/json",
            HTTP_X_SALES_CART_USER=str(self.d.user.pk + 999),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.sale.lines.exists())
        self.assertFalse(CartOperation.objects.exists())

    def test_metrics_are_aggregate_and_read_only(self):
        self.post([self.add()])
        out = StringIO()
        call_command("cart_receipt_stats", exact=True, stdout=out)
        metrics = json.loads(out.getvalue())
        self.assertEqual(metrics["exact"]["count"], 1)
        self.assertFalse(metrics["writes"])
        self.assertNotIn("business", out.getvalue())
        self.assertEqual(CartOperation.objects.count(), 1)
