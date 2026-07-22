# Generated manually for TPV-018 customers

import decimal
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "customer_type",
                    models.CharField(
                        choices=[
                            ("individual", "Particular"),
                            ("company", "Empresa"),
                            ("foreign", "Extranjero"),
                        ],
                        default="individual",
                        max_length=20,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("legal_name", models.CharField(blank=True, max_length=255)),
                ("tax_identifier", models.CharField(blank=True, max_length=32)),
                ("country_code", models.CharField(default="ES", max_length=2)),
                ("foreign_id_type", models.CharField(blank=True, max_length=32)),
                ("foreign_id", models.CharField(blank=True, max_length=64)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=32)),
                ("address_line_1", models.CharField(blank=True, max_length=255)),
                ("postal_code", models.CharField(blank=True, max_length=20)),
                ("city", models.CharField(blank=True, max_length=120)),
                ("province", models.CharField(blank=True, max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customers_customer_set",
                        related_query_name="customers_customer",
                        to="core.business",
                    ),
                ),
            ],
            options={"ordering": ("name", "pk")},
        ),
        migrations.CreateModel(
            name="CustomerAccount",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "balance",
                    models.DecimalField(
                        decimal_places=2, default=decimal.Decimal("0.00"), max_digits=12
                    ),
                ),
                (
                    "credit_limit",
                    models.DecimalField(
                        decimal_places=2, default=decimal.Decimal("0.00"), max_digits=12
                    ),
                ),
                ("is_blocked", models.BooleanField(default=False)),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customers_customeraccount_set",
                        related_query_name="customers_customeraccount",
                        to="core.business",
                    ),
                ),
                (
                    "customer",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="account",
                        to="customers.customer",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="CustomerAccountEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "entry_type",
                    models.CharField(
                        choices=[
                            ("charge", "Cargo"),
                            ("payment", "Pago"),
                            ("refund", "Reembolso"),
                            ("adjustment", "Ajuste"),
                        ],
                        max_length=20,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("balance_after", models.DecimalField(decimal_places=2, max_digits=12)),
                ("notes", models.TextField(blank=True)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="entries",
                        to="customers.customeraccount",
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customers_customeraccountentry_set",
                        related_query_name="customers_customeraccountentry",
                        to="core.business",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_account_entries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
        migrations.AddIndex(
            model_name="customer",
            index=models.Index(
                fields=["business", "is_active", "name"],
                name="customers_biz_active_name_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                condition=models.Q(("tax_identifier", ""), _negated=True),
                fields=("business", "tax_identifier"),
                name="customers_unique_tax_identifier_business",
            ),
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("foreign_id_type", ""), ("foreign_id", ""), _negated=True
                ),
                fields=("business", "foreign_id_type", "foreign_id"),
                name="customers_unique_foreign_id_business",
            ),
        ),
        migrations.AddIndex(
            model_name="customeraccountentry",
            index=models.Index(
                fields=["business", "account", "-created_at"],
                name="cust_entry_biz_account_idx",
            ),
        ),
    ]
