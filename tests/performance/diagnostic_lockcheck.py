"""Controlled Sale lock in a disposable PostgreSQL test DB; no timing claim."""

from concurrent.futures import ThreadPoolExecutor
import time
from threading import Event
from uuid import uuid4

from django.db import connection, connections, transaction
from django.test import Client, TransactionTestCase

from tests.performance.dataset import Dataset
from tests.performance.diagnostic import recent
from tests.performance.diagnostic_locks import SQL
from tests.performance.diagnostic_matrix import (
    checkout_data,
    guard,
    path,
    save_result,
    verify,
)


class ControlledLock(TransactionTestCase):
    def test_sale_lock_is_correlated(self):
        guard()
        if connection.vendor != "postgresql":
            self.skipTest("Real locks require PostgreSQL")
        from apps.sales.models import Sale

        dataset = Dataset(1, label="diagnostic-lock")
        sale, _ = dataset.sale(1)
        client = Client()
        client.force_login(dataset.user)
        data = checkout_data(dataset)
        trace_id = str(uuid4())
        locked = Event()
        release = Event()
        worker_ready = Event()
        worker_pid = []

        def hold_lock():
            try:
                with transaction.atomic():
                    Sale.objects.select_for_update().get(pk=sale.pk)
                    locked.set()
                    if not release.wait(10):
                        raise TimeoutError("Diagnostic lock was not released")
            finally:
                connections.close_all()

        def checkout():
            try:
                connection.ensure_connection()
                worker_pid.append(connection.connection.info.backend_pid)
                worker_ready.set()
                response = client.post(
                    path("sale_checkout", sale),
                    data,
                    HTTP_HX_REQUEST="true",
                    HTTP_X_TPV_TRACE=trace_id,
                )
                return response.status_code
            finally:
                connections.close_all()

        observed = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            locker = executor.submit(hold_lock)
            try:
                self.assertTrue(locked.wait(5))
                request = executor.submit(checkout)
                self.assertTrue(worker_ready.wait(5))
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute(SQL, (worker_pid,))
                        for pid, kind, event, age, blockers in cursor.fetchall():
                            if kind == "Lock" and blockers:
                                observed.append(
                                    {
                                        "pid": pid,
                                        "wait_type": kind,
                                        "wait_event": event,
                                        "blocking_pids": blockers,
                                    }
                                )
                    if observed:
                        break
                    Event().wait(0.02)
                self.assertTrue(
                    observed, "Expected a directly observed PostgreSQL lock"
                )
            finally:
                release.set()
            locker.result(timeout=5)
            self.assertEqual(request.result(timeout=10), 200)
        trace = recent(trace_id)
        self.assertIn(worker_pid[0], trace["driver_backend_pids"])
        verify(self, sale, "checkout_post", 1)
        save_result(
            "controlled-lock.json",
            {},
            observed=observed,
            trace=trace,
            interpretation="Artificial lock; observed wait, not exact lock duration",
        )
