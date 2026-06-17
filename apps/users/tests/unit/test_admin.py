from django.contrib import admin
from django.test import TestCase

from apps.users.admin import (
    CustomUserAdmin,
    UserStoreAccessAdmin,
    UserStoreAccessInline,
)
from apps.users.models import CustomUser, UserStoreAccess


class UsersAdminTests(TestCase):
    def test_custom_user_is_registered_in_admin(self):
        """Verifica que CustomUser esté registrado en el admin con CustomUserAdmin."""
        self.assertIn(CustomUser, admin.site._registry)
        self.assertIsInstance(
            admin.site._registry[CustomUser],
            CustomUserAdmin,
        )

    def test_user_store_access_is_registered_in_admin(self):
        """Verifica que UserStoreAccess esté registrado en el admin con UserStoreAccessAdmin."""
        self.assertIn(UserStoreAccess, admin.site._registry)
        self.assertIsInstance(
            admin.site._registry[UserStoreAccess],
            UserStoreAccessAdmin,
        )

    def test_custom_user_admin_list_display(self):
        """Verifica que la lista de campos visibles en admin de CustomUser sea correcta."""
        model_admin = admin.site._registry[CustomUser]

        self.assertEqual(
            model_admin.list_display,
            (
                "email",
                "first_name",
                "last_name",
                "business",
                "role",
                "is_active",
                "is_staff",
                "is_superuser",
                "date_joined",
            ),
        )

    def test_custom_user_admin_list_filter_contains_expected_fields(self):
        """Verifica que el admin de CustomUser tenga los filtros esperados (negocio, rol, estado, etc)."""
        model_admin = admin.site._registry[CustomUser]

        self.assertIn("business", model_admin.list_filter)
        self.assertIn("role", model_admin.list_filter)
        self.assertIn("is_active", model_admin.list_filter)
        self.assertIn("is_staff", model_admin.list_filter)
        self.assertIn("is_superuser", model_admin.list_filter)

    def test_custom_user_admin_search_fields(self):
        """Verifica que el admin de CustomUser permita búsquedas por email, nombre, teléfono, etc."""
        model_admin = admin.site._registry[CustomUser]

        self.assertEqual(
            model_admin.search_fields,
            (
                "email",
                "first_name",
                "last_name",
                "phone",
            ),
        )

    def test_custom_user_admin_readonly_fields(self):
        """Verifica que el admin tenga campos de solo lectura (código, fechas, último login, etc)."""
        model_admin = admin.site._registry[CustomUser]

        self.assertIn("employee_code", model_admin.readonly_fields)
        self.assertIn("date_joined", model_admin.readonly_fields)
        self.assertIn("created_at", model_admin.readonly_fields)
        self.assertIn("updated_at", model_admin.readonly_fields)
        self.assertIn("last_login", model_admin.readonly_fields)

    def test_custom_user_admin_has_user_store_access_inline(self):
        """Verifica que el admin de CustomUser tenga inline para gestionar accesos a tiendas."""
        model_admin = admin.site._registry[CustomUser]

        self.assertIn(UserStoreAccessInline, model_admin.inlines)

    def test_user_store_access_inline_configuration(self):
        """Verifica que el inline de acceso a tienda esté configurado correctamente."""
        self.assertEqual(UserStoreAccessInline.model, UserStoreAccess)
        self.assertEqual(UserStoreAccessInline.extra, 0)

        self.assertEqual(
            UserStoreAccessInline.fields,
            (
                "business",
                "store",
                "can_sell",
                "can_open_cash",
                "can_close_cash",
                "is_active",
            ),
        )

        self.assertEqual(
            UserStoreAccessInline.autocomplete_fields,
            ("business", "store"),
        )

    def test_user_store_access_admin_list_display(self):
        """Verifica que la lista de campos visibles en admin de UserStoreAccess sea correcta."""
        model_admin = admin.site._registry[UserStoreAccess]

        self.assertEqual(
            model_admin.list_display,
            (
                "user",
                "business",
                "store",
                "can_sell",
                "can_open_cash",
                "can_close_cash",
                "is_active",
            ),
        )

    def test_user_store_access_admin_list_filter_contains_expected_fields(self):
        """Verifica que el admin de UserStoreAccess tenga los filtros esperados (negocio, tienda, permisos, etc)."""
        model_admin = admin.site._registry[UserStoreAccess]

        self.assertIn("business", model_admin.list_filter)
        self.assertIn("store", model_admin.list_filter)
        self.assertIn("can_sell", model_admin.list_filter)
        self.assertIn("can_open_cash", model_admin.list_filter)
        self.assertIn("can_close_cash", model_admin.list_filter)
        self.assertIn("is_active", model_admin.list_filter)

    def test_user_store_access_admin_search_fields(self):
        """Verifica que el admin de UserStoreAccess permita búsquedas por usuario, tienda, etc."""
        model_admin = admin.site._registry[UserStoreAccess]

        self.assertEqual(
            model_admin.search_fields,
            (
                "user__email",
                "user__first_name",
                "user__last_name",
                "store__name",
                "store__code",
            ),
        )

    def test_user_store_access_admin_autocomplete_fields(self):
        """Verifica que el admin de UserStoreAccess tenga autocomplete para negocio, usuario y tienda."""
        model_admin = admin.site._registry[UserStoreAccess]

        self.assertEqual(
            model_admin.autocomplete_fields,
            (
                "business",
                "user",
                "store",
            ),
        )
