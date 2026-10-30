"""P01: historical payment inputs cannot produce new economic intents."""

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.billing.models import BillingDocument, BillingSeries
from apps.business_config.models import BusinessProfile
from apps.payments.models import Payment
from apps.inventory.models import StockMovement
from apps.sales import checkout
from apps.sales.tests.factories import (
    create_sales_store,
    create_sales_user,
    create_store_access,
)
from apps.users.models import RoleChoices
from tests.performance.dataset import Dataset
from tests.performance.phase3_harness import payload, url


class AuthorizedBillingRecoveryTests(TestCase):
    def setUp(self):
        self.d = Dataset(1, label="p01-authorized")
        self.d.settings.allow_split_payments = True
        self.d.settings.save()
        self.sale, _ = self.d.sale(1)
        self.client.force_login(self.d.user)

    def paid(self, split=False):
        body = payload(self.d, self.sale, "split" if split else "card")
        with patch(
            "apps.sales.checkout.issue_sale_document",
            side_effect=ValidationError("Synthetic Billing failure"),
        ):
            self.client.post(url(self.sale), body)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.payment_status, "paid")
        self.assertFalse(BillingDocument.objects.filter(sale=self.sale).exists())
        return body

    def assert_effects(self, payments=1, documents=1):
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, Decimal("0.00"))
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), payments)
        self.assertEqual(
            BillingDocument.objects.filter(sale=self.sale).count(), documents
        )
        self.assertEqual(StockMovement.objects.filter(sale=self.sale).count(), 1)

    def test_single_split_inactive_methods_and_identical_retry(self):
        for split in (False, True):
            with self.subTest(split=split):
                if split:
                    self.sale = self.d.sale(1)[0]
                body = self.paid(split)
                for method in self.d.methods:
                    method.is_active = False
                    method.save(update_fields=["is_active"])
                # Paid routing ignores unused payment fields, not fiscal identity.
                with patch("apps.sales.checkout.register_sale_payment") as payment:
                    for _ in range(2):
                        response = self.client.post(
                            url(self.sale), body, HTTP_HX_REQUEST="true"
                        )
                        self.assertContains(response, "VENTA COMPLETADA")
                payment.assert_not_called()
                self.assert_effects(2 if split else 1)
                self.assertEqual(
                    str(BillingDocument.objects.get(sale=self.sale).idempotency_key),
                    body["billing_idempotency_key"],
                )
                for method in self.d.methods:
                    method.is_active = True
                    method.save(update_fields=["is_active"])

    def test_forged_paid_flag_cannot_skip_pending_payment(self):
        body = payload(self.d, self.sale)
        body.update(
            mode="billing_only", pending_amount="0", payment_status="paid", method=""
        )
        response = self.client.post(url(self.sale), body, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Payment.objects.filter(sale=self.sale).exists())
        self.assertFalse(BillingDocument.objects.filter(sale=self.sale).exists())

    def test_persisted_payment_balance_rechecked_under_sale_lock(self):
        body = self.paid()
        original = checkout.run_checkout

        def change(**kwargs):
            Payment.objects.filter(sale=self.sale).update(status="cancelled")
            return original(**kwargs)

        with (
            patch("apps.sales.views.run_checkout", change),
            patch("apps.sales.checkout.issue_sale_document") as issue,
        ):
            response = self.client.post(url(self.sale), body, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 409)
        issue.assert_not_called()
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), 1)

    def test_stale_version_and_missing_identity_do_not_issue(self):
        body = self.paid()
        for changed, code in (
            ({"cart_version": -1}, 409),
            ({"billing_idempotency_key": "bad"}, 422),
        ):
            response = self.client.post(
                url(self.sale), {**body, **changed}, HTTP_HX_REQUEST="true"
            )
            self.assertEqual(response.status_code, code)
            self.assert_effects(documents=0)

    def test_existing_document_inactive_series_replay_and_incompatible_identity(self):
        body = self.paid()
        self.assertContains(self.client.post(url(self.sale), body), "VENTA COMPLETADA")
        document = BillingDocument.objects.get(sale=self.sale)
        BillingSeries.objects.filter(pk=document.series_id).update(is_active=False)
        for method in self.d.methods:
            type(method).objects.filter(pk=method.pk).update(is_active=False)
        self.assertContains(self.client.post(url(self.sale), body), "VENTA COMPLETADA")
        response = self.client.post(
            url(self.sale),
            {**body, "billing_idempotency_key": str(uuid4())},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 409)
        self.assert_effects()
        self.assertEqual(
            BillingDocument.objects.get(sale=self.sale).number, document.number
        )

    def test_fiscal_validation_remains_authoritative(self):
        body = self.paid()
        BusinessProfile.objects.filter(business=self.d.business).update(legal_name="")
        response = self.client.post(url(self.sale), body)
        self.assertContains(response, "perfil fiscal")
        self.assert_effects(documents=0)

    def test_authorization_store_and_business_are_not_bypassed(self):
        body = self.paid()
        user = create_sales_user(business=self.d.business, role=RoleChoices.CASHIER)
        access = create_store_access(
            business=self.d.business, user=user, store=self.d.store
        )
        self.client.force_login(user)
        self.client.get(url(self.sale))
        access.can_sell = False
        access.save(update_fields=["can_sell"])
        self.assertEqual(self.client.post(url(self.sale), body).status_code, 403)
        self.client.force_login(self.d.user)
        other = create_sales_store(business=self.d.business)
        self.assertEqual(
            self.client.post(
                reverse("sales:sale_checkout", args=[other.pk, self.sale.pk]), body
            ).status_code,
            404,
        )
        foreign = Dataset(1, label="p01-foreign")
        self.assertEqual(
            self.client.post(url(foreign.sale(1)[0]), body).status_code, 403
        )
        self.assert_effects(documents=0)
