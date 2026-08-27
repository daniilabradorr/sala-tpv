import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import (
    BillingDocument,
    BillingDocumentLine,
    BillingDocumentRelation,
    BillingDocumentRelationTypeChoices,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingSeries,
    BillingTaxBreakdown,
)
from apps.billing.services import (
    BILLING_LINE_SNAPSHOT_FIELDS,
    BILLING_TAX_SNAPSHOT_FIELDS,
    BillingAlreadyIssued,
    BillingIdempotencyConflict,
    BillingServiceError,
    issue_sale_document,
    substitute_simplified_document,
)
from apps.business_config.models import BusinessProfile
from apps.sales.models import RequestedDocumentTypeChoices, Sale, SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sales_business,
    create_sales_customer,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
    create_store_access,
)
from apps.users.models import RoleChoices


class BillingEmissionServiceTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.profile = BusinessProfile.objects.get(business=self.business)
        for field, value in {
            "legal_name": "Netxodo SL",
            "tax_identifier": "B12345678",
            "phone": "600000000",
            "email": "billing@example.test",
            "address_line_1": "Calle Mayor 1",
            "address_line_2": "2.º B",
            "postal_code": "28001",
            "city": "Madrid",
            "province": "Madrid",
            "country_code": "ES",
        }.items():
            setattr(self.profile, field, value)
        self.profile.save()
        tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(business=self.business, tax=tax)

    def make_sale(self, requested=RequestedDocumentTypeChoices.TICKET, customer=None):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            customer=customer,
            status=SaleStatusChoices.COMPLETED,
            document_type_requested=requested,
        )
        create_sale_line(business=self.business, sale=sale, product=self.product)
        return sale

    def make_series(
        self,
        document_type,
        current_number=0,
        prefix="TCK-CEN",
        year=None,
        business=None,
        store=None,
        is_active=True,
        cash_register=None,
    ):
        return BillingSeries.objects.create(
            business=business or self.business,
            store=self.store if store is None else store,
            name=f"Serie {document_type}",
            document_type=document_type,
            prefix=prefix,
            year=year or timezone.localdate().year,
            current_number=current_number,
            is_active=is_active,
            cash_register=cash_register,
        )

    def issue(self, sale, series, key=None):
        return issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=series.pk,
            issued_by=self.user,
            idempotency_key=key or uuid.uuid4(),
        )

    def test_ticket_issues_complete_snapshotted_f2(self):
        sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2, current_number=25)
        document = self.issue(sale, series)
        self.assertEqual(document.document_type, BillingDocumentTypeChoices.F2)
        self.assertEqual(document.status, BillingDocumentStatusChoices.ISSUED)
        self.assertEqual(document.number, 26)
        self.assertEqual(document.series_text, f"TCK-CEN-{series.year}")
        self.assertEqual(
            document.description, f"Venta #{sale.pk} · Factura simplificada"
        )
        self.assertEqual(
            document.operation_date, timezone.localtime(sale.completed_at).date()
        )
        self.assertEqual(document.issuer_legal_name, "Netxodo SL")
        self.assertEqual(document.lines.get().product_name, self.product.name)
        self.assertEqual(
            document.tax_breakdowns.get().taxable_base_amount, Decimal("10.00")
        )
        series.refresh_from_db()
        self.assertEqual(series.current_number, 26)

    def test_none_maps_to_f2_and_invoice_maps_to_f1_customer_snapshot(self):
        none_sale = self.make_sale(RequestedDocumentTypeChoices.NONE)
        self.assertEqual(
            self.issue(
                none_sale, self.make_series(BillingDocumentTypeChoices.F2)
            ).document_type,
            BillingDocumentTypeChoices.F2,
        )
        customer = create_sales_customer(
            business=self.business,
            legal_name="Cliente Fiscal SL",
            tax_identifier="B87654321",
        )
        invoice = self.make_sale(RequestedDocumentTypeChoices.INVOICE, customer)
        document = self.issue(
            invoice, self.make_series(BillingDocumentTypeChoices.F1, prefix="FAC")
        )
        self.assertEqual(document.document_type, BillingDocumentTypeChoices.F1)
        self.assertEqual(document.recipient_legal_name, "Cliente Fiscal SL")
        self.assertEqual(document.recipient_tax_identifier, "B87654321")

    def test_rejects_non_completed_sale_and_invalid_invoice_customer(self):
        sale = create_sale(
            business=self.business, store=self.store, opened_by=self.user
        )
        series = self.make_series(BillingDocumentTypeChoices.F2)
        with self.assertRaises(ValidationError):
            self.issue(sale, series)
        customer = create_sales_customer(business=self.business)
        invoice = self.make_sale(RequestedDocumentTypeChoices.INVOICE, customer)
        with self.assertRaises(ValidationError):
            self.issue(invoice, self.make_series(BillingDocumentTypeChoices.F1))

    def test_idempotency_and_existing_document_policy(self):
        sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2)
        key = uuid.uuid4()
        first = self.issue(sale, series, key)
        retry = self.issue(sale, series, key)
        self.assertEqual(retry.pk, first.pk)
        series.refresh_from_db()
        self.assertEqual(series.current_number, 1)
        other_series = self.make_series(BillingDocumentTypeChoices.F2, prefix="TCK-ALT")
        with self.assertRaises(BillingIdempotencyConflict):
            issue_sale_document(
                business=self.business,
                sale_id=sale.pk,
                series_id=other_series.pk,
                issued_by=self.user,
                idempotency_key=key,
            )
        with self.assertRaises(BillingAlreadyIssued):
            self.issue(sale, series, uuid.uuid4())

    def test_series_id_is_canonical_and_invalid_values_are_domain_errors(self):
        sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2)
        key = uuid.uuid4()
        document = issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=str(series.pk),
            issued_by=self.user,
            idempotency_key=key,
        )
        retry = self.issue(sale, series, key)
        self.assertEqual(retry.pk, document.pk)
        for invalid in (None, "", "abc", uuid.uuid4(), 0, -1):
            with self.subTest(invalid=invalid), self.assertRaises(BillingServiceError):
                issue_sale_document(
                    business=self.business,
                    sale_id=sale.pk,
                    series_id=invalid,
                    issued_by=self.user,
                    idempotency_key=uuid.uuid4(),
                )

    def test_retry_requires_current_authorization(self):
        sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2)
        key = uuid.uuid4()
        self.issue(sale, series, key)
        cashier = create_sales_user(business=self.business, role=RoleChoices.CASHIER)
        with self.assertRaises(BillingServiceError):
            issue_sale_document(
                business=self.business,
                sale_id=sale.pk,
                series_id=series.pk,
                issued_by=cashier,
                idempotency_key=key,
            )

    def test_same_key_on_another_sale_is_a_conflict(self):
        first_sale = self.make_sale()
        second_sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2)
        key = uuid.uuid4()
        self.issue(first_sale, series, key)
        with self.assertRaises(BillingIdempotencyConflict):
            self.issue(second_sale, series, key)

    def test_retry_uses_historical_document_not_mutable_domain_state(self):
        customer = create_sales_customer(
            business=self.business, tax_identifier="B22222222"
        )
        sale = self.make_sale(RequestedDocumentTypeChoices.INVOICE, customer)
        series = self.make_series(BillingDocumentTypeChoices.F1, prefix="FAC")
        key = uuid.uuid4()
        document = self.issue(sale, series, key)
        Sale.objects.filter(pk=sale.pk).update(
            status=SaleStatusChoices.RETURNED,
            document_type_requested=RequestedDocumentTypeChoices.TICKET,
        )
        BillingSeries.objects.filter(pk=series.pk).update(is_active=False)
        customer.is_active = False
        customer.save()
        retry = issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=str(series.pk),
            issued_by=self.user,
            idempotency_key=key,
        )
        self.assertEqual(retry.pk, document.pk)

    def test_permission_matrix(self):
        sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2)
        other_business = create_sales_business()
        cases = [
            None,
            create_sales_user(business=other_business),
            create_sales_user(business=self.business, role=RoleChoices.CASHIER),
        ]
        inactive = create_sales_user(business=self.business)
        inactive.is_active = False
        inactive.save()
        cases.append(inactive)
        no_sell = create_sales_user(business=self.business, role=RoleChoices.CASHIER)
        create_store_access(
            business=self.business, user=no_sell, store=self.store, can_sell=False
        )
        cases.append(no_sell)
        for issuer in cases:
            with self.subTest(issuer=issuer), self.assertRaises(BillingServiceError):
                issue_sale_document(
                    business=self.business,
                    sale_id=sale.pk,
                    series_id=series.pk,
                    issued_by=issuer,
                    idempotency_key=uuid.uuid4(),
                )

        cashier = create_sales_user(business=self.business, role=RoleChoices.CASHIER)
        create_store_access(
            business=self.business, user=cashier, store=self.store, can_sell=True
        )
        self.assertTrue(
            issue_sale_document(
                business=self.business,
                sale_id=sale.pk,
                series_id=series.pk,
                issued_by=cashier,
                idempotency_key=uuid.uuid4(),
            ).pk
        )

    def test_superuser_is_allowed(self):
        sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2)
        superuser = create_sales_user(
            business=self.business, role=RoleChoices.OWNER, is_superuser=True
        )
        self.assertTrue(
            issue_sale_document(
                business=self.business,
                sale_id=sale.pk,
                series_id=series.pk,
                issued_by=superuser,
                idempotency_key=uuid.uuid4(),
            ).pk
        )

    def test_f3_copies_f2_and_creates_relation_without_mutating_sale_customer(self):
        sale = self.make_sale()
        f2 = self.issue(sale, self.make_series(BillingDocumentTypeChoices.F2))
        customer = create_sales_customer(
            business=self.business, legal_name="Receptor SL", tax_identifier="B11111111"
        )
        f3_series = self.make_series(BillingDocumentTypeChoices.F3, prefix="SUS")
        key = uuid.uuid4()
        f3 = substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=customer,
            series_id=f3_series.pk,
            issued_by=self.user,
            idempotency_key=key,
        )
        self.assertEqual(f3.document_type, BillingDocumentTypeChoices.F3)
        for field in (
            "subtotal_amount",
            "discount_amount",
            "tax_amount",
            "total_amount",
        ):
            self.assertEqual(getattr(f3, field), getattr(f2, field))
        self.assertEqual(
            list(f3.lines.values(*BILLING_LINE_SNAPSHOT_FIELDS)),
            list(f2.lines.values(*BILLING_LINE_SNAPSHOT_FIELDS)),
        )
        self.assertEqual(
            list(f3.tax_breakdowns.values(*BILLING_TAX_SNAPSHOT_FIELDS)),
            list(f2.tax_breakdowns.values(*BILLING_TAX_SNAPSHOT_FIELDS)),
        )
        relation = f3.outgoing_relations.get()
        self.assertEqual(relation.target_document, f2)
        self.assertEqual(
            relation.relation_type, BillingDocumentRelationTypeChoices.SUBSTITUTES
        )
        sale.refresh_from_db()
        self.assertIsNone(sale.customer)
        retry = substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=customer,
            series_id=f3_series.pk,
            issued_by=self.user,
            idempotency_key=key,
        )
        self.assertEqual(retry.pk, f3.pk)

        customer.is_active = False
        customer.save()
        historical_retry = substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=customer,
            series_id=f3_series.pk,
            issued_by=self.user,
            idempotency_key=key,
        )
        self.assertEqual(historical_retry.pk, f3.pk)

    def test_f3_invalid_customer_references_are_controlled(self):
        sale = self.make_sale()
        self.issue(sale, self.make_series(BillingDocumentTypeChoices.F2))
        f3_series = self.make_series(BillingDocumentTypeChoices.F3, prefix="SUS")
        unsaved = create_sales_customer(
            business=self.business, tax_identifier="B33333333"
        )
        unsaved.pk = None
        for customer in (None, unsaved):
            with (
                self.subTest(customer=customer),
                self.assertRaises(BillingServiceError),
            ):
                substitute_simplified_document(
                    business=self.business,
                    sale_id=sale.pk,
                    customer=customer,
                    series_id=f3_series.pk,
                    issued_by=self.user,
                    idempotency_key=uuid.uuid4(),
                )

    def test_f3_new_operation_validates_customer_and_original_f2(self):
        sale_without_f2 = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F3, prefix="SUS")
        valid = create_sales_customer(
            business=self.business, tax_identifier="B77777777"
        )
        with self.assertRaises(BillingServiceError):
            substitute_simplified_document(
                business=self.business,
                sale_id=sale_without_f2.pk,
                customer=valid,
                series_id=series.pk,
                issued_by=self.user,
                idempotency_key=uuid.uuid4(),
            )

        sale = self.make_sale()
        self.issue(
            sale,
            self.make_series(BillingDocumentTypeChoices.F2, prefix="TCK-F3-VALID"),
        )
        other_business = create_sales_business()
        customers = [
            create_sales_customer(business=other_business, tax_identifier="B88888888"),
            create_sales_customer(
                business=self.business,
                tax_identifier="B99999999",
                is_active=False,
            ),
            create_sales_customer(business=self.business),
        ]
        for customer in customers:
            with (
                self.subTest(customer=customer),
                self.assertRaises(BillingServiceError),
            ):
                substitute_simplified_document(
                    business=self.business,
                    sale_id=sale.pk,
                    customer=customer,
                    series_id=series.pk,
                    issued_by=self.user,
                    idempotency_key=uuid.uuid4(),
                )

    def test_snapshot_values_are_frozen_after_live_records_change(self):
        customer = create_sales_customer(
            business=self.business,
            name="Cliente original",
            legal_name="Fiscal original",
            tax_identifier="B44444444",
        )
        customer.address_line_1 = "Dirección cliente"
        customer.postal_code = "28002"
        customer.city = "Madrid"
        customer.province = "Madrid"
        customer.save()
        sale = self.make_sale(RequestedDocumentTypeChoices.INVOICE, customer)
        document = self.issue(
            sale, self.make_series(BillingDocumentTypeChoices.F1, prefix="FAC")
        )
        issuer = {
            "issuer_legal_name": "Netxodo SL",
            "issuer_tax_identifier": "B12345678",
            "issuer_address_line_1": "Calle Mayor 1",
            "issuer_address_line_2": "2.º B",
            "issuer_postal_code": "28001",
            "issuer_city": "Madrid",
            "issuer_province": "Madrid",
            "issuer_country_code": "ES",
        }
        recipient = {
            "recipient_name": "Cliente original",
            "recipient_legal_name": "Fiscal original",
            "recipient_tax_identifier": "B44444444",
            "recipient_country_code": "ES",
            "recipient_foreign_id_type": "",
            "recipient_foreign_id": "",
            "recipient_address_line_1": "Dirección cliente",
            "recipient_postal_code": "28002",
            "recipient_city": "Madrid",
            "recipient_province": "Madrid",
        }
        self.profile.legal_name = "Emisor cambiado"
        self.profile.save()
        customer.name = "Cliente cambiado"
        customer.save()
        document.refresh_from_db()
        for field, value in issuer.items() | recipient.items():
            self.assertEqual(getattr(document, field), value)

    def test_breakdown_groups_multiple_tax_rates(self):
        sale = self.make_sale()
        tax_10 = create_sales_tax(
            business=self.business,
            rate=Decimal("10.00"),
            name="IVA 10%",
            is_default=False,
        )
        product_10 = create_sales_product(
            business=self.business, tax=tax_10, base_price=Decimal("20.00")
        )
        create_sale_line(business=self.business, sale=sale, product=product_10)
        document = self.issue(sale, self.make_series(BillingDocumentTypeChoices.F2))
        groups = {
            row.tax_rate: (row.taxable_base_amount, row.tax_amount)
            for row in document.tax_breakdowns.all()
        }
        self.assertEqual(
            groups,
            {
                Decimal("21.00"): (Decimal("10.00"), Decimal("2.10")),
                Decimal("10.00"): (Decimal("20.00"), Decimal("2.00")),
            },
        )

    def test_cross_year_uses_issue_year_and_operation_date(self):
        completed_at = timezone.make_aware(
            timezone.datetime(2026, 12, 31, 23, 0),
            timezone.get_current_timezone(),
        )
        issue_moment = timezone.make_aware(
            timezone.datetime(2027, 1, 3, 10, 0),
            timezone.get_current_timezone(),
        )
        sale = self.make_sale()
        Sale.objects.filter(pk=sale.pk).update(completed_at=completed_at)
        sale.refresh_from_db()
        valid = self.make_series(
            BillingDocumentTypeChoices.F2, prefix="TCK27", year=2027
        )
        with patch("apps.billing.services.timezone.now", return_value=issue_moment):
            document = self.issue(sale, valid)
        self.assertEqual(document.operation_date.isoformat(), "2026-12-31")
        self.assertEqual(timezone.localtime(document.issued_at).year, 2027)

        other_sale = self.make_sale()
        Sale.objects.filter(pk=other_sale.pk).update(completed_at=completed_at)
        invalid = self.make_series(
            BillingDocumentTypeChoices.F2, prefix="TCK26", year=2026
        )
        with patch("apps.billing.services.timezone.now", return_value=issue_moment):
            with self.assertRaises(BillingServiceError):
                self.issue(other_sale, invalid)

    def test_series_text_year_token_boundaries(self):
        prefixes = {
            f"TCK-{timezone.localdate().year}": f"TCK-{timezone.localdate().year}",
            f"TCK/{timezone.localdate().year}": f"TCK/{timezone.localdate().year}",
            f"TCK_{timezone.localdate().year}": f"TCK_{timezone.localdate().year}",
            f"F{timezone.localdate().year}": f"F{timezone.localdate().year}",
            f"SERIE1{timezone.localdate().year}0": (
                f"SERIE1{timezone.localdate().year}0-{timezone.localdate().year}"
            ),
        }
        for index, (prefix, expected) in enumerate(prefixes.items()):
            sale = self.make_sale()
            series = self.make_series(
                BillingDocumentTypeChoices.F2, prefix=f"{prefix}-{index}"
            )
            # Remove the uniqueness suffix after creation; no document exists yet.
            series.prefix = prefix
            series.save()
            self.assertEqual(self.issue(sale, series).series_text, expected)

    def test_series_validation_is_tenant_scoped_and_checks_configuration(self):
        sale = self.make_sale()
        other_business = create_sales_business()
        other_store = create_sales_store(business=other_business)
        series_to_reject = [
            self.make_series(
                BillingDocumentTypeChoices.F2,
                prefix="FOREIGN",
                business=other_business,
                store=other_store,
            ),
            self.make_series(
                BillingDocumentTypeChoices.F2,
                prefix="INACTIVE",
                is_active=False,
            ),
            self.make_series(
                BillingDocumentTypeChoices.F2,
                prefix="STORE",
                store=create_sales_store(business=self.business),
            ),
            self.make_series(BillingDocumentTypeChoices.F1, prefix="TYPE"),
            self.make_series(
                BillingDocumentTypeChoices.F2,
                prefix="YEAR",
                year=timezone.localdate().year - 1,
            ),
        ]
        for series_id in [999999, *(series.pk for series in series_to_reject)]:
            with (
                self.subTest(series_id=series_id),
                self.assertRaises(BillingServiceError),
            ):
                issue_sale_document(
                    business=self.business,
                    sale_id=sale.pk,
                    series_id=series_id,
                    issued_by=self.user,
                    idempotency_key=uuid.uuid4(),
                )

    def test_existing_draft_is_not_resumed(self):
        sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2)
        key = uuid.uuid4()
        BillingDocument.objects.create(
            business=self.business,
            store=self.store,
            sale=sale,
            series=series,
            document_type=BillingDocumentTypeChoices.F2,
            idempotency_key=key,
            idempotency_fingerprint="0" * 64,
        )
        with self.assertRaises(BillingServiceError):
            self.issue(sale, series, key)
        self.assertEqual(BillingDocument.objects.count(), 1)
        self.assertEqual(
            BillingDocument.objects.get().status, BillingDocumentStatusChoices.DRAFT
        )

    def test_failure_after_number_allocation_rolls_everything_back(self):
        sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2, current_number=7)
        original_save = BillingDocument.save

        def fail_issued(document, *args, **kwargs):
            if document.status == BillingDocumentStatusChoices.ISSUED:
                raise RuntimeError("forced after numbering")
            return original_save(document, *args, **kwargs)

        with patch.object(BillingDocument, "save", fail_issued):
            with self.assertRaises(RuntimeError):
                self.issue(sale, series)
        series.refresh_from_db()
        self.assertEqual(series.current_number, 7)
        self.assertFalse(BillingDocument.objects.filter(sale=sale).exists())
        self.assertFalse(BillingDocumentLine.objects.exists())
        self.assertFalse(BillingTaxBreakdown.objects.exists())

    def test_f3_failure_after_numbering_rolls_back_new_history_only(self):
        sale = self.make_sale()
        f2 = self.issue(sale, self.make_series(BillingDocumentTypeChoices.F2))
        customer = create_sales_customer(
            business=self.business, tax_identifier="B55555555"
        )
        series = self.make_series(
            BillingDocumentTypeChoices.F3, current_number=4, prefix="SUS"
        )
        original_save = BillingDocument.save

        def fail_issued_f3(document, *args, **kwargs):
            if (
                document.document_type == BillingDocumentTypeChoices.F3
                and document.status == BillingDocumentStatusChoices.ISSUED
            ):
                raise RuntimeError("forced F3 after numbering")
            return original_save(document, *args, **kwargs)

        baseline_lines = BillingDocumentLine.objects.count()
        baseline_taxes = BillingTaxBreakdown.objects.count()
        with patch.object(BillingDocument, "save", fail_issued_f3):
            with self.assertRaises(RuntimeError):
                substitute_simplified_document(
                    business=self.business,
                    sale_id=sale.pk,
                    customer=customer,
                    series_id=series.pk,
                    issued_by=self.user,
                    idempotency_key=uuid.uuid4(),
                )
        series.refresh_from_db()
        self.assertEqual(series.current_number, 4)
        self.assertEqual(BillingDocument.objects.filter(sale=sale).count(), 1)
        self.assertTrue(BillingDocument.objects.filter(pk=f2.pk).exists())
        self.assertEqual(BillingDocumentLine.objects.count(), baseline_lines)
        self.assertEqual(BillingTaxBreakdown.objects.count(), baseline_taxes)
        self.assertFalse(BillingDocumentRelation.objects.exists())

    def test_issued_history_is_immutable(self):
        sale = self.make_sale()
        document = self.issue(sale, self.make_series(BillingDocumentTypeChoices.F2))
        line = document.lines.get()
        breakdown = document.tax_breakdowns.get()
        document.description = "altered"
        line.product_name = "altered"
        breakdown.tax_amount = Decimal("99.00")
        for instance in (document, line, breakdown):
            with (
                self.subTest(instance=type(instance).__name__),
                self.assertRaises(ValidationError),
            ):
                instance.save()

    def test_f3_relation_is_immutable(self):
        sale = self.make_sale()
        self.issue(sale, self.make_series(BillingDocumentTypeChoices.F2))
        customer = create_sales_customer(
            business=self.business, tax_identifier="B66666666"
        )
        f3 = substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=customer,
            series_id=self.make_series(BillingDocumentTypeChoices.F3, prefix="SUS").pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        relation = f3.outgoing_relations.get()
        relation.relation_type = BillingDocumentRelationTypeChoices.RECTIFIES
        with self.assertRaises(ValidationError):
            relation.save()
