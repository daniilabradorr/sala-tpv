from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from unittest.mock import patch
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess
from apps.users.services import (
    activate_user,
    create_user_with_store_accesses,
    deactivate_user,
    update_user,
    update_user_store_accesses,
)
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_store_access,
    create_user,
)


class UserServicesTests(TestCase):
    def setUp(self):
        self.business = create_business("Services A", "services-a")
        self.other = create_business("Services B", "services-b")
        self.store = create_store(self.business, "Centro", "CENTRO")
        self.foreign_store = create_store(self.other, "Ajena", "AJENA")
        self.owner = create_user(
            self.business, "owner-services@test.com", role=RoleChoices.OWNER
        )
        self.manager = create_user(
            self.business, "manager-services@test.com", role=RoleChoices.MANAGER
        )
        self.cashier = create_user(
            self.business, "cashier-services@test.com", role=RoleChoices.CASHIER
        )
        self.target = create_user(self.business, "target-services@test.com")
        self.foreign = create_user(self.other, "foreign-services@test.com")

    def data(self, role=RoleChoices.CASHIER):
        return {
            "email": "new-services@test.com",
            "first_name": "New",
            "last_name": "User",
            "phone": "600000000",
            "role": role,
            "password": "secret-pass-123",
            "password_confirm": "secret-pass-123",
        }

    def test_atomic_create_hashes_password_and_access(self):
        user = create_user_with_store_accesses(
            actor=self.owner,
            user_data=self.data(),
            accesses={
                self.store.pk: {
                    "is_active": True,
                    "can_sell": True,
                    "can_open_cash": True,
                    "can_close_cash": False,
                }
            },
        )
        self.assertTrue(user.check_password("secret-pass-123"))
        self.assertTrue(
            UserStoreAccess.objects.get(user=user, store=self.store).can_open_cash
        )

    def test_atomic_create_rolls_back(self):
        with patch(
            "apps.users.services._update_accesses", side_effect=ValidationError("boom")
        ):
            with self.assertRaises(ValidationError):
                create_user_with_store_accesses(
                    actor=self.owner, user_data=self.data(), accesses={}
                )
        self.assertFalse(
            CustomUser.objects.filter(email="new-services@test.com").exists()
        )

    def test_manager_cannot_create_owner(self):
        with self.assertRaises(PermissionDenied):
            create_user_with_store_accesses(
                actor=self.manager, user_data=self.data(RoleChoices.OWNER), accesses={}
            )

    def test_cashier_cannot_create_user_through_service(self):
        with self.assertRaises(PermissionDenied):
            create_user_with_store_accesses(
                actor=self.cashier, user_data=self.data(), accesses={}
            )

    def test_update_is_scoped_and_preserves_email_status_and_access(self):
        access = create_store_access(self.business, self.target, self.store)
        updated = update_user(
            actor=self.owner,
            target_user=self.target,
            data={
                "first_name": "Changed",
                "role": RoleChoices.MANAGER,
                "email": "forged@test.com",
                "is_active": False,
            },
        )
        self.assertEqual(updated.email, "target-services@test.com")
        self.assertTrue(updated.is_active)
        self.assertTrue(UserStoreAccess.objects.filter(pk=access.pk).exists())
        with self.assertRaises(PermissionDenied):
            update_user(
                actor=self.owner, target_user=self.foreign, data={"first_name": "No"}
            )

    def test_access_off_preserves_row_and_can_reactivate(self):
        access = create_store_access(
            self.business, self.target, self.store, can_sell=True
        )
        off = {
            self.store.pk: {
                "is_active": False,
                "can_sell": True,
                "can_open_cash": False,
                "can_close_cash": False,
            }
        }
        update_user_store_accesses(
            actor=self.owner, target_user=self.target, accesses=off
        )
        access.refresh_from_db()
        self.assertFalse(access.is_active)
        self.assertTrue(access.can_sell)
        off[self.store.pk]["is_active"] = True
        update_user_store_accesses(
            actor=self.owner, target_user=self.target, accesses=off
        )
        access.refresh_from_db()
        self.assertTrue(access.is_active)

    def test_access_rejects_cross_tenant_store(self):
        with self.assertRaises(ValidationError):
            update_user_store_accesses(
                actor=self.owner,
                target_user=self.target,
                accesses={
                    self.foreign_store.pk: {
                        "is_active": True,
                        "can_sell": True,
                        "can_open_cash": False,
                        "can_close_cash": False,
                    }
                },
            )

    def test_lifecycle_preserves_access_and_blocks_self(self):
        access = create_store_access(self.business, self.target, self.store)
        deactivate_user(actor=self.owner, target_user=self.target)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertTrue(UserStoreAccess.objects.filter(pk=access.pk).exists())
        activate_user(actor=self.owner, target_user=self.target)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        with self.assertRaises(ValidationError):
            deactivate_user(actor=self.owner, target_user=self.owner)
