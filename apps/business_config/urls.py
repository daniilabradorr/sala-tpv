from django.urls import path

from apps.business_config.views import BusinessProfileUpdateView

app_name = "business_config"

urlpatterns = [
    path("profile/", BusinessProfileUpdateView.as_view(), name="profile"),
]
