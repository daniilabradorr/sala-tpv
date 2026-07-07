"""Factories de pruebas para el modulo inventory."""

from decimal import Decimal
from uuid import uuid4

from apps.catalog.models import Product
from apps.inventory.models import InventoryItem
from apps.stores.models import Store
from apps.users.models import RoleChoices
from apps.users.tests.factories import (
    create_business as create_users_business,
    create_user,
)


def create_business(name="Negocio Test", slug="negocio-test"):
    """Crea un negocio de pruebas reutilizando factories de users."""
    return create_users_business(name=name, slug=slug)


def create_inventory_store(
    *, business, name="Tienda Inventario", code=None, is_active=True
):
    if code is None:
        code = f"INV{uuid4().hex[:6].upper()}"

    return Store.objects.create(
        business=business,
        name=name,
        code=code,
        is_active=is_active,
    )


def create_inventory_product(
    *,
    business,
    name="Producto Inventario",
    base_price=Decimal("10.00"),
    is_active=True,
    is_service=False,
    track_stock=True,
):
    return Product.objects.create(
        business=business,
        name=name,
        base_price=base_price,
        is_active=is_active,
        is_service=is_service,
        track_stock=track_stock,
    )


def create_inventory_item(
    *,
    business,
    store,
    product,
    current_stock=Decimal("0.000"),
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


def create_inventory_owner(*, business, password="testpass123"):
    email = f"owner-{uuid4().hex[:8]}@inventory.test"
    return create_user(
        business=business,
        email=email,
        password=password,
        role=RoleChoices.OWNER,
    )


def create_inventory_cashier(*, business, password="testpass123"):
    email = f"cashier-{uuid4().hex[:8]}@inventory.test"
    return create_user(
        business=business,
        email=email,
        password=password,
        role=RoleChoices.CASHIER,
    )
