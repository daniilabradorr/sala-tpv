from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("business_config", "0006_businessprofile_unique_fiscal_identity")]
    operations = [
        migrations.AddField(
            model_name="businessprofile",
            name="logo",
            field=models.ImageField(
                blank=True,
                editable=False,
                upload_to="",
                verbose_name="logo gestionado",
            ),
        ),
    ]
