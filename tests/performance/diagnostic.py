"""Temporary, opt-in synchronous TPV tracing. Never records SQL or arguments."""

from collections import defaultdict, deque
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
import re
import threading
from time import perf_counter, time
from uuid import uuid4

from django.conf import settings
from django.db import connections


CURRENT = ContextVar("tpv_diagnostic", default=None)
GUNICORN_STARTED = ContextVar("tpv_gunicorn_started", default=None)
RECENT = deque(maxlen=1000)
RECENT_LOCK = threading.Lock()
LOGGER = logging.getLogger("tpv.diagnostic")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_installed = False


class Trace:
    def __init__(self, trace_id):
        self.id = trace_id
        self.start = perf_counter()
        self.epoch_ms = round(time() * 1000, 3)
        self.sql_ms = 0.0
        self.sql_count = 0
        self.stack = []
        self.stages = defaultdict(
            lambda: {"calls": 0, "ms": 0.0, "sql_ms": 0.0, "queries": 0}
        )
        self.pids = set()

    def execute(self, execute, sql, params, many, context):
        # sql/params are deliberately neither retained nor fingerprinted.
        raw = context["connection"].connection
        pid = getattr(getattr(raw, "info", None), "backend_pid", None)
        if isinstance(pid, int):
            self.pids.add(pid)
        start = perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            elapsed = (perf_counter() - start) * 1000
            self.sql_ms += elapsed
            self.sql_count += 1
            for name in self.stack:
                self.stages[name]["sql_ms"] += elapsed
                self.stages[name]["queries"] += 1

    def report(self, status):
        return {
            "trace_id": self.id,
            "status": status,
            "request_start_epoch_ms": self.epoch_ms,
            "assigned_request_to_django_ms": (
                round((self.start - GUNICORN_STARTED.get()) * 1000, 3)
                if GUNICORN_STARTED.get() is not None
                else None
            ),
            "django_ms": round((perf_counter() - self.start) * 1000, 3),
            "sql_execute_ms": round(self.sql_ms, 3),
            "sql_count": self.sql_count,
            "driver_backend_pids": sorted(self.pids),
            "stages": {
                name: {
                    k: round(v, 3) if isinstance(v, float) else v
                    for k, v in row.items()
                }
                for name, row in self.stages.items()
            },
        }


@contextmanager
def span(name):
    trace = CURRENT.get()
    if trace is None:
        yield
        return
    start = perf_counter()
    trace.stack.append(name)
    trace.stages[name]["calls"] += 1
    try:
        yield
    finally:
        trace.stack.pop()
        trace.stages[name]["ms"] += (perf_counter() - start) * 1000


def timed(function, name):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with span(name):
            return function(*args, **kwargs)

    return wrapped


def install():
    """Patch only in the diagnostic process, including imported function aliases."""
    global _installed
    if _installed:
        return
    from apps.sales import checkout, services, views
    from apps.payments import services as payments
    from apps.billing import services as billing
    from apps.inventory import services as inventory
    from django.db.backends.base.base import BaseDatabaseWrapper

    for name in ("connect", "commit", "rollback"):
        setattr(
            BaseDatabaseWrapper,
            name,
            timed(getattr(BaseDatabaseWrapper, name), "db_" + name),
        )

    modules = (checkout, services, views, payments, billing, inventory)
    targets = (
        (checkout, "run_checkout", "checkout"),
        (checkout, "checkout_state", "state"),
        (checkout, "checkout_options", "options"),
        (services, "complete_sale", "complete_sale"),
        (payments, "register_sale_payment", "payment"),
        (billing, "issue_sale_document", "billing"),
        (inventory, "decrease_stock", "inventory"),
        (billing, "_create_lines_and_breakdowns", "billing_lines"),
        (views, "render", "html_render"),
    )
    for module, attribute, label in targets:
        original = getattr(module, attribute)
        wrapper = timed(original, label)
        for candidate in modules:
            for name, value in list(vars(candidate).items()):
                if value is original:
                    setattr(candidate, name, wrapper)
    for cls in (
        views.SaleCheckoutView,
        views.SaleLineAddView,
        views.SaleLineQuantityUpdateView,
        views.SaleLineDeleteView,
    ):
        for method in ("get", "post"):
            if method in cls.__dict__:
                setattr(cls, method, timed(getattr(cls, method), "view"))
    _installed = True


def recent(trace_id):
    with RECENT_LOCK:
        return next((r for r in reversed(RECENT) if r["trace_id"] == trace_id), None)


class DiagnosticMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, "TPV_DIAGNOSTICS", False)
        if self.enabled:
            install()

    def __call__(self, request):
        if not self.enabled or not request.path.startswith("/sales/stores/"):
            return self.get_response(request)
        incoming = request.headers.get("X-TPV-Trace", "")
        trace = Trace(incoming if UUID.fullmatch(incoming) else str(uuid4()))
        token = CURRENT.set(trace)
        try:
            with ExitStack() as stack:
                for connection in connections.all():
                    stack.enter_context(connection.execute_wrapper(trace.execute))
                response = self.get_response(request)
            report = trace.report(response.status_code)
            response["X-TPV-Trace"] = trace.id
            response["Server-Timing"] = (
                f"django;dur={report['django_ms']}, sql;dur={report['sql_execute_ms']}"
            )
            with RECENT_LOCK:
                RECENT.append(report)
            LOGGER.info(json.dumps(report, separators=(",", ":")))
            return response
        finally:
            CURRENT.reset(token)
