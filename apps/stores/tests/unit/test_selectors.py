from django.test import TestCase

from apps.stores.selectors import (
    get_default_store_for_user,
    get_next_active_store_for_business,
    get_operational_store_for_user,
    get_store_for_business,
    get_store_access_for_user,
    get_stores_available_for_user,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_store_access,
    create_user,
)


class StoreSelectorsTests(TestCase):
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
            email="owner@stores.com",
            role=RoleChoices.OWNER,
        )
        self.manager = create_user(
            business=self.business,
            email="manager@stores.com",
            role=RoleChoices.MANAGER,
        )
        self.cashier = create_user(
            business=self.business,
            email="cashier@stores.com",
            role=RoleChoices.CASHIER,
        )

        self.default_store = create_store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
            is_active=True,
        )
        self.default_store.is_default = True
        self.default_store.save(update_fields=["is_default", "updated_at"])

        self.secondary_store = create_store(
            business=self.business,
            name="Tienda Norte",
            code="NORTE",
            is_active=True,
        )
        self.inactive_store = create_store(
            business=self.business,
            name="Tienda Sur",
            code="SUR",
            is_active=False,
        )

        self.other_store = create_store(
            business=self.other_business,
            name="Tienda Externa",
            code="EXT",
            is_active=True,
        )

    def test_owner_gets_all_active_stores_from_own_business(self):
        stores = list(
            get_stores_available_for_user(
                user=self.owner,
                only_active=True,
            )
        )

        self.assertEqual(stores, [self.default_store, self.secondary_store])

    def test_owner_can_request_inactive_stores_too(self):
        stores = list(
            get_stores_available_for_user(
                user=self.owner,
                only_active=False,
            )
        )

        self.assertEqual(
            stores,
            [self.default_store, self.secondary_store, self.inactive_store],
        )

    def test_manager_only_gets_stores_with_active_access(self):
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.default_store,
            is_active=True,
        )
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.secondary_store,
            is_active=False,
        )

        stores = list(
            get_stores_available_for_user(
                user=self.manager,
                only_active=True,
            )
        )

        self.assertEqual(stores, [self.default_store])

    def test_cashier_without_access_gets_empty_queryset(self):
        stores = get_stores_available_for_user(
            user=self.cashier,
            only_active=True,
        )

        self.assertFalse(stores.exists())

    def test_default_store_for_user_returns_accessible_default(self):
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.default_store,
            is_active=True,
        )

        store = get_default_store_for_user(
            user=self.manager,
            only_active=True,
        )

        self.assertEqual(store, self.default_store)

    def test_default_store_for_user_returns_none_when_no_accessible_default(self):
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.secondary_store,
            is_active=True,
        )

        store = get_default_store_for_user(
            user=self.manager,
            only_active=True,
        )

        self.assertIsNone(store)

    def test_operational_store_uses_default_first(self):
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.default_store,
            is_active=True,
        )
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.secondary_store,
            is_active=True,
        )

        store = get_operational_store_for_user(user=self.manager)

        self.assertEqual(store, self.default_store)

    def test_operational_store_falls_back_to_first_accessible(self):
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.secondary_store,
            is_active=True,
        )

        store = get_operational_store_for_user(user=self.manager)

        self.assertEqual(store, self.secondary_store)

    def test_get_store_access_for_user_returns_active_access_row(self):
        access = create_store_access(
            business=self.business,
            user=self.cashier,
            store=self.secondary_store,
            can_sell=True,
            can_open_cash=True,
            can_close_cash=False,
            is_active=True,
        )

        selected = get_store_access_for_user(
            user=self.cashier,
            store=self.secondary_store,
        )

        self.assertEqual(selected, access)

    def test_get_store_access_for_user_returns_none_for_owner(self):
        selected = get_store_access_for_user(
            user=self.owner,
            store=self.default_store,
        )

        self.assertIsNone(selected)

    def test_get_store_access_for_user_returns_none_for_other_business_store(self):
        selected = get_store_access_for_user(
            user=self.cashier,
            store=self.other_store,
        )

        self.assertIsNone(selected)

    def test_get_store_for_business_returns_store_when_belongs(self):
        selected = get_store_for_business(
            business=self.business,
            store=self.default_store,
        )

        self.assertEqual(selected, self.default_store)

    def test_get_store_for_business_returns_none_when_not_belongs(self):
        selected = get_store_for_business(
            business=self.business,
            store=self.other_store,
        )

        self.assertIsNone(selected)

    def test_get_next_active_store_for_business_returns_ordered_candidate(self):
        selected = get_next_active_store_for_business(
            business=self.business,
            excluded_store=self.default_store,
        )

        self.assertEqual(selected, self.secondary_store)
