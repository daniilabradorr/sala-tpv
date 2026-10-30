"""Controlled contention and economic boundaries on a dedicated test cluster."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event
from time import monotonic, perf_counter, sleep
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.test import Client, TransactionTestCase

from tests.performance.dataset import Dataset
from tests.performance.diagnostic import recent
from tests.performance.diagnostic_locks import SQL
from tests.performance.phase3_harness import economic, guard, payload, save, url


def client_for(user):
    client = Client(raise_request_exception=False)
    client.force_login(user)
    return client


def post(client, sale, data):
    start = perf_counter()
    response = client.post(url(sale), data, HTTP_HX_REQUEST="true")
    return {
        "ms": (perf_counter() - start) * 1000,
        "status": response.status_code,
        "trace": recent(response.get("X-TPV-Trace")),
    }, response


def second_session(dataset, sale):
    from apps.cash_register.models import CashRegister, CashSession
    from apps.sales.models import Sale

    register = CashRegister.objects.create(
        business=dataset.business, store=dataset.store, name="Second", code="SECOND"
    )
    session = CashSession.objects.create(
        business=dataset.business,
        store=dataset.store,
        cash_register=register,
        opened_by=dataset.user,
    )
    Sale.objects.filter(pk=sale.pk).update(cash_register=register, cash_session=session)
    sale.refresh_from_db()
    return session


class BoundaryCases(TransactionTestCase):
    def test_failures_and_h01(self):
        guard()
        from apps.sales import checkout, views
        from apps.inventory import services as inventory
        from apps.payments import services as payments
        from apps.billing import services as billing
        from apps.billing.models import BillingSeries

        records = {}
        cases = [
            ("F01_before_T1", checkout, "_preflight", "before"),
            ("F02_inventory", checkout, "complete_sale", "inventory"),
            ("F03_after_T1", checkout, "register_sale_payment", "before"),
            ("F04_during_payment", payments, "register_payment_cash_movement", "after"),
            ("F05_after_T2", checkout, "issue_sale_document", "before"),
            ("F06_during_billing", billing, "_issue_draft", "after"),
            ("F07_after_T3_render", views.SaleCheckoutView, "_render", "render"),
        ]
        for name, module, attribute, moment in cases:
            dataset = Dataset(1, label=name.lower())
            sale, _ = dataset.sale(1)
            client = client_for(dataset.user)
            data = payload(dataset, sale, "cash")
            before_number = BillingSeries.objects.get(
                business=dataset.business, document_type="F2"
            ).current_number
            original = getattr(module, attribute)
            if moment == "inventory":
                original_stock = inventory._create_stock_movement

                def fail_stock(*args, **kwargs):
                    original_stock(*args, **kwargs)
                    raise ValidationError("Synthetic inventory failure")

                context = patch.object(inventory, "_create_stock_movement", fail_stock)
            else:

                def failure(*args, _original=original, _moment=moment, **kwargs):
                    if _moment == "render":
                        raise RuntimeError("Synthetic post-commit render failure")
                    if _moment == "after":
                        _original(*args, **kwargs)
                    raise ValidationError("Synthetic boundary failure")

                context = patch.object(module, attribute, failure)
            with context:
                row, _ = post(client, sale, data)
            row["economic_after_error"] = economic(sale)
            failed = row["economic_after_error"]
            expected_payments = 1 if name.startswith(("F05", "F06", "F07")) else 0
            self.assertEqual(failed["payments"], expected_payments)
            self.assertEqual(failed["documents"], 1 if name.startswith("F07") else 0)
            self.assertEqual(
                failed["stock_movements"], 0 if name.startswith(("F01", "F02")) else 1
            )
            number = BillingSeries.objects.get(
                business=dataset.business, document_type="F2"
            ).current_number
            self.assertEqual(number - before_number, failed["documents"])
            recovery, _ = post(client, sale, data)
            row["recovery"] = recovery
            row["economic_after_retry"] = economic(sale)
            self.assertEqual(row["economic_after_retry"]["payments"], 1)
            self.assertEqual(row["economic_after_retry"]["documents"], 1)
            self.assertEqual(row["economic_after_retry"]["stock_movements"], 1)
            records[name] = row
        # H01 retained from A, now on PostgreSQL and without TestCase outer atomic.
        dataset = Dataset(1, label="h01-postgres")
        sale, _ = dataset.sale(1)
        client = client_for(dataset.user)
        data = payload(dataset, sale)
        with patch.object(
            checkout,
            "issue_sale_document",
            side_effect=ValidationError("Synthetic billing error"),
        ):
            first, _ = post(client, sale, data)
        method = next(m for m in dataset.methods if m.code == "card")
        method.is_active = False
        method.save()
        retry, response = post(client, sale, data)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(b"field-error", response.content)
        self.assertEqual(economic(sale)["documents"], 0)
        retry["economic"] = economic(sale)
        fresh = client.get(url(sale), HTTP_HX_REQUEST="true")
        data.update(
            method="",
            payment_idempotency_key=str(
                fresh.context["form"]["payment_idempotency_key"].value()
            ),
            billing_idempotency_key=str(
                fresh.context["form"]["billing_idempotency_key"].value()
            ),
        )
        recovered, _ = post(client, sale, data)
        self.assertEqual(economic(sale)["payments"], 1)
        self.assertEqual(economic(sale)["documents"], 1)
        records["H01"] = {
            "first": first,
            "retry_inactive": retry,
            "fresh_get_and_emit": recovered,
            "economic_final": economic(sale),
        }
        save("boundaries.json", records)

    def test_controlled_locks(self):
        guard()
        from apps.sales.models import Sale
        from apps.cash_register.models import CashSession
        from apps.inventory.models import InventoryItem
        from apps.billing.models import BillingSeries

        results = {}
        for name, model in [
            ("L01_Sale", Sale),
            ("L02_CashSession", CashSession),
            ("L03_InventoryItem", InventoryItem),
            ("L04_BillingSeries", BillingSeries),
        ]:
            dataset = Dataset(1, label=name.lower())
            sale, _ = dataset.sale(1)
            client = client_for(dataset.user)
            data = payload(dataset, sale, "cash")
            obj = {
                "L01_Sale": sale,
                "L02_CashSession": dataset.session,
                "L03_InventoryItem": InventoryItem.objects.get(
                    product=dataset.products[0]
                ),
                "L04_BillingSeries": BillingSeries.objects.get(
                    business=dataset.business, document_type="F2"
                ),
            }[name]
            release, acquired, ready = Event(), Event(), Event()
            pids = []

            def hold():
                try:
                    with transaction.atomic():
                        model.objects.select_for_update().get(pk=obj.pk)
                        acquired.set()
                        if not release.wait(10):
                            raise TimeoutError("locker release")
                finally:
                    connections.close_all()

            def checkout():
                try:
                    connection.ensure_connection()
                    pids.append(connection.connection.info.backend_pid)
                    ready.set()
                    return post(client, sale, data)[0]
                finally:
                    connections.close_all()

            observed = []
            with ThreadPoolExecutor(max_workers=2) as executor:
                holder = executor.submit(hold)
                try:
                    self.assertTrue(acquired.wait(5))
                    worker = executor.submit(checkout)
                    self.assertTrue(ready.wait(5))
                    deadline = monotonic() + 5
                    while monotonic() < deadline:
                        with connection.cursor() as cursor:
                            cursor.execute(SQL, (pids,))
                            for pid, kind, event, age, blockers in cursor.fetchall():
                                if kind == "Lock" and blockers:
                                    observed.append(
                                        {
                                            "pid": pid,
                                            "wait_event_type": kind,
                                            "wait_event": event,
                                            "blockers": blockers,
                                            "transaction_age_ms": float(age)
                                            if age
                                            else None,
                                        }
                                    )
                        if observed:
                            break
                        sleep(0.02)
                    self.assertTrue(observed, name)
                    start_hold = perf_counter()
                    # Inject a known wait only after PostgreSQL confirms a blocker.
                    sleep(0.25)
                    held_ms = (perf_counter() - start_hold) * 1000
                finally:
                    release.set()
                holder.result(5)
                result = worker.result(15)
            self.assertEqual(result["status"], 200)
            result.update(
                observed=observed,
                artificial_hold_after_observed_ms=held_ms,
                economic=economic(sale),
            )
            self.assertEqual(result["economic"]["payments"], 1)
            self.assertEqual(result["economic"]["documents"], 1)
            self.assertEqual(result["economic"]["stock_movements"], 1)
            results[name] = result
        save("controlled-locks.json", results)

    def test_contention(self):
        guard()
        from apps.cash_register.services import CashRegisterService
        from apps.inventory.models import InventoryItem
        from apps.billing.models import BillingSeries
        from apps.payments.models import Payment
        from apps.sales.tests.factories import create_sales_user
        from django.db.models import Sum
        from apps.cash_register.models import CashMovement

        results = {}
        for case in range(1, 8):
            rows = []
            for repetition in range(3):
                dataset = Dataset(1, label=f"c{case}-r{repetition}")
                dataset.settings.allow_split_payments = True
                dataset.settings.allow_sale_without_stock = False
                dataset.settings.save()
                sale1, _ = dataset.sale(1)
                sale2 = sale1 if case in (1, 5) else dataset.sale(1)[0]
                if case in (2, 3, 7):
                    second_session(dataset, sale2)
                if case == 2:
                    InventoryItem.objects.filter(product=dataset.products[0]).update(
                        current_stock=Decimal("1")
                    )
                user2 = create_sales_user(business=dataset.business)
                clients = [client_for(dataset.user), client_for(user2)]
                mode = "split" if case == 5 else "cash"
                bodies = [payload(dataset, sale, mode) for sale in (sale1, sale2)]
                if case == 7:
                    first_series = BillingSeries.objects.get(
                        business=dataset.business, document_type="F2"
                    )
                    second_series = BillingSeries.objects.create(
                        business=dataset.business,
                        store=dataset.store,
                        cash_register=sale2.cash_register,
                        name="Second F2",
                        prefix="SECOND-F2",
                        year=first_series.year,
                        document_type="F2",
                    )
                    bodies[0]["series"], bodies[1]["series"] = (
                        first_series.pk,
                        second_series.pk,
                    )
                barrier, finished = Barrier(3), Event()
                pids, observed = [], []

                def worker(index):
                    try:
                        connection.ensure_connection()
                        pids.append(connection.connection.info.backend_pid)
                        barrier.wait(5)
                        if case == 4 and index == 1:
                            start = perf_counter()
                            CashRegisterService().close_cash_session(
                                business=dataset.business,
                                store_id=dataset.store.pk,
                                cash_register_id=dataset.register.pk,
                                cash_session_id=dataset.session.pk,
                                user=dataset.user,
                                counted_cash_amount=Decimal("0"),
                            )
                            return {
                                "status": "closed",
                                "ms": (perf_counter() - start) * 1000,
                                "trace": None,
                            }
                        return post(
                            clients[index], (sale1, sale2)[index], bodies[index]
                        )[0]
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(worker, i) for i in range(2)]
                    barrier.wait(5)
                    while not all(f.done() for f in futures):
                        with connection.cursor() as cursor:
                            cursor.execute(SQL, (pids,))
                            for pid, kind, event, age, blockers in cursor.fetchall():
                                if kind == "Lock" and blockers:
                                    observed.append(
                                        {
                                            "pid": pid,
                                            "wait_event": event,
                                            "transaction_age_ms": float(age)
                                            if age
                                            else None,
                                            "blocking_pids": blockers,
                                        }
                                    )
                        finished.wait(0.02)
                    outcomes = [f.result(5) for f in futures]
                states = [economic(sale) for sale in dict.fromkeys((sale1, sale2))]
                rows.append(
                    {
                        "outcomes": outcomes,
                        "observed_locks": observed,
                        "economic": states,
                    }
                )
                results[f"C{case:02d}"] = rows
                save("contention.json", results)
                for state in states:
                    self.assertLessEqual(state["documents"], 1)
                    self.assertLessEqual(state["payments"], 2 if case == 5 else 1)
                    self.assertLessEqual(state["stock_movements"], 1)
                if case in (1, 5):
                    self.assertEqual(states[0]["payments"], 2 if case == 5 else 1)
                    self.assertTrue(states[0]["pending_zero"])
                if case == 2:
                    self.assertEqual(
                        Payment.objects.filter(business=dataset.business).count(), 1
                    )
                    self.assertEqual(
                        InventoryItem.objects.get(
                            product=dataset.products[0]
                        ).current_stock,
                        0,
                    )
                if case in (3, 6, 7):
                    self.assertTrue(all(state["pending_zero"] for state in states))
                    self.assertTrue(all(state["documents"] == 1 for state in states))
                for session in dataset.business.cash_sessions.all():
                    cash_total = CashMovement.objects.filter(
                        cash_session=session
                    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
                    self.assertEqual(session.expected_cash_amount, cash_total)
            results[f"C{case:02d}"] = rows
            save("contention.json", results)


class CollectionOverhead(TransactionTestCase):
    def test_paired_on_off(self):
        guard()
        from django.test import override_settings
        from tests.performance.phase3_harness import summary

        dataset = Dataset(50, label="phase3-overhead")
        clients = {}
        for enabled in (False, True):
            with override_settings(TPV_DIAGNOSTICS=enabled):
                client = client_for(dataset.user)
                client.handler.load_middleware()
                clients[enabled] = client
        rows = {}
        for size in (1, 20, 50):
            pairs = []
            for iteration in range(8):
                sales = {enabled: dataset.sale(size)[0] for enabled in (False, True)}
                bodies = {
                    enabled: payload(dataset, sales[enabled])
                    for enabled in (False, True)
                }
                elapsed = {}
                for enabled in (False, True) if iteration % 2 else (True, False):
                    row, response = post(
                        clients[enabled], sales[enabled], bodies[enabled]
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual("X-TPV-Trace" in response, enabled)
                    elapsed[enabled] = row["ms"]
                if iteration >= 2:
                    pairs.append(
                        {
                            "on_ms": elapsed[True],
                            "off_ms": elapsed[False],
                            "delta_ms": elapsed[True] - elapsed[False],
                            "delta_percent": 100
                            * (elapsed[True] - elapsed[False])
                            / elapsed[False],
                        }
                    )
            rows[str(size)] = {
                "samples": pairs,
                "delta_percent": summary([r["delta_percent"] for r in pairs]),
                "delta_ms": summary([r["delta_ms"] for r in pairs]),
            }
        save("overhead.json", rows)


class BetweenTransactions(TransactionTestCase):
    def test_cash_close_exactly_after_t1(self):
        guard()
        from apps.sales import checkout
        from apps.cash_register.services import CashRegisterService
        from apps.cash_register.models import CashSession
        from apps.payments.services import register_sale_payment

        dataset = Dataset(1, label="close-between-t1-t2")
        sale, _ = dataset.sale(1)
        data = payload(dataset, sale, "cash")
        client = client_for(dataset.user)
        original = checkout.register_sale_payment

        def close_then_pay(**kwargs):
            CashRegisterService().close_cash_session(
                business=dataset.business,
                store_id=dataset.store.pk,
                cash_register_id=dataset.register.pk,
                cash_session_id=dataset.session.pk,
                user=dataset.user,
                counted_cash_amount=Decimal("0"),
            )
            return original(**kwargs)

        with patch.object(checkout, "register_sale_payment", close_then_pay):
            first, _ = post(client, sale, data)
        state = economic(sale)
        self.assertEqual(first["status"], 409)
        self.assertEqual(state["sale_status"], "completed")
        self.assertEqual(state["payments"], 0)
        self.assertEqual(state["stock_movements"], 1)
        retry, _ = post(client, sale, data)
        self.assertEqual(retry["status"], 409)
        # Existing Payments API can select a fresh open session without editing
        # the completed Sale; this is an alternate existing recovery path.
        fresh_session = CashSession.objects.create(
            business=dataset.business,
            store=dataset.store,
            cash_register=dataset.register,
            opened_by=dataset.user,
        )
        sale.refresh_from_db()
        register_sale_payment(
            business=dataset.business,
            sale_id=sale.pk,
            method_id=data["method"],
            amount=sale.pending_amount,
            user=dataset.user,
            idempotency_key=data["payment_idempotency_key"],
            cash_session_id=fresh_session.pk,
        )
        final, _ = post(client, sale, data)
        self.assertEqual(final["status"], 200)
        self.assertEqual(economic(sale)["payments"], 1)
        self.assertEqual(economic(sale)["documents"], 1)
        save(
            "between-transactions.json",
            {
                "first": first,
                "economic_after_close": state,
                "same_checkout_retry": retry,
                "existing_payment_api_then_checkout": final,
                "economic_final": economic(sale),
            },
        )


class FiscalModelCosts(TransactionTestCase):
    def test_model_validation_and_save_costs(self):
        guard()
        from collections import defaultdict
        from functools import wraps
        from django.db.models import Model
        from apps.billing.models import (
            BillingDocument,
            BillingDocumentLine,
            BillingTaxBreakdown,
        )
        from tests.performance.phase3_harness import summary

        dataset = Dataset(50, label="phase3-fiscal-models")
        client = client_for(dataset.user)
        totals = {}
        for size in (1, 20, 50):
            rows = []
            for iteration in range(6):
                sale, _ = dataset.sale(size)
                timings = defaultdict(lambda: {"calls": 0, "ms": 0.0})
                original_clean = Model.full_clean

                def clean(obj, *args, **kwargs):
                    start = perf_counter()
                    try:
                        return original_clean(obj, *args, **kwargs)
                    finally:
                        label = obj._meta.label_lower
                        if label.startswith("billing."):
                            timings[label + ".full_clean"]["calls"] += 1
                            timings[label + ".full_clean"]["ms"] += (
                                perf_counter() - start
                            ) * 1000

                def wrap_save(original, label):
                    @wraps(original)
                    def save_model(*args, **kwargs):
                        before = sum(
                            v["ms"]
                            for key, v in timings.items()
                            if key.endswith(".full_clean")
                        )
                        start = perf_counter()
                        try:
                            return original(*args, **kwargs)
                        finally:
                            elapsed = (perf_counter() - start) * 1000
                            clean_delta = (
                                sum(
                                    v["ms"]
                                    for key, v in timings.items()
                                    if key.endswith(".full_clean")
                                )
                                - before
                            )
                            timings[label + ".save_inclusive"]["calls"] += 1
                            timings[label + ".save_inclusive"]["ms"] += elapsed
                            timings[label + ".save_residual_after_full_clean"][
                                "calls"
                            ] += 1
                            timings[label + ".save_residual_after_full_clean"][
                                "ms"
                            ] += elapsed - clean_delta

                    return save_model

                with (
                    patch.object(Model, "full_clean", clean),
                    patch.object(
                        BillingDocument,
                        "save",
                        wrap_save(BillingDocument.save, "billing.billingdocument"),
                    ),
                    patch.object(
                        BillingDocumentLine,
                        "save",
                        wrap_save(
                            BillingDocumentLine.save, "billing.billingdocumentline"
                        ),
                    ),
                    patch.object(
                        BillingTaxBreakdown,
                        "save",
                        wrap_save(
                            BillingTaxBreakdown.save, "billing.billingtaxbreakdown"
                        ),
                    ),
                ):
                    row, response = post(client, sale, payload(dataset, sale))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(economic(sale)["documents"], 1)
                row["fiscal_models"] = dict(timings)
                if iteration:
                    rows.append(row)
            totals[str(size)] = {
                "samples": rows,
                "warmup": 1,
                "model_summary": {
                    key: {
                        "calls": summary(
                            [
                                r["fiscal_models"].get(key, {}).get("calls", 0)
                                for r in rows
                            ]
                        ),
                        "ms": summary(
                            [r["fiscal_models"].get(key, {}).get("ms", 0) for r in rows]
                        ),
                    }
                    for key in rows[0]["fiscal_models"]
                },
            }
        save("fiscal-models.json", totals)
