from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.business_config.models import POSSettings
from apps.cash_register.models import CashCount, CashMovement, CashSession
from apps.cash_register.services import CashRegisterService
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


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
        POSSettings.objects.create(
            business=self.business,
            require_pin_for_sensitive_actions=False,
        )
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
