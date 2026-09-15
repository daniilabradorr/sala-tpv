import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from apps.audit.exceptions import AuditPayloadError

REDACTED = "[REDACTED]"
MAX_DEPTH = 5
MAX_ITEMS = 50
MAX_STRING_LENGTH = 2000

_SECRET_MARKERS = {
    "password",
    "passwordhash",
    "rawpassword",
    "passwd",
    "token",
    "accesstoken",
    "refreshtoken",
    "apikey",
    "secret",
    "secretkey",
    "clientsecret",
    "credential",
    "credentials",
    "authorization",
    "authtoken",
    "bearertoken",
    "cookie",
    "clientcredentials",
    "privatekey",
    "sessionid",
    "signingkey",
    "csrftoken",
    "csrfmiddlewaretoken",
    "webhooksecret",
}
_SAFE_NON_SECRET_KEYS = {
    "cashsessionid",
}


def _normalized_key(key):
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _is_secret_key(key):
    normalized = _normalized_key(key)
    if normalized in _SAFE_NON_SECRET_KEYS:
        return False
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    words = {word.lower() for word in re.split(r"[^a-zA-Z0-9]+", words) if word}
    return (
        any(marker in normalized for marker in _SECRET_MARKERS)
        or "pin" in words
        or "pinhash" in normalized
    )


def sanitize_payload(payload):
    """Return a safe JSON-compatible copy, redacting known secret keys."""
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise AuditPayloadError("Audit payloads must be dictionaries or None.")
    return _sanitize(payload, depth=0)


def _sanitize(value, *, depth):
    if depth > MAX_DEPTH:
        raise AuditPayloadError(f"Audit payload exceeds maximum depth {MAX_DEPTH}.")

    if isinstance(value, Enum):
        return _sanitize(value.value, depth=depth)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise AuditPayloadError(
                f"Audit string exceeds maximum length {MAX_STRING_LENGTH}."
            )
        return value
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        if len(value) > MAX_ITEMS:
            raise AuditPayloadError(
                f"Audit object exceeds maximum item count {MAX_ITEMS}."
            )
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise AuditPayloadError("Audit object keys must be strings.")
            if _is_secret_key(key):
                result[key] = REDACTED
            else:
                result[key] = _sanitize(item, depth=depth + 1)
        return result

    if isinstance(value, (list, tuple, set)):
        if len(value) > MAX_ITEMS:
            raise AuditPayloadError(
                f"Audit list exceeds maximum item count {MAX_ITEMS}."
            )
        return [_sanitize(item, depth=depth + 1) for item in value]

    raise AuditPayloadError(
        f"Unsupported audit payload value type: {type(value).__name__}."
    )
