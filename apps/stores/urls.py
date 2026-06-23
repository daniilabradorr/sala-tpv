from django.urls import path

from apps.stores.views import (
    ListStoresView,
    StoreDetailView,
    StoreCreateView,
    StoreUpdateView,
    StoreDeactivateView,
    StoreActivateView,
    StoreDeleteView,
)

app_name = "stores"

urlpatterns = [
    path("stores/", ListStoresView.as_view(), name="store_list"),
    path("stores/create/", StoreCreateView.as_view(), name="store_create"),
    path(
        "stores/<int:pk>/",
        StoreDetailView.as_view(),
        name="store_detail",
    ),
    path(
        "stores/<int:pk>/edit/",
        StoreUpdateView.as_view(),
        name="store_update",
    ),
    path(
        "stores/<int:pk>/deactivate/",
        StoreDeactivateView.as_view(),
        name="store_deactivate",
    ),
    path(
        "stores/<int:pk>/activate/",
        StoreActivateView.as_view(),
        name="store_activate",
    ),
    path(
        "stores/<int:pk>/delete/",
        StoreDeleteView.as_view(),
        name="store_delete",
    ),
]
