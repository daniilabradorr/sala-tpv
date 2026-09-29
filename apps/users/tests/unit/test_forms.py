from django.test import TestCase

from apps.users.forms import (
    UserProfileUpdateForm,
    UserCreateForm,
    UserUpdateForm,
    UserPinChangeForm,
    StoreAccessMatrixForm,
    UserFilterForm,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_store_access
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
        self.assertNotIn("is_active", form.fields)
        self.assertNotIn("employee_code", form.fields)


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


class UserAdministrationFormTests(TestCase):
    def setUp(self):
        self.business = create_business(name="Forms A", slug="forms-a")
        self.other_business = create_business(name="Forms B", slug="forms-b")
        self.store = create_store(business=self.business, name="Centro", code="CENTRO")
        self.inactive_store = create_store(
            business=self.business, name="Cerrada", code="CERRADA", is_active=False
        )
        self.foreign_store = create_store(
            business=self.other_business, name="Ajena", code="AJENA"
        )
        self.user = create_user(business=self.business, role=RoleChoices.CASHIER)

    def test_filter_choices_and_safe_store(self):
        form = UserFilterForm(
            {"role": "manager", "status": "inactive", "store": str(self.store.pk)},
            stores=[self.store],
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["store"], self.store)

    def test_filter_rejects_cross_business_store(self):
        form = UserFilterForm(
            {"status": "all", "store": str(self.foreign_store.pk)}, stores=[self.store]
        )
        self.assertFalse(form.is_valid())
        self.assertIn("store", form.errors)

    def test_matrix_has_server_defined_row_per_store_without_scope_fields(self):
        form = StoreAccessMatrixForm(stores=[self.store, self.inactive_store])
        self.assertEqual(len(form.matrix_rows), 2)
        self.assertNotIn("business", form.fields)
        self.assertNotIn("user", form.fields)
        self.assertNotIn(f"store_{self.foreign_store.pk}_active", form.fields)

    def test_matrix_uses_access_initial_values_and_keeps_inactive_store(self):
        access = create_store_access(
            business=self.business,
            user=self.user,
            store=self.store,
            is_active=True,
            can_sell=False,
            can_open_cash=True,
            can_close_cash=True,
        )
        form = StoreAccessMatrixForm(
            stores=[self.store, self.inactive_store], accesses=[access]
        )
        self.assertTrue(form.fields[f"store_{self.store.pk}_active"].initial)
        self.assertFalse(form.fields[f"store_{self.store.pk}_sell"].initial)
        self.assertTrue(form.fields[f"store_{self.store.pk}_open"].initial)
        self.assertTrue(form.fields[f"store_{self.store.pk}_close"].initial)
        self.assertEqual(form.matrix_rows[1]["store"], self.inactive_store)

    def test_matrix_normalizes_operational_permissions(self):
        data = {
            f"store_{self.store.pk}_active": "on",
            f"store_{self.store.pk}_sell": "on",
            f"store_{self.store.pk}_open": "on",
            f"store_{self.store.pk}_close": "on",
        }
        form = StoreAccessMatrixForm(data, stores=[self.store])
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.normalized_accesses()[self.store.pk],
            {
                "is_active": True,
                "can_sell": True,
                "can_open_cash": True,
                "can_close_cash": True,
            },
        )

    def test_matrix_rejects_arbitrary_store_key(self):
        form = StoreAccessMatrixForm(
            {f"store_{self.foreign_store.pk}_active": "on"}, stores=[self.store]
        )
        self.assertFalse(form.is_valid())
        self.assertIn("tienda no autorizada", str(form.non_field_errors()))

    def test_update_exposes_only_safe_fields(self):
        form = UserUpdateForm(instance=self.user)
        self.assertEqual(set(form.fields), {"first_name", "last_name", "phone", "role"})

    def test_manager_role_choices_exclude_owner(self):
        manager = create_user(
            business=self.business,
            email="manager-forms@test.com",
            role=RoleChoices.MANAGER,
        )
        form = UserUpdateForm(instance=self.user, actor=manager)
        self.assertNotIn(RoleChoices.OWNER, dict(form.fields["role"].choices))
