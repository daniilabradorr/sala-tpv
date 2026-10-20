"""Synthetic 1/20/50-line matrix. Use only config.settings.diagnostic[_postgres]."""

import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from tests.performance.dataset import Dataset
from tests.performance.diagnostic import recent
from tests.performance.metrics import distribution


def guard():
    if os.environ.get("DJANGO_SETTINGS_MODULE") not in (
        "config.settings.diagnostic",
        "config.settings.diagnostic_postgres",
    ):
        raise RuntimeError("Only isolated diagnostic settings are supported")


def path(name, sale, line=None):
    args = [sale.store_id, sale.pk]
    if line is not None:
        args.append(line.pk)
    return reverse(f"sales:{name}", args=args)


def checkout_data(dataset):
    return {
        "mode": "single",
        "method": next(m.pk for m in dataset.methods if m.affects_cash_register),
        "cash_received": "",
        "payment_idempotency_key": str(uuid4()),
        "billing_idempotency_key": str(uuid4()),
    }


def verify(test, sale, operation, initial_count):
    from apps.billing.models import BillingDocument
    from apps.cash_register.models import CashMovement
    from apps.payments.models import Payment

    sale.refresh_from_db()
    count = sale.lines.count()
    test.assertEqual(
        count,
        initial_count
        + (1 if operation == "add" else -1 if operation == "delete" else 0),
    )
    if operation == "checkout_post":
        test.assertEqual(sale.status, "completed")
        test.assertEqual(sale.pending_amount, 0)
        test.assertEqual(
            Payment.objects.filter(sale=sale, status="completed").count(), 1
        )
        test.assertEqual(
            BillingDocument.objects.filter(sale=sale, status="issued").count(), 1
        )
        test.assertEqual(CashMovement.objects.filter(sale=sale).count(), 1)
        test.assertEqual(Payment.objects.get(sale=sale).amount, sale.total_amount)
        test.assertEqual(CashMovement.objects.get(sale=sale).amount, sale.total_amount)


def save_result(name, scenarios, **extra):
    root = Path(os.getenv("TPV_DIAGNOSTIC_OUTPUT", "work/tpv-diagnostic"))
    root.mkdir(parents=True, exist_ok=True)
    result = {
        "base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "working_tree_instrumented": True,
        "environment": "synthetic-local-test",
        "database_vendor": connection.vendor,
        "enabled": settings.TPV_DIAGNOSTICS,
        "scenarios": scenarios,
        **extra,
    }
    (root / name).write_text(json.dumps(result, indent=2) + "\n")


class ServerMatrix(TestCase):
    def test_matrix(self):
        guard()
        dataset = Dataset(60, label="diagnostic-server")
        client = Client()
        client.force_login(dataset.user)
        samples = int(os.getenv("TPV_DIAGNOSTIC_SAMPLES", "5"))
        scenarios = {}
        for size in (1, 20, 50):
            for operation in (
                "add",
                "quantity",
                "delete",
                "checkout_get",
                "checkout_post",
            ):
                rows = []
                for iteration in range(samples + 1):
                    sale, lines = dataset.sale(size)
                    if operation == "add":
                        url = path("sale_line_add", sale)
                        data = {"product": dataset.products[21].pk, "quantity": "1"}
                    elif operation == "quantity":
                        url = path("sale_line_quantity_update", sale, lines[0])
                        data = {"quantity": "2"}
                    elif operation == "delete":
                        url = path("sale_line_delete", sale, lines[0])
                        data = {}
                    else:
                        url = path("sale_checkout", sale)
                        data = (
                            checkout_data(dataset)
                            if operation == "checkout_post"
                            else None
                        )
                    start = time.perf_counter()
                    response = (
                        client.get(url, HTTP_HX_REQUEST="true")
                        if data is None
                        else client.post(url, data, HTTP_HX_REQUEST="true")
                    )
                    elapsed = (time.perf_counter() - start) * 1000
                    self.assertEqual(response.status_code, 200)
                    verify(self, sale, operation, size)
                    if operation == "quantity":
                        lines[0].refresh_from_db()
                        self.assertEqual(lines[0].quantity, 2)
                    row = {"client_ms": elapsed, "bytes": len(response.content)}
                    if settings.TPV_DIAGNOSTICS:
                        trace = recent(response["X-TPV-Trace"])
                        self.assertIsNotNone(trace)
                        row["trace"] = trace
                    if iteration:
                        rows.append(row)
                scenarios[f"{operation}_{size}"] = {
                    "client_ms": distribution([r["client_ms"] for r in rows]),
                    "samples": rows,
                }
        save_result(
            "server.json",
            scenarios,
            warmups=1,
            iterations=samples,
            transport="Django Client; outer TestCase transaction; not HTTP",
        )


class BrowserMatrix(StaticLiveServerTestCase):
    def test_matrix(self):
        guard()
        from playwright.sync_api import expect, sync_playwright
        from tests.performance.diagnostic_http import server, lookup

        dataset = Dataset(60, label="diagnostic-browser")
        client = Client()
        client.force_login(dataset.user)
        samples = int(os.getenv("TPV_DIAGNOSTIC_SAMPLES", "5"))
        # Fixture writes stay on the synchronous Django thread.
        fixtures = {
            (size, operation): [dataset.sale(size) for _ in range(samples + 1)]
            for size in (1, 20, 50)
            for operation in (
                "add",
                "quantity",
                "delete",
                "checkout_get",
                "checkout_post",
            )
        }
        scenarios = {}
        script = Path(__file__).with_name("diagnostic-browser.js").read_text()
        with (
            server(self.live_server_url) as (base_url, trace_file),
            sync_playwright() as playwright,
        ):
            browser = playwright.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM", "/usr/bin/chromium"),
                headless=True,
            )
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            # Same-host baseline: external fonts/images are excluded explicitly.
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith(base_url + "/")
                    else route.abort()
                ),
            )
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": base_url,
                    }
                ]
            )
            for (size, operation), sales in fixtures.items():
                rows = []
                for iteration, (sale, lines) in enumerate(sales):
                    page = context.new_page()
                    page.goto(
                        base_url + path("sale_detail", sale),
                        wait_until="load",
                    )
                    page.wait_for_function("window.htmx !== undefined")
                    page.evaluate(script)
                    if operation == "checkout_post":
                        page.locator("[data-checkout-open]").click()
                        expect(page.locator("[data-checkout-form]")).to_be_visible()
                        page.locator('[name="method"][data-method-cash="true"]').check()
                        page.wait_for_function("window.tpvDiagnostic.rows.length === 1")
                        page.evaluate("window.tpvDiagnostic.rows.length = 0")
                    with page.expect_response(
                        lambda r: (
                            "/sales/stores/" in r.url
                            and r.request.resource_type == "xhr"
                        )
                    ) as captured:
                        if operation == "add":
                            page.locator("#product-grid .product-card").nth(21).click()
                        elif operation == "quantity":
                            page.locator(
                                '.cart-line:first-child [data-quantity-step="1"]'
                            ).click()
                        elif operation == "delete":
                            page.locator(".cart-line:first-child .link-danger").click()
                        elif operation == "checkout_get":
                            page.locator("[data-checkout-open]").click()
                        else:
                            page.locator(".checkout-confirm").click()
                    self.assertEqual(captured.value.status, 200)
                    page.wait_for_function(
                        "window.tpvDiagnostic.rows.length === 1", timeout=60000
                    )
                    if operation == "checkout_post":
                        expect(page.locator(".checkout-success")).to_be_visible()
                    elif operation == "checkout_get":
                        expect(page.locator("[data-checkout-form]")).to_be_visible()
                    else:
                        expect(page.locator(".cart-line")).to_have_count(
                            size
                            + (
                                1
                                if operation == "add"
                                else -1
                                if operation == "delete"
                                else 0
                            )
                        )
                    if operation == "quantity":
                        expect(page.locator(f"#quantity-{lines[0].pk}")).to_have_value(
                            "2"
                        )
                    row = page.evaluate("window.tpvDiagnostic.rows[0]")
                    if settings.TPV_DIAGNOSTICS:
                        row["trace"] = lookup(row["trace_id"], trace_file)
                        self.assertIsNotNone(row["trace"])
                    if iteration:
                        rows.append(row)
                    page.close()
                scenarios[f"{operation}_{size}"] = {
                    "http_ms": distribution([r["http_ms"] for r in rows]),
                    "interaction_to_frame_ms": distribution(
                        [r["interaction_to_frame_ms"] for r in rows]
                    ),
                    "samples": rows,
                }
            version = browser.version
            browser.close()
        # ORM validation outside Playwright's async context.
        for (size, operation), sales in fixtures.items():
            for sale, _ in sales:
                verify(self, sale, operation, size)
        save_result(
            "browser.json",
            scenarios,
            warmups=1,
            iterations=samples,
            chromium=version,
            transport="HTTP loopback; Gunicorn sync 1 worker"
            if trace_file
            else "HTTP loopback; Django test WSGI server",
            external_resources="blocked; same-host baseline",
        )
