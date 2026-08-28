import uuid
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.billing.models import (
    BillingDocument,
    BillingDocumentRelationTypeChoices,
    BillingDocumentTypeChoices,
    BillingRectificationMethodChoices,
    BillingSeries,
)
from apps.billing.services import (
    BillingUnsupportedFiscalCase,
    issue_sale_document,
    issue_sale_return_rectification,
    substitute_simplified_document,
)
from apps.business_config.models import BusinessProfile
from apps.sales.models import (
    RequestedDocumentTypeChoices,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_business,
    create_sales_customer,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


class SaleReturnRectificationTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        profile = BusinessProfile.objects.get(business=self.business)
        for field, value in {
            "legal_name": "Current Issuer SL",
            "tax_identifier": "B12345678",
            "address_line_1": "Calle 1",
            "postal_code": "28001",
            "city": "Madrid",
            "province": "Madrid",
            "country_code": "ES",
        }.items():
            setattr(profile, field, value)
        profile.save()
        self.tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(business=self.business, tax=self.tax)

    def series(self, document_type, prefix):
        return BillingSeries.objects.create(
            business=self.business,
            store=self.store,
            name=prefix,
            document_type=document_type,
            prefix=prefix,
            year=timezone.localdate().year,
        )

    def completed_sale(
        self, *, invoice=False, customer=None, quantity=Decimal("1.000")
    ):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            customer=customer,
            status=SaleStatusChoices.COMPLETED,
            document_type_requested=(
                RequestedDocumentTypeChoices.INVOICE
                if invoice
                else RequestedDocumentTypeChoices.TICKET
            ),
        )
        line = create_sale_line(
            business=self.business, sale=sale, product=self.product, quantity=quantity
        )
        return sale, line

    def completed_return(self, sale, line, *, quantity=Decimal("1.000"), amount=None):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=line,
            quantity=quantity,
            amount=amount,
        )
        return_doc.status = SaleReturnStatusChoices.COMPLETED
        return_doc.completed_at = timezone.now()
        return_doc.save()
        return return_doc

    def issue_original(self, sale, document_type):
        return issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=self.series(document_type, f"OR{document_type}").pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )

    def assert_fiscal_invariants(self, line):
        self.assertEqual(
            line.gross_base_amount,
            (line.unit_base_price * line.quantity).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
        )
        self.assertEqual(
            line.gross_base_amount - line.discount_amount, line.taxable_base_amount
        )
        self.assertEqual(
            line.tax_amount,
            (line.taxable_base_amount * line.tax_rate / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
        )
        self.assertEqual(line.taxable_base_amount + line.tax_amount, line.line_total)

    def test_f1_completed_return_issues_negative_r1_with_historical_snapshots(self):
        customer = create_sales_customer(
            business=self.business,
            legal_name="Historical Recipient SL",
            tax_identifier="B87654321",
        )
        sale, sale_line = self.completed_sale(invoice=True, customer=customer)
        original = self.issue_original(sale, BillingDocumentTypeChoices.F1)
        customer.legal_name = "Mutable Recipient SL"
        customer.save()
        self.product.name = "Mutable product"
        self.product.save()
        return_doc = self.completed_return(sale, sale_line)
        series = self.series(BillingDocumentTypeChoices.R1, "R1")
        before = timezone.now()
        rectification = issue_sale_return_rectification(
            business=self.business,
            sale_return_id=return_doc.pk,
            series_id=series.pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        self.assertEqual(rectification.document_type, BillingDocumentTypeChoices.R1)
        self.assertEqual(
            rectification.rectification_method,
            BillingRectificationMethodChoices.DIFFERENCES,
        )
        self.assertEqual(rectification.sale_return, return_doc)
        self.assertGreaterEqual(rectification.issued_at, before)
        self.assertEqual(
            rectification.operation_date,
            timezone.localtime(return_doc.completed_at).date(),
        )
        self.assertEqual(
            rectification.recipient_legal_name, original.recipient_legal_name
        )
        self.assertEqual(rectification.issuer_legal_name, "Current Issuer SL")
        relation = rectification.outgoing_relations.get()
        self.assertEqual(
            (relation.relation_type, relation.target_document_id),
            (BillingDocumentRelationTypeChoices.RECTIFIES, original.pk),
        )
        return_doc.refresh_from_db()
        self.assertEqual(return_doc.original_billing_document_id, original.pk)
        line = rectification.lines.get()
        self.assertLess(line.quantity, 0)
        self.assertLess(line.line_total, 0)
        self.assertEqual(line.product_name, original.lines.get().product_name)
        self.assert_fiscal_invariants(line)
        self.assertLess(rectification.tax_breakdowns.get().taxable_base_amount, 0)

    def test_f2_return_issues_r5_and_retry_does_not_consume_number(self):
        sale, sale_line = self.completed_sale()
        original = self.issue_original(sale, BillingDocumentTypeChoices.F2)
        return_doc = self.completed_return(sale, sale_line)
        series = self.series(BillingDocumentTypeChoices.R5, "R5")
        key = uuid.uuid4()
        first = issue_sale_return_rectification(
            business=self.business,
            sale_return_id=return_doc.pk,
            series_id=series.pk,
            issued_by=self.user,
            idempotency_key=key,
        )
        retry = issue_sale_return_rectification(
            business=self.business,
            sale_return_id=return_doc.pk,
            series_id=series.pk,
            issued_by=self.user,
            idempotency_key=key,
        )
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(first.document_type, BillingDocumentTypeChoices.R5)
        self.assertEqual(first.outgoing_relations.get().target_document_id, original.pk)
        series.refresh_from_db()
        self.assertEqual(series.current_number, 1)

    def test_f2_f3_return_issues_and_validates_companion_f3_on_retry(self):
        sale, sale_line = self.completed_sale()
        original = self.issue_original(sale, BillingDocumentTypeChoices.F2)
        customer = create_sales_customer(
            business=self.business,
            legal_name="Historical F3 Recipient SL",
            tax_identifier="B11223344",
        )
        initial_f3 = substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=customer,
            series_id=self.series(BillingDocumentTypeChoices.F3, "F3I").pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        customer.legal_name = "Mutable recipient"
        customer.save()
        return_doc = self.completed_return(sale, sale_line)
        r5_series = self.series(BillingDocumentTypeChoices.R5, "R5F3")
        companion_series = self.series(BillingDocumentTypeChoices.F3, "F3C")
        key = uuid.uuid4()
        r5 = issue_sale_return_rectification(
            business=self.business,
            sale_return_id=return_doc.pk,
            series_id=r5_series.pk,
            companion_f3_series_id=companion_series.pk,
            issued_by=self.user,
            idempotency_key=key,
        )
        companion = BillingDocument.objects.get(
            sale_return=return_doc, document_type=BillingDocumentTypeChoices.F3
        )
        self.assertEqual(
            companion.recipient_legal_name, initial_f3.recipient_legal_name
        )
        self.assertEqual(companion.outgoing_relations.get().target_document_id, r5.pk)
        self.assertEqual(
            companion.outgoing_relations.get().relation_type,
            BillingDocumentRelationTypeChoices.SUBSTITUTES,
        )
        self.assertEqual(
            companion.idempotency_key,
            uuid.uuid5(key, "netxodo:billing:sale-return-companion-f3"),
        )
        retry = issue_sale_return_rectification(
            business=self.business,
            sale_return_id=return_doc.pk,
            series_id=r5_series.pk,
            companion_f3_series_id=companion_series.pk,
            issued_by=self.user,
            idempotency_key=key,
        )
        self.assertEqual(retry.pk, r5.pk)
        r5_series.refresh_from_db()
        companion_series.refresh_from_db()
        self.assertEqual(
            (r5_series.current_number, companion_series.current_number), (1, 1)
        )
        self.assertEqual(r5.outgoing_relations.get().target_document_id, original.pk)

    def test_partial_allocation_finds_tax_consistent_base_for_review_case(self):
        sale, sale_line = self.completed_sale(quantity=Decimal("2.000"))
        original = self.issue_original(sale, BillingDocumentTypeChoices.F2)
        fiscal = original.lines.get()
        BillingDocument.objects.filter(pk=original.pk).update(
            subtotal_amount=Decimal("1.00"),
            discount_amount=Decimal("0.13"),
            tax_amount=Decimal("0.09"),
            total_amount=Decimal("0.96"),
        )
        type(fiscal).objects.filter(pk=fiscal.pk).update(
            quantity=Decimal("2.000"),
            unit_base_price=Decimal("0.50"),
            gross_base_amount=Decimal("1.00"),
            discount_amount=Decimal("0.13"),
            taxable_base_amount=Decimal("0.87"),
            tax_rate=Decimal("10.00"),
            tax_amount=Decimal("0.09"),
            line_total=Decimal("0.96"),
        )
        return_doc = self.completed_return(sale, sale_line, amount=Decimal("0.48"))
        rectification = issue_sale_return_rectification(
            business=self.business,
            sale_return_id=return_doc.pk,
            series_id=self.series(BillingDocumentTypeChoices.R5, "R5C").pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        line = rectification.lines.get()
        self.assertEqual(
            (line.taxable_base_amount, line.tax_amount),
            (Decimal("-0.44"), Decimal("-0.04")),
        )
        self.assert_fiscal_invariants(line)

    def test_missing_source_sale_line_fails_closed_without_consuming_number(self):
        sale, sale_line = self.completed_sale()
        original = self.issue_original(sale, BillingDocumentTypeChoices.F2)
        original.lines.update(source_sale_line=None)
        return_doc = self.completed_return(sale, sale_line)
        series = self.series(BillingDocumentTypeChoices.R5, "R5NOSOURCE")
        with self.assertRaises(BillingUnsupportedFiscalCase):
            issue_sale_return_rectification(
                business=self.business,
                sale_return_id=return_doc.pk,
                series_id=series.pk,
                issued_by=self.user,
                idempotency_key=uuid.uuid4(),
            )
        series.refresh_from_db()
        self.assertEqual(series.current_number, 0)
        self.assertFalse(
            BillingDocument.objects.filter(sale_return=return_doc).exists()
        )

    def test_companion_failure_after_numbering_rolls_back_entire_operation(self):
        sale, sale_line = self.completed_sale()
        self.issue_original(sale, BillingDocumentTypeChoices.F2)
        customer = create_sales_customer(
            business=self.business,
            legal_name="Rollback Recipient SL",
            tax_identifier="B44332211",
        )
        substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=customer,
            series_id=self.series(BillingDocumentTypeChoices.F3, "F3ROLLBASE").pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        return_doc = self.completed_return(sale, sale_line)
        r5_series = self.series(BillingDocumentTypeChoices.R5, "R5ROLL")
        f3_series = self.series(BillingDocumentTypeChoices.F3, "F3ROLL")
        from apps.billing import services

        real_finalize = services._finalize_return_document
        calls = 0

        def fail_after_companion_numbering(**kwargs):
            nonlocal calls
            calls += 1
            real_finalize(**kwargs)
            if calls == 2:
                raise BillingUnsupportedFiscalCase("Fallo inyectado tras numeración.")

        with (
            patch(
                "apps.billing.services._finalize_return_document",
                side_effect=fail_after_companion_numbering,
            ),
            self.assertRaises(BillingUnsupportedFiscalCase),
        ):
            issue_sale_return_rectification(
                business=self.business,
                sale_return_id=return_doc.pk,
                series_id=r5_series.pk,
                companion_f3_series_id=f3_series.pk,
                issued_by=self.user,
                idempotency_key=uuid.uuid4(),
            )
        r5_series.refresh_from_db()
        f3_series.refresh_from_db()
        return_doc.refresh_from_db()
        self.assertEqual((r5_series.current_number, f3_series.current_number), (0, 0))
        self.assertIsNone(return_doc.original_billing_document_id)
        self.assertFalse(
            BillingDocument.objects.filter(sale_return=return_doc).exists()
        )

    def test_impossible_amount_fails_closed_and_rolls_back_anchor(self):
        sale, sale_line = self.completed_sale()
        self.issue_original(sale, BillingDocumentTypeChoices.F2)
        return_doc = self.completed_return(
            sale, sale_line, quantity=Decimal("0.500"), amount=Decimal("0.03")
        )
        with self.assertRaises(BillingUnsupportedFiscalCase):
            issue_sale_return_rectification(
                business=self.business,
                sale_return_id=return_doc.pk,
                series_id=self.series(BillingDocumentTypeChoices.R5, "R5X").pk,
                issued_by=self.user,
                idempotency_key=uuid.uuid4(),
            )
        return_doc.refresh_from_db()
        self.assertIsNone(return_doc.original_billing_document_id)
        self.assertFalse(
            BillingDocument.objects.filter(sale_return=return_doc).exists()
        )

    def test_three_partial_returns_reconstruct_full_snapshot_exactly(self):
        sale, sale_line = self.completed_sale(quantity=Decimal("3.000"))
        original = self.issue_original(sale, BillingDocumentTypeChoices.F2)
        returns = [
            self.completed_return(sale, sale_line, quantity=Decimal("1.000"))
            for _ in range(3)
        ]
        series = self.series(BillingDocumentTypeChoices.R5, "R5PARTS")
        documents = [
            issue_sale_return_rectification(
                business=self.business,
                sale_return_id=return_doc.pk,
                series_id=series.pk,
                issued_by=self.user,
                idempotency_key=uuid.uuid4(),
            )
            for return_doc in returns
        ]
        lines = [document.lines.get() for document in documents]
        for line in lines:
            self.assert_fiscal_invariants(line)
        original_line = original.lines.get()
        for field in (
            "gross_base_amount",
            "discount_amount",
            "taxable_base_amount",
            "tax_amount",
            "line_total",
        ):
            self.assertEqual(
                sum((getattr(line, field) for line in lines), Decimal("0.00")),
                -getattr(original_line, field),
            )
