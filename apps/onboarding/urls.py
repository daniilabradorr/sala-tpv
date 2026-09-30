from django.urls import path

from apps.onboarding import views

app_name = "onboarding"

urlpatterns = [
    path("", views.start, name="start"),
    path("success/", views.success, name="success"),
    path("welcome/", views.welcome, name="welcome"),
]
