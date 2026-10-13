"""Exact, ungrouped quantity presentation shared by Sales and print."""

from decimal import Decimal, InvalidOperation

from django.utils.formats import get_format


def quantity_input(value):
    """Return an HTML decimal string, trimming only redundant trailing zeros."""
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    if not amount.is_finite():
        return ""
    rendered = format(amount, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if amount == 0 else rendered


def quantity(value):
    """Localize the decimal separator without rounding or losing precision."""
    return quantity_input(value).replace(".", get_format("DECIMAL_SEPARATOR"))
