"""In-process diagnostic wrappers only. No SQL text/values leave this module."""

from collections import defaultdict
from contextvars import ContextVar
from functools import wraps
from hashlib import sha256
import re
from time import perf_counter

from django.conf import settings
from django.db import transaction

from tests.performance import diagnostic as base
from tests.performance.metrics import sql_pattern

_installed = False
_atomic_frames = ContextVar("phase3_atomic_frames", default=())


class DetailedTrace(base.Trace):
    def __init__(self, trace_id):
        super().__init__(trace_id)
        self.details = defaultdict(lambda: {"calls": 0, "ms": 0.0, "exclusive_ms": 0.0})
        self.detail_stack = []
        self.groups = {}
        self.shape_cache = {}
        self.locks = []
        self.transactions = []

    def execute(self, execute, sql, params, many, context):
        start = perf_counter()
        try:
            return super().execute(execute, sql, params, many, context)
        finally:
            elapsed = (perf_counter() - start) * 1000
            # Only hashes and fixed schema identifiers are retained, never SQL/params.
            digest = sha256(sql.encode()).digest()
            shape = self.shape_cache.get(digest)
            if shape is None:
                operation = sql.lstrip().split(None, 1)[0].upper()
                operation = (
                    operation
                    if operation
                    in {
                        "SELECT",
                        "INSERT",
                        "UPDATE",
                        "SAVEPOINT",
                        "RELEASE",
                        "ROLLBACK",
                        "DELETE",
                    }
                    else "OTHER"
                )
                normalized = (
                    operation
                    if operation in {"SAVEPOINT", "RELEASE", "ROLLBACK"}
                    else sql_pattern(sql)
                )
                fingerprint = sha256(normalized.encode()).hexdigest()[:16]
                tables = sorted(
                    set(re.findall(r'(?:FROM|JOIN|INTO|UPDATE) "([a-z_]+)"', sql))
                )
                tables = [
                    t
                    for t in tables
                    if t.startswith(
                        (
                            "sales_",
                            "payments_",
                            "billing_",
                            "inventory_",
                            "cash_register_",
                            "audit_",
                            "business_config_",
                        )
                    )
                ]
                shape = (fingerprint, operation, tables, "FOR UPDATE" in sql.upper())
                # Bounded to this trace; no query text or parameter is cached.
                if len(self.shape_cache) < 4096:
                    self.shape_cache[digest] = shape
            fingerprint, operation, tables, is_lock = shape
            row = self.groups.setdefault(
                fingerprint,
                {
                    "fingerprint": fingerprint,
                    "operation": operation,
                    "tables": tables,
                    "count": 0,
                    "ms": 0.0,
                    "max_ms": 0.0,
                },
            )
            row["count"] += 1
            row["ms"] += elapsed
            row["max_ms"] = max(row["max_ms"], elapsed)
            if is_lock:
                self.locks.append(
                    {
                        "tables": tables,
                        "execute_ms": round(elapsed, 3),
                        "stage": self.detail_stack[-1][0]
                        if self.detail_stack
                        else (self.stack[-1] if self.stack else None),
                    }
                )

    def report(self, status):
        result = super().report(status)
        result["detail_stages"] = {
            key: {k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()}
            for key, row in self.details.items()
        }
        result["sql_groups"] = sorted(
            (
                {k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()}
                for row in self.groups.values()
            ),
            key=lambda r: r["ms"],
            reverse=True,
        )
        result["lock_executes"] = self.locks
        result["transactions"] = self.transactions
        result["collector_revision"] = "phase3-v2-cached-shapes"
        return result


def measured(function, label):
    @wraps(function)
    def wrapped(*args, **kwargs):
        trace = base.CURRENT.get()
        if not isinstance(trace, DetailedTrace):
            return function(*args, **kwargs)
        frame = [label, 0.0]
        trace.detail_stack.append(frame)
        start = perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            elapsed = (perf_counter() - start) * 1000
            trace.detail_stack.pop()
            row = trace.details[label]
            row["calls"] += 1
            row["ms"] += elapsed
            row["exclusive_ms"] += elapsed - frame[1]
            if trace.detail_stack:
                trace.detail_stack[-1][1] += elapsed

    return wrapped


def install():
    global _installed
    if _installed:
        return
    base.Trace = DetailedTrace
    from apps.sales import checkout, services as sales, views, selectors, forms
    from apps.payments import services as payments
    from apps.billing import services as billing
    from apps.inventory import services as inventory
    from apps.cash_register import services as cash
    from apps.audit import services as audit
    from apps.core import context_processors
    from django.db.models import Model
    from django.forms.forms import BaseForm
    from django.db import connections

    modules = (
        checkout,
        sales,
        views,
        selectors,
        forms,
        payments,
        billing,
        inventory,
        cash,
        audit,
    )
    targets = (
        (checkout, "_preflight", "preflight"),
        (selectors, "get_sale_checkout", "initial_sale_read"),
        (sales, "_lock_sale", "sales_lock_sale"),
        (sales, "_recalculate_locked_sale", "recalculate_lines"),
        (sales, "_validate_line_integrity", "line_integrity"),
        (inventory, "_create_stock_movement", "stock_movement"),
        (payments, "_existing", "payment_uuid"),
        (payments, "_get_sale_payment_balance", "payment_balance"),
        (payments, "recalculate_sale_payment_state", "payment_state"),
        (cash, "register_payment_cash_movement", "cash_movement"),
        (billing, "_validate_sale", "fiscal_sale_validation"),
        (billing, "_validate_customer", "fiscal_customer_validation"),
        (billing, "_issuer_snapshot", "issuer_snapshot"),
        (billing, "_sale_line_snapshots", "line_snapshots"),
        (billing, "_candidate_series", "series_candidate"),
        (billing, "_lock_series", "series_lock"),
        (billing, "_issue_draft", "number_and_issue"),
        (audit, "log_event", "audit"),
    )
    for module, attribute, label in targets:
        original = getattr(module, attribute)
        wrapper = measured(original, label)
        for candidate in modules:
            for name, value in list(vars(candidate).items()):
                if value is original:
                    setattr(candidate, name, wrapper)
    for cls, attr, label in (
        (views.SaleCheckoutView, "_forms", "forms_options"),
        (views.SaleCheckoutView, "dispatch", "dispatch_permissions"),
        (BaseForm, "full_clean", "form_validation"),
        (Model, "full_clean", "model_full_clean"),
    ):
        setattr(cls, attr, measured(getattr(cls, attr), label))
    # Template engines resolve context processors lazily; wrap before first render.
    context_processors.app_shell = measured(
        context_processors.app_shell, "context_app_shell"
    )
    original_enter, original_exit = (
        transaction.Atomic.__enter__,
        transaction.Atomic.__exit__,
    )

    def enter(atomic):
        trace = base.CURRENT.get()
        if not isinstance(trace, DetailedTrace):
            return original_enter(atomic)
        db = connections[atomic.using or "default"]
        outer = not db.in_atomic_block
        phase = (
            next(
                (
                    name
                    for name in ("payment", "billing", "checkout")
                    if name in trace.stack
                ),
                "other",
            )
            if outer
            else None
        )
        previous = _atomic_frames.get()
        _atomic_frames.set(
            (*previous, (atomic, trace, phase, perf_counter() if outer else None))
        )
        try:
            return original_enter(atomic)
        except BaseException:
            _atomic_frames.set(previous)
            raise

    def leave(atomic, exc_type, exc_value, traceback):
        try:
            return original_exit(atomic, exc_type, exc_value, traceback)
        finally:
            frames = _atomic_frames.get()
            if frames and frames[-1][0] is atomic:
                _, trace, phase, start = frames[-1]
                if phase is not None:
                    trace.transactions.append(
                        {
                            "phase": phase,
                            "ms": round((perf_counter() - start) * 1000, 3),
                            "exception_at_exit": exc_type is not None,
                        }
                    )
                _atomic_frames.set(frames[:-1])

    transaction.Atomic.__enter__, transaction.Atomic.__exit__ = enter, leave
    _installed = True


class Phase3Middleware(base.DiagnosticMiddleware):
    def __init__(self, get_response):
        if getattr(settings, "TPV_DIAGNOSTICS", False) and getattr(
            settings, "TPV_PHASE3_DIAGNOSTICS", False
        ):
            base.install()
            install()
        super().__init__(get_response)
