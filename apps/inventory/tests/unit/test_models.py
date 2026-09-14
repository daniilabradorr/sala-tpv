"""Tests unitarios de modelos de inventory."""

from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.inventory.models import StockAdjustment, StockAdjustmentLine, StockMovement
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
    PurchaseStatusChoices,
    Supplier,
)
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_product,
    create_sales_tax,
)


class InventoryModelsTests(TestCase):
    """Valida properties y reglas de validacion en modelos de inventory."""

    def setUp(self):  # noqa: N802
        """Crea datos base para pruebas unitarias de modelo."""
        self.business = create_business(
            name="Negocio Inventory Models",
            slug="negocio-inventory-models",
        )
        self.store = create_inventory_store(
            business=self.business,
            name="Tienda Models",
            code="INVMOD1",
        )
        self.product = create_inventory_product(
            business=self.business,
            name="Patatas Fritas",
        )
        self.user = create_inventory_owner(business=self.business)

    def test_inventory_item_available_stock_property(self):
        """available_stock debe devolver current_stock - reserved_stock."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("10.000"),
            reserved_stock=Decimal("3.000"),
        )

        self.assertEqual(item.available_stock, Decimal("7.000"))

    def test_inventory_item_needs_restock_property(self):
        """needs_restock debe ser True cuando available_stock <= minimum_stock."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("2.000"),
            minimum_stock=Decimal("2.000"),
        )

        self.assertTrue(item.needs_restock)

    def test_stock_adjustment_clean_requires_confirmed_at_when_confirmed(self):
        """Un ajuste confirmado debe tener fecha de confirmacion."""
        adjustment = StockAdjustment(
            business=self.business,
            store=self.store,
            status=StockAdjustment.STATUS_CONFIRMED,
            reason=StockAdjustment.REASON_STOCKTAKE,
            created_by=self.user,
            confirmed_by=self.user,
        )

        with self.assertRaises(ValidationError):
            adjustment.full_clean()

    def test_stock_adjustment_is_confirmed_property(self):
        """Property is_confirmed debe reflejar correctamente el estado."""
        adjustment = StockAdjustment.objects.create(
            business=self.business,
            store=self.store,
            status=StockAdjustment.STATUS_CONFIRMED,
            reason=StockAdjustment.REASON_OTHER,
            confirmed_at=timezone.now(),
            created_by=self.user,
            confirmed_by=self.user,
        )

        self.assertTrue(adjustment.is_confirmed)
        self.assertFalse(adjustment.is_draft)

    def test_stock_movement_direction_properties(self):
        """is_incoming/is_outgoing deben mapear correctamente tipos de movimiento."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("5.000"),
        )

        incoming = StockMovement.objects.create(
            business=self.business,
            inventory_item=item,
            store=self.store,
            product=self.product,
            movement_type=StockMovement.TYPE_ADJUSTMENT_IN,
            quantity=Decimal("1.000"),
            stock_before=Decimal("5.000"),
            stock_after=Decimal("6.000"),
            created_by=self.user,
        )
        outgoing = StockMovement.objects.create(
            business=self.business,
            inventory_item=item,
            store=self.store,
            product=self.product,
            movement_type=StockMovement.TYPE_ADJUSTMENT_OUT,
            quantity=Decimal("2.000"),
            stock_before=Decimal("6.000"),
            stock_after=Decimal("4.000"),
            created_by=self.user,
        )

        self.assertTrue(incoming.is_incoming)
        self.assertFalse(incoming.is_outgoing)
        self.assertFalse(outgoing.is_incoming)
        self.assertTrue(outgoing.is_outgoing)

    def test_inventory_item_needs_restock_uses_available_stock(self):
        """needs_restock debe usar current_stock - reserved_stock."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("10.000"),
            reserved_stock=Decimal("8.000"),
            minimum_stock=Decimal("3.000"),
        )

        self.assertEqual(item.available_stock, Decimal("2.000"))
        self.assertTrue(item.needs_restock)

    def test_stock_adjustment_line_allows_negative_system_stock(self):
        """Ajuste desde stock negativo debe calcular difference correctamente."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("-3.000"),
        )
        adjustment = StockAdjustment.objects.create(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            created_by=self.user,
        )

        line = StockAdjustmentLine.objects.create(
            adjustment=adjustment,
            inventory_item=item,
            product=self.product,
            system_stock=Decimal("-3.000"),
            counted_stock=Decimal("2.000"),
        )

        self.assertEqual(line.difference, Decimal("5.000"))

    def test_stock_adjustment_line_rejects_negative_counted_stock(self):
        """El stock contado físicamente no puede ser negativo."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("-3.000"),
        )
        adjustment = StockAdjustment.objects.create(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            created_by=self.user,
        )

        with self.assertRaises(ValidationError):
            StockAdjustmentLine.objects.create(
                adjustment=adjustment,
                inventory_item=item,
                product=self.product,
                system_stock=Decimal("-3.000"),
                counted_stock=Decimal("-1.000"),
            )


class StockMovementPurchasesIntegrityTests(TestCase):
    """Protege la cadena fuerte desde una recepción hasta su movimiento."""

    def setUp(self):  # noqa: N802
        self.business = create_business(name="Compras", slug="inventory-purchases")
        self.store = create_inventory_store(business=self.business)
        self.user = create_inventory_owner(business=self.business)
        self.product = create_inventory_product(business=self.business)
        self.item = create_inventory_item(
            business=self.business, store=self.store, product=self.product
        )
        self.supplier = Supplier.objects.create(
            business=self.business, name="Proveedor"
        )
        self.purchase = Purchase.objects.create(
            business=self.business,
            store=self.store,
            supplier=self.supplier,
            created_by=self.user,
            status=PurchaseStatusChoices.ORDERED,
            ordered_at=timezone.now(),
        )
        self.purchase_line = PurchaseLine.objects.create(
            business=self.business,
            purchase=self.purchase,
            product=self.product,
            product_name=self.product.name,
            unit="ud",
            quantity_ordered=Decimal("10.000"),
            quantity_received=Decimal("0.000"),
            unit_cost=Decimal("4.00"),
        )
        self.receipt = PurchaseReceipt.objects.create(
            business=self.business,
            store=self.store,
            purchase=self.purchase,
            received_by=self.user,
            idempotency_key=uuid4(),
            idempotency_fingerprint="a" * 64,
        )
        self.receipt_line = PurchaseReceiptLine.objects.create(
            business=self.business,
            receipt=self.receipt,
            purchase_line=self.purchase_line,
            quantity_received=Decimal("3.000"),
        )

    def movement(self, **overrides):
        values = {
            "business": self.business,
            "inventory_item": self.item,
            "store": self.store,
            "product": self.product,
            "movement_type": StockMovement.TYPE_PURCHASE_RECEIPT,
            "quantity": Decimal("3.000"),
            "stock_before": Decimal("0.000"),
            "stock_after": Decimal("3.000"),
            "purchase": self.purchase,
            "purchase_line": self.purchase_line,
            "purchase_receipt": self.receipt,
            "purchase_receipt_line": self.receipt_line,
        }
        values.update(overrides)
        return StockMovement(**values)

    def create_purchase(self, *, store=None, suffix="other"):
        return Purchase.objects.create(
            business=self.business,
            store=store or self.store,
            supplier=self.supplier,
            created_by=self.user,
            status=PurchaseStatusChoices.ORDERED,
            ordered_at=timezone.now(),
            reference=suffix,
        )

    def create_purchase_line(self, *, purchase=None, suffix="other"):
        return PurchaseLine.objects.create(
            business=self.business,
            purchase=purchase or self.purchase,
            product=self.product,
            product_name=f"Producto {suffix}",
            unit="ud",
            quantity_ordered=Decimal("10.000"),
            unit_cost=Decimal("4.00"),
        )

    def create_receipt(self, *, purchase=None, store=None):
        return PurchaseReceipt.objects.create(
            business=self.business,
            store=store or self.store,
            purchase=purchase or self.purchase,
            received_by=self.user,
            idempotency_key=uuid4(),
            idempotency_fingerprint="c" * 64,
        )

    def test_coherent_purchase_receipt_movement_saves(self):
        movement = self.movement()
        movement.full_clean()
        movement.save()
        self.assertEqual(movement.purchase_receipt_line, self.receipt_line)

    def test_purchase_receipt_requires_all_strong_relations(self):
        for field in (
            "purchase",
            "purchase_line",
            "purchase_receipt",
            "purchase_receipt_line",
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.movement(**{field: None}).full_clean()

    def test_receipt_relations_require_purchase_receipt_type(self):
        with self.assertRaises(ValidationError):
            self.movement(movement_type=StockMovement.TYPE_ADJUSTMENT_IN).full_clean()

    def test_purchase_and_line_alone_are_allowed_for_future_types(self):
        movement = self.movement(
            movement_type=StockMovement.TYPE_ADJUSTMENT_IN,
            purchase_receipt=None,
            purchase_receipt_line=None,
        )
        movement.full_clean()

    def test_rejects_wrong_quantity_or_product(self):
        other_product = create_inventory_product(
            business=self.business, name="Producto distinto"
        )
        for overrides in (
            {"quantity": Decimal("2.000"), "stock_after": Decimal("2.000")},
            {"product": other_product},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.movement(**overrides).full_clean()

    def test_rejects_cross_tenant_purchase(self):
        other_business = create_business(name="Ajeno", slug="purchase-foreign")
        other_store = create_inventory_store(business=other_business)
        other_user = create_inventory_owner(business=other_business)
        other_supplier = Supplier.objects.create(
            business=other_business, name="Proveedor ajeno"
        )
        other_purchase = Purchase.objects.create(
            business=other_business,
            store=other_store,
            supplier=other_supplier,
            created_by=other_user,
        )
        with self.assertRaises(ValidationError):
            self.movement(purchase=other_purchase).full_clean()

    def test_rejects_purchase_line_from_another_business(self):
        other_business = create_business(name="Ajeno línea", slug="foreign-line")
        other_store = create_inventory_store(business=other_business)
        other_user = create_inventory_owner(business=other_business)
        other_product = create_inventory_product(business=other_business)
        other_supplier = Supplier.objects.create(
            business=other_business, name="Proveedor ajeno línea"
        )
        other_purchase = Purchase.objects.create(
            business=other_business,
            store=other_store,
            supplier=other_supplier,
            created_by=other_user,
        )
        other_line = PurchaseLine.objects.create(
            business=other_business,
            purchase=other_purchase,
            product=other_product,
            product_name=other_product.name,
            unit="ud",
            quantity_ordered=Decimal("3.000"),
            unit_cost=Decimal("4.00"),
        )

        with self.assertRaises(ValidationError) as error:
            self.movement(purchase_line=other_line).full_clean()

        self.assertIn("purchase_line", error.exception.message_dict)

    def test_rejects_purchase_line_from_another_purchase(self):
        other_line = self.create_purchase_line(purchase=self.create_purchase())

        with self.assertRaises(ValidationError) as error:
            self.movement(purchase_line=other_line).full_clean()

        self.assertIn("purchase_line", error.exception.message_dict)

    def test_rejects_purchase_receipt_from_another_purchase(self):
        other_receipt = self.create_receipt(purchase=self.create_purchase())

        with self.assertRaises(ValidationError) as error:
            self.movement(purchase_receipt=other_receipt).full_clean()

        self.assertIn("purchase_receipt", error.exception.message_dict)

    def test_rejects_purchase_receipt_from_another_store(self):
        other_store = create_inventory_store(business=self.business)
        other_purchase = self.create_purchase(store=other_store)
        other_receipt = self.create_receipt(purchase=other_purchase, store=other_store)

        with self.assertRaises(ValidationError) as error:
            self.movement(
                purchase=other_purchase, purchase_receipt=other_receipt
            ).full_clean()

        self.assertIn("purchase_receipt", error.exception.message_dict)

    def test_rejects_purchase_receipt_line_from_another_receipt(self):
        other_receipt = self.create_receipt()
        other_receipt_line = PurchaseReceiptLine.objects.create(
            business=self.business,
            receipt=other_receipt,
            purchase_line=self.purchase_line,
            quantity_received=Decimal("3.000"),
        )

        with self.assertRaises(ValidationError) as error:
            self.movement(purchase_receipt_line=other_receipt_line).full_clean()

        self.assertIn("purchase_receipt_line", error.exception.message_dict)

    def test_rejects_receipt_line_pointing_to_another_purchase_line(self):
        other_line = self.create_purchase_line()
        receipt_line_for_other_line = PurchaseReceiptLine.objects.create(
            business=self.business,
            receipt=self.receipt,
            purchase_line=other_line,
            quantity_received=Decimal("3.000"),
        )

        with self.assertRaises(ValidationError) as error:
            self.movement(
                purchase_receipt_line=receipt_line_for_other_line
            ).full_clean()

        self.assertIn("purchase_receipt_line", error.exception.message_dict)

    def test_database_rejects_two_movements_for_same_receipt_line(self):
        self.movement().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockMovement.objects.bulk_create([self.movement()])


class StockMovementSalesIntegrityTests(TestCase):
    """Protege las relaciones Sales que originan un movimiento de stock."""

    def setUp(self):  # noqa: N802
        self.business = create_business(
            name="Inventory Sales Relations", slug="inventory-sales-relations"
        )
        self.store = create_inventory_store(business=self.business)
        self.user = create_inventory_owner(business=self.business)
        self.tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(business=self.business, tax=self.tax)
        self.item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("10.000"),
        )
        self.sale = create_sale(
            business=self.business, store=self.store, opened_by=self.user
        )
        self.line = create_sale_line(
            business=self.business, sale=self.sale, product=self.product
        )
        self.return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
        )
        self.return_line = create_sale_return_line(
            business=self.business,
            return_doc=self.return_doc,
            original_line=self.line,
        )

    def movement(self, **overrides):
        values = {
            "business": self.business,
            "inventory_item": self.item,
            "store": self.store,
            "product": self.product,
            "movement_type": StockMovement.TYPE_SALE_RETURN,
            "quantity": Decimal("1.000"),
            "stock_before": Decimal("10.000"),
            "stock_after": Decimal("11.000"),
        }
        values.update(overrides)
        return StockMovement(**values)

    def test_rejects_sale_from_another_business(self):
        other_business = create_business(
            name="Other Sales Relations", slug="other-sales-relations"
        )
        other_store = create_inventory_store(business=other_business)
        other_user = create_inventory_owner(business=other_business)
        other_sale = create_sale(
            business=other_business, store=other_store, opened_by=other_user
        )

        with self.assertRaises(ValidationError):
            self.movement(sale=other_sale).full_clean()

    def test_rejects_sale_line_from_another_sale(self):
        other_sale = create_sale(
            business=self.business, store=self.store, opened_by=self.user
        )
        other_line = create_sale_line(
            business=self.business, sale=other_sale, product=self.product
        )

        with self.assertRaises(ValidationError):
            self.movement(sale=self.sale, sale_line=other_line).full_clean()

    def test_rejects_return_from_another_sale(self):
        other_sale = create_sale(
            business=self.business, store=self.store, opened_by=self.user
        )
        other_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=other_sale,
            created_by=self.user,
        )

        with self.assertRaises(ValidationError):
            self.movement(sale=self.sale, sale_return=other_return).full_clean()

    def test_rejects_return_line_from_another_return(self):
        other_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
        )

        with self.assertRaises(ValidationError):
            self.movement(
                sale=self.sale,
                sale_return=self.return_doc,
                sale_return_line=create_sale_return_line(
                    business=self.business,
                    return_doc=other_return,
                    original_line=self.line,
                ),
            ).full_clean()

    def test_rejects_return_line_product_without_sale_line(self):
        other_product = create_sales_product(
            business=self.business, tax=self.tax, name="Otro producto"
        )
        other_item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=other_product,
        )

        with self.assertRaises(ValidationError):
            self.movement(
                inventory_item=other_item,
                product=other_product,
                sale=self.sale,
                sale_return=self.return_doc,
                sale_return_line=self.return_line,
                sale_line=None,
            ).full_clean()

    def test_accepts_fully_coherent_sales_references(self):
        movement = self.movement(
            sale=self.sale,
            sale_line=self.line,
            sale_return=self.return_doc,
            sale_return_line=self.return_line,
        )

        movement.save()

        self.assertIsNotNone(movement.pk)
