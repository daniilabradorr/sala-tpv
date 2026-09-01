from decimal import Decimal

from django.db import transaction

from apps.business_config.models import BusinessProfile, POSSettings


@transaction.atomic
def create_business_configuration(
    *,
    business,
    legal_name,
    tax_identifier,
    phone,
    email,
    address_line_1,
    postal_code,
    city,
    province,
    trade_name="",
    address_line_2="",
    country_code="ES",
    currency_code="EUR",
    brand_name="",
    website="",
    logo_url="",
    receipt_footer="",
    return_policy="",
):
    """Create the configuration supplied during an explicit business setup.

    Model validation rejects a second configuration for the same business
    rather than silently returning existing records.
    """
    profile = BusinessProfile.objects.create(
        business=business,
        legal_name=legal_name,
        tax_identifier=tax_identifier,
        trade_name=trade_name,
        phone=phone,
        email=email,
        website=website,
        address_line_1=address_line_1,
        address_line_2=address_line_2,
        postal_code=postal_code,
        city=city,
        province=province,
        country_code=country_code,
        currency_code=currency_code,
        brand_name=brand_name,
        logo_url=logo_url,
        receipt_footer=receipt_footer,
        return_policy=return_policy,
    )

    settings = POSSettings.objects.create(
        business=business,
        prices_include_tax=True,
        enable_stock_control=True,
        allow_sale_without_stock=False,
        allow_manual_price=True,
        allow_manual_discounts=True,
        max_manual_discount_percent=Decimal("20.00"),
        require_open_cash_register=True,
        allow_split_payments=True,
        require_pin_for_sensitive_actions=True,
    )
    return profile, settings
