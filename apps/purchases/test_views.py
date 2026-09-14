from uuid import uuid4

from django.test import TestCase
from django.urls import reverse

from apps.core.models import Business
from apps.purchases.models import Purchase, Supplier
from apps.stores.models import Store
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


class PurchaseViewAccessTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="A", slug=f"a-{uuid4().hex}")
        self.store = Store.objects.create(business=self.business, name="A", code="A1")
        self.supplier = Supplier.objects.create(
            business=self.business, name="Proveedor"
        )
        self.owner = create_user(business=self.business, role=RoleChoices.OWNER)
        self.manager = create_user(business=self.business, role=RoleChoices.MANAGER)
        self.cashier = create_user(business=self.business, role=RoleChoices.CASHIER)
        self.purchase = Purchase.objects.create(
            business=self.business,
            store=self.store,
            supplier=self.supplier,
            created_by=self.owner,
        )

    def test_owner_can_open_purchase_list(self):
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("purchases:purchase_list")).status_code, 200
        )

    def test_cashier_is_forbidden(self):
        self.client.force_login(self.cashier)
        self.assertEqual(
            self.client.get(reverse("purchases:purchase_list")).status_code, 403
        )

    def test_manager_without_store_access_gets_404_for_detail(self):
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(
                reverse("purchases:purchase_detail", kwargs={"pk": self.purchase.pk})
            ).status_code,
            404,
        )

    def test_actions_reject_get(self):
        self.client.force_login(self.owner)
        for name in ("purchase_order", "purchase_cancel"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(
                        reverse(f"purchases:{name}", kwargs={"pk": self.purchase.pk})
                    ).status_code,
                    405,
                )
