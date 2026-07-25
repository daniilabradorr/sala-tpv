from apps.users.models import RoleChoices, UserStoreAccess


def is_authenticated_user(user):
    """Comprueba que exista un usuario autenticado y activo."""

    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
    )


def is_owner(user):
    """Indica si el usuario activo tiene rol owner."""

    return is_authenticated_user(user) and user.role == RoleChoices.OWNER


def is_manager(user):
    """Indica si el usuario activo tiene rol manager."""

    return is_authenticated_user(user) and user.role == RoleChoices.MANAGER


def is_cashier(user):
    """Indica si el usuario activo tiene rol cashier."""

    return is_authenticated_user(user) and user.role == RoleChoices.CASHIER


def is_owner_or_manager(user):
    """Indica si el usuario es owner o manager."""

    return is_owner(user) or is_manager(user)


def belongs_to_business(user, business):
    """Comprueba si el usuario pertenece al negocio indicado."""

    if not is_authenticated_user(user):
        return False

    if business is None or not getattr(business, "pk", None):
        return False

    if user.is_superuser:
        return True

    return user.business_id == business.pk


def can_access_store(user, store):
    """Comprueba si el usuario puede consultar una tienda concreta.

    Una tienda inactiva puede seguir consultándose para ver detalle,
    administrarla o reactivarla.
    """

    if not is_authenticated_user(user):
        return False

    if store is None or not getattr(store, "pk", None):
        return False

    if user.is_superuser:
        return True

    if not user.business_id or user.business_id != store.business_id:
        return False

    if is_owner(user):
        return True

    return UserStoreAccess.objects.filter(
        business_id=user.business_id,
        user=user,
        store=store,
        is_active=True,
    ).exists()


def can_sell_in_store(user, store):
    """Comprueba si el usuario puede vender en una tienda activa."""

    if not can_access_store(user, store):
        return False

    if not store.is_active:
        return False

    if user.is_superuser:
        return True

    if is_owner(user):
        return True

    return UserStoreAccess.objects.filter(
        business_id=user.business_id,
        user=user,
        store=store,
        can_sell=True,
        is_active=True,
    ).exists()


def can_open_cash_register(user, store):
    """Comprueba si el usuario puede abrir caja en una tienda activa."""

    if not can_access_store(user, store):
        return False

    if not store.is_active:
        return False

    if user.is_superuser:
        return True

    if is_owner(user):
        return True

    return UserStoreAccess.objects.filter(
        business_id=user.business_id,
        user=user,
        store=store,
        can_open_cash=True,
        is_active=True,
    ).exists()


def can_close_cash_register(user, store):
    """Comprueba si el usuario puede cerrar caja en una tienda activa."""

    if not can_access_store(user, store):
        return False

    if not store.is_active:
        return False

    if user.is_superuser:
        return True

    if is_owner(user):
        return True

    return UserStoreAccess.objects.filter(
        business_id=user.business_id,
        user=user,
        store=store,
        can_close_cash=True,
        is_active=True,
    ).exists()


def can_manage_users(user):
    """Owner y manager pueden gestionar usuarios."""

    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    return is_owner(user) or is_manager(user)


def can_manage_business_settings(user):
    """Solo owner puede modificar la configuración del negocio."""

    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    return is_owner(user)


def can_view_reports(user):
    """Owner y manager pueden consultar reportes."""

    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    return is_owner(user) or is_manager(user)


def can_perform_sensitive_action(user):
    """Permiso base para acciones sensibles."""

    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    return is_owner(user) or is_manager(user)
