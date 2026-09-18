from .base import *  # noqa: F403
import os

from django.core.exceptions import ImproperlyConfigured

DEBUG = False

_media_required = (
    "MEDIA_STORAGE_ENDPOINT_URL",
    "MEDIA_STORAGE_ACCESS_KEY",
    "MEDIA_STORAGE_SECRET_KEY",
    "MEDIA_STORAGE_BUCKET_NAME",
)
_media_missing = [name for name in _media_required if not os.getenv(name)]
if _media_missing:
    raise ImproperlyConfigured(
        "Configuración de media incompleta; faltan: " + ", ".join(_media_missing)
    )

_media_public = os.getenv("MEDIA_STORAGE_PUBLIC_READ", "1") == "1"
STORAGES["default"] = {  # noqa: F405
    "BACKEND": "storages.backends.s3.S3Storage",
    "OPTIONS": {
        "endpoint_url": os.environ["MEDIA_STORAGE_ENDPOINT_URL"],
        "access_key": os.environ["MEDIA_STORAGE_ACCESS_KEY"],
        "secret_key": os.environ["MEDIA_STORAGE_SECRET_KEY"],
        "bucket_name": os.environ["MEDIA_STORAGE_BUCKET_NAME"],
        "region_name": os.getenv("MEDIA_STORAGE_REGION") or None,
        "custom_domain": os.getenv("MEDIA_STORAGE_CUSTOM_DOMAIN") or None,
        "default_acl": "public-read" if _media_public else None,
        "querystring_auth": not _media_public,
        "file_overwrite": False,
        "object_parameters": {
            "CacheControl": "public, max-age=31536000, immutable"
        },
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "1") == "1"
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "1") == "1"
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "1") == "1"

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
