from django.contrib import admin
from django.test import RequestFactory, TestCase

from apps.customers.admin import (
    CustomerAccountAdmin,
    CustomerAccountEntryAdmin,
    CustomerAdmin,
)
from apps.customers.models import Customer, CustomerAccount, CustomerAccountEntry
from apps.customers.tests.factories import create_account, create_customer_user
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_user


class CustomerAdminTests(TestCase):
    def test_permissions_and_business_scoping(self):
        b1 = create_business(slug="ad1")
        b2 = create_business(name="B2", slug="ad2")
        create_account(business=b1)
        create_account(business=b2)
        user = create_customer_user(business=b1, role=RoleChoices.MANAGER)
        superuser = create_user(
            business=None,
            email="root@admin.test",
            role=RoleChoices.OWNER,
            is_superuser=True,
            is_staff=True,
        )
        request = RequestFactory().get("/")
        request.user = user
        customer_admin = CustomerAdmin(Customer, admin.site)
        account_admin = CustomerAccountAdmin(CustomerAccount, admin.site)
        entry_admin = CustomerAccountEntryAdmin(CustomerAccountEntry, admin.site)
        self.assertFalse(customer_admin.has_delete_permission(request))
        self.assertIn("balance", account_admin.get_readonly_fields(request))
        self.assertFalse(account_admin.has_add_permission(request))
        self.assertFalse(account_admin.has_delete_permission(request))
        self.assertFalse(entry_admin.has_add_permission(request))
        self.assertFalse(entry_admin.has_change_permission(request))
        self.assertFalse(entry_admin.has_delete_permission(request))
        self.assertEqual(customer_admin.get_queryset(request).count(), 1)
        request.user = superuser
        self.assertEqual(customer_admin.get_queryset(request).count(), 2)
