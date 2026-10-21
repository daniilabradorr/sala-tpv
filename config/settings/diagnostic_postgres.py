"""Explicit, dedicated PostgreSQL test database; never DATABASE_URL."""

from .diagnostic import *  # noqa: F403
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

database = dj_database_url.parse(os.environ["TPV_TEST_DATABASE_URL"], conn_max_age=600)
if database["ENGINE"] != "django.db.backends.postgresql" or not database[
    "NAME"
].startswith("tpv_diag_"):
    raise ImproperlyConfigured("Dedicated PostgreSQL database tpv_diag_* required")
DATABASES = {"default": database}
