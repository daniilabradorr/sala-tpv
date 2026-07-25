from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.core.models import Business
from apps.stores.models import Store


class StoreModelTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Negocio Test",
            slug="negocio-test",
        )

    def test_store_str_returns_name_and_code(self):
        store = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )

        self.assertEqual(str(store), "Tienda Centro (CENTRO)")

    def test_store_str_returns_only_name_when_code_is_empty_before_validation(self):
        store = Store(
            business=self.business,
            name="Tienda Centro",
            code="",
        )

        self.assertEqual(str(store), "Tienda Centro")

    def test_store_generates_code_automatically_when_missing(self):
        store = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
        )

        self.assertTrue(store.code)
        self.assertEqual(store.code, "NEGOCIOTE-TIENDACEN")

    def test_store_generates_unique_suffix_when_base_code_collides(self):
        first = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
        )
        second = Store.objects.create(
            business=self.business,
            name="Tienda-Centro",
        )

        self.assertNotEqual(first.code, second.code)
        self.assertTrue(second.code.endswith("-2"))

    def test_generated_code_never_exceeds_max_length(self):
        store = Store.objects.create(
            business=self.business,
            name="Tienda Centro Muy Larga Con Nombre Extendido",
        )

        self.assertLessEqual(len(store.code), 20)

    def test_first_active_store_becomes_default(self):
        store = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
        )

        self.assertTrue(store.is_default)

    def test_second_active_store_does_not_replace_existing_default(self):
        first = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
        )
        second = Store.objects.create(
            business=self.business,
            name="Tienda Norte",
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertTrue(first.is_default)
        self.assertFalse(second.is_default)

    def test_each_business_can_have_its_own_default_store(self):
        other_business = Business.objects.create(
            name="Otro Negocio",
            slug="otro-negocio",
        )

        first = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
        )
        second = Store.objects.create(
            business=other_business,
            name="Tienda Centro",
        )

        self.assertTrue(first.is_default)
        self.assertTrue(second.is_default)

    def test_same_business_cannot_have_two_default_stores(self):
        first = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )

        second = Store(
            business=self.business,
            name="Tienda Norte",
            code="NORTE",
            is_default=True,
        )

        with self.assertRaises(ValidationError) as context:
            second.full_clean()

        non_field_errors = context.exception.error_dict.get("__all__", [])
        self.assertTrue(
            any(
                "unique_default_store_per_business" in str(error)
                for error in non_field_errors
            )
        )

        first.refresh_from_db()
        self.assertTrue(first.is_default)

    def test_database_rejects_two_default_stores_for_same_business(self):
        first = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )

        second = Store.objects.create(
            business=self.business,
            name="Tienda Norte",
            code="NORTE",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Store.objects.filter(pk=second.pk).update(is_default=True)

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertTrue(first.is_default)
        self.assertFalse(second.is_default)

    def test_inactive_store_cannot_be_default(self):
        store = Store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
            is_active=False,
            is_default=True,
        )

        with self.assertRaises(ValidationError) as context:
            store.full_clean()

        self.assertIn("is_default", context.exception.message_dict)

    def test_store_normalizes_text_fields(self):
        store = Store(
            business=self.business,
            name="  Tienda Centro  ",
            code=" centro_1 ",
            address_line_1="  Calle Mayor 1  ",
            postal_code=" 37001 ",
            city=" Salamanca ",
            province=" Salamanca ",
            country_code="es",
            phone_store=" 600123123 ",
            email_store="CENTRO@TEST.COM",
        )

        store.full_clean()

        self.assertEqual(store.name, "Tienda Centro")
        self.assertEqual(store.code, "CENTRO_1")
        self.assertEqual(store.address_line_1, "Calle Mayor 1")
        self.assertEqual(store.postal_code, "37001")
        self.assertEqual(store.city, "Salamanca")
        self.assertEqual(store.province, "Salamanca")
        self.assertEqual(store.country_code, "ES")
        self.assertEqual(store.phone_store, "600123123")
        self.assertEqual(store.email_store, "centro@test.com")

    def test_store_normalizes_manual_code(self):
        store = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code=" centro_1 ",
        )

        self.assertEqual(store.code, "CENTRO_1")

    def test_store_requires_business(self):
        store = Store(
            name="Tienda Centro",
            code="CENTRO",
        )

        with self.assertRaises(ValidationError) as context:
            store.full_clean()

        self.assertIn("business", context.exception.message_dict)

    def test_store_requires_name(self):
        store = Store(
            business=self.business,
            name="",
            code="CENTRO",
        )

        with self.assertRaises(ValidationError) as context:
            store.full_clean()

        self.assertIn("name", context.exception.message_dict)

    def test_store_rejects_invalid_code(self):
        store = Store(
            business=self.business,
            name="Tienda Centro",
            code="CODIGO INVALIDO",
        )

        with self.assertRaises(ValidationError) as context:
            store.full_clean()

        self.assertIn("code", context.exception.message_dict)

    def test_store_rejects_invalid_country_code(self):
        store = Store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
            country_code="ESP",
        )

        with self.assertRaises(ValidationError) as context:
            store.full_clean()

        self.assertIn("country_code", context.exception.message_dict)

    def test_store_rejects_invalid_spanish_postal_code(self):
        store = Store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
            country_code="ES",
            postal_code="3700A",
        )

        with self.assertRaises(ValidationError) as context:
            store.full_clean()

        self.assertIn("postal_code", context.exception.message_dict)

    def test_store_rejects_invalid_phone(self):
        store = Store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
            phone_store="ABC123",
        )

        with self.assertRaises(ValidationError) as context:
            store.full_clean()

        self.assertIn("phone_store", context.exception.message_dict)

    def test_store_code_must_be_unique_per_business(self):
        Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )

        duplicate = Store(
            business=self.business,
            name="Tienda Norte",
            code="CENTRO",
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_same_store_code_is_allowed_in_different_business(self):
        other_business = Business.objects.create(
            name="Otro Negocio",
            slug="otro-negocio",
        )

        Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )

        store = Store(
            business=other_business,
            name="Tienda Centro",
            code="CENTRO",
        )

        store.full_clean()

        self.assertEqual(store.code, "CENTRO")

    def test_database_rejects_empty_code_with_constraint(self):
        store = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Store.objects.filter(pk=store.pk).update(code="")

    def test_contact_phone_prefers_store_phone(self):
        store = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
            phone_store="600111222",
        )

        self.assertEqual(store.contact_phone, "600111222")

    def test_contact_email_prefers_store_email(self):
        store = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
            email_store="centro@test.com",
        )

        self.assertEqual(store.contact_email, "centro@test.com")
