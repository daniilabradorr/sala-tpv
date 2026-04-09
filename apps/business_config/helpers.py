from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ObjectDoesNotExist

TWOPLACES = Decimal("0.01")
ONE_HUNDRED = Decimal("100")


def normalize_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_money(value) -> Decimal:
    return normalize_decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def resolve_tax_rate(explicit_tax_rate, default_tax_rate):
    if explicit_tax_rate is not None:
        return normalize_decimal(explicit_tax_rate)

    if default_tax_rate is not None:
        return normalize_decimal(default_tax_rate)

    return None


def get_business_default_tax_rate(business):
    try:
        return business.profile.default_tax_rate
    except ObjectDoesNotExist:
        return None


def calculate_final_price(base_price, tax_rate):
    base_price = normalize_decimal(base_price)

    if tax_rate is None:
        return quantize_money(base_price)

    tax_rate = normalize_decimal(tax_rate)
    final_price = base_price + (base_price * tax_rate / ONE_HUNDRED)
    return quantize_money(final_price)


def get_display_price(base_price, tax_rate, prices_include_tax):
    base_price = quantize_money(base_price)
    final_price = calculate_final_price(base_price, tax_rate)

    return final_price if prices_include_tax else base_price
