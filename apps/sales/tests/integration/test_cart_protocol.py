"""Cart protocol invariants with synthetic fixtures; no external fiscal traffic."""

import json
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError

from apps.sales.cart import CartConflict, mutate
from apps.sales.checkout import CheckoutConflict, PaymentIntent, run_checkout
from apps.sales.models import CartOperation
from apps.sales.services import update_sale_header, update_sale_line
from tests.performance.dataset import Dataset


class CartProtocolTests(TestCase):
    def setUp(self):
        self.d = Dataset(3, label="cart-protocol")
        self.sale, self.lines = self.d.sale(1)
        self.client.force_login(self.d.user)
        self.url = reverse("sales:sale_cart_sync", args=[self.d.store.pk, self.sale.pk])

    def data(self, kind="add", **extra):
        self.sale.refresh_from_db()
        return {
            "key": str(uuid4()),
            "version": self.sale.cart_version,
            "kind": kind,
            "product": self.d.products[0].pk,
            "quantity": "1.000",
            **extra,
        }

    def mutate(self, data):
        return mutate(
            business=self.d.business,
            store=self.d.store,
            sale_id=self.sale.pk,
            user=self.d.user,
            data=data,
        )

    def post(self, data):
        return self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )

    def test_lost_add_response_replay_and_normalized_quantity(self):
        data = self.data()
        first = self.mutate(data)
        data["quantity"] = "1"
        replay = self.mutate(data)
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["line"], replay["line"])
        self.assertEqual(self.sale.lines.count(), 2)
        self.assertEqual(CartOperation.objects.count(), 1)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 1)

    def test_reused_key_with_changed_payload_is_rejected(self):
        data = self.data()
        self.mutate(data)
        data["quantity"] = "2"
        with self.assertRaises(CartConflict):
            self.mutate(data)
        self.assertEqual(self.sale.lines.count(), 2)

    def test_two_tabs_stale_absolute_quantity_cannot_overwrite(self):
        data = self.data("quantity", line=self.lines[0].pk, quantity="2")
        self.assertEqual(self.post(data).status_code, 200)
        stale = {**data, "key": str(uuid4()), "quantity": "3"}
        self.assertEqual(self.post(stale).status_code, 409)
        self.lines[0].refresh_from_db()
        self.assertEqual(self.lines[0].quantity, Decimal("2.000"))

    def test_noop_has_receipt_but_does_not_advance_version(self):
        data = self.data("quantity", line=self.lines[0].pk, quantity="1")
        self.assertEqual(self.mutate(data)["cart"]["version"], 0)
        self.assertTrue(self.mutate(data)["replayed"])
        self.assertEqual(CartOperation.objects.count(), 1)

    def test_delete_replay_after_line_disappears(self):
        data = self.data("delete", line=self.lines[0].pk)
        self.mutate(data)
        self.assertTrue(self.mutate(data)["replayed"])
        self.assertFalse(self.sale.lines.exists())
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 1)

    def test_failed_mutation_rolls_back_receipt_version_lines(self):
        with patch(
            "apps.sales.cart.add_sale_line", side_effect=ValidationError("Rejected")
        ):
            self.assertEqual(self.post(self.data()).status_code, 422)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 0)
        self.assertEqual(self.sale.lines.count(), 1)
        self.assertFalse(CartOperation.objects.exists())

    def test_invalid_payloads_and_inactive_product(self):
        for quantity in ("NaN", "Infinity", "0", "-1", "1.0001", None):
            with self.subTest(quantity=quantity):
                self.assertEqual(
                    self.post(self.data(quantity=quantity)).status_code, 422
                )
        self.d.products[0].is_active = False
        self.d.products[0].save()
        self.assertEqual(self.post(self.data()).status_code, 422)
        self.assertEqual(self.sale.lines.count(), 1)

    def test_scope_store_and_business(self):
        other = Dataset(1, label="other-cart")
        other_sale, _ = other.sale(0)
        for store, sale in ((self.d.store, other_sale), (other.store, self.sale)):
            url = reverse("sales:sale_cart_sync", args=[store.pk, sale.pk])
            self.assertIn(self.client.get(url).status_code, (403, 404))
            self.assertIn(
                self.client.post(
                    url, json.dumps(self.data()), content_type="application/json"
                ).status_code,
                (403, 404),
            )
        self.assertFalse(CartOperation.objects.exists())

    def test_legacy_price_and_header_changes_advance_version(self):
        update_sale_line(
            business=self.d.business,
            sale=self.sale,
            line=self.lines[0],
            quantity="2",
            user=self.d.user,
        )
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 1)
        update_sale_header(
            business=self.d.business,
            sale=self.sale,
            customer=None,
            document_type_requested="none",
            updated_by=self.d.user,
        )
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 2)

    def test_header_response_reports_only_its_accepted_revision(self):
        url = reverse("sales:sale_header_update", args=[self.d.store.pk, self.sale.pk])
        for previous, current in ((0, 1), (1, 1)):
            response = self.client.post(
                url,
                {"customer": "", "document_type_requested": "invoice"},
                HTTP_HX_REQUEST="true",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["X-Sales-Cart-Previous-Version"], str(previous))
            self.assertEqual(response["X-Sales-Cart-Version"], str(current))

    def test_stale_checkout_never_calls_payment_or_completion(self):
        self.mutate(self.data())
        with (
            patch("apps.sales.checkout.complete_sale") as complete,
            patch("apps.sales.checkout.register_sale_payment") as payment,
        ):
            with self.assertRaises(CheckoutConflict):
                run_checkout(
                    business=self.d.business,
                    sale=self.sale,
                    user=self.d.user,
                    intents=[],
                    series_id=None,
                    billing_key=uuid4(),
                    allow_split=True,
                    expected_version=0,
                )
        complete.assert_not_called()
        payment.assert_not_called()

    def test_http_checkout_requires_version(self):
        url = reverse("sales:sale_checkout", args=[self.d.store.pk, self.sale.pk])
        self.assertEqual(self.client.post(url, {}).status_code, 409)
        self.assertContains(self.client.get(url), 'name="cart_version" value="0"')

    def test_completed_checkout_replay_preserves_existing_payment_idempotency(self):
        key, billing_key = uuid4(), uuid4()
        kwargs = dict(
            business=self.d.business,
            sale=self.sale,
            user=self.d.user,
            intents=[PaymentIntent(self.d.methods[0].pk, self.sale.total_amount, key)],
            series_id=None,
            billing_key=billing_key,
            allow_split=True,
            expected_version=0,
        )
        first = run_checkout(**kwargs)
        self.assertTrue(first["complete"])
        self.assertTrue(run_checkout(**kwargs)["complete"])
        self.assertEqual(self.sale.payments.count(), 1)

    def test_receipt_failure_rolls_back_domain_mutation(self):
        with patch(
            "apps.sales.cart.CartOperation.objects.create",
            side_effect=ValidationError("Receipt failed"),
        ):
            self.assertEqual(self.post(self.data()).status_code, 422)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.cart_version, 0)
        self.assertEqual(self.sale.lines.count(), 1)
        self.assertFalse(CartOperation.objects.exists())

    def test_read_returns_only_this_sales_requested_receipts(self):
        data = self.data()
        result = self.mutate(data)
        response = self.client.get(
            self.url, {"pending": data["key"] + "," + str(uuid4())}
        )
        self.assertEqual(
            response.json()["receipts"], [{"key": data["key"], "line": result["line"]}]
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_distinct_commercial_snapshots_have_distinct_visual_groups(self):
        result = self.mutate(self.data())
        first, second = list(self.sale.lines.order_by("pk"))
        self.assertEqual(
            result["cart"]["lines"][0]["group"], result["cart"]["lines"][1]["group"]
        )
        update_sale_line(
            business=self.d.business,
            sale=self.sale,
            line=second,
            quantity="1",
            unit_base_price="11",
            user=self.d.user,
        )
        snapshot = self.client.get(self.url).json()["cart"]
        self.assertNotEqual(
            snapshot["lines"][0]["group"], snapshot["lines"][1]["group"]
        )
        first.refresh_from_db()
        self.assertEqual(first.unit_base_price, Decimal("10.00"))

    def test_manual_editor_cannot_save_over_a_newer_quantity(self):
        self.mutate(self.data("quantity", line=self.lines[0].pk, quantity="2"))
        with self.assertRaises(CartConflict):
            update_sale_line(
                business=self.d.business,
                sale=self.sale,
                line=self.lines[0],
                quantity="1",
                unit_base_price="11",
                user=self.d.user,
                expected_version=0,
            )
        self.lines[0].refresh_from_db()
        self.assertEqual(self.lines[0].quantity, Decimal("2.000"))
        self.assertEqual(self.lines[0].unit_base_price, Decimal("10.00"))

    def test_frontend_can_be_disabled_without_disabling_server_protocol(self):
        from django.test import override_settings

        url = reverse("sales:sale_detail", args=[self.d.store.pk, self.sale.pk])
        with override_settings(TPV_OPTIMISTIC_CART=False):
            response = self.client.get(url)
            self.assertNotContains(response, "data-cart-sync=")
            self.assertEqual(self.post(self.data()).status_code, 200)
        with override_settings(TPV_OPTIMISTIC_CART=True):
            self.assertContains(self.client.get(url), "data-cart-sync=")
