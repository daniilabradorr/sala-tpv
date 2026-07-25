"""Selectors del módulo stores.

Regla:
- Aquí solo consultamos datos.
- No modificamos estados ni relaciones.
"""

from apps.stores.models import Store
from apps.users.models import UserStoreAccess


def _is_authenticated_active_user(user):
    return user is not None and user.is_authenticated and user.is_active


def get_store_for_business(*, business, store, for_update=False):
    """Devuelve una tienda concreta del negocio indicado.

    Si ``for_update`` es True, aplica bloqueo de fila para uso en servicios
    dentro de transacciones atómicas.
    """

    if business is None or not getattr(business, "pk", None):
        return None

    if store is None or not getattr(store, "pk", None):
        return None

    queryset = Store.objects.select_related("business")
    if for_update:
        queryset = queryset.select_for_update()

    return queryset.filter(
        pk=store.pk,
        business_id=business.pk,
    ).first()


def get_stores_for_business(*, business, for_update=False, only_active=None):
    """Devuelve tiendas del negocio para casos de uso de dominio."""

    if business is None or not getattr(business, "pk", None):
        return Store.objects.none()

    queryset = Store.objects.filter(
        business_id=business.pk,
    )

    if only_active is True:
        queryset = queryset.filter(is_active=True)
    elif only_active is False:
        queryset = queryset.filter(is_active=False)

    if for_update:
        queryset = queryset.select_for_update()

    return queryset.order_by("name", "pk")


def get_next_active_store_for_business(
    *, business, excluded_store=None, for_update=False
):
    """Devuelve una tienda activa candidata para reemplazo de predeterminada."""

    if business is None or not getattr(business, "pk", None):
        return None

    queryset = Store.objects.filter(
        business_id=business.pk,
        is_active=True,
    )

    if excluded_store is not None and getattr(excluded_store, "pk", None):
        queryset = queryset.exclude(pk=excluded_store.pk)

    if for_update:
        queryset = queryset.select_for_update()

    return queryset.order_by("name", "pk").first()


def get_default_store_for_business(
    *, business, for_update=False, only_active=False, excluded_store=None
):
    """Devuelve la tienda predeterminada del negocio o None."""

    if business is None or not getattr(business, "pk", None):
        return None

    queryset = Store.objects.filter(
        business_id=business.pk,
        is_default=True,
    )

    if only_active:
        queryset = queryset.filter(is_active=True)

    if excluded_store is not None and getattr(excluded_store, "pk", None):
        queryset = queryset.exclude(pk=excluded_store.pk)

    if for_update:
        queryset = queryset.select_for_update()

    return queryset.order_by("name", "pk").first()


def get_stores_available_for_user(*, user, only_active=True):
    """Devuelve las tiendas que puede usar un usuario.

    - Superuser: todas las tiendas.
    - Owner: todas las tiendas de su negocio.
    - Manager/Cashier: solo tiendas con UserStoreAccess activo.
    """

    if not _is_authenticated_active_user(user):
        return Store.objects.none()

    queryset = Store.objects.select_related("business")

    if user.is_superuser:
        if only_active:
            queryset = queryset.filter(is_active=True)

        return queryset.order_by("name", "pk")

    if not getattr(user, "business_id", None):
        return Store.objects.none()

    if user.role == "owner":
        queryset = queryset.filter(
            business_id=user.business_id,
        )
    else:
        queryset = queryset.filter(
            business_id=user.business_id,
            user_accesses__business_id=user.business_id,
            user_accesses__user_id=user.pk,
            user_accesses__is_active=True,
        )

    if only_active:
        queryset = queryset.filter(is_active=True)

    return queryset.distinct().order_by("-is_default", "name", "pk")


def get_default_store_for_user(*, user, only_active=True):
    """Devuelve la tienda predeterminada a la que el usuario puede acceder."""

    return (
        get_stores_available_for_user(
            user=user,
            only_active=only_active,
        )
        .filter(is_default=True)
        .first()
    )


def get_operational_store_for_user(*, user):
    """Devuelve la tienda operativa del usuario.

    Prioridad:
    1. Tienda predeterminada accesible.
    2. Primera tienda accesible (orden estable).
    """

    stores = get_stores_available_for_user(
        user=user,
        only_active=True,
    )

    default_store = stores.filter(is_default=True).first()
    if default_store is not None:
        return default_store

    return stores.first()


def get_store_access_for_user(*, user, store):
    """Devuelve el registro activo de acceso usuario-tienda o None."""

    if not _is_authenticated_active_user(user):
        return None

    if store is None or not getattr(store, "pk", None):
        return None

    if user.is_superuser:
        return None

    if user.role == "owner" and user.business_id == store.business_id:
        return None

    if user.business_id != store.business_id:
        return None

    return (
        UserStoreAccess.objects.select_related("business", "store", "user")
        .filter(
            business_id=user.business_id,
            user_id=user.pk,
            store_id=store.pk,
            is_active=True,
        )
        .first()
    )
