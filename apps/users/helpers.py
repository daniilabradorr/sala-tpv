from apps.users.models import UserStoreAccess


def is_authenticated_user(user):
    return user is not None and user.is_authenticated and user.is_active


def is_owner(user):
    return is_authenticated_user(user) and user.role == "owner"


def is_manager(user):
    return is_authenticated_user(user) and user.role == "manager"


def is_cashier(user):
    return is_authenticated_user(user) and user.role == "cashier"


def is_owner_or_manager(user):
    return is_owner(user) or is_manager(user)


def belongs_to_business(user, business):
    """
    Comprueba si el usuario pertenece al negocio indicado.
    """
    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    return user.business_id == business.id


def can_access_store(user, store):
    """
    Comprueba si el usuario puede acceder a una tienda concreta.
    """

    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    # Seguridad multiempresa:
    # un usuario nunca debería acceder a tiendas de otro negocio.
    if user.business_id != store.business_id:
        return False

    # El owner puede acceder a todas las tiendas de su negocio.
    if is_owner(user) and (user.business_id == store.business_id):
        return True

    # Manager y cashier necesitan un UserStoreAccess activo.
    return UserStoreAccess.objects.filter(
        business=user.business,
        user=user,
        store=store,
        is_active=True,
    ).exists()


def can_sell_in_store(user, store):
    """
    Comprueba si el usuario puede vender en una tienda.
    """

    if not can_access_store(user, store):
        return False

    if user.is_superuser:
        return True

    if is_owner(user) and (user.business_id == store.business_id):
        return True

    return UserStoreAccess.objects.filter(
        business=user.business,
        user=user,
        store=store,
        can_sell=True,
        is_active=True,
    ).exists()


def can_open_cash_register(user, store):
    """
    Comprueba si el usuario puede abrir caja en una tienda.
    """

    if not can_access_store(user, store):
        return False

    if user.is_superuser:
        return True

    if is_owner(user) and (user.business_id == store.business_id):
        return True

    return UserStoreAccess.objects.filter(
        business=user.business,
        user=user,
        store=store,
        can_open_cash=True,
        is_active=True,
    ).exists()


def can_close_cash_register(user, store):
    """
    Comprueba si el usuario puede cerrar caja en una tienda.
    """

    if not can_access_store(user, store):
        return False

    if user.is_superuser:
        return True

    if is_owner(user) and (user.business_id == store.business_id):
        return True

    return UserStoreAccess.objects.filter(
        business=user.business,
        user=user,
        store=store,
        can_close_cash=True,
        is_active=True,
    ).exists()


def can_manage_users(user):
    """
    Permiso para gestionar usuarios internos del negocio.
    Normalmente owner y manager.
    """

    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    return is_owner(user) or is_manager(user)


def can_manage_business_settings(user):
    """
    Permiso para tocar configuración general del negocio.
    Mejor limitarlo a owner.
    """

    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    return is_owner(user)


def can_view_reports(user):
    """
    Permiso para ver reportes.
    Normalmente owner y manager.
    """

    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    return is_owner(user) or is_manager(user)


def can_perform_sensitive_action(user):
    """
    Permiso base para acciones sensibles.
    El PIN se validará aparte.
    """

    if not is_authenticated_user(user):
        return False

    if user.is_superuser:
        return True

    return is_owner(user) or is_manager(user)
