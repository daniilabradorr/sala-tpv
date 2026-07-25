from django.core.exceptions import ValidationError
from django.test import TestCase

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

    def test_set_default_store_success(self):
        updated = set_default_store(
            business=self.business,
            store=self.store,
        )

        self.store.refresh_from_db()
        self.assertEqual(updated.pk, self.store.pk)
        self.assertTrue(self.store.is_default)

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

    def test_activate_store_success(self):
        self.store.is_active = False
        self.store.save(update_fields=["is_active", "updated_at"])

        updated = activate_store(
            business=self.business,
            store=self.store,
        )

        self.store.refresh_from_db()
        self.assertEqual(updated.pk, self.store.pk)
        self.assertTrue(self.store.is_active)

    def test_activate_store_raises_for_invalid_business(self):
        with self.assertRaises(ValidationError):
            activate_store(
                business=None,
                store=self.store,
            )

    def test_deactivate_store_success(self):
        updated = deactivate_store(
            business=self.business,
            store=self.store,
        )

        self.store.refresh_from_db()
        self.assertEqual(updated.pk, self.store.pk)
        self.assertFalse(self.store.is_active)

    def test_deactivate_store_raises_for_invalid_store(self):
        with self.assertRaises(ValidationError):
            deactivate_store(
                business=self.business,
                store=None,
            )

    def test_delete_store_success(self):
        store_name = delete_store(
            business=self.business,
            store=self.store,
        )

        self.assertEqual(store_name, "Tienda Centro")
        self.assertFalse(type(self.store).objects.filter(pk=self.store.pk).exists())

    def test_delete_default_store_assigns_replacement(self):
        self.store.is_default = True
        self.store.save(update_fields=["is_default", "updated_at"])

        replacement = create_store(
            business=self.business,
            name="Tienda Norte",
            code="NORTE",
            is_active=True,
        )

        delete_store(
            business=self.business,
            store=self.store,
        )

        replacement.refresh_from_db()
        self.assertTrue(replacement.is_default)

    def test_delete_store_raises_for_wrong_business(self):
        with self.assertRaises(ValidationError):
            delete_store(
                business=self.other_business,
                store=self.store,
            )
