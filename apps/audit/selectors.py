from django.db.models import Q

from apps.audit.models import AuditEvent


def get_audit_events(
    *,
    business,
    stores=None,
    store=None,
    user=None,
    module=None,
    event_type=None,
    period=None,
    query=None,
):
    """Return read-only audit history scoped and filtered before evaluation.

    ``stores`` is an authorization boundary (including an empty iterable), while
    ``store`` is an optional user-selected filter inside that boundary.
    """
    queryset = AuditEvent.objects.for_business(business).select_related(
        "business", "store", "user"
    )
    if stores is not None:
        queryset = queryset.filter(store__in=stores)
    if store is not None:
        queryset = queryset.filter(store=store)
    if user == "system":
        queryset = queryset.filter(user__isnull=True)
    elif user is not None:
        queryset = queryset.filter(user=user)
    if module:
        queryset = queryset.filter(module=module)
    if event_type:
        queryset = queryset.filter(event_type=event_type)
    if period is not None:
        queryset = queryset.filter(
            created_at__gte=period.start, created_at__lt=period.end
        )
    if query:
        queryset = queryset.filter(
            Q(message__icontains=query)
            | Q(event_type__icontains=query)
            | Q(entity_type__icontains=query)
            | Q(entity_id__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query)
        )
    return queryset
