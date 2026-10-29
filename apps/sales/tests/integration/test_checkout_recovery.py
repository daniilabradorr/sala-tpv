"""Presentation regressions; H01's economic routing remains unchanged."""

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

    def test_h01_remains_rejected_but_error_is_visible_without_javascript(self):
        body = payload(self.dataset, self.sale)
        with patch(
            "apps.sales.checkout.issue_sale_document",
            side_effect=ValidationError("Fallo fiscal sintético"),
        ):
            self.client.post(url(self.sale), body)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.payment_status, "paid")
        card = next(m for m in self.dataset.methods if m.code == "card")
        card.is_active = False
        card.save()
        response = self.client.post(url(self.sale), body, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 422)
        self.assertIn("method", response.context["form"].errors)
        self.assertContains(response, "data-checkout-error-summary", status_code=422)
        self.assertContains(
            response, "El cobro se ha registrado correctamente.", status_code=422
        )
        self.assertContains(response, "Consultar estado actualizado", status_code=422)
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), 1)
        self.assertFalse(BillingDocument.objects.filter(sale=self.sale).exists())
        # Existing GET and billing-only request, not a new routing contract.
        fresh = self.client.get(url(self.sale))
        body.update(
            method="",
            payment_idempotency_key=str(
                fresh.context["form"]["payment_idempotency_key"].value()
            ),
            billing_idempotency_key=str(
                fresh.context["form"]["billing_idempotency_key"].value()
            ),
        )
        success = self.client.post(url(self.sale), body)
        self.assertContains(success, "VENTA COMPLETADA")
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), 1)
        self.assertEqual(BillingDocument.objects.filter(sale=self.sale).count(), 1)

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
