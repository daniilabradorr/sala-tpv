"""Servicios de escritura para el dominio de inventario.

Regla general:
- Si cambia current_stock, debe crearse StockMovement.
- Las views no modifican stock directamente.
- Las views no crean StockMovement directamente.
- Los cambios críticos van con transaction.atomic().
- Al modificar stock se usa select_for_update().
"""

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import (
    InventoryItem,
    StockAdjustment,
    StockAdjustmentLine,
    StockMovement,
)

# Compatibilidad temporal:
# Si alguna view antigua importa get_inventory_dashboard_data desde services.py,
# seguirá funcionando. La lectura vive realmente en selectors.py.
from apps.inventory.selectors import (
    get_inventory_dashboard_data as _selector_get_inventory_dashboard_data,
)


# ==========================================================
# Helpers internos
# ==========================================================


def _to_decimal(value):
    """Normaliza valores numéricos a Decimal."""

    if isinstance(value, Decimal):
        return value

    return Decimal(str(value))


def get_inventory_dashboard_data(*args, **kwargs):
    """Compatibilidad temporal para imports antiguos desde services.py."""

    return _selector_get_inventory_dashboard_data(*args, **kwargs)


def _validate_positive_quantity(quantity):
    """Valida que una cantidad sea mayor que cero."""

    quantity = _to_decimal(quantity)

    if quantity <= Decimal("0.000"):
        raise ValidationError("La cantidad debe ser mayor que cero.")

    return quantity


def _validate_inventory_item_creation(*, business, store, product):
    """Valida reglas esenciales para crear una ficha de inventario."""

    if business is None:
        raise ValidationError("No se ha indicado el negocio.")

    if store.business_id != business.id:
        raise ValidationError("La tienda debe pertenecer al mismo negocio.")

    if product.business_id != business.id:
        raise ValidationError("El producto debe pertenecer al mismo negocio.")

    if not store.is_active:
        raise ValidationError("No puedes crear inventario en una tienda inactiva.")

    if not product.is_active:
        raise ValidationError("No puedes crear inventario para un producto inactivo.")

    if product.is_service:
        raise ValidationError("No se puede controlar stock de un servicio.")

    if not product.track_stock:
        raise ValidationError(
            "No se puede crear inventario para un producto que no controla stock."
        )


def _create_stock_movement(
    *,
    inventory_item,
    movement_type,
    quantity,
    stock_before,
    stock_after,
    user=None,
    unit_cost=None,
    reference_type="",
    reference_id="",
    stock_adjustment_line=None,
    reason="",
    notes="",
    operation_id=None,
):
    """Crea un movimiento de stock.

    IMPORTANTE:
    Esta función NO debe llamarse desde views.
    Solo desde services.
    """

    quantity = _validate_positive_quantity(quantity)

    movement = StockMovement(
        business=inventory_item.business,
        inventory_item=inventory_item,
        store=inventory_item.store,
        product=inventory_item.product,
        stock_adjustment_line=stock_adjustment_line,
        movement_type=movement_type,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        unit_cost=unit_cost,
        reference_type=reference_type,
        reference_id=str(reference_id) if reference_id else "",
        reason=reason or "",
        notes=notes or "",
        occurred_at=timezone.now(),
        created_by=user,
    )

    if operation_id:
        movement.operation_id = operation_id

    movement.save()

    return movement


# ==========================================================
# InventoryItem
# ==========================================================


def create_inventory_item(
    *,
    business,
    store,
    product,
    minimum_stock=Decimal("0.000"),
    maximum_stock=None,
    location="",
):
    """Crea una ficha de inventario sin meter stock físico.

    La ficha nace con:
    - current_stock = 0
    - reserved_stock = 0

    El stock inicial se cargará con create_initial_stock().
    """

    _validate_inventory_item_creation(business=business, store=store, product=product)

    exists = InventoryItem.objects.filter(
        business=business,
        store=store,
        product=product,
    ).exists()

    if exists:
        raise ValidationError(
            "Ya existe una ficha de inventario para este producto en esta tienda."
        )

    inventory_item = InventoryItem(
        business=business,
        store=store,
        product=product,
        current_stock=Decimal("0.000"),
        reserved_stock=Decimal("0.000"),
        minimum_stock=minimum_stock or Decimal("0.000"),
        maximum_stock=maximum_stock,
        location=location or "",
        is_active=True,
    )

    inventory_item.save()

    return inventory_item


def get_or_create_inventory_item(
    *,
    business,
    store,
    product,
):
    """Obtiene o crea una ficha de inventario.

    Útil para compras futuras o integraciones,
    pero para pantallas manuales preferimos create_inventory_item().
    """

    _validate_inventory_item_creation(business=business, store=store, product=product)

    inventory_item, _created = InventoryItem.objects.get_or_create(
        business=business,
        store=store,
        product=product,
        defaults={
            "current_stock": Decimal("0.000"),
            "reserved_stock": Decimal("0.000"),
            "minimum_stock": Decimal("0.000"),
            "is_active": True,
        },
    )

    return inventory_item


def update_inventory_item_settings(
    *,
    inventory_item,
    business,
    minimum_stock,
    maximum_stock,
    location,
    is_active,
):
    """Actualiza configuración de inventario.

    IMPORTANTE:
    No modifica current_stock.
    No modifica reserved_stock.
    No crea StockMovement.
    """

    if inventory_item.business_id != business.id:
        raise ValidationError("No puedes editar inventario de otro negocio.")

    inventory_item.minimum_stock = minimum_stock
    inventory_item.maximum_stock = maximum_stock
    inventory_item.location = location or ""
    inventory_item.is_active = is_active

    inventory_item.save(
        update_fields=[
            "minimum_stock",
            "maximum_stock",
            "location",
            "is_active",
            "updated_at",
        ]
    )

    return inventory_item


# ==========================================================
# Movimientos base de stock
# ==========================================================


def create_initial_stock(
    *,
    inventory_item,
    quantity,
    unit_cost=None,
    reason="",
    notes="",
    user=None,
):
    """Carga stock inicial para una ficha de inventario.

    Reglas:
    - Solo se puede hacer si aún no hay movimientos.
    - Crea StockMovement.
    - Modifica current_stock.
    """

    quantity = _validate_positive_quantity(quantity)

    with transaction.atomic():
        locked_item = (
            InventoryItem.objects.select_for_update()
            .select_related("business", "store", "product")
            .get(pk=inventory_item.pk)
        )

        if not locked_item.is_active:
            raise ValidationError(
                "No puedes cargar stock inicial en una ficha inactiva."
            )

        if locked_item.movements.exists():
            raise ValidationError(
                "No puedes cargar stock inicial porque esta ficha ya tiene movimientos."
            )

        if locked_item.current_stock != Decimal("0.000"):
            raise ValidationError(
                "No puedes cargar stock inicial porque el stock actual no es cero."
            )

        stock_before = locked_item.current_stock
        stock_after = stock_before + quantity

        locked_item.current_stock = stock_after
        locked_item.save(
            update_fields=[
                "current_stock",
                "updated_at",
            ]
        )

        movement = _create_stock_movement(
            inventory_item=locked_item,
            movement_type=StockMovement.TYPE_INITIAL,
            quantity=quantity,
            stock_before=stock_before,
            stock_after=stock_after,
            user=user,
            unit_cost=unit_cost,
            reference_type=StockMovement.REF_MANUAL,
            reason=reason or "Inventario inicial",
            notes=notes,
        )

    return locked_item, movement


def increase_stock(
    *,
    inventory_item,
    quantity,
    movement_type,
    user=None,
    unit_cost=None,
    reference_type="",
    reference_id="",
    stock_adjustment_line=None,
    reason="",
    notes="",
    operation_id=None,
):
    """Incrementa stock y crea movimiento de entrada."""

    quantity = _validate_positive_quantity(quantity)

    if movement_type not in StockMovement.IN_TYPES:
        raise ValidationError("El tipo de movimiento no es de entrada.")

    with transaction.atomic():
        locked_item = (
            InventoryItem.objects.select_for_update()
            .select_related("business", "store", "product")
            .get(pk=inventory_item.pk)
        )

        if not locked_item.is_active:
            raise ValidationError(
                "No se puede modificar una ficha de inventario inactiva."
            )

        stock_before = locked_item.current_stock
        stock_after = stock_before + quantity

        locked_item.current_stock = stock_after
        locked_item.save(
            update_fields=[
                "current_stock",
                "updated_at",
            ]
        )

        movement = _create_stock_movement(
            inventory_item=locked_item,
            movement_type=movement_type,
            quantity=quantity,
            stock_before=stock_before,
            stock_after=stock_after,
            user=user,
            unit_cost=unit_cost,
            reference_type=reference_type,
            reference_id=reference_id,
            stock_adjustment_line=stock_adjustment_line,
            reason=reason,
            notes=notes,
            operation_id=operation_id,
        )

    return locked_item, movement


def decrease_stock(
    *,
    inventory_item,
    quantity,
    movement_type,
    user=None,
    unit_cost=None,
    reference_type="",
    reference_id="",
    stock_adjustment_line=None,
    reason="",
    notes="",
    operation_id=None,
    allow_negative=False,
):
    """Reduce stock y crea movimiento de salida."""

    quantity = _validate_positive_quantity(quantity)

    if movement_type not in StockMovement.OUT_TYPES:
        raise ValidationError("El tipo de movimiento no es de salida.")

    with transaction.atomic():
        locked_item = (
            InventoryItem.objects.select_for_update()
            .select_related("business", "store", "product")
            .get(pk=inventory_item.pk)
        )

        if not locked_item.is_active:
            raise ValidationError(
                "No se puede modificar una ficha de inventario inactiva."
            )

        if not allow_negative and locked_item.available_stock < quantity:
            raise ValidationError("No hay stock disponible suficiente.")

        stock_before = locked_item.current_stock
        stock_after = stock_before - quantity

        locked_item.current_stock = stock_after
        locked_item.save(
            update_fields=[
                "current_stock",
                "updated_at",
            ]
        )

        movement = _create_stock_movement(
            inventory_item=locked_item,
            movement_type=movement_type,
            quantity=quantity,
            stock_before=stock_before,
            stock_after=stock_after,
            user=user,
            unit_cost=unit_cost,
            reference_type=reference_type,
            reference_id=reference_id,
            stock_adjustment_line=stock_adjustment_line,
            reason=reason,
            notes=notes,
            operation_id=operation_id,
        )

    return locked_item, movement


# ==========================================================
# Ajustes de stock
# ==========================================================


def create_stock_adjustment(
    *,
    business,
    store,
    reason,
    notes="",
    user=None,
):
    """Crea cabecera de ajuste en borrador.

    Crear ajuste NO toca stock.
    """

    if business is None:
        raise ValidationError("No se ha indicado el negocio.")

    if store.business_id != business.id:
        raise ValidationError("La tienda debe pertenecer al mismo negocio.")

    if not store.is_active:
        raise ValidationError("No puedes crear un ajuste en una tienda inactiva.")

    adjustment = StockAdjustment(
        business=business,
        store=store,
        status=StockAdjustment.STATUS_DRAFT,
        reason=reason,
        notes=notes or "",
        created_by=user,
    )

    adjustment.save()

    return adjustment


def add_stock_adjustment_line(
    *,
    adjustment,
    inventory_item,
    counted_stock,
    notes="",
):
    """Añade línea de ajuste.

    Añadir línea NO toca stock.
    """

    counted_stock = _to_decimal(counted_stock)

    if not adjustment.is_draft:
        raise ValidationError("Solo se pueden añadir líneas a ajustes en borrador.")

    if inventory_item.business_id != adjustment.business_id:
        raise ValidationError(
            "El stock afectado debe pertenecer al mismo negocio que el ajuste."
        )

    if inventory_item.store_id != adjustment.store_id:
        raise ValidationError(
            "El stock afectado debe pertenecer a la misma tienda que el ajuste."
        )

    if not inventory_item.is_active:
        raise ValidationError("No se puede modificar una ficha de inventario inactiva.")

    exists = StockAdjustmentLine.objects.filter(
        adjustment=adjustment,
        inventory_item=inventory_item,
    ).exists()

    if exists:
        raise ValidationError("Este producto ya tiene una línea en este ajuste.")

    line = StockAdjustmentLine(
        adjustment=adjustment,
        inventory_item=inventory_item,
        product=inventory_item.product,
        system_stock=inventory_item.current_stock,
        counted_stock=counted_stock,
        notes=notes or "",
    )

    line.save()

    return line


def update_stock_adjustment_line(
    *,
    line,
    inventory_item,
    counted_stock,
    notes="",
):
    """Actualiza una línea de ajuste en borrador.

    Editar línea NO toca stock.
    """

    counted_stock = _to_decimal(counted_stock)
    adjustment = line.adjustment

    if not adjustment.is_draft:
        raise ValidationError("Solo se pueden editar líneas de ajustes en borrador.")

    if inventory_item.business_id != adjustment.business_id:
        raise ValidationError(
            "El stock afectado debe pertenecer al mismo negocio que el ajuste."
        )

    if inventory_item.store_id != adjustment.store_id:
        raise ValidationError(
            "El stock afectado debe pertenecer a la misma tienda que el ajuste."
        )

    if not inventory_item.is_active:
        raise ValidationError("No se puede modificar una ficha de inventario inactiva.")

    duplicate_queryset = StockAdjustmentLine.objects.filter(
        adjustment=adjustment,
        inventory_item=inventory_item,
    ).exclude(pk=line.pk)

    if duplicate_queryset.exists():
        raise ValidationError("Este producto ya tiene una línea en este ajuste.")

    line.inventory_item = inventory_item
    line.product = inventory_item.product
    line.system_stock = inventory_item.current_stock
    line.counted_stock = counted_stock
    line.notes = notes or ""

    line.save()

    return line


def delete_stock_adjustment_line(*, line):
    """Elimina una línea de ajuste.

    Eliminar línea NO toca stock.
    """

    adjustment = line.adjustment

    if not adjustment.is_draft:
        raise ValidationError("Solo se pueden borrar líneas de ajustes en borrador.")

    line.delete()

    return adjustment


def confirm_stock_adjustment(
    *,
    adjustment,
    user=None,
):
    """Confirma un ajuste de stock y aplica sus líneas.

    Esta es una de las operaciones críticas del módulo.

    Reglas:
    1. Solo se confirma si está en borrador.
    2. Debe tener líneas.
    3. Todo va dentro de transaction.atomic().
    4. Cada InventoryItem se bloquea con select_for_update().
    5. Se modifica current_stock.
    6. Se crea StockMovement por cada diferencia.
    7. Se marca el ajuste como confirmado.
    """

    with transaction.atomic():
        locked_adjustment = (
            StockAdjustment.objects.select_for_update()
            .select_related(
                "business",
                "store",
            )
            .get(pk=adjustment.pk)
        )

        if not locked_adjustment.is_draft:
            raise ValidationError("Solo se pueden confirmar ajustes en borrador.")

        lines = list(
            locked_adjustment.lines.select_related(
                "inventory_item",
                "product",
            ).order_by("pk")
        )

        if not lines:
            raise ValidationError("No puedes confirmar un ajuste sin líneas.")

        operation_id = uuid.uuid4()

        for line in lines:
            inventory_item = (
                InventoryItem.objects.select_for_update()
                .select_related("business", "store", "product")
                .get(pk=line.inventory_item_id)
            )

            if inventory_item.business_id != locked_adjustment.business_id:
                raise ValidationError("Una línea del ajuste pertenece a otro negocio.")

            if inventory_item.store_id != locked_adjustment.store_id:
                raise ValidationError("Una línea del ajuste pertenece a otra tienda.")

            if not inventory_item.is_active:
                raise ValidationError(
                    "No se puede confirmar un ajuste sobre una ficha de inventario "
                    "inactiva."
                )

            if inventory_item.current_stock != line.system_stock:
                raise ValidationError(
                    "El stock ha cambiado desde que se preparó el ajuste. "
                    "Actualiza la línea y realiza de nuevo el recuento."
                )

            stock_before = inventory_item.current_stock
            stock_after = line.counted_stock

            if stock_after < Decimal("0.000"):
                raise ValidationError("El stock contado no puede ser negativo.")

            if inventory_item.reserved_stock > stock_after:
                raise ValidationError(
                    (
                        "No se puede confirmar el ajuste porque el stock contado "
                        "es menor que el stock reservado."
                    )
                )

            difference = stock_after - stock_before

            if difference == Decimal("0.000"):
                continue

            quantity = abs(difference)

            if difference > Decimal("0.000"):
                movement_type = StockMovement.TYPE_ADJUSTMENT_IN
            else:
                movement_type = StockMovement.TYPE_ADJUSTMENT_OUT

            inventory_item.current_stock = stock_after
            inventory_item.save(
                update_fields=[
                    "current_stock",
                    "updated_at",
                ]
            )

            _create_stock_movement(
                inventory_item=inventory_item,
                movement_type=movement_type,
                quantity=quantity,
                stock_before=stock_before,
                stock_after=stock_after,
                user=user,
                reference_type=StockMovement.REF_STOCK_ADJUSTMENT,
                reference_id=locked_adjustment.code,
                stock_adjustment_line=line,
                reason=locked_adjustment.get_reason_display(),
                notes=locked_adjustment.notes,
                operation_id=operation_id,
            )

        locked_adjustment.status = StockAdjustment.STATUS_CONFIRMED
        locked_adjustment.confirmed_at = timezone.now()
        locked_adjustment.confirmed_by = user
        locked_adjustment.save(
            update_fields=[
                "status",
                "confirmed_at",
                "confirmed_by",
                "updated_at",
            ]
        )

    return locked_adjustment


def cancel_stock_adjustment(
    *,
    adjustment,
    user=None,
):
    """Cancela un ajuste en borrador.

    Cancelar ajuste NO toca stock.
    """

    _ = user

    with transaction.atomic():
        locked_adjustment = StockAdjustment.objects.select_for_update().get(
            pk=adjustment.pk
        )

        if not locked_adjustment.is_draft:
            raise ValidationError("Solo se pueden cancelar ajustes en borrador.")

        locked_adjustment.status = StockAdjustment.STATUS_CANCELLED
        locked_adjustment.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

    return locked_adjustment
