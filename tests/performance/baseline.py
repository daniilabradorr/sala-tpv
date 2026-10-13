"""Opt-in server baseline: python -m tests.performance.baseline --output ...

Only config.settings.test is accepted. Django creates and destroys its test DB;
this is neither an installed management command nor a production endpoint.
"""

import argparse
import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path

import django


def metadata():
    from django.db import connection

    version = None
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            version = cursor.fetchone()[0]
    return {
        "schema_version": 1,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "python": platform.python_version(),
        "django": django.get_version(),
        "database": {"vendor": connection.vendor, "version": version},
        "percentile": "nearest rank: sorted[ceil(0.95*n)-1]; p50=statistics.median",
    }


def scenarios(dataset):
    from django.urls import reverse
    from decimal import Decimal

    from apps.sales.selectors import get_sale_cart
    from django.template.loader import render_to_string

    def url(endpoint, sale, line=None):
        args = [dataset.store.pk, sale.pk]
        if line is not None:
            args.append(line.pk)
        return reverse(f"sales:{endpoint}", args=args)

    for size in (0, 1, 5, 20, 50):
        sale, _ = dataset.sale(size)
        yield (
            f"workspace_{size}_lines",
            lambda s=sale: ("GET", url("sale_detail", s), {}, False),
        )
        if size:

            def cart(s=sale):
                current = get_sale_cart(
                    business=dataset.business, store=dataset.store, pk=s.pk
                )
                return render_to_string(
                    "sales/partials/_cart_content.html",
                    {
                        "store": dataset.store,
                        "sale": current,
                        "lines": current.lines.all(),
                        "pos_settings": dataset.settings,
                    },
                ).encode()

            yield f"cart_read_{size}_lines", lambda c=cart: c

    for count in (1, 20):
        sale, _ = dataset.sale(count)
        yield (
            f"checkout_get_{count}_lines",
            lambda s=sale: ("GET", url("sale_checkout", s), {}, True),
        )

    for name, initial, final in (
        ("ticket_to_invoice", (None, "ticket"), (None, "invoice")),
        ("invoice_to_ticket", (None, "invoice"), (None, "ticket")),
        (
            "customer_none_to_customer",
            (None, "ticket"),
            (dataset.customers[0], "ticket"),
        ),
        (
            "customer_to_other",
            (dataset.customers[0], "ticket"),
            (dataset.customers[1], "ticket"),
        ),
    ):

        def prepare(before=initial, after=final):
            sale, _ = dataset.sale(5, customer=before[0], document=before[1])
            return (
                "POST",
                url("sale_header_update", sale),
                {
                    "customer": after[0].pk if after[0] else "",
                    "document_type_requested": after[1],
                },
                True,
            )

        yield f"header_{name}", prepare

    for count in (1, 20):

        def add(n=count):
            sale, _ = dataset.sale(n)
            return (
                "POST",
                url("sale_line_add", sale),
                {"product": dataset.products[n].pk, "quantity": "1"},
                True,
            )

        yield f"add_product_{count}_lines", add

        def delete(n=count):
            sale, lines = dataset.sale(n)
            return "POST", url("sale_line_delete", sale, lines[0]), {}, True

        yield f"delete_line_{count}_lines", delete

    for before, after in (("1", "2"), ("2", "1"), ("1", "1.5")):

        def quantity(a=before, b=after):
            sale, lines = dataset.sale(5, quantity=a)
            return (
                "POST",
                url("sale_line_quantity_update", sale, lines[0]),
                {"quantity": b},
                True,
            )

        yield f"quantity_{before}_to_{after}", quantity

    for mode in ("discount", "price"):
        sale, lines = dataset.sale(5)
        path = url("sale_line_update", sale, lines[0]) + f"?mode={mode}"
        yield f"editor_{mode}_get", lambda p=path: ("GET", p, {}, True)

        def editor(m=mode):
            sale, lines = dataset.sale(5)
            data = (
                {"discount_amount": "1"}
                if m == "discount"
                else {"unit_base_price": "11"}
            )
            return (
                "POST",
                url("sale_line_update", sale, lines[0]) + f"?mode={m}",
                data,
                True,
            )

        yield f"editor_{mode}_post", editor

    # Additional phase 7 payload sizes, using the same fresh-sale method.
    for mode in ("quantity", "discount", "price"):

        def large_edit(kind=mode):
            sale, lines = dataset.sale(50)
            if kind == "quantity":
                return (
                    "POST",
                    url("sale_line_quantity_update", sale, lines[24]),
                    {"quantity": "1.5"},
                    True,
                )
            data = (
                {"discount_amount": "1.00"}
                if kind == "discount"
                else {"unit_base_price": "11.00"}
            )
            return (
                "POST",
                url("sale_line_update", sale, lines[24]) + "?mode=" + kind,
                data,
                True,
            )

        yield f"{mode}_50_lines", large_edit

    import uuid

    cash = next(m for m in dataset.methods if m.affects_cash_register)
    card = next(m for m in dataset.methods if not m.affects_cash_register)
    for name in ("card", "cash_exact", "cash_change", "split"):

        def checkout(kind=name):
            sale, _ = dataset.sale(1)
            data = {
                "mode": "single",
                "payment_idempotency_key": str(uuid.uuid4()),
                "billing_idempotency_key": str(uuid.uuid4()),
                "method": card.pk if kind == "card" else cash.pk,
                "cash_received": "" if kind != "cash_change" else "20.00",
            }
            if kind == "split":
                data.update(
                    {
                        "mode": "split",
                        "payments-TOTAL_FORMS": "2",
                        "payments-INITIAL_FORMS": "0",
                        "payments-MIN_NUM_FORMS": "2",
                        "payments-MAX_NUM_FORMS": "2",
                    }
                )
                for index, method in enumerate((cash, card)):
                    data.update(
                        {
                            f"payments-{index}-method": method.pk,
                            f"payments-{index}-amount": "5.00"
                            if index == 0
                            else str(sale.pending_amount - Decimal("5.00")),
                            f"payments-{index}-cash_received": "20.00"
                            if index == 0
                            else "",
                            f"payments-{index}-idempotency_key": str(uuid.uuid4()),
                        }
                    )
            return ("POST", url("sale_checkout", sale), data, True)

        yield f"checkout_post_{name}", checkout


def grid_scenarios(dataset):
    from django.urls import reverse

    sale, _ = dataset.sale(5)
    path = reverse("sales:sale_detail", args=[dataset.store.pk, sale.pk])
    for size in (50, 250, 1000):
        dataset.grow_catalog(size)
        for label, params in (
            ("all", {}),
            ("search", {"q": "Producto 00"}),
            ("search_exact", {"q": "BASE-0020"}),
            ("category", {"category": dataset.categories[0].pk}),
            (
                "category_search",
                {"q": "Producto 00", "category": dataset.categories[0].pk},
            ),
            ("page_2", {"page": 2}),
        ):
            yield f"grid_{size}_{label}", lambda p=params: ("GET", path, p, True)


def measure(client, prepared):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from tests.performance.metrics import query_summary

    verify = operation_verifier(prepared)
    sql_ms = 0.0
    # CaptureQueriesContext slices Django's bounded (9000-entry) debug deque.
    # A long manual run must not let previous fixtures/samples fill that buffer.
    connection.queries_log.clear()

    def sql_timer(execute, sql, params, many, context):
        nonlocal sql_ms
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            sql_ms += (time.perf_counter() - start) * 1000

    with (
        CaptureQueriesContext(connection) as queries,
        connection.execute_wrapper(sql_timer),
    ):
        start = time.perf_counter()
        if callable(prepared):
            body = prepared()
            status, templates = 200, ["sales/partials/_cart_content.html"]
            method, endpoint, kind = (
                "RENDER",
                "get_sale_cart + render_to_string",
                "selector + template",
            )
        else:
            method, endpoint, params, partial = prepared
            response = getattr(client, method.lower())(
                endpoint, params, **({"HTTP_HX_REQUEST": "true"} if partial else {})
            )
            body, status = response.content, response.status_code
            templates = sorted({t.name for t in response.templates if t.name})
            kind = "HTMX" if partial else "full"
        duration = (time.perf_counter() - start) * 1000
    if status != 200:
        raise RuntimeError(f"Invalid benchmark response: {method} {endpoint}: {status}")
    if not queries.captured_queries:
        raise RuntimeError("Query capture was empty; refusing an invalid baseline")
    if verify is not None:
        verify()
    return {
        "server_ms": duration,
        "sql_ms": sql_ms,
        "response_bytes": len(body),
        "status": status,
        "queries": query_summary(queries.captured_queries),
        "templates": templates,
        "method": method,
        "endpoint": re.sub(r"/\d+", "/{id}", endpoint),
        "kind": kind,
    }


def operation_verifier(prepared):
    """Check persisted outcomes outside timing/query capture, including deletes.

    A 200 response alone cannot prove a service accepted the mutation.
    """
    if callable(prepared) or prepared[0] != "POST":
        return None
    from django.urls import resolve
    from apps.sales.models import Sale, SaleLine
    from decimal import Decimal

    _, path, data, _ = prepared
    match = resolve(path.split("?")[0])
    sale_pk = match.kwargs["sale_pk"]
    before_count = SaleLine.objects.filter(sale_id=sale_pk).count()

    def verify():
        sale = Sale.objects.get(pk=sale_pk)
        lines = list(sale.lines.all())
        endpoint = match.url_name
        if endpoint == "sale_header_update":
            expected_customer = int(data["customer"]) if data["customer"] else None
            assert sale.customer_id == expected_customer
            assert sale.document_type_requested == data["document_type_requested"]
        elif endpoint == "sale_line_add":
            assert len(lines) == before_count + 1
            assert any(line.product_id == data["product"] for line in lines)
        elif endpoint == "sale_line_delete":
            assert len(lines) == before_count - 1
            assert all(line.pk != match.kwargs["line_pk"] for line in lines)
        elif endpoint == "sale_checkout":
            from apps.payments.models import Payment
            from apps.billing.models import BillingDocument
            from apps.cash_register.models import CashMovement

            payments = list(Payment.objects.filter(sale=sale).select_related("method"))
            assert sale.status == "completed" and sale.pending_amount == Decimal("0.00")
            assert len(payments) == (2 if data["mode"] == "split" else 1)
            assert (
                sum((p.amount for p in payments), Decimal("0.00")) == sale.total_amount
            )
            assert (
                BillingDocument.objects.filter(sale=sale, status="issued").count() == 1
            )
            assert CashMovement.objects.filter(sale=sale).count() == sum(
                p.method.affects_cash_register for p in payments
            )
            for payment in payments:
                if payment.method.affects_cash_register:
                    assert (
                        CashMovement.objects.get(payment=payment).amount
                        == payment.amount
                    )
        else:
            line = next(line for line in lines if line.pk == match.kwargs["line_pk"])
            for field, value in data.items():
                assert getattr(line, field) == Decimal(value), (endpoint, field)
        subtotal = sum((line.gross_base_amount for line in lines), Decimal("0"))
        discount = sum((line.discount_amount for line in lines), Decimal("0"))
        tax = sum((line.tax_amount for line in lines), Decimal("0"))
        assert sale.subtotal_amount == subtotal
        assert sale.discount_amount == discount
        assert sale.tax_amount == tax
        assert sale.total_amount == subtotal - discount + tax
        assert sale.pending_amount == (
            Decimal("0.00") if endpoint == "sale_checkout" else sale.total_amount
        )

    return verify


def run_server(warmups, iterations):
    from django.test import Client
    from tests.performance.dataset import Dataset
    from tests.performance.metrics import distribution

    result = metadata()
    result.update(warmups=warmups, iterations=iterations, scenarios={})
    dataset = Dataset(50)
    client = Client()
    client.force_login(dataset.user)
    # Generator evaluation preserves catalogue sizes: do not materialize this list.
    for name, prepare in grid_scenarios(dataset):
        record_scenario(
            result, client, name, prepare, warmups, iterations, distribution
        )
    dataset = Dataset(250, label="workspace-baseline")
    client = Client()
    client.force_login(dataset.user)
    for name, prepare in scenarios(dataset):
        record_scenario(
            result, client, name, prepare, warmups, iterations, distribution
        )
    return result


def record_scenario(result, client, name, prepare, warmups, iterations, distribution):
    first = measure(client, prepare())
    for _ in range(warmups):
        measure(client, prepare())
    samples = [measure(client, prepare()) for _ in range(iterations)]
    result["scenarios"][name] = {
        "first_measured_request": first,
        "server_ms": distribution([s["server_ms"] for s in samples]),
        "sql_ms": distribution([s["sql_ms"] for s in samples]),
        "query_count": {
            "min": min(s["queries"]["count"] for s in samples),
            "max": max(s["queries"]["count"] for s in samples),
        },
        "response_bytes": {
            "min": min(s["response_bytes"] for s in samples),
            "max": max(s["response_bytes"] for s in samples),
        },
        "representative": samples[0],
        "samples": [
            {
                "server_ms": sample["server_ms"],
                "sql_ms": sample["sql_ms"],
                "query_count": sample["queries"]["count"],
                "response_bytes": sample["response_bytes"],
                "status": sample["status"],
            }
            for sample in samples
        ],
    }
    print(
        f"{name:36} queries={samples[0]['queries']['count']:3} bytes={len_range(samples)} p50={result['scenarios'][name]['server_ms']['p50']}ms"
    )


def len_range(samples):
    return f"{min(s['response_bytes'] for s in samples)}–{max(s['response_bytes'] for s in samples)}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--chromium", help="Optional local Chromium executable")
    args = parser.parse_args()
    if args.warmups < 0 or args.iterations < 1:
        parser.error("warmups >= 0 and iterations >= 1 required")
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings.test")
        != "config.settings.test"
    ):
        parser.error("Only config.settings.test is supported")
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    django.setup()
    from django.db import connection
    from django.test.runner import DiscoverRunner

    if connection.vendor != "postgresql":
        parser.error("The reference baseline requires PostgreSQL 16")
    connection.ensure_connection()
    if connection.pg_version // 10000 != 16:
        parser.error("The reference baseline requires PostgreSQL 16")
    runner = DiscoverRunner(interactive=False, verbosity=1)
    if args.browser:
        from tests.performance.browser import BrowserBaseline

        BrowserBaseline.output = args.output
        BrowserBaseline.warmups = args.warmups
        BrowserBaseline.iterations = args.iterations
        BrowserBaseline.chromium = args.chromium
        raise SystemExit(runner.run_tests(["tests.performance.browser"]))
    runner.setup_test_environment()
    old_config = None
    try:
        old_config = runner.setup_databases()
        start = time.perf_counter()
        result = run_server(args.warmups, args.iterations)
        result["profiling_seconds"] = round(time.perf_counter() - start, 3)
        result["scenario_count"] = len(result["scenarios"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    finally:
        if old_config is not None:
            runner.teardown_databases(old_config)
        runner.teardown_test_environment()


if __name__ == "__main__":
    main()
