from django.core.exceptions import ValidationError
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

    def test_store_generates_code_automatically_when_empty(self):
        store = Store.objects.create(
            business=self.business,
            name="Tienda Centro",
            code="",
        )

        self.assertTrue(store.code)
        self.assertNotEqual(store.code, "")

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
