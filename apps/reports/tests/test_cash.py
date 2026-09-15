from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.cash_register.models import CashMovement, CashRegister, CashSession
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.reports.periods import ReportPeriod
from apps.reports.selectors import (
    cash_session_summary,
    cash_sessions_summary,
    cash_summary,
)
from apps.sales.models import SaleReturnStatusChoices, SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_return,
    create_sales_user,
)

UTC = ZoneInfo("UTC")


class CashReportTests(TestCase):
    def setUp(self):
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business, name="Centro")
        self.user = create_sales_user(business=self.business)
        self.register = create_cash_register(
            business=self.business, store=self.store, name="Caja 1", code="ONE"
        )
        self.cash_method = PaymentMethod.objects.create(
            business=self.business, name="Efectivo", code="cash"
        )
        self.period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 3, tzinfo=UTC)
        )

    def _session(
        self, *, opened=None, register=None, store=None, opening="20", expected="20"
    ):
        store = store or self.store
        register = register or self.register
        return CashSession.objects.create(
            business=self.business,
            store=store,
            cash_register=register,
            opened_by=self.user,
            opened_at=opened or datetime(2026, 9, 1, 9, tzinfo=UTC),
            opening_amount=Decimal(opening),
            expected_cash_amount=Decimal(expected),
        )

    def _close(self, session, *, closed, expected="20", counted="20", difference="0"):
        CashSession.objects.filter(pk=session.pk).update(
            status=CashSession.Status.CLOSED,
            closed_at=closed,
            closed_by=self.user,
            expected_cash_amount=Decimal(expected),
            counted_cash_amount=Decimal(counted),
            difference_amount=Decimal(difference),
        )
        session.refresh_from_db()
        return session

    def _manual(self, session, movement_type, amount, *, when=None, direction=None):
        movement = CashMovement.objects.create(
            business=self.business,
            store=session.store,
            cash_session=session,
            movement_type=movement_type,
            adjustment_direction=direction,
            amount=Decimal(amount),
            balance_after=Decimal("100"),
            created_by=self.user,
            reason="test",
        )
        if when is not None:
            CashMovement.objects.filter(pk=movement.pk).update(created_at=when)
        return movement

    def _cash_payment_movement(self, session, movement_type, amount, *, when=None):
        sale = create_sale(
            business=self.business,
            store=session.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("100"),
            cash_register=session.cash_register,
            cash_session=session,
        )
        payment_type = PaymentTypeChoices.SALE_PAYMENT
        sale_return = None
        if movement_type == CashMovement.MovementType.REFUND_CASH:
            payment_type = PaymentTypeChoices.REFUND
            sale_return = create_sale_return(
                business=self.business,
                store=session.store,
                original_sale=sale,
                created_by=self.user,
                status=SaleReturnStatusChoices.DRAFT,
            )
        payment = Payment.objects.create(
            business=self.business,
            store=session.store,
            sale=sale,
            method=self.cash_method,
            cash_session=session,
            sale_return=sale_return,
            payment_type=payment_type,
            amount=Decimal(amount),
            status=PaymentStatusChoices.COMPLETED,
            processed_by=self.user,
            idempotency_key=uuid4(),
        )
        movement = CashMovement.objects.create(
            business=self.business,
            store=session.store,
            cash_session=session,
            movement_type=movement_type,
            amount=Decimal(amount),
            balance_after=Decimal("100"),
            sale=sale,
            payment=payment,
            created_by=self.user,
        )
        if when is not None:
            CashMovement.objects.filter(pk=movement.pk).update(created_at=when)
        return movement

    def _all_movements(self, session):
        self._cash_payment_movement(session, CashMovement.MovementType.SALE_CASH, "50")
        self._cash_payment_movement(session, CashMovement.MovementType.REFUND_CASH, "7")
        self._manual(session, CashMovement.MovementType.CASH_IN, "11")
        self._manual(session, CashMovement.MovementType.CASH_OUT, "3")
        self._manual(
            session,
            CashMovement.MovementType.ADJUSTMENT,
            "5",
            direction=CashMovement.AdjustmentDirection.IN,
        )
        self._manual(
            session,
            CashMovement.MovementType.ADJUSTMENT,
            "2",
            direction=CashMovement.AdjustmentDirection.OUT,
        )

    def test_session_summary_all_movement_types_and_authoritative_close_values(self):
        session = self._session(opening="20")
        self._all_movements(session)
        self._close(
            session,
            closed=datetime(2026, 9, 2, tzinfo=UTC),
            expected="74",
            counted="72",
            difference="-2",
        )
        result = cash_session_summary(
            business=self.business, cash_session_id=session.pk
        )
        for key, value in {
            "cash_sales": "50",
            "cash_refunds": "7",
            "manual_cash_in": "11",
            "manual_cash_out": "3",
            "adjustment_in": "5",
            "adjustment_out": "2",
            "net_physical_movement": "54",
            "expected_cash": "74",
            "counted_cash": "72",
            "difference": "-2",
            "opening_amount": "20",
        }.items():
            self.assertEqual(result[key], Decimal(value))

    def test_open_session_preserves_not_counted_semantics(self):
        session = self._session()
        result = cash_session_summary(
            business=self.business, cash_session_id=session.pk
        )
        self.assertIsNone(result["counted_cash"])
        self.assertEqual(result["net_physical_movement"], Decimal("0.00"))

    def test_session_summary_business_store_isolation(self):
        session = self._session()
        second_store = create_cash_store(business=self.business)
        self.assertRaises(
            CashSession.DoesNotExist,
            cash_session_summary,
            business=self.business,
            cash_session_id=session.pk,
            store=second_store,
        )
        other_business = create_cash_business()
        self.assertRaises(
            CashSession.DoesNotExist,
            cash_session_summary,
            business=other_business,
            cash_session_id=session.pk,
        )
        foreign_store = create_cash_store(business=other_business)
        with self.assertRaisesRegex(ValueError, "store must belong"):
            cash_session_summary(
                business=self.business, cash_session_id=session.pk, store=foreign_store
            )

    def test_cash_summary_period_events_bounds_and_closed_values(self):
        session = self._session(opened=self.period.start, opening="20")
        self._manual(
            session, CashMovement.MovementType.CASH_IN, "10", when=self.period.start
        )
        self._manual(
            session, CashMovement.MovementType.CASH_OUT, "99", when=self.period.end
        )
        self._close(
            session,
            closed=datetime(2026, 9, 2, tzinfo=UTC),
            expected="30",
            counted="29",
            difference="-1",
        )
        later_register = create_cash_register(business=self.business, store=self.store)
        later = self._session(
            opened=self.period.end, register=later_register, opening="100"
        )
        self._close(later, closed=self.period.end, expected="100", counted="100")
        result = cash_summary(business=self.business, period=self.period)
        self.assertEqual(result["sessions_opened_count"], 1)
        self.assertEqual(result["sessions_closed_count"], 1)
        self.assertEqual(result["opening_amount"], Decimal("20"))
        self.assertEqual(result["manual_cash_in"], Decimal("10"))
        self.assertEqual(result["manual_cash_out"], Decimal("0.00"))
        self.assertEqual(
            (
                result["closed_expected_cash"],
                result["closed_counted_cash"],
                result["closed_difference"],
            ),
            (Decimal("30"), Decimal("29"), Decimal("-1")),
        )

    def test_cash_summary_aggregates_every_physical_movement_kind(self):
        session = self._session()
        self._all_movements(session)
        CashMovement.objects.filter(cash_session=session).update(
            created_at=datetime(2026, 9, 2, tzinfo=UTC)
        )
        result = cash_summary(business=self.business, period=self.period)
        self.assertEqual(result["cash_sales"], Decimal("50"))
        self.assertEqual(result["cash_refunds"], Decimal("7"))
        self.assertEqual(result["manual_cash_in"], Decimal("11"))
        self.assertEqual(result["manual_cash_out"], Decimal("3"))
        self.assertEqual(result["adjustment_in"], Decimal("5"))
        self.assertEqual(result["adjustment_out"], Decimal("2"))
        self.assertEqual(result["net_physical_movement"], Decimal("54"))

    def test_cash_summary_store_filter_and_business_isolation(self):
        self._session(opening="10")
        second_store = create_cash_store(business=self.business)
        second_register = create_cash_register(
            business=self.business, store=second_store
        )
        self._session(store=second_store, register=second_register, opening="20")
        self.assertEqual(
            cash_summary(business=self.business, period=self.period, store=self.store)[
                "opening_amount"
            ],
            Decimal("10"),
        )
        other_business = create_cash_business()
        foreign_store = create_cash_store(business=other_business)
        self.assertEqual(
            cash_summary(business=other_business, period=self.period)[
                "sessions_opened_count"
            ],
            0,
        )
        with self.assertRaisesRegex(ValueError, "store must belong"):
            cash_summary(
                business=self.business, period=self.period, store=foreign_store
            )

    def test_sessions_intersection_complete_movements_and_no_cross_session_mix(self):
        active = self._session(opened=datetime(2026, 8, 31, tzinfo=UTC))
        self._manual(
            active,
            CashMovement.MovementType.CASH_IN,
            "4",
            when=datetime(2026, 8, 31, 1, tzinfo=UTC),
        )
        closed_register = create_cash_register(business=self.business, store=self.store)
        closing = self._session(
            opened=datetime(2026, 8, 30, tzinfo=UTC), register=closed_register
        )
        self._manual(closing, CashMovement.MovementType.CASH_OUT, "3")
        self._close(closing, closed=datetime(2026, 9, 1, 12, tzinfo=UTC))
        old_register = create_cash_register(business=self.business, store=self.store)
        old = self._session(
            opened=datetime(2026, 8, 1, tzinfo=UTC), register=old_register
        )
        self._close(old, closed=datetime(2026, 8, 2, tzinfo=UTC))
        future_register = create_cash_register(business=self.business, store=self.store)
        self._session(opened=datetime(2026, 9, 4, tzinfo=UTC), register=future_register)
        rows = cash_sessions_summary(business=self.business, period=self.period)
        by_id = {row["session_id"]: row for row in rows}
        self.assertEqual(set(by_id), {active.pk, closing.pk})
        self.assertEqual(by_id[active.pk]["manual_cash_in"], Decimal("4"))
        self.assertEqual(by_id[active.pk]["manual_cash_out"], Decimal("0.00"))
        self.assertEqual(by_id[closing.pk]["manual_cash_out"], Decimal("3"))

    def test_sessions_summary_store_and_business_isolation(self):
        own = self._session()
        second_store = create_cash_store(business=self.business)
        second_register = create_cash_register(
            business=self.business, store=second_store
        )
        other = self._session(store=second_store, register=second_register)
        rows = cash_sessions_summary(
            business=self.business, period=self.period, store=self.store
        )
        self.assertEqual([row["session_id"] for row in rows], [own.pk])
        self.assertNotIn(other.pk, [row["session_id"] for row in rows])
        foreign_business = create_cash_business()
        self.assertEqual(
            cash_sessions_summary(business=foreign_business, period=self.period), []
        )

    def test_sessions_summary_query_count_is_constant_without_duplicate_open_register(
        self,
    ):
        self._session()
        with self.assertNumQueries(2):
            one = cash_sessions_summary(business=self.business, period=self.period)
        for number in (2, 3):
            register = CashRegister.objects.create(
                business=self.business,
                store=self.store,
                name=f"Caja {number}",
                code=f"C{number}",
            )
            self._session(register=register)
        with self.assertNumQueries(2):
            many = cash_sessions_summary(business=self.business, period=self.period)
        self.assertEqual(len(one), 1)
        self.assertEqual(len(many), 3)
