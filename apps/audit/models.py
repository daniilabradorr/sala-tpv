from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.audit.exceptions import AuditImmutableError
from apps.core.models import BusinessOwnedModel
from apps.core.querysets import BusinessScopedQuerySet


class AuditEventQuerySet(BusinessScopedQuerySet):
    def update(self, **kwargs):
        raise AuditImmutableError("Audit events are append-only.")

    def delete(self):
        raise AuditImmutableError("Audit events are append-only.")

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        if ignore_conflicts or update_conflicts:
            raise AuditImmutableError(
                "Audit bulk creation cannot ignore or update conflicting rows."
            )
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class AuditEventManager(models.Manager.from_queryset(AuditEventQuerySet)):
    def bulk_update(self, objs, fields, batch_size=None):
        raise AuditImmutableError("Audit events are append-only.")


class AuditEvent(BusinessOwnedModel):
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    event_type = models.CharField(max_length=100)
    module = models.CharField(max_length=50)
    entity_type = models.CharField(max_length=100, null=True, blank=True)
    entity_id = models.CharField(max_length=255, null=True, blank=True)
    message = models.TextField()
    old_payload = models.JSONField(null=True, blank=True)
    new_payload = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    objects = AuditEventManager()

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(entity_type__isnull=True, entity_id__isnull=True)
                    | (
                        Q(entity_type__isnull=False, entity_id__isnull=False)
                        & ~Q(entity_type="")
                        & ~Q(entity_id="")
                    )
                ),
                name="audit_entity_reference_pair",
            )
        ]
        indexes = [
            models.Index(
                fields=["business", "-created_at"], name="audit_biz_created_idx"
            ),
            models.Index(
                fields=["business", "module", "-created_at"],
                name="audit_biz_module_idx",
            ),
            models.Index(
                fields=["business", "event_type", "-created_at"],
                name="audit_biz_event_idx",
            ),
            models.Index(
                fields=["business", "store", "-created_at"],
                name="audit_biz_store_idx",
            ),
            models.Index(
                fields=["business", "user", "-created_at"],
                name="audit_biz_user_idx",
            ),
            models.Index(
                fields=["business", "entity_type", "entity_id", "created_at"],
                name="audit_biz_entity_idx",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        entity_type_missing = self.entity_type is None
        entity_id_missing = self.entity_id is None
        if entity_type_missing != entity_id_missing:
            errors["entity_type"] = (
                "Entity type and entity ID must be provided together."
            )
        elif not entity_type_missing and (
            not self.entity_type.strip() or not self.entity_id.strip()
        ):
            errors["entity_type"] = "Entity type and entity ID cannot be blank."
        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = "The store does not belong to the audit business."
        if self.user_id and self.business_id and not self.user.is_superuser:
            if self.user.business_id != self.business_id:
                errors["user"] = "The user does not belong to the audit business."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditImmutableError("Audit events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditImmutableError("Audit events are append-only.")

    def __str__(self):
        return f"{self.event_type} at {self.created_at:%Y-%m-%d %H:%M:%S}"
