import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("cash_register", "0001_initial"),
        ("core", "0001_initial"),
        ("sales", "0003_salereturn_completed_at"),
        ("stores", "0005_store_is_default_alter_store_code_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="PaymentMethod",
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
                ("name", models.CharField(max_length=100, verbose_name="Nombre")),
                (
                    "code",
                    models.CharField(
                        choices=[
                            ("cash", "Efectivo"),
                            ("card", "Tarjeta"),
                            ("bizum", "Bizum"),
                            ("transfer", "Transferencia"),
                        ],
                        max_length=30,
                        verbose_name="Código",
                    ),
                ),
                (
                    "affects_cash_register",
                    models.BooleanField(
                        default=False,
                        editable=False,
                        help_text="Se determina automáticamente según el método de pago. En el MVP únicamente el efectivo mueve caja física.",
                        verbose_name="Afecta a caja física",
                    ),
                ),
                (
                    "allows_refund",
                    models.BooleanField(
                        default=True,
                        help_text="Indica si este método puede utilizarse para realizar nuevos reembolsos.",
                        verbose_name="Permite reembolso",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Permite desactivar el método para nuevas operaciones sin perder su histórico.",
                        verbose_name="Activo",
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_methods",
                        to="core.business",
                        verbose_name="Negocio",
                    ),
                ),
            ],
            options={
                "ordering": ["name", "pk"],
                "verbose_name": "Método de pago",
                "verbose_name_plural": "Métodos de pago",
            },
        ),
        migrations.CreateModel(
            name="Payment",
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
                    "payment_type",
                    models.CharField(
                        choices=[("sale_payment", "Cobro"), ("refund", "Reembolso")],
                        db_index=True,
                        default="sale_payment",
                        max_length=20,
                        verbose_name="Tipo",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Importe económico de la operación. Siempre se almacena como valor positivo.",
                        max_digits=14,
                        verbose_name="Importe",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendiente"),
                            ("completed", "Completado"),
                            ("failed", "Fallido"),
                            ("cancelled", "Cancelado"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                        verbose_name="Estado",
                    ),
                ),
                (
                    "idempotency_key",
                    models.UUIDField(
                        help_text="Identificador estable de la operación económica. Permite detectar reintentos del mismo cobro o reembolso y evitar duplicados.",
                        verbose_name="Clave de idempotencia",
                    ),
                ),
                (
                    "external_reference",
                    models.CharField(
                        blank=True,
                        help_text="Referencia opcional procedente del datáfono, Bizum, transferencia o una futura pasarela de pago. No sustituye a la clave de idempotencia.",
                        max_length=150,
                        verbose_name="Referencia externa",
                    ),
                ),
                ("notes", models.TextField(blank=True, verbose_name="Notas")),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payments",
                        to="core.business",
                        verbose_name="Negocio",
                    ),
                ),
                (
                    "cash_session",
                    models.ForeignKey(
                        blank=True,
                        help_text="Sesión de caja asociada a la operación cuando corresponda. Será especialmente relevante para efectivo, pero también puede conservarse como contexto operativo del turno para tarjeta, Bizum o transferencia.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="cash_register.cashsession",
                        verbose_name="Sesión de caja",
                    ),
                ),
                (
                    "method",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="payments.paymentmethod",
                        verbose_name="Método de pago",
                    ),
                ),
                (
                    "processed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments_processed",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Procesado por",
                    ),
                ),
                (
                    "sale",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="sales.sale",
                        verbose_name="Venta",
                    ),
                ),
                (
                    "sale_return",
                    models.ForeignKey(
                        blank=True,
                        help_text="Devolución comercial que origina el reembolso. Debe existir únicamente en Payments de tipo refund.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="refund_payments",
                        to="sales.salereturn",
                        verbose_name="Devolución",
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="stores.store",
                        verbose_name="Tienda",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "verbose_name": "Pago",
                "verbose_name_plural": "Pagos",
            },
        ),
        migrations.AddConstraint(
            model_name="paymentmethod",
            constraint=models.UniqueConstraint(
                fields=("business", "code"), name="uniq_paymentmethod_business_code"
            ),
        ),
        migrations.AddConstraint(
            model_name="paymentmethod",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("affects_cash_register", True), ("code", "cash")),
                    models.Q(
                        models.Q(("code", "cash"), _negated=True),
                        ("affects_cash_register", False),
                    ),
                    _connector="OR",
                ),
                name="chk_paymethod_cash_register_effect",
            ),
        ),
        migrations.AddIndex(
            model_name="paymentmethod",
            index=models.Index(
                fields=["business", "is_active"], name="idx_paymethod_bus_active"
            ),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gt", Decimal("0.00"))),
                name="chk_payment_amount_gt_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("payment_type", "refund"), ("sale_return__isnull", False)
                    ),
                    models.Q(
                        ("payment_type", "sale_payment"), ("sale_return__isnull", True)
                    ),
                    _connector="OR",
                ),
                name="chk_payment_type_sale_return",
            ),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.UniqueConstraint(
                fields=("business", "idempotency_key"),
                name="uniq_payment_business_idempotency",
            ),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(
                fields=["business", "store", "status"],
                name="idx_payment_bus_store_status",
            ),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(
                fields=["business", "sale"], name="idx_payment_bus_sale"
            ),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(
                fields=["business", "payment_type"], name="idx_payment_bus_type"
            ),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(
                fields=["business", "created_at"], name="idx_payment_bus_created"
            ),
        ),
    ]
