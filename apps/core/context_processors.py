"""Global, tenant-safe context for the authenticated application shell."""

from apps.core.navigation import build_shell_navigation
from apps.core.shell import resolve_active_store
from apps.users.helpers import (
    can_manage_business_settings,
    can_manage_users,
    is_owner_or_manager,
)


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


def app_shell(request):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {}

    stores, active_store = resolve_active_store(request, user=user)
    navigation, quick_actions = build_shell_navigation(
        request, active_store=active_store
    )
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
