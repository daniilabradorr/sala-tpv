import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0003_salereturn_completed_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="saleline",
            name="tax_type",
            field=models.CharField(
                default="IVA", max_length=20, verbose_name="Tipo de impuesto"
            ),
        ),
        migrations.AddField(
            model_name="saleline",
            name="clave_regimen",
            field=models.CharField(
                blank=True,
                default="01",
                max_length=2,
                null=True,
                verbose_name="Clave de régimen",
            ),
        ),
        migrations.AddField(
            model_name="saleline",
            name="calificacion_operacion",
            field=models.CharField(
                blank=True,
                default="S1",
                max_length=2,
                null=True,
                verbose_name="Calificación de la operación",
            ),
        ),
        migrations.AddField(
            model_name="saleline",
            name="operacion_exenta",
            field=models.CharField(
                blank=True,
                max_length=2,
                null=True,
                verbose_name="Causa de operación exenta",
            ),
        ),
        migrations.AddField(
            model_name="saleline",
            name="has_equivalence_surcharge",
            field=models.BooleanField(
                default=False, verbose_name="Tiene recargo de equivalencia"
            ),
        ),
        migrations.AddField(
            model_name="saleline",
            name="equivalence_surcharge_rate",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=5,
                null=True,
                verbose_name="Porcentaje de recargo de equivalencia",
            ),
        ),
        migrations.AddField(
            model_name="salereturn",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sale_returns_approved",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Aprobada por",
            ),
        ),
    ]
