from uuid import uuid4

from django.test import TestCase

from apps.core.models import Business
from apps.purchases.models import Purchase, Supplier
from apps.purchases.selectors import (
    get_accessible_purchase_stores,
    get_purchases_for_user,
    get_suppliers_for_business,
)
from apps.stores.models import Store
from apps.users.models import RoleChoices, UserStoreAccess
from apps.users.tests.factories import create_user


class PurchaseSelectorTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="A", slug=f"a-{uuid4().hex}")
        self.other = Business.objects.create(name="B", slug=f"b-{uuid4().hex}")
        self.store_a = Store.objects.create(business=self.business, name="A", code="A1")
        self.store_b = Store.objects.create(business=self.business, name="B", code="B1")
        self.owner = create_user(business=self.business, role=RoleChoices.OWNER)
        self.manager = create_user(business=self.business, role=RoleChoices.MANAGER)
        UserStoreAccess.objects.create(
            business=self.business, user=self.manager, store=self.store_a
        )
        self.supplier = Supplier.objects.create(
            business=self.business, name="Proveedor buscable", tax_identifier="A1"
        )
        self.other_supplier = Supplier.objects.create(business=self.other, name="Ajeno")
        self.purchase_a = Purchase.objects.create(
            business=self.business,
            store=self.store_a,
            supplier=self.supplier,
            created_by=self.owner,
            reference="REF-A",
        )
        self.purchase_b = Purchase.objects.create(
            business=self.business,
            store=self.store_b,
            supplier=self.supplier,
            created_by=self.owner,
            reference="REF-B",
        )

    def test_supplier_query_never_leaks_business(self):
        self.assertQuerySetEqual(
            get_suppliers_for_business(business=self.business, query="Proveedor"),
            [self.supplier],
        )
        self.assertNotIn(
            self.other_supplier,
            get_suppliers_for_business(business=self.business, status="all"),
        )

    def test_owner_sees_all_stores_manager_only_accessible_store(self):
        self.assertEqual(
            set(
                get_accessible_purchase_stores(business=self.business, user=self.owner)
            ),
            {self.store_a, self.store_b},
        )
        self.assertQuerySetEqual(
            get_accessible_purchase_stores(business=self.business, user=self.manager),
            [self.store_a],
        )
        self.assertQuerySetEqual(
            get_purchases_for_user(business=self.business, user=self.manager),
            [self.purchase_a],
        )

    def test_purchase_filters(self):
        self.assertQuerySetEqual(
            get_purchases_for_user(
                business=self.business,
                user=self.owner,
                query="REF-A",
                store=self.store_a,
                supplier=self.supplier,
            ),
            [self.purchase_a],
        )
