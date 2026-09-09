from django.contrib import admin
from django.urls import path, include

from apps.core.views import health_check

admin.site.site_header = "Netxodo Admin"
admin.site.site_title = "Netxodo"
admin.site.index_title = "Panel de administración"

urlpatterns = [
    path("", include("apps.core.urls")),
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),
    path("users/", include("apps.users.urls")),
    path("config/", include("apps.business_config.urls")),
    path("stores/", include("apps.stores.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("customers/", include("apps.customers.urls")),
    path("sales/", include("apps.sales.urls", namespace="sales")),
    path("payments/", include("apps.payments.urls", namespace="payments")),
    path("billing/", include("apps.billing.urls", namespace="billing")),
    path(
        "cash-register/", include("apps.cash_register.urls", namespace="cash_register")
    ),
]
