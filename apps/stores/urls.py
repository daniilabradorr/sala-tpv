from django.urls import path

from apps.stores.views import (
    ListStoresView,
    StoreDetailView,
    StoreCreateView,
    StoreUpdateView,
    StoreDeactivateView,
    StoreActivateView,
    StoreDeleteView,
    StoreSetDefaultView,
)

app_name = "stores"

urlpatterns = [
    path("", ListStoresView.as_view(), name="store_list"),
    path("create/", StoreCreateView.as_view(), name="store_create"),
    path(
        "<int:pk>/",
        StoreDetailView.as_view(),
        name="store_detail",
    ),
    path(
        "<int:pk>/edit/",
        StoreUpdateView.as_view(),
        name="store_update",
    ),
    path(
        "<int:pk>/deactivate/",
        StoreDeactivateView.as_view(),
        name="store_deactivate",
    ),
    path(
        "<int:pk>/activate/",
        StoreActivateView.as_view(),
        name="store_activate",
    ),
    path(
        "<int:pk>/delete/",
        StoreDeleteView.as_view(),
        name="store_delete",
    ),
    path(
        "<int:pk>/set-default/",
        StoreSetDefaultView.as_view(),
        name="store_set_default",
    ),
]
