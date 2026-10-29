"""Presentation regressions retained, with H01 routing authorized by P01."""

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.billing.models import BillingDocument
from apps.payments.models import Payment
from tests.performance.dataset import Dataset
from tests.performance.phase3_harness import payload, url


class CheckoutRecoveryPresentationTests(TestCase):
    def setUp(self):
        self.dataset = Dataset(1, label="checkout-recovery-presentation")
        self.sale, _ = self.dataset.sale(1)
        self.client.force_login(self.dataset.user)

    def test_h01_recovers_with_inactive_method_without_another_payment(self):
        body = payload(self.dataset, self.sale)
        with patch(
            "apps.sales.checkout.issue_sale_document",
            side_effect=ValidationError("Fallo fiscal sintético"),
        ):
            self.client.post(url(self.sale), body)
        card = next(m for m in self.dataset.methods if m.code == "card")
        card.is_active = False
        card.save(update_fields=["is_active"])
        with patch("apps.sales.checkout.register_sale_payment") as payment:
            response = self.client.post(url(self.sale), body, HTTP_HX_REQUEST="true")
        self.assertContains(response, "VENTA COMPLETADA")
        payment.assert_not_called()
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), 1)
        document = BillingDocument.objects.get(sale=self.sale)
        self.assertEqual(str(document.idempotency_key), body["billing_idempotency_key"])

    def test_get_declares_only_authoritative_display_state(self):
        response = self.client.get(url(self.sale), HTTP_HX_REQUEST="true")
        self.assertContains(response, 'data-checkout-complete="false"')
        self.assertContains(response, 'data-payment-status="unpaid"')
        self.assertNotContains(response, "data-checkout-error-summary")
        self.assertNotContains(response, "data-nx-checkout-status")

    def test_single_payment_does_not_validate_a_missing_split_management_form(self):
        response = self.client.post(url(self.sale), payload(self.dataset, self.sale))
        self.assertContains(response, "VENTA COMPLETADA")
        self.assertNotContains(response, "ManagementForm")

    def test_hidden_uuid_validation_errors_are_presented_without_changing_payment(self):
        body = payload(self.dataset, self.sale)
        body["billing_idempotency_key"] = "invalid"
        response = self.client.post(url(self.sale), body, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "data-checkout-error-summary", status_code=422)
        self.assertFalse(Payment.objects.filter(sale=self.sale).exists())

    def test_cancelled_sale_is_not_presented_as_open_or_chargeable(self):
        self.sale.status = "cancelled"
        self.sale.save(update_fields=["status", "updated_at"])
        response = self.client.get(url(self.sale), HTTP_HX_REQUEST="true")
        self.assertContains(response, "Venta cancelada")
        self.assertNotContains(response, "data-checkout-form")
        self.assertFalse(Payment.objects.filter(sale=self.sale).exists())
