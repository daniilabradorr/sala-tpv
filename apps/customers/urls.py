"""URLs del módulo customers."""

from django.urls import path

from apps.customers.views import (
    CustomerCreateView,
    CustomerDeactivateView,
    CustomerDetailView,
    CustomerListView,
    CustomerUpdateView,
)


app_name = "customers"


urlpatterns = [
    path(
        "",
        CustomerListView.as_view(),
        name="customer_list",
    ),
    path(
        "create/",
        CustomerCreateView.as_view(),
        name="customer_create",
    ),
    path(
        "<int:pk>/",
        CustomerDetailView.as_view(),
        name="customer_detail",
    ),
    path(
        "<int:pk>/edit/",
        CustomerUpdateView.as_view(),
        name="customer_update",
    ),
    path(
        "<int:pk>/deactivate/",
        CustomerDeactivateView.as_view(),
        name="customer_deactivate",
    ),
]
