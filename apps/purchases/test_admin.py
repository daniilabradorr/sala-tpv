from uuid import uuid4

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase

from apps.core.models import Business
from apps.purchases.admin import PurchaseAdmin, PurchaseReceiptAdmin
from apps.purchases.models import Purchase, PurchaseReceipt
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


class PurchaseReadOnlyAdminTests(TestCase):
    def setUp(self):
        self.user = create_user(
            business=Business.objects.create(name="Admin", slug=f"admin-{uuid4().hex}"),
            role=RoleChoices.MANAGER,
            email="purchases-admin@test.com",
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff", "updated_at"])
        self.request = RequestFactory().get("/admin/purchases/")
        self.request.user = self.user

    def test_purchase_and_receipt_admins_deny_mutations(self):
        for model, admin_class in (
            (Purchase, PurchaseAdmin),
            (PurchaseReceipt, PurchaseReceiptAdmin),
        ):
            model_admin = admin_class(model, AdminSite())
            with self.subTest(model=model):
                self.assertFalse(model_admin.has_add_permission(self.request))
                self.assertFalse(model_admin.has_change_permission(self.request))
                self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_read_only_admin_does_not_grant_view_permission(self):
        model_admin = PurchaseAdmin(Purchase, AdminSite())
        self.assertFalse(model_admin.has_view_permission(self.request))
