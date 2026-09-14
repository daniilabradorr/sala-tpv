from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.business_config.models import POSSettings
from apps.inventory.models import InventoryItem, StockMovement
from apps.purchases.models import PurchaseReceipt, PurchaseReceiptLine, Supplier
from apps.purchases.services import (
    add_purchase_line,
    create_purchase,
    order_purchase,
    register_purchase_receipt,
)
from apps.sales.tests.factories import (
    create_sales_business,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


@skipUnlessDBFeature("has_select_for_update")
class PurchaseReceiptPostgreSQLLockingTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):  # noqa: N802
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.supplier = Supplier.objects.create(
            business=self.business, name="Proveedor concurrente"
        )
        POSSettings.objects.create(business=self.business, enable_stock_control=True)
        tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(business=self.business, tax=tax)
        self.purchase = create_purchase(
            business=self.business,
            store=self.store,
            supplier=self.supplier,
            created_by=self.user,
        )
        self.line = add_purchase_line(
            business=self.business,
            purchase=self.purchase,
            product=self.product,
            quantity=Decimal("10.000"),
            unit_cost=Decimal("4.00"),
            user=self.user,
        )
        order_purchase(
            business=self.business,
            purchase=self.purchase,
            ordered_by=self.user,
        )

    def _concurrent_receive(self, *, key, quantity, barrier):
        connections.close_all()
        try:
            barrier.wait(timeout=5)
            receipt = register_purchase_receipt(
                business=self.business,
                purchase=self.purchase,
                received_by=self.user,
                lines=[{"purchase_line": self.line, "quantity_received": quantity}],
                idempotency_key=key,
            )
            return receipt.pk
        finally:
            connections.close_all()

    def test_concurrent_receipts_cannot_over_receive(self):
        barrier = Barrier(2)
        keys = [uuid4(), uuid4()]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    self._concurrent_receive,
                    key=key,
                    quantity=Decimal("7.000"),
                    barrier=barrier,
                )
                for key in keys
            ]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except ValidationError:
                outcomes.append("validation-error")

        self.assertEqual(outcomes.count("validation-error"), 1)
        self.line.refresh_from_db()
        inventory = InventoryItem.objects.get(product=self.product, store=self.store)
        self.assertEqual(self.line.quantity_received, Decimal("7.000"))
        self.assertEqual(inventory.current_stock, Decimal("7.000"))
        self.assertEqual(PurchaseReceipt.objects.count(), 1)
        self.assertEqual(PurchaseReceiptLine.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_concurrent_same_key_returns_one_receipt(self):
        barrier = Barrier(2)
        key = uuid4()
        with ThreadPoolExecutor(max_workers=2) as executor:
            receipt_ids = list(
                executor.map(
                    lambda _index: self._concurrent_receive(
                        key=key, quantity=Decimal("4.000"), barrier=barrier
                    ),
                    range(2),
                )
            )

        self.assertEqual(receipt_ids[0], receipt_ids[1])
        inventory = InventoryItem.objects.get(product=self.product, store=self.store)
        self.assertEqual(inventory.current_stock, Decimal("4.000"))
        self.assertEqual(PurchaseReceipt.objects.count(), 1)
        self.assertEqual(PurchaseReceiptLine.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)
