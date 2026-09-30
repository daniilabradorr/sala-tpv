class AuditError(Exception):
    """Base exception for the audit boundary."""


class AuditValidationError(AuditError, ValueError):
    """The caller supplied an invalid audit event."""


class AuditPayloadError(AuditValidationError):
    """A payload cannot be safely represented in audit JSON."""


class AuditImmutableError(AuditError):
    """An existing audit event cannot be mutated or deleted."""
