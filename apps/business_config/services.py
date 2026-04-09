from decimal import Decimal
import logging

from django.db import transaction

from apps.business_config.models import BusinessProfile, POSSettings

logger = logging.getLogger(__name__)


@transaction.atomic
def bootstrap_business_configuration(business):
    profile, profile_created = BusinessProfile.objects.get_or_create(
        business=business,
        defaults={
            "legal_name": business.name,
            "trade_name": business.name,
            "brand_name": business.name,
            "country_code": "ES",  # España
            "currency_code": "EUR",  # Euro
            "receipt_footer": "Gracias por su visita.",
            "return_policy": "",
            "default_tax_rate": Decimal("21.00"),
        },
    )

    settings, settings_created = POSSettings.objects.get_or_create(
        business=business,
        defaults={
            "prices_include_tax": True,
            "allow_sale_without_stock": False,
            "allow_manual_price": True,
            "allow_manual_discounts": True,
            "max_manual_discount_percent": Decimal("20.00"),
            "require_open_cash_register": True,
            "allow_split_payments": True,
            "require_pin_for_sensitive_actions": False,
        },
    )

    logger.info(
        (
            "Bootstrap de configuración para business_id=%s "
            "(profile_created=%s, settings_created=%s)"
        ),
        business.id,
        profile_created,
        settings_created,
    )

    return profile, settings
