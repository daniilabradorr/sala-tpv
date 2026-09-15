from django.core.exceptions import ValidationError
from django.db.models import Model

from apps.audit.constants import EVENT_MODULES
from apps.audit.exceptions import AuditValidationError
from apps.audit.models import AuditEvent
from apps.audit.sanitizers import sanitize_payload
from apps.core.models import Business


def log_event(
    *,
    business,
    event_type,
    module,
    message,
    store=None,
    user=None,
    entity=None,
    entity_type=None,
    entity_id=None,
    old_payload=None,
    new_payload=None,
    metadata=None,
    ip_address=None,
):
    """Persist one explicit business event in the caller's transaction."""
    expected_module = EVENT_MODULES.get(event_type)
    if expected_module is None:
        raise AuditValidationError(f"Unknown audit event type: {event_type!r}.")
    if module != expected_module:
        raise AuditValidationError(
            f"Event {event_type!r} belongs to module {expected_module!r}, not {module!r}."
        )
    if not isinstance(message, str) or not message.strip():
        raise AuditValidationError("Audit event message must be a non-blank string.")
    if not isinstance(business, Business) or business.pk is None:
        raise AuditValidationError("A persisted business is required.")
    if entity is not None and (entity_type is not None or entity_id is not None):
        raise AuditValidationError(
            "Provide either entity or entity_type/entity_id, not both."
        )
    if entity is not None:
        if not isinstance(entity, Model) or entity.pk is None:
            raise AuditValidationError("Entity must be a persisted Django model.")
        if isinstance(entity, Business):
            entity_business_id = entity.pk
        else:
            entity_business_id = getattr(entity, "business_id", None)
        if entity_business_id is not None and entity_business_id != business.pk:
            raise AuditValidationError("Entity does not belong to the audit business.")
        entity_type = entity._meta.label_lower
        entity_id = str(entity.pk)
    elif (entity_type is None) != (entity_id is None):
        raise AuditValidationError(
            "Entity type and entity ID must be provided together."
        )
    elif entity_type is not None:
        entity_type = str(entity_type).strip()
        entity_id = str(entity_id).strip()
        if not entity_type or not entity_id:
            raise AuditValidationError(
                "Entity type and entity ID must be non-blank values."
            )

    event = AuditEvent(
        business=business,
        store=store,
        user=user,
        event_type=event_type,
        module=module,
        entity_type=entity_type,
        entity_id=entity_id,
        message=message,
        old_payload=sanitize_payload(old_payload),
        new_payload=sanitize_payload(new_payload),
        metadata=sanitize_payload(metadata),
        ip_address=ip_address,
    )
    try:
        event.full_clean()
    except ValidationError as exc:
        raise AuditValidationError(str(exc)) from exc
    event.save()
    return event
