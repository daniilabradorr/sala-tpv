"""Tests unitarios de formularios de inventory."""

from decimal import Decimal

from django.test import TestCase

from apps.inventory.forms import (
    InventoryItemCreateForm,
    InitialStockForm,
    StockAdjustmentConfirmForm,
    StockAdjustmentLineForm,
)
from apps.inventory.models import StockAdjustment
from apps.inventory.services import add_stock_adjustment_line, create_stock_adjustment
from apps.inventory.tests.factories import (
    create_business,
    create_inventory_item,
    create_inventory_product,
    create_inventory_store,
)


class InventoryFormsTests(TestCase):
    """Valida reglas de negocio que viven en formularios de inventory."""

    def setUp(self):
        """Crea negocio, tienda y producto base para formularios."""
        self.business = create_business(
            name="Negocio Inventario",
            slug="negocio-inventario-forms",
        )
        self.store = create_inventory_store(
            business=self.business,
            name="Tienda Centro",
            code="INVFORM1",
        )
        self.product = create_inventory_product(
            business=self.business,
            name="Cerveza 33cl",
        )

    def test_inventory_item_create_form_is_valid_with_correct_data(self):
        """El formulario de alta de item acepta datos validos."""
        form = InventoryItemCreateForm(
            data={
                "store": self.store.pk,
                "product": self.product.pk,
                "minimum_stock": "2.000",
                "maximum_stock": "20.000",
                "location": "Estante A",
            },
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_inventory_item_create_form_rejects_store_from_other_business(self):
        """No debe permitir tienda de otro negocio en alta de inventario."""
        other_business = create_business(
            name="Negocio Alternativo",
            slug="negocio-alternativo-forms",
        )
        other_store = create_inventory_store(
            business=other_business,
            name="Tienda Externa",
            code="INVFORM2",
        )

        form = InventoryItemCreateForm(
            data={
                "store": other_store.pk,
                "product": self.product.pk,
                "minimum_stock": "1.000",
            },
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("store", form.errors)

    def test_stock_adjustment_line_form_rejects_duplicate_inventory_item(self):
        """No debe permitir dos lineas del mismo item en un ajuste."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("5.000"),
        )
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason="stocktake",
        )

        # Primera linea valida
        form1 = StockAdjustmentLineForm(
            data={
                "inventory_item": item.pk,
                "counted_stock": "7.000",
                "notes": "Linea inicial",
            },
            business=self.business,
            adjustment=adjustment,
        )
        self.assertTrue(form1.is_valid(), form1.errors.as_data())
        form1.save()

        # Duplicado para el mismo ajuste + item
        form2 = StockAdjustmentLineForm(
            data={
                "inventory_item": item.pk,
                "counted_stock": "8.000",
                "notes": "Duplicada",
            },
            business=self.business,
            adjustment=adjustment,
        )

        self.assertFalse(form2.is_valid())
        self.assertIn("inventory_item", form2.errors)

    def test_stock_adjustment_line_form_rejects_non_draft_adjustment(self):
        """No se pueden editar lineas cuando el ajuste no esta en borrador."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("2.000"),
        )
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
        )
        add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=item,
            counted_stock=Decimal("2.000"),
        )

        adjustment.status = StockAdjustment.STATUS_CANCELLED
        adjustment.save(update_fields=["status", "updated_at"])

        form = StockAdjustmentLineForm(
            data={
                "inventory_item": item.pk,
                "counted_stock": "2.000",
                "notes": "No deberia permitir",
            },
            business=self.business,
            adjustment=adjustment,
        )

        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors)

    def test_stock_adjustment_line_form_is_valid_for_draft_adjustment(self):
        """Linea valida en ajuste borrador debe pasar validacion."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("3.000"),
        )
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
        )

        form = StockAdjustmentLineForm(
            data={
                "adjustment": adjustment.pk,
                "inventory_item": item.pk,
                "counted_stock": "4.000",
                "notes": "Recuento correcto",
            },
            business=self.business,
            adjustment=adjustment,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_stock_adjustment_confirm_form_requires_lines(self):
        """Confirmacion requiere que el ajuste tenga lineas."""
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason="stocktake",
        )

        form = StockAdjustmentConfirmForm(
            data={"confirm": True},
            adjustment=adjustment,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)

    def test_stock_adjustment_confirm_form_is_valid_with_lines(self):
        """Confirm form debe validar cuando hay lineas y checkbox marcado."""
        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("6.000"),
        )
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
        )
        add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=item,
            counted_stock=Decimal("6.000"),
        )

        form = StockAdjustmentConfirmForm(
            data={"confirm": True},
            adjustment=adjustment,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_initial_stock_form_rejects_zero_quantity(self):
        """Stock inicial debe ser mayor que cero."""
        form = InitialStockForm(
            data={
                "quantity": "0.000",
                "unit_cost": "1.00",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("quantity", form.errors)
