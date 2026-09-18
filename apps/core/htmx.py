"""Small, domain-free helpers for HTMX response contracts."""

import json


def _existing_events(header):
    """Normalize HTMX JSON-object and legacy comma-separated event headers."""
    if not header:
        return {}
    try:
        decoded = json.loads(header)
    except (json.JSONDecodeError, TypeError):
        decoded = header
    if isinstance(decoded, dict):
        return decoded
    if isinstance(decoded, list):
        names = [name for name in decoded if isinstance(name, str)]
    elif isinstance(decoded, str):
        names = decoded.split(",")
    else:
        names = []
    return {name.strip(): {} for name in names if name.strip()}


def add_hx_trigger(response, events):
    """Merge events, normalizing object or legacy event-name headers to JSON."""
    payload = _existing_events(response.get("HX-Trigger"))
    payload.update(events)
    response["HX-Trigger"] = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )
    return response
