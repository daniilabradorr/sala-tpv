from django.test import TestCase

from apps.stores.helpers import (
    belongs_to_business,
    can_access_store,
    can_close_cash_register,
    can_manage_business_settings,
    can_manage_users,
    can_open_cash_register,
    can_perform_sensitive_action,
    can_sell_in_store,
    can_view_reports,
    is_cashier,
    is_manager,
    is_owner,
    is_owner_or_manager,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_store_access,
    create_user,
)


class StoreHelpersTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )
        self.other_business = create_business(
            name="Negocio B",
            slug="negocio-b",
        )

        self.owner = create_user(
            business=self.business,
            email="owner@helpers.com",
            role=RoleChoices.OWNER,
        )
        self.manager = create_user(
            business=self.business,
            email="manager@helpers.com",
            role=RoleChoices.MANAGER,
        )
        self.cashier = create_user(
            business=self.business,
            email="cashier@helpers.com",
            role=RoleChoices.CASHIER,
        )

        self.store = create_store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
            is_active=True,
        )
        self.inactive_store = create_store(
            business=self.business,
            name="Tienda Inactiva",
            code="INACTIVA",
            is_active=False,
        )
        self.other_store = create_store(
            business=self.other_business,
            name="Tienda Externa",
            code="EXT",
            is_active=True,
        )

    def test_role_helpers(self):
        self.assertTrue(is_owner(self.owner))
        self.assertFalse(is_owner(self.manager))
        self.assertTrue(is_manager(self.manager))
        self.assertFalse(is_manager(self.cashier))
        self.assertTrue(is_cashier(self.cashier))
        self.assertTrue(is_owner_or_manager(self.owner))
        self.assertTrue(is_owner_or_manager(self.manager))
        self.assertFalse(is_owner_or_manager(self.cashier))

    def test_belongs_to_business(self):
        self.assertTrue(belongs_to_business(self.owner, self.business))
        self.assertFalse(belongs_to_business(self.owner, self.other_business))

    def test_owner_can_access_own_store(self):
        self.assertTrue(can_access_store(self.owner, self.store))

    def test_manager_requires_active_access(self):
        self.assertFalse(can_access_store(self.manager, self.store))

        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.store,
            is_active=True,
        )
        self.assertTrue(can_access_store(self.manager, self.store))

    def test_cannot_access_store_from_other_business(self):
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.store,
            is_active=True,
        )

        self.assertFalse(can_access_store(self.manager, self.other_store))

    def test_can_sell_requires_active_store(self):
        create_store_access(
            business=self.business,
            user=self.cashier,
            store=self.store,
            can_sell=True,
            is_active=True,
        )
        create_store_access(
            business=self.business,
            user=self.cashier,
            store=self.inactive_store,
            can_sell=True,
            is_active=True,
        )

        self.assertTrue(can_sell_in_store(self.cashier, self.store))
        self.assertFalse(can_sell_in_store(self.cashier, self.inactive_store))

    def test_open_close_cash_permissions(self):
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.store,
            can_open_cash=True,
            can_close_cash=False,
            is_active=True,
        )

        self.assertTrue(can_open_cash_register(self.manager, self.store))
        self.assertFalse(can_close_cash_register(self.manager, self.store))

    def test_global_permission_helpers(self):
        self.assertTrue(can_manage_users(self.owner))
        self.assertTrue(can_manage_users(self.manager))
        self.assertFalse(can_manage_users(self.cashier))

        self.assertTrue(can_manage_business_settings(self.owner))
        self.assertFalse(can_manage_business_settings(self.manager))

        self.assertTrue(can_view_reports(self.owner))
        self.assertTrue(can_view_reports(self.manager))
        self.assertFalse(can_view_reports(self.cashier))

        self.assertTrue(can_perform_sensitive_action(self.owner))
        self.assertTrue(can_perform_sensitive_action(self.manager))
        self.assertFalse(can_perform_sensitive_action(self.cashier))
