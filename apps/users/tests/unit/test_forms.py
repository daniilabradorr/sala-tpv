from django.test import TestCase

from apps.users.forms import (
    UserProfileUpdateForm,
    UserCreateForm,
    UserUpdateForm,
    UserPinChangeForm,
    UserStoreAccessForm,
    UserStoreAccessFormSet,
)
from apps.users.models import RoleChoices, UserStoreAccess
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_user,
)


class UserProfileUpdateFormTests(TestCase):
    def setUp(self):
        self.business = create_business()
        self.user = create_user(
            business=self.business,
            email="profile@test.com",
        )

    def test_profile_update_form_is_valid_with_correct_data(self):
        """Verifica que el formulario de actualización de perfil sea válido con datos correctos."""
        form = UserProfileUpdateForm(
            data={
                "first_name": "Daniel",
                "last_name": "Labrador",
                "phone": "600123123",
            },
            instance=self.user,
        )

        self.assertTrue(form.is_valid())

    def test_profile_update_form_rejects_invalid_phone(self):
        """Verifica que el formulario rechace un número de teléfono inválido."""
        form = UserProfileUpdateForm(
            data={
                "first_name": "Daniel",
                "last_name": "Labrador",
                "phone": "600ABC123",
            },
            instance=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)

    def test_profile_update_form_does_not_expose_sensitive_fields(self):
        """Verifica que el formulario no muestre campos sensibles como email, password, role, etc."""
        form = UserProfileUpdateForm(instance=self.user)

        self.assertNotIn("email", form.fields)
        self.assertNotIn("password", form.fields)
        self.assertNotIn("role", form.fields)
        self.assertNotIn("business", form.fields)
        self.assertNotIn("pin_hash", form.fields)


class UserCreateFormTests(TestCase):
    def setUp(self):
        self.business = create_business()

    def test_user_create_form_is_valid_with_correct_data(self):
        """Verifica que el formulario de creación de usuario sea válido con datos correctos."""
        form = UserCreateForm(
            data={
                "email": "newuser@test.com",
                "first_name": "Nuevo",
                "last_name": "Usuario",
                "phone": "600123123",
                "role": RoleChoices.CASHIER,
                "password": "testpass123",
                "password_confirm": "testpass123",
            },
            business=self.business,
        )

        self.assertTrue(form.is_valid())

    def test_user_create_form_assigns_business_to_instance(self):
        """Verifica que el formulario asigne automáticamente el negocio a la instancia de usuario."""
        form = UserCreateForm(
            data={
                "email": "newuser@test.com",
                "first_name": "Nuevo",
                "last_name": "Usuario",
                "phone": "600123123",
                "role": RoleChoices.CASHIER,
                "password": "testpass123",
                "password_confirm": "testpass123",
            },
            business=self.business,
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(form.instance.business, self.business)

    def test_user_create_form_rejects_different_passwords(self):
        """Verifica que el formulario rechace cuando las contraseñas no coinciden."""
        form = UserCreateForm(
            data={
                "email": "newuser@test.com",
                "first_name": "Nuevo",
                "last_name": "Usuario",
                "phone": "600123123",
                "role": RoleChoices.CASHIER,
                "password": "testpass123",
                "password_confirm": "different123",
            },
            business=self.business,
        )

        self.assertFalse(form.is_valid())

    def test_user_create_form_does_not_expose_sensitive_fields(self):
        """Verifica que el formulario no exponga campos sensibles como business, is_staff, permisos, etc."""
        form = UserCreateForm(business=self.business)

        self.assertNotIn("business", form.fields)
        self.assertNotIn("is_staff", form.fields)
        self.assertNotIn("is_superuser", form.fields)
        self.assertNotIn("groups", form.fields)
        self.assertNotIn("user_permissions", form.fields)
        self.assertNotIn("pin_hash", form.fields)


class UserUpdateFormTests(TestCase):
    def setUp(self):
        self.business = create_business()
        self.user = create_user(
            business=self.business,
            email="update@test.com",
        )

    def test_user_update_form_is_valid_with_correct_data(self):
        """Verifica que el formulario de actualización de usuario sea válido con datos correctos."""
        form = UserUpdateForm(
            data={
                "first_name": "Usuario",
                "last_name": "Editado",
                "phone": "600123123",
                "role": RoleChoices.MANAGER,
                "is_active": True,
            },
            instance=self.user,
        )

        self.assertTrue(form.is_valid())

    def test_user_update_form_rejects_invalid_phone(self):
        """Verifica que el formulario de actualización rechace un número de teléfono inválido."""
        form = UserUpdateForm(
            data={
                "first_name": "Usuario",
                "last_name": "Editado",
                "phone": "600ABC123",
                "role": RoleChoices.MANAGER,
                "is_active": True,
            },
            instance=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)

    def test_user_update_form_does_not_expose_dangerous_fields(self):
        """Verifica que el formulario no exponga campos peligrosos como email, password, business, etc."""
        form = UserUpdateForm(instance=self.user)

        self.assertNotIn("business", form.fields)
        self.assertNotIn("email", form.fields)
        self.assertNotIn("password", form.fields)
        self.assertNotIn("pin_hash", form.fields)
        self.assertNotIn("is_staff", form.fields)
        self.assertNotIn("is_superuser", form.fields)


class UserPinChangeFormTests(TestCase):
    def test_pin_change_form_is_valid_with_correct_pin(self):
        """Verifica que el formulario de cambio de PIN sea válido con un PIN válido."""
        form = UserPinChangeForm(
            data={
                "new_pin": "1234",
                "new_pin_confirm": "1234",
            }
        )

        self.assertTrue(form.is_valid())

    def test_pin_change_form_rejects_pin_with_letters(self):
        """Verifica que el formulario rechace un PIN que contenga letras."""
        form = UserPinChangeForm(
            data={
                "new_pin": "12AB",
                "new_pin_confirm": "12AB",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("new_pin", form.errors)

    def test_pin_change_form_rejects_different_confirmation(self):
        """Verifica que el formulario rechace cuando el PIN y su confirmación no coinciden."""
        form = UserPinChangeForm(
            data={
                "new_pin": "1234",
                "new_pin_confirm": "9999",
            }
        )

        self.assertFalse(form.is_valid())

    def test_pin_change_form_rejects_short_pin(self):
        """Verifica que el formulario rechace un PIN demasiado corto (menos de 4 dígitos)."""
        form = UserPinChangeForm(
            data={
                "new_pin": "123",
                "new_pin_confirm": "123",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("new_pin", form.errors)

    def test_pin_change_form_rejects_long_pin(self):
        """Verifica que el formulario rechace un PIN demasiado largo (más de 6 dígitos)."""
        form = UserPinChangeForm(
            data={
                "new_pin": "1234567",
                "new_pin_confirm": "1234567",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("new_pin", form.errors)


class UserStoreAccessFormTests(TestCase):
    def setUp(self):
        self.business = create_business()
        self.store = create_store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )
        self.user = create_user(
            business=self.business,
            email="cashier@test.com",
        )

    def test_user_store_access_form_has_expected_fields(self):
        """Verifica que el formulario de acceso a tienda contenga los campos esperados."""
        form = UserStoreAccessForm()

        self.assertIn("store", form.fields)
        self.assertIn("can_sell", form.fields)
        self.assertIn("can_open_cash", form.fields)
        self.assertIn("can_close_cash", form.fields)
        self.assertIn("is_active", form.fields)

    def test_user_store_access_form_does_not_expose_business_or_user(self):
        """Verifica que el formulario no exponga los campos business y user."""
        form = UserStoreAccessForm()

        self.assertNotIn("business", form.fields)
        self.assertNotIn("user", form.fields)

    def test_user_store_access_formset_is_valid_with_correct_data(self):
        """Verifica que el formset de acceso a tiendas sea válido con datos correctos."""
        formset = UserStoreAccessFormSet(
            data={
                "store_accesses-TOTAL_FORMS": "1",
                "store_accesses-INITIAL_FORMS": "0",
                "store_accesses-MIN_NUM_FORMS": "0",
                "store_accesses-MAX_NUM_FORMS": "1000",
                "store_accesses-0-store": str(self.store.pk),
                "store_accesses-0-can_sell": "on",
                "store_accesses-0-can_open_cash": "on",
                "store_accesses-0-is_active": "on",
            },
            queryset=UserStoreAccess.objects.none(),
            prefix="store_accesses",
        )

        self.assertTrue(formset.is_valid())
