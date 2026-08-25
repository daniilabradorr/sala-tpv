from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("payments", "0002_seed_mvp_methods")]

    operations = [
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.CheckConstraint(
                condition=~Q(status="completed") | Q(cash_session__isnull=False),
                name="chk_payment_completed_session",
            ),
        ),
    ]
