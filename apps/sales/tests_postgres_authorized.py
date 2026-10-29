"""Controlled P01/P02 HTTP races on disposable PostgreSQL only."""

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

    def test_p02_same_and_distinct_keys_never_exceed_persisted_balance(self):
        from apps.sales.services import complete_sale
        from apps.payments.services import register_sale_payment
        from apps.cash_register.services import CashRegisterService
        from apps.cash_register.models import CashRegister, CashSession, CashMovement

        for distinct in (False, True):
            for repetition in range(3):
                d = Dataset(1, label=f"p02-race-{distinct}-{repetition}")
                d.settings.allow_split_payments = True
                d.settings.save()
                sale, _ = d.sale(1)
                complete_sale(business=d.business, sale=sale, closed_by=d.user)
                sale.refresh_from_db()
                half = (sale.total_amount / 2).quantize(Decimal(".01"))
                first = register_sale_payment(
                    business=d.business,
                    sale_id=sale.pk,
                    method_id=d.methods[0].pk,
                    amount=half,
                    user=d.user,
                    idempotency_key=uuid4(),
                    cash_session_id=d.session.pk,
                )
                CashRegisterService().close_cash_session(
                    business=d.business,
                    store_id=d.store.pk,
                    cash_register_id=d.register.pk,
                    cash_session_id=d.session.pk,
                    user=d.user,
                    counted_cash_amount=half,
                )
                register = CashRegister.objects.create(
                    business=d.business, store=d.store, name="Recovery", code="RECOVERY"
                )
                session = CashSession.objects.create(
                    business=d.business,
                    store=d.store,
                    cash_register=register,
                    opened_by=d.user,
                )
                sale.refresh_from_db()
                body = {
                    **payload(d, sale, "cash"),
                    "amount": str(half),
                    "recovery_cash_session": session.pk,
                    "recovery_confirm": "on",
                }
                other = (
                    {**body, "payment_idempotency_key": str(uuid4())}
                    if distinct
                    else dict(body)
                )
                clients = [
                    HTTPCheckout(self.live_server_url, user, sale, self)
                    for user in (d.user, create_sales_user(business=d.business))
                ]
                statuses = self.race(
                    [
                        lambda: clients[0].post(sale, body),
                        lambda: clients[1].post(sale, other),
                    ]
                )
                self.assertTrue(all(code in (200, 409) for code in statuses))
                self.assertIn(200, statuses)
                first.refresh_from_db()
                sale.refresh_from_db()
                self.assertEqual(first.cash_session_id, d.session.pk)
                self.assertEqual(sale.cash_session_id, d.session.pk)
                self.assertEqual(sale.pending_amount, 0)
                self.assertEqual(Payment.objects.filter(sale=sale).count(), 2)
                self.assertEqual(BillingDocument.objects.filter(sale=sale).count(), 1)
                self.assertEqual(StockMovement.objects.filter(sale=sale).count(), 1)
                self.assertEqual(
                    CashMovement.objects.filter(cash_session=d.session).count(), 1
                )
                self.assertEqual(
                    CashMovement.objects.filter(cash_session=session).count(), 1
                )
                doc = BillingDocument.objects.get(sale=sale)
                self.assertEqual(doc.cash_session_id, d.session.pk)
                result = state(d, [sale])
                self.assertEqual(
                    Decimal(result["sales"][0]["confirmed_amount"]), sale.total_amount
                )
                self.assertEqual(result["sales"][0]["numbers"], [1])
                self.assertEqual(result["inventory"], ["999.000"])
                result["http"] = statuses
                save_case(f"P02-{distinct}-{repetition}", result)

    def test_p02_destination_closes_before_or_during_t2_cash_and_card(self):
        from threading import Event
        from apps.sales.services import complete_sale
        from apps.cash_register.services import CashRegisterService
        from apps.cash_register.models import CashRegister, CashSession, CashMovement
        from apps.payments import services as payment_services
        from apps.sales import views

        for method in ("cash", "card"):
            for position in ("before", "during"):
                d = Dataset(1, label=f"p02-close-{method}-{position}")
                sale, _ = d.sale(1)
                complete_sale(business=d.business, sale=sale, closed_by=d.user)
                sale.refresh_from_db()

                def close(session, register):
                    try:
                        CashRegisterService().close_cash_session(
                            business=d.business,
                            store_id=d.store.pk,
                            cash_register_id=register.pk,
                            cash_session_id=session.pk,
                            user=d.user,
                            counted_cash_amount=Decimal("0"),
                        )
                    finally:
                        connections.close_all()

                close(d.session, d.register)
                register = CashRegister.objects.create(
                    business=d.business, store=d.store, name="Recovery", code="RECOVERY"
                )
                session = CashSession.objects.create(
                    business=d.business,
                    store=d.store,
                    cash_register=register,
                    opened_by=d.user,
                )
                body = {
                    **payload(d, sale, method),
                    "amount": str(sale.pending_amount),
                    "recovery_cash_session": session.pk,
                    "recovery_confirm": "on",
                }
                client = HTTPCheckout(self.live_server_url, d.user, sale, self)
                if position == "before":
                    original = views.recover_pending_checkout_payment

                    def close_first(**kwargs):
                        close(session, register)
                        return original(**kwargs)

                    with patch.object(
                        views, "recover_pending_checkout_payment", close_first
                    ):
                        status = client.post(sale, body)
                    self.assertEqual(status, 422)
                    self.assertEqual(Payment.objects.filter(sale=sale).count(), 0)
                else:
                    entered, release, attempted, closed = (
                        Event(),
                        Event(),
                        Event(),
                        Event(),
                    )
                    original = payment_services._get_sale_payment_balance

                    def hold(locked):
                        # Called by Payments after destination session lock.
                        entered.set()
                        if not release.wait(8):
                            raise TimeoutError("release T2")
                        return original(locked)

                    def closer():
                        attempted.set()
                        close(session, register)
                        closed.set()

                    with (
                        patch.object(
                            payment_services, "_get_sale_payment_balance", hold
                        ),
                        ThreadPoolExecutor(max_workers=2) as pool,
                    ):
                        future = pool.submit(client.post, sale, body)
                        try:
                            self.assertTrue(entered.wait(5))
                            other = pool.submit(closer)
                            self.assertTrue(attempted.wait(5))
                            self.assertFalse(closed.wait(0.1))
                        finally:
                            release.set()
                        status = future.result(20)
                        other.result(20)
                    self.assertEqual(status, 200)
                    self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
                self.assertEqual(
                    CashMovement.objects.filter(cash_session=d.session).count(), 0
                )
                self.assertEqual(
                    CashSession.objects.get(pk=session.pk).status, "closed"
                )
                self.assertEqual(StockMovement.objects.filter(sale=sale).count(), 1)
                result = state(d, [sale])
                result["http"] = status
                save_case(f"P02-close-{method}-{position}", result)
