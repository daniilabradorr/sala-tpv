"""Tests unitarios de servicios de inventory."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.inventory.models import StockAdjustment, StockMovement
from apps.inventory.services import (
    add_stock_adjustment_line,
    cancel_stock_adjustment,
    confirm_stock_adjustment,
    create_inventory_item as create_inventory_item_service,
    create_initial_stock,
    create_stock_adjustment,
)
from apps.inventory.tests.factories import (
    create_business,
    create_inventory_item,
    create_inventory_owner,
    create_inventory_product,
    create_inventory_store,
)


class InventoryServicesTests(TestCase):
    """Valida reglas de negocio de servicios de inventario."""

    def setUp(self):  # noqa: N802
        """Prepara negocio, tienda, producto, usuario e item base."""
        self.business = create_business(
            name="Negocio Inventory Services",
            slug="negocio-inventory-services",
        )
        self.store = create_inventory_store(
            business=self.business,
            name="Tienda Service",
            code="INVSERV1",
        )
        self.product = create_inventory_product(
            business=self.business,
            name="Refresco Lata",
        )
        self.user = create_inventory_owner(business=self.business)
        self.item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("0.000"),
            minimum_stock=Decimal("1.000"),
        )

    def test_create_initial_stock_updates_stock_and_creates_movement(self):
        """Carga inicial debe actualizar stock y crear movimiento inicial."""
        updated_item, movement = create_initial_stock(
            inventory_item=self.item,
            quantity=Decimal("10.000"),
            reason="Carga inicial",
            user=self.user,
        )

        self.assertEqual(updated_item.current_stock, Decimal("10.000"))
        self.assertEqual(movement.movement_type, StockMovement.TYPE_INITIAL)
        self.assertEqual(movement.quantity, Decimal("10.000"))

    def test_confirm_stock_adjustment_applies_counted_stock_and_creates_movement(self):
        """Confirmar ajuste debe aplicar stock contado y crear movimiento."""
        self.item.current_stock = Decimal("5.000")
        self.item.save(update_fields=["current_stock", "updated_at"])

        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.user,
        )

        line = add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=self.item,
            counted_stock=Decimal("8.000"),
            notes="Ajuste por recuento",
        )

        confirmed = confirm_stock_adjustment(
            adjustment=adjustment,
            user=self.user,
        )

        self.item.refresh_from_db()
        line.refresh_from_db()

        self.assertEqual(confirmed.status, StockAdjustment.STATUS_CONFIRMED)
        self.assertEqual(self.item.current_stock, Decimal("8.000"))
        self.assertTrue(
            StockMovement.objects.filter(
                stock_adjustment_line=line,
                movement_type=StockMovement.TYPE_ADJUSTMENT_IN,
                quantity=Decimal("3.000"),
            ).exists()
        )

    def test_cancel_stock_adjustment_changes_status_to_cancelled(self):
        """Cancelar ajuste en borrador debe pasar a estado cancelado."""
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_OTHER,
            user=self.user,
        )

        cancelled = cancel_stock_adjustment(
            adjustment=adjustment,
            user=self.user,
        )

        self.assertEqual(cancelled.status, StockAdjustment.STATUS_CANCELLED)

    def test_cancel_stock_adjustment_rejects_non_draft_adjustment(self):
        """Cancelar un ajuste no borrador debe lanzar ValidationError."""
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_OTHER,
            user=self.user,
        )
        adjustment.status = StockAdjustment.STATUS_CONFIRMED
        adjustment.confirmed_at = timezone.now()
        adjustment.confirmed_by = self.user
        adjustment.save(
            update_fields=["status", "confirmed_at", "confirmed_by", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            cancel_stock_adjustment(
                adjustment=adjustment,
                user=self.user,
            )

    def test_create_initial_stock_rejects_second_initial_load(self):
        """No debe permitir carga inicial si ya existen movimientos."""
        create_initial_stock(
            inventory_item=self.item,
            quantity=Decimal("2.000"),
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            create_initial_stock(
                inventory_item=self.item,
                quantity=Decimal("1.000"),
                user=self.user,
            )

    def test_confirm_stock_adjustment_rejects_adjustment_without_lines(self):
        """Confirmar sin lineas debe fallar por regla de negocio."""
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            confirm_stock_adjustment(
                adjustment=adjustment,
                user=self.user,
            )

    def test_add_stock_adjustment_line_rejects_inventory_item_other_store(self):
        """No debe permitir lineas con item de otra tienda."""
        other_store = create_inventory_store(
            business=self.business,
            name="Tienda Secundaria",
            code="INVSERV2",
        )
        other_product = create_inventory_product(
            business=self.business,
            name="Producto Secundario",
        )
        other_item = create_inventory_item(
            business=self.business,
            store=other_store,
            product=other_product,
        )
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            add_stock_adjustment_line(
                adjustment=adjustment,
                inventory_item=other_item,
                counted_stock=Decimal("1.000"),
            )

    def test_create_inventory_item_rejects_service_product(self):
        """No debe crear inventario para productos tipo servicio."""
        service_product = create_inventory_product(
            business=self.business,
            name="Servicio tecnico",
            is_service=True,
            track_stock=False,
        )

        with self.assertRaises(ValidationError):
            create_inventory_item_service(
                business=self.business,
                store=self.store,
                product=service_product,
                minimum_stock=Decimal("0.000"),
            )
