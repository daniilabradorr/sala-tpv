from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.cash_register.models import CashRegister, CashSession
from apps.sales.tests.factories import (
    create_sales_business,
    create_sales_store,
    create_sales_user,
)


class CashRegisterModelTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)

    def test_register_accepts_store_from_same_business(self):
        register = CashRegister.objects.create(
            business=self.business, store=self.store, name="Caja principal"
        )

        self.assertEqual(register.business, self.business)
        self.assertEqual(register.store, self.store)
        self.assertTrue(register.is_active)

    def test_register_rejects_store_from_another_business(self):
        other_business = create_sales_business(name="Otro negocio")
        other_store = create_sales_store(business=other_business)

        with self.assertRaises(ValidationError):
            CashRegister.objects.create(
                business=self.business, store=other_store, name="Caja inválida"
            )


class CashSessionModelTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.register = CashRegister.objects.create(
            business=self.business, store=self.store, name="Caja principal"
        )

    def test_open_session_is_open(self):
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.register,
            opened_by=self.user,
        )

        self.assertTrue(session.is_open)

    def test_closed_session_requires_closed_at_and_is_not_open(self):
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.register,
            opened_by=self.user,
            closed_by=self.user,
            status=CashSession.Status.CLOSED,
            closed_at=timezone.now(),
        )

        self.assertFalse(session.is_open)

        session.closed_at = None
        with self.assertRaises(ValidationError):
            session.save()

    def test_session_rejects_register_from_another_store(self):
        other_store = create_sales_store(business=self.business, name="Otra tienda")

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=other_store,
                cash_register=self.register,
                opened_by=self.user,
            )

    def test_session_rejects_user_from_another_business(self):
        other_business = create_sales_business(name="Otro negocio")
        other_user = create_sales_user(business=other_business)

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                opened_by=other_user,
            )

    def test_session_rejects_closed_by_from_another_business(self):
        other_business = create_sales_business(name="Otro negocio")
        other_user = create_sales_user(business=other_business)

        with self.assertRaises(ValidationError):
            CashSession.objects.create(
                business=self.business,
                store=self.store,
                cash_register=self.register,
                opened_by=self.user,
                closed_by=other_user,
                status=CashSession.Status.CLOSED,
                closed_at=timezone.now(),
            )
