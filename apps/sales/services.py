from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Sale, SaleLine, SaleReturn, SaleReturnLine

CENT = Decimal("0.01")


def _money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _assert_open(instance):
    if instance.status != instance.Status.OPEN:
        raise ValidationError("La operación ya no es editable.")


def _recalculate_sale(sale):
    subtotal = sum((line.subtotal for line in sale.lines.all()), Decimal("0"))
    tax_total = sum((line.tax_total for line in sale.lines.all()), Decimal("0"))
    Sale.objects.filter(pk=sale.pk).update(
        subtotal=_money(subtotal),
        tax_total=_money(tax_total),
        total=_money(subtotal + tax_total),
    )


@transaction.atomic
def open_sale(
    *,
    business,
    store,
    user,
    customer=None,
    cash_register=None,
    cash_session=None,
    requires_invoice=False,
    notes="",
):
    if user.business_id != business.pk or store.business_id != business.pk:
        raise ValidationError("Usuario y tienda deben pertenecer al negocio.")
    if bool(cash_register) != bool(cash_session):
        raise ValidationError("La caja y la sesión deben indicarse conjuntamente.")
    if cash_session and (
        not cash_session.is_open or cash_session.cash_register_id != cash_register.pk
    ):
        raise ValidationError("La sesión de caja no es válida o no está abierta.")
    sale = Sale(
        business=business,
        store=store,
        created_by=user,
        customer=customer,
        cash_register=cash_register,
        cash_session=cash_session,
        requires_invoice=requires_invoice,
        notes=notes,
    )
    sale.full_clean()
    sale.save()
    return sale


@transaction.atomic
def update_sale_header(
    *,
    sale,
    customer=None,
    cash_register=None,
    cash_session=None,
    requires_invoice=False,
    notes="",
):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    _assert_open(sale)
    sale.customer, sale.cash_register, sale.cash_session = (
        customer,
        cash_register,
        cash_session,
    )
    sale.requires_invoice, sale.notes = requires_invoice, notes
    sale.full_clean()
    sale.save()
    return sale


@transaction.atomic
def add_sale_line(
    *, sale, product, quantity, unit_price=None, discount_percent=Decimal("0")
):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    _assert_open(sale)
    if product.business_id != sale.business_id:
        raise ValidationError("El producto debe pertenecer al negocio.")
    price = product.base_price if unit_price is None else unit_price
    tax_rate = getattr(getattr(product, "tax", None), "rate", Decimal("0"))
    subtotal = _money(
        quantity * price * (Decimal("1") - discount_percent / Decimal("100"))
    )
    tax_total = _money(subtotal * tax_rate / Decimal("100"))
    line = SaleLine.objects.create(
        sale=sale,
        product=product,
        description=product.name,
        quantity=quantity,
        unit_price=price,
        discount_percent=discount_percent,
        tax_rate=tax_rate,
        subtotal=subtotal,
        tax_total=tax_total,
        total=subtotal + tax_total,
    )
    _recalculate_sale(sale)
    return line


@transaction.atomic
def update_sale_line(*, line, quantity, unit_price, discount_percent):
    sale = Sale.objects.select_for_update().get(pk=line.sale_id)
    _assert_open(sale)
    line = SaleLine.objects.select_for_update().get(pk=line.pk)
    subtotal = _money(
        quantity * unit_price * (Decimal("1") - discount_percent / Decimal("100"))
    )
    line.quantity, line.unit_price, line.discount_percent, line.subtotal = (
        quantity,
        unit_price,
        discount_percent,
        subtotal,
    )
    line.tax_total = _money(subtotal * line.tax_rate / Decimal("100"))
    line.total = line.subtotal + line.tax_total
    line.save()
    _recalculate_sale(sale)
    return line


@transaction.atomic
def delete_sale_line(*, line):
    sale = Sale.objects.select_for_update().get(pk=line.sale_id)
    _assert_open(sale)
    line.delete()
    _recalculate_sale(sale)


@transaction.atomic
def complete_sale(*, sale, user=None):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    _assert_open(sale)
    if not sale.lines.exists():
        raise ValidationError("No se puede completar una venta sin líneas.")
    sale.status, sale.completed_at = Sale.Status.COMPLETED, timezone.now()
    sale.save(update_fields=("status", "completed_at", "updated_at"))
    return sale


@transaction.atomic
def cancel_sale(*, sale, reason, user=None):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    _assert_open(sale)
    sale.status, sale.cancelled_at, sale.cancel_reason = (
        Sale.Status.CANCELLED,
        timezone.now(),
        reason,
    )
    sale.save(update_fields=("status", "cancelled_at", "cancel_reason", "updated_at"))
    return sale


@transaction.atomic
def create_sale_return(*, sale, user, reason):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.Status.COMPLETED:
        raise ValidationError("Solo se pueden devolver ventas completadas.")
    return SaleReturn.objects.create(
        business=sale.business,
        store=sale.store,
        sale=sale,
        created_by=user,
        reason=reason,
    )


@transaction.atomic
def add_sale_return_line(*, sale_return, sale_line, quantity):
    sale_return = SaleReturn.objects.select_for_update().get(pk=sale_return.pk)
    _assert_open(sale_return)
    if sale_line.sale_id != sale_return.sale_id or quantity > sale_line.quantity:
        raise ValidationError("La línea o cantidad de devolución no es válida.")
    line = SaleReturnLine.objects.create(
        sale_return=sale_return,
        sale_line=sale_line,
        quantity=quantity,
        total=_money(sale_line.total * quantity / sale_line.quantity),
    )
    SaleReturn.objects.filter(pk=sale_return.pk).update(
        total=sum((item.total for item in sale_return.lines.all()), Decimal("0"))
    )
    return line


@transaction.atomic
def update_sale_return_line(*, line, quantity):
    sale_return = SaleReturn.objects.select_for_update().get(pk=line.sale_return_id)
    _assert_open(sale_return)
    if quantity > line.sale_line.quantity:
        raise ValidationError("La cantidad supera la cantidad vendida.")
    line.quantity = quantity
    line.total = _money(line.sale_line.total * quantity / line.sale_line.quantity)
    line.save()
    return line


@transaction.atomic
def delete_sale_return_line(*, line):
    sale_return = SaleReturn.objects.select_for_update().get(pk=line.sale_return_id)
    _assert_open(sale_return)
    line.delete()


@transaction.atomic
def complete_sale_return(*, sale_return, user=None):
    sale_return = SaleReturn.objects.select_for_update().get(pk=sale_return.pk)
    _assert_open(sale_return)
    if not sale_return.lines.exists():
        raise ValidationError("No se puede completar una devolución sin líneas.")
    sale_return.status, sale_return.completed_at = (
        SaleReturn.Status.COMPLETED,
        timezone.now(),
    )
    sale_return.save(update_fields=("status", "completed_at", "updated_at"))
    return sale_return


@transaction.atomic
def cancel_sale_return(*, sale_return, reason, user=None):
    sale_return = SaleReturn.objects.select_for_update().get(pk=sale_return.pk)
    _assert_open(sale_return)
    sale_return.status, sale_return.cancelled_at, sale_return.cancel_reason = (
        SaleReturn.Status.CANCELLED,
        timezone.now(),
        reason,
    )
    sale_return.save(
        update_fields=("status", "cancelled_at", "cancel_reason", "updated_at")
    )
    return sale_return
