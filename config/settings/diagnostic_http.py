"""Gunicorn child of the synthetic test runner; requires an existing test DB."""

from .diagnostic import *  # noqa: F403
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

database = dj_database_url.parse(os.environ["TPV_TEST_DATABASE_URL"], conn_max_age=600)
if (
    os.environ.get("TPV_DIAGNOSTIC_TEST_CHILD") != "1"
    or database["ENGINE"] != "django.db.backends.postgresql"
    or not database["NAME"].startswith("test_tpv_diag_")
):
    raise ImproperlyConfigured("Only the disposable PostgreSQL test child is allowed")
DATABASES = {"default": database}
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
LOGGING = {
    **LOGGING,  # noqa: F405
    "handlers": {
        "diagnostic_file": {
            "class": "logging.FileHandler",
            "filename": os.environ["TPV_DIAGNOSTIC_LOG"],
        }
    },
    "root": {"handlers": [], "level": "WARNING"},
    "loggers": {
        "tpv.diagnostic": {
            "handlers": ["diagnostic_file"],
            "level": "INFO",
            "propagate": False,
        }
    },
}
