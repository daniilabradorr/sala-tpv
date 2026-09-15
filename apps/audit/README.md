# Audit

`audit` stores append-only business events for investigation and traceability. It
is not an HTTP request log and is not an event-sourcing source of truth.

Domain services must call `apps.audit.services.log_event()` explicitly inside the
same transaction as the mutation. The helper validates the event/module mapping,
tenant relationships and optional entity reference, and recursively sanitizes
small JSON payloads. Signals, request globals and `transaction.on_commit()` are
not used.

Application reads must use `get_audit_events(business=...)` or the
`AuditEvent.objects.for_business(...)` manager scope. Audit records cannot be
updated or deleted through the model, queryset, manager or admin. `Business`,
`Store` and `User` references are protected; a null user denotes a system event.
Conflict-ignoring and upsert variants of `bulk_create()` are rejected as they can
silently lose or overwrite history.

Never pass model dictionaries, form data or request payloads wholesale. Build an
explicit allowlist containing only the relevant change and never include
passwords, PINs, tokens, API keys, credentials or other secrets.
