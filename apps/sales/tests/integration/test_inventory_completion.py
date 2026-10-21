"""Inventory invariants at the public Sale completion boundary."""

from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models.signals import pre_save, post_save
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.inventory import services as inventory_services
from apps.inventory.models import InventoryItem, StockMovement
from apps.sales.models import SaleStatusChoices
from apps.sales.services import add_sale_line, complete_sale
from apps.sales.tests.factories import create_sales_inventory_item, create_sales_store
from tests.performance.dataset import Dataset


class SaleInventoryCompletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset(60, label="inventory-completion")

    def complete(self, sale):
        return complete_sale(
            business=self.dataset.business, sale=sale, closed_by=self.dataset.user
        )

    def item(self, index=0):
        return InventoryItem.objects.get(
            store=self.dataset.store, product=self.dataset.products[index]
        )

    def assert_untouched(self, sale, size):
        sale.refresh_from_db()
        self.assertEqual(sale.status, SaleStatusChoices.OPEN)
        self.assertFalse(StockMovement.objects.filter(sale=sale).exists())
        for index in range(size):
            self.assertEqual(self.item(index).current_stock, Decimal("1000"))

    def test_one_twenty_and_fifty_products_preserve_every_line_trace(self):
        for size in (1, 20, 50):
            with self.subTest(size=size):
                before = {i: self.item(i).current_stock for i in range(size)}
                sale, lines = self.dataset.sale(size)
                self.complete(sale)
                movements = list(
                    StockMovement.objects.filter(sale=sale).order_by("sale_line_id")
                )
                self.assertEqual(len(movements), size)
                self.assertEqual(
                    {m.sale_line_id for m in movements}, {line.pk for line in lines}
                )
                self.assertEqual(len({m.operation_id for m in movements}), 1)
                for movement in movements:
                    index = next(
                        i
                        for i, p in enumerate(self.dataset.products)
                        if p.pk == movement.product_id
                    )
                    self.assertEqual(movement.business_id, self.dataset.business.pk)
                    self.assertEqual(movement.store_id, self.dataset.store.pk)
                    self.assertEqual(movement.stock_before, before[index])
                    self.assertEqual(movement.stock_after, before[index] - 1)
                    self.assertEqual(self.item(index).current_stock, before[index] - 1)
                    self.assertEqual(
                        movement.reference_id, f"{sale.pk}:{movement.sale_line_id}"
                    )

    def test_duplicate_product_lines_keep_cumulative_snapshots_and_idempotency(self):
        sale, lines = self.dataset.sale(1)
        second = add_sale_line(
            business=self.dataset.business,
            sale=sale,
            product=self.dataset.products[0],
            quantity=Decimal("2"),
            user=self.dataset.user,
        )
        self.complete(sale)
        self.complete(sale)
        movements = list(
            StockMovement.objects.filter(sale=sale).order_by("sale_line_id")
        )
        self.assertEqual(
            [(m.sale_line_id, m.stock_before, m.stock_after) for m in movements],
            [
                (lines[0].pk, Decimal("1000"), Decimal("999")),
                (second.pk, Decimal("999"), Decimal("997")),
            ],
        )
        self.assertEqual(self.item().current_stock, Decimal("997"))

    def test_duplicate_product_total_cannot_overdraw_available_stock(self):
        sale, _ = self.dataset.sale(1)
        add_sale_line(
            business=self.dataset.business,
            sale=sale,
            product=self.dataset.products[0],
            quantity=Decimal("1"),
            user=self.dataset.user,
        )
        item = self.item()
        item.current_stock = Decimal("1")
        item.save()
        with self.assertRaises(ValidationError):
            self.complete(sale)
        item.refresh_from_db()
        self.assertEqual(item.current_stock, 1)
        self.assertFalse(StockMovement.objects.filter(sale=sale).exists())

    def test_reserved_stock_is_not_available(self):
        sale, _ = self.dataset.sale(1)
        item = self.item()
        item.reserved_stock = item.current_stock
        item.save()
        with self.assertRaises(ValidationError):
            self.complete(sale)
        self.assert_untouched(sale, 1)

    def test_allow_negative_is_explicit_and_traced(self):
        self.dataset.settings.allow_sale_without_stock = True
        self.dataset.settings.save()
        sale, _ = self.dataset.sale(1)
        item = self.item()
        item.current_stock = 0
        item.save()
        self.complete(sale)
        self.assertEqual(self.item().current_stock, -1)
        movement = StockMovement.objects.get(sale=sale)
        self.assertEqual((movement.stock_before, movement.stock_after), (0, -1))

    def test_disabled_control_does_not_query_inventory(self):
        self.dataset.settings.enable_stock_control = False
        self.dataset.settings.save()
        sale, _ = self.dataset.sale(20)
        with CaptureQueriesContext(connection) as queries:
            self.complete(sale)
        self.assertFalse(any('"inventory_inventoryitem"' in q["sql"] for q in queries))
        self.assertFalse(StockMovement.objects.filter(sale=sale).exists())

    def test_untracked_products_do_not_query_inventory(self):
        product = self.dataset.products[0]
        product.track_stock = False
        product.save()
        sale, _ = self.dataset.sale(1)
        with CaptureQueriesContext(connection) as queries:
            self.complete(sale)
        self.assertFalse(any('"inventory_inventoryitem"' in q["sql"] for q in queries))
        self.assertFalse(StockMovement.objects.filter(sale=sale).exists())

    def test_inactive_or_absent_item_blocks_sale(self):
        for inactive in (True, False):
            with self.subTest(inactive=inactive):
                sale, _ = self.dataset.sale(1)
                item = self.item()
                item.is_active = not inactive
                item.save()
                if not inactive:
                    item.delete()
                with self.assertRaises(ValidationError):
                    self.complete(sale)
                self.assertFalse(StockMovement.objects.filter(sale=sale).exists())

    def test_inventory_of_another_store_cannot_satisfy_sale(self):
        sale, _ = self.dataset.sale(1)
        self.item().delete()
        store = create_sales_store(business=self.dataset.business)
        foreign = create_sales_inventory_item(
            business=self.dataset.business,
            store=store,
            product=self.dataset.products[0],
            current_stock=1000,
        )
        with self.assertRaises(ValidationError):
            self.complete(sale)
        foreign.refresh_from_db()
        self.assertEqual(foreign.current_stock, 1000)
        self.assertFalse(StockMovement.objects.filter(sale=sale).exists())

    def test_foreign_business_sale_is_rejected(self):
        foreign = Dataset(1, label="inventory-foreign-business")
        sale, _ = self.dataset.sale(1)
        with self.assertRaises(ValidationError):
            complete_sale(business=foreign.business, sale=sale, closed_by=foreign.user)
        self.assert_untouched(sale, 1)

    def test_failure_after_first_movement_rolls_back_and_retry_is_safe(self):
        sale, _ = self.dataset.sale(3)
        original = inventory_services._create_stock_movement
        calls = []

        def fail_second(**kwargs):
            calls.append(kwargs["sale_line"].pk)
            if len(calls) == 2:
                raise RuntimeError("synthetic movement failure")
            return original(**kwargs)

        with patch.object(
            inventory_services, "_create_stock_movement", side_effect=fail_second
        ):
            with self.assertRaises(RuntimeError):
                self.complete(sale)
        self.assertEqual(len(calls), 2)
        self.assert_untouched(sale, 3)
        self.complete(sale)
        self.complete(sale)
        self.assertEqual(StockMovement.objects.filter(sale=sale).count(), 3)
        for index in range(3):
            self.assertEqual(self.item(index).current_stock, 999)

    def test_save_full_clean_and_signals_are_preserved_per_line(self):
        sale, _ = self.dataset.sale(3)
        events = []

        def receiver(sender, instance, **kwargs):
            events.append(sender.__name__)

        for signal in (pre_save, post_save):
            for model in (InventoryItem, StockMovement):
                signal.connect(receiver, sender=model, weak=False)
        item_clean, movement_clean = InventoryItem.full_clean, StockMovement.full_clean
        try:
            with (
                patch.object(
                    InventoryItem, "full_clean", autospec=True, side_effect=item_clean
                ) as item_calls,
                patch.object(
                    StockMovement,
                    "full_clean",
                    autospec=True,
                    side_effect=movement_clean,
                ) as movement_calls,
            ):
                self.complete(sale)
            self.assertEqual(item_calls.call_count, 3)
            self.assertEqual(movement_calls.call_count, 3)
            self.assertEqual(events.count("InventoryItem"), 6)
            self.assertEqual(events.count("StockMovement"), 6)
        finally:
            for signal in (pre_save, post_save):
                for model in (InventoryItem, StockMovement):
                    signal.disconnect(receiver, sender=model)
