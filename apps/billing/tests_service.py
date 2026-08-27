import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import (
    BillingDocument,
    BillingDocumentRelationTypeChoices,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingSeries,
)
from apps.billing.services import (
    BillingAlreadyIssued,
    BillingIdempotencyConflict,
    issue_sale_document,
    substitute_simplified_document,
)
from apps.business_config.models import BusinessProfile
from apps.sales.models import RequestedDocumentTypeChoices, SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sales_business,
    create_sales_customer,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


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

    def make_series(self, document_type, current_number=0, prefix="TCK-CEN"):
        return BillingSeries.objects.create(
            business=self.business,
            store=self.store,
            name=f"Serie {document_type}",
            document_type=document_type,
            prefix=prefix,
            year=timezone.localdate().year,
            current_number=current_number,
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
        with self.assertRaises(BillingIdempotencyConflict):
            issue_sale_document(
                business=self.business,
                sale_id=sale.pk,
                series_id=uuid.uuid4(),
                issued_by=self.user,
                idempotency_key=key,
            )
        with self.assertRaises(BillingAlreadyIssued):
            self.issue(sale, series, uuid.uuid4())

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
        self.assertEqual(f3.total_amount, f2.total_amount)
        self.assertEqual(
            list(f3.lines.values("product_name", "line_total")),
            list(f2.lines.values("product_name", "line_total")),
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

    def test_failure_after_number_allocation_rolls_everything_back(self):
        sale = self.make_sale()
        series = self.make_series(BillingDocumentTypeChoices.F2, current_number=7)
        with patch(
            "apps.billing.services.timezone.now", side_effect=RuntimeError("forced")
        ):
            with self.assertRaises(RuntimeError):
                self.issue(sale, series)
        series.refresh_from_db()
        self.assertEqual(series.current_number, 7)
        self.assertFalse(BillingDocument.objects.filter(sale=sale).exists())
