from decimal import Decimal
import uuid

from django.test import TestCase

from apps.cash_register.models import CashSession
from apps.cash_register.selectors import (
    get_cash_session_counts,
    get_cash_session_movements,
    get_cash_session_payment_summary,
    get_open_cash_session,
)
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.payments.models import Payment, PaymentMethod, PaymentStatusChoices
from apps.sales.models import SaleStatusChoices
from apps.sales.tests.factories import create_sale
from apps.users.tests.factories import create_user


class CashRegisterSelectorsTests(TestCase):
    def setUp(self):
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business)
        self.user = create_user(business=self.business, email="selector@test.com")
        register = create_cash_register(business=self.business, store=self.store)
        self.session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
            opening_amount=Decimal("10"),
            expected_cash_amount=Decimal("10"),
        )

    def test_read_selectors_are_session_scoped(self):
        self.assertEqual(
            get_open_cash_session(
                business=self.business,
                store=self.store,
                cash_register=self.session.cash_register,
            ),
            self.session,
        )
        self.assertFalse(
            get_cash_session_movements(
                business=self.business, store=self.store, cash_session=self.session
            ).exists()
        )
        self.assertFalse(
            get_cash_session_counts(
                business=self.business, store=self.store, cash_session=self.session
            ).exists()
        )

    def test_payment_summary_includes_non_cash_without_changing_expected(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("50"),
        )
        card = PaymentMethod.objects.create(
            business=self.business, name="Tarjeta", code="card"
        )
        Payment.objects.create(
            business=self.business,
            store=self.store,
            sale=sale,
            method=card,
            cash_session=self.session,
            amount=Decimal("50"),
            status=PaymentStatusChoices.COMPLETED,
            processed_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        summary = get_cash_session_payment_summary(
            business=self.business, store=self.store, cash_session=self.session
        )
        self.assertEqual(summary[0]["payments"], Decimal("50"))
        self.assertEqual(summary[0]["net"], Decimal("50"))
        self.session.refresh_from_db()
        self.assertEqual(self.session.expected_cash_amount, Decimal("10"))
