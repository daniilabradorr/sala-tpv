"""Start/stop local Gunicorn against the runner's disposable PostgreSQL DB."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

from django.db import connection


@contextmanager
def server(fallback):
    if os.getenv("TPV_DIAGNOSTIC_GUNICORN") != "1":
        yield fallback, None
        return
    if connection.vendor != "postgresql":
        raise RuntimeError("Gunicorn matrix requires isolated PostgreSQL settings")
    root = Path(os.getenv("TPV_DIAGNOSTIC_OUTPUT", "work/tpv-diagnostic")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    trace_file = root / "gunicorn-traces.jsonl"
    trace_file.write_text("")
    url = urlsplit(os.environ["TPV_TEST_DATABASE_URL"])
    database_url = urlunsplit(url._replace(path="/" + connection.settings_dict["NAME"]))
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.diagnostic_http",
        "TPV_DIAGNOSTIC_TEST_CHILD": "1",
        "TPV_TEST_DATABASE_URL": database_url,
        "TPV_DIAGNOSTIC_LOG": str(trace_file),
    }
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (root / "gunicorn.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "gunicorn",
                "config.wsgi:application",
                "--bind",
                f"127.0.0.1:{port}",
                "--workers",
                "1",
                "--threads",
                "1",
                "--timeout",
                "30",
                "--config",
                "python:tests.performance.diagnostic_gunicorn",
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError(
                        "Gunicorn startup failed; inspect local gunicorn.log"
                    )
                try:
                    with urlopen(base + "/health/", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Gunicorn readiness timed out")
                    time.sleep(0.05)
            yield base, trace_file
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def lookup(trace_id, trace_file):
    if trace_file is None:
        from tests.performance.diagnostic import recent

        return recent(trace_id)
    for line in reversed(trace_file.read_text().splitlines()):
        row = json.loads(line)
        if row["trace_id"] == trace_id:
            return row
    return None
