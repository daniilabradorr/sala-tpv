from django.urls import path

from apps.business_config.views import BusinessProfileUpdateView, POSSettingsUpdateView

app_name = "business_config"

urlpatterns = [
    path("profile/", BusinessProfileUpdateView.as_view(), name="profile"),
    path("pos/", POSSettingsUpdateView.as_view(), name="pos"),
]
