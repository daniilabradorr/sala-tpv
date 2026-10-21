"""Allowlisted runtime snapshot. --database performs only PostgreSQL SHOW/SELECT."""

import argparse
import json
import os
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    import django
    import gunicorn

    django.setup()
    from django.conf import settings
    from django.db import connection
    from gunicorn.config import Config

    database = settings.DATABASES["default"]
    config = Config()
    commit = os.environ.get("RENDER_GIT_COMMIT", "")
    report = {
        "django": django.get_version(),
        "gunicorn": gunicorn.__version__,
        "settings_module": os.environ["DJANGO_SETTINGS_MODULE"],
        "checkout_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "render_commit": commit if re.fullmatch(r"[0-9a-f]{40,64}", commit) else None,
        "database": {
            key: database.get(key)
            for key in (
                "ENGINE",
                "CONN_MAX_AGE",
                "CONN_HEALTH_CHECKS",
                "ATOMIC_REQUESTS",
            )
        },
        "gunicorn_defaults_not_running_process": {
            key: config.settings[key].value
            for key in (
                "workers",
                "worker_class",
                "threads",
                "timeout",
                "graceful_timeout",
                "keepalive",
                "backlog",
            )
        },
        "runtime_override_presence": {
            key: key in os.environ
            for key in (
                "GUNICORN_CMD_ARGS",
                "WEB_CONCURRENCY",
                "RENDER_GIT_COMMIT",
            )
        },
        "pooler": "unknown; requires provider configuration",
    }
    if args.database:
        if connection.vendor != "postgresql":
            report["postgresql"] = "not configured"
        else:
            with connection.cursor() as cursor:
                # Fixed names, no credentials or request data.
                cursor.execute("""
                    SELECT name, setting, unit FROM pg_settings
                    WHERE name IN ('server_version', 'max_connections',
                    'statement_timeout', 'lock_timeout',
                    'idle_in_transaction_session_timeout') ORDER BY name
                """)
                report["postgresql"] = [
                    {"name": name, "setting": value, "unit": unit}
                    for name, value, unit in cursor.fetchall()
                ]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
