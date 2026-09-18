"""Small, domain-free helpers for HTMX response contracts."""

import json


def add_hx_trigger(response, events):
    """Merge *events* into the JSON ``HX-Trigger`` response header."""
    existing = response.get("HX-Trigger")
    payload = json.loads(existing) if existing else {}
    if not isinstance(payload, dict):
        payload = {}
    payload.update(events)
    response["HX-Trigger"] = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )
    return response
