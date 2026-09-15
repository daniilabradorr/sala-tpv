import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.catalog.models import Product
from apps.core.models import Business
from apps.purchases.models import (
    Purchase,
    PurchaseLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    Supplier,
)
from apps.reports.periods import ReportPeriod
from apps.reports.selectors import (
    purchase_receipts_summary,
    purchase_summary,
    purchases_by_product,
    purchases_by_store,
    purchases_by_supplier,
)
from apps.stores.models import Store
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user

UTC = ZoneInfo("UTC")


class PurchaseReportTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Principal", slug="principal-reports"
        )
        self.store = Store.objects.create(
            business=self.business, name="Centro", code="CENTRO-R"
        )
        self.user = create_user(
            business=self.business,
            email="reports-purchases@example.test",
            role=RoleChoices.OWNER,
        )
        self.supplier = Supplier.objects.create(
            business=self.business, name="Proveedor A"
        )
        self.product = Product.objects.create(
            business=self.business,
            name="Café",
            sku="CAFE",
            base_price=Decimal("2"),
            cost_price=Decimal("1"),
            unit=Product.UNIT_UNIDAD,
        )
        self.period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
        )

    def _purchase(
        self,
        *,
        status="ordered",
        when=None,
        store=None,
        supplier=None,
        subtotal="100",
        tax="21",
    ):
        return Purchase.objects.create(
            business=self.business,
            store=store or self.store,
            supplier=supplier or self.supplier,
            created_by=self.user,
            status=status,
            ordered_at=when
            if when is not None
            else (None if status == "draft" else datetime(2026, 9, 10, tzinfo=UTC)),
            subtotal_amount=Decimal(subtotal),
            tax_amount=Decimal(tax),
            total_amount=Decimal(subtotal) + Decimal(tax),
        )

    def _line(
        self,
        purchase,
        *,
        product=None,
        name=None,
        sku=None,
        quantity="10",
        received="3",
        total="24",
    ):
        product = product or self.product
        return PurchaseLine.objects.create(
            business=self.business,
            purchase=purchase,
            product=product,
            product_name=name or product.name,
            sku=sku or product.sku,
            unit=product.unit,
            quantity_ordered=Decimal(quantity),
            quantity_received=Decimal(received),
            unit_cost=Decimal("2"),
            line_subtotal=Decimal("20"),
            tax_amount=Decimal("4"),
            line_total=Decimal(total),
        )

    def _receipt(self, purchase, line, when, quantity="2"):
        receipt = PurchaseReceipt.objects.create(
            business=self.business,
            store=purchase.store,
            purchase=purchase,
            received_by=self.user,
            received_at=when,
            idempotency_key=uuid.uuid4(),
            idempotency_fingerprint="a" * 64,
        )
        PurchaseReceiptLine.objects.create(
            business=self.business,
            receipt=receipt,
            purchase_line=line,
            quantity_received=Decimal(quantity),
        )
        return receipt

    def test_empty_summary_and_confirmed_statuses(self):
        self.assertEqual(
            purchase_summary(business=self.business, period=self.period),
            {
                "purchase_count": 0,
                "subtotal_amount": Decimal("0.00"),
                "tax_amount": Decimal("0.00"),
                "total_amount": Decimal("0.00"),
                "ordered_count": 0,
                "partially_received_count": 0,
                "received_count": 0,
            },
        )
        self._purchase(status="draft", subtotal="0", tax="0")
        self._purchase(status="cancelled")
        self._purchase(status="ordered", subtotal="10", tax="2")
        self._purchase(status="partially_received", subtotal="20", tax="4")
        self._purchase(status="received", subtotal="30", tax="6")
        result = purchase_summary(business=self.business, period=self.period)
        self.assertEqual(
            (
                result["purchase_count"],
                result["subtotal_amount"],
                result["tax_amount"],
                result["total_amount"],
            ),
            (3, Decimal("60"), Decimal("12"), Decimal("72")),
        )
        self.assertEqual(
            (
                result["ordered_count"],
                result["partially_received_count"],
                result["received_count"],
            ),
            (1, 1, 1),
        )

    def test_ordered_at_bounds_store_business_and_grouping(self):
        supplier_b = Supplier.objects.create(business=self.business, name="Proveedor B")
        north = Store.objects.create(
            business=self.business, name="Norte", code="NORTE-R"
        )
        self._purchase(when=self.period.start, subtotal="10", tax="2")
        self._purchase(when=self.period.end, subtotal="999", tax="1")
        self._purchase(store=north, supplier=supplier_b, subtotal="30", tax="6")
        self._purchase(store=north, supplier=supplier_b, subtotal="20", tax="4")
        suppliers = purchases_by_supplier(business=self.business, period=self.period)
        self.assertEqual(
            [r["supplier_id"] for r in suppliers], [supplier_b.pk, self.supplier.pk]
        )
        self.assertEqual(
            (suppliers[0]["purchase_count"], suppliers[0]["total_amount"]),
            (2, Decimal("60")),
        )
        stores = purchases_by_store(
            business=self.business, period=self.period, store=north
        )
        self.assertEqual(
            (len(stores), stores[0]["purchase_count"], stores[0]["total_amount"]),
            (1, 2, Decimal("60")),
        )
        other = Business.objects.create(name="Otro", slug="otro-purchase-reports")
        foreign = Store.objects.create(business=other, name="Otra", code="OTRA-R")
        self.assertEqual(
            purchase_summary(business=self.business, period=self.period)[
                "purchase_count"
            ],
            3,
        )
        with self.assertRaises(ValueError):
            purchase_summary(business=self.business, period=self.period, store=foreign)

    def test_products_use_line_snapshots_amounts_and_current_fulfillment(self):
        purchase = self._purchase(subtotal="100", tax="21")
        self._line(
            purchase,
            name="Café histórico",
            sku="OLD",
            quantity="10",
            received="3",
            total="24",
        )
        self._line(
            purchase,
            name="Café histórico",
            sku="OLD",
            quantity="2",
            received="1",
            total="6",
        )
        second = Product.objects.create(
            business=self.business,
            name="Té",
            sku="TE",
            base_price=Decimal("1"),
            unit=Product.UNIT_KG,
        )
        self._line(purchase, product=second, quantity="5", received="0", total="10")
        self.product.name = "Café actual"
        self.product.save()
        rows = purchases_by_product(business=self.business, period=self.period)
        old = next(row for row in rows if row["sku"] == "OLD")
        self.assertEqual(
            (old["product_name"], old["purchase_amount"]),
            ("Café histórico", Decimal("30")),
        )
        self.assertEqual(
            (
                old["quantity_ordered"],
                old["quantity_received"],
                old["quantity_pending"],
            ),
            (Decimal("12"), Decimal("4"), Decimal("8")),
        )
        self.assertEqual(len(rows), 2)

    def test_receipts_use_received_at_not_ordered_at_and_keep_products_separate(self):
        august = self._purchase(when=datetime(2026, 8, 15, tzinfo=UTC))
        august_line = self._line(august, received="0")
        self._receipt(august, august_line, self.period.start, quantity="2")
        september = self._purchase(when=datetime(2026, 9, 15, tzinfo=UTC))
        september_line = self._line(september, received="0", name="Café B", sku="B")
        self._receipt(september, september_line, self.period.end, quantity="3")
        result = purchase_receipts_summary(business=self.business, period=self.period)
        self.assertEqual(
            (result["receipt_count"], result["receipt_line_count"]), (1, 1)
        )
        self.assertEqual(
            result["by_product"],
            [
                {
                    "sku": "CAFE",
                    "product_name": "Café",
                    "unit": self.product.unit,
                    "quantity_received": Decimal("2"),
                }
            ],
        )
        self.assertEqual(
            purchase_summary(business=self.business, period=self.period)[
                "purchase_count"
            ],
            1,
        )

    def test_receipt_store_and_business_isolation(self):
        purchase = self._purchase()
        line = self._line(purchase, received="0")
        self._receipt(purchase, line, datetime(2026, 9, 10, tzinfo=UTC))
        self.assertEqual(
            purchase_receipts_summary(
                business=self.business, period=self.period, store=self.store
            )["receipt_count"],
            1,
        )
        other = Business.objects.create(name="Otro", slug="receipt-other")
        foreign = Store.objects.create(business=other, name="Otra", code="RECEIPT-O")
        with self.assertRaises(ValueError):
            purchase_receipts_summary(
                business=self.business, period=self.period, store=foreign
            )
