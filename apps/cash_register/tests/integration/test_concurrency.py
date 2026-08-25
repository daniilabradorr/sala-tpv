import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.business_config.models import POSSettings
from apps.cash_register.models import CashCount, CashMovement, CashSession
from apps.cash_register.services import CashRegisterService
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.payments.models import Payment, PaymentMethod
from apps.payments.services import register_sale_payment
from apps.sales.models import SaleStatusChoices
from apps.sales.tests.factories import create_sale
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


class CashRegisterConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business)
        self.register = create_cash_register(business=self.business, store=self.store)
        self.user = create_user(
            business=self.business,
            email="cash-concurrency-owner@test.com",
            role=RoleChoices.OWNER,
        )
        POSSettings.objects.create(
            business=self.business, require_pin_for_sensitive_actions=False
        )

    def run_threads(self, *operations):
        barrier = Barrier(len(operations))

        def execute(operation):
            connections.close_all()
            try:
                barrier.wait()
                operation()
                return True
            except ValidationError:
                return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            return list(executor.map(execute, operations))

    def open_session(self, amount=Decimal("100.00")):
        return CashRegisterService().open_cash_session(
            business=self.business,
            store_id=self.store.pk,
            cash_register_id=self.register.pk,
            user=self.user,
            opening_amount=amount,
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_concurrent_opens_create_exactly_one_open_session(self):
        results = self.run_threads(self.open_session, self.open_session)
        self.assertEqual(results.count(True), 1)
        self.assertEqual(
            CashSession.objects.filter(
                cash_register=self.register, status=CashSession.Status.OPEN
            ).count(),
            1,
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_concurrent_movements_do_not_lose_updates(self):
        session = self.open_session()
        common = {
            "business": self.business,
            "store_id": self.store.pk,
            "cash_register_id": self.register.pk,
            "cash_session_id": session.pk,
            "user": self.user,
        }
        results = self.run_threads(
            lambda: CashRegisterService().register_cash_in(
                **common, amount=Decimal("20.00")
            ),
            lambda: CashRegisterService().register_cash_out(
                **common, amount=Decimal("10.00")
            ),
        )
        self.assertEqual(results, [True, True])
        session.refresh_from_db()
        self.assertEqual(session.expected_cash_amount, Decimal("110.00"))
        movements = CashMovement.objects.filter(cash_session=session)
        self.assertEqual(movements.count(), 2)
        self.assertIn(
            set(movements.values_list("balance_after", flat=True)),
            [
                {Decimal("120.00"), Decimal("110.00")},
                {Decimal("90.00"), Decimal("110.00")},
            ],
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_concurrent_closes_create_one_closing_count(self):
        session = self.open_session()
        common = {
            "business": self.business,
            "store_id": self.store.pk,
            "cash_register_id": self.register.pk,
            "cash_session_id": session.pk,
            "user": self.user,
            "counted_cash_amount": Decimal("100.00"),
        }
        results = self.run_threads(
            lambda: CashRegisterService().close_cash_session(**common),
            lambda: CashRegisterService().close_cash_session(**common),
        )
        self.assertEqual(results.count(True), 1)
        session.refresh_from_db()
        self.assertEqual(session.status, CashSession.Status.CLOSED)
        self.assertEqual(
            CashCount.objects.filter(
                cash_session=session, count_type=CashCount.CountType.CLOSING
            ).count(),
            1,
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_cash_payment_vs_close_is_serially_consistent(self):
        session = self.open_session()
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("20.00"),
        )
        cash = PaymentMethod.objects.create(
            business=self.business, name="Efectivo", code="cash"
        )
        payment_key = uuid.uuid4()
        results = self.run_threads(
            lambda: register_sale_payment(
                business=self.business,
                sale_id=sale.pk,
                method_id=cash.pk,
                amount=Decimal("20.00"),
                user=self.user,
                idempotency_key=payment_key,
                cash_session_id=session.pk,
            ),
            lambda: CashRegisterService().close_cash_session(
                business=self.business,
                store_id=self.store.pk,
                cash_register_id=self.register.pk,
                cash_session_id=session.pk,
                user=self.user,
                counted_cash_amount=Decimal("100.00"),
            ),
        )
        self.assertTrue(results[1])
        session.refresh_from_db()
        self.assertEqual(session.status, CashSession.Status.CLOSED)
        payment = Payment.objects.filter(idempotency_key=payment_key).first()
        movement = (
            CashMovement.objects.filter(payment=payment).first() if payment else None
        )
        closing = CashCount.objects.get(
            cash_session=session, count_type=CashCount.CountType.CLOSING
        )
        if results[0]:
            self.assertIsNotNone(payment)
            self.assertIsNotNone(movement)
            self.assertEqual(movement.cash_session, session)
            self.assertEqual(session.expected_cash_amount, Decimal("120.00"))
            self.assertEqual(closing.expected_amount, Decimal("120.00"))
        else:
            self.assertIsNone(payment)
            self.assertIsNone(movement)
            self.assertFalse(CashMovement.objects.filter(cash_session=session).exists())
            self.assertEqual(session.expected_cash_amount, Decimal("100.00"))
            self.assertEqual(closing.expected_amount, Decimal("100.00"))
