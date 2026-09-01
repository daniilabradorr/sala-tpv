from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("business_config", "0005_possettings_enable_stock_control_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="businessprofile",
            constraint=models.UniqueConstraint(
                fields=("country_code", "tax_identifier"),
                name="uniq_businessprofile_country_tax_id",
            ),
        ),
    ]
