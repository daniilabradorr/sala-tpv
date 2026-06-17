from django.test import SimpleTestCase
from django.urls import resolve, reverse

from apps.users.views import (
    UserLoginView,
    UserLogoutView,
    UserProfileDetailView,
    UserProfileUpdateView,
    UserPasswordChangeView,
    UserPinChangeView,
    UserListView,
    UserDetailView,
    UserCreateView,
    UserUpdateView,
    UserDeactivateView,
    UserActivateView,
    UserStoreAccessManageView,
)


class UserUrlsTests(SimpleTestCase):
    def test_login_url_resolves(self):
        """Verifica que la URL de login se resuelva correctamente a la vista UserLoginView."""
        url = reverse("users:login")

        self.assertEqual(url, "/users/login/")
        self.assertEqual(resolve(url).func.view_class, UserLoginView)

    def test_logout_url_resolves(self):
        """Verifica que la URL de logout se resuelva correctamente a la vista UserLogoutView."""
        url = reverse("users:logout")

        self.assertEqual(url, "/users/logout/")
        self.assertEqual(resolve(url).func.view_class, UserLogoutView)

    def test_profile_url_resolves(self):
        """Verifica que la URL de perfil se resuelva correctamente a la vista UserProfileDetailView."""
        url = reverse("users:profile")

        self.assertEqual(url, "/users/profile/")
        self.assertEqual(resolve(url).func.view_class, UserProfileDetailView)

    def test_profile_update_url_resolves(self):
        """Verifica que la URL de edición de perfil se resuelva correctamente a UserProfileUpdateView."""
        url = reverse("users:profile_update")

        self.assertEqual(url, "/users/profile/edit/")
        self.assertEqual(resolve(url).func.view_class, UserProfileUpdateView)

    def test_password_change_url_resolves(self):
        """Verifica que la URL de cambio de contraseña se resuelva correctamente a UserPasswordChangeView."""
        url = reverse("users:password_change")

        self.assertEqual(url, "/users/profile/password/")
        self.assertEqual(resolve(url).func.view_class, UserPasswordChangeView)

    def test_pin_change_url_resolves(self):
        """Verifica que la URL de cambio de PIN se resuelva correctamente a UserPinChangeView."""
        url = reverse("users:pin_change")

        self.assertEqual(url, "/users/profile/pin/")
        self.assertEqual(resolve(url).func.view_class, UserPinChangeView)

    def test_user_list_url_resolves(self):
        """Verifica que la URL de listado de usuarios se resuelva correctamente a UserListView."""
        url = reverse("users:user_list")

        self.assertEqual(url, "/users/")
        self.assertEqual(resolve(url).func.view_class, UserListView)

    def test_user_create_url_resolves(self):
        """Verifica que la URL de creación de usuario se resuelva correctamente a UserCreateView."""
        url = reverse("users:user_create")

        self.assertEqual(url, "/users/create/")
        self.assertEqual(resolve(url).func.view_class, UserCreateView)

    def test_user_detail_url_resolves(self):
        """Verifica que la URL de detalle de usuario se resuelva correctamente a UserDetailView."""
        url = reverse("users:user_detail", kwargs={"pk": 1})

        self.assertEqual(url, "/users/1/")
        self.assertEqual(resolve(url).func.view_class, UserDetailView)

    def test_user_update_url_resolves(self):
        """Verifica que la URL de edición de usuario se resuelva correctamente a UserUpdateView."""
        url = reverse("users:user_update", kwargs={"pk": 1})

        self.assertEqual(url, "/users/1/edit/")
        self.assertEqual(resolve(url).func.view_class, UserUpdateView)

    def test_user_deactivate_url_resolves(self):
        """Verifica que la URL de desactivación de usuario se resuelva correctamente a UserDeactivateView."""
        url = reverse("users:user_deactivate", kwargs={"pk": 1})

        self.assertEqual(url, "/users/1/deactivate/")
        self.assertEqual(resolve(url).func.view_class, UserDeactivateView)

    def test_user_activate_url_resolves(self):
        """Verifica que la URL de activación de usuario se resuelva correctamente a UserActivateView."""
        url = reverse("users:user_activate", kwargs={"pk": 1})

        self.assertEqual(url, "/users/1/activate/")
        self.assertEqual(resolve(url).func.view_class, UserActivateView)

    def test_user_store_access_manage_url_resolves(self):
        """Verifica que la URL de gestión de acceso a tiendas se resuelva correctamente a UserStoreAccessManageView."""
        url = reverse("users:user_store_access_manage", kwargs={"pk": 1})

        self.assertEqual(url, "/users/1/store-access/")
        self.assertEqual(resolve(url).func.view_class, UserStoreAccessManageView)
