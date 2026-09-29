from django.urls import path

from apps.audit.views import ActivityDetailView, ActivityView

app_name = "audit"

urlpatterns = [
    path("", ActivityView.as_view(), name="activity"),
    path("<int:pk>/", ActivityDetailView.as_view(), name="activity_detail"),
]
