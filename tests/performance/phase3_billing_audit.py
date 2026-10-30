"""Block E: opt-in evidence on disposable PostgreSQL, never production."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import (
    connection,
    connections,
    transaction,
    DatabaseError,
    IntegrityError,
)
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from apps.audit.constants import AuditEventType
from apps.audit.models import AuditEvent
from apps.billing import services as billing
from apps.billing.models import (
    BillingDocument,
    BillingDocumentLine,
    BillingSeries,
    BillingTaxBreakdown,
)
from apps.cash_register.models import CashRegister
from apps.payments.services import register_sale_payment
from apps.sales.services import complete_sale
from apps.sales.tests.factories import (
    create_sale_line,
    create_sales_store,
    create_sales_user,
)
from apps.sales.tests_postgres_recovery import state as economic_state
from tests.performance.dataset import Dataset

CASES = {}


def record(name, value):
    CASES[name] = value
    target = os.getenv("TPV_BILLING_E_OUTPUT")
    if target:
        Path(target).write_text(json.dumps(CASES, indent=2, default=str) + "\n")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def document_rows(document):
    return {
        "document": BillingDocument.objects.filter(pk=document.pk).values().get(),
        "lines": list(document.lines.order_by("pk").values()),
        "taxes": list(document.tax_breakdowns.order_by("pk").values()),
    }


def snapshot(d, sales):
    docs = BillingDocument.objects.filter(business=d.business).order_by("pk")
    return {
        **economic_state(d, sales),
        "fiscal_documents": [
            {
                "type": doc.document_type,
                "status": doc.status,
                "series": doc.series_text,
                "number": doc.number,
                "operation_date": str(doc.operation_date),
                "subtotal": str(doc.subtotal_amount),
                "discount": str(doc.discount_amount),
                "tax": str(doc.tax_amount),
                "total": str(doc.total_amount),
                "lines": list(
                    doc.lines.values(
                        "quantity",
                        "unit_base_price",
                        "tax_rate",
                        "taxable_base_amount",
                        "tax_amount",
                        "line_total",
                    )
                ),
                "breakdowns": list(
                    doc.tax_breakdowns.values(
                        "tax_rate", "taxable_base_amount", "tax_amount"
                    )
                ),
                "snapshot_digest": digest(document_rows(doc)),
            }
            for doc in docs
        ],
        "all_series": list(
            BillingSeries.objects.filter(business=d.business)
            .order_by("document_type", "pk")
            .values("document_type", "year", "current_number", "is_active")
        ),
        "billing_audit_events": AuditEvent.objects.filter(
            business=d.business, event_type=AuditEventType.BILLING_DOCUMENT_ISSUED
        ).count(),
    }


def fixture(label, lines=1, invoice=False):
    d = Dataset(max(lines, 1), label="e-" + label)
    sale, _ = d.sale(
        lines,
        document="invoice" if invoice else "ticket",
        customer=d.customers[0] if invoice else None,
    )
    return d, sale


def paid(d, sale):
    complete_sale(business=d.business, sale=sale, closed_by=d.user)
    sale.refresh_from_db()
    register_sale_payment(
        business=d.business,
        sale_id=sale.pk,
        method_id=d.methods[1].pk,
        amount=sale.total_amount,
        user=d.user,
        idempotency_key=uuid4(),
        cash_session_id=d.session.pk,
    )
    sale.refresh_from_db()


def series_for(d, sale):
    kind = "F1" if sale.document_type_requested == "invoice" else "F2"
    return BillingSeries.objects.get(
        business=d.business, document_type=kind, prefix=f"BASE-{kind}"
    )


def issue(d, sale, series=None, key=None, user=None):
    return billing.issue_sale_document(
        business=d.business,
        sale_id=sale.pk,
        series_id=(series or series_for(d, sale)).pk,
        issued_by=user or d.user,
        idempotency_key=key or uuid4(),
    )


@skipUnlessDBFeature("has_select_for_update")
class BillingIntegrityAudit(TransactionTestCase):
    def test_f1_f2_sizes_and_independent_rounding_vectors(self):
        for invoice in (False, True):
            for size in (1, 20, 50):
                d, sale = fixture(f"amounts-{invoice}-{size}", size, invoice)
                paid(d, sale)
                doc = issue(d, sale)
                expected_base = Decimal("10.00") * size
                # Dataset alternates21%/10% with default21%; explicit fixture oracle.
                expected_tax = sum(
                    (
                        Decimal("1.00") if i % 3 and i % 2 else Decimal("2.10")
                        for i in range(size)
                    ),
                    Decimal("0"),
                )
                self.assertEqual(doc.subtotal_amount, expected_base)
                self.assertEqual(doc.tax_amount, expected_tax)
                self.assertEqual(doc.total_amount, expected_base + expected_tax)
                self.assertEqual(
                    sum(doc.tax_breakdowns.values_list("tax_amount", flat=True)),
                    expected_tax,
                )
                self.assertEqual(doc.lines.count(), size)
                record(f"E-amounts-{doc.document_type}-{size}", snapshot(d, [sale]))
        vectors = [
            # price, quantity, discount, rate, expected gross/base/tax/total
            ("0.05", "1.000", "0", "10", "0.05", "0.05", "0.01", "0.06"),
            ("0.05", "1.000", "0", "10", "0.05", "0.05", "0.01", "0.06"),
            ("1.01", "0.500", "0", "21", "0.51", "0.51", "0.11", "0.62"),
            ("10.25", "1.125", "0.03", "21", "11.53", "11.50", "2.42", "13.92"),
            ("3.33", "0.333", "0.01", "10", "1.11", "1.10", "0.11", "1.21"),
            ("1.00", "1.000", "0.25", "0", "1.00", "0.75", "0.00", "0.75"),
            ("2.00", "1.000", "0", "4", "2.00", "2.00", "0.08", "2.08"),
        ]
        d, sale = fixture("rounding", 0, True)
        for price, quantity, discount, rate, *_ in vectors:
            create_sale_line(
                business=d.business,
                sale=sale,
                product=d.products[0],
                unit_base_price=price,
                quantity=quantity,
                discount_amount=discount,
                tax_rate=rate,
            )
        paid(d, sale)
        doc = issue(d, sale)
        for line, vector in zip(doc.lines.order_by("pk"), vectors, strict=True):
            expected = tuple(map(Decimal, vector[4:]))
            self.assertEqual(
                (
                    line.gross_base_amount,
                    line.taxable_base_amount,
                    line.tax_amount,
                    line.line_total,
                ),
                expected,
            )
        ten = doc.tax_breakdowns.get(tax_rate=10)
        self.assertEqual(
            ten.tax_amount, Decimal(".13")
        )  # sum per-line .01+.01+.11, not re-tax aggregate
        self.assertEqual(doc.total_amount, Decimal("18.70"))
        self.assertEqual(doc.subtotal_amount, Decimal("16.25"))
        self.assertEqual(doc.discount_amount, Decimal("0.29"))
        self.assertEqual(doc.tax_amount, Decimal("2.74"))
        observed_groups = {
            str(group.tax_rate): (str(group.taxable_base_amount), str(group.tax_amount))
            for group in doc.tax_breakdowns.all()
        }
        self.assertEqual(
            observed_groups,
            {
                "0.00": ("0.75", "0.00"),
                "4.00": ("2.00", "0.08"),
                "10.00": ("1.20", "0.13"),
                "21.00": ("12.01", "2.53"),
            },
        )
        record("E-rounding-oracle", {"vectors": vectors, **snapshot(d, [sale])})

    def test_numbering_two_users_concurrent_and_uuid_contract(self):
        for repeat in range(3):
            for mode in (
                "different_sales",
                "same_sale_different_keys",
                "same_sale_same_key",
            ):
                d, first = fixture(f"number-{repeat}-{mode}")
                second = d.sale(1)[0] if mode == "different_sales" else first
                paid(d, first)
                if second != first:
                    paid(d, second)
                other_user = create_sales_user(business=d.business)
                first_key = uuid4()
                second_key = first_key if mode == "same_sale_same_key" else uuid4()
                barrier = Barrier(2)

                def run(index):
                    connections.close_all()
                    try:
                        barrier.wait(timeout=10)
                        doc = issue(
                            d,
                            (first, second)[index],
                            key=(first_key, second_key)[index],
                            user=(d.user, other_user)[index],
                        )
                        return ("issued", doc.number)
                    except ValidationError as error:
                        return (type(error).__name__, None)
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(run, (0, 1)))
                count = 2 if mode == "different_sales" else 1
                self.assertEqual(
                    BillingDocument.objects.filter(business=d.business).count(), count
                )
                self.assertEqual(series_for(d, first).current_number, count)
                self.assertEqual(
                    sum(r[0] == "issued" for r in results),
                    1 if mode == "same_sale_different_keys" else 2,
                )
                self.assertEqual(
                    set(
                        BillingDocument.objects.filter(business=d.business).values_list(
                            "number", flat=True
                        )
                    ),
                    set(range(1, count + 1)),
                )
                record(
                    f"N01-N02-N03-{repeat}-{mode}",
                    {"outcomes": results, **snapshot(d, [first, second])},
                )
        d, sale = fixture("uuid-compatibility")
        paid(d, sale)
        key = uuid4()
        doc = issue(d, sale, key=key)
        alternate = BillingSeries.objects.create(
            business=d.business,
            store=d.store,
            name="Alternate",
            prefix="ALTERNATE",
            document_type="F2",
            year=timezone.localdate().year,
        )
        with self.assertRaises(billing.BillingIdempotencyConflict):
            issue(d, sale, alternate, key)
        with self.assertRaises(billing.BillingAlreadyIssued):
            issue(d, sale, key=uuid4())
        self.assertEqual(issue(d, sale, key=key).pk, doc.pk)
        record("N04-N05-uuid", snapshot(d, [sale]))

    def test_fault_boundaries_roll_back_document_children_number_and_audit(self):
        for name, target, after in [
            ("snapshots", "_issuer_snapshot", False),
            ("lines", "_create_lines_and_breakdowns", True),
            ("fiscal_validation", "_validate_supported_line", False),
            ("series_lock", "_lock_series", False),
            ("after_number", "_issue_draft", True),
            ("audit", "log_event", True),
        ]:
            d, sale = fixture("fault-" + name)
            paid(d, sale)
            key = uuid4()
            original = getattr(billing, target)

            def failing(*args, **kwargs):
                if after:
                    original(*args, **kwargs)
                raise RuntimeError("Synthetic Billing boundary: " + name)

            with (
                patch.object(billing, target, failing),
                self.assertRaises(RuntimeError),
            ):
                issue(d, sale, key=key)
            before = snapshot(d, [sale])
            self.assertEqual(before["sales"][0]["payments"], 1)
            self.assertEqual(before["sales"][0]["stock_movements"], 1)
            self.assertEqual(before["fiscal_documents"], [])
            self.assertEqual(before["billing_audit_events"], 0)
            self.assertEqual(series_for(d, sale).current_number, 0)
            self.assertFalse(
                BillingDocumentLine.objects.filter(business=d.business).exists()
            )
            self.assertFalse(
                BillingTaxBreakdown.objects.filter(business=d.business).exists()
            )
            issue(d, sale, key=key)
            self.assertEqual(series_for(d, sale).current_number, 1)
            record(
                "N06-N07-fault-" + name,
                {"after_failure": before, "after_retry": snapshot(d, [sale])},
            )

    def test_series_tenant_store_register_inactive_and_year_boundary(self):
        d, sale = fixture("series-scope")
        paid(d, sale)
        other = Dataset(1, label="e-other-business")
        other_store = create_sales_store(business=d.business)
        register = CashRegister.objects.create(
            business=d.business, store=d.store, name="Other", code="OTHER"
        )
        invalid = [series_for(other, other.sale(0)[0])]
        for label, values in [
            ("store", {"store": other_store}),
            ("register", {"cash_register": register}),
            ("type", {"document_type": "F1"}),
            ("inactive", {"is_active": False}),
            ("old_year", {"year": timezone.localdate().year - 1}),
        ]:
            invalid.append(
                BillingSeries.objects.create(
                    **(
                        {
                            "business": d.business,
                            "store": d.store,
                            "name": label,
                            "prefix": label.upper(),
                            "document_type": "F2",
                            "year": timezone.localdate().year,
                        }
                        | values
                    )
                )
            )
        for series in invalid:
            with self.assertRaises(ValidationError):
                issue(d, sale, series)
        self.assertFalse(BillingDocument.objects.filter(business=d.business).exists())
        next_year = timezone.localdate().year + 1
        moment = datetime(next_year, 1, 1, 12, tzinfo=datetime_timezone.utc)
        new_series = BillingSeries.objects.create(
            business=d.business,
            store=d.store,
            name="New year",
            prefix="NEW",
            document_type="F2",
            year=next_year,
        )
        with patch.object(billing.timezone, "now", return_value=moment):
            with self.assertRaises(ValidationError):
                issue(d, sale)
            doc = issue(d, sale, new_series)
        self.assertEqual(doc.number, 1)
        self.assertEqual(doc.series.year, next_year)
        self.assertIn(str(next_year), doc.series_text)
        self.assertEqual(
            doc.operation_date, timezone.localtime(sale.completed_at).date()
        )
        # Compatible replay is historical, even after deactivation/year change.
        new_series.is_active = False
        new_series.save(update_fields=["is_active"])
        self.assertEqual(issue(d, sale, new_series, doc.idempotency_key).pk, doc.pk)
        other_sale = other.sale(1)[0]
        paid(other, other_sale)
        other_document = issue(other, other_sale)
        self.assertEqual(other_document.number, 1)
        record("N09-N11-N12-series", snapshot(d, [sale]))
        record(
            "N10-independent-businesses",
            {"first": snapshot(d, [sale]), "second": snapshot(other, [other_sale])},
        )

    def test_snapshot_changes_and_inactive_tax_after_sale_do_not_rewrite_history(self):
        d, sale = fixture("snapshots", 1, True)
        paid(d, sale)
        # After sale, before issue: fiscal lines must not consult current catalog.
        old_line = sale.lines.get()
        product = d.products[0]
        product.name = "Current catalog changed"
        product.base_price = Decimal("99.99")
        product.tax = d.taxes[1]
        product.save()
        d.taxes[0].is_active = False
        d.taxes[0].save(update_fields=["is_active"])
        doc = issue(d, sale)
        self.assertEqual(doc.lines.get().product_name, old_line.product_name)
        self.assertEqual(doc.lines.get().tax_rate, old_line.tax_rate)
        original = digest(document_rows(doc))
        customer = d.customers[0]
        customer.name = customer.legal_name = "Current customer changed"
        customer.tax_identifier = "CURRENT-CUSTOMER"
        customer.save()
        profile = d.business.profile
        profile.legal_name = "Current issuer changed"
        profile.tax_identifier = "CURRENT-ISSUER"
        profile.save()
        client = Client()
        client.force_login(d.user)
        path = reverse("billing:document_print", args=[d.store.pk, doc.pk])
        for _ in range(3):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            self.assertIn(doc.issuer_legal_name, html)
            self.assertNotIn("Current issuer changed", html)
            self.assertNotIn("Current customer changed", html)
            self.assertNotIn("Current catalog changed", html)
        self.assertEqual(digest(document_rows(doc)), original)
        record(
            "E07-E15-historical-print",
            {"reprints": 3, "snapshot_unchanged": True, **snapshot(d, [sale])},
        )

    def test_immutability_model_guards_and_database_bypass_limits(self):
        d, sale = fixture("immutability")
        paid(d, sale)
        doc = issue(d, sale)
        original = digest(document_rows(doc))
        for item in (doc, doc.lines.get(), doc.tax_breakdowns.get()):
            with self.assertRaises(ValidationError):
                item.save()
            with self.assertRaises(ValidationError):
                item.delete()
        probes = {}
        with transaction.atomic():
            BillingDocument.objects.filter(pk=doc.pk).update(issuer_legal_name="Bypass")
            probes["queryset_header_update_bypasses_guard"] = (
                BillingDocument.objects.get(pk=doc.pk).issuer_legal_name == "Bypass"
            )
            transaction.set_rollback(True)
        with transaction.atomic():
            line = doc.lines.get()
            line.product_name = "Bulk bypass"
            BillingDocumentLine.objects.bulk_update([line], ["product_name"])
            probes["bulk_update_child_bypasses_guard"] = (
                doc.lines.get().product_name == "Bulk bypass"
            )
            transaction.set_rollback(True)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE billing_billingdocument SET description = %s WHERE id = %s",
                    ["SQL bypass", doc.pk],
                )
            probes["direct_sql_update_bypasses_guard"] = (
                BillingDocument.objects.get(pk=doc.pk).description == "SQL bypass"
            )
            transaction.set_rollback(True)
        with transaction.atomic():
            doc.lines.all().delete()
            probes["queryset_child_delete_bypasses_guard"] = not doc.lines.exists()
            transaction.set_rollback(True)
        with transaction.atomic():
            duplicate = BillingDocument.objects.get(pk=doc.pk)
            duplicate.pk = None
            duplicate.number = 2
            duplicate.idempotency_key = uuid4()
            BillingDocument.objects.bulk_create([duplicate])
            probes["no_database_unique_initial_document_per_sale"] = (
                BillingDocument.objects.filter(sale=sale).count() == 2
            )
            transaction.set_rollback(True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            duplicate = BillingDocument.objects.get(pk=doc.pk)
            duplicate.pk = None
            duplicate.idempotency_key = uuid4()
            BillingDocument.objects.bulk_create([duplicate])
        self.assertTrue(all(probes.values()))
        self.assertEqual(digest(document_rows(doc)), original)
        record(
            "E08-database-boundary-observed",
            {
                "model_save_delete_blocked": True,
                "duplicate_series_number_rejected_by_database": True,
                "isolated_rollback_probes": probes,
                "risk_not_fixed": True,
                **snapshot(d, [sale]),
            },
        )

    def test_terminate_only_own_emitter_connection_rolls_back_t3(self):
        d, sale = fixture("terminated-connection")
        paid(d, sale)
        entered, release = Event(), Event()
        backend = {}
        key = uuid4()
        original = billing._issue_draft

        def held(**kwargs):
            result = original(**kwargs)
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid(), current_database()")
                backend["pid"], backend["database"] = cursor.fetchone()
            entered.set()
            if not release.wait(8):
                raise TimeoutError("Synthetic release timed out")
            return result

        def worker():
            connections.close_all()
            try:
                with patch.object(billing, "_issue_draft", held):
                    issue(d, sale, key=key)
                return "unexpected_success"
            except DatabaseError:
                return "database_error"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue(backend["database"].startswith("test_tpv_diag_"))
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_terminate_backend(%s)", [backend["pid"]])
                    self.assertTrue(cursor.fetchone()[0])
            finally:
                release.set()
            self.assertEqual(future.result(timeout=8), "database_error")
        self.assertFalse(BillingDocument.objects.filter(sale=sale).exists())
        self.assertEqual(series_for(d, sale).current_number, 0)
        before = snapshot(d, [sale])
        self.assertEqual(before["sales"][0]["payments"], 1)
        issue(d, sale, key=key)
        record(
            "E12-own-connection-termination",
            {"after_disconnect": before, "after_retry": snapshot(d, [sale])},
        )

    def test_p01_fiscal_dependencies_reject_then_recover_without_new_payment(self):
        for problem in ("inactive_series", "incomplete_profile", "incomplete_customer"):
            d, sale = fixture("p01-" + problem, 1, True)
            paid(d, sale)
            series = series_for(d, sale)
            key = uuid4()
            d.methods[1].is_active = False
            d.methods[1].save(update_fields=["is_active"])
            if problem == "inactive_series":
                series.is_active = False
                series.save(update_fields=["is_active"])
            elif problem == "incomplete_profile":
                type(d.business.profile).objects.filter(business=d.business).update(
                    legal_name=""
                )
            else:
                type(d.customers[0]).objects.filter(pk=d.customers[0].pk).update(
                    tax_identifier=""
                )
            with self.assertRaises(ValidationError):
                issue(d, sale, series, key)
            before = snapshot(d, [sale])
            self.assertEqual(before["sales"][0]["payments"], 1)
            self.assertEqual(before["sales"][0]["documents"], 0)
            self.assertEqual(before["sales"][0]["stock_movements"], 1)
            if problem == "inactive_series":
                series.is_active = True
                series.save(update_fields=["is_active"])
            elif problem == "incomplete_profile":
                type(d.business.profile).objects.filter(business=d.business).update(
                    legal_name="Repaired synthetic issuer"
                )
            else:
                type(d.customers[0]).objects.filter(pk=d.customers[0].pk).update(
                    tax_identifier="REPAIRED-SYNTHETIC"
                )
            document = issue(d, sale, series, key)
            self.assertEqual(document.idempotency_key, key)
            self.assertEqual(sale.payments.count(), 1)
            record(
                "E10-P01-" + problem,
                {"before_repair": before, "after_repair": snapshot(d, [sale])},
            )

    def test_real_postgresql_series_lock_timeout_rolls_back_t3(self):
        d, sale = fixture("real-series-lock-timeout")
        paid(d, sale)
        series = series_for(d, sale)
        reached = Event()
        original = billing._lock_series

        def observed(**kwargs):
            reached.set()
            return original(**kwargs)

        def worker():
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '200ms'")
                with patch.object(billing, "_lock_series", observed):
                    issue(d, sale)
                return "unexpected_success"
            except DatabaseError as error:
                return getattr(error.__cause__, "sqlstate", None)
            finally:
                connections.close_all()

        with transaction.atomic():
            BillingSeries.objects.select_for_update().get(pk=series.pk)
            with ThreadPoolExecutor(max_workers=1) as pool:
                outcome = pool.submit(worker).result(timeout=8)
        self.assertTrue(reached.is_set())
        self.assertEqual(outcome, "55P03")
        self.assertFalse(BillingDocument.objects.filter(sale=sale).exists())
        self.assertEqual(series_for(d, sale).current_number, 0)
        record(
            "E12-real-series-lock-timeout",
            {"sqlstate": outcome, "lock_series_reached": True, **snapshot(d, [sale])},
        )

    def test_non_eur_configuration_is_rejected_after_e_p01(self):
        # The original E02 evidence remains in block-e-measurements.json.
        # E-P01 now authorizes correcting that observed configuration defect.
        from django.forms.models import model_to_dict
        from apps.business_config.forms import BusinessProfileForm
        from apps.business_config.services import update_business_profile

        d, sale = fixture("currency-boundary", 1, True)
        profile = d.business.profile
        form = BusinessProfileForm(
            data={**model_to_dict(profile), "currency_code": "USD"}, instance=profile
        )
        self.assertFalse(form.is_valid())
        self.assertIn("currency_code", form.errors)
        with self.assertRaisesMessage(ValidationError, "Netxodo solo admite EUR"):
            update_business_profile(
                business=d.business, updated_by=d.user, currency_code="USD"
            )
        profile.refresh_from_db()
        self.assertEqual(profile.currency_code, "EUR")
        paid(d, sale)
        document = issue(d, sale)
        client = Client()
        client.force_login(d.user)
        response = client.get(
            reverse("billing:document_print", args=[d.store.pk, document.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("12,10 €", response.content.decode())
        record("E-P01-currency-configuration-rejected", snapshot(d, [sale]))

    def test_direct_billing_http_current_contract_can_issue_before_payment(self):
        d, sale = fixture("direct-unpaid-issue")
        complete_sale(business=d.business, sale=sale, closed_by=d.user)
        sale.refresh_from_db()
        self.assertEqual(sale.payment_status, "unpaid")
        self.assertEqual(sale.payments.count(), 0)
        client = Client()
        client.force_login(d.user)
        response = client.post(
            reverse("billing:issue_sale_document", args=[d.store.pk, sale.pk]),
            {
                "series": series_for(d, sale).pk,
                "idempotency_key": str(uuid4()),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            BillingDocument.objects.filter(sale=sale, status="issued").count(), 1
        )
        sale.refresh_from_db()
        self.assertEqual(sale.payment_status, "unpaid")
        self.assertEqual(sale.payments.count(), 0)
        record(
            "E01-direct-billing-unpaid-contract",
            {
                "http": response.status_code,
                "direct_billing_requires_payment": False,
                "checkout_paid_gate_unchanged": True,
                "credit_policy_requires_explicit_product_acceptance": True,
                **snapshot(d, [sale]),
            },
        )


@skipUnlessDBFeature("has_select_for_update")
class BillingPerformanceAudit(TransactionTestCase):
    def test_warm_billing_and_print_costs(self):
        import re
        from contextlib import ExitStack
        from time import perf_counter

        for invoice in (False, True):
            for size in (1, 20, 50):
                d = Dataset(size, label=f"e-perf-{invoice}-{size}")
                results = []
                for sample in range(6):
                    sale = d.sale(
                        size,
                        document="invoice" if invoice else "ticket",
                        customer=d.customers[0] if invoice else None,
                    )[0]
                    paid(d, sale)
                    measured_series = series_for(d, sale)
                    measured_key = uuid4()
                    spans, sql = {}, {}

                    def measured(name, original):
                        def wrapper(*args, **kwargs):
                            start = perf_counter()
                            try:
                                return original(*args, **kwargs)
                            finally:
                                stats = spans.setdefault(name, {"calls": 0, "ms": 0})
                                stats["calls"] += 1
                                stats["ms"] += (perf_counter() - start) * 1000

                        return wrapper

                    def query(execute, statement, params, many, context):
                        operation = statement.lstrip().split(None, 1)[0].upper()
                        table = re.search(
                            r'(?:FROM|INTO|UPDATE)\s+"([a-z_]+)"', statement, re.I
                        )
                        key = (
                            operation
                            + ":"
                            + (table.group(1) if table else "transaction_or_expression")
                        )
                        start = perf_counter()
                        try:
                            return execute(statement, params, many, context)
                        finally:
                            item = sql.setdefault(key, {"count": 0, "ms": 0})
                            item["count"] += 1
                            item["ms"] += (perf_counter() - start) * 1000

                    with ExitStack() as stack:
                        stack.enter_context(connection.execute_wrapper(query))
                        for function in (
                            "_sale_line_snapshots",
                            "_issuer_snapshot",
                            "_recipient_snapshot",
                            "_save_draft",
                            "_create_lines_and_breakdowns",
                            "_lock_series",
                            "_issue_draft",
                            "log_event",
                        ):
                            stack.enter_context(
                                patch.object(
                                    billing,
                                    function,
                                    measured(function, getattr(billing, function)),
                                )
                            )
                        for model in (
                            BillingDocument,
                            BillingDocumentLine,
                            BillingTaxBreakdown,
                            BillingSeries,
                        ):
                            stack.enter_context(
                                patch.object(
                                    model,
                                    "full_clean",
                                    measured(
                                        model.__name__ + ".full_clean", model.full_clean
                                    ),
                                )
                            )
                        start = perf_counter()
                        document = billing.issue_sale_document(
                            business=d.business,
                            sale_id=sale.pk,
                            series_id=measured_series.pk,
                            issued_by=d.user,
                            idempotency_key=measured_key,
                        )
                        t3 = (perf_counter() - start) * 1000
                    client = Client()
                    client.force_login(d.user)
                    start = perf_counter()
                    response = client.get(
                        reverse(
                            "billing:document_print", args=[d.store.pk, document.pk]
                        )
                    )
                    print_ms = (perf_counter() - start) * 1000
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(document.lines.count(), size)
                    self.assertEqual(sale.payments.count(), 1)
                    self.assertEqual(
                        BillingDocument.objects.filter(sale=sale).count(), 1
                    )
                    self.assertEqual(sale.stock_movements.count(), size)
                    result = {
                        "t3_ms": t3,
                        "print_client_get_ms": print_ms,
                        "sql": sql,
                        "spans_inclusive": spans,
                        "state": snapshot(d, [sale])["sales"][0],
                    }
                    if sample:
                        results.append(result)
                record(
                    f"E20-perf-{'F1' if invoice else 'F2'}-{size}",
                    {
                        "warmups": 1,
                        "samples": results,
                        "n": len(results),
                        "instrumentation": "in-process opt-in timing and SQL aggregate hook; no SQL/parameters retained; inclusive spans not additive; Client GET not Chromium HTTP",
                    },
                )

    def test_print_read_render_and_query_costs(self):
        from time import perf_counter
        from apps.billing import views

        for invoice in (False, True):
            for size in (1, 20, 50):
                d, sale = fixture(f"print-cost-{invoice}-{size}", size, invoice)
                paid(d, sale)
                document = issue(d, sale)
                before = digest(document_rows(document))
                client = Client()
                client.force_login(d.user)
                url = reverse("billing:document_print", args=[d.store.pk, document.pk])
                results = []
                for sample in range(6):
                    observed = {"sql_count": 0, "render_ms": 0, "render_calls": 0}
                    original = views.render

                    def render(*args, **kwargs):
                        start = perf_counter()
                        try:
                            return original(*args, **kwargs)
                        finally:
                            observed["render_ms"] += (perf_counter() - start) * 1000
                            observed["render_calls"] += 1

                    def query(execute, statement, params, many, context):
                        observed["sql_count"] += 1
                        return execute(statement, params, many, context)

                    with (
                        patch.object(views, "render", render),
                        connection.execute_wrapper(query),
                    ):
                        start = perf_counter()
                        response = client.get(url)
                        observed["client_get_ms"] = (perf_counter() - start) * 1000
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(observed["render_calls"], 1)
                    if sample:
                        results.append(observed)
                self.assertEqual(digest(document_rows(document)), before)
                self.assertEqual(series_for(d, sale).current_number, 1)
                self.assertEqual(sale.payments.count(), 1)
                record(
                    f"E20-print-{'F1' if invoice else 'F2'}-{size}",
                    {
                        "warmups": 1,
                        "samples": results,
                        "no_document_mutation": True,
                        "state": snapshot(d, [sale]),
                    },
                )
