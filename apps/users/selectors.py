from django.db.models import Prefetch, Q

from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


def get_users_for_admin(*, business, q="", role="", status="active", store=None):
    """Return the tenant-scoped, presentation-ready administrative user list."""
    accesses = (
        UserStoreAccess.objects.filter(is_active=True)
        .select_related("store")
        .order_by("store__name")
    )
    users = (
        CustomUser.objects.filter(business=business)
        .select_related("business")
        .prefetch_related(
            Prefetch(
                "store_accesses", queryset=accesses, to_attr="active_store_accesses"
            )
        )
    )
    if q:
        users = users.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
        )
    if role in RoleChoices.values:
        users = users.filter(role=role)
    if status == "active":
        users = users.filter(is_active=True)
    elif status == "inactive":
        users = users.filter(is_active=False)
    if store is not None:
        users = users.filter(
            Q(role=RoleChoices.OWNER)
            | Q(store_accesses__store=store, store_accesses__is_active=True)
        )
    return users.distinct().order_by("first_name", "last_name", "email")


def get_user_for_admin(*, business, pk):
    return get_users_for_admin(business=business, status="all").get(pk=pk)
