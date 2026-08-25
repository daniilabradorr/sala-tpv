from uuid import uuid4

from apps.cash_register.models import CashRegister
from apps.core.models import Business
from apps.stores.models import Store


def create_cash_business(name="Negocio Cash Register", slug=None):
    if slug is None:
        slug = f"cash-{uuid4().hex[:10]}"

    return Business.objects.create(
        name=name,
        slug=slug,
        is_active=True,
    )


def create_cash_store(*, business, name=None, code=None, is_active=True):
    if name is None:
        name = f"Tienda {uuid4().hex[:8]}"
    if code is None:
        code = f"CASH{uuid4().hex[:7].upper()}"

    return Store.objects.create(
        business=business,
        name=name,
        code=code,
        is_active=is_active,
    )


def create_cash_register(
    *,
    business,
    store,
    name="Caja principal",
    code="CAJA-01",
    is_active=True,
):
    return CashRegister.objects.create(
        business=business,
        store=store,
        name=name,
        code=code,
        is_active=is_active,
    )
