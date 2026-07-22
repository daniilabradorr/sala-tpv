from django.urls import path

from apps.customers import views

app_name = "customers"

urlpatterns = [
    path("", views.CustomerListView.as_view(), name="customer_list"),
    path("create/", views.CustomerCreateView.as_view(), name="customer_create"),
    path("<int:pk>/", views.CustomerDetailView.as_view(), name="customer_detail"),
    path("<int:pk>/edit/", views.CustomerUpdateView.as_view(), name="customer_update"),
    path(
        "<int:pk>/deactivate/",
        views.CustomerDeactivateView.as_view(),
        name="customer_deactivate",
    ),
    path(
        "<int:pk>/reactivate/",
        views.CustomerReactivateView.as_view(),
        name="customer_reactivate",
    ),
    path(
        "<int:pk>/account/settings/",
        views.CustomerAccountSettingsView.as_view(),
        name="customer_account_settings",
    ),
]
