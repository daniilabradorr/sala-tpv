import uuid
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.billing.models import (
    BillingDocument,
    BillingDocumentRelation,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingRectificationMethodChoices,
    BillingSeries,
    BillingTaxBreakdown,
)
from apps.reports.periods import ReportPeriod
from apps.reports.selectors import (
    billing_documents_summary,
    tax_by_rate,
    tax_summary,
)
from apps.sales.tests.factories import (
    create_sales_business,
    create_sales_store,
    create_sales_user,
)

UTC = ZoneInfo("UTC")


class TaxReportTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business, name="Centro")
        self.user = create_sales_user(business=self.business)
        self.period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
        )
        self.number = 0

    def _document(
        self,
        document_type,
        *,
        when=None,
        base="100.00",
        tax="21.00",
        total=None,
        tax_type="IVA",
        tax_rate="21.00",
        status=BillingDocumentStatusChoices.ISSUED,
        store=None,
        business=None,
        extra_breakdowns=(),
    ):
        business = business or self.business
        store = store or self.store
        self.number += 1
        document_base = Decimal(base) + sum(
            (values["taxable_base_amount"] for values in extra_breakdowns),
            Decimal("0.00"),
        )
        document_tax = Decimal(tax) + sum(
            (values["tax_amount"] for values in extra_breakdowns), Decimal("0.00")
        )
        series = BillingSeries.objects.create(
            business=business,
            store=store,
            name=f"Serie {document_type} {self.number}",
            document_type=document_type,
            prefix=f"{document_type}-{self.number}",
            year=2026,
        )
        is_rectification = document_type.startswith("R")
        document = BillingDocument.objects.create(
            business=business,
            store=store,
            series=series,
            document_type=document_type,
            rectification_method=(
                BillingRectificationMethodChoices.DIFFERENCES
                if is_rectification
                else None
            ),
            subtotal_amount=document_base,
            tax_amount=document_tax,
            total_amount=Decimal(total) if total else document_base + document_tax,
        )
        BillingTaxBreakdown.objects.create(
            business=business,
            billing_document=document,
            tax_type=tax_type,
            tax_rate=Decimal(tax_rate),
            taxable_base_amount=Decimal(base),
            tax_amount=Decimal(tax),
        )
        for values in extra_breakdowns:
            BillingTaxBreakdown.objects.create(
                business=business, billing_document=document, **values
            )
        if status == BillingDocumentStatusChoices.ISSUED:
            issued_by = (
                self.user
                if business == self.business
                else create_sales_user(business=business)
            )
            BillingDocument.objects.filter(pk=document.pk).update(
                status=status,
                number=self.number,
                series_text=series.prefix,
                issued_at=when or datetime(2026, 9, 10, tzinfo=UTC),
                operation_date=date(2026, 9, 10),
                issued_by=issued_by,
                idempotency_key=uuid.uuid4(),
                idempotency_fingerprint="a" * 64,
            )
            document.refresh_from_db()
        return document

    def test_empty_and_draft_have_no_fiscal_effect(self):
        self._document(BillingDocumentTypeChoices.F1, status="draft")
        self.assertEqual(
            billing_documents_summary(business=self.business, period=self.period),
            {
                "issued_document_count": 0,
                "effective_document_count": 0,
                "substituted_document_count": 0,
                "rectification_document_count": 0,
                "by_type": [],
            },
        )
        result = tax_summary(business=self.business, period=self.period)
        self.assertEqual(result["effective_document_count"], 0)
        for key in result.keys() - {"effective_document_count"}:
            self.assertEqual(result[key], Decimal("0.00"))

    def test_output_types_and_all_rectification_types_preserve_signs(self):
        for kind in ("F1", "F2", "F3"):
            self._document(kind)
        for kind in ("R1", "R2", "R3", "R4", "R5"):
            self._document(kind, base="-20.00", tax="-4.20")
        result = tax_summary(business=self.business, period=self.period)
        self.assertEqual(result["output_taxable_base"], Decimal("300"))
        self.assertEqual(result["output_tax_amount"], Decimal("63"))
        self.assertEqual(result["rectified_taxable_base"], Decimal("-100"))
        self.assertEqual(result["rectified_tax_amount"], Decimal("-21"))
        self.assertEqual(result["net_taxable_base"], Decimal("200"))
        self.assertEqual(result["net_tax_amount"], Decimal("42"))
        summary = billing_documents_summary(business=self.business, period=self.period)
        self.assertEqual(summary["rectification_document_count"], 5)
        self.assertEqual(
            [row["document_type"] for row in summary["by_type"]],
            ["F1", "F2", "F3", "R1", "R2", "R3", "R4", "R5"],
        )

    def test_breakdowns_are_authoritative_and_rate_groups_keep_type(self):
        self._document(
            "F1",
            base="40",
            tax="8.40",
            total="70.50",
            extra_breakdowns=(
                {
                    "tax_type": "IVA",
                    "tax_rate": Decimal("10"),
                    "taxable_base_amount": Decimal("10"),
                    "tax_amount": Decimal("1"),
                },
                {
                    "tax_type": "IGIC",
                    "tax_rate": Decimal("21"),
                    "taxable_base_amount": Decimal("10"),
                    "tax_amount": Decimal("1.10"),
                },
            ),
        )
        result = tax_summary(business=self.business, period=self.period)
        self.assertEqual(result["output_taxable_base"], Decimal("60"))
        self.assertEqual(result["output_tax_amount"], Decimal("10.50"))
        self.assertEqual(result["effective_total_amount"], Decimal("70.50"))
        rows = tax_by_rate(business=self.business, period=self.period)
        self.assertEqual(
            [(r["tax_type"], r["tax_rate"]) for r in rows],
            [("IGIC", Decimal("21")), ("IVA", Decimal("10")), ("IVA", Decimal("21"))],
        )
        self.assertTrue(all(row["document_count"] == 1 for row in rows))

    def test_substitutes_but_rectifies_does_not_remove_target(self):
        f1 = self._document("F1")
        r1 = self._document("R1", base="-20", tax="-4.20")
        BillingDocumentRelation.objects.bulk_create(
            [
                BillingDocumentRelation(
                    business=self.business,
                    source_document=r1,
                    target_document=f1,
                    relation_type="rectifies",
                )
            ]
        )
        self.assertEqual(
            tax_summary(business=self.business, period=self.period)["net_taxable_base"],
            Decimal("80"),
        )

        f2 = self._document("F2")
        f3 = self._document("F3")
        BillingDocumentRelation.objects.bulk_create(
            [
                BillingDocumentRelation(
                    business=self.business,
                    source_document=f3,
                    target_document=f2,
                    relation_type="substitutes",
                )
            ]
        )
        summary = billing_documents_summary(business=self.business, period=self.period)
        self.assertEqual(summary["issued_document_count"], 4)
        self.assertEqual(summary["effective_document_count"], 3)
        self.assertEqual(summary["substituted_document_count"], 1)
        self.assertEqual(
            tax_summary(business=self.business, period=self.period)["net_taxable_base"],
            Decimal("180"),
        )

    def test_cross_period_bounds_store_and_business_isolation(self):
        august = ReportPeriod(datetime(2026, 8, 1, tzinfo=UTC), self.period.start)
        old = self._document("F2", when=datetime(2026, 8, 15, tzinfo=UTC))
        replacement = self._document("F3", when=self.period.start)
        BillingDocumentRelation.objects.bulk_create(
            [
                BillingDocumentRelation(
                    business=self.business,
                    source_document=replacement,
                    target_document=old,
                    relation_type="substitutes",
                )
            ]
        )
        self._document("F1", when=self.period.end)
        second = create_sales_store(business=self.business, name="Norte")
        self._document("F1", store=second)
        other = create_sales_business()
        other_store = create_sales_store(business=other)
        self._document("F1", business=other, store=other_store)
        self.assertEqual(
            billing_documents_summary(business=self.business, period=august)[
                "issued_document_count"
            ],
            1,
        )
        self.assertEqual(
            tax_summary(business=self.business, period=august)[
                "effective_document_count"
            ],
            0,
        )
        self.assertEqual(
            tax_summary(business=self.business, period=self.period, store=self.store)[
                "effective_document_count"
            ],
            1,
        )
        with self.assertRaises(ValueError):
            tax_summary(business=self.business, period=self.period, store=other_store)
