from decimal import Decimal

from django.db import transaction

from apps.business_config.models import BusinessProfile, POSSettings


BUSINESS_PROFILE_EDITABLE_FIELDS = (
    "legal_name",
    "tax_identifier",
    "trade_name",
    "phone",
    "email",
    "website",
    "address_line_1",
    "address_line_2",
    "postal_code",
    "city",
    "province",
    "country_code",
    "currency_code",
    "brand_name",
    "logo_url",
    "receipt_footer",
    "return_policy",
)

POS_SETTINGS_EDITABLE_FIELDS = (
    "prices_include_tax",
    "enable_stock_control",
    "allow_sale_without_stock",
    "allow_manual_price",
    "allow_manual_discounts",
    "max_manual_discount_percent",
    "require_open_cash_register",
    "allow_split_payments",
    "require_pin_for_sensitive_actions",
)


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


@transaction.atomic
def update_business_profile(*, business, **profile_data):
    """Update the editable profile fields for one explicitly supplied business."""
    for field_name in ("country_code", "tax_identifier"):
        if field_name in profile_data:
            profile_data[field_name] = profile_data[field_name].strip().upper()

    profile = (
        BusinessProfile.objects.select_for_update().filter(business=business).get()
    )

    for field_name in BUSINESS_PROFILE_EDITABLE_FIELDS:
        if field_name in profile_data:
            setattr(profile, field_name, profile_data[field_name])

    profile.save(update_fields=(*BUSINESS_PROFILE_EDITABLE_FIELDS, "updated_at"))
    return profile


@transaction.atomic
def update_pos_settings(*, business, **settings_data):
    """Update only editable POS settings for the explicitly supplied business."""
    settings = POSSettings.objects.select_for_update().get(business=business)

    for field_name in POS_SETTINGS_EDITABLE_FIELDS:
        if field_name in settings_data:
            setattr(settings, field_name, settings_data[field_name])

    settings.save(update_fields=(*POS_SETTINGS_EDITABLE_FIELDS, "updated_at"))
    return settings
