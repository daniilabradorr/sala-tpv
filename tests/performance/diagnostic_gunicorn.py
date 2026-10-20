"""Optional test/staging Gunicorn config; does not log request URLs or bodies."""

import json
from time import perf_counter


accesslog = None


def pre_request(worker, req):
    from tests.performance.diagnostic import GUNICORN_STARTED

    req.tpv_started = perf_counter()
    GUNICORN_STARTED.set(req.tpv_started)


def post_request(worker, req, environ, resp):
    from tests.performance.diagnostic import GUNICORN_STARTED

    headers = dict(resp.headers)
    worker.log.info(
        json.dumps(
            {
                "event": "gunicorn_response_done",
                "trace_id": headers.get("X-TPV-Trace"),
                "gunicorn_ms": round((perf_counter() - req.tpv_started) * 1000, 3),
            }
        )
    )
    GUNICORN_STARTED.set(None)
