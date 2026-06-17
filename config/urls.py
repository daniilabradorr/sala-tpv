from django.contrib import admin
from django.urls import path, include

from apps.core.views import health_check

admin.site.site_header = "Sala TPV Admin"
admin.site.site_title = "Sala TPV"
admin.site.index_title = "Panel de administración"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),
    path("users/", include("apps.users.urls")),
]
