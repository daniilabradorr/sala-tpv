"""P02 explicit recovery preserves history and delegates money to Payments."""

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.billing.models import BillingDocument
from apps.cash_register.models import CashRegister, CashSession, CashMovement
from apps.cash_register.services import CashRegisterService
from apps.inventory.models import StockMovement, InventoryItem
from apps.payments.models import Payment
from apps.payments.services import register_sale_payment
from apps.sales.services import complete_sale
from apps.sales.tests.factories import (
    create_sales_store,
    create_sales_user,
    create_store_access,
)
from apps.users.models import RoleChoices
from tests.performance.dataset import Dataset
from tests.performance.phase3_harness import payload, url


class AuthorizedPendingPaymentTests(TestCase):
    def setUp(self):
        self.d = Dataset(1, label="p02-authorized")
        self.d.settings.allow_split_payments = True
        self.d.settings.save()
        self.sale, _ = self.d.sale(1)
        complete_sale(business=self.d.business, sale=self.sale, closed_by=self.d.user)
        self.sale.refresh_from_db()
        self.cash, self.card = self.d.methods
        self.half = (self.sale.total_amount / 2).quantize(Decimal(".01"))
        self.historical = register_sale_payment(
            business=self.d.business,
            sale_id=self.sale.pk,
            method_id=self.cash.pk,
            amount=self.half,
            user=self.d.user,
            idempotency_key=uuid4(),
            cash_session_id=self.d.session.pk,
        )
        CashRegisterService().close_cash_session(
            business=self.d.business,
            store_id=self.d.store.pk,
            cash_register_id=self.d.register.pk,
            cash_session_id=self.d.session.pk,
            user=self.d.user,
            counted_cash_amount=self.half,
        )
        self.register = CashRegister.objects.create(
            business=self.d.business,
            store=self.d.store,
            name="Recovery",
            code="RECOVERY",
        )
        self.session = CashSession.objects.create(
            business=self.d.business,
            store=self.d.store,
            cash_register=self.register,
            opened_by=self.d.user,
        )
        self.client.force_login(self.d.user)
        self.sale.refresh_from_db()
        self.body = {
            **payload(self.d, self.sale),
            "amount": str(self.sale.pending_amount),
            "recovery_cash_session": self.session.pk,
            "recovery_confirm": "on",
        }

    def assert_history(self, payments=2, documents=1):
        self.sale.refresh_from_db()
        self.historical.refresh_from_db()
        self.d.session.refresh_from_db()
        self.assertEqual(self.sale.cash_session_id, self.d.session.pk)
        self.assertEqual(self.sale.cash_register_id, self.d.register.pk)
        self.assertEqual(self.historical.cash_session_id, self.d.session.pk)
        self.assertEqual(self.d.session.status, "closed")
        self.assertEqual(
            CashMovement.objects.filter(cash_session=self.d.session).count(), 1
        )
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), payments)
        self.assertEqual(
            BillingDocument.objects.filter(sale=self.sale).count(), documents
        )
        self.assertEqual(StockMovement.objects.filter(sale=self.sale).count(), 1)
        self.assertEqual(
            InventoryItem.objects.get(product=self.d.products[0]).current_stock,
            Decimal("999.000"),
        )
        if documents:
            doc = BillingDocument.objects.get(sale=self.sale)
            self.assertEqual(doc.cash_session_id, self.d.session.pk)
            self.assertEqual(doc.cash_register_id, self.d.register.pk)

    def test_explicit_get_and_card_or_cash_recovery(self):
        response = self.client.get(url(self.sale))
        self.assertContains(response, "data-payment-recovery-form")
        self.assertIsNone(response.context["form"]["recovery_cash_session"].value())
        self.assertContains(response, str(self.historical.idempotency_key))
        body = {**self.body, "method": self.cash.pk}
        for _ in range(2):
            self.assertContains(
                self.client.post(url(self.sale), body), "VENTA COMPLETADA"
            )
        new = Payment.objects.exclude(pk=self.historical.pk).get(sale=self.sale)
        self.assertEqual(new.cash_session_id, self.session.pk)
        self.assertEqual(str(new.idempotency_key), body["payment_idempotency_key"])
        self.assertEqual(
            CashMovement.objects.get(payment=new).cash_session_id, self.session.pk
        )
        self.assert_history()

    def test_confirmation_and_destination_are_required(self):
        for changes in (
            {"recovery_confirm": ""},
            {"recovery_cash_session": ""},
            {"recovery_cash_session": self.d.session.pk},
            {"amount": "99.00"},
        ):
            response = self.client.post(
                url(self.sale), {**self.body, **changes}, HTTP_HX_REQUEST="true"
            )
            self.assertIn(response.status_code, (409, 422))
            self.assert_history(payments=1, documents=0)

    def test_foreign_store_business_and_inactive_destination_are_rejected(self):
        foreign = Dataset(1, label="p02-other-business")
        otherstore = create_sales_store(business=self.d.business)
        register = CashRegister.objects.create(
            business=self.d.business, store=otherstore, name="Other", code="OTHER"
        )
        other = CashSession.objects.create(
            business=self.d.business,
            store=otherstore,
            cash_register=register,
            opened_by=self.d.user,
        )
        for session in (foreign.session, other):
            response = self.client.post(
                url(self.sale),
                {**self.body, "recovery_cash_session": session.pk},
                HTTP_HX_REQUEST="true",
            )
            self.assertEqual(response.status_code, 422)
        self.register.is_active = False
        self.register.save(update_fields=["is_active"])
        self.assertEqual(
            self.client.post(
                url(self.sale), self.body, HTTP_HX_REQUEST="true"
            ).status_code,
            422,
        )
        self.assert_history(payments=1, documents=0)

    def test_confirmed_key_cannot_move_to_another_session(self):
        response = self.client.post(
            url(self.sale),
            {
                **self.body,
                "payment_idempotency_key": str(self.historical.idempotency_key),
                "method": self.cash.pk,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assert_history(payments=1, documents=0)

    def test_lost_permission_and_stale_version(self):
        user = create_sales_user(business=self.d.business, role=RoleChoices.CASHIER)
        access = create_store_access(
            business=self.d.business, user=user, store=self.d.store
        )
        self.client.force_login(user)
        self.client.get(url(self.sale))
        access.can_sell = False
        access.save(update_fields=["can_sell"])
        self.assertEqual(self.client.post(url(self.sale), self.body).status_code, 403)
        self.client.force_login(self.d.user)
        self.assertEqual(
            self.client.post(
                url(self.sale),
                {**self.body, "cart_version": -1},
                HTTP_HX_REQUEST="true",
            ).status_code,
            409,
        )
        self.assert_history(payments=1, documents=0)

    def test_partial_piece_uses_fresh_next_intent_and_no_overpayment(self):
        body = {**self.body, "amount": "3.00"}
        response = self.client.post(url(self.sale), body)
        self.assertContains(response, "data-payment-recovery-form")
        self.assertNotEqual(
            str(response.context["form"]["payment_idempotency_key"].value()),
            body["payment_idempotency_key"],
        )
        self.assertEqual(
            response["X-Netxodo-Confirmed-Payment"], body["payment_idempotency_key"]
        )
        self.assertEqual(self.client.post(url(self.sale), body).status_code, 200)
        self.assert_history(payments=2, documents=0)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, self.half - Decimal("3.00"))
        response = self.client.post(
            url(self.sale),
            {**body, "payment_idempotency_key": str(uuid4()), "amount": str(self.half)},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 409)
        self.assert_history(payments=2, documents=0)

    def test_billing_failure_after_recovery_does_not_repeat_payment(self):
        with patch(
            "apps.sales.checkout.issue_sale_document",
            side_effect=ValidationError("Synthetic Billing failure"),
        ):
            response = self.client.post(url(self.sale), self.body)
        self.assertContains(response, "REINTENTAR EMISIÓN")
        self.assertNotContains(response, "data-payment-recovery-form")
        self.assert_history(documents=0)
        self.card.is_active = False
        self.card.save(update_fields=["is_active"])
        self.assertContains(
            self.client.post(url(self.sale), self.body), "VENTA COMPLETADA"
        )
        self.assert_history()

    def test_pending_amount_is_read_from_persisted_payments(self):
        # Deliberately stale cache: display and guards must still use Payments.
        type(self.sale).objects.filter(pk=self.sale.pk).update(
            pending_amount=Decimal("0.00"), payment_status="paid"
        )
        response = self.client.get(url(self.sale))
        self.assertEqual(response.context["recovery_pending_amount"], self.half)
        self.assertContains(response, "data-payment-recovery-form")
        self.assertContains(
            self.client.post(url(self.sale), self.body), "VENTA COMPLETADA"
        )
        self.assert_history()

    def test_split_transition_preserves_only_the_unconfirmed_part_key(self):
        body = payload(self.d, self.sale, "split")
        body["payments-0-idempotency_key"] = str(self.historical.idempotency_key)
        pending_key = body["payments-1-idempotency_key"]
        body["payments-1-amount"] = str(self.half)
        response = self.client.post(url(self.sale), body, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            str(response.context["form"]["payment_idempotency_key"].value()),
            pending_key,
        )
        self.assertEqual(
            str(response.context["form"]["amount"].value()), str(self.half)
        )
        confirmed = {
            **body,
            "mode": "single",
            "method": self.card.pk,
            "amount": str(self.half),
            "payment_idempotency_key": pending_key,
            "recovery_cash_session": self.session.pk,
            "recovery_confirm": "on",
        }
        self.assertContains(
            self.client.post(url(self.sale), confirmed), "VENTA COMPLETADA"
        )
        self.assertEqual(
            Payment.objects.get(
                business=self.d.business, idempotency_key=pending_key
            ).cash_session_id,
            self.session.pk,
        )
        self.assert_history()

    def test_cached_paid_state_cannot_hide_balance_when_document_already_exists(self):
        from apps.billing.services import issue_sale_document
        from apps.billing.models import BillingSeries

        document = issue_sale_document(
            business=self.d.business,
            sale_id=self.sale.pk,
            series_id=BillingSeries.objects.get(
                business=self.d.business, document_type="F2"
            ).pk,
            issued_by=self.d.user,
            idempotency_key=uuid4(),
        )
        type(self.sale).objects.filter(pk=self.sale.pk).update(
            pending_amount=Decimal("0.00"), payment_status="paid"
        )
        response = self.client.get(url(self.sale))
        self.assertContains(response, "data-payment-recovery-form")
        self.assertNotContains(response, "VENTA COMPLETADA")
        self.assertContains(response, 'data-payment-status="partial"')
        self.assertContains(
            self.client.post(url(self.sale), self.body), "VENTA COMPLETADA"
        )
        self.assertEqual(BillingDocument.objects.get(sale=self.sale).pk, document.pk)
        self.assert_history()

    def test_noncompleted_existing_key_is_not_reported_as_confirmed(self):
        from apps.payments.services import cancel_payment
        from uuid import UUID

        pending = Payment.objects.create(
            business=self.d.business,
            store=self.d.store,
            sale=self.sale,
            method=self.card,
            cash_session=self.session,
            amount=Decimal("3.00"),
            processed_by=self.d.user,
            idempotency_key=UUID(self.body["payment_idempotency_key"]),
            status="pending",
        )
        body = {**self.body, "amount": "3.00"}
        for status in ("pending", "cancelled"):
            with self.subTest(status=status):
                if status == "cancelled":
                    cancel_payment(
                        business=self.d.business,
                        payment_id=pending.pk,
                        user=self.d.user,
                    )
                response = self.client.post(
                    url(self.sale), body, HTTP_HX_REQUEST="true"
                )
                self.assertEqual(response.status_code, 409)
                self.assertNotIn("X-Netxodo-Confirmed-Payment", response)
                pending.refresh_from_db()
                self.assertEqual(pending.status, status)
                self.assert_history(payments=2, documents=0)
                self.assertFalse(CashMovement.objects.filter(payment=pending).exists())

    def test_new_sale_after_recovery_uses_existing_start_rules_and_keeps_history(self):
        from django.urls import reverse
        import re

        response = self.client.post(url(self.sale), self.body)
        success = response.content.decode().split('class="checkout-success"', 1)[1]
        action = re.search(r'<form[^>]*action="([^"]+)"', success).group(1)
        self.assertEqual(action, reverse("sales:sale_start", args=[self.d.store.pk]))
        started = self.client.post(action)
        self.assertEqual(started.status_code, 302)
        new_sale = (
            type(self.sale)
            .objects.filter(business=self.d.business)
            .exclude(pk=self.sale.pk)
            .get()
        )
        self.assertEqual(new_sale.status, "open")
        self.assertEqual(new_sale.cash_session_id, self.session.pk)
        self.assert_history()
