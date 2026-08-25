from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("cash_register", "0005_classify_historical_closing_counts"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="cashmovement",
            name="chk_cashmovement_origin",
        ),
        migrations.AddConstraint(
            model_name="cashmovement",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        movement_type__in=("sale_cash", "refund_cash"),
                        payment__isnull=False,
                        sale__isnull=False,
                    )
                    | Q(
                        movement_type__in=("cash_in", "cash_out"),
                        payment__isnull=True,
                        sale__isnull=True,
                    )
                    | Q(
                        movement_type="adjustment",
                        payment__isnull=True,
                        sale__isnull=True,
                    )
                ),
                name="chk_cashmovement_origin",
            ),
        ),
    ]
