from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from apps.users.helpers import (
    is_authenticated_user,
    is_owner,
    is_manager,
    is_cashier,
    is_owner_or_manager,
    belongs_to_business,
    can_access_store,
    can_sell_in_store,
    can_open_cash_register,
    can_close_cash_register,
    can_manage_users,
    can_manage_business_settings,
    can_view_reports,
    can_perform_sensitive_action,
)
from apps.users.models import CustomUser, RoleChoices
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_user,
    create_store_access,
)


class UserHelpersTests(TestCase):
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
        )

        self.other_store = create_store(
            business=self.other_business,
            name="Otra Tienda",
            code="OTRA",
        )

        self.owner = create_user(
            business=self.business,
            email="owner@test.com",
            role=RoleChoices.OWNER,
        )

        self.manager = create_user(
            business=self.business,
            email="manager@test.com",
            role=RoleChoices.MANAGER,
        )

        self.cashier = create_user(
            business=self.business,
            email="cashier@test.com",
            role=RoleChoices.CASHIER,
        )

        self.inactive_user = create_user(
            business=self.business,
            email="inactive@test.com",
            role=RoleChoices.OWNER,
            is_active=False,
        )

        self.superuser = CustomUser.objects.create_superuser(
            email="admin@test.com",
            password="adminpass123",
            role=RoleChoices.OWNER,
            first_name="Admin",
            last_name="User",
            phone="600123123",
        )

    # ============================================================
    # AUTENTICACIÓN BASE
    # ============================================================

    def test_is_authenticated_user_returns_false_for_none(self):
        """Verifica que is_authenticated_user devuelva False para None."""
        self.assertFalse(is_authenticated_user(None))

    def test_is_authenticated_user_returns_false_for_anonymous_user(self):
        """Verifica que is_authenticated_user devuelva False para usuarios anónimos."""
        self.assertFalse(is_authenticated_user(AnonymousUser()))

    def test_is_authenticated_user_returns_false_for_inactive_user(self):
        """Verifica que is_authenticated_user devuelva False para usuarios inactivos."""
        self.assertFalse(is_authenticated_user(self.inactive_user))

    def test_is_authenticated_user_returns_true_for_active_user(self):
        """Verifica que is_authenticated_user devuelva True para usuarios activos."""
        self.assertTrue(is_authenticated_user(self.owner))

    # ============================================================
    # ROLES
    # ============================================================

    def test_role_helpers_detect_owner_manager_and_cashier(self):
        """Verifica que los helpers de rol identifiquen correctamente propietarios, gerentes y cajeros."""
        self.assertTrue(is_owner(self.owner))
        self.assertFalse(is_owner(self.manager))
        self.assertFalse(is_owner(self.cashier))

        self.assertTrue(is_manager(self.manager))
        self.assertFalse(is_manager(self.owner))
        self.assertFalse(is_manager(self.cashier))

        self.assertTrue(is_cashier(self.cashier))
        self.assertFalse(is_cashier(self.owner))
        self.assertFalse(is_cashier(self.manager))

    def test_is_owner_or_manager_returns_true_only_for_owner_or_manager(self):
        """Verifica que is_owner_or_manager devuelva True solo para propietarios y gerentes."""
        self.assertTrue(is_owner_or_manager(self.owner))
        self.assertTrue(is_owner_or_manager(self.manager))
        self.assertFalse(is_owner_or_manager(self.cashier))

    # ============================================================
    # BUSINESS
    # ============================================================

    def test_belongs_to_business_returns_true_for_same_business(self):
        """Verifica que belongs_to_business devuelva True para usuarios del mismo negocio."""
        self.assertTrue(belongs_to_business(self.owner, self.business))

    def test_belongs_to_business_returns_false_for_other_business(self):
        """Verifica que belongs_to_business devuelva False para usuarios de otro negocio."""
        self.assertFalse(belongs_to_business(self.owner, self.other_business))

    def test_belongs_to_business_returns_true_for_superuser(self):
        """Verifica que belongs_to_business devuelva True para superusuarios (independiente del negocio)."""
        self.assertTrue(belongs_to_business(self.superuser, self.other_business))

    def test_belongs_to_business_returns_false_for_inactive_user(self):
        """Verifica que belongs_to_business devuelva False para usuarios inactivos."""
        self.assertFalse(belongs_to_business(self.inactive_user, self.business))

    # ============================================================
    # ACCESO A TIENDA
    # ============================================================

    def test_owner_can_access_any_store_of_own_business(self):
        """Verifica que los propietarios puedan acceder a cualquier tienda de su negocio."""
        self.assertTrue(can_access_store(self.owner, self.store))

    def test_owner_cannot_access_store_from_other_business(self):
        """Verifica que los propietarios no puedan acceder a tiendas de otro negocio."""
        self.assertFalse(can_access_store(self.owner, self.other_store))

    def test_superuser_can_access_any_store(self):
        """Verifica que los superusuarios puedan acceder a cualquier tienda."""
        self.assertTrue(can_access_store(self.superuser, self.other_store))

    def test_manager_without_store_access_cannot_access_store(self):
        """Verifica que gerentes sin acceso explícito no puedan acceder a tiendas."""
        self.assertFalse(can_access_store(self.manager, self.store))

    def test_manager_with_active_store_access_can_access_store(self):
        """Verifica que gerentes con acceso activo a tienda puedan acceder."""
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.store,
            is_active=True,
        )

        self.assertTrue(can_access_store(self.manager, self.store))

    def test_manager_with_inactive_store_access_cannot_access_store(self):
        """Verifica que gerentes con acceso inactivo a tienda no puedan acceder."""
        create_store_access(
            business=self.business,
            user=self.manager,
            store=self.store,
            is_active=False,
        )

        self.assertFalse(can_access_store(self.manager, self.store))

    # ============================================================
    # PERMISOS DE TIENDA: VENDER / ABRIR CAJA / CERRAR CAJA
    # ============================================================

    def test_can_sell_in_store_depends_on_user_store_access(self):
        """Verifica que el permiso de venta en tienda dependa de la configuración de acceso."""
        create_store_access(
            business=self.business,
            user=self.cashier,
            store=self.store,
            can_sell=True,
            can_open_cash=False,
            can_close_cash=False,
            is_active=True,
        )

        self.assertTrue(can_sell_in_store(self.cashier, self.store))
        self.assertFalse(can_open_cash_register(self.cashier, self.store))
        self.assertFalse(can_close_cash_register(self.cashier, self.store))

    def test_can_open_cash_register_depends_on_user_store_access(self):
        """Verifica que el permiso de abrir caja dependa de la configuración de acceso."""
        create_store_access(
            business=self.business,
            user=self.cashier,
            store=self.store,
            can_sell=False,
            can_open_cash=True,
            can_close_cash=False,
            is_active=True,
        )

        self.assertFalse(can_sell_in_store(self.cashier, self.store))
        self.assertTrue(can_open_cash_register(self.cashier, self.store))
        self.assertFalse(can_close_cash_register(self.cashier, self.store))

    def test_can_close_cash_register_depends_on_user_store_access(self):
        """Verifica que el permiso de cerrar caja dependa de la configuración de acceso."""
        create_store_access(
            business=self.business,
            user=self.cashier,
            store=self.store,
            can_sell=False,
            can_open_cash=False,
            can_close_cash=True,
            is_active=True,
        )

        self.assertFalse(can_sell_in_store(self.cashier, self.store))
        self.assertFalse(can_open_cash_register(self.cashier, self.store))
        self.assertTrue(can_close_cash_register(self.cashier, self.store))

    def test_owner_can_sell_open_and_close_cash_in_own_store(self):
        """Verifica que propietarios puedan vender, abrir y cerrar caja en sus tiendas."""
        self.assertTrue(can_sell_in_store(self.owner, self.store))
        self.assertTrue(can_open_cash_register(self.owner, self.store))
        self.assertTrue(can_close_cash_register(self.owner, self.store))

    def test_owner_cannot_sell_open_or_close_cash_in_other_business_store(self):
        """Verifica que propietarios no puedan vender, abrir o cerrar caja en tiendas de otro negocio."""
        self.assertFalse(can_sell_in_store(self.owner, self.other_store))
        self.assertFalse(can_open_cash_register(self.owner, self.other_store))
        self.assertFalse(can_close_cash_register(self.owner, self.other_store))

    def test_superuser_can_sell_open_and_close_cash_in_any_store(self):
        """Verifica que superusuarios puedan vender, abrir y cerrar caja en cualquier tienda."""
        self.assertTrue(can_sell_in_store(self.superuser, self.other_store))
        self.assertTrue(can_open_cash_register(self.superuser, self.other_store))
        self.assertTrue(can_close_cash_register(self.superuser, self.other_store))

    # ============================================================
    # PERMISOS GLOBALES
    # ============================================================

    def test_can_manage_users_allows_owner_manager_and_superuser(self):
        """Verifica que solo propietarios, gerentes y superusuarios puedan gestionar usuarios."""
        self.assertTrue(can_manage_users(self.owner))
        self.assertTrue(can_manage_users(self.manager))
        self.assertTrue(can_manage_users(self.superuser))
        self.assertFalse(can_manage_users(self.cashier))
        self.assertFalse(can_manage_users(self.inactive_user))

    def test_can_manage_business_settings_allows_only_owner_and_superuser(self):
        """Verifica que solo propietarios y superusuarios puedan gestionar configuración del negocio."""
        self.assertTrue(can_manage_business_settings(self.owner))
        self.assertTrue(can_manage_business_settings(self.superuser))
        self.assertFalse(can_manage_business_settings(self.manager))
        self.assertFalse(can_manage_business_settings(self.cashier))
        self.assertFalse(can_manage_business_settings(self.inactive_user))

    def test_can_view_reports_allows_owner_manager_and_superuser(self):
        """Verifica que solo propietarios, gerentes y superusuarios puedan ver reportes."""
        self.assertTrue(can_view_reports(self.owner))
        self.assertTrue(can_view_reports(self.manager))
        self.assertTrue(can_view_reports(self.superuser))
        self.assertFalse(can_view_reports(self.cashier))
        self.assertFalse(can_view_reports(self.inactive_user))

    def test_can_perform_sensitive_action_allows_owner_manager_and_superuser(self):
        """Verifica que solo propietarios, gerentes y superusuarios puedan realizar acciones sensibles."""
        self.assertTrue(can_perform_sensitive_action(self.owner))
        self.assertTrue(can_perform_sensitive_action(self.manager))
        self.assertTrue(can_perform_sensitive_action(self.superuser))
        self.assertFalse(can_perform_sensitive_action(self.cashier))
        self.assertFalse(can_perform_sensitive_action(self.inactive_user))
