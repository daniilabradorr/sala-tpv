from django.urls import path

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


app_name = "users"


urlpatterns = [
    # Autenticación
    path(
        "login/",
        UserLoginView.as_view(),
        name="login",
    ),
    path(
        "logout/",
        UserLogoutView.as_view(),
        name="logout",
    ),
    # Perfil del usuario logueado
    path(
        "profile/",
        UserProfileDetailView.as_view(),
        name="profile",
    ),
    path(
        "profile/edit/",
        UserProfileUpdateView.as_view(),
        name="profile_update",
    ),
    path(
        "profile/password/",
        UserPasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "profile/pin/",
        UserPinChangeView.as_view(),
        name="pin_change",
    ),
    # Gestión de usuarios del negocio
    path(
        "",
        UserListView.as_view(),
        name="user_list",
    ),
    path(
        "create/",
        UserCreateView.as_view(),
        name="user_create",
    ),
    path(
        "<int:pk>/",
        UserDetailView.as_view(),
        name="user_detail",
    ),
    path(
        "<int:pk>/edit/",
        UserUpdateView.as_view(),
        name="user_update",
    ),
    path(
        "<int:pk>/deactivate/",
        UserDeactivateView.as_view(),
        name="user_deactivate",
    ),
    path(
        "<int:pk>/activate/",
        UserActivateView.as_view(),
        name="user_activate",
    ),
    # Accesos del usuario a tiendas
    path(
        "<int:pk>/store-access/",
        UserStoreAccessManageView.as_view(),
        name="user_store_access_manage",
    ),
]
