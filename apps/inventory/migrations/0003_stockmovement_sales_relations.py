import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0002_allow_negative_stock_snapshots"),
        ("sales", "0004_saleline_tax_snapshot_salereturn_approved_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockmovement",
            name="sale",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="sales.sale",
                verbose_name="Venta",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="sale_line",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="sales.saleline",
                verbose_name="Línea de venta",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="sale_return",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="sales.salereturn",
                verbose_name="Devolución de venta",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="sale_return_line",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="sales.salereturnline",
                verbose_name="Línea de devolución",
            ),
        ),
        migrations.AlterField(
            model_name="stockmovement",
            name="reference_id",
            field=models.CharField(
                blank=True,
                help_text="ID externo o interno del documento relacionado. Se conserva como referencia genérica y por compatibilidad.",
                max_length=80,
                verbose_name="ID de referencia",
            ),
        ),
    ]
