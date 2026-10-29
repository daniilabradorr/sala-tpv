"""P01 Billing recovery HTTP races on disposable PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import Client, skipUnlessDBFeature

from apps.billing.models import BillingDocument
from apps.inventory.models import StockMovement
from apps.payments.models import Payment, PaymentMethod
from apps.sales.tests.factories import create_sales_user
from apps.sales.tests_postgres_recovery import HTTPCheckout, state, save_case
from e2e.browser_optimistic_cart import JoinedLiveServerThread
from tests.performance.dataset import Dataset
from tests.performance.phase3_harness import payload, url


@skipUnlessDBFeature("has_select_for_update")
class AuthorizedRecoveryHTTPTests(StaticLiveServerTestCase):
    server_thread_class = JoinedLiveServerThread

    def setUp(self):
        cls = type(self)
        if not cls.server_thread.is_alive():
            cls.server_thread = cls._create_server_thread(
                cls.server_thread.connections_override
            )
            cls.server_thread.daemon = True
            cls.server_thread.start()
            cls.server_thread.is_ready.wait()
            if cls.server_thread.error:
                raise cls.server_thread.error

    def _post_teardown(self):
        self.server_thread.terminate()
        super()._post_teardown()

    def race(self, calls):
        barrier = Barrier(len(calls))

        def run(call):
            try:
                barrier.wait(5)
                return call()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return [f.result(25) for f in [pool.submit(run, call) for call in calls]]

    def test_p01_two_authorized_users_same_and_distinct_billing_keys(self):
        for distinct in (False, True):
            for repetition in range(3):
                d = Dataset(1, label=f"p01-race-{distinct}-{repetition}")
                sale, _ = d.sale(1)
                body = payload(d, sale)
                client = Client()
                client.force_login(d.user)
                with patch(
                    "apps.sales.checkout.issue_sale_document",
                    side_effect=ValidationError("Synthetic Billing failure"),
                ):
                    client.post(url(sale), body)
                PaymentMethod.objects.filter(business=d.business).update(
                    is_active=False
                )
                users = [d.user, create_sales_user(business=d.business)]
                clients = [
                    HTTPCheckout(self.live_server_url, user, sale, self)
                    for user in users
                ]
                other = (
                    {**body, "billing_idempotency_key": str(uuid4())}
                    if distinct
                    else dict(body)
                )
                with patch("apps.sales.checkout.register_sale_payment") as payment:
                    statuses = self.race(
                        [
                            lambda: clients[0].post(sale, body),
                            lambda: clients[1].post(sale, other),
                        ]
                    )
                payment.assert_not_called()
                self.assertEqual(
                    sorted(statuses), [200, 409] if distinct else [200, 200]
                )
                self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
                self.assertEqual(BillingDocument.objects.filter(sale=sale).count(), 1)
                self.assertEqual(StockMovement.objects.filter(sale=sale).count(), 1)
                result = state(d, [sale])
                self.assertEqual(
                    Decimal(result["sales"][0]["confirmed_amount"]), sale.total_amount
                )
                self.assertEqual(result["sales"][0]["numbers"], [1])
                self.assertEqual(result["inventory"], ["999.000"])
                result["http"] = statuses
                save_case(f"P01-{distinct}-{repetition}", result)
