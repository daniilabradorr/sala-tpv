from apps.stores.models import Store
from apps.stores.selectors import get_stores_available_for_user


def get_home_operational_stores(*, user):
    """Return active stores that may be used from the tenant Home."""

    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
        or not getattr(user, "business_id", None)
    ):
        return Store.objects.none()

    if user.is_superuser:
        return (
            Store.objects.select_related("business")
            .filter(business_id=user.business_id, is_active=True)
            .order_by("-is_default", "name", "pk")
        )

    return get_stores_available_for_user(user=user, only_active=True)
