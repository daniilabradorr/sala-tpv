import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "customers",
            "0002_remove_customeraccountentry_chk_custentry_type_sign_and_more",
        ),
        ("sales", "0003_salereturn_completed_at"),
    ]
    operations = [
        migrations.AddField(
            model_name="customeraccountentry",
            name="sale",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="customer_account_entries",
                to="sales.sale",
                verbose_name="Venta",
            ),
        ),
    ]
