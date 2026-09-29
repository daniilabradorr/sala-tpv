from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.cash_register.models import CashRegister, CashSession
from apps.cash_register.services import (
    activate_cash_register,
    create_cash_register,
    deactivate_cash_register,
    update_cash_register,
)
from apps.core.models import Business
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices


class CashRegisterAdminServiceTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Admin cash")
        self.store = Store.objects.create(
            business=self.business, name="Centro", code="CENTRO"
        )
        self.user = CustomUser.objects.create_user(
            business=self.business,
            email="cash-admin@example.com",
            password="test",
            role=RoleChoices.OWNER,
        )

    def test_create_update_and_idempotent_lifecycle(self):
        register = create_cash_register(
            business=self.business,
            store=self.store,
            name="  Principal  ",
            code=" caja-01 ",
        )
        self.assertEqual((register.name, register.code), ("Principal", "CAJA-01"))
        register = update_cash_register(
            business=self.business,
            store=self.store,
            cash_register=register,
            name="Mostrador",
            code="caja-02",
        )
        self.assertEqual((register.name, register.code), ("Mostrador", "CAJA-02"))
        deactivate_cash_register(
            business=self.business, store=self.store, cash_register=register
        )
        deactivate_cash_register(
            business=self.business, store=self.store, cash_register=register
        )
        activate_cash_register(
            business=self.business, store=self.store, cash_register=register
        )
        register.refresh_from_db()
        self.assertTrue(register.is_active)

    def test_open_session_blocks_register_deactivation(self):
        register = CashRegister.objects.create(
            business=self.business, store=self.store, name="Principal", code="CAJA-01"
        )
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        with self.assertRaisesMessage(ValidationError, "sesión abierta"):
            deactivate_cash_register(
                business=self.business, store=self.store, cash_register=register
            )
        register.refresh_from_db()
        session.refresh_from_db()
        self.assertTrue(register.is_active)
        self.assertEqual(session.status, CashSession.Status.OPEN)
