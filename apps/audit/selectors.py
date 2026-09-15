from apps.audit.models import AuditEvent


def get_audit_events(*, business):
    """Return audit history explicitly scoped to one business."""
    return AuditEvent.objects.for_business(business).select_related(
        "business", "store", "user"
    )
