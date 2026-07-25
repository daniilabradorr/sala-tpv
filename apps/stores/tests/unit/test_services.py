from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from unittest.mock import patch

from apps.stores.models import Store
from apps.stores.services import (
    activate_store,
    deactivate_store,
    delete_store,
    set_default_store,
)
from apps.users.tests.factories import create_business, create_store


class StoreServicesTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )
        self.other_business = create_business(
            name="Negocio B",
            slug="negocio-b",
        )

        self.store = create_store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
            is_active=True,
        )

        self.other_active_store = create_store(
            business=self.business,
            name="Tienda Norte",
            code="NORTE",
            is_active=True,
        )

        self.store.is_default = True
        self.store.save(update_fields=["is_default", "updated_at"])

        self.other_active_store.refresh_from_db()
        self.assertFalse(self.other_active_store.is_default)

    def test_set_default_store_success(self):
        updated = set_default_store(
            business=self.business,
            store=self.other_active_store,
        )

        self.store.refresh_from_db()
        self.other_active_store.refresh_from_db()
        self.assertEqual(updated.pk, self.other_active_store.pk)
        self.assertFalse(self.store.is_default)
        self.assertTrue(self.other_active_store.is_default)

    def test_set_default_store_raises_for_inactive_store(self):
        self.store.is_active = False
        self.store.save(update_fields=["is_active", "updated_at"])

        with self.assertRaises(ValidationError):
            set_default_store(
                business=self.business,
                store=self.store,
            )

    def test_set_default_store_raises_for_wrong_business(self):
        with self.assertRaises(ValidationError):
            set_default_store(
                business=self.other_business,
                store=self.store,
            )

    def test_set_default_store_is_idempotent(self):
        first = set_default_store(
            business=self.business,
            store=self.store,
        )
        second = set_default_store(
            business=self.business,
            store=self.store,
        )

        self.assertEqual(first.pk, second.pk)
        self.store.refresh_from_db()
        self.assertTrue(self.store.is_default)

    def test_activate_store_success(self):
        self.store.is_active = False
        self.store.is_default = False
        self.store.save(update_fields=["is_active", "is_default", "updated_at"])

        self.other_active_store.is_default = True
        self.other_active_store.save(update_fields=["is_default", "updated_at"])

        updated = activate_store(
            business=self.business,
            store=self.store,
        )

        self.store.refresh_from_db()
        self.assertEqual(updated.pk, self.store.pk)
        self.assertTrue(self.store.is_active)
        self.assertFalse(self.store.is_default)

    def test_activate_store_raises_for_invalid_business(self):
        with self.assertRaises(ValidationError):
            activate_store(
                business=None,
                store=self.store,
            )

    def test_activate_store_assigns_default_when_none_exists(self):
        self.store.is_active = False
        self.store.is_default = False
        self.store.save(update_fields=["is_active", "is_default", "updated_at"])

        Store.objects.filter(pk=self.other_active_store.pk).update(
            is_default=False,
        )

        updated = activate_store(
            business=self.business,
            store=self.store,
        )

        self.store.refresh_from_db()
        self.assertEqual(updated.pk, self.store.pk)
        self.assertTrue(self.store.is_active)
        self.assertTrue(self.store.is_default)

    def test_activate_store_is_idempotent(self):
        first = activate_store(
            business=self.business,
            store=self.store,
        )
        second = activate_store(
            business=self.business,
            store=self.store,
        )

        self.assertEqual(first.pk, second.pk)

    def test_deactivate_store_success(self):
        updated = deactivate_store(
            business=self.business,
            store=self.store,
        )

        self.store.refresh_from_db()
        self.other_active_store.refresh_from_db()
        self.assertEqual(updated.pk, self.store.pk)
        self.assertFalse(self.store.is_active)
        self.assertFalse(self.store.is_default)
        self.assertTrue(self.other_active_store.is_default)

    def test_deactivate_store_raises_for_invalid_store(self):
        with self.assertRaises(ValidationError):
            deactivate_store(
                business=self.business,
                store=None,
            )

    def test_deactivate_last_active_store_leaves_business_without_default(self):
        Store.objects.filter(
            pk=self.other_active_store.pk,
        ).update(
            is_active=False,
            is_default=False,
        )

        deactivate_store(
            business=self.business,
            store=self.store,
        )

        self.assertFalse(
            Store.objects.filter(
                business=self.business,
                is_default=True,
            ).exists()
        )

    def test_deactivate_store_is_idempotent(self):
        first = deactivate_store(
            business=self.business,
            store=self.store,
        )
        second = deactivate_store(
            business=self.business,
            store=self.store,
        )

        self.assertEqual(first.pk, second.pk)

    def test_delete_store_success(self):
        store_name = delete_store(
            business=self.business,
            store=self.store,
        )

        self.assertEqual(store_name, "Tienda Centro")
        self.assertFalse(type(self.store).objects.filter(pk=self.store.pk).exists())

    def test_delete_default_store_assigns_replacement(self):
        delete_store(
            business=self.business,
            store=self.store,
        )

        self.other_active_store.refresh_from_db()
        self.assertTrue(self.other_active_store.is_default)

    def test_delete_store_raises_for_wrong_business(self):
        with self.assertRaises(ValidationError):
            delete_store(
                business=self.other_business,
                store=self.store,
            )

    def test_delete_store_raises_validation_error_for_protected_relations(self):
        protected_error = ProtectedError(
            "protected",
            protected_objects=[],
        )

        with patch(
            "apps.stores.models.Store.delete",
            side_effect=protected_error,
        ):
            with self.assertRaises(ValidationError) as context:
                delete_store(
                    business=self.business,
                    store=self.store,
                )

        self.assertIn("Desactívala", str(context.exception))
