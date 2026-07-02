from decimal import Decimal

from apps.catalog.models import Category, Tax, Product
from apps.users.tests.factories import create_business


def create_category(
    business=None,
    name="Bebidas",
    slug="bebidas",
    parent=None,
    sort_order=0,
    is_active=True,
):
    if business is None:
        business = create_business()

    return Category.objects.create(
        business=business,
        name=name,
        slug=slug,
        parent=parent,
        sort_order=sort_order,
        is_active=is_active,
    )


def create_tax(
    business=None,
    name="IVA 21%",
    code="IVA_21",
    tax_type=Tax.TAX_TYPE_IVA,
    rate=Decimal("21.00"),
    clave_regimen="01",
    calificacion_operacion="S1",
    operacion_exenta=None,
    has_equivalence_surcharge=False,
    equivalence_surcharge_rate=None,
    is_default=False,
    is_active=True,
):
    if business is None:
        business = create_business()

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


def create_product(
    business=None,
    category=None,
    tax=None,
    name="Coca-Cola 500ml",
    sku="COCA_500",
    barcode="PRD000001",
    base_price=Decimal("2.00"),
    cost_price=Decimal("1.00"),
    unit=Product.UNIT_UNIDAD,
    sort_order=0,
    track_stock=True,
    is_service=False,
    is_active=True,
):
    if business is None:
        business = create_business()

    return Product.objects.create(
        business=business,
        category=category,
        tax=tax,
        name=name,
        sku=sku,
        barcode=barcode,
        base_price=base_price,
        cost_price=cost_price,
        unit=unit,
        sort_order=sort_order,
        track_stock=track_stock,
        is_service=is_service,
        is_active=is_active,
    )
