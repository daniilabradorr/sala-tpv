from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("cash_register", "0003_alter_cashregister_code_and_more")]

    operations = [
        migrations.AddField(
            model_name="cashcount",
            name="count_type",
            field=models.CharField(
                choices=[("review", "Revisión"), ("closing", "Cierre")],
                db_index=True,
                default="review",
                max_length=10,
                verbose_name="Tipo de arqueo",
            ),
        ),
        migrations.AddField(
            model_name="cashmovement",
            name="adjustment_direction",
            field=models.CharField(
                blank=True,
                choices=[("in", "Entrada"), ("out", "Salida")],
                max_length=3,
                null=True,
                verbose_name="Dirección del ajuste",
            ),
        ),
        migrations.AddConstraint(
            model_name="cashcount",
            constraint=models.UniqueConstraint(
                condition=Q(count_type="closing"),
                fields=("cash_session",),
                name="uniq_cashcount_closing_session",
            ),
        ),
        migrations.AddConstraint(
            model_name="cashmovement",
            constraint=models.CheckConstraint(
                condition=(
                    Q(movement_type="adjustment", adjustment_direction__isnull=False)
                    | (
                        ~Q(movement_type="adjustment")
                        & Q(adjustment_direction__isnull=True)
                    )
                ),
                name="chk_cashmovement_adjust_dir",
            ),
        ),
    ]
