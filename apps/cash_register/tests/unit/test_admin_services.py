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

    def test_duplicate_name_and_code_are_rejected(self):
        create_cash_register(
            business=self.business,
            store=self.store,
            name="Principal",
            code="CAJA-01",
        )
        with self.assertRaises(ValidationError):
            create_cash_register(
                business=self.business,
                store=self.store,
                name="Principal",
                code="CAJA-02",
            )
        with self.assertRaises(ValidationError):
            create_cash_register(
                business=self.business,
                store=self.store,
                name="Secundaria",
                code="CAJA-01",
            )

    def test_create_rejects_wrong_business_store_pair(self):
        other_business = Business.objects.create(name="Other admin cash")
        other_store = Store.objects.create(
            business=other_business, name="Other", code="OTHER"
        )
        with self.assertRaisesMessage(ValidationError, "no pertenece"):
            create_cash_register(
                business=self.business,
                store=other_store,
                name="Invalid",
                code="INVALID",
            )

    def test_update_rejects_wrong_store_and_preserves_tenant_and_store(self):
        register = create_cash_register(
            business=self.business,
            store=self.store,
            name="Principal",
            code="CAJA-01",
        )
        other_store = Store.objects.create(
            business=self.business, name="Norte", code="NORTE"
        )
        with self.assertRaisesMessage(ValidationError, "no pertenece"):
            update_cash_register(
                business=self.business,
                store=other_store,
                cash_register=register,
                name="Moved",
                code="MOVED",
            )
        register.refresh_from_db()
        self.assertEqual(register.business, self.business)
        self.assertEqual(register.store, self.store)
        self.assertEqual(register.name, "Principal")

    def test_activate_and_deactivate_are_individually_idempotent(self):
        register = create_cash_register(
            business=self.business,
            store=self.store,
            name="Principal",
            code="CAJA-01",
        )
        first = activate_cash_register(
            business=self.business, store=self.store, cash_register=register
        )
        second = activate_cash_register(
            business=self.business, store=self.store, cash_register=register
        )
        self.assertTrue(first.is_active)
        self.assertTrue(second.is_active)
        first = deactivate_cash_register(
            business=self.business, store=self.store, cash_register=register
        )
        second = deactivate_cash_register(
            business=self.business, store=self.store, cash_register=register
        )
        self.assertFalse(first.is_active)
        self.assertFalse(second.is_active)
