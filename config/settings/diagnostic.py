"""Isolated synthetic tests only; does not inherit DATABASE_URL or production DB."""

from .test import *  # noqa: F403
import os

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
TPV_DIAGNOSTICS = os.getenv("TPV_DIAGNOSTICS", "0") == "1"
MIDDLEWARE = [  # noqa: F405
    "tests.performance.diagnostic.DiagnosticMiddleware",
    *MIDDLEWARE,  # noqa: F405
]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# Benchmark consumes the bounded in-process trace buffer; no synchronous log I/O.
LOGGING = {  # noqa: F405
    **LOGGING,  # noqa: F405
    "loggers": {"tpv.diagnostic": {"handlers": [], "propagate": False}},
}
