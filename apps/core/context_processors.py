"""Global, tenant-safe context for the authenticated application shell."""

from apps.core.navigation import build_shell_navigation
from apps.stores.selectors import get_stores_available_for_user
from apps.users.helpers import (
    can_manage_business_settings,
    can_manage_users,
    is_owner_or_manager,
)

ACTIVE_STORE_SESSION_KEY = "netxodo_active_store_id"


def _initials(user):
    parts = [part for part in (user.first_name, user.last_name) if part]
    if parts:
        return "".join(part[0] for part in parts[:2]).upper()
    return user.email[:2].upper()


def _display_name(user):
    return (
        " ".join(part for part in (user.first_name, user.last_name) if part)
        or user.email
    )


def resolve_active_store(request):
    """Resolve session state only against the user's current accessible stores."""

    user = request.user
    if not user.is_authenticated or (user.is_superuser and not user.business_id):
        request.session.pop(ACTIVE_STORE_SESSION_KEY, None)
        return [], None

    stores = list(get_stores_available_for_user(user=user, only_active=True))
    stored_id = request.session.get(ACTIVE_STORE_SESSION_KEY)
    active_store = next((store for store in stores if store.pk == stored_id), None)
    if active_store is None:
        active_store = next((store for store in stores if store.is_default), None)
        active_store = active_store or (stores[0] if stores else None)

    if active_store is None:
        request.session.pop(ACTIVE_STORE_SESSION_KEY, None)
    elif stored_id != active_store.pk:
        request.session[ACTIVE_STORE_SESSION_KEY] = active_store.pk
    return stores, active_store


def app_shell(request):
    if not request.user.is_authenticated:
        return {}

    stores, active_store = resolve_active_store(request)
    navigation, quick_actions = build_shell_navigation(
        request, active_store=active_store
    )
    user = request.user
    return {
        "shell_business": getattr(user, "business", None),
        "shell_stores": stores,
        "active_store": active_store,
        "shell_navigation": navigation,
        "shell_quick_actions": quick_actions,
        "shell_capabilities": {
            "can_manage_stores": is_owner_or_manager(user),
            "can_manage_users": can_manage_users(user),
            "can_manage_business": can_manage_business_settings(user),
            "can_sell": any(action["id"] == "new-sale" for action in quick_actions),
        },
        "shell_user_initials": _initials(user),
        "shell_user_name": _display_name(user),
    }
