from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.cash_register.models import CashRegister, CashSession
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.users.tests.factories import create_user
from datetime import timedelta
from decimal import Decimal

from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.cash_register.models import (
    CashCount,
    CashMovement,
    CashRegister,
    CashSession,
)
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.sales.models import SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_return,
)

class CashRegisterModelTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business)

    def test_register_accepts_store_from_same_business(self):
        register = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja principal",
            code="CAJA-01",
        )

        self.assertEqual(register.business, self.business)
        self.assertEqual(register.store, self.store)
        self.assertEqual(register.name, "Caja principal")
        self.assertEqual(register.code, "CAJA-01")
        self.assertTrue(register.is_active)

    def test_register_rejects_store_from_another_business(self):
        other_business = create_cash_business(
            name="Otro negocio",
        )
        other_store = create_cash_store(
            business=other_business,
        )

        with self.assertRaises(ValidationError):
            CashRegister.objects.create(
                business=self.business,
                store=other_store,
                name="Caja inválida",
                code="CAJA-01",
            )

    def test_register_normalizes_code(self):
        register = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja principal",
            code="   cAja-01   ",
        )

        self.assertEqual(
            register.code,
            "CAJA-01",
        )

    def test_register_normalizes_name(self):
        register = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="   Caja principal   ",
            code="CAJA-01",
        )

        self.assertEqual(
            register.name,
            "Caja principal",
        )

    def test_register_requires_code(self):
        with self.assertRaises(ValidationError):
            CashRegister.objects.create(
                business=self.business,
                store=self.store,
                name="Caja principal",
                code="",
            )

    def test_register_requires_name(self):
        with self.assertRaises(ValidationError):
            CashRegister.objects.create(
                business=self.business,
                store=self.store,
                name="",
                code="CAJA-01",
            )

    def test_same_code_cannot_repeat_in_same_store(self):
        CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja principal",
            code="CAJA-01",
        )

        with self.assertRaises(ValidationError):
            CashRegister.objects.create(
                business=self.business,
                store=self.store,
                name="Caja secundaria",
                code="CAJA-01",
            )

    def test_same_code_can_exist_in_different_stores(self):
        other_store = create_cash_store(
            business=self.business,
            name="Otra tienda",
        )

        CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja principal",
            code="CAJA-01",
        )

        register = CashRegister.objects.create(
            business=self.business,
            store=other_store,
            name="Caja otra tienda",
            code="CAJA-01",
        )

        self.assertEqual(
            register.code,
            "CAJA-01",
        )
        self.assertEqual(
            register.store,
            other_store,
        )

    def test_database_rejects_duplicate_code_in_same_store(self):
        register_1 = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja 1",
            code="CAJA-01",
        )

        register_2 = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja 2",
            code="CAJA-02",
        )

        # QuerySet.update() se salta:
        # save() -> full_clean() -> clean()
        #
        # Por tanto aquí comprobamos directamente
        # la UniqueConstraint de la base de datos.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashRegister.objects.filter(
                    pk=register_2.pk,
                ).update(
                    code=register_1.code,
                )

    def test_same_name_cannot_repeat_in_same_store(self):
        CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja principal",
            code="CAJA-01",
        )

        with self.assertRaises(ValidationError):
            CashRegister.objects.create(
                business=self.business,
                store=self.store,
                name="Caja principal",
                code="CAJA-02",
            )

    def test_same_name_can_exist_in_different_stores(self):
        other_store = create_cash_store(
            business=self.business,
            name="Otra tienda",
        )

        CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja principal",
            code="CAJA-01",
        )

        register = CashRegister.objects.create(
            business=self.business,
            store=other_store,
            name="Caja principal",
            code="CAJA-02",
        )

        self.assertEqual(
            register.name,
            "Caja principal",
        )
        self.assertEqual(
            register.store,
            other_store,
        )

    def test_database_rejects_duplicate_name_in_same_store(self):
        register_1 = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja 1",
            code="CAJA-01",
        )

        register_2 = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja 2",
            code="CAJA-02",
        )

        # Igual que con code:
        # nos saltamos save()/full_clean()
        # para comprobar la constraint real de la BD.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashRegister.objects.filter(
                    pk=register_2.pk,
                ).update(
                    name=register_1.name,
                )


class CashSessionModelTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_cash_business()
        self.store = create_cash_store(
            business=self.business,
        )
        self.register = create_cash_register(
            business=self.business,
            store=self.store,
        )
        self.user = create_user(
            business=self.business,
        )

    # ==========================================================
    # Helpers
    # ==========================================================

    def _create_open_session(
        self,
        *,
        register=None,
        opening_amount=Decimal("100.00"),
        expected_cash_amount=Decimal("100.00"),
    ):
        return CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register or self.register,
            opened_by=self.user,
            opening_amount=opening_amount,
            expected_cash_amount=expected_cash_amount,
        )

    def _create_closed_session(
        self,
        *,
        register=None,
        opening_amount=Decimal("100.00"),
        expected_cash_amount=Decimal("120.00"),
        counted_cash_amount=Decimal("115.00"),
    ):
        opened_at = timezone.now()

        return CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register or self.register,
            status=CashSession.Status.CLOSED,
            opened_at=opened_at,
            closed_at=opened_at + timedelta(hours=1),
            opened_by=self.user,
            closed_by=self.user,
            opening_amount=opening_amount,
            expected_cash_amount=expected_cash_amount,
            counted_cash_amount=counted_cash_amount,
            difference_amount=(
                counted_cash_amount
                - expected_cash_amount
            ),
        )

    # ==========================================================
    # Creación / estado OPEN
    # ==========================================================

    def test_create_open_session_success(self):
        session = self._create_open_session()

        self.assertEqual(
            session.business,
            self.business,
        )
        self.assertEqual(
            session.store,
            self.store,
        )
        self.assertEqual(
            session.cash_register,
            self.register,
        )
        self.assertEqual(
            session.opened_by,
            self.user,
        )

        self.assertEqual(
            session.status,
            CashSession.Status.OPEN,
        )
        self.assertTrue(session.is_open)

        self.assertIsNone(
            session.closed_at,
        )
        self.assertIsNone(
            session.closed_by,
        )
        self.assertIsNone(
            session.counted_cash_amount,
        )

        self.assertEqual(
            session.opening_amount,
            Decimal("100.00"),
        )
        self.assertEqual(
            session.expected_cash_amount,
            Decimal("100.00"),
        )
        self.assertEqual(
            session.difference_amount,
            Decimal("0.00"),
        )

    def test_two_open_sessions_same_register_are_rejected(self):
        self._create_open_session()

        with self.assertRaises(ValidationError):
            self._create_open_session()

    def test_two_different_registers_can_have_open_session(self):
        other_register = create_cash_register(
            business=self.business,
            store=self.store,
            name="Caja 2",
            code="CAJA-02",
        )

        session_1 = self._create_open_session(
            register=self.register,
        )

        session_2 = self._create_open_session(
            register=other_register,
        )

        self.assertNotEqual(
            session_1.pk,
            session_2.pk,
        )

        self.assertTrue(
            session_1.is_open,
        )
        self.assertTrue(
            session_2.is_open,
        )

    def test_same_register_can_open_again_after_previous_session_closed(self):
        closed_session = self._create_closed_session()

        new_session = self._create_open_session()

        self.assertEqual(
            closed_session.status,
            CashSession.Status.CLOSED,
        )
        self.assertTrue(
            new_session.is_open,
        )

        self.assertNotEqual(
            closed_session.pk,
            new_session.pk,
        )

    # ==========================================================
    # Business / Store / Register
    # ==========================================================

    def test_session_rejects_register_from_another_business(self):
        other_business = create_cash_business(
            name="Otro negocio",
        )

        other_store = create_cash_store(
            business=other_business,
            name="Tienda otro negocio",
            code="TIENDA-02",
        )

        other_register = create_cash_register(
            business=other_business,
            store=other_store,
            name="Caja otro negocio",
            code="CAJA-02",
        )

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=other_register,
                opened_by=self.user,
            )

    def test_session_rejects_register_from_another_store(self):
        other_store = create_cash_store(
            business=self.business,
            name="Otra tienda",
            code="TIENDA-02",
        )

        other_register = create_cash_register(
            business=self.business,
            store=other_store,
            name="Caja otra tienda",
            code="CAJA-01",
        )

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=other_register,
                opened_by=self.user,
            )

    def test_session_rejects_store_from_another_business(self):
        other_business = create_cash_business(
            name="Otro negocio",
        )

        other_store = create_cash_store(
            business=other_business,
            name="Tienda otro negocio",
            code="TIENDA-02",
        )

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=other_store,
                cash_register=self.register,
                opened_by=self.user,
            )

    # ==========================================================
    # Usuarios
    # ==========================================================

    def test_session_rejects_opened_by_from_another_business(self):
        other_business = create_cash_business(
            name="Otro negocio",
        )

        other_user = create_user(
            business=other_business,
            email="other-open@test.com",
        )

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                opened_by=other_user,
            )

    def test_closed_session_rejects_closed_by_from_another_business(self):
        other_business = create_cash_business(
            name="Otro negocio",
        )

        other_user = create_user(
            business=other_business,
            email="other-close@test.com",
        )

        opened_at = timezone.now()

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                status=CashSession.Status.CLOSED,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(hours=1),
                opened_by=self.user,
                closed_by=other_user,
                opening_amount=Decimal("100.00"),
                expected_cash_amount=Decimal("100.00"),
                counted_cash_amount=Decimal("100.00"),
                difference_amount=Decimal("0.00"),
            )

    # ==========================================================
    # Importes
    # ==========================================================

    def test_session_rejects_negative_opening_amount(self):
        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                opened_by=self.user,
                opening_amount=Decimal("-0.01"),
                expected_cash_amount=Decimal("0.00"),
            )

    def test_session_accepts_zero_opening_amount(self):
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.register,
            opened_by=self.user,
            opening_amount=Decimal("0.00"),
            expected_cash_amount=Decimal("0.00"),
        )

        self.assertEqual(
            session.opening_amount,
            Decimal("0.00"),
        )

    def test_session_rejects_negative_counted_cash_amount(self):
        opened_at = timezone.now()

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                status=CashSession.Status.CLOSED,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(hours=1),
                opened_by=self.user,
                closed_by=self.user,
                opening_amount=Decimal("100.00"),
                expected_cash_amount=Decimal("100.00"),
                counted_cash_amount=Decimal("-1.00"),
                difference_amount=Decimal("-101.00"),
            )

    # ==========================================================
    # Estado OPEN
    # ==========================================================

    def test_open_session_cannot_have_closed_at(self):
        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                opened_by=self.user,
                status=CashSession.Status.OPEN,
                closed_at=timezone.now(),
            )

    def test_open_session_cannot_have_closed_by(self):
        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                opened_by=self.user,
                closed_by=self.user,
                status=CashSession.Status.OPEN,
            )

    def test_open_session_cannot_have_counted_cash(self):
        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                opened_by=self.user,
                counted_cash_amount=Decimal("100.00"),
            )

    def test_open_session_difference_must_be_zero(self):
        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                opened_by=self.user,
                difference_amount=Decimal("10.00"),
            )

    # ==========================================================
    # Estado CLOSED
    # ==========================================================

    def test_create_closed_session_success(self):
        session = self._create_closed_session(
            expected_cash_amount=Decimal("120.00"),
            counted_cash_amount=Decimal("115.00"),
        )

        self.assertEqual(
            session.status,
            CashSession.Status.CLOSED,
        )

        self.assertFalse(
            session.is_open,
        )

        self.assertIsNotNone(
            session.closed_at,
        )

        self.assertEqual(
            session.closed_by,
            self.user,
        )

        self.assertEqual(
            session.counted_cash_amount,
            Decimal("115.00"),
        )

        self.assertEqual(
            session.difference_amount,
            Decimal("-5.00"),
        )

    def test_closed_session_requires_closed_at(self):
        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                status=CashSession.Status.CLOSED,
                opened_by=self.user,
                closed_by=self.user,
                counted_cash_amount=Decimal("100.00"),
                expected_cash_amount=Decimal("100.00"),
                difference_amount=Decimal("0.00"),
            )

    def test_closed_session_requires_closed_by(self):
        opened_at = timezone.now()

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                status=CashSession.Status.CLOSED,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(hours=1),
                opened_by=self.user,
                counted_cash_amount=Decimal("100.00"),
                expected_cash_amount=Decimal("100.00"),
                difference_amount=Decimal("0.00"),
            )

    def test_closed_session_requires_counted_cash_amount(self):
        opened_at = timezone.now()

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                status=CashSession.Status.CLOSED,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(hours=1),
                opened_by=self.user,
                closed_by=self.user,
                expected_cash_amount=Decimal("100.00"),
                difference_amount=Decimal("0.00"),
            )

    def test_closed_session_rejects_incorrect_difference(self):
        opened_at = timezone.now()

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                status=CashSession.Status.CLOSED,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(hours=1),
                opened_by=self.user,
                closed_by=self.user,
                expected_cash_amount=Decimal("100.00"),
                counted_cash_amount=Decimal("90.00"),
                difference_amount=Decimal("0.00"),
            )

    def test_closed_at_cannot_be_before_opened_at(self):
        opened_at = timezone.now()

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                status=CashSession.Status.CLOSED,
                opened_at=opened_at,
                closed_at=opened_at - timedelta(seconds=1),
                opened_by=self.user,
                closed_by=self.user,
                expected_cash_amount=Decimal("100.00"),
                counted_cash_amount=Decimal("100.00"),
                difference_amount=Decimal("0.00"),
            )

    # ==========================================================
    # Constraints reales de base de datos
    # ==========================================================

    def test_database_rejects_negative_opening_amount(self):
        session = self._create_open_session()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashSession.objects.filter(
                    pk=session.pk,
                ).update(
                    opening_amount=Decimal("-1.00"),
                )

    def test_database_rejects_two_open_sessions_same_register(self):
        other_register = create_cash_register(
            business=self.business,
            store=self.store,
            name="Caja 2",
            code="CAJA-02",
        )

        session_1 = self._create_open_session(
            register=self.register,
        )

        session_2 = self._create_open_session(
            register=other_register,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashSession.objects.filter(
                    pk=session_2.pk,
                ).update(
                    cash_register=session_1.cash_register,
                )

    def test_database_rejects_invalid_open_state(self):
        session = self._create_open_session()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashSession.objects.filter(
                    pk=session.pk,
                ).update(
                    closed_at=timezone.now(),
                )

    def test_database_rejects_incorrect_closed_difference(self):
        session = self._create_closed_session(
            expected_cash_amount=Decimal("100.00"),
            counted_cash_amount=Decimal("90.00"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashSession.objects.filter(
                    pk=session.pk,
                ).update(
                    difference_amount=Decimal("0.00"),
                )

    def test_database_rejects_negative_counted_cash_amount(self):
        session = self._create_closed_session(
            expected_cash_amount=Decimal("100.00"),
            counted_cash_amount=Decimal("90.00"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashSession.objects.filter(
                    pk=session.pk,
                ).update(
                    counted_cash_amount=Decimal("-1.00"),
                    difference_amount=Decimal("-101.00"),
                )

    def test_database_rejects_closed_at_before_opened_at(self):
        session = self._create_closed_session()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashSession.objects.filter(
                    pk=session.pk,
                ).update(
                    closed_at=(
                        session.opened_at
                        - timedelta(seconds=1)
                    ),
                )

class CashMovementModelTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_cash_business()
        self.store = create_cash_store(
            business=self.business,
        )
        self.register = create_cash_register(
            business=self.business,
            store=self.store,
        )
        self.user = create_user(
            business=self.business,
        )

        self.session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.register,
            opened_by=self.user,
            opening_amount=Decimal("100.00"),
            expected_cash_amount=Decimal("100.00"),
        )

        self.sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("100.00"),
            cash_register=self.register,
            cash_session=self.session,
        )

        self.cash_method = PaymentMethod.objects.create(
            business=self.business,
            name="Efectivo",
            code="cash",
        )

        self.card_method = PaymentMethod.objects.create(
            business=self.business,
            name="Tarjeta",
            code="card",
        )

        self.payment = self._create_payment()

    # ==========================================================
    # Helpers
    # ==========================================================

    def _create_payment(
        self,
        *,
        sale=None,
        session=None,
        method=None,
        status=PaymentStatusChoices.COMPLETED,
        payment_type=PaymentTypeChoices.SALE_PAYMENT,
        amount=Decimal("25.00"),
    ):
        sale = sale or self.sale
        session = session or self.session
        method = method or self.cash_method

        sale_return = None

        if payment_type == PaymentTypeChoices.REFUND:
            sale_return = create_sale_return(
                business=self.business,
                store=self.store,
                original_sale=sale,
                created_by=self.user,
                reason="Devolución test",
            )

        return Payment.objects.create(
            business=self.business,
            store=self.store,
            sale=sale,
            method=method,
            cash_session=session,
            sale_return=sale_return,
            payment_type=payment_type,
            amount=amount,
            status=status,
            processed_by=self.user,
            idempotency_key=uuid4(),
        )

    def _create_manual_movement(
        self,
        *,
        movement_type=CashMovement.MovementType.CASH_IN,
        amount=Decimal("10.00"),
        balance_after=Decimal("110.00"),
    ):
        return CashMovement.objects.create(
            business=self.business,
            store=self.store,
            cash_session=self.session,
            movement_type=movement_type,
            amount=amount,
            balance_after=balance_after,
            created_by=self.user,
            reason="Movimiento manual test",
        )

    # ==========================================================
    # Creación válida
    # ==========================================================

    def test_create_sale_cash_movement_success(self):
        movement = CashMovement.objects.create(
            business=self.business,
            store=self.store,
            cash_session=self.session,
            movement_type=CashMovement.MovementType.SALE_CASH,
            amount=Decimal("25.00"),
            balance_after=Decimal("125.00"),
            sale=self.sale,
            payment=self.payment,
            created_by=self.user,
        )

        self.assertEqual(
            movement.business,
            self.business,
        )
        self.assertEqual(
            movement.store,
            self.store,
        )
        self.assertEqual(
            movement.cash_session,
            self.session,
        )
        self.assertEqual(
            movement.sale,
            self.sale,
        )
        self.assertEqual(
            movement.payment,
            self.payment,
        )
        self.assertEqual(
            movement.amount,
            Decimal("25.00"),
        )
        self.assertEqual(
            movement.balance_after,
            Decimal("125.00"),
        )

    def test_create_refund_cash_movement_success(self):
        refund_payment = self._create_payment(
            payment_type=PaymentTypeChoices.REFUND,
            amount=Decimal("20.00"),
        )

        movement = CashMovement.objects.create(
            business=self.business,
            store=self.store,
            cash_session=self.session,
            movement_type=CashMovement.MovementType.REFUND_CASH,
            amount=Decimal("20.00"),
            balance_after=Decimal("80.00"),
            sale=self.sale,
            payment=refund_payment,
            created_by=self.user,
        )

        self.assertEqual(
            movement.movement_type,
            CashMovement.MovementType.REFUND_CASH,
        )
        self.assertEqual(
            movement.payment,
            refund_payment,
        )

    def test_create_cash_in_success(self):
        movement = self._create_manual_movement(
            movement_type=CashMovement.MovementType.CASH_IN,
            amount=Decimal("20.00"),
            balance_after=Decimal("120.00"),
        )

        self.assertIsNone(movement.payment)
        self.assertIsNone(movement.sale)

        self.assertEqual(
            movement.amount,
            Decimal("20.00"),
        )

    def test_create_cash_out_success(self):
        movement = self._create_manual_movement(
            movement_type=CashMovement.MovementType.CASH_OUT,
            amount=Decimal("20.00"),
            balance_after=Decimal("80.00"),
        )

        self.assertEqual(
            movement.movement_type,
            CashMovement.MovementType.CASH_OUT,
        )
        self.assertIsNone(movement.payment)
        self.assertIsNone(movement.sale)

    def test_create_adjustment_without_origin_success(self):
        movement = self._create_manual_movement(
            movement_type=CashMovement.MovementType.ADJUSTMENT,
            amount=Decimal("5.00"),
            balance_after=Decimal("105.00"),
        )

        self.assertEqual(
            movement.movement_type,
            CashMovement.MovementType.ADJUSTMENT,
        )
        self.assertIsNone(movement.payment)
        self.assertIsNone(movement.sale)

    # ==========================================================
    # Amount
    # ==========================================================

    def test_movement_rejects_zero_amount(self):
        with self.assertRaises(ValidationError):
            self._create_manual_movement(
                amount=Decimal("0.00"),
            )

    def test_movement_rejects_negative_amount(self):
        with self.assertRaises(ValidationError):
            self._create_manual_movement(
                amount=Decimal("-1.00"),
            )

    # ==========================================================
    # Sale / Payment
    # ==========================================================

    def test_sale_cash_requires_payment_and_sale(self):
        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.SALE_CASH,
                amount=Decimal("25.00"),
                balance_after=Decimal("125.00"),
                created_by=self.user,
            )

    def test_refund_cash_requires_payment_and_sale(self):
        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.REFUND_CASH,
                amount=Decimal("20.00"),
                balance_after=Decimal("80.00"),
                created_by=self.user,
            )

    def test_cash_in_rejects_payment_and_sale(self):
        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.CASH_IN,
                amount=Decimal("25.00"),
                balance_after=Decimal("125.00"),
                sale=self.sale,
                payment=self.payment,
                created_by=self.user,
            )

    def test_cash_out_rejects_payment_and_sale(self):
        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.CASH_OUT,
                amount=Decimal("25.00"),
                balance_after=Decimal("75.00"),
                sale=self.sale,
                payment=self.payment,
                created_by=self.user,
            )

    def test_movement_rejects_non_cash_payment_method(self):
        card_payment = self._create_payment(
            method=self.card_method,
        )

        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.SALE_CASH,
                amount=Decimal("25.00"),
                balance_after=Decimal("125.00"),
                sale=self.sale,
                payment=card_payment,
                created_by=self.user,
            )

    def test_movement_rejects_pending_payment(self):
        pending_payment = self._create_payment(
            status=PaymentStatusChoices.PENDING,
        )

        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.SALE_CASH,
                amount=Decimal("25.00"),
                balance_after=Decimal("125.00"),
                sale=self.sale,
                payment=pending_payment,
                created_by=self.user,
            )

    def test_movement_type_must_match_payment_type(self):
        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.REFUND_CASH,
                amount=Decimal("25.00"),
                balance_after=Decimal("75.00"),
                sale=self.sale,
                payment=self.payment,
                created_by=self.user,
            )

    def test_same_payment_cannot_create_two_cash_movements(self):
        CashMovement.objects.create(
            business=self.business,
            store=self.store,
            cash_session=self.session,
            movement_type=CashMovement.MovementType.SALE_CASH,
            amount=Decimal("25.00"),
            balance_after=Decimal("125.00"),
            sale=self.sale,
            payment=self.payment,
            created_by=self.user,
        )

        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.SALE_CASH,
                amount=Decimal("25.00"),
                balance_after=Decimal("150.00"),
                sale=self.sale,
                payment=self.payment,
                created_by=self.user,
            )

    # ==========================================================
    # Coherencia Session / Sale / Payment
    # ==========================================================

    def test_movement_rejects_payment_from_different_cash_session(self):
        other_register = create_cash_register(
            business=self.business,
            store=self.store,
            name="Caja 2",
            code="CAJA-02",
        )

        other_session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=other_register,
            opened_by=self.user,
        )

        other_payment = self._create_payment(
            session=other_session,
        )

        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.SALE_CASH,
                amount=Decimal("25.00"),
                balance_after=Decimal("125.00"),
                sale=self.sale,
                payment=other_payment,
                created_by=self.user,
            )

    def test_movement_rejects_sale_different_from_payment_sale(self):
        other_sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("50.00"),
            cash_register=self.register,
            cash_session=self.session,
        )

        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.SALE_CASH,
                amount=Decimal("25.00"),
                balance_after=Decimal("125.00"),
                sale=other_sale,
                payment=self.payment,
                created_by=self.user,
            )

    def test_movement_rejects_session_from_another_store(self):
        other_store = create_cash_store(
            business=self.business,
            name="Otra tienda",
            code="TIENDA-02",
        )

        other_register = create_cash_register(
            business=self.business,
            store=other_store,
            name="Caja otra tienda",
            code="CAJA-01",
        )

        other_session = CashSession.objects.create(
            business=self.business,
            store=other_store,
            cash_register=other_register,
            opened_by=self.user,
        )

        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=other_session,
                movement_type=CashMovement.MovementType.CASH_IN,
                amount=Decimal("10.00"),
                balance_after=Decimal("110.00"),
                created_by=self.user,
            )

    def test_movement_rejects_created_by_from_another_business(self):
        other_business = create_cash_business(
            name="Otro negocio",
        )

        other_user = create_user(
            business=other_business,
            email="other-movement@test.com",
        )

        with self.assertRaises(ValidationError):
            CashMovement.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                movement_type=CashMovement.MovementType.CASH_IN,
                amount=Decimal("10.00"),
                balance_after=Decimal("110.00"),
                created_by=other_user,
            )

    # ==========================================================
    # Constraints reales de base de datos
    # ==========================================================

    def test_database_rejects_zero_amount(self):
        movement = self._create_manual_movement()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashMovement.objects.filter(
                    pk=movement.pk,
                ).update(
                    amount=Decimal("0.00"),
                )

    def test_database_rejects_duplicate_payment(self):
        movement_1 = CashMovement.objects.create(
            business=self.business,
            store=self.store,
            cash_session=self.session,
            movement_type=CashMovement.MovementType.SALE_CASH,
            amount=Decimal("25.00"),
            balance_after=Decimal("125.00"),
            sale=self.sale,
            payment=self.payment,
            created_by=self.user,
        )

        movement_2 = self._create_manual_movement(
            amount=Decimal("10.00"),
            balance_after=Decimal("135.00"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashMovement.objects.filter(
                    pk=movement_2.pk,
                ).update(
                    movement_type=CashMovement.MovementType.SALE_CASH,
                    sale=self.sale,
                    payment=self.payment,
                )

    def test_database_rejects_invalid_manual_movement_origin(self):
        other_payment = self._create_payment(
            amount=Decimal("10.00"),
        )

        movement = self._create_manual_movement()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashMovement.objects.filter(
                    pk=movement.pk,
                ).update(
                    payment=other_payment,
                )


class CashCountModelTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_cash_business()

        self.store = create_cash_store(
            business=self.business,
        )

        self.register = create_cash_register(
            business=self.business,
            store=self.store,
        )

        self.user = create_user(
            business=self.business,
        )

        self.session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.register,
            opened_by=self.user,
            opening_amount=Decimal("100.00"),
            expected_cash_amount=Decimal("100.00"),
        )

    def _create_count(
        self,
        *,
        counted_amount=Decimal("95.00"),
        expected_amount=Decimal("100.00"),
        notes="Arqueo test",
    ):
        return CashCount.objects.create(
            business=self.business,
            store=self.store,
            cash_session=self.session,
            counted_amount=counted_amount,
            expected_amount=expected_amount,
            difference_amount=(
                counted_amount
                - expected_amount
            ),
            counted_by=self.user,
            notes=notes,
        )

    # ==========================================================
    # Creación válida
    # ==========================================================

    def test_create_cash_count_success(self):
        cash_count = self._create_count(
            counted_amount=Decimal("95.00"),
            expected_amount=Decimal("100.00"),
        )

        self.assertEqual(
            cash_count.business,
            self.business,
        )
        self.assertEqual(
            cash_count.store,
            self.store,
        )
        self.assertEqual(
            cash_count.cash_session,
            self.session,
        )
        self.assertEqual(
            cash_count.counted_by,
            self.user,
        )

        self.assertEqual(
            cash_count.counted_amount,
            Decimal("95.00"),
        )
        self.assertEqual(
            cash_count.expected_amount,
            Decimal("100.00"),
        )
        self.assertEqual(
            cash_count.difference_amount,
            Decimal("-5.00"),
        )

    def test_cash_count_accepts_zero_counted_amount(self):
        cash_count = self._create_count(
            counted_amount=Decimal("0.00"),
            expected_amount=Decimal("100.00"),
        )

        self.assertEqual(
            cash_count.counted_amount,
            Decimal("0.00"),
        )
        self.assertEqual(
            cash_count.difference_amount,
            Decimal("-100.00"),
        )

    # ==========================================================
    # Importes
    # ==========================================================

    def test_cash_count_rejects_negative_counted_amount(self):
        with self.assertRaises(ValidationError):
            CashCount.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                counted_amount=Decimal("-1.00"),
                expected_amount=Decimal("100.00"),
                difference_amount=Decimal("-101.00"),
                counted_by=self.user,
            )

    def test_cash_count_rejects_incorrect_difference(self):
        with self.assertRaises(ValidationError):
            CashCount.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                counted_amount=Decimal("90.00"),
                expected_amount=Decimal("100.00"),

                # Incorrecto:
                # debería ser -10.00
                difference_amount=Decimal("0.00"),

                counted_by=self.user,
            )

    # ==========================================================
    # Business / Store / Session
    # ==========================================================

    def test_cash_count_rejects_session_from_another_store(self):
        other_store = create_cash_store(
            business=self.business,
            name="Otra tienda",
            code="TIENDA-02",
        )

        other_register = create_cash_register(
            business=self.business,
            store=other_store,
            name="Caja otra tienda",
            code="CAJA-01",
        )

        other_session = CashSession.objects.create(
            business=self.business,
            store=other_store,
            cash_register=other_register,
            opened_by=self.user,
        )

        with self.assertRaises(ValidationError):
            CashCount.objects.create(
                business=self.business,

                # Indicamos Store original
                store=self.store,

                # Pero Session de otra Store
                cash_session=other_session,

                counted_amount=Decimal("100.00"),
                expected_amount=Decimal("100.00"),
                difference_amount=Decimal("0.00"),
                counted_by=self.user,
            )

    def test_cash_count_rejects_session_from_another_business(self):
        other_business = create_cash_business(
            name="Otro negocio",
        )

        other_store = create_cash_store(
            business=other_business,
            name="Tienda otro negocio",
            code="TIENDA-02",
        )

        other_register = create_cash_register(
            business=other_business,
            store=other_store,
            name="Caja otro negocio",
            code="CAJA-01",
        )

        other_user = create_user(
            business=other_business,
            email="other-session@test.com",
        )

        other_session = CashSession.objects.create(
            business=other_business,
            store=other_store,
            cash_register=other_register,
            opened_by=other_user,
        )

        with self.assertRaises(ValidationError):
            CashCount.objects.create(
                business=self.business,
                store=self.store,
                cash_session=other_session,
                counted_amount=Decimal("100.00"),
                expected_amount=Decimal("100.00"),
                difference_amount=Decimal("0.00"),
                counted_by=self.user,
            )

    def test_cash_count_rejects_counted_by_from_another_business(self):
        other_business = create_cash_business(
            name="Otro negocio",
        )

        other_user = create_user(
            business=other_business,
            email="other-counter@test.com",
        )

        with self.assertRaises(ValidationError):
            CashCount.objects.create(
                business=self.business,
                store=self.store,
                cash_session=self.session,
                counted_amount=Decimal("100.00"),
                expected_amount=Decimal("100.00"),
                difference_amount=Decimal("0.00"),
                counted_by=other_user,
            )

    # ==========================================================
    # Histórico / cardinalidad
    # ==========================================================

    def test_cash_count_cannot_be_modified_after_creation(self):
        cash_count = self._create_count()

        cash_count.notes = "Intento de modificación"

        with self.assertRaises(ValidationError):
            cash_count.save()

    def test_same_session_can_currently_have_multiple_counts(self):
        count_1 = self._create_count(
            counted_amount=Decimal("95.00"),
            expected_amount=Decimal("100.00"),
            notes="Primer conteo",
        )

        count_2 = self._create_count(
            counted_amount=Decimal("96.00"),
            expected_amount=Decimal("100.00"),
            notes="Segundo conteo",
        )

        self.assertNotEqual(
            count_1.pk,
            count_2.pk,
        )

        self.assertEqual(
            self.session.counts.count(),
            2,
        )

    # ==========================================================
    # Constraints reales de base de datos
    # ==========================================================

    def test_database_rejects_negative_counted_amount(self):
        cash_count = self._create_count()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashCount.objects.filter(
                    pk=cash_count.pk,
                ).update(
                    counted_amount=Decimal("-1.00"),
                    difference_amount=Decimal("-101.00"),
                )

    def test_database_rejects_incorrect_difference(self):
        cash_count = self._create_count(
            counted_amount=Decimal("95.00"),
            expected_amount=Decimal("100.00"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashCount.objects.filter(
                    pk=cash_count.pk,
                ).update(
                    difference_amount=Decimal("0.00"),
                )