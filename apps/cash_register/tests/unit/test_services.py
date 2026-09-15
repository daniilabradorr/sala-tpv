from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.audit.constants import AuditEventType, AuditModule
from apps.audit.exceptions import AuditValidationError
from apps.audit.models import AuditEvent
from apps.audit.services import log_event as real_log_event
from apps.business_config.models import POSSettings
from apps.cash_register.models import CashCount, CashMovement, CashSession
from apps.cash_register.services import CashRegisterService
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_store_access, create_user


class CashRegisterServiceTests(TestCase):
    def setUp(self):
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business)
        self.register = create_cash_register(business=self.business, store=self.store)
        self.user = create_user(
            business=self.business,
            email="owner-cash@test.com",
            role=RoleChoices.OWNER,
        )
        self.user.set_pin("1234")
        self.user.save()
        settings = POSSettings.objects.create(business=self.business)
        settings.require_pin_for_sensitive_actions = False
        settings.save()
        self.service = CashRegisterService()
        self.session = self.service.open_cash_session(
            business=self.business,
            store_id=self.store.pk,
            cash_register_id=self.register.pk,
            user=self.user,
            opening_amount=Decimal("100.00"),
        )

    def common(self):
        return {
            "business": self.business,
            "store_id": self.store.pk,
            "cash_register_id": self.register.pk,
            "cash_session_id": self.session.pk,
            "user": self.user,
        }

    def events(self, event_type):
        return AuditEvent.objects.filter(event_type=event_type)

    def test_open_cash_session_creates_allowlisted_audit_event(self):
        event = self.events(AuditEventType.CASH_SESSION_OPENED).get(
            entity_id=str(self.session.pk)
        )
        self.assertEqual(event.module, AuditModule.CASH_REGISTER)
        self.assertEqual(event.business, self.business)
        self.assertEqual(event.store, self.store)
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.entity_type, "cash_register.cashsession")
        self.assertEqual(event.message, f"Sesión de caja #{self.session.pk} abierta.")
        self.assertIsNone(event.old_payload)
        self.assertEqual(
            event.new_payload,
            {
                "status": CashSession.Status.OPEN,
                "opening_amount": "100.00",
                "expected_cash_amount": "100.00",
                "opened_at": self.session.opened_at.isoformat(),
            },
        )
        self.assertEqual(
            event.metadata,
            {
                "cash_register_id": self.register.pk,
                "cash_register_code": self.register.code,
            },
        )

    def test_rejected_second_open_does_not_duplicate_audit_event(self):
        before = self.events(AuditEventType.CASH_SESSION_OPENED).count()
        with self.assertRaises(ValidationError):
            self.service.open_cash_session(
                business=self.business,
                store_id=self.store.pk,
                cash_register_id=self.register.pk,
                user=self.user,
                opening_amount=Decimal("1.00"),
            )
        self.assertEqual(
            self.events(AuditEventType.CASH_SESSION_OPENED).count(), before
        )

    def test_manual_movements_create_exact_audit_events(self):
        cash_in = self.service.register_cash_in(
            **self.common(), amount=Decimal("20"), reason="Fondo adicional"
        )
        cash_out = self.service.register_cash_out(
            **self.common(), amount=Decimal("10"), reason="Compra urgente"
        )
        adjustment = self.service.register_adjustment(
            **self.common(),
            amount=Decimal("5"),
            adjustment_direction=CashMovement.AdjustmentDirection.OUT,
            reason="Corrección de arqueo",
        )
        expectations = (
            (AuditEventType.CASH_IN, cash_in, "100.00", "120.00", None),
            (AuditEventType.CASH_OUT, cash_out, "120.00", "110.00", None),
            (
                AuditEventType.CASH_ADJUSTED,
                adjustment,
                "110.00",
                "105.00",
                CashMovement.AdjustmentDirection.OUT,
            ),
        )
        for event_type, movement, before, after, adjustment_direction in expectations:
            event = self.events(event_type).get()
            self.assertEqual(event.entity_type, "cash_register.cashmovement")
            self.assertEqual(event.entity_id, str(movement.pk))
            self.assertEqual(event.old_payload, {"expected_cash_amount": before})
            self.assertEqual(event.new_payload, {"expected_cash_amount": after})
            self.assertEqual(
                event.metadata,
                {
                    "cash_session_id": self.session.pk,
                    "cash_register_id": self.register.pk,
                    "movement_type": movement.movement_type,
                    "adjustment_direction": adjustment_direction,
                    "amount": str(movement.amount),
                    "balance_after": str(movement.balance_after),
                    "reason": movement.reason,
                },
            )

    def test_review_creates_allowlisted_count_audit_without_notes(self):
        count = self.service.review_cash_count(
            **self.common(), counted_amount=Decimal("98"), notes="nota privada"
        )
        event = self.events(AuditEventType.CASH_COUNTED).get()
        self.assertEqual(event.entity_type, "cash_register.cashcount")
        self.assertEqual(event.entity_id, str(count.pk))
        self.assertIsNone(event.old_payload)
        self.assertEqual(
            event.new_payload,
            {
                "count_type": CashCount.CountType.REVIEW,
                "counted_amount": "98.00",
                "expected_amount": "100.00",
                "difference_amount": "-2.00",
            },
        )
        self.assertEqual(
            event.metadata,
            {
                "cash_session_id": self.session.pk,
                "cash_register_id": self.register.pk,
            },
        )
        self.assertNotIn("nota privada", str(event.new_payload) + str(event.metadata))

    def test_close_creates_counted_then_closed_events_without_pin_or_notes(self):
        settings = self.business.pos_settings
        settings.require_pin_for_sensitive_actions = True
        settings.save()
        session, count = self.service.close_cash_session(
            **self.common(),
            counted_cash_amount=Decimal("97"),
            pin="1234",
            notes="nota de cierre",
        )
        counted = self.events(AuditEventType.CASH_COUNTED).get(entity_id=str(count.pk))
        closed = self.events(AuditEventType.CASH_SESSION_CLOSED).get()
        self.assertLess(counted.pk, closed.pk)
        self.assertEqual(counted.entity_type, "cash_register.cashcount")
        self.assertEqual(counted.new_payload["count_type"], CashCount.CountType.CLOSING)
        self.assertEqual(closed.entity_type, "cash_register.cashsession")
        self.assertEqual(closed.entity_id, str(session.pk))
        self.assertEqual(closed.old_payload, {"status": CashSession.Status.OPEN})
        self.assertEqual(
            closed.new_payload,
            {
                "status": CashSession.Status.CLOSED,
                "counted_cash_amount": "97.00",
                "difference_amount": "-3.00",
                "closed_at": session.closed_at.isoformat(),
            },
        )
        self.assertEqual(
            closed.metadata,
            {
                "cash_register_id": self.register.pk,
                "closing_count_id": count.pk,
                "expected_cash_amount": "100.00",
            },
        )
        serialized = " ".join(
            str(value)
            for event in (counted, closed)
            for value in (
                event.message,
                event.old_payload,
                event.new_payload,
                event.metadata,
            )
        )
        self.assertNotIn("1234", serialized)
        self.assertNotIn("nota de cierre", serialized)
        before = {
            event_type: self.events(event_type).count()
            for event_type in (
                AuditEventType.CASH_COUNTED,
                AuditEventType.CASH_SESSION_CLOSED,
            )
        }
        with self.assertRaises(ValidationError):
            self.service.close_cash_session(
                **self.common(), counted_cash_amount=Decimal("97"), pin="1234"
            )
        for event_type, count_before in before.items():
            self.assertEqual(self.events(event_type).count(), count_before)

    def test_open_rolls_back_when_audit_fails(self):
        register = create_cash_register(
            business=self.business, store=self.store, code="AUDIT-FAIL"
        )
        with patch(
            "apps.cash_register.services.log_event",
            side_effect=AuditValidationError("audit failed"),
        ):
            with self.assertRaises(AuditValidationError):
                self.service.open_cash_session(
                    business=self.business,
                    store_id=self.store.pk,
                    cash_register_id=register.pk,
                    user=self.user,
                    opening_amount=Decimal("10"),
                )
        self.assertFalse(CashSession.objects.filter(cash_register=register).exists())

    def test_manual_movements_roll_back_when_audit_fails(self):
        for operation in (
            self.service.register_cash_in,
            self.service.register_cash_out,
        ):
            with self.subTest(operation=operation.__name__):
                with patch(
                    "apps.cash_register.services.log_event",
                    side_effect=AuditValidationError("audit failed"),
                ):
                    with self.assertRaises(AuditValidationError):
                        operation(
                            **self.common(), amount=Decimal("10"), reason="operación"
                        )
                self.session.refresh_from_db()
                self.assertEqual(self.session.expected_cash_amount, Decimal("100.00"))
                self.assertFalse(
                    CashMovement.objects.filter(cash_session=self.session).exists()
                )

    def test_review_rolls_back_when_audit_fails(self):
        with patch(
            "apps.cash_register.services.log_event",
            side_effect=AuditValidationError("audit failed"),
        ):
            with self.assertRaises(AuditValidationError):
                self.service.review_cash_count(
                    **self.common(), counted_amount=Decimal("100")
                )
        self.assertFalse(
            CashCount.objects.filter(count_type=CashCount.CountType.REVIEW).exists()
        )

    def test_close_rolls_back_when_first_audit_fails(self):
        with patch(
            "apps.cash_register.services.log_event",
            side_effect=AuditValidationError("audit failed"),
        ):
            with self.assertRaises(AuditValidationError):
                self.service.close_cash_session(
                    **self.common(), counted_cash_amount=Decimal("100")
                )
        self._assert_close_rolled_back()

    def test_close_rolls_back_first_event_when_second_audit_fails(self):
        calls = 0

        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise AuditValidationError("audit failed")
            return real_log_event(**kwargs)

        with patch("apps.cash_register.services.log_event", side_effect=fail_second):
            with self.assertRaises(AuditValidationError):
                self.service.close_cash_session(
                    **self.common(), counted_cash_amount=Decimal("100")
                )
        self._assert_close_rolled_back()
        self.assertFalse(self.events(AuditEventType.CASH_COUNTED).exists())
        self.assertFalse(self.events(AuditEventType.CASH_SESSION_CLOSED).exists())

    def _assert_close_rolled_back(self):
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, CashSession.Status.OPEN)
        self.assertIsNone(self.session.closed_at)
        self.assertIsNone(self.session.closed_by_id)
        self.assertIsNone(self.session.counted_cash_amount)
        self.assertFalse(
            CashCount.objects.filter(count_type=CashCount.CountType.CLOSING).exists()
        )

    def test_manual_movements_and_adjustments_update_locked_balance(self):
        cash_in = self.service.register_cash_in(**self.common(), amount=Decimal("20"))
        cash_out = self.service.register_cash_out(**self.common(), amount=Decimal("10"))
        adjustment = self.service.register_adjustment(
            **self.common(),
            amount=Decimal("5"),
            adjustment_direction=CashMovement.AdjustmentDirection.OUT,
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.expected_cash_amount, Decimal("105.00"))
        self.assertEqual(
            [cash_in.balance_after, cash_out.balance_after, adjustment.balance_after],
            [Decimal("120.00"), Decimal("110.00"), Decimal("105.00")],
        )

    def test_negative_manual_out_requires_reason(self):
        with self.assertRaises(ValidationError):
            self.service.register_cash_out(**self.common(), amount=Decimal("120"))
        movement = self.service.register_cash_out(
            **self.common(), amount=Decimal("120"), reason="Retirada extraordinaria"
        )
        self.assertEqual(movement.balance_after, Decimal("-20.00"))

    def test_review_is_snapshot_and_does_not_close_session(self):
        first = self.service.review_cash_count(
            **self.common(), counted_amount=Decimal("98")
        )
        second = self.service.review_cash_count(
            **self.common(), counted_amount=Decimal("101")
        )
        self.session.refresh_from_db()
        self.assertEqual(first.difference_amount, Decimal("-2.00"))
        self.assertEqual(second.count_type, CashCount.CountType.REVIEW)
        self.assertEqual(self.session.status, CashSession.Status.OPEN)
        self.assertIsNone(self.session.counted_cash_amount)

    def test_close_creates_one_closing_count(self):
        session, count = self.service.close_cash_session(
            **self.common(), counted_cash_amount=Decimal("97")
        )
        self.assertEqual(session.status, CashSession.Status.CLOSED)
        self.assertEqual(count.count_type, CashCount.CountType.CLOSING)
        self.assertEqual(count.difference_amount, Decimal("-3.00"))
        with self.assertRaises(ValidationError):
            self.service.close_cash_session(
                **self.common(), counted_cash_amount=Decimal("97")
            )
        self.assertEqual(
            CashCount.objects.filter(
                cash_session=self.session, count_type=CashCount.CountType.CLOSING
            ).count(),
            1,
        )

    def test_manual_movement_failure_rolls_back_expected(self):
        with patch.object(
            self.service.repository,
            "create_cash_movement",
            side_effect=RuntimeError("persistence failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.service.register_cash_in(**self.common(), amount=Decimal("20"))
        self.session.refresh_from_db()
        self.assertEqual(self.session.expected_cash_amount, Decimal("100.00"))

    def test_count_failure_rolls_back_close(self):
        with patch.object(
            self.service.repository,
            "create_cash_count",
            side_effect=RuntimeError("persistence failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.service.close_cash_session(
                    **self.common(), counted_cash_amount=Decimal("100")
                )
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, CashSession.Status.OPEN)

    def test_created_movement_rolls_back_when_session_save_fails(self):
        with patch.object(
            CashSession, "save", side_effect=RuntimeError("session save failure")
        ):
            with self.assertRaises(RuntimeError):
                self.service.register_cash_in(**self.common(), amount=Decimal("20"))
        self.session.refresh_from_db()
        self.assertEqual(self.session.expected_cash_amount, Decimal("100.00"))
        self.assertFalse(
            CashMovement.objects.filter(cash_session=self.session).exists()
        )

    def test_created_closing_count_rolls_back_when_session_save_fails(self):
        with patch.object(
            CashSession, "save", side_effect=RuntimeError("session save failure")
        ):
            with self.assertRaises(RuntimeError):
                self.service.close_cash_session(
                    **self.common(), counted_cash_amount=Decimal("100")
                )
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, CashSession.Status.OPEN)
        self.assertIsNone(self.session.counted_cash_amount)
        self.assertIsNone(self.session.closed_at)
        self.assertFalse(
            CashCount.objects.filter(
                cash_session=self.session, count_type=CashCount.CountType.CLOSING
            ).exists()
        )

    def test_review_rejects_inactive_store_and_business(self):
        self.store.is_active = False
        self.store.save()
        with self.assertRaises(ValidationError):
            self.service.review_cash_count(
                **self.common(), counted_amount=Decimal("100")
            )
        self.store.is_active = True
        self.store.save()
        self.business.is_active = False
        self.business.save()
        with self.assertRaises(ValidationError):
            self.service.review_cash_count(
                **self.common(), counted_amount=Decimal("100")
            )

    def test_open_zero_and_rejects_negative(self):
        register = create_cash_register(
            business=self.business, store=self.store, code="SECOND"
        )
        session = self.service.open_cash_session(
            business=self.business,
            store_id=self.store.pk,
            cash_register_id=register.pk,
            user=self.user,
            opening_amount=Decimal("0.00"),
        )
        self.assertEqual(session.expected_cash_amount, Decimal("0.00"))
        third = create_cash_register(
            business=self.business, store=self.store, code="THIRD"
        )
        with self.assertRaises(ValidationError):
            self.service.open_cash_session(
                business=self.business,
                store_id=self.store.pk,
                cash_register_id=third.pk,
                user=self.user,
                opening_amount=Decimal("-1.00"),
            )

    def test_open_rejects_inactive_store_register_and_second_open(self):
        with self.assertRaises(ValidationError):
            self.service.open_cash_session(
                business=self.business,
                store_id=self.store.pk,
                cash_register_id=self.register.pk,
                user=self.user,
                opening_amount=Decimal("1.00"),
            )
        inactive = create_cash_register(
            business=self.business,
            store=self.store,
            code="INACTIVE",
            is_active=False,
        )
        with self.assertRaises(ValidationError):
            self.service.open_cash_session(
                business=self.business,
                store_id=self.store.pk,
                cash_register_id=inactive.pk,
                user=self.user,
                opening_amount=Decimal("1.00"),
            )
        self.store.is_active = False
        self.store.save()
        with self.assertRaises(ValidationError):
            self.service.open_cash_session(
                business=self.business,
                store_id=self.store.pk,
                cash_register_id=inactive.pk,
                user=self.user,
                opening_amount=Decimal("1.00"),
            )

    def test_reopen_after_correct_close(self):
        self.service.close_cash_session(
            **self.common(), counted_cash_amount=Decimal("100.00")
        )
        reopened = self.service.open_cash_session(
            business=self.business,
            store_id=self.store.pk,
            cash_register_id=self.register.pk,
            user=self.user,
            opening_amount=Decimal("25.00"),
        )
        self.assertTrue(reopened.is_open)

    def test_open_rejects_user_without_open_permission(self):
        register = create_cash_register(
            business=self.business, store=self.store, code="NO-PERM"
        )
        cashier = create_user(
            business=self.business, email="no-open@test.com", role=RoleChoices.CASHIER
        )
        create_store_access(
            business=self.business,
            user=cashier,
            store=self.store,
            can_open_cash=False,
        )
        with self.assertRaises(ValidationError):
            self.service.open_cash_session(
                business=self.business,
                store_id=self.store.pk,
                cash_register_id=register.pk,
                user=cashier,
                opening_amount=Decimal("1.00"),
            )

    def test_close_pin_empty_wrong_and_correct(self):
        settings = self.business.pos_settings
        settings.require_pin_for_sensitive_actions = True
        settings.save()
        for pin in (None, "wrong"):
            with self.assertRaises(ValidationError):
                self.service.close_cash_session(
                    **self.common(), counted_cash_amount=Decimal("100"), pin=pin
                )
        session, _count = self.service.close_cash_session(
            **self.common(), counted_cash_amount=Decimal("100"), pin="1234"
        )
        self.assertEqual(session.status, CashSession.Status.CLOSED)

    def test_close_rejects_user_without_permission_and_missing_settings(self):
        cashier = create_user(
            business=self.business,
            email="no-close@test.com",
            role=RoleChoices.CASHIER,
        )
        create_store_access(
            business=self.business,
            user=cashier,
            store=self.store,
            can_close_cash=False,
        )
        with self.assertRaises(ValidationError):
            self.service.close_cash_session(
                **{**self.common(), "user": cashier},
                counted_cash_amount=Decimal("100"),
            )
        POSSettings.objects.filter(business=self.business).delete()
        with self.assertRaises(ValidationError):
            self.service.close_cash_session(
                **self.common(), counted_cash_amount=Decimal("100")
            )
