"""Factories reutilizables para los tests del módulo sales."""

from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from django.utils import timezone

from apps.business_config.models import POSSettings
from apps.catalog.models import Product, Tax
from apps.core.models import Business
from apps.customers.models import Customer
from apps.inventory.models import InventoryItem
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
from apps.stores.models import Store
from apps.users.models import RoleChoices, UserStoreAccess
from apps.users.tests.factories import create_user


MONEY_STEP = Decimal("0.01")


def _money(value):
    return Decimal(str(value)).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def create_sales_business(name="Negocio Sales", slug=None):
    if slug is None:
        slug = f"sales-{uuid4().hex[:10]}"

    return Business.objects.create(
        name=name,
        slug=slug,
        is_active=True,
    )


def create_sales_store(*, business, name="Tienda Sales", code=None, is_active=True):
    if code is None:
        code = f"SAL{uuid4().hex[:7].upper()}"

    return Store.objects.create(
        business=business,
        name=name,
        code=code,
        is_active=is_active,
    )


def create_sales_user(
    *,
    business,
    role=RoleChoices.OWNER,
    password="testpass123",
    email=None,
    pin=None,
):
    if email is None:
        email = f"{role}-{uuid4().hex[:10]}@sales.test"

    user = create_user(
        business=business,
        email=email,
        password=password,
        role=role,
    )

    if pin is not None:
        user.set_pin(pin)
        user.save(update_fields=["pin_hash", "updated_at"])

    return user


def create_store_access(
    *,
    business,
    user,
    store,
    can_sell=True,
    can_open_cash=False,
    can_close_cash=False,
    is_active=True,
):
    return UserStoreAccess.objects.create(
        business=business,
        user=user,
        store=store,
        can_sell=can_sell,
        can_open_cash=can_open_cash,
        can_close_cash=can_close_cash,
        is_active=is_active,
    )


def create_pos_settings(
    *,
    business,
    prices_include_tax=True,
    enable_stock_control=True,
    allow_sale_without_stock=False,
    allow_manual_price=True,
    allow_manual_discounts=True,
    max_manual_discount_percent=Decimal("20.00"),
    require_open_cash_register=False,
    allow_split_payments=True,
    require_pin_for_sensitive_actions=False,
):
    settings, _created = POSSettings.objects.update_or_create(
        business=business,
        defaults={
            "prices_include_tax": prices_include_tax,
            "enable_stock_control": enable_stock_control,
            "allow_sale_without_stock": allow_sale_without_stock,
            "allow_manual_price": allow_manual_price,
            "allow_manual_discounts": allow_manual_discounts,
            "max_manual_discount_percent": max_manual_discount_percent,
            "require_open_cash_register": require_open_cash_register,
            "allow_split_payments": allow_split_payments,
            "require_pin_for_sensitive_actions": require_pin_for_sensitive_actions,
        },
    )
    return settings


def create_sales_tax(
    *,
    business,
    name="IVA 21%",
    code=None,
    rate=Decimal("21.00"),
    is_default=True,
    is_active=True,
    tax_type=Tax.TAX_TYPE_IVA,
    clave_regimen="01",
    calificacion_operacion="S1",
    operacion_exenta=None,
    has_equivalence_surcharge=False,
    equivalence_surcharge_rate=None,
):
    if code is None:
        code = f"IVA_{str(rate).replace('.', '_')}_{uuid4().hex[:6].upper()}"

    if is_default:
        Tax.objects.filter(business=business, is_default=True).update(is_default=False)

    return Tax.objects.create(
        business=business,
        name=name,
        code=code,
        tax_type=tax_type,
        rate=rate,
        clave_regimen=clave_regimen,
        calificacion_operacion=calificacion_operacion,
        operacion_exenta=operacion_exenta,
        has_equivalence_surcharge=has_equivalence_surcharge,
        equivalence_surcharge_rate=equivalence_surcharge_rate,
        is_default=is_default,
        is_active=is_active,
    )


def create_sales_product(
    *,
    business,
    tax=None,
    name="Producto Sales",
    sku=None,
    barcode=None,
    base_price=Decimal("10.00"),
    cost_price=Decimal("4.00"),
    unit=Product.UNIT_UNIDAD,
    track_stock=True,
    is_service=False,
    is_active=True,
):
    if sku is None:
        sku = f"SKU_{uuid4().hex[:10].upper()}"

    if barcode is None and not is_service:
        barcode = f"9{uuid4().int % 10**12:012d}"

    return Product.objects.create(
        business=business,
        tax=tax,
        name=name,
        sku=sku,
        barcode=barcode,
        base_price=base_price,
        cost_price=cost_price,
        unit=unit,
        track_stock=track_stock,
        is_service=is_service,
        is_active=is_active,
    )


def create_sales_customer(
    *,
    business,
    name="Cliente Sales",
    legal_name="",
    tax_identifier="",
    country_code="ES",
    foreign_id_type="",
    foreign_id="",
    is_active=True,
):
    return Customer.objects.create(
        business=business,
        name=name,
        legal_name=legal_name,
        tax_identifier=tax_identifier,
        country_code=country_code,
        foreign_id_type=foreign_id_type,
        foreign_id=foreign_id,
        is_active=is_active,
    )


def create_sales_inventory_item(
    *,
    business,
    store,
    product,
    current_stock=Decimal("20.000"),
    reserved_stock=Decimal("0.000"),
    minimum_stock=Decimal("0.000"),
    is_active=True,
):
    return InventoryItem.objects.create(
        business=business,
        store=store,
        product=product,
        current_stock=current_stock,
        reserved_stock=reserved_stock,
        minimum_stock=minimum_stock,
        is_active=is_active,
    )


def create_sale(
    *,
    business,
    store,
    opened_by,
    customer=None,
    status=SaleStatusChoices.OPEN,
    document_type_requested=RequestedDocumentTypeChoices.TICKET,
    payment_status=PaymentStatusChoices.UNPAID,
    subtotal_amount=Decimal("0.00"),
    discount_amount=Decimal("0.00"),
    tax_amount=Decimal("0.00"),
    total_amount=Decimal("0.00"),
    pending_amount=None,
    closed_by=None,
    completed_at=None,
    cash_register=None,
    cash_session=None,
):
    if pending_amount is None:
        pending_amount = total_amount

    if status == SaleStatusChoices.COMPLETED:
        closed_by = closed_by or opened_by
        completed_at = completed_at or timezone.now()

    return Sale.objects.create(
        business=business,
        store=store,
        cash_register=cash_register,
        cash_session=cash_session,
        customer=customer,
        opened_by=opened_by,
        closed_by=closed_by,
        status=status,
        document_type_requested=document_type_requested,
        payment_status=payment_status,
        subtotal_amount=subtotal_amount,
        discount_amount=discount_amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
        pending_amount=pending_amount,
        completed_at=completed_at,
    )


def create_sale_line(
    *,
    business,
    sale,
    product,
    quantity=Decimal("1.000"),
    unit_base_price=None,
    discount_amount=Decimal("0.00"),
    tax_rate=None,
):
    if unit_base_price is None:
        unit_base_price = product.base_price

    if tax_rate is None:
        tax_rate = product.tax.rate if product.tax_id else Decimal("21.00")

    gross = _money(Decimal(str(unit_base_price)) * Decimal(str(quantity)))
    taxable = _money(gross - Decimal(str(discount_amount)))
    tax_amount = _money(taxable * Decimal(str(tax_rate)) / Decimal("100.00"))
    line_total = _money(taxable + tax_amount)

    line = SaleLine.objects.create(
        business=business,
        sale=sale,
        product=product,
        product_name=product.name,
        sku=product.sku or "",
        quantity=quantity,
        unit=product.unit,
        unit_base_price=unit_base_price,
        discount_amount=discount_amount,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        line_total=line_total,
    )

    subtotal = _money(
        sum(
            (_money(item.unit_base_price * item.quantity) for item in sale.lines.all()),
            Decimal("0.00"),
        )
    )
    discounts = _money(
        sum((item.discount_amount for item in sale.lines.all()), Decimal("0.00"))
    )
    taxes = _money(sum((item.tax_amount for item in sale.lines.all()), Decimal("0.00")))
    total = _money(subtotal - discounts + taxes)

    Sale.objects.filter(pk=sale.pk).update(
        subtotal_amount=subtotal,
        discount_amount=discounts,
        tax_amount=taxes,
        total_amount=total,
        pending_amount=total,
    )
    sale.refresh_from_db()

    return line


def create_sale_return(
    *,
    business,
    store,
    original_sale,
    created_by,
    reason="Producto devuelto",
    status=SaleReturnStatusChoices.DRAFT,
    total_amount=Decimal("0.00"),
):
    return SaleReturn.objects.create(
        business=business,
        store=store,
        original_sale=original_sale,
        created_by=created_by,
        reason=reason,
        status=status,
        total_amount=total_amount,
    )


def create_sale_return_line(
    *,
    business,
    return_doc,
    original_line,
    quantity=Decimal("1.000"),
    amount=None,
    restock=True,
):
    if amount is None:
        amount = _money(
            original_line.line_total * Decimal(str(quantity)) / original_line.quantity
        )

    line = SaleReturnLine.objects.create(
        business=business,
        return_doc=return_doc,
        original_line=original_line,
        quantity=quantity,
        amount=amount,
        restock=restock,
    )

    total = _money(
        sum((item.amount for item in return_doc.lines.all()), Decimal("0.00"))
    )
    SaleReturn.objects.filter(pk=return_doc.pk).update(total_amount=total)
    return_doc.refresh_from_db()

    return line
