"""Tests unitarios de modelos de inventory."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.inventory.models import StockAdjustment, StockMovement
from apps.inventory.tests.factories import (
    create_business,
    create_inventory_item,
    create_inventory_owner,
    create_inventory_product,
    create_inventory_store,
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
        """needs_restock debe ser True cuando current_stock <= minimum_stock."""
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
