"""Tests unitarios de modelos de inventory."""

from decimal import Decimal

from django.core.exceptions import ValidationError
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
