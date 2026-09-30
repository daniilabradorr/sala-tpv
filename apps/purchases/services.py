"""Servicios del módulo purchases.

Reglas de arquitectura:
- Las views coordinan la petición HTTP.
- Los selectors realizan lecturas reutilizables.
- Los services contienen las mutaciones y las reglas de negocio.
- Crear u ordenar compras no modifica el inventario.
- La recepción de mercancía integra Purchases e Inventory atómicamente.
"""

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.constants import AuditEventType, AuditModule
from apps.audit.services import log_event
from apps.business_config.models import POSSettings
from apps.catalog.models import Product
from apps.core.models import Business
from apps.inventory.models import StockMovement
from apps.inventory.services import (
    get_or_create_inventory_item_for_purchase_receipt,
    increase_stock,
)
from apps.purchases.models import (
    Purchase,
    PurchaseLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    PurchaseStatusChoices,
    Supplier,
)
from apps.stores.models import Store
from apps.users.helpers import can_access_store, is_owner_or_manager

MONEY_STEP = Decimal("0.01")
QUANTITY_STEP = Decimal("0.001")
PERCENT_BASE = Decimal("100.00")
ZERO_MONEY = Decimal("0.00")
ZERO_QUANTITY = Decimal("0.000")

_UNSET = object()


def _to_decimal(value, *, field_name, default=None):
    if value is None:
        if default is not None:
            return default
        raise ValidationError({field_name: "Este valor es obligatorio."})

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field_name: "Debes indicar un número válido."}) from exc


def _money(value):
    return _to_decimal(value, field_name="amount", default=ZERO_MONEY).quantize(
        MONEY_STEP, rounding=ROUND_HALF_UP
    )


def _quantity(value):
    return _to_decimal(value, field_name="quantity").quantize(
        QUANTITY_STEP, rounding=ROUND_HALF_UP
    )


def _get_pos_settings(business):
    settings = POSSettings.objects.filter(business_id=business.pk).first()
    if settings is None:
        raise ValidationError(
            {"pos_settings": "El negocio no tiene configuración POS."}
        )
    return settings


def _normalize_idempotency_key(value):
    if value in (None, ""):
        raise ValidationError({"idempotency_key": "Este valor es obligatorio."})
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(
            {"idempotency_key": "Debes indicar una clave UUID válida."}
        ) from exc


def _normalize_purchase_receipt_lines(lines):
    if lines is None:
        raise ValidationError({"lines": "Debes indicar al menos una línea."})
    try:
        entries = list(lines)
    except TypeError as exc:
        raise ValidationError({"lines": "Debes indicar una lista de líneas."}) from exc
    if not entries:
        raise ValidationError({"lines": "Debes indicar al menos una línea."})

    normalized = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError({"lines": "Cada línea debe ser un diccionario."})
        line = entry.get("purchase_line")
        line_id = getattr(line, "pk", None)
        if not line_id:
            raise ValidationError(
                {"purchase_line": "La línea de compra debe estar persistida."}
            )
        if line_id in seen:
            raise ValidationError(
                {"purchase_line": "Una línea no puede repetirse en la recepción."}
            )
        seen.add(line_id)
        quantity = _quantity(entry.get("quantity_received"))
        if quantity <= ZERO_QUANTITY:
            raise ValidationError(
                {"quantity_received": "La cantidad debe ser mayor que cero."}
            )
        normalized.append((line_id, quantity))
    return sorted(normalized, key=lambda item: item[0])


def _build_purchase_receipt_fingerprint(*, business_id, purchase_id, store_id, lines):
    payload = {
        "version": 1,
        "business_id": business_id,
        "purchase_id": purchase_id,
        "store_id": store_id,
        "lines": [
            {
                "purchase_line_id": line_id,
                "quantity_received": f"{quantity:.3f}",
            }
            for line_id, quantity in sorted(lines, key=lambda item: item[0])
        ],
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _purchase_receipt_operation_id(*, business_id, receipt_id):
    return uuid5(NAMESPACE_URL, f"netxodo:purchase_receipt:{business_id}:{receipt_id}")


def _idempotent_receipt_or_conflict(*, business, key, fingerprint):
    existing = PurchaseReceipt.objects.filter(
        business_id=business.pk, idempotency_key=key
    ).first()
    if existing is None:
        return None
    if existing.idempotency_fingerprint != fingerprint:
        raise ValidationError(
            {
                "idempotency_key": (
                    "La clave de idempotencia ya fue utilizada con una "
                    "recepción diferente."
                )
            }
        )
    return existing


def _tax_rate(value):
    return _to_decimal(value, field_name="tax_rate", default=ZERO_MONEY).quantize(
        MONEY_STEP, rounding=ROUND_HALF_UP
    )


def calculate_purchase_line_amounts(*, quantity, unit_cost, tax_rate=ZERO_MONEY):
    """Calcula importes de compra sin consultar el impuesto de venta del producto."""

    quantity = _quantity(quantity)
    unit_cost = _to_decimal(unit_cost, field_name="unit_cost").quantize(
        MONEY_STEP, rounding=ROUND_HALF_UP
    )
    tax_rate = _tax_rate(tax_rate)

    if quantity <= ZERO_QUANTITY:
        raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})
    if unit_cost < ZERO_MONEY:
        raise ValidationError({"unit_cost": "El coste no puede ser negativo."})
    if tax_rate < ZERO_MONEY:
        raise ValidationError({"tax_rate": "El tipo impositivo no puede ser negativo."})

    line_subtotal = _money(quantity * unit_cost)
    tax_amount = _money(line_subtotal * tax_rate / PERCENT_BASE)
    line_total = _money(line_subtotal + tax_amount)
    return {
        "quantity_ordered": quantity,
        "unit_cost": unit_cost,
        "tax_rate": tax_rate,
        "line_subtotal": line_subtotal,
        "tax_amount": tax_amount,
        "line_total": line_total,
    }


def _validate_business(business):
    if business is None or not getattr(business, "pk", None):
        raise ValidationError({"business": "Debes indicar un negocio válido."})
    if not Business.objects.filter(pk=business.pk).exists():
        raise ValidationError({"business": "El negocio no existe."})


def _validate_user(*, business, user):
    _validate_business(business)
    if user is None or not getattr(user, "is_authenticated", False):
        raise ValidationError({"user": "El usuario debe estar autenticado."})
    if not getattr(user, "is_active", False):
        raise ValidationError({"user": "El usuario responsable está inactivo."})
    if not user.is_superuser and user.business_id != business.pk:
        raise ValidationError({"user": "El usuario no pertenece al negocio actual."})
    if not user.is_superuser and not is_owner_or_manager(user):
        raise ValidationError("Solo owner o manager pueden gestionar compras.")


def _validate_store_access(*, business, store, user, require_active):
    _validate_user(business=business, user=user)
    if store is None or not getattr(store, "pk", None):
        raise ValidationError({"store": "Debes indicar una tienda válida."})
    if store.business_id != business.pk:
        raise ValidationError({"store": "La tienda no pertenece al negocio actual."})
    current_store = Store.objects.filter(pk=store.pk, business=business).first()
    if current_store is None:
        raise ValidationError({"store": "La tienda no existe."})
    if require_active and not current_store.is_active:
        raise ValidationError({"store": "La tienda debe estar activa."})
    if not can_access_store(user, current_store):
        raise ValidationError({"user": "No tienes acceso a esta tienda."})
    return current_store


def _get_supplier(*, business, supplier, require_active):
    if supplier is None or not getattr(supplier, "pk", None):
        raise ValidationError({"supplier": "Debes indicar un proveedor válido."})
    query = Supplier.objects.filter(pk=supplier.pk, business=business)
    if require_active:
        query = query.filter(is_active=True)
    current = query.first()
    if current is None:
        message = (
            "El proveedor no está activo."
            if Supplier.objects.filter(pk=supplier.pk, business=business).exists()
            else "El proveedor no pertenece al negocio actual."
        )
        raise ValidationError({"supplier": message})
    return current


def _lock_purchase(*, business, purchase):
    _validate_business(business)
    if purchase is None or not getattr(purchase, "pk", None):
        raise ValidationError("La compra no existe.")
    try:
        return (
            Purchase.objects.select_for_update(of=("self",))
            .select_related("business", "store", "supplier", "created_by")
            .get(pk=purchase.pk, business=business)
        )
    except Purchase.DoesNotExist as exc:
        raise ValidationError("La compra no pertenece al negocio actual.") from exc


def _validate_draft(purchase):
    if purchase.status != PurchaseStatusChoices.DRAFT:
        raise ValidationError("La compra ya no admite modificaciones.")


def _lock_line(*, business, purchase, line):
    if line is None or not getattr(line, "pk", None):
        raise ValidationError("La línea de compra no existe.")
    try:
        return PurchaseLine.objects.select_for_update().get(
            pk=line.pk, business=business, purchase=purchase
        )
    except PurchaseLine.DoesNotExist as exc:
        raise ValidationError(
            "La línea no pertenece a la compra y negocio actuales."
        ) from exc


def _validate_line_integrity(line):
    calculated = calculate_purchase_line_amounts(
        quantity=line.quantity_ordered,
        unit_cost=line.unit_cost,
        tax_rate=line.tax_rate,
    )
    for field in ("line_subtotal", "tax_amount", "line_total"):
        if getattr(line, field) != calculated[field]:
            raise ValidationError(
                "Los importes persistidos de la línea son incoherentes."
            )
    return calculated


def _recalculate_locked_purchase(locked_purchase):
    lines = list(
        PurchaseLine.objects.filter(
            business=locked_purchase.business, purchase=locked_purchase
        ).only(
            "quantity_ordered",
            "unit_cost",
            "tax_rate",
            "line_subtotal",
            "tax_amount",
            "line_total",
        )
    )
    for line in lines:
        _validate_line_integrity(line)
    subtotal = _money(sum((line.line_subtotal for line in lines), ZERO_MONEY))
    tax = _money(sum((line.tax_amount for line in lines), ZERO_MONEY))
    total = _money(sum((line.line_total for line in lines), ZERO_MONEY))
    if total != _money(subtotal + tax):
        raise ValidationError("Los importes de las líneas no coinciden con el total.")
    locked_purchase.subtotal_amount = subtotal
    locked_purchase.tax_amount = tax
    locked_purchase.total_amount = total
    locked_purchase.save(
        update_fields=[
            "subtotal_amount",
            "tax_amount",
            "total_amount",
            "updated_at",
        ]
    )
    return locked_purchase


@transaction.atomic
def create_supplier(
    *,
    business,
    name,
    user=None,
    created_by=None,
    legal_name="",
    tax_identifier="",
    email="",
    phone="",
    address="",
    is_active=True,
):
    user = user or created_by
    _validate_user(business=business, user=user)
    supplier = Supplier(
        business=business,
        name=name,
        legal_name=legal_name,
        tax_identifier=tax_identifier,
        email=email,
        phone=phone,
        address=address,
        is_active=is_active,
    )
    supplier.save()
    return supplier


@transaction.atomic
def update_supplier(
    *,
    business,
    supplier,
    user=None,
    updated_by=None,
    name=_UNSET,
    legal_name=_UNSET,
    tax_identifier=_UNSET,
    email=_UNSET,
    phone=_UNSET,
    address=_UNSET,
    is_active=_UNSET,
):
    user = user or updated_by
    _validate_user(business=business, user=user)
    if supplier is None or not getattr(supplier, "pk", None):
        raise ValidationError("El proveedor no existe.")
    try:
        locked = Supplier.objects.select_for_update().get(
            pk=supplier.pk, business=business
        )
    except Supplier.DoesNotExist as exc:
        raise ValidationError("El proveedor no pertenece al negocio actual.") from exc
    editable = {
        "name": name,
        "legal_name": legal_name,
        "tax_identifier": tax_identifier,
        "email": email,
        "phone": phone,
        "address": address,
        "is_active": is_active,
    }
    changed = []
    for field, value in editable.items():
        if value is not _UNSET:
            setattr(locked, field, value)
            changed.append(field)
    if changed:
        locked.save(update_fields=[*changed, "updated_at"])
    return locked


@transaction.atomic
def create_purchase(*, business, store, supplier, created_by, reference="", notes=""):
    current_store = _validate_store_access(
        business=business, store=store, user=created_by, require_active=True
    )
    current_supplier = _get_supplier(
        business=business, supplier=supplier, require_active=True
    )
    purchase = Purchase(
        business=business,
        store=current_store,
        supplier=current_supplier,
        created_by=created_by,
        status=PurchaseStatusChoices.DRAFT,
        reference=reference,
        notes=notes,
        ordered_at=None,
        subtotal_amount=ZERO_MONEY,
        tax_amount=ZERO_MONEY,
        total_amount=ZERO_MONEY,
    )
    purchase.save()
    log_event(
        business=business,
        store=current_store,
        user=created_by,
        event_type=AuditEventType.PURCHASE_CREATED,
        module=AuditModule.PURCHASES,
        entity=purchase,
        message=f"Compra #{purchase.pk} creada.",
        old_payload=None,
        new_payload={"status": purchase.status},
        metadata={"supplier_id": purchase.supplier_id},
    )
    return purchase


@transaction.atomic
def update_purchase_header(
    *,
    business,
    purchase,
    user=None,
    updated_by=None,
    store=_UNSET,
    supplier=_UNSET,
    reference=_UNSET,
    notes=_UNSET,
):
    user = user or updated_by
    locked = _lock_purchase(business=business, purchase=purchase)
    _validate_draft(locked)
    _validate_store_access(
        business=business, store=locked.store, user=user, require_active=False
    )

    changed = []
    if store is not _UNSET:
        current_store = _validate_store_access(
            business=business, store=store, user=user, require_active=True
        )
        if current_store.pk != locked.store_id:
            locked.store = current_store
            changed.append("store")
    if supplier is not _UNSET:
        current_supplier = _get_supplier(
            business=business, supplier=supplier, require_active=True
        )
        if current_supplier.pk != locked.supplier_id:
            locked.supplier = current_supplier
            changed.append("supplier")
    for field, value in (("reference", reference), ("notes", notes)):
        if value is not _UNSET:
            setattr(locked, field, value)
            changed.append(field)
    if changed:
        locked.save(update_fields=[*changed, "updated_at"])
    return locked


@transaction.atomic
def add_purchase_line(
    *, business, purchase, product, quantity, unit_cost, user, tax_rate=ZERO_MONEY
):
    locked = _lock_purchase(business=business, purchase=purchase)
    _validate_draft(locked)
    _validate_store_access(
        business=business, store=locked.store, user=user, require_active=True
    )
    if product is None or not getattr(product, "pk", None):
        raise ValidationError({"product": "Debes indicar un producto."})
    try:
        current_product = Product.objects.get(
            pk=product.pk, business=business, is_active=True
        )
    except Product.DoesNotExist as exc:
        raise ValidationError(
            {"product": "El producto no está activo en el negocio actual."}
        ) from exc
    calculated = calculate_purchase_line_amounts(
        quantity=quantity, unit_cost=unit_cost, tax_rate=tax_rate
    )
    line = PurchaseLine(
        business=business,
        purchase=locked,
        product=current_product,
        product_name=current_product.name,
        sku=current_product.sku,
        unit=current_product.unit,
        quantity_received=ZERO_QUANTITY,
        **calculated,
    )
    line.save()
    _recalculate_locked_purchase(locked)
    return line


@transaction.atomic
def update_purchase_line(
    *, business, purchase, line, quantity, unit_cost, tax_rate, user
):
    locked = _lock_purchase(business=business, purchase=purchase)
    _validate_draft(locked)
    _validate_store_access(
        business=business, store=locked.store, user=user, require_active=True
    )
    locked_line = _lock_line(business=business, purchase=locked, line=line)
    calculated = calculate_purchase_line_amounts(
        quantity=quantity, unit_cost=unit_cost, tax_rate=tax_rate
    )
    for field, value in calculated.items():
        setattr(locked_line, field, value)
    locked_line.save(update_fields=[*calculated, "updated_at"])
    _recalculate_locked_purchase(locked)
    return locked_line


@transaction.atomic
def delete_purchase_line(*, business, purchase, line, user):
    locked = _lock_purchase(business=business, purchase=purchase)
    _validate_draft(locked)
    _validate_store_access(
        business=business, store=locked.store, user=user, require_active=True
    )
    locked_line = _lock_line(business=business, purchase=locked, line=line)
    locked_line.delete()
    _recalculate_locked_purchase(locked)


@transaction.atomic
def order_purchase(*, business, purchase, ordered_by):
    locked = _lock_purchase(business=business, purchase=purchase)
    _validate_store_access(
        business=business,
        store=locked.store,
        user=ordered_by,
        require_active=True,
    )
    if locked.status == PurchaseStatusChoices.ORDERED:
        return locked
    if locked.status != PurchaseStatusChoices.DRAFT:
        raise ValidationError("La compra no puede pasar al estado ordered.")
    previous_status = locked.status
    if not locked.supplier.is_active:
        raise ValidationError({"supplier": "El proveedor debe estar activo."})

    lines = list(
        PurchaseLine.objects.select_for_update()
        .select_related("product")
        .filter(business=business, purchase=locked)
        .order_by("product_id", "pk")
    )
    if not lines:
        raise ValidationError("La compra necesita al menos una línea.")
    for line in lines:
        if line.product.business_id != business.pk:
            raise ValidationError("Una línea contiene un producto de otro negocio.")
        if not line.product.is_active:
            raise ValidationError(
                {"product": "Todos los productos deben estar activos."}
            )
        _validate_line_integrity(line)
    _recalculate_locked_purchase(locked)
    locked.status = PurchaseStatusChoices.ORDERED
    locked.ordered_at = timezone.now()
    locked.save(update_fields=["status", "ordered_at", "updated_at"])
    log_event(
        business=business,
        store=locked.store,
        user=ordered_by,
        event_type=AuditEventType.PURCHASE_ORDERED,
        module=AuditModule.PURCHASES,
        entity=locked,
        message=f"Compra #{locked.pk} pedida.",
        old_payload={"status": previous_status},
        new_payload={
            "status": locked.status,
            "ordered_at": locked.ordered_at,
            "subtotal_amount": locked.subtotal_amount,
            "tax_amount": locked.tax_amount,
            "total_amount": locked.total_amount,
        },
        metadata={"supplier_id": locked.supplier_id, "line_count": len(lines)},
    )
    return locked


@transaction.atomic
def cancel_purchase(*, business, purchase, cancelled_by):
    locked = _lock_purchase(business=business, purchase=purchase)
    _validate_store_access(
        business=business,
        store=locked.store,
        user=cancelled_by,
        require_active=False,
    )
    if locked.status == PurchaseStatusChoices.CANCELLED:
        return locked
    if locked.status not in {
        PurchaseStatusChoices.DRAFT,
        PurchaseStatusChoices.ORDERED,
    }:
        raise ValidationError("Una compra recibida no se puede cancelar.")
    if locked.receipts.exists():
        raise ValidationError("Una compra con recepciones no se puede cancelar.")
    if locked.lines.filter(quantity_received__gt=ZERO_QUANTITY).exists():
        raise ValidationError("Una compra con mercancía recibida no se puede cancelar.")
    previous_status = locked.status
    locked.status = PurchaseStatusChoices.CANCELLED
    locked.save(update_fields=["status", "updated_at"])
    log_event(
        business=business,
        store=locked.store,
        user=cancelled_by,
        event_type=AuditEventType.PURCHASE_CANCELLED,
        module=AuditModule.PURCHASES,
        entity=locked,
        message=f"Compra #{locked.pk} cancelada.",
        old_payload={"status": previous_status},
        new_payload={"status": locked.status},
        metadata={
            "supplier_id": locked.supplier_id,
            "total_amount": locked.total_amount,
        },
    )
    return locked


@transaction.atomic
def register_purchase_receipt(
    *,
    business,
    purchase,
    received_by,
    lines,
    idempotency_key,
    notes="",
    received_at=None,
):
    """Registra una recepción comercial y sus efectos físicos de forma atómica."""

    normalized_lines = _normalize_purchase_receipt_lines(lines)
    normalized_key = _normalize_idempotency_key(idempotency_key)

    # Purchase is the aggregate mutex: all state-dependent validation happens
    # after this lock, so concurrent receipts cannot consume the same remainder.
    locked_purchase = _lock_purchase(business=business, purchase=purchase)
    _validate_store_access(
        business=business,
        store=locked_purchase.store,
        user=received_by,
        require_active=False,
    )
    fingerprint = _build_purchase_receipt_fingerprint(
        business_id=business.pk,
        purchase_id=locked_purchase.pk,
        store_id=locked_purchase.store_id,
        lines=normalized_lines,
    )
    existing = _idempotent_receipt_or_conflict(
        business=business, key=normalized_key, fingerprint=fingerprint
    )
    if existing is not None:
        return existing

    previous_purchase_status = locked_purchase.status

    if locked_purchase.status not in {
        PurchaseStatusChoices.ORDERED,
        PurchaseStatusChoices.PARTIALLY_RECEIVED,
    }:
        raise ValidationError(
            "Solo se pueden recibir compras pedidas o parcialmente recibidas."
        )
    current_store = _validate_store_access(
        business=business,
        store=locked_purchase.store,
        user=received_by,
        require_active=True,
    )

    locked_lines = list(
        PurchaseLine.objects.select_for_update()
        .select_related("product")
        .filter(business=business, purchase=locked_purchase)
        .order_by("pk")
    )
    lines_by_id = {line.pk: line for line in locked_lines}
    requested = []
    for line_id, quantity in normalized_lines:
        locked_line = lines_by_id.get(line_id)
        if locked_line is None:
            raise ValidationError(
                {
                    "purchase_line": "La línea no pertenece a la compra y negocio actuales."
                }
            )
        requested.append((locked_line, quantity))

    historical_totals = {
        row["purchase_line_id"]: row["total"]
        for row in PurchaseReceiptLine.objects.filter(
            business=business, purchase_line_id__in=lines_by_id
        )
        .values("purchase_line_id")
        .annotate(total=Sum("quantity_received"))
    }
    for locked_line in locked_lines:
        historical = historical_totals.get(locked_line.pk, ZERO_QUANTITY)
        if locked_line.quantity_received != historical:
            raise ValidationError(
                {"quantity_received": "El histórico de recepciones es incoherente."}
            )

    for locked_line, quantity in requested:
        if locked_line.product.business_id != business.pk:
            raise ValidationError({"product": "El producto pertenece a otro negocio."})
        remaining = locked_line.quantity_ordered - locked_line.quantity_received
        if quantity > remaining:
            raise ValidationError(
                {"quantity_received": "La cantidad supera la pendiente de recibir."}
            )

    pos_settings = _get_pos_settings(business)
    inventory_by_product_id = {}
    if pos_settings.enable_stock_control:
        products = {
            line.product_id: line.product
            for line, _quantity_received in requested
            if line.product.track_stock
        }
        for product_id in sorted(products):
            inventory_by_product_id[product_id] = (
                get_or_create_inventory_item_for_purchase_receipt(
                    business=business,
                    store=current_store,
                    product=products[product_id],
                )
            )

    receipt_values = {
        "business": business,
        "store": current_store,
        "purchase": locked_purchase,
        "received_by": received_by,
        "received_at": received_at or timezone.now(),
        "notes": notes,
        "idempotency_key": normalized_key,
        "idempotency_fingerprint": fingerprint,
    }
    try:
        with transaction.atomic():
            receipt = PurchaseReceipt.objects.create(**receipt_values)
    except IntegrityError:
        existing = _idempotent_receipt_or_conflict(
            business=business, key=normalized_key, fingerprint=fingerprint
        )
        if existing is not None:
            return existing
        raise

    operation_id = _purchase_receipt_operation_id(
        business_id=business.pk, receipt_id=receipt.pk
    )
    stock_movement_count = 0
    for locked_line, quantity in requested:
        receipt_line = PurchaseReceiptLine.objects.create(
            business=business,
            receipt=receipt,
            purchase_line=locked_line,
            quantity_received=quantity,
        )
        inventory_item = inventory_by_product_id.get(locked_line.product_id)
        if inventory_item is not None:
            _inventory_item, _movement = increase_stock(
                inventory_item=inventory_item,
                quantity=receipt_line.quantity_received,
                movement_type=StockMovement.TYPE_PURCHASE_RECEIPT,
                user=received_by,
                unit_cost=locked_line.unit_cost,
                reference_type=StockMovement.REF_PURCHASE,
                reference_id=f"{receipt.pk}:{receipt_line.pk}",
                operation_id=operation_id,
                purchase=locked_purchase,
                purchase_line=locked_line,
                purchase_receipt=receipt,
                purchase_receipt_line=receipt_line,
                occurred_at=receipt.received_at,
            )
            stock_movement_count += 1
        locked_line.quantity_received = _quantity(
            locked_line.quantity_received + quantity
        )
        locked_line.save(update_fields=["quantity_received", "updated_at"])

    locked_purchase.status = (
        PurchaseStatusChoices.RECEIVED
        if all(line.quantity_received == line.quantity_ordered for line in locked_lines)
        else PurchaseStatusChoices.PARTIALLY_RECEIVED
    )
    locked_purchase.save(update_fields=["status", "updated_at"])
    log_event(
        business=business,
        store=current_store,
        user=received_by,
        event_type=AuditEventType.PURCHASE_RECEIVED,
        module=AuditModule.PURCHASES,
        entity=receipt,
        message=f"Recepción de compra #{receipt.pk} registrada.",
        old_payload={"purchase_status": previous_purchase_status},
        new_payload={
            "purchase_status": locked_purchase.status,
            "received_at": receipt.received_at,
        },
        metadata={
            "purchase_id": locked_purchase.pk,
            "supplier_id": locked_purchase.supplier_id,
            "line_count": len(requested),
            "stock_control_enabled": pos_settings.enable_stock_control,
            "inventory_effect_applied": stock_movement_count > 0,
            "stock_movement_count": stock_movement_count,
            "operation_id": operation_id,
        },
    )
    return receipt
