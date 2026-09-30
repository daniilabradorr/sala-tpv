from django.urls import path

from apps.business_config.views import (
    BusinessProfileUpdateView,
    PaymentMethodUpdateView,
    POSSettingsUpdateView,
)

app_name = "business_config"

urlpatterns = [
    path("profile/", BusinessProfileUpdateView.as_view(), name="profile"),
    path("pos/", POSSettingsUpdateView.as_view(), name="pos"),
    path(
        "payments/<int:pk>/", PaymentMethodUpdateView.as_view(), name="payment_method"
    ),
]
