"""Real PostgreSQL inventory races through complete_sale; no success mocks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.cash_register.models import CashRegister, CashSession
from apps.inventory.models import InventoryItem, StockMovement
from apps.sales.models import Sale, SaleStatusChoices
from apps.sales.services import complete_sale
from tests.performance.dataset import Dataset


@skipUnlessDBFeature("has_select_for_update")
class SaleInventoryPostgreSQLTests(TransactionTestCase):
    def setUp(self):
        self.dataset = Dataset(2, label="stock-concurrency")

    def item(self, index=0):
        return InventoryItem.objects.get(
            store=self.dataset.store, product=self.dataset.products[index]
        )

    def complete(self, sale):
        return complete_sale(
            business=self.dataset.business, sale=sale, closed_by=self.dataset.user
        )

    def run_sales(self, *sales):
        barrier = Barrier(len(sales))

        def worker(sale):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                barrier.wait(timeout=5)
                self.complete(sale)
                return True
            except ValidationError:
                return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(sales)) as pool:
            futures = [pool.submit(worker, sale) for sale in sales]
            return [future.result(timeout=15) for future in futures]

    def second_register_sale(self, size=1):
        register = CashRegister.objects.create(
            business=self.dataset.business,
            store=self.dataset.store,
            name="Second",
            code="SECOND",
        )
        session = CashSession.objects.create(
            business=self.dataset.business,
            store=self.dataset.store,
            cash_register=register,
            opened_by=self.dataset.user,
        )
        sale, lines = self.dataset.sale(size)
        sale.cash_register, sale.cash_session = register, session
        sale.save()
        return sale, lines

    def test_two_sales_in_two_registers_do_not_lose_stock(self):
        first, _ = self.dataset.sale(1)
        second, _ = self.second_register_sale()
        self.assertEqual(self.run_sales(first, second), [True, True])
        self.assertEqual(self.item().current_stock, 998)
        movements = list(StockMovement.objects.order_by("stock_before"))
        self.assertEqual(len(movements), 2)
        self.assertEqual({m.sale_id for m in movements}, {first.pk, second.pk})
        self.assertEqual(
            {(m.stock_before, m.stock_after) for m in movements},
            {(1000, 999), (999, 998)},
        )

    def test_last_unit_can_only_be_sold_once_across_registers(self):
        item = self.item()
        item.current_stock = 1
        item.save()
        first, _ = self.dataset.sale(1)
        second, _ = self.second_register_sale()
        self.assertEqual(sorted(self.run_sales(first, second)), [False, True])
        self.assertEqual(self.item().current_stock, 0)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(
            Sale.objects.filter(status=SaleStatusChoices.COMPLETED).count(), 1
        )
        self.assertEqual(Sale.objects.filter(status=SaleStatusChoices.OPEN).count(), 1)

    def test_same_sale_retry_is_concurrently_idempotent(self):
        sale, _ = self.dataset.sale(2)
        self.assertEqual(self.run_sales(sale, sale), [True, True])
        self.assertEqual(StockMovement.objects.filter(sale=sale).count(), 2)
        for index in range(2):
            self.assertEqual(self.item(index).current_stock, 999)

    def test_opposite_line_creation_orders_keep_product_lock_order(self):
        first, _ = self.dataset.sale(2)
        second, _ = self.second_register_sale(size=0)
        from apps.sales.services import add_sale_line

        for product in reversed(self.dataset.products):
            add_sale_line(
                business=self.dataset.business,
                sale=second,
                product=product,
                quantity=1,
                user=self.dataset.user,
            )
        self.assertEqual(self.run_sales(first, second), [True, True])
        self.assertEqual(StockMovement.objects.count(), 4)
        for index in range(2):
            self.assertEqual(self.item(index).current_stock, 998)

    def test_locked_read_sees_change_committed_after_preload(self):
        sale, _ = self.dataset.sale(1)
        held, release, about_to_lock = Event(), Event(), Event()

        def hold():
            connections.close_all()
            try:
                with transaction.atomic():
                    item = InventoryItem.objects.select_for_update().get(
                        pk=self.item().pk
                    )
                    item.current_stock = 0
                    item.save()
                    held.set()
                    if not release.wait(10):
                        raise AssertionError("Test lock was not released")
            finally:
                connections.close_all()

        def attempt():
            connections.close_all()

            def observe(execute, sql, params, many, context):
                if 'FROM "inventory_inventoryitem"' in sql and "FOR UPDATE" in sql:
                    about_to_lock.set()
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(observe):
                    self.complete(sale)
                return True
            except ValidationError:
                return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(hold)
            try:
                self.assertTrue(held.wait(5))
                worker = pool.submit(attempt)
                self.assertTrue(about_to_lock.wait(5))
            finally:
                release.set()
            holder.result(timeout=5)
            self.assertFalse(worker.result(timeout=10))
        self.assertEqual(self.item().current_stock, 0)
        self.assertFalse(StockMovement.objects.filter(sale=sale).exists())
        sale.refresh_from_db()
        self.assertEqual(sale.status, SaleStatusChoices.OPEN)
