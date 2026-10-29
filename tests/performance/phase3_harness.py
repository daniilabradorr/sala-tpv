"""Phase 3 B synthetic measurements; invoked explicitly, excluded from auto discovery."""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import monotonic, sleep
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen
from uuid import uuid4
import socket
import signal

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection, connections
from django.test import Client
from django.urls import reverse

from tests.performance.dataset import Dataset
from tests.performance.diagnostic_http import lookup

ROOT = Path(os.environ.get("TPV_DIAGNOSTIC_OUTPUT", "/workspace/work/phase3-b"))


def guard():
    if os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings.diagnostic_phase3":
        raise RuntimeError("Only phase3 diagnostic settings")
    db = connection.settings_dict
    if (
        connection.vendor != "postgresql"
        or db["HOST"] != "127.0.0.1"
        or str(db["PORT"]) != "55437"
        or not db["NAME"].startswith("test_tpv_diag_")
    ):
        raise RuntimeError(
            "Requires the dedicated disposable container on loopback:55437 and runner test DB"
        )


def save(name, value):
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / name).write_text(json.dumps(value, indent=2) + "\n")


def summary(values):
    return {
        "n": len(values),
        "min": round(min(values), 3),
        "median": round(median(values), 3),
        "max": round(max(values), 3),
        "p95": None,
    }


def url(sale):
    return reverse("sales:sale_checkout", args=[sale.store_id, sale.pk])


def payload(dataset, sale, mode="card"):
    methods = {m.code: m for m in dataset.methods}
    data = {
        "mode": "single",
        "method": methods[mode if mode != "split" else "card"].pk,
        "cart_version": sale.cart_version,
        "payment_idempotency_key": str(uuid4()),
        "billing_idempotency_key": str(uuid4()),
    }
    if mode == "split":
        half = (sale.total_amount / 2).quantize(Decimal(".01"))
        data.update(
            mode="split",
            **{
                "payments-TOTAL_FORMS": "2",
                "payments-INITIAL_FORMS": "0",
                "payments-MIN_NUM_FORMS": "2",
                "payments-MAX_NUM_FORMS": "2",
            },
        )
        for index, (method, amount) in enumerate(
            ((methods["cash"], half), (methods["card"], sale.total_amount - half))
        ):
            data.update(
                {
                    f"payments-{index}-method": method.pk,
                    f"payments-{index}-amount": str(amount),
                    f"payments-{index}-idempotency_key": str(uuid4()),
                }
            )
    return data


def economic(sale):
    from apps.billing.models import BillingDocument
    from apps.payments.models import Payment
    from apps.inventory.models import StockMovement
    from apps.cash_register.models import CashMovement, CashSession

    sale.refresh_from_db()
    return {
        "sale_status": sale.status,
        "payment_status": sale.payment_status,
        "pending_zero": sale.pending_amount == 0,
        "payments": Payment.objects.filter(sale=sale).count(),
        "documents": BillingDocument.objects.filter(sale=sale, status="issued").count(),
        "stock_movements": StockMovement.objects.filter(sale=sale).count(),
        "cash_movements": CashMovement.objects.filter(sale=sale).count(),
        "cash_session_status": CashSession.objects.get(pk=sale.cash_session_id).status,
    }


@contextmanager
def gunicorn():
    guard()
    ROOT.mkdir(parents=True, exist_ok=True)
    trace_file = ROOT / "gunicorn-traces.jsonl"
    trace_file.write_text("")
    parsed = urlsplit(os.environ["TPV_TEST_DATABASE_URL"])
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.diagnostic_phase3",
        "TPV_DIAGNOSTIC_TEST_CHILD": "1",
        "TPV_TEST_DATABASE_URL": urlunsplit(
            parsed._replace(path="/" + connection.settings_dict["NAME"])
        ),
        "TPV_DIAGNOSTIC_LOG": str(trace_file),
    }
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (ROOT / "gunicorn.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "gunicorn",
                "config.wsgi:application",
                "--bind",
                f"127.0.0.1:{port}",
                "--no-control-socket",
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
            start_new_session=True,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = monotonic() + 20
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Gunicorn failed; inspect scratch gunicorn.log")
                try:
                    with urlopen(base + "/health/", timeout=1):
                        break
                except OSError:
                    if monotonic() > deadline:
                        raise TimeoutError("Gunicorn readiness")
                    sleep(0.05)
            yield base, trace_file
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


SCENARIOS = [
    ("E01", 1, "cash", "ticket", True, False),
    ("E02", 1, "card", "ticket", True, False),
    ("E03", 20, "cash", "ticket", True, False),
    ("E04", 20, "card", "ticket", True, False),
    ("E05", 50, "cash", "ticket", True, False),
    ("E06", 50, "card", "ticket", True, False),
    ("E07", 1, "split", "ticket", True, False),
    ("E08", 20, "split", "ticket", True, False),
    ("E09", 20, "card", "invoice", True, False),
    ("E10", 50, "card", "invoice", True, False),
    ("E11_stock_off", 20, "card", "ticket", False, False),
    ("E12_repeated", 20, "card", "ticket", True, True),
]


class BrowserMeasurements(StaticLiveServerTestCase):
    def test_matrix(self):
        guard()
        from playwright.sync_api import sync_playwright, expect

        dataset = Dataset(60, label="phase3-browser")
        dataset.settings.allow_split_payments = True
        dataset.settings.save()
        client = Client()
        client.force_login(dataset.user)
        count = int(os.environ.get("TPV_PHASE3_SAMPLES", "7"))
        fixtures = {}
        for name, size, mode, document, stock, repeated in SCENARIOS:
            fixtures[name] = [
                dataset.sale(
                    size,
                    document=document,
                    customer=dataset.customers[0] if document == "invoice" else None,
                )
                for _ in range(count + 1)
            ]
            if repeated:
                from apps.sales.models import SaleLine

                # Fixture only: identical snapshots for equal-product repeated lines.
                for sale, lines in fixtures[name]:
                    original = lines[0]
                    for line in lines[1:]:
                        for field in (
                            "product_id",
                            "product_name",
                            "sku",
                            "category_source_id",
                            "category_name",
                            "category_slug",
                            "tax_type",
                            "tax_rate",
                            "tax_amount",
                            "line_total",
                        ):
                            setattr(line, field, getattr(original, field))
                    SaleLine.objects.bulk_update(
                        lines[1:],
                        [
                            "product",
                            "product_name",
                            "sku",
                            "category_source_id",
                            "category_name",
                            "category_slug",
                            "tax_type",
                            "tax_rate",
                            "tax_amount",
                            "line_total",
                        ],
                    )
                    from apps.sales.models import Sale

                    Sale.objects.filter(pk=sale.pk).update(
                        tax_amount=original.tax_amount * size,
                        total_amount=original.line_total * size,
                        pending_amount=original.line_total * size,
                    )
                    sale.refresh_from_db()
        results = {}
        # One server for all warm samples; warmup excluded per cell. Stock policy is
        # global to this synthetic business and changed outside measured intervals.
        with gunicorn() as (base, traces), sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/usr/bin/chromium", headless=True
            )
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith(base + "/")
                    else route.abort()
                ),
            )
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": base,
                    }
                ]
            )
            context.add_init_script(
                Path(__file__).with_name("phase3-browser.js").read_text()
            )
            observer = Path(__file__).with_name("diagnostic-browser.js").read_text()
            for name, size, mode, document, stock, repeated in SCENARIOS:
                # ORM outside Playwright async callbacks: allow sync ORM only on
                # this main test thread between browser operations.
                def set_stock():
                    try:
                        from apps.business_config.models import POSSettings

                        POSSettings.objects.filter(pk=dataset.settings.pk).update(
                            enable_stock_control=stock
                        )
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(set_stock).result()
                rows = []
                for index, (sale, lines) in enumerate(fixtures[name]):
                    page = context.new_page()
                    page.goto(
                        base
                        + reverse("sales:sale_detail", args=[sale.store_id, sale.pk]),
                        wait_until="load",
                    )
                    page.wait_for_function("window.SalesCartQueue && window.htmx")
                    page.evaluate("phase3.installQueue()")
                    page.evaluate(observer)
                    page.locator("[data-checkout-open]").click()
                    expect(page.locator("[data-checkout-form]")).to_be_visible(
                        timeout=30000
                    )
                    page.wait_for_function(
                        "tpvDiagnostic.rows.length >= 1 && phase3.open?.frame"
                    )
                    opened = page.evaluate(
                        "({observer: tpvDiagnostic.rows[0], detail: phase3.open, flush: phase3.flush, sync: phase3.sync})"
                    )
                    page.evaluate("tpvDiagnostic.rows.length = 0")
                    if mode == "split":
                        page.locator('[name="mode"][value="split"]').check()
                        half = (sale.total_amount / 2).quantize(Decimal(".01"))
                        page.locator('[name="payments-0-method"]').select_option(
                            str(next(m.pk for m in dataset.methods if m.code == "cash"))
                        )
                        page.locator('[name="payments-0-amount"]').fill(str(half))
                        page.locator('[name="payments-1-method"]').select_option(
                            str(next(m.pk for m in dataset.methods if m.code == "card"))
                        )
                        page.locator('[name="payments-1-amount"]').fill(
                            str(sale.total_amount - half)
                        )
                    else:
                        page.locator(
                            f'[name="method"][data-method-code="{mode}"]'
                        ).check()
                    page.locator(".checkout-confirm").click()
                    expect(page.locator(".checkout-success")).to_be_visible(
                        timeout=30000
                    )
                    page.wait_for_function(
                        "tpvDiagnostic.rows.length >= 1 && phase3.submit?.frame"
                    )
                    row = page.evaluate(
                        "({post: tpvDiagnostic.rows[0], frontend: phase3.submit, events: phase3.events, js_errors: phase3.errors})"
                    )
                    row["open"] = opened
                    row["trace"] = lookup(row["post"]["trace_id"], traces)
                    row["get_trace"] = lookup(opened["observer"]["trace_id"], traces)
                    self.assertIsNotNone(row["trace"])
                    self.assertFalse(row["frontend"]["processing"])
                    self.assertTrue(row["frontend"]["new_sale_enabled"])
                    self.assertEqual(row["js_errors"], 0)
                    if index:
                        rows.append(row)
                    page.close()
                results[name] = {
                    "lines": size,
                    "payment": mode,
                    "document": document,
                    "stock": stock,
                    "repeated_products": repeated,
                    "warmup": 1,
                    "samples": rows,
                    "http_ms": summary([r["post"]["http_ms"] for r in rows]),
                }
                save("browser.json", results)
                print(
                    f"{name}: n={len(rows)} HTTP median={results[name]['http_ms']['median']} ms",
                    flush=True,
                )
            browser.close()
        # Persistent invariants outside the asynchronous browser runtime.
        dataset.session.refresh_from_db()
        from apps.cash_register.models import CashMovement
        from django.db.models import Sum

        self.assertEqual(
            dataset.session.expected_cash_amount,
            CashMovement.objects.filter(cash_session=dataset.session).aggregate(
                total=Sum("amount")
            )["total"],
        )
        for name, size, mode, document, stock, repeated in SCENARIOS:
            final = []
            for sale, _ in fixtures[name]:
                state = economic(sale)
                self.assertEqual(state["payments"], 2 if mode == "split" else 1)
                self.assertEqual(state["documents"], 1)
                self.assertEqual(state["stock_movements"], size if stock else 0)
                self.assertTrue(state["pending_zero"])
                final.append(state)
            results[name]["economic_checks_including_warmup"] = final
        save("browser.json", results)
