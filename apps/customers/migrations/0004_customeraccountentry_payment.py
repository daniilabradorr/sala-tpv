import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0003_customeraccountentry_sale"),
        ("payments", "0002_seed_mvp_methods"),
    ]
    operations = [
        migrations.AddField(
            model_name="customeraccountentry",
            name="payment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="customer_account_entries",
                to="payments.payment",
                verbose_name="Pago",
            ),
        ),
    ]
