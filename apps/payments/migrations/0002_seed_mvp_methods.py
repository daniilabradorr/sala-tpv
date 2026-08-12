from django.db import migrations

METHODS = (
    ("cash", "Efectivo", True),
    ("card", "Tarjeta", False),
    ("bizum", "Bizum", False),
    ("transfer", "Transferencia", False),
)


def seed(apps, schema_editor):
    Business = apps.get_model("core", "Business")
    PaymentMethod = apps.get_model("payments", "PaymentMethod")
    for business in Business.objects.all().iterator():
        for code, name, affects_cash in METHODS:
            PaymentMethod.objects.get_or_create(
                business=business,
                code=code,
                defaults={"name": name, "affects_cash_register": affects_cash},
            )


class Migration(migrations.Migration):
    dependencies = [("payments", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
