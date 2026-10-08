"""Presentation helpers for persisted fiscal snapshots."""

from decimal import Decimal, InvalidOperation

from django import template
from django.utils.formats import get_format

register = template.Library()


@register.filter
def quantity(value):
    """Localize a Decimal without rounding, grouping or redundant trailing zeros."""
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    if not amount.is_finite():
        return ""
    rendered = format(amount, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if amount == 0:
        rendered = "0"
    return rendered.replace(".", get_format("DECIMAL_SEPARATOR"))
