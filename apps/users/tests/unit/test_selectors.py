from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.users.models import RoleChoices
from apps.users.selectors import get_users_for_admin
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_store_access,
    create_user,
)


class UserSelectorsTests(TestCase):
    def setUp(self):
        self.business = create_business("Selectors A", "selectors-a")
        self.other = create_business("Selectors B", "selectors-b")
        self.store = create_store(self.business, "Centro", "CENTRO")
        self.owner = create_user(
            self.business,
            "ana.owner@test.com",
            role=RoleChoices.OWNER,
            first_name="Ana",
            last_name="Propietaria",
        )
        self.manager = create_user(
            self.business,
            "laura.manager@test.com",
            role=RoleChoices.MANAGER,
            first_name="Laura",
            last_name="Martín",
        )
        self.cashier = create_user(
            self.business,
            "carlos.cashier@test.com",
            role=RoleChoices.CASHIER,
            first_name="Carlos",
            last_name="Caja",
            is_active=False,
        )
        self.foreign = create_user(
            self.other, "foreign@test.com", role=RoleChoices.OWNER
        )
        create_store_access(self.business, self.manager, self.store, is_active=True)
        create_store_access(self.business, self.cashier, self.store, is_active=False)

    def ids(self, **filters):
        return set(
            get_users_for_admin(
                business=self.business, status="all", **filters
            ).values_list("pk", flat=True)
        )

    def test_searches_first_last_and_email(self):
        self.assertEqual(self.ids(q="Laura"), {self.manager.pk})
        self.assertEqual(self.ids(q="Martín"), {self.manager.pk})
        self.assertEqual(self.ids(q="owner@"), {self.owner.pk})

    def test_filters_each_role(self):
        self.assertEqual(self.ids(role="owner"), {self.owner.pk})
        self.assertEqual(self.ids(role="manager"), {self.manager.pk})
        self.assertEqual(self.ids(role="cashier"), {self.cashier.pk})

    def test_filters_status(self):
        self.assertEqual(
            set(
                get_users_for_admin(
                    business=self.business, status="active"
                ).values_list("pk", flat=True)
            ),
            {self.owner.pk, self.manager.pk},
        )
        self.assertEqual(
            set(
                get_users_for_admin(
                    business=self.business, status="inactive"
                ).values_list("pk", flat=True)
            ),
            {self.cashier.pk},
        )
        self.assertEqual(self.ids(), {self.owner.pk, self.manager.pk, self.cashier.pk})

    def test_store_filter_honours_owner_global_and_active_access(self):
        self.assertEqual(self.ids(store=self.store), {self.owner.pk, self.manager.pk})

    def test_never_returns_cross_tenant(self):
        self.assertNotIn(self.foreign.pk, self.ids())

    def test_prefetch_query_count_is_stable(self):
        with CaptureQueriesContext(connection) as before:
            list(get_users_for_admin(business=self.business, status="all"))
        for i in range(4):
            create_user(self.business, f"extra-{i}@test.com")
        with CaptureQueriesContext(connection) as after:
            list(get_users_for_admin(business=self.business, status="all"))
        self.assertEqual(len(before), len(after))
