"""Tests unitarios de servicios de inventory."""

from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.inventory.models import StockAdjustment, StockAdjustmentLine, StockMovement
from apps.inventory.services import (
    add_stock_adjustment_line,
    cancel_stock_adjustment,
    confirm_stock_adjustment,
    create_inventory_item as create_inventory_item_service,
    create_initial_stock,
    create_stock_adjustment,
    decrease_stock,
    get_or_create_inventory_item,
    increase_stock,
    update_stock_adjustment_line,
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

    def test_increase_stock_updates_stock_and_creates_movement_with_snapshots(self):
        """Entrada debe aumentar stock y guardar stock_before/stock_after."""
        self.item.current_stock = Decimal("2.000")
        self.item.save(update_fields=["current_stock", "updated_at"])

        updated_item, movement = increase_stock(
            inventory_item=self.item,
            quantity=Decimal("5.000"),
            movement_type=StockMovement.TYPE_ADJUSTMENT_IN,
            user=self.user,
        )

        self.assertEqual(updated_item.current_stock, Decimal("7.000"))
        self.assertEqual(movement.quantity, Decimal("5.000"))
        self.assertEqual(movement.stock_before, Decimal("2.000"))
        self.assertEqual(movement.stock_after, Decimal("7.000"))

    def test_decrease_stock_with_enough_stock_and_default_allow_negative_false(self):
        """Salida con stock suficiente debe reducir y guardar snapshots."""
        self.item.current_stock = Decimal("8.000")
        self.item.save(update_fields=["current_stock", "updated_at"])

        updated_item, movement = decrease_stock(
            inventory_item=self.item,
            quantity=Decimal("3.000"),
            movement_type=StockMovement.TYPE_SALE,
            user=self.user,
        )

        self.assertEqual(updated_item.current_stock, Decimal("5.000"))
        self.assertEqual(movement.stock_before, Decimal("8.000"))
        self.assertEqual(movement.stock_after, Decimal("5.000"))

    def test_decrease_stock_without_enough_stock_rejects_by_default(self):
        """Salida insuficiente no modifica stock ni crea movimiento."""
        self.item.current_stock = Decimal("2.000")
        self.item.save(update_fields=["current_stock", "updated_at"])

        with self.assertRaises(ValidationError):
            decrease_stock(
                inventory_item=self.item,
                quantity=Decimal("5.000"),
                movement_type=StockMovement.TYPE_SALE,
                user=self.user,
            )

        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock, Decimal("2.000"))
        self.assertFalse(
            StockMovement.objects.filter(inventory_item=self.item).exists()
        )

    def test_decrease_stock_without_enough_stock_allows_negative_when_explicit(self):
        """allow_negative=True permite salida con stock_after negativo."""
        self.item.current_stock = Decimal("2.000")
        self.item.save(update_fields=["current_stock", "updated_at"])

        updated_item, movement = decrease_stock(
            inventory_item=self.item,
            quantity=Decimal("5.000"),
            movement_type=StockMovement.TYPE_SALE,
            user=self.user,
            allow_negative=True,
        )

        self.assertEqual(updated_item.current_stock, Decimal("-3.000"))
        self.assertEqual(movement.stock_before, Decimal("2.000"))
        self.assertEqual(movement.stock_after, Decimal("-3.000"))

    def test_inactive_inventory_item_rejects_increase_and_decrease(self):
        """Ficha inactiva no puede modificarse ni crear movimientos."""
        self.item.current_stock = Decimal("4.000")
        self.item.is_active = False
        self.item.save(update_fields=["current_stock", "is_active", "updated_at"])

        with self.assertRaises(ValidationError):
            increase_stock(
                inventory_item=self.item,
                quantity=Decimal("1.000"),
                movement_type=StockMovement.TYPE_ADJUSTMENT_IN,
            )
        with self.assertRaises(ValidationError):
            decrease_stock(
                inventory_item=self.item,
                quantity=Decimal("1.000"),
                movement_type=StockMovement.TYPE_SALE,
            )

        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock, Decimal("4.000"))
        self.assertFalse(
            StockMovement.objects.filter(inventory_item=self.item).exists()
        )

    def test_get_or_create_inventory_item_rejects_invalid_creation_context(self):
        """get_or_create aplica validaciones esenciales de creación."""
        other_business = create_business(name="Otro Negocio", slug="otro-negocio-inv")
        other_store = create_inventory_store(business=other_business, code="OTHER1")
        other_product = create_inventory_product(
            business=other_business,
            name="Otro prod",
        )
        service_product = create_inventory_product(
            business=self.business,
            name="Servicio inventario",
            is_service=True,
            track_stock=True,
        )
        no_track_product = create_inventory_product(
            business=self.business,
            name="No stock",
            track_stock=False,
        )
        inactive_product = create_inventory_product(
            business=self.business,
            name="Inactivo",
            is_active=False,
        )
        inactive_store = create_inventory_store(
            business=self.business,
            code="INACT1",
            is_active=False,
        )

        invalid_cases = [
            {"business": self.business, "store": self.store, "product": other_product},
            {"business": self.business, "store": other_store, "product": self.product},
            {
                "business": self.business,
                "store": self.store,
                "product": service_product,
            },
            {
                "business": self.business,
                "store": self.store,
                "product": no_track_product,
            },
            {
                "business": self.business,
                "store": self.store,
                "product": inactive_product,
            },
            {
                "business": self.business,
                "store": inactive_store,
                "product": self.product,
            },
        ]

        for params in invalid_cases:
            with self.subTest(params=params):
                with self.assertRaises(ValidationError):
                    get_or_create_inventory_item(**params)

    def test_confirm_stock_adjustment_rejects_stale_system_stock_without_changes(self):
        """No confirma una línea si el stock cambió tras preparar el ajuste."""
        self.item.current_stock = Decimal("-3.000")
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
            counted_stock=Decimal("2.000"),
        )
        self.item.current_stock = Decimal("7.000")
        self.item.save(update_fields=["current_stock", "updated_at"])

        with self.assertRaisesMessage(
            ValidationError,
            "El stock ha cambiado desde que se preparó el ajuste.",
        ):
            confirm_stock_adjustment(adjustment=adjustment, user=self.user)

        self.item.refresh_from_db()
        adjustment.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(self.item.current_stock, Decimal("7.000"))
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_DRAFT)
        self.assertIsNone(adjustment.confirmed_at)
        self.assertIsNone(adjustment.confirmed_by)
        self.assertEqual(line.system_stock, Decimal("-3.000"))
        self.assertFalse(
            StockMovement.objects.filter(stock_adjustment_line=line).exists()
        )

    def test_confirm_stock_adjustment_rejects_inactive_inventory_item(self):
        """No confirma ajustes si una ficha se desactiva tras preparar la línea."""
        self.item.current_stock = Decimal("3.000")
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
            counted_stock=Decimal("5.000"),
        )
        self.item.is_active = False
        self.item.save(update_fields=["is_active", "updated_at"])

        with self.assertRaisesMessage(
            ValidationError,
            "No se puede confirmar un ajuste sobre una ficha de inventario inactiva.",
        ):
            confirm_stock_adjustment(adjustment=adjustment, user=self.user)

        self.item.refresh_from_db()
        adjustment.refresh_from_db()
        self.assertEqual(self.item.current_stock, Decimal("3.000"))
        self.assertFalse(self.item.is_active)
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_DRAFT)
        self.assertIsNone(adjustment.confirmed_at)
        self.assertIsNone(adjustment.confirmed_by)
        self.assertFalse(
            StockMovement.objects.filter(stock_adjustment_line=line).exists()
        )

    def test_confirm_stock_adjustment_rolls_back_previous_lines_when_later_line_fails(
        self,
    ):
        """Si una línea posterior falla, no persiste cambios de líneas anteriores."""
        first_product = create_inventory_product(
            business=self.business,
            name="Producto rollback 1",
        )
        second_product = create_inventory_product(
            business=self.business,
            name="Producto rollback 2",
        )
        first_item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=first_product,
            current_stock=Decimal("4.000"),
        )
        second_item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=second_product,
            current_stock=Decimal("6.000"),
        )
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.user,
        )
        first_line = add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=first_item,
            counted_stock=Decimal("9.000"),
        )
        second_line = add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=second_item,
            counted_stock=Decimal("2.000"),
        )
        second_item.current_stock = Decimal("7.000")
        second_item.save(update_fields=["current_stock", "updated_at"])

        with self.assertRaises(ValidationError):
            confirm_stock_adjustment(adjustment=adjustment, user=self.user)

        first_item.refresh_from_db()
        second_item.refresh_from_db()
        adjustment.refresh_from_db()
        self.assertEqual(first_item.current_stock, Decimal("4.000"))
        self.assertEqual(second_item.current_stock, Decimal("7.000"))
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_DRAFT)
        self.assertIsNone(adjustment.confirmed_at)
        self.assertIsNone(adjustment.confirmed_by)
        first_line.refresh_from_db()
        second_line.refresh_from_db()
        self.assertEqual(first_line.inventory_item_id, first_item.id)
        self.assertEqual(first_line.system_stock, Decimal("4.000"))
        self.assertEqual(first_line.counted_stock, Decimal("9.000"))
        self.assertEqual(second_line.inventory_item_id, second_item.id)
        self.assertEqual(second_line.system_stock, Decimal("6.000"))
        self.assertEqual(second_line.counted_stock, Decimal("2.000"))
        self.assertTrue(StockAdjustmentLine.objects.filter(pk=first_line.pk).exists())
        self.assertTrue(StockAdjustmentLine.objects.filter(pk=second_line.pk).exists())
        self.assertFalse(
            StockMovement.objects.filter(
                stock_adjustment_line__in=[first_line, second_line]
            ).exists()
        )

    def test_add_stock_adjustment_line_rejects_inactive_inventory_item(self):
        """No permite crear líneas de ajuste para fichas inactivas."""
        self.item.current_stock = Decimal("6.000")
        self.item.is_active = False
        self.item.save(update_fields=["current_stock", "is_active", "updated_at"])
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.user,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "No se puede modificar una ficha de inventario inactiva.",
        ):
            add_stock_adjustment_line(
                adjustment=adjustment,
                inventory_item=self.item,
                counted_stock=Decimal("8.000"),
            )

        self.item.refresh_from_db()
        adjustment.refresh_from_db()
        self.assertEqual(self.item.current_stock, Decimal("6.000"))
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_DRAFT)
        self.assertFalse(
            StockAdjustmentLine.objects.filter(adjustment=adjustment).exists()
        )
        self.assertFalse(
            StockMovement.objects.filter(inventory_item=self.item).exists()
        )

    def test_update_stock_adjustment_line_rejects_inactive_inventory_item(self):
        """No permite actualizar una línea usando una ficha inactiva."""
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.user,
        )
        line = add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=self.item,
            counted_stock=Decimal("2.000"),
            notes="Original",
        )
        original_values = {
            "inventory_item_id": line.inventory_item_id,
            "product_id": line.product_id,
            "system_stock": line.system_stock,
            "counted_stock": line.counted_stock,
            "notes": line.notes,
        }
        inactive_product = create_inventory_product(
            business=self.business,
            name="Producto ajuste inactivo",
        )
        inactive_item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=inactive_product,
            current_stock=Decimal("5.000"),
            is_active=False,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "No se puede modificar una ficha de inventario inactiva.",
        ):
            update_stock_adjustment_line(
                line=line,
                inventory_item=inactive_item,
                counted_stock=Decimal("4.000"),
                notes="Nuevo valor",
            )

        line.refresh_from_db()
        adjustment.refresh_from_db()
        self.assertEqual(line.inventory_item_id, original_values["inventory_item_id"])
        self.assertEqual(line.product_id, original_values["product_id"])
        self.assertEqual(line.system_stock, original_values["system_stock"])
        self.assertEqual(line.counted_stock, original_values["counted_stock"])
        self.assertEqual(line.notes, original_values["notes"])
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_DRAFT)
        self.assertFalse(
            StockMovement.objects.filter(stock_adjustment_line=line).exists()
        )

    def test_increase_stock_recovers_inventory_from_negative_stock(self):
        """Una entrada puede recuperar una ficha que estaba en stock negativo."""
        self.item.current_stock = Decimal("-3.000")
        self.item.save(update_fields=["current_stock", "updated_at"])

        updated_item, movement = increase_stock(
            inventory_item=self.item,
            quantity=Decimal("10.000"),
            movement_type=StockMovement.TYPE_PURCHASE_RECEIPT,
            user=self.user,
        )

        self.item.refresh_from_db()
        self.assertEqual(updated_item.current_stock, Decimal("7.000"))
        self.assertEqual(self.item.current_stock, Decimal("7.000"))
        self.assertEqual(movement.quantity, Decimal("10.000"))
        self.assertEqual(movement.stock_before, Decimal("-3.000"))
        self.assertEqual(movement.stock_after, Decimal("7.000"))
        self.assertTrue(movement.is_incoming)

    def test_decrease_stock_rolls_back_when_movement_creation_fails(self):
        """Rollback real: current_stock se revierte si falla crear movimiento."""
        self.item.current_stock = Decimal("10.000")
        self.item.save(update_fields=["current_stock", "updated_at"])

        with patch(
            "apps.inventory.services._create_stock_movement",
            side_effect=ValidationError("Error creando movimiento"),
        ):
            with self.assertRaises(ValidationError):
                decrease_stock(
                    inventory_item=self.item,
                    quantity=Decimal("3.000"),
                    movement_type=StockMovement.TYPE_SALE,
                    user=self.user,
                )

        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock, Decimal("10.000"))
        self.assertFalse(
            StockMovement.objects.filter(inventory_item=self.item).exists()
        )

    def test_confirm_stock_adjustment_from_negative_stock_creates_incoming_movement(
        self,
    ):
        """Confirmar ajuste válido desde stock negativo crea movimiento de entrada."""
        self.item.current_stock = Decimal("-3.000")
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
            counted_stock=Decimal("2.000"),
        )

        confirmed = confirm_stock_adjustment(adjustment=adjustment, user=self.user)

        self.item.refresh_from_db()
        line.refresh_from_db()
        movement = StockMovement.objects.get(stock_adjustment_line=line)
        self.assertEqual(confirmed.status, StockAdjustment.STATUS_CONFIRMED)
        self.assertEqual(self.item.current_stock, Decimal("2.000"))
        self.assertEqual(movement.movement_type, StockMovement.TYPE_ADJUSTMENT_IN)
        self.assertEqual(movement.quantity, Decimal("5.000"))
        self.assertEqual(movement.stock_before, Decimal("-3.000"))
        self.assertEqual(movement.stock_after, Decimal("2.000"))
        self.assertEqual(line.system_stock, Decimal("-3.000"))
        self.assertEqual(line.difference, Decimal("5.000"))
