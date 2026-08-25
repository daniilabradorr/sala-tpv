from django.db import migrations


def classify_historical_closing_counts(apps, schema_editor):
    CashCount = apps.get_model("cash_register", "CashCount")
    CashSession = apps.get_model("cash_register", "CashSession")

    closed_session_ids = CashSession.objects.filter(status="closed").values_list(
        "pk", flat=True
    )
    for session_id in closed_session_ids.iterator():
        latest = (
            CashCount.objects.filter(cash_session_id=session_id)
            .order_by("-created_at", "-pk")
            .first()
        )
        if latest is not None:
            CashCount.objects.filter(pk=latest.pk).update(count_type="closing")


def restore_all_counts_as_review(apps, schema_editor):
    CashCount = apps.get_model("cash_register", "CashCount")
    CashCount.objects.filter(count_type="closing").update(count_type="review")


class Migration(migrations.Migration):
    dependencies = [
        (
            "cash_register",
            "0004_cashcount_count_type_cashmovement_adjustment_direction",
        ),
    ]

    operations = [
        migrations.RunPython(
            classify_historical_closing_counts,
            restore_all_counts_as_review,
        ),
    ]
