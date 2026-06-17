from apps.core.models import Business
from apps.stores.models import Stores
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


def create_business(name="Negocio Test", slug="negocio-test"):
    return Business.objects.create(
        name=name,
        slug=slug,
        is_active=True,
    )


def create_store(
    business,
    name="Tienda Test",
    code="TST",
    is_active=True,
):
    return Stores.objects.create(
        business=business,
        name=name,
        code=code,
        is_active=is_active,
    )


def create_user(
    business,
    email="user@test.com",
    password="testpass123",
    role=RoleChoices.CASHIER,
    first_name="Test",
    last_name="User",
    phone="600123123",
    **extra_fields,
):
    return CustomUser.objects.create_user(
        email=email,
        password=password,
        business=business,
        role=role,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        **extra_fields,
    )


def create_store_access(
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
