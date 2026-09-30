from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.inventory.models import StockMovement
from apps.inventory.tests.factories import (
    create_business,
    create_inventory_item,
    create_inventory_owner,
    create_inventory_product,
    create_inventory_store,
)
from apps.purchases.models import (
    Purchase,
    PurchaseLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    Supplier,
)
from apps.reports.periods import ReportPeriod
from apps.reports.selectors import inventory_movements_summary, inventory_summary

UTC = ZoneInfo("UTC")


class InventoryReportTests(TestCase):
    def setUp(self):
        self.business = create_business()
        self.store = create_inventory_store(business=self.business)
        self.user = create_inventory_owner(business=self.business)
        self.period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
        )

    def _item(self, name, **values):
        product = create_inventory_product(business=self.business, name=name)
        return create_inventory_item(
            business=self.business, store=self.store, product=product, **values
        )

    def _movement(
        self,
        item,
        movement_type,
        *,
        when=None,
        before="0",
        after=None,
        quantity="1",
        **relations,
    ):
        before = Decimal(before)
        quantity = Decimal(quantity)
        if after is None:
            after = (
                before - quantity
                if movement_type in StockMovement.OUT_TYPES
                else before + quantity
            )
        return StockMovement.objects.bulk_create(
            [
                StockMovement(
                    business=self.business,
                    inventory_item=item,
                    store=item.store,
                    product=item.product,
                    movement_type=movement_type,
                    quantity=quantity,
                    stock_before=before,
                    stock_after=Decimal(after),
                    occurred_at=when or datetime(2026, 9, 10, tzinfo=UTC),
                    created_by=self.user,
                    **relations,
                )
            ]
        )

    def test_empty_current_summary(self):
        self.assertEqual(
            inventory_summary(business=self.business),
            {
                "tracked_items_count": 0,
                "out_of_stock_count": 0,
                "low_stock_count": 0,
                "healthy_stock_count": 0,
                "items": [],
            },
        )

    def test_current_stock_statuses_are_exclusive_and_inactive_is_ignored(self):
        out = self._item(
            "Agua",
            current_stock=Decimal("2"),
            reserved_stock=Decimal("2"),
            minimum_stock=Decimal("3"),
        )
        low = self._item(
            "Café",
            current_stock=Decimal("4"),
            reserved_stock=Decimal("1"),
            minimum_stock=Decimal("3"),
        )
        healthy = self._item(
            "Té",
            current_stock=Decimal("8"),
            reserved_stock=Decimal("1"),
            minimum_stock=Decimal("3"),
        )
        self._item("Inactivo", current_stock=Decimal("99"), is_active=False)
        result = inventory_summary(business=self.business)
        self.assertEqual(
            (
                result["tracked_items_count"],
                result["out_of_stock_count"],
                result["low_stock_count"],
                result["healthy_stock_count"],
            ),
            (3, 1, 1, 1),
        )
        rows = {row["inventory_item_id"]: row for row in result["items"]}
        self.assertEqual(rows[out.pk]["available_stock"], Decimal("0"))
        self.assertEqual(rows[out.pk]["stock_status"], "out_of_stock")
        self.assertEqual(rows[low.pk]["stock_status"], "low_stock")
        self.assertEqual(rows[healthy.pk]["stock_status"], "healthy")
        self.assertIsNone(rows[out.pk]["maximum_stock"])
        self.assertNotIn("total_current_stock", result)
        self.assertNotIn("total_available_stock", result)

    def test_current_summary_scope(self):
        self._item("Centro", current_stock=Decimal("1"))
        other_store = create_inventory_store(
            business=self.business, name="Tienda Inventario Norte"
        )
        product = create_inventory_product(business=self.business, name="Norte")
        create_inventory_item(
            business=self.business, store=other_store, product=product
        )
        other_business = create_business(name="Otro", slug="otro")
        foreign_store = create_inventory_store(business=other_business)
        foreign_product = create_inventory_product(business=other_business)
        create_inventory_item(
            business=other_business, store=foreign_store, product=foreign_product
        )
        self.assertEqual(
            inventory_summary(business=self.business)["tracked_items_count"], 2
        )
        self.assertEqual(
            inventory_summary(business=self.business, store=self.store)[
                "tracked_items_count"
            ],
            1,
        )
        with self.assertRaises(ValueError):
            inventory_summary(business=self.business, store=foreign_store)

    def test_movement_directions_grouping_occurred_at_and_bounds(self):
        first = self._item("Café")
        second = self._item("Té")
        expected = {
            "initial": "incoming",
            "sale_return": "incoming",
            "adjustment_in": "incoming",
            "transfer_in": "incoming",
            "sale": "outgoing",
            "purchase_return": "outgoing",
            "adjustment_out": "outgoing",
            "transfer_out": "outgoing",
            "loss": "outgoing",
        }
        for movement_type in expected:
            self._movement(first, movement_type)
        supplier = Supplier.objects.create(business=self.business, name="Proveedor")
        purchase = Purchase.objects.create(
            business=self.business,
            store=self.store,
            supplier=supplier,
            created_by=self.user,
            status="ordered",
            ordered_at=self.period.start,
        )
        purchase_line = PurchaseLine.objects.create(
            business=self.business,
            purchase=purchase,
            product=first.product,
            product_name=first.product.name,
            sku=first.product.sku,
            unit=first.product.unit,
            quantity_ordered=Decimal("1"),
            unit_cost=Decimal("1"),
        )
        receipt = PurchaseReceipt.objects.create(
            business=self.business,
            store=self.store,
            purchase=purchase,
            received_by=self.user,
            received_at=self.period.start,
            idempotency_key="781525fd-1c9d-470d-ad70-c8330081ba7a",
            idempotency_fingerprint="a" * 64,
        )
        receipt_line = PurchaseReceiptLine.objects.create(
            business=self.business,
            receipt=receipt,
            purchase_line=purchase_line,
            quantity_received=Decimal("1"),
        )
        self._movement(
            first,
            "purchase_receipt",
            purchase=purchase,
            purchase_line=purchase_line,
            purchase_receipt=receipt,
            purchase_receipt_line=receipt_line,
        )
        expected["purchase_receipt"] = "incoming"
        self._movement(first, "sale", quantity="2")
        self._movement(first, "stocktake", before="2", after="3")
        self._movement(first, "stocktake", before="3", after="1", quantity="2")
        self._movement(second, "sale", quantity="7")
        self._movement(first, "initial", when=self.period.start)
        self._movement(first, "initial", when=self.period.end)
        rows = inventory_movements_summary(business=self.business, period=self.period)
        for row in rows:
            if row["movement_type"] in expected:
                self.assertEqual(row["direction"], expected[row["movement_type"]])
        sale_rows = [row for row in rows if row["movement_type"] == "sale"]
        self.assertEqual(len(sale_rows), 2)
        coffee_sale = next(
            row for row in sale_rows if row["product_id"] == first.product_id
        )
        self.assertEqual(
            (coffee_sale["movement_count"], coffee_sale["quantity"]), (2, Decimal("3"))
        )
        self.assertEqual(
            {r["direction"] for r in rows if r["movement_type"] == "stocktake"},
            {"incoming", "outgoing"},
        )
        initial = next(row for row in rows if row["movement_type"] == "initial")
        self.assertEqual(initial["movement_count"], 2)

    def test_movement_store_and_business_scope(self):
        item = self._item("Centro")
        self._movement(item, "initial")
        other_business = create_business(name="Otro", slug="mov-otro")
        foreign_store = create_inventory_store(business=other_business)
        foreign_product = create_inventory_product(business=other_business)
        foreign_item = create_inventory_item(
            business=other_business, store=foreign_store, product=foreign_product
        )
        foreign_user = create_inventory_owner(business=other_business)
        StockMovement.objects.create(
            business=other_business,
            inventory_item=foreign_item,
            store=foreign_store,
            product=foreign_product,
            movement_type="initial",
            quantity=Decimal("1"),
            stock_before=Decimal("0"),
            stock_after=Decimal("1"),
            occurred_at=self.period.start,
            created_by=foreign_user,
        )
        self.assertEqual(
            len(
                inventory_movements_summary(
                    business=self.business, period=self.period, store=self.store
                )
            ),
            1,
        )
        with self.assertRaises(ValueError):
            inventory_movements_summary(
                business=self.business, period=self.period, store=foreign_store
            )
