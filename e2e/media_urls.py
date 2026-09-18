"""Test-only URLConf that serves managed media while DEBUG is false."""

from django.conf import settings
from django.urls import re_path
from django.views.static import serve

from config.urls import urlpatterns as application_urlpatterns

urlpatterns = [
    *application_urlpatterns,
    re_path(
        r"^media/(?P<path>.*)$",
        serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
