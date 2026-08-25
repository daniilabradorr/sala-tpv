from apps.cash_register.models import CashRegister
from apps.core.models import Business
from apps.stores.models import Store


def business_exists(
    business: Business | None,
) -> bool:
    """
    Comprueba que el Business exista y esté activo.
    """
    if business is None or not business.pk:
        return False

    return Business.objects.filter(
        pk=business.pk,
        is_active=True,
    ).exists()


def cash_register_pertenece_business_store(
    business: Business | None,
    store_id: int | None,
    cash_register_id: int | None,
) -> bool:
    """
    Comprueba que la caja pertenezca exactamente
    al Business y Store indicados.
    """
    if (
        business is None
        or not business.pk
        or not store_id
        or not cash_register_id
    ):
        return False

    return CashRegister.objects.filter(
        pk=cash_register_id,
        business=business,
        store_id=store_id,
    ).exists()


def verify_cash_register_and_store_active(
    business: Business | None,
    store_id: int | None,
    cash_register_id: int | None,
) -> bool:
    """
    Comprueba conjuntamente que:

    - la Store pertenece al Business;
    - la Store está activa;
    - la CashRegister pertenece a esa Store;
    - la CashRegister pertenece a ese Business;
    - la CashRegister está activa.
    """
    if (
        business is None
        or not business.pk
        or not store_id
        or not cash_register_id
    ):
        return False

    return CashRegister.objects.filter(
        pk=cash_register_id,
        business=business,
        store_id=store_id,
        is_active=True,
        store__is_active=True,
    ).exists()