"""Tenant-safe Store resolution for the authenticated application shell."""

from apps.stores.selectors import (
    get_stores_available_for_user,
    get_stores_for_business,
)

ACTIVE_STORE_SESSION_KEY = "netxodo_active_store_id"


def get_shell_stores_for_user(user):
    """Return active Stores that may be used as this user's shell context."""

    if user.is_superuser:
        if not user.business_id:
            return []
        return list(
            get_stores_for_business(
                business=user.business,
                only_active=True,
            )
        )
    return list(get_stores_available_for_user(user=user, only_active=True))


def resolve_active_store(request, *, user):
    """Resolve URL/session state only within the shell-authorized Store set."""

    stores = get_shell_stores_for_user(user)
    stores_by_id = {store.pk: store for store in stores}
    route_store_id = getattr(
        getattr(request, "resolver_match", None), "kwargs", {}
    ).get("store_id")
    stored_id = request.session.get(ACTIVE_STORE_SESSION_KEY)
    route_store = stores_by_id.get(route_store_id)
    stored_store = stores_by_id.get(stored_id)
    active_store = route_store or stored_store
    if active_store is None:
        active_store = next((store for store in stores if store.is_default), None)
        active_store = active_store or (stores[0] if stores else None)

    if active_store is None:
        request.session.pop(ACTIVE_STORE_SESSION_KEY, None)
    elif stored_id != active_store.pk:
        request.session[ACTIVE_STORE_SESSION_KEY] = active_store.pk
    return stores, active_store
