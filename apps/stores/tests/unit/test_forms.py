from django.test import TestCase

from apps.stores.forms import StoreCreateForm, StoreUpdateForm
from apps.users.tests.factories import create_business, create_store


class StoreCreateFormTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio Test",
            slug="negocio-test",
        )

    def valid_data(self, **overrides):
        data = {
            "name": "Tienda Centro",
            "address_line_1": "Calle Mayor 1",
            "address_line_2": "",
            "postal_code": "37001",
            "city": "Salamanca",
            "province": "Salamanca",
            "country_code": "ES",
            "phone_store": "600123123",
            "email_store": "centro@test.com",
        }
        data.update(overrides)
        return data

    def test_store_create_form_is_valid_with_correct_data(self):
        """
        Verifica que el formulario de creación sea válido
        cuando recibe datos correctos y el business desde la vista.
        """
        form = StoreCreateForm(
            data=self.valid_data(),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_store_create_form_assigns_business_to_instance(self):
        """
        Verifica que el formulario asigne el negocio a la instancia
        antes de validar/guardar.
        """
        form = StoreCreateForm(
            data=self.valid_data(),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())
        store = form.save()

        self.assertEqual(store.business, self.business)

    def test_store_create_form_generates_code_automatically(self):
        """
        Verifica que el código de tienda se genere automáticamente
        desde el modelo cuando no viene en el formulario.
        """
        form = StoreCreateForm(
            data=self.valid_data(),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())
        store = form.save()

        self.assertTrue(store.code)
        self.assertNotEqual(store.code, "")

    def test_store_create_form_does_not_expose_dangerous_fields(self):
        """
        Verifica que el formulario no exponga campos que deben venir
        de la lógica interna, no del usuario.
        """
        form = StoreCreateForm(business=self.business)

        self.assertNotIn("business", form.fields)
        self.assertNotIn("code", form.fields)
        self.assertNotIn("is_active", form.fields)

    def test_store_create_form_rejects_invalid_postal_code(self):
        """
        Verifica que el formulario rechace códigos postales españoles inválidos.
        """
        form = StoreCreateForm(
            data=self.valid_data(postal_code="3700A"),
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("postal_code", form.errors)

    def test_store_create_form_rejects_invalid_email(self):
        """
        Verifica que el formulario rechace un email de tienda inválido.
        """
        form = StoreCreateForm(
            data=self.valid_data(email_store="correo-invalido"),
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email_store", form.errors)


class StoreUpdateFormTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio Test",
            slug="negocio-test",
        )
        self.store = create_store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )

    def valid_data(self, **overrides):
        data = {
            "name": "Tienda Centro Editada",
            "code": "CENTRO-EDITADA",
            "address_line_1": "Calle Nueva 10",
            "address_line_2": "",
            "postal_code": "37002",
            "city": "Salamanca",
            "province": "Salamanca",
            "country_code": "ES",
            "phone_store": "600999888",
            "email_store": "centroeditada@test.com",
        }
        data.update(overrides)
        return data

    def test_store_update_form_is_valid_with_correct_data(self):
        """
        Verifica que el formulario de edición sea válido con datos correctos.
        """
        form = StoreUpdateForm(
            data=self.valid_data(),
            instance=self.store,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_store_update_form_exposes_code_but_not_business(self):
        """
        En edición sí permitimos cambiar code,
        pero nunca business.
        """
        form = StoreUpdateForm(instance=self.store)

        self.assertIn("code", form.fields)
        self.assertNotIn("business", form.fields)
        self.assertNotIn("is_active", form.fields)

    def test_store_update_form_normalizes_code_country_and_email(self):
        """
        Verifica que el modelo normalice code, country_code y email_store
        al validar el formulario.
        """
        form = StoreUpdateForm(
            data=self.valid_data(
                code=" centro_2 ",
                country_code="es",
                email_store="CENTRO@TEST.COM",
            ),
            instance=self.store,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())
        store = form.save()

        self.assertEqual(store.code, "CENTRO_2")
        self.assertEqual(store.country_code, "ES")
        self.assertEqual(store.email_store, "centro@test.com")

    def test_store_update_form_rejects_invalid_code(self):
        """
        Verifica que el código no acepte espacios ni caracteres inválidos.
        """
        form = StoreUpdateForm(
            data=self.valid_data(code="CODIGO INVALIDO"),
            instance=self.store,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)

    def test_store_update_form_rejects_invalid_phone(self):
        """
        Verifica que el teléfono solo acepte números y caracteres permitidos.
        """
        form = StoreUpdateForm(
            data=self.valid_data(phone_store="ABC123"),
            instance=self.store,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("phone_store", form.errors)
