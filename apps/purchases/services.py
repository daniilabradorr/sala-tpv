"""Servicios del módulo purchases.

Reglas de arquitectura:
- Las views coordinan la petición HTTP.
- Los selectors realizan lecturas reutilizables.
- Los services contienen las mutaciones y las reglas de negocio.
- Crear u ordenar compras no modifica el inventario.
- La recepción de mercancía todavía no se implementa en este módulo.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.models import Business
from apps.purchases.models import (
    Purchase,
    PurchaseLine,
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
    locked.status = PurchaseStatusChoices.CANCELLED
    locked.save(update_fields=["status", "updated_at"])
    return locked
