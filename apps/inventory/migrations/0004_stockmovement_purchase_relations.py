import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0003_stockmovement_sales_relations"),
        ("purchases", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockmovement",
            name="purchase",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="purchases.purchase",
                verbose_name="Compra",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="purchase_line",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="purchases.purchaseline",
                verbose_name="Línea de compra",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="purchase_receipt",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="purchases.purchasereceipt",
                verbose_name="Recepción de compra",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="purchase_receipt_line",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="purchases.purchasereceiptline",
                verbose_name="Línea de recepción de compra",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.UniqueConstraint(
                condition=models.Q(("purchase_receipt_line__isnull", False)),
                fields=("purchase_receipt_line",),
                name="uniq_stmov_purch_receipt_line",
            ),
        ),
    ]
