from decimal import Decimal

from django.db import migrations


def backfill_business_configuration(apps, schema_editor):
    Business = apps.get_model("core", "Business")
    BusinessProfile = apps.get_model("business_config", "BusinessProfile")
    POSSettings = apps.get_model("business_config", "POSSettings")

    for business in Business.objects.all():
        BusinessProfile.objects.get_or_create(
            business=business,
            defaults={
                "legal_name": business.name,
                "trade_name": business.name,
                "brand_name": business.name,
                "country_code": "ES",
                "currency_code": "EUR",
                "receipt_footer": "Gracias por su visita.",
                "return_policy": "",
                "default_tax_rate": Decimal("21.00"),
            },
        )

        POSSettings.objects.get_or_create(
            business=business,
            defaults={
                "prices_include_tax": True,
                "allow_sale_without_stock": False,
                "allow_manual_price": False,
                "allow_manual_discounts": True,
                "max_manual_discount_percent": Decimal("20.00"),
                "require_open_cash_register": True,
                "allow_split_payments": True,
                "require_pin_for_sensitive_actions": True,
            },
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("business_config", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            backfill_business_configuration,
            noop_reverse,
        ),
    ]