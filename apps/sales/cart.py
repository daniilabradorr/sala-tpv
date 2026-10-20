"""Versioned cart protocol. Domain effects stay in the existing Sales services."""

import hashlib
import json
from uuid import UUID
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.catalog.models import Product
from apps.sales.models import CartOperation, Sale, SaleLine
from apps.sales.services import (
    _validate_can_sell,
    _validate_sale_editable,
    add_sale_line,
    update_sale_line,
    delete_sale_line,
)


class CartConflict(ValidationError):
    def __init__(self, message, *, code="version"):
        self.conflict_code = code
        super().__init__(message)


def line_group(line):
    """Only commercially equivalent snapshots may share a visual quantity control."""
    values = [
        str(getattr(line, field))
        for field in (
            "product_id",
            "product_name",
            "sku",
            "unit",
            "unit_base_price",
            "discount_amount",
            "tax_rate",
            "tax_type",
            "clave_regimen",
            "calificacion_operacion",
        )
    ]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()[:24]


def snapshot(sale):
    return {
        "sale_id": sale.pk,
        "store_id": sale.store_id,
        "business_id": sale.business_id,
        "version": sale.cart_version,
        "status": sale.status,
        "total": str(sale.total_amount),
        "subtotal": str(sale.subtotal_amount),
        "tax": str(sale.tax_amount),
        "discount": str(sale.discount_amount),
        "lines": [
            {
                "id": line.pk,
                "product": line.product_id,
                "name": line.product_name,
                "group": line_group(line),
                "quantity": str(line.quantity),
                "price": str(line.unit_base_price),
                "total": str(line.line_total),
            }
            for line in sale.lines.order_by("pk")
        ],
    }


def normalize(data):
    try:
        key = UUID(str(data["key"]))
        if isinstance(data["version"], bool) or not str(data["version"]).isdigit():
            raise ValueError
        version = int(data["version"])
        kind = data["kind"]
        if kind not in ("add", "quantity", "delete") or version < 0:
            raise ValueError
        payload = {"kind": kind}
        field = "product" if kind == "add" else "line"
        if (
            isinstance(data[field], bool)
            or not str(data[field]).isdigit()
            or int(data[field]) <= 0
        ):
            raise ValueError
        payload[field] = int(data[field])
        if kind != "delete":
            quantity = Decimal(str(data["quantity"]))
            if (
                not quantity.is_finite()
                or quantity <= 0
                or quantity > Decimal("99999999999.999")
            ):
                raise ValueError
            if quantity.as_tuple().exponent < -3:
                raise ValueError
            payload["quantity"] = format(quantity.quantize(Decimal("0.001")), "f")
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise ValidationError("Operación de carrito no válida.") from error
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
    return key, version, payload, fingerprint


@transaction.atomic
def mutate(*, business, store, sale_id, user, data):
    sale = Sale.objects.select_for_update(of=("self",)).get(
        pk=sale_id, business=business, store=store
    )
    _validate_can_sell(business=business, store=store, user=user)
    key, version, payload, fingerprint = normalize(data)
    receipt = CartOperation.objects.filter(sale=sale, key=key).first()
    if receipt:
        if receipt.fingerprint != fingerprint:
            raise CartConflict("La clave ya se utilizó con otro contenido.", code="key")
        return {
            "cart": snapshot(sale),
            "key": str(key),
            "replayed": True,
            "accepted_version": receipt.version,
            "line": receipt.line_id_result,
        }
    _validate_sale_editable(sale)
    if version != sale.cart_version:
        raise CartConflict(
            "La venta ha cambiado en otra ventana. Revisa los cambios pendientes."
        )
    kind = payload["kind"]
    if kind == "add":
        try:
            product = Product.objects.get(
                pk=payload["product"], business=business, is_active=True
            )
        except Product.DoesNotExist as error:
            raise ValidationError("El producto ya no está disponible.") from error
        line = add_sale_line(
            business=business,
            sale=sale,
            product=product,
            quantity=payload["quantity"],
            user=user,
        )
    else:
        try:
            line = SaleLine.objects.get(
                pk=payload["line"], sale=sale, business=business
            )
        except SaleLine.DoesNotExist as error:
            raise CartConflict(
                "La línea ya no existe. Revisa el carrito.", code="line"
            ) from error
        if kind == "quantity":
            line = update_sale_line(
                business=business,
                sale=sale,
                line=line,
                quantity=payload["quantity"],
                user=user,
            )
        else:
            delete_sale_line(business=business, sale=sale, line=line, user=user)
    sale.refresh_from_db()
    CartOperation.objects.create(
        business=business,
        sale=sale,
        key=key,
        kind=kind,
        fingerprint=fingerprint,
        version=sale.cart_version,
        line_id_result=line.pk if kind != "delete" else None,
    )
    return {
        "cart": snapshot(sale),
        "key": str(key),
        "replayed": False,
        "accepted_version": sale.cart_version,
        "line": line.pk if kind != "delete" else None,
    }
