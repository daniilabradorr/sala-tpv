"""Phase 3 C: real HTTP races and durable-boundary evidence on test PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
from threading import Barrier, Event
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.exceptions import ValidationError
from django.db import connections
from django.db.models import Sum
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from apps.billing.models import BillingDocument, BillingSeries
from apps.cash_register.models import CashMovement, CashSession
from apps.cash_register.services import CashRegisterService
from apps.inventory.models import InventoryItem, StockMovement
from apps.payments.models import Payment
from apps.sales import checkout
from apps.sales.models import Sale
from apps.sales.tests.factories import (
    create_sales_store,
    create_sales_user,
    create_store_access,
)
from apps.users.models import RoleChoices
from e2e.browser_optimistic_cart import JoinedLiveServerThread
from tests.performance.dataset import Dataset
from tests.performance.phase3_cases import second_session
from tests.performance.phase3_harness import payload, url


EVIDENCE = {}


def save_case(name, value):
    EVIDENCE[name] = value
    target = os.environ.get("TPV_INTEGRITY_OUTPUT")
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(EVIDENCE, indent=2) + "\n")


def state(dataset, sales):
    rows = []
    for sale in dict.fromkeys(sales):
        sale.refresh_from_db()
        payments = Payment.objects.filter(sale=sale, status="completed")
        documents = BillingDocument.objects.filter(sale=sale, status="issued")
        rows.append(
            {
                "sale": sale.status,
                "payment_status": sale.payment_status,
                "pending": str(sale.pending_amount),
                "confirmed_amount": str(
                    payments.aggregate(v=Sum("amount"))["v"] or Decimal("0")
                ),
                "payments": payments.count(),
                "documents": documents.count(),
                "numbers": list(documents.values_list("number", flat=True)),
                "stock_movements": StockMovement.objects.filter(sale=sale).count(),
                "cash_movements": CashMovement.objects.filter(sale=sale).count(),
            }
        )
    return {
        "sales": rows,
        "inventory": [
            str(v)
            for v in InventoryItem.objects.filter(
                business=dataset.business
            ).values_list("current_stock", flat=True)
        ],
        "sessions": [
            {
                "status": session.status,
                "expected": str(session.expected_cash_amount),
                "movement_sum": str(
                    CashMovement.objects.filter(cash_session=session).aggregate(
                        v=Sum("amount")
                    )["v"]
                    or Decimal("0")
                ),
            }
            for session in CashSession.objects.filter(business=dataset.business)
        ],
        "series_numbers": list(
            BillingSeries.objects.filter(
                business=dataset.business, document_type="F2"
            ).values_list("current_number", flat=True)
        ),
    }


class HTTPCheckout:
    def __init__(self, base, user, sale, test):
        client = Client()
        client.force_login(user)
        self.base, self.test = base, test
        self.cookie = f"{settings.SESSION_COOKIE_NAME}={client.cookies[settings.SESSION_COOKIE_NAME].value}"
        request = Request(
            base + url(sale), headers={"Cookie": self.cookie, "HX-Request": "true"}
        )
        with urlopen(request, timeout=10) as response:
            html = response.read().decode()
            cookies = SimpleCookie()
            for header in response.headers.get_all("Set-Cookie", []):
                cookies.load(header)
            self.cookie += "".join(
                f"; {name}={value.value}" for name, value in cookies.items()
            )
        self.csrf = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', html
        ).group(1)

    def post(self, sale, data, path=None):
        body = urlencode({**data, "csrfmiddlewaretoken": self.csrf}).encode()
        request = Request(
            self.base + (path or url(sale)),
            data=body,
            headers={
                "Cookie": self.cookie,
                "HX-Request": "true",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                response.read()
                return response.status
        except HTTPError as error:
            error.read()
            return error.code


@skipUnlessDBFeature("has_select_for_update")
class CheckoutHTTPIntegrityTests(StaticLiveServerTestCase):
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

    def verify(self, dataset, sales):
        result = state(dataset, sales)
        for sale, row in zip(dict.fromkeys(sales), result["sales"]):
            self.assertLessEqual(row["documents"], 1)
            self.assertLessEqual(row["stock_movements"], 1)
            self.assertLessEqual(Decimal(row["confirmed_amount"]), sale.total_amount)
            self.assertEqual(
                Decimal(row["pending"]),
                max(sale.total_amount - Decimal(row["confirmed_amount"]), Decimal("0")),
            )
        for session in result["sessions"]:
            self.assertEqual(
                Decimal(session["expected"]), Decimal(session["movement_sum"])
            )
        for item in InventoryItem.objects.filter(business=dataset.business):
            quantity = StockMovement.objects.filter(inventory_item=item).aggregate(
                v=Sum("quantity")
            )["v"] or Decimal("0")
            self.assertEqual(
                item.current_stock,
                getattr(dataset, "initial_stock", Decimal("1000")) - quantity,
            )
            self.assertEqual(item.available_stock, item.current_stock)
        for series in BillingSeries.objects.filter(business=dataset.business):
            self.assertEqual(
                series.current_number,
                BillingDocument.objects.filter(series=series, status="issued").count(),
            )
        for movement in CashMovement.objects.filter(
            business=dataset.business
        ).select_related("payment"):
            self.assertEqual(movement.amount, movement.payment.amount)
        return result

    def test_required_http_matrix(self):
        for case in range(1, 11):
            for repetition in range(3):
                d = Dataset(1, label=f"c-http-{case}-{repetition}")
                d.settings.allow_split_payments = True
                d.settings.allow_sale_without_stock = False
                d.settings.save()
                sale, _ = d.sale(1)
                other = d.sale(1)[0] if case in (4, 5) else sale
                if case in (4, 5):
                    second_session(d, other)
                user2 = create_sales_user(business=d.business)
                if case == 9:
                    user2.role = RoleChoices.CASHIER
                    user2.save(update_fields=["role"])
                    access = create_store_access(
                        business=d.business, user=user2, store=d.store
                    )
                clients = [
                    HTTPCheckout(self.live_server_url, user, target, self)
                    for user, target in ((d.user, sale), (user2, other))
                ]
                bodies = [
                    payload(d, target, "split" if case == 6 else "cash")
                    for target in (sale, other)
                ]
                if case == 1:
                    bodies[1] = dict(bodies[0])
                if case == 3:
                    Sale.objects.filter(pk=sale.pk).update(
                        cart_version=sale.cart_version + 1
                    )
                    bodies[1]["cart_version"] += 1
                if case == 4:
                    d.initial_stock = Decimal("1")
                    InventoryItem.objects.filter(product=d.products[0]).update(
                        current_stock=Decimal("1")
                    )
                if case == 9:
                    access.can_sell = False
                    access.save(update_fields=["can_sell"])
                if case == 6:
                    original = checkout.register_sale_payment
                    card = next(m.pk for m in d.methods if m.code == "card")

                    def fail_second(**kwargs):
                        if kwargs["method_id"] == card:
                            raise ValidationError("Synthetic second part interruption")
                        return original(**kwargs)

                    with patch.object(checkout, "register_sale_payment", fail_second):
                        first = clients[0].post(sale, bodies[0])
                    self.assertEqual(first, 422)
                    self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
                    bodies[1] = dict(bodies[0])
                if case == 7:
                    original = checkout.register_sale_payment

                    def close_then_pay(**kwargs):
                        CashRegisterService().close_cash_session(
                            business=d.business,
                            store_id=d.store.pk,
                            cash_register_id=d.register.pk,
                            cash_session_id=d.session.pk,
                            user=d.user,
                            counted_cash_amount=Decimal("0"),
                        )
                        return original(**kwargs)

                    with patch.object(
                        checkout, "register_sale_payment", close_then_pay
                    ):
                        outcomes = [clients[0].post(sale, bodies[0])]
                    outcomes.append(clients[1].post(sale, bodies[0]))
                    self.assertEqual(outcomes, [409, 422])
                elif case == 8:
                    first = clients[0].post(sale, bodies[0])
                    self.assertEqual(first, 200)
                    outcomes = self.race(
                        [
                            lambda: clients[0].post(sale, bodies[0]),
                            lambda: clients[1].post(sale, bodies[1]),
                        ]
                    )
                elif case == 10:
                    wrong_store = create_sales_store(business=d.business)
                    foreign = Dataset(1, label=f"c-http-foreign-{repetition}")
                    alien = dict(bodies[0], method=foreign.methods[0].pk)
                    wrong_path = reverse(
                        "sales:sale_checkout", args=[wrong_store.pk, sale.pk]
                    )
                    foreign_path = reverse(
                        "sales:sale_checkout",
                        args=[foreign.store.pk, foreign.sale(1)[0].pk],
                    )
                    outcomes = [
                        clients[0].post(sale, bodies[0], wrong_path),
                        clients[0].post(sale, bodies[0], foreign_path),
                        clients[0].post(sale, alien),
                    ]
                    self.assertEqual(outcomes, [404, 403, 422])
                else:
                    outcomes = self.race(
                        [
                            lambda: clients[0].post(sale, bodies[0]),
                            lambda: clients[1].post(other, bodies[1]),
                        ]
                    )
                result = self.verify(d, [sale, other])
                result["http"] = outcomes
                save_case(f"C{case:02d}-{repetition}", result)
                payments = Payment.objects.filter(
                    business=d.business, status="completed"
                ).count()
                if case in (1, 2, 3, 8, 9):
                    self.assertEqual(payments, 1)
                    self.assertEqual(
                        BillingDocument.objects.filter(sale=sale).count(), 1
                    )
                elif case == 4:
                    self.assertEqual(payments, 1)
                    self.assertEqual(
                        InventoryItem.objects.get(product=d.products[0]).current_stock,
                        0,
                    )
                    self.assertEqual(sorted(outcomes), [200, 422])
                elif case == 5:
                    self.assertEqual(payments, 2)
                    numbers = list(
                        BillingDocument.objects.filter(business=d.business).values_list(
                            "number", flat=True
                        )
                    )
                    self.assertEqual(sorted(numbers), [1, 2])
                elif case == 6:
                    self.assertEqual(payments, 2)
                    self.assertEqual(
                        BillingDocument.objects.filter(sale=sale).count(), 1
                    )
                else:
                    self.assertEqual(payments, 0)
                if case == 3:
                    self.assertEqual(sorted(outcomes), [200, 409])
                if case == 9:
                    self.assertEqual(sorted(outcomes), [200, 403])

    def test_cash_closure_boundaries_and_non_cash(self):
        for scenario in (
            "before_T1",
            "during_T1",
            "after_T1",
            "between_split",
            "cash_race",
            "card_race",
        ):
            d = Dataset(1, label="close-" + scenario.lower())
            d.settings.allow_split_payments = True
            d.settings.save()
            sale, _ = d.sale(1)
            client = HTTPCheckout(self.live_server_url, d.user, sale, self)
            body = payload(
                d,
                sale,
                "split"
                if scenario == "between_split"
                else "card"
                if scenario == "card_race"
                else "cash",
            )

            def close():
                try:
                    return CashRegisterService().close_cash_session(
                        business=d.business,
                        store_id=d.store.pk,
                        cash_register_id=d.register.pk,
                        cash_session_id=d.session.pk,
                        user=d.user,
                        counted_cash_amount=Decimal("0"),
                    )
                finally:
                    connections.close_all()

            if scenario == "before_T1":
                close()
                status = client.post(sale, body)
                self.assertEqual(status, 409)
                self.assertEqual(StockMovement.objects.filter(sale=sale).count(), 0)
            elif scenario in ("after_T1", "between_split"):
                original = checkout.register_sale_payment
                once = Event()

                def pay(**kwargs):
                    if scenario == "after_T1" and not once.is_set():
                        once.set()
                        close()
                    payment = original(**kwargs)
                    if scenario == "between_split" and not once.is_set():
                        once.set()
                        close()
                    return payment

                with patch.object(checkout, "register_sale_payment", pay):
                    status = client.post(sale, body)
                self.assertEqual(status, 409)
                self.assertEqual(
                    Payment.objects.filter(sale=sale).count(),
                    1 if scenario == "between_split" else 0,
                )
            elif scenario == "during_T1":
                entered, release, attempted, closed = Event(), Event(), Event(), Event()
                original = checkout.complete_sale
                from apps.sales import services

                original_stock = services.decrease_stock

                def hold_stock(**kwargs):
                    entered.set()
                    if not release.wait(8):
                        raise TimeoutError("release T1")
                    return original_stock(**kwargs)

                def closer():
                    attempted.set()
                    close()
                    closed.set()

                with (
                    patch.object(services, "decrease_stock", hold_stock),
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
                    status = future.result(15)
                    other.result(15)
                self.assertIn(status, (200, 409))
            else:
                result = self.race(
                    [lambda: client.post(sale, body), lambda: (close(), "closed")[1]]
                )
                status = result[0]
                self.assertIn(status, (200, 409))
            result = self.verify(d, [sale])
            result["http"] = status
            save_case("closure-" + scenario, result)
            self.assertEqual(CashSession.objects.get(pk=d.session.pk).status, "closed")
            if scenario == "card_race":
                self.assertEqual(CashMovement.objects.filter(sale=sale).count(), 0)


@skipUnlessDBFeature("has_select_for_update")
class CheckoutIdentityContractTests(TransactionTestCase):
    def test_cart_payment_and_document_identities(self):
        from apps.sales.cart import mutate, CartConflict
        from apps.sales.services import complete_sale
        from apps.payments.services import register_sale_payment
        from apps.billing.services import issue_sale_document

        d = Dataset(1, label="identities-c")
        sale, _ = d.sale(0)
        key = str(uuid4())
        data = {
            "key": key,
            "version": sale.cart_version,
            "kind": "add",
            "product": d.products[0].pk,
            "quantity": "1",
        }
        first = mutate(
            business=d.business, store=d.store, sale_id=sale.pk, user=d.user, data=data
        )
        second = mutate(
            business=d.business, store=d.store, sale_id=sale.pk, user=d.user, data=data
        )
        self.assertEqual(first["line"], second["line"])
        with self.assertRaises(CartConflict):
            mutate(
                business=d.business,
                store=d.store,
                sale_id=sale.pk,
                user=d.user,
                data={**data, "quantity": "2"},
            )
        sale.refresh_from_db()
        complete_sale(business=d.business, sale=sale, closed_by=d.user)
        sale.refresh_from_db()
        method = next(m for m in d.methods if m.code == "card")
        kwargs = dict(
            business=d.business,
            sale_id=sale.pk,
            method_id=method.pk,
            amount=sale.total_amount,
            user=d.user,
            idempotency_key=uuid4(),
            cash_session_id=d.session.pk,
        )
        payment = register_sale_payment(**kwargs)
        self.assertEqual(register_sale_payment(**kwargs).pk, payment.pk)
        with self.assertRaises(ValidationError):
            register_sale_payment(**{**kwargs, "amount": sale.total_amount / 2})
        with self.assertRaises(ValidationError):
            register_sale_payment(**{**kwargs, "idempotency_key": uuid4()})
        series = BillingSeries.objects.get(business=d.business, document_type="F2")
        billing = dict(
            business=d.business,
            sale_id=sale.pk,
            series_id=series.pk,
            issued_by=d.user,
            idempotency_key=uuid4(),
        )
        document = issue_sale_document(**billing)
        self.assertEqual(issue_sale_document(**billing).pk, document.pk)
        with self.assertRaises(ValidationError):
            issue_sale_document(**{**billing, "idempotency_key": uuid4()})
        other_series = BillingSeries.objects.create(
            business=d.business,
            store=d.store,
            name="Other",
            prefix="OTHER",
            document_type="F2",
            year=series.year,
        )
        with self.assertRaises(ValidationError):
            issue_sale_document(**{**billing, "series_id": other_series.pk})
        series.is_active = False
        series.save(update_fields=["is_active"])
        self.assertEqual(issue_sale_document(**billing).pk, document.pk)
        client = Client()
        client.force_login(d.user)
        http = payload(d, sale)
        http["series"] = series.pk
        http["billing_idempotency_key"] = str(document.idempotency_key)
        response = client.post(url(sale), http, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        method.is_active = False
        method.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            register_sale_payment(**kwargs)
        outsider = create_sales_user(business=d.business, role=RoleChoices.CASHIER)
        with self.assertRaises(ValidationError):
            register_sale_payment(**{**kwargs, "user": outsider})
        with self.assertRaises(ValidationError):
            issue_sale_document(**{**billing, "issued_by": outsider})
        save_case("idempotency-contracts", state(d, [sale]))
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
        self.assertEqual(StockMovement.objects.filter(sale=sale).count(), 1)
        self.assertEqual(BillingDocument.objects.filter(sale=sale).count(), 1)

    def test_existing_service_recovers_only_pending_part_in_valid_session(self):
        from apps.sales.services import complete_sale
        from apps.payments.services import register_sale_payment
        from apps.cash_register.models import CashRegister

        d = Dataset(1, label="pending-session-c")
        sale, _ = d.sale(1)
        complete_sale(business=d.business, sale=sale, closed_by=d.user)
        sale.refresh_from_db()
        cash = next(m for m in d.methods if m.code == "cash")
        half = (sale.total_amount / 2).quantize(Decimal(".01"))
        historical = dict(
            business=d.business,
            sale_id=sale.pk,
            method_id=cash.pk,
            amount=half,
            user=d.user,
            idempotency_key=uuid4(),
            cash_session_id=d.session.pk,
        )
        first = register_sale_payment(**historical)
        CashRegisterService().close_cash_session(
            business=d.business,
            store_id=d.store.pk,
            cash_register_id=d.register.pk,
            cash_session_id=d.session.pk,
            user=d.user,
            counted_cash_amount=half,
        )
        pending = {
            **historical,
            "idempotency_key": uuid4(),
            "amount": sale.total_amount - half,
        }
        with self.assertRaises(ValidationError):
            register_sale_payment(**pending)
        register = CashRegister.objects.create(
            business=d.business, store=d.store, name="Recovery", code="RECOVERY"
        )
        session = CashSession.objects.create(
            business=d.business, store=d.store, cash_register=register, opened_by=d.user
        )
        pending["cash_session_id"] = session.pk
        outsider = create_sales_user(business=d.business, role=RoleChoices.CASHIER)
        with self.assertRaises(ValidationError):
            register_sale_payment(**{**pending, "user": outsider})
        with self.assertRaises(ValidationError):
            register_sale_payment(**{**historical, "cash_session_id": session.pk})
        recovered = register_sale_payment(**pending)
        self.assertEqual(register_sale_payment(**pending).pk, recovered.pk)
        sale.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(sale.cash_session_id, d.session.pk)
        self.assertEqual(first.cash_session_id, d.session.pk)
        self.assertEqual(recovered.cash_session_id, session.pk)
        self.assertEqual(sale.payment_status, "paid")
        self.assertEqual(sale.pending_amount, 0)
        self.assertEqual(Payment.objects.filter(sale=sale).count(), 2)
        self.assertEqual(StockMovement.objects.filter(sale=sale).count(), 1)
        self.assertEqual(CashMovement.objects.filter(cash_session=d.session).count(), 1)
        self.assertEqual(CashMovement.objects.filter(cash_session=session).count(), 1)
        save_case("pending-session-service-recovery", state(d, [sale]))
