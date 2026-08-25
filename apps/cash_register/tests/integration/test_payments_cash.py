import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.cash_register.models import CashMovement, CashSession
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.payments.models import Payment, PaymentMethod
from apps.payments.services import register_sale_payment
from apps.sales.models import SaleStatusChoices
from apps.sales.tests.factories import create_pos_settings, create_sale
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


class PaymentCashIntegrationTests(TestCase):
    def setUp(self):
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business)
        self.user = create_user(
            business=self.business,
            email="payment-cash@test.com",
            role=RoleChoices.OWNER,
        )
        create_pos_settings(business=self.business)
        register = create_cash_register(business=self.business, store=self.store)
        self.session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
            opening_amount=Decimal("100"),
            expected_cash_amount=Decimal("100"),
        )
        self.sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("50"),
        )
        self.cash = PaymentMethod.objects.create(
            business=self.business, name="Efectivo", code="cash"
        )
        self.card = PaymentMethod.objects.create(
            business=self.business, name="Tarjeta", code="card"
        )

    def pay(self, *, method, key=None):
        return register_sale_payment(
            business=self.business,
            sale_id=self.sale.pk,
            method_id=method.pk,
            amount=Decimal("50"),
            user=self.user,
            idempotency_key=key or uuid.uuid4(),
            cash_session_id=self.session.pk,
        )

    def test_cash_payment_and_retry_create_one_physical_effect(self):
        key = uuid.uuid4()
        payment = self.pay(method=self.cash, key=key)
        retry = self.pay(method=self.cash, key=key)
        movement = CashMovement.objects.get(payment=payment)
        self.session.refresh_from_db()
        self.assertEqual(payment, retry)
        self.assertEqual(movement.movement_type, CashMovement.MovementType.SALE_CASH)
        self.assertEqual(movement.balance_after, Decimal("150.00"))
        self.assertEqual(self.session.expected_cash_amount, Decimal("150.00"))
        self.assertEqual(Payment.objects.filter(idempotency_key=key).count(), 1)
        self.assertEqual(CashMovement.objects.filter(payment=payment).count(), 1)

    def test_card_requires_session_but_has_no_physical_effect(self):
        payment = self.pay(method=self.card)
        self.session.refresh_from_db()
        self.assertEqual(payment.cash_session, self.session)
        self.assertFalse(CashMovement.objects.filter(payment=payment).exists())
        self.assertEqual(self.session.expected_cash_amount, Decimal("100.00"))

    def test_cash_movement_failure_rolls_back_payment_and_expected(self):
        with patch(
            "apps.payments.services.register_payment_cash_movement",
            side_effect=RuntimeError("cash persistence failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.pay(method=self.cash)
        self.session.refresh_from_db()
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self.session.expected_cash_amount, Decimal("100.00"))
