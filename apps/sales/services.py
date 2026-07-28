"""Servicios del módulo sales.

Reglas de arquitectura:
- Las views coordinan la petición HTTP.
- Los forms validan la entrada del usuario.
- Los selectors realizan lecturas reutilizables.
- Los services contienen la lógica de negocio y las escrituras.
- Sales no genera facturas ni envía directamente a VeriFactu.
"""

import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.business_config.models import POSSettings
from apps.catalog.models import Product
from apps.catalog.services import ProductTaxResolutionError, resolve_product_tax
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import decrease_stock, increase_stock
from apps.sales.models import (
    PaymentStatusChoices,
    RequestedDocumentTypeChoices,
    Sale,
    SaleLine,
    SaleReturn,
    SaleReturnLine,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.users.helpers import can_perform_sensitive_action, can_sell_in_store


MONEY_STEP = Decimal("0.01")
QUANTITY_STEP = Decimal("0.001")
PERCENT_BASE = Decimal("100.00")
ZERO_MONEY = Decimal("0.00")
ZERO_QUANTITY = Decimal("0.000")


# ==========================================================
# Conversión, redondeo y cálculo
# ==========================================================


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
    return _to_decimal(
        value,
        field_name="amount",
        default=ZERO_MONEY,
    ).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def _quantity(value):
    return _to_decimal(
        value,
        field_name="quantity",
    ).quantize(QUANTITY_STEP, rounding=ROUND_HALF_UP)


def calculate_sale_line_amounts(
    *,
    quantity,
    unit_base_price,
    discount_amount=ZERO_MONEY,
    tax_rate=ZERO_MONEY,
):
    """Calcula una línea usando importes sin IVA y redondeo por línea."""

    quantity = _quantity(quantity)
    unit_base_price = _money(unit_base_price)
    discount_amount = _money(discount_amount)
    tax_rate = _to_decimal(
        tax_rate,
        field_name="tax_rate",
        default=ZERO_MONEY,
    ).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)

    if quantity <= ZERO_QUANTITY:
        raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})

    if unit_base_price < ZERO_MONEY:
        raise ValidationError({"unit_base_price": "El precio no puede ser negativo."})

    if discount_amount < ZERO_MONEY:
        raise ValidationError(
            {"discount_amount": "El descuento no puede ser negativo."}
        )

    if tax_rate < ZERO_MONEY:
        raise ValidationError({"tax_rate": "El tipo impositivo no puede ser negativo."})

    gross_base_amount = _money(unit_base_price * quantity)

    if discount_amount > gross_base_amount:
        raise ValidationError(
            {
                "discount_amount": (
                    "El descuento no puede superar el importe bruto de la línea."
                )
            }
        )

    taxable_base_amount = _money(gross_base_amount - discount_amount)
    tax_amount = _money(taxable_base_amount * tax_rate / PERCENT_BASE)
    line_total = _money(taxable_base_amount + tax_amount)

    return {
        "quantity": quantity,
        "unit_base_price": unit_base_price,
        "discount_amount": discount_amount,
        "tax_rate": tax_rate,
        "gross_base_amount": gross_base_amount,
        "taxable_base_amount": taxable_base_amount,
        "tax_amount": tax_amount,
        "line_total": line_total,
    }


# ==========================================================
# Validaciones compartidas
# ==========================================================


def _get_pos_settings(business):
    if business is None:
        raise ValidationError("No se ha indicado el negocio.")

    try:
        settings = business.pos_settings
    except ObjectDoesNotExist:
        settings = POSSettings.objects.filter(business=business).first()

    if settings is None:
        raise ValidationError("El negocio no tiene configuración TPV.")

    return settings


def _validate_business_object(*, business, obj, field_name):
    if obj is None:
        return

    if getattr(obj, "business_id", None) != business.pk:
        raise ValidationError(
            {field_name: ("El registro seleccionado no pertenece al negocio actual.")}
        )


def _validate_user(*, business, user):
    if user is None:
        raise ValidationError({"user": "Debes indicar el usuario responsable."})

    if not getattr(user, "is_authenticated", False):
        raise ValidationError({"user": "El usuario debe estar autenticado."})

    if not getattr(user, "is_active", False):
        raise ValidationError({"user": "El usuario responsable está inactivo."})

    if not user.is_superuser and user.business_id != business.pk:
        raise ValidationError({"user": "El usuario no pertenece al negocio actual."})


def _validate_can_sell(*, business, store, user):
    _validate_user(business=business, user=user)
    _validate_business_object(
        business=business,
        obj=store,
        field_name="store",
    )

    if not store.is_active:
        raise ValidationError({"store": "No se puede vender en una tienda inactiva."})

    if not can_sell_in_store(user, store):
        raise ValidationError({"user": "No tienes permiso para vender en esta tienda."})


def _validate_sensitive_action(
    *,
    business,
    user,
    pin,
    pos_settings,
):
    _validate_user(business=business, user=user)

    if not can_perform_sensitive_action(user):
        raise ValidationError("Solo owner o manager pueden realizar esta acción.")

    if pos_settings.require_pin_for_sensitive_actions:
        if not pin:
            raise ValidationError({"pin": "Debes indicar el PIN de seguridad."})

        if not user.check_pin(pin):
            raise ValidationError({"pin": "El PIN indicado no es válido."})


def _validate_customer(
    *,
    business,
    customer,
    document_type_requested,
    require_fiscal_identity=False,
):
    if document_type_requested not in RequestedDocumentTypeChoices.values:
        raise ValidationError(
            {
                "document_type_requested": (
                    "El tipo de documento solicitado no es válido."
                )
            }
        )

    if customer is not None:
        _validate_business_object(
            business=business,
            obj=customer,
            field_name="customer",
        )

        if not customer.is_active:
            raise ValidationError(
                {"customer": "El cliente seleccionado está inactivo."}
            )

    if (
        document_type_requested == RequestedDocumentTypeChoices.INVOICE
        and customer is None
    ):
        raise ValidationError(
            {"customer": ("Una venta con factura solicitada necesita cliente.")}
        )

    if (
        require_fiscal_identity
        and document_type_requested == RequestedDocumentTypeChoices.INVOICE
        and not customer.has_complete_fiscal_identity
    ):
        raise ValidationError(
            {
                "customer": (
                    "El cliente no tiene una identidad fiscal completa "
                    "para emitir una factura."
                )
            }
        )


def _is_session_open(cash_session):
    if cash_session is None:
        return False

    is_open = getattr(cash_session, "is_open", None)

    if callable(is_open):
        return bool(is_open())

    if is_open is not None:
        return bool(is_open)

    if hasattr(cash_session, "status"):
        return str(cash_session.status).lower() == "open"

    if hasattr(cash_session, "closed_at"):
        return cash_session.closed_at is None

    # Adaptar cuando se cierre el contrato definitivo de CashSession.
    return True


def _validate_cash_context(
    *,
    business,
    store,
    cash_register,
    cash_session,
    pos_settings,
):
    if bool(cash_register) != bool(cash_session):
        raise ValidationError(
            {
                "cash_session": (
                    "La caja y la sesión de caja deben indicarse conjuntamente."
                )
            }
        )

    if pos_settings.require_open_cash_register:
        if cash_register is None:
            raise ValidationError({"cash_register": "Debes seleccionar una caja."})

        if cash_session is None:
            raise ValidationError(
                {"cash_session": ("Debe existir una sesión de caja abierta.")}
            )

    if cash_register is not None:
        _validate_business_object(
            business=business,
            obj=cash_register,
            field_name="cash_register",
        )

        register_store_id = getattr(cash_register, "store_id", None)

        if register_store_id is not None and register_store_id != store.pk:
            raise ValidationError(
                {"cash_register": ("La caja no pertenece a la tienda de la venta.")}
            )

        if hasattr(cash_register, "is_active") and not cash_register.is_active:
            raise ValidationError(
                {"cash_register": "La caja seleccionada está inactiva."}
            )

    if cash_session is not None:
        _validate_business_object(
            business=business,
            obj=cash_session,
            field_name="cash_session",
        )

        session_store_id = getattr(cash_session, "store_id", None)

        if session_store_id is not None and session_store_id != store.pk:
            raise ValidationError(
                {"cash_session": ("La sesión de caja no pertenece a la tienda.")}
            )

        session_register_id = getattr(
            cash_session,
            "cash_register_id",
            None,
        )

        if (
            cash_register is not None
            and session_register_id is not None
            and session_register_id != cash_register.pk
        ):
            raise ValidationError(
                {"cash_session": ("La sesión no pertenece a la caja seleccionada.")}
            )

        if not _is_session_open(cash_session):
            raise ValidationError(
                {"cash_session": "La sesión de caja no está abierta."}
            )


def _lock_sale(*, business, sale):
    if sale is None or sale.pk is None:
        raise ValidationError("La venta no existe.")

    try:
        return (
            Sale.objects.select_for_update()
            .select_related(
                "business",
                "store",
                "cash_register",
                "cash_session",
                "customer",
                "opened_by",
                "closed_by",
            )
            .get(pk=sale.pk, business=business)
        )
    except Sale.DoesNotExist as exc:
        raise ValidationError("La venta no pertenece al negocio actual.") from exc


def _lock_return(*, business, return_doc):
    if return_doc is None or return_doc.pk is None:
        raise ValidationError("La devolución no existe.")

    try:
        return (
            SaleReturn.objects.select_for_update()
            .select_related(
                "business",
                "store",
                "original_sale",
                "created_by",
            )
            .get(pk=return_doc.pk, business=business)
        )
    except SaleReturn.DoesNotExist as exc:
        raise ValidationError("La devolución no pertenece al negocio actual.") from exc


def _validate_sale_editable(sale):
    if not sale.is_editable:
        raise ValidationError("La venta ya no admite modificaciones.")

    if sale.payment_status != PaymentStatusChoices.UNPAID:
        raise ValidationError(
            "No se puede editar una venta que ya tiene cobros aplicados."
        )


def _validate_return_editable(return_doc):
    if not return_doc.is_editable:
        raise ValidationError("La devolución ya no admite modificaciones.")


def _validate_manual_pricing(
    *,
    pos_settings,
    reference_price,
    unit_base_price,
    quantity,
    discount_amount,
):
    if unit_base_price != reference_price and not pos_settings.allow_manual_price:
        raise ValidationError(
            {
                "unit_base_price": (
                    "La configuración del negocio no permite precios manuales."
                )
            }
        )

    if discount_amount <= ZERO_MONEY:
        return

    if not pos_settings.allow_manual_discounts:
        raise ValidationError(
            {
                "discount_amount": (
                    "La configuración del negocio no permite descuentos manuales."
                )
            }
        )

    gross_amount = _money(unit_base_price * quantity)

    if gross_amount == ZERO_MONEY:
        raise ValidationError(
            {
                "discount_amount": (
                    "No se puede aplicar descuento sobre una línea con importe cero."
                )
            }
        )

    discount_percent = discount_amount / gross_amount * PERCENT_BASE

    if discount_percent > pos_settings.max_manual_discount_percent:
        raise ValidationError(
            {
                "discount_amount": (
                    "El descuento supera el máximo permitido "
                    f"({pos_settings.max_manual_discount_percent} %)."
                )
            }
        )


def _validate_supported_tax_snapshot(tax):
    """Impide perder datos fiscales que SaleLine aún no almacena."""

    if getattr(tax, "tax_type", "IVA") != "IVA":
        raise ValidationError(
            {
                "product": (
                    "SaleLine todavía no guarda el tipo de impuesto "
                    "necesario para esta operación."
                )
            }
        )

    if getattr(tax, "clave_regimen", "01") not in (None, "", "01"):
        raise ValidationError(
            {
                "product": (
                    "SaleLine todavía no guarda la clave de régimen "
                    "necesaria para esta operación."
                )
            }
        )

    if getattr(tax, "has_equivalence_surcharge", False):
        raise ValidationError(
            {
                "product": (
                    "El impuesto aplica recargo de equivalencia, pero "
                    "SaleLine todavía no guarda ese snapshot fiscal."
                )
            }
        )

    if getattr(tax, "operacion_exenta", None):
        raise ValidationError(
            {
                "product": (
                    "Las operaciones exentas requieren ampliar el "
                    "snapshot fiscal de SaleLine."
                )
            }
        )

    ordinary_qualification = getattr(
        tax,
        "CALIFICACION_SUJETA_NO_EXENTA",
        "S1",
    )

    if (
        getattr(tax, "calificacion_operacion", ordinary_qualification)
        != ordinary_qualification
    ):
        raise ValidationError(
            {
                "product": (
                    "El tratamiento fiscal del producto no puede "
                    "congelarse por completo con SaleLine."
                )
            }
        )


def _operation_uuid(prefix, business_id, object_id):
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"netxodo:{prefix}:{business_id}:{object_id}",
    )


# ==========================================================
# Venta: apertura y cabecera
# ==========================================================


@transaction.atomic
def open_sale(
    *,
    business,
    store,
    opened_by,
    customer=None,
    document_type_requested=RequestedDocumentTypeChoices.TICKET,
    cash_register=None,
    cash_session=None,
):
    """Abre una venta directamente en estado open."""

    if business is None:
        raise ValidationError("No se ha indicado el negocio.")

    _validate_can_sell(
        business=business,
        store=store,
        user=opened_by,
    )

    pos_settings = _get_pos_settings(business)

    _validate_customer(
        business=business,
        customer=customer,
        document_type_requested=document_type_requested,
    )

    _validate_cash_context(
        business=business,
        store=store,
        cash_register=cash_register,
        cash_session=cash_session,
        pos_settings=pos_settings,
    )

    sale = Sale(
        business=business,
        store=store,
        cash_register=cash_register,
        cash_session=cash_session,
        customer=customer,
        opened_by=opened_by,
        status=SaleStatusChoices.OPEN,
        document_type_requested=document_type_requested,
        payment_status=PaymentStatusChoices.UNPAID,
        subtotal_amount=ZERO_MONEY,
        discount_amount=ZERO_MONEY,
        tax_amount=ZERO_MONEY,
        total_amount=ZERO_MONEY,
        pending_amount=ZERO_MONEY,
    )
    sale.save()
    return sale


@transaction.atomic
def update_sale_header(
    *,
    business,
    sale,
    customer,
    document_type_requested,
    updated_by,
):
    """Actualiza cliente y documento solicitado de una venta editable."""

    locked_sale = _lock_sale(business=business, sale=sale)
    _validate_sale_editable(locked_sale)

    _validate_can_sell(
        business=business,
        store=locked_sale.store,
        user=updated_by,
    )

    _validate_customer(
        business=business,
        customer=customer,
        document_type_requested=document_type_requested,
    )

    locked_sale.customer = customer
    locked_sale.document_type_requested = document_type_requested
    locked_sale.save(
        update_fields=[
            "customer",
            "document_type_requested",
            "updated_at",
        ]
    )
    return locked_sale


# ==========================================================
# Venta: importes y líneas
# ==========================================================


def _recalculate_locked_sale(locked_sale):
    lines = list(
        SaleLine.objects.filter(
            business=locked_sale.business,
            sale=locked_sale,
        ).only(
            "quantity",
            "unit_base_price",
            "discount_amount",
            "tax_amount",
            "line_total",
        )
    )

    subtotal_amount = _money(
        sum(
            (_money(line.unit_base_price * line.quantity) for line in lines),
            ZERO_MONEY,
        )
    )
    discount_amount = _money(sum((line.discount_amount for line in lines), ZERO_MONEY))
    tax_amount = _money(sum((line.tax_amount for line in lines), ZERO_MONEY))
    total_amount = _money(subtotal_amount - discount_amount + tax_amount)
    line_total_sum = _money(sum((line.line_total for line in lines), ZERO_MONEY))

    if total_amount != line_total_sum:
        raise ValidationError("Los importes de las líneas no coinciden con el total.")

    locked_sale.subtotal_amount = subtotal_amount
    locked_sale.discount_amount = discount_amount
    locked_sale.tax_amount = tax_amount
    locked_sale.total_amount = total_amount
    locked_sale.pending_amount = total_amount
    locked_sale.save(
        update_fields=[
            "subtotal_amount",
            "discount_amount",
            "tax_amount",
            "total_amount",
            "pending_amount",
            "updated_at",
        ]
    )
    return locked_sale


@transaction.atomic
def recalculate_sale(*, business, sale):
    locked_sale = _lock_sale(business=business, sale=sale)
    _validate_sale_editable(locked_sale)
    return _recalculate_locked_sale(locked_sale)


@transaction.atomic
def add_sale_line(
    *,
    business,
    sale,
    product,
    quantity,
    user,
    unit_base_price=None,
    discount_amount=None,
):
    """Añade una línea congelando datos comerciales e IVA."""

    locked_sale = _lock_sale(business=business, sale=sale)
    _validate_sale_editable(locked_sale)

    _validate_can_sell(
        business=business,
        store=locked_sale.store,
        user=user,
    )

    if product is None or product.pk is None:
        raise ValidationError({"product": "Debes indicar un producto."})

    try:
        current_product = Product.objects.select_related("tax", "category").get(
            pk=product.pk,
            business=business,
            is_active=True,
        )
    except Product.DoesNotExist as exc:
        raise ValidationError(
            {"product": "El producto no está disponible para la venta."}
        ) from exc

    pos_settings = _get_pos_settings(business)
    quantity = _quantity(quantity)
    reference_price = _money(current_product.base_price)
    effective_price = (
        reference_price if unit_base_price is None else _money(unit_base_price)
    )
    effective_discount = _money(
        ZERO_MONEY if discount_amount is None else discount_amount
    )

    _validate_manual_pricing(
        pos_settings=pos_settings,
        reference_price=reference_price,
        unit_base_price=effective_price,
        quantity=quantity,
        discount_amount=effective_discount,
    )

    try:
        tax = resolve_product_tax(current_product)
    except ProductTaxResolutionError as exc:
        raise ValidationError({"product": str(exc)}) from exc

    _validate_supported_tax_snapshot(tax)

    calculated = calculate_sale_line_amounts(
        quantity=quantity,
        unit_base_price=effective_price,
        discount_amount=effective_discount,
        tax_rate=tax.rate,
    )

    line = SaleLine(
        business=business,
        sale=locked_sale,
        product=current_product,
        product_name=current_product.name,
        sku=current_product.sku or "",
        quantity=calculated["quantity"],
        unit=current_product.unit,
        unit_base_price=calculated["unit_base_price"],
        discount_amount=calculated["discount_amount"],
        tax_rate=calculated["tax_rate"],
        tax_amount=calculated["tax_amount"],
        line_total=calculated["line_total"],
    )
    line.save()
    _recalculate_locked_sale(locked_sale)
    return line


@transaction.atomic
def update_sale_line(
    *,
    business,
    sale,
    line,
    quantity,
    user,
    unit_base_price=None,
    discount_amount=None,
):
    """Actualiza una línea conservando el impuesto histórico."""

    locked_sale = _lock_sale(business=business, sale=sale)
    _validate_sale_editable(locked_sale)

    _validate_can_sell(
        business=business,
        store=locked_sale.store,
        user=user,
    )

    try:
        locked_line = (
            SaleLine.objects.select_for_update()
            .select_related("product")
            .get(
                pk=line.pk,
                business=business,
                sale=locked_sale,
            )
        )
    except SaleLine.DoesNotExist as exc:
        raise ValidationError("La línea no pertenece a la venta indicada.") from exc

    pos_settings = _get_pos_settings(business)
    quantity = _quantity(quantity)
    reference_price = _money(locked_line.unit_base_price)
    effective_price = (
        reference_price if unit_base_price is None else _money(unit_base_price)
    )
    effective_discount = _money(
        locked_line.discount_amount if discount_amount is None else discount_amount
    )

    _validate_manual_pricing(
        pos_settings=pos_settings,
        reference_price=reference_price,
        unit_base_price=effective_price,
        quantity=quantity,
        discount_amount=effective_discount,
    )

    calculated = calculate_sale_line_amounts(
        quantity=quantity,
        unit_base_price=effective_price,
        discount_amount=effective_discount,
        tax_rate=locked_line.tax_rate,
    )

    locked_line.quantity = calculated["quantity"]
    locked_line.unit_base_price = calculated["unit_base_price"]
    locked_line.discount_amount = calculated["discount_amount"]
    locked_line.tax_amount = calculated["tax_amount"]
    locked_line.line_total = calculated["line_total"]
    locked_line.save(
        update_fields=[
            "quantity",
            "unit_base_price",
            "discount_amount",
            "tax_amount",
            "line_total",
            "updated_at",
        ]
    )

    _recalculate_locked_sale(locked_sale)
    return locked_line


@transaction.atomic
def delete_sale_line(*, business, sale, line, user):
    """Elimina una línea de una venta editable."""

    locked_sale = _lock_sale(business=business, sale=sale)
    _validate_sale_editable(locked_sale)

    _validate_can_sell(
        business=business,
        store=locked_sale.store,
        user=user,
    )

    try:
        locked_line = SaleLine.objects.select_for_update().get(
            pk=line.pk,
            business=business,
            sale=locked_sale,
        )
    except SaleLine.DoesNotExist as exc:
        raise ValidationError("La línea no pertenece a la venta indicada.") from exc

    locked_line.delete()
    _recalculate_locked_sale(locked_sale)
    return locked_sale


# ==========================================================
# Venta: completar y cancelar
# ==========================================================


def _validate_line_integrity(line):
    calculated = calculate_sale_line_amounts(
        quantity=line.quantity,
        unit_base_price=line.unit_base_price,
        discount_amount=line.discount_amount,
        tax_rate=line.tax_rate,
    )

    if (
        calculated["tax_amount"] != line.tax_amount
        or calculated["line_total"] != line.line_total
    ):
        raise ValidationError(f"La línea {line.pk} contiene importes inconsistentes.")


@transaction.atomic
def complete_sale(*, business, sale, closed_by):
    """Completa una venta y descuenta stock de forma atómica."""

    locked_sale = _lock_sale(business=business, sale=sale)

    if locked_sale.status == SaleStatusChoices.COMPLETED:
        return locked_sale

    if locked_sale.status in {
        SaleStatusChoices.CANCELLED,
        SaleStatusChoices.RETURNED,
    }:
        raise ValidationError("La venta no puede completarse desde su estado actual.")

    if locked_sale.status != SaleStatusChoices.OPEN:
        raise ValidationError("Solo se puede completar una venta abierta.")

    _validate_can_sell(
        business=business,
        store=locked_sale.store,
        user=closed_by,
    )

    pos_settings = _get_pos_settings(business)

    _validate_customer(
        business=business,
        customer=locked_sale.customer,
        document_type_requested=locked_sale.document_type_requested,
        require_fiscal_identity=True,
    )

    _validate_cash_context(
        business=business,
        store=locked_sale.store,
        cash_register=locked_sale.cash_register,
        cash_session=locked_sale.cash_session,
        pos_settings=pos_settings,
    )

    lines = list(
        SaleLine.objects.select_for_update()
        .select_related("product")
        .filter(business=business, sale=locked_sale)
        .order_by("product_id", "pk")
    )

    if not lines:
        raise ValidationError("No se puede completar una venta sin líneas.")

    _recalculate_locked_sale(locked_sale)

    for line in lines:
        _validate_line_integrity(line)

    if locked_sale.total_amount <= ZERO_MONEY:
        raise ValidationError("El total de la venta debe ser mayor que cero.")

    if pos_settings.enable_stock_control:
        operation_id = _operation_uuid(
            "sale",
            business.pk,
            locked_sale.pk,
        )

        for line in lines:
            product = line.product

            if product is None or product.is_service or not product.track_stock:
                continue

            try:
                inventory_item = InventoryItem.objects.get(
                    business=business,
                    store=locked_sale.store,
                    product=product,
                    is_active=True,
                )
            except InventoryItem.DoesNotExist as exc:
                raise ValidationError(
                    {
                        "stock": (
                            "No existe una ficha de inventario activa "
                            f"para '{line.product_name}' en esta tienda."
                        )
                    }
                ) from exc

            decrease_stock(
                inventory_item=inventory_item,
                quantity=line.quantity,
                movement_type=StockMovement.TYPE_SALE,
                user=closed_by,
                unit_cost=product.cost_price,
                reference_type=StockMovement.REF_SALE,
                reference_id=f"{locked_sale.pk}:{line.pk}",
                reason=f"Salida por venta #{locked_sale.pk}",
                notes=f"Línea de venta #{line.pk}",
                operation_id=operation_id,
                allow_negative=pos_settings.allow_sale_without_stock,
            )

    locked_sale.status = SaleStatusChoices.COMPLETED
    locked_sale.closed_by = closed_by
    locked_sale.completed_at = timezone.now()
    locked_sale.save(
        update_fields=[
            "status",
            "closed_by",
            "completed_at",
            "updated_at",
        ]
    )

    return locked_sale


@transaction.atomic
def cancel_sale(*, business, sale, cancelled_by, pin=None):
    """Cancela una venta editable sin eliminarla."""

    locked_sale = _lock_sale(business=business, sale=sale)

    if locked_sale.status == SaleStatusChoices.CANCELLED:
        return locked_sale

    if locked_sale.status in {
        SaleStatusChoices.COMPLETED,
        SaleStatusChoices.RETURNED,
    }:
        raise ValidationError("Una venta completada no se cancela; debe devolverse.")

    _validate_sale_editable(locked_sale)

    _validate_can_sell(
        business=business,
        store=locked_sale.store,
        user=cancelled_by,
    )

    pos_settings = _get_pos_settings(business)
    _validate_sensitive_action(
        business=business,
        user=cancelled_by,
        pin=pin,
        pos_settings=pos_settings,
    )

    locked_sale.status = SaleStatusChoices.CANCELLED
    locked_sale.closed_by = cancelled_by
    locked_sale.completed_at = None
    locked_sale.save(
        update_fields=[
            "status",
            "closed_by",
            "completed_at",
            "updated_at",
        ]
    )
    return locked_sale


# ==========================================================
# Devoluciones: importes
# ==========================================================


def _completed_return_totals(*, business, original_line):
    result = SaleReturnLine.objects.filter(
        business=business,
        original_line=original_line,
        return_doc__status=SaleReturnStatusChoices.COMPLETED,
    ).aggregate(
        quantity=Sum("quantity"),
        amount=Sum("amount"),
    )

    return (
        result["quantity"] or ZERO_QUANTITY,
        result["amount"] or ZERO_MONEY,
    )


def _remaining_return_capacity(*, business, original_line):
    returned_quantity, returned_amount = _completed_return_totals(
        business=business,
        original_line=original_line,
    )

    return (
        original_line.quantity - returned_quantity,
        _money(original_line.line_total - returned_amount),
    )


def _calculate_return_line_amount(*, business, original_line, quantity):
    quantity = _quantity(quantity)

    if quantity <= ZERO_QUANTITY:
        raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})

    remaining_quantity, remaining_amount = _remaining_return_capacity(
        business=business,
        original_line=original_line,
    )

    if quantity > remaining_quantity:
        raise ValidationError(
            {
                "quantity": (
                    "La cantidad supera lo que todavía puede devolverse "
                    f"({remaining_quantity})."
                )
            }
        )

    if quantity == remaining_quantity:
        return remaining_amount

    return _money(original_line.line_total * quantity / original_line.quantity)


def _recalculate_locked_return(return_doc):
    total_amount = (
        SaleReturnLine.objects.filter(
            business=return_doc.business,
            return_doc=return_doc,
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO_MONEY
    )

    return_doc.total_amount = _money(total_amount)
    return_doc.save(update_fields=["total_amount", "updated_at"])
    return return_doc


@transaction.atomic
def recalculate_sale_return(*, business, return_doc):
    locked_return = _lock_return(
        business=business,
        return_doc=return_doc,
    )
    _validate_return_editable(locked_return)
    return _recalculate_locked_return(locked_return)


# ==========================================================
# Devoluciones: cabecera y líneas
# ==========================================================


@transaction.atomic
def create_sale_return(
    *,
    business,
    store,
    original_sale,
    created_by,
    reason,
):
    """Crea una devolución en borrador sin tocar stock."""

    locked_sale = _lock_sale(
        business=business,
        sale=original_sale,
    )

    _validate_can_sell(
        business=business,
        store=store,
        user=created_by,
    )

    if locked_sale.store_id != store.pk:
        raise ValidationError("La devolución debe realizarse en la tienda de la venta.")

    if locked_sale.status != SaleStatusChoices.COMPLETED:
        raise ValidationError("Solo se pueden devolver ventas completadas.")

    reason = (reason or "").strip()

    if not reason:
        raise ValidationError({"reason": "Debes indicar el motivo de la devolución."})

    original_lines = list(
        SaleLine.objects.filter(
            business=business,
            sale=locked_sale,
        ).order_by("pk")
    )

    if not original_lines:
        raise ValidationError("La venta original no contiene líneas.")

    if not any(
        _remaining_return_capacity(
            business=business,
            original_line=line,
        )[0]
        > ZERO_QUANTITY
        for line in original_lines
    ):
        raise ValidationError(
            "La venta ya no tiene cantidades pendientes de devolución."
        )

    return_doc = SaleReturn(
        business=business,
        store=store,
        original_sale=locked_sale,
        created_by=created_by,
        reason=reason,
        status=SaleReturnStatusChoices.DRAFT,
        total_amount=ZERO_MONEY,
    )
    return_doc.save()
    return return_doc


@transaction.atomic
def add_sale_return_line(
    *,
    business,
    return_doc,
    original_line,
    quantity,
    user,
):
    """Añade una línea a una devolución en borrador."""

    locked_return = _lock_return(
        business=business,
        return_doc=return_doc,
    )
    _validate_return_editable(locked_return)

    _validate_can_sell(
        business=business,
        store=locked_return.store,
        user=user,
    )

    try:
        locked_original_line = (
            SaleLine.objects.select_for_update()
            .select_related("sale", "product")
            .get(
                pk=original_line.pk,
                business=business,
                sale=locked_return.original_sale,
            )
        )
    except SaleLine.DoesNotExist as exc:
        raise ValidationError("La línea no pertenece a la venta original.") from exc

    amount = _calculate_return_line_amount(
        business=business,
        original_line=locked_original_line,
        quantity=quantity,
    )

    try:
        return_line = SaleReturnLine(
            business=business,
            return_doc=locked_return,
            original_line=locked_original_line,
            quantity=_quantity(quantity),
            amount=amount,
        )
        return_line.save()
    except IntegrityError as exc:
        raise ValidationError(
            {"original_line": ("Esta línea ya está incluida en la devolución.")}
        ) from exc

    _recalculate_locked_return(locked_return)
    return return_line


@transaction.atomic
def update_sale_return_line(
    *,
    business,
    return_doc,
    line,
    quantity,
    user,
):
    """Actualiza la cantidad de una línea de devolución en borrador."""

    locked_return = _lock_return(
        business=business,
        return_doc=return_doc,
    )
    _validate_return_editable(locked_return)

    _validate_can_sell(
        business=business,
        store=locked_return.store,
        user=user,
    )

    try:
        locked_line = (
            SaleReturnLine.objects.select_for_update()
            .select_related(
                "original_line",
                "original_line__sale",
                "original_line__product",
            )
            .get(
                pk=line.pk,
                business=business,
                return_doc=locked_return,
            )
        )
    except SaleReturnLine.DoesNotExist as exc:
        raise ValidationError(
            "La línea no pertenece a la devolución indicada."
        ) from exc

    amount = _calculate_return_line_amount(
        business=business,
        original_line=locked_line.original_line,
        quantity=quantity,
    )

    locked_line.quantity = _quantity(quantity)
    locked_line.amount = amount
    locked_line.save(update_fields=["quantity", "amount", "updated_at"])

    _recalculate_locked_return(locked_return)
    return locked_line


@transaction.atomic
def delete_sale_return_line(
    *,
    business,
    return_doc,
    line,
    user,
):
    """Elimina una línea de una devolución en borrador."""

    locked_return = _lock_return(
        business=business,
        return_doc=return_doc,
    )
    _validate_return_editable(locked_return)

    _validate_can_sell(
        business=business,
        store=locked_return.store,
        user=user,
    )

    try:
        locked_line = SaleReturnLine.objects.select_for_update().get(
            pk=line.pk,
            business=business,
            return_doc=locked_return,
        )
    except SaleReturnLine.DoesNotExist as exc:
        raise ValidationError(
            "La línea no pertenece a la devolución indicada."
        ) from exc

    locked_line.delete()
    _recalculate_locked_return(locked_return)
    return locked_return


# ==========================================================
# Devoluciones: completar y cancelar
# ==========================================================


@transaction.atomic
def complete_sale_return(
    *,
    business,
    return_doc,
    completed_by,
    pin=None,
):
    """Completa una devolución y reintegra el stock físico."""

    locked_return = _lock_return(
        business=business,
        return_doc=return_doc,
    )

    if locked_return.status == SaleReturnStatusChoices.COMPLETED:
        return locked_return

    if locked_return.status == SaleReturnStatusChoices.CANCELLED:
        raise ValidationError("Una devolución cancelada no puede completarse.")

    _validate_return_editable(locked_return)

    _validate_can_sell(
        business=business,
        store=locked_return.store,
        user=completed_by,
    )

    pos_settings = _get_pos_settings(business)
    _validate_sensitive_action(
        business=business,
        user=completed_by,
        pin=pin,
        pos_settings=pos_settings,
    )

    locked_sale = _lock_sale(
        business=business,
        sale=locked_return.original_sale,
    )

    if locked_sale.status not in {
        SaleStatusChoices.COMPLETED,
        SaleStatusChoices.RETURNED,
    }:
        raise ValidationError("La venta original no admite devoluciones.")

    return_lines = list(
        SaleReturnLine.objects.select_for_update()
        .select_related("original_line", "original_line__product")
        .filter(business=business, return_doc=locked_return)
        .order_by("original_line_id", "pk")
    )

    if not return_lines:
        raise ValidationError("No se puede completar una devolución sin líneas.")

    total_amount = ZERO_MONEY

    for return_line in return_lines:
        original_line = (
            SaleLine.objects.select_for_update()
            .select_related("product")
            .get(
                pk=return_line.original_line_id,
                business=business,
                sale=locked_sale,
            )
        )

        amount = _calculate_return_line_amount(
            business=business,
            original_line=original_line,
            quantity=return_line.quantity,
        )

        return_line.amount = amount
        return_line.save(update_fields=["amount", "updated_at"])
        total_amount += amount

    total_amount = _money(total_amount)

    if total_amount <= ZERO_MONEY:
        raise ValidationError("El total de la devolución debe ser mayor que cero.")

    if pos_settings.enable_stock_control:
        operation_id = _operation_uuid(
            "sale-return",
            business.pk,
            locked_return.pk,
        )

        for return_line in return_lines:
            product = return_line.original_line.product

            if product is None or product.is_service or not product.track_stock:
                continue

            try:
                inventory_item = InventoryItem.objects.get(
                    business=business,
                    store=locked_return.store,
                    product=product,
                    is_active=True,
                )
            except InventoryItem.DoesNotExist as exc:
                raise ValidationError(
                    {
                        "stock": (
                            "No existe una ficha de inventario activa "
                            f"para '{return_line.original_line.product_name}'."
                        )
                    }
                ) from exc

            increase_stock(
                inventory_item=inventory_item,
                quantity=return_line.quantity,
                movement_type=StockMovement.TYPE_SALE_RETURN,
                user=completed_by,
                unit_cost=product.cost_price,
                reference_type=StockMovement.REF_SALE,
                reference_id=(f"return:{locked_return.pk}:{return_line.pk}"),
                reason=f"Entrada por devolución #{locked_return.pk}",
                notes=(f"Línea original #{return_line.original_line_id}"),
                operation_id=operation_id,
            )

    locked_return.total_amount = total_amount
    locked_return.status = SaleReturnStatusChoices.COMPLETED
    locked_return.save(update_fields=["total_amount", "status", "updated_at"])

    original_lines = list(
        SaleLine.objects.filter(
            business=business,
            sale=locked_sale,
        ).order_by("pk")
    )

    fully_returned = bool(original_lines)

    for original_line in original_lines:
        returned_quantity = (
            SaleReturnLine.objects.filter(
                business=business,
                original_line=original_line,
                return_doc__status=SaleReturnStatusChoices.COMPLETED,
            ).aggregate(total=Sum("quantity"))["total"]
            or ZERO_QUANTITY
        )

        if returned_quantity < original_line.quantity:
            fully_returned = False
            break

    locked_sale.status = (
        SaleStatusChoices.RETURNED if fully_returned else SaleStatusChoices.COMPLETED
    )
    locked_sale.save(update_fields=["status", "updated_at"])

    # Payments realizará el reembolso y Billing la rectificativa.
    return locked_return


@transaction.atomic
def cancel_sale_return(
    *,
    business,
    return_doc,
    cancelled_by,
    pin=None,
):
    """Cancela una devolución en borrador sin modificar stock."""

    locked_return = _lock_return(
        business=business,
        return_doc=return_doc,
    )

    if locked_return.status == SaleReturnStatusChoices.CANCELLED:
        return locked_return

    if locked_return.status == SaleReturnStatusChoices.COMPLETED:
        raise ValidationError("Una devolución completada no puede cancelarse.")

    _validate_return_editable(locked_return)

    _validate_can_sell(
        business=business,
        store=locked_return.store,
        user=cancelled_by,
    )

    pos_settings = _get_pos_settings(business)
    _validate_sensitive_action(
        business=business,
        user=cancelled_by,
        pin=pin,
        pos_settings=pos_settings,
    )

    locked_return.status = SaleReturnStatusChoices.CANCELLED
    locked_return.save(update_fields=["status", "updated_at"])
    return locked_return
