"""Opt-in phase 3 diagnostics, exclusively on a runner-created PostgreSQL DB."""

import os

if os.environ.get("TPV_DIAGNOSTIC_TEST_CHILD") == "1":
    from .diagnostic_http import *  # noqa: F403
else:
    from .diagnostic_postgres import *  # noqa: F403

TPV_PHASE3_DIAGNOSTICS = os.environ.get("TPV_PHASE3_DIAGNOSTICS", "0") == "1"
MIDDLEWARE = [  # noqa: F405
    "tests.performance.phase3_trace.Phase3Middleware",
    *MIDDLEWARE[1:],  # noqa: F405
]
