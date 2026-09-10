from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event

from django.db import connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.sales.models import Sale, SaleReturnStatusChoices, SaleStatusChoices
from apps.inventory.models import StockMovement
from apps.sales.services import (
    _lock_sale,
    complete_sale,
    complete_sale_return,
    recalculate_sale,
)
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_business,
    create_sales_inventory_item,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


@skipUnlessDBFeature("has_select_for_update")
class SalePostgreSQLLockingTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            cash_register=None,
            cash_session=None,
            customer=None,
            closed_by=None,
        )

    def test_recalculate_sale_with_nullable_related_rows(self):
        """PostgreSQL must not try to lock nullable OUTER JOIN relations."""

        recalculated = recalculate_sale(business=self.business, sale=self.sale)

        self.assertEqual(recalculated.pk, self.sale.pk)
        self.assertIsNone(recalculated.cash_register)
        self.assertIsNone(recalculated.cash_session)
        self.assertIsNone(recalculated.customer)
        self.assertIsNone(recalculated.closed_by)
        self.assertEqual(recalculated.business, self.business)
        self.assertEqual(recalculated.store, self.store)
        self.assertEqual(recalculated.opened_by, self.user)

    def test_sale_row_lock_serializes_two_database_connections(self):
        first_has_lock = Event()
        second_is_attempting_lock = Event()
        second_has_lock = Event()
        release_first = Event()

        def first_transaction():
            connections.close_all()
            try:
                with transaction.atomic():
                    sale = Sale.objects.get(pk=self.sale.pk)
                    locked_sale = _lock_sale(business=self.business, sale=sale)
                    locked_sale.status = SaleStatusChoices.CANCELLED
                    locked_sale.save(update_fields=["status", "updated_at"])
                    first_has_lock.set()
                    if not release_first.wait(timeout=5):
                        raise AssertionError(
                            "Timed out waiting to release the first lock"
                        )
            finally:
                connections.close_all()

        def second_transaction():
            connections.close_all()
            try:
                if not first_has_lock.wait(timeout=5):
                    raise AssertionError(
                        "The first connection did not acquire the lock"
                    )
                with transaction.atomic():
                    sale = Sale.objects.get(pk=self.sale.pk)
                    second_is_attempting_lock.set()
                    locked_sale = _lock_sale(business=self.business, sale=sale)
                    second_has_lock.set()
                    return locked_sale.status
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(first_transaction)
            second = executor.submit(second_transaction)
            self.assertTrue(first_has_lock.wait(timeout=5))
            self.assertTrue(second_is_attempting_lock.wait(timeout=5))
            try:
                self.assertFalse(
                    second_has_lock.wait(timeout=0.2),
                    "The second connection bypassed the Sale row lock",
                )
            finally:
                release_first.set()

            first.result(timeout=5)
            self.assertEqual(second.result(timeout=5), SaleStatusChoices.CANCELLED)
            self.assertTrue(second_has_lock.is_set())

    def test_concurrent_complete_sale_decreases_stock_only_once(self):
        create_pos_settings(
            business=self.business,
            require_open_cash_register=False,
            enable_stock_control=True,
        )
        tax = create_sales_tax(business=self.business)
        product = create_sales_product(business=self.business, tax=tax)
        inventory_item = create_sales_inventory_item(
            business=self.business,
            store=self.store,
            product=product,
            current_stock=Decimal("20.000"),
        )
        create_sale_line(
            business=self.business,
            sale=self.sale,
            product=product,
            quantity=Decimal("2.000"),
        )
        start = Barrier(2)

        def complete_from_separate_connection(_worker_number):
            connections.close_all()
            try:
                start.wait(timeout=5)
                completed = complete_sale(
                    business=self.business,
                    sale=self.sale,
                    closed_by=self.user,
                )
                return completed.status
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(complete_from_separate_connection, range(2)))

        self.assertEqual(statuses, [SaleStatusChoices.COMPLETED] * 2)
        inventory_item.refresh_from_db()
        self.assertEqual(inventory_item.current_stock, Decimal("18.000"))
        self.assertEqual(
            StockMovement.objects.filter(
                sale=self.sale,
                movement_type=StockMovement.TYPE_SALE,
            ).count(),
            1,
        )

    def test_complete_sale_return_with_nullable_original_line_product_join(self):
        create_pos_settings(
            business=self.business,
            require_open_cash_register=False,
            require_pin_for_sensitive_actions=False,
            enable_stock_control=True,
        )
        tax = create_sales_tax(business=self.business)
        product = create_sales_product(business=self.business, tax=tax)
        inventory_item = create_sales_inventory_item(
            business=self.business,
            store=self.store,
            product=product,
            current_stock=Decimal("20.000"),
        )
        original_line = create_sale_line(
            business=self.business,
            sale=self.sale,
            product=product,
            quantity=Decimal("2.000"),
        )
        complete_sale(
            business=self.business,
            sale=self.sale,
            closed_by=self.user,
        )
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=original_line,
            quantity=Decimal("1.000"),
            restock=True,
        )

        completed_return = complete_sale_return(
            business=self.business,
            return_doc=return_doc,
            completed_by=self.user,
        )

        self.assertEqual(completed_return.status, SaleReturnStatusChoices.COMPLETED)
        inventory_item.refresh_from_db()
        self.assertEqual(inventory_item.current_stock, Decimal("19.000"))
        self.assertEqual(
            StockMovement.objects.filter(
                sale_return=return_doc,
                movement_type=StockMovement.TYPE_SALE_RETURN,
            ).count(),
            1,
        )
