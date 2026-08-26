# Initial structural migration for Billing.

import decimal
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.billing.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("cash_register", "0006_strengthen_cashmovement_origin"),
        ("core", "0001_initial"),
        ("customers", "0005_customeraccountentry_uniq_custentry_payment_not_null"),
        ("sales", "0004_saleline_tax_snapshot_salereturn_approved_by"),
        ("stores", "0005_store_is_default_alter_store_code_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BillingSeries",
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
                ("name", models.CharField(max_length=150, verbose_name="Nombre")),
                (
                    "document_type",
                    models.CharField(
                        choices=[
                            ("F1", "Factura completa"),
                            ("F2", "Factura simplificada"),
                            ("F3", "Factura en sustitución de simplificada"),
                            ("R1", "Rectificativa R1"),
                            ("R2", "Rectificativa R2"),
                            ("R3", "Rectificativa R3"),
                            ("R4", "Rectificativa R4"),
                            ("R5", "Rectificativa R5"),
                        ],
                        max_length=2,
                        verbose_name="Tipo de documento",
                    ),
                ),
                ("prefix", models.CharField(max_length=50, verbose_name="Prefijo")),
                (
                    "year",
                    models.PositiveIntegerField(
                        default=apps.billing.models.current_local_year,
                        verbose_name="Año",
                    ),
                ),
                (
                    "current_number",
                    models.PositiveBigIntegerField(
                        default=0, verbose_name="Último número"
                    ),
                ),
                (
                    "padding",
                    models.PositiveSmallIntegerField(
                        default=6, verbose_name="Relleno numérico"
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Activa")),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_series",
                        to="core.business",
                    ),
                ),
                (
                    "cash_register",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_series",
                        to="cash_register.cashregister",
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_series",
                        to="stores.store",
                    ),
                ),
            ],
            options={
                "verbose_name": "Serie de facturación",
                "verbose_name_plural": "Series de facturación",
                "ordering": ["-year", "prefix", "pk"],
                "indexes": [
                    models.Index(
                        fields=["business", "is_active"],
                        name="idx_billseries_bus_active",
                    ),
                    models.Index(
                        fields=["business", "document_type"],
                        name="idx_billseries_bus_type",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("business", "prefix", "year"),
                        name="uniq_billseries_bus_prefix_year",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("current_number__gte", 0)),
                        name="chk_billseries_number_gte_0",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("padding__gt", 0)),
                        name="chk_billseries_padding_gt_0",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("cash_register__isnull", True),
                            ("store__isnull", False),
                            _connector="OR",
                        ),
                        name="chk_billseries_cash_has_store",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BillingDocument",
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
                    "series_text",
                    models.CharField(
                        blank=True,
                        help_text="Snapshot de la identidad fiscal visible e inequívoca de la serie. El servicio de emisión debe construirla a partir del prefijo y el año, o una representación equivalente aprobada, sin duplicar el año.",
                        max_length=64,
                        verbose_name="Serie emitida",
                    ),
                ),
                (
                    "number",
                    models.PositiveBigIntegerField(
                        blank=True, null=True, verbose_name="Número"
                    ),
                ),
                (
                    "document_type",
                    models.CharField(
                        choices=[
                            ("F1", "Factura completa"),
                            ("F2", "Factura simplificada"),
                            ("F3", "Factura en sustitución de simplificada"),
                            ("R1", "Rectificativa R1"),
                            ("R2", "Rectificativa R2"),
                            ("R3", "Rectificativa R3"),
                            ("R4", "Rectificativa R4"),
                            ("R5", "Rectificativa R5"),
                        ],
                        max_length=2,
                        verbose_name="Tipo de documento",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Borrador"), ("issued", "Emitido")],
                        default="draft",
                        max_length=10,
                        verbose_name="Estado",
                    ),
                ),
                (
                    "issued_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="Fecha de emisión"
                    ),
                ),
                (
                    "operation_date",
                    models.DateField(
                        blank=True, null=True, verbose_name="Fecha de operación"
                    ),
                ),
                (
                    "description",
                    models.TextField(blank=True, verbose_name="Descripción"),
                ),
                ("idempotency_key", models.UUIDField(blank=True, null=True)),
                (
                    "idempotency_fingerprint",
                    models.CharField(blank=True, max_length=64),
                ),
                ("issuer_legal_name", models.CharField(blank=True, max_length=150)),
                ("issuer_tax_identifier", models.CharField(blank=True, max_length=20)),
                ("issuer_address_line_1", models.CharField(blank=True, max_length=255)),
                ("issuer_address_line_2", models.CharField(blank=True, max_length=255)),
                ("issuer_postal_code", models.CharField(blank=True, max_length=12)),
                ("issuer_city", models.CharField(blank=True, max_length=100)),
                ("issuer_province", models.CharField(blank=True, max_length=100)),
                ("issuer_country_code", models.CharField(blank=True, max_length=2)),
                ("recipient_name", models.CharField(blank=True, max_length=180)),
                ("recipient_legal_name", models.CharField(blank=True, max_length=180)),
                (
                    "recipient_tax_identifier",
                    models.CharField(blank=True, max_length=30),
                ),
                ("recipient_country_code", models.CharField(blank=True, max_length=2)),
                (
                    "recipient_foreign_id_type",
                    models.CharField(blank=True, max_length=50),
                ),
                ("recipient_foreign_id", models.CharField(blank=True, max_length=50)),
                (
                    "recipient_address_line_1",
                    models.CharField(blank=True, max_length=255),
                ),
                ("recipient_postal_code", models.CharField(blank=True, max_length=12)),
                ("recipient_city", models.CharField(blank=True, max_length=100)),
                ("recipient_province", models.CharField(blank=True, max_length=100)),
                (
                    "subtotal_amount",
                    models.DecimalField(
                        decimal_places=2, default=decimal.Decimal("0.00"), max_digits=14
                    ),
                ),
                (
                    "discount_amount",
                    models.DecimalField(
                        decimal_places=2, default=decimal.Decimal("0.00"), max_digits=14
                    ),
                ),
                (
                    "tax_amount",
                    models.DecimalField(
                        decimal_places=2, default=decimal.Decimal("0.00"), max_digits=14
                    ),
                ),
                (
                    "total_amount",
                    models.DecimalField(
                        decimal_places=2, default=decimal.Decimal("0.00"), max_digits=14
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_documents",
                        to="core.business",
                    ),
                ),
                (
                    "cash_register",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_documents",
                        to="cash_register.cashregister",
                    ),
                ),
                (
                    "cash_session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_documents",
                        to="cash_register.cashsession",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_documents",
                        to="customers.customer",
                    ),
                ),
                (
                    "issued_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_documents_issued",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "sale",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_documents",
                        to="sales.sale",
                    ),
                ),
                (
                    "series",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="documents",
                        to="billing.billingseries",
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_documents",
                        to="stores.store",
                    ),
                ),
            ],
            options={
                "verbose_name": "Documento de facturación",
                "verbose_name_plural": "Documentos de facturación",
                "ordering": ["-issued_at", "-created_at", "-pk"],
                "indexes": [
                    models.Index(
                        fields=["business", "store", "issued_at"],
                        name="idx_billdoc_bus_store_date",
                    ),
                    models.Index(
                        fields=["business", "document_type", "status"],
                        name="idx_billdoc_bus_type_status",
                    ),
                    models.Index(
                        fields=["business", "sale"], name="idx_billdoc_bus_sale"
                    ),
                    models.Index(
                        fields=["business", "customer"], name="idx_billdoc_bus_customer"
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("idempotency_key__isnull", False)),
                        fields=("business", "idempotency_key"),
                        name="uniq_billdoc_bus_idem_key",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("number__isnull", False)),
                        fields=("series", "number"),
                        name="uniq_billdoc_series_number",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("issued_at__isnull", True),
                                ("number__isnull", True),
                                ("status", "draft"),
                            ),
                            models.Q(
                                models.Q(
                                    ("idempotency_key__isnull", False),
                                    ("issued_at__isnull", False),
                                    ("issued_by__isnull", False),
                                    ("number__isnull", False),
                                    ("operation_date__isnull", False),
                                    ("status", "issued"),
                                ),
                                models.Q(("series_text", ""), _negated=True),
                                models.Q(
                                    ("idempotency_fingerprint", ""), _negated=True
                                ),
                            ),
                            _connector="OR",
                        ),
                        name="chk_billdoc_draft_issued_shape",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("number__isnull", True), ("number__gt", 0), _connector="OR"
                        ),
                        name="chk_billdoc_number_gt_0",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BillingDocumentLine",
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
                ("product_name", models.CharField(max_length=180)),
                ("sku", models.CharField(blank=True, max_length=80)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("unit", models.CharField(max_length=20)),
                (
                    "unit_base_price",
                    models.DecimalField(decimal_places=2, max_digits=12),
                ),
                (
                    "discount_amount",
                    models.DecimalField(
                        decimal_places=2, default=decimal.Decimal("0.00"), max_digits=14
                    ),
                ),
                (
                    "gross_base_amount",
                    models.DecimalField(decimal_places=2, max_digits=14),
                ),
                (
                    "taxable_base_amount",
                    models.DecimalField(decimal_places=2, max_digits=14),
                ),
                ("tax_rate", models.DecimalField(decimal_places=2, max_digits=5)),
                ("tax_type", models.CharField(max_length=20)),
                (
                    "clave_regimen",
                    models.CharField(blank=True, max_length=2, null=True),
                ),
                (
                    "calificacion_operacion",
                    models.CharField(blank=True, max_length=2, null=True),
                ),
                (
                    "operacion_exenta",
                    models.CharField(blank=True, max_length=2, null=True),
                ),
                ("has_equivalence_surcharge", models.BooleanField(default=False)),
                (
                    "equivalence_surcharge_rate",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=5, null=True
                    ),
                ),
                (
                    "tax_amount",
                    models.DecimalField(
                        decimal_places=2, default=decimal.Decimal("0.00"), max_digits=14
                    ),
                ),
                (
                    "line_total",
                    models.DecimalField(
                        decimal_places=2, default=decimal.Decimal("0.00"), max_digits=14
                    ),
                ),
                (
                    "billing_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lines",
                        to="billing.billingdocument",
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_document_lines",
                        to="core.business",
                    ),
                ),
            ],
            options={
                "verbose_name": "Línea de documento de facturación",
                "verbose_name_plural": "Líneas de documentos de facturación",
                "ordering": ["created_at", "pk"],
                "indexes": [
                    models.Index(
                        fields=["business", "billing_document"],
                        name="idx_billline_bus_document",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="BillingTaxBreakdown",
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
                ("tax_type", models.CharField(max_length=20)),
                ("tax_rate", models.DecimalField(decimal_places=2, max_digits=5)),
                (
                    "clave_regimen",
                    models.CharField(blank=True, max_length=2, null=True),
                ),
                (
                    "calificacion_operacion",
                    models.CharField(blank=True, max_length=2, null=True),
                ),
                (
                    "operacion_exenta",
                    models.CharField(blank=True, max_length=2, null=True),
                ),
                ("has_equivalence_surcharge", models.BooleanField(default=False)),
                (
                    "equivalence_surcharge_rate",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=5, null=True
                    ),
                ),
                (
                    "taxable_base_amount",
                    models.DecimalField(decimal_places=2, max_digits=14),
                ),
                ("tax_amount", models.DecimalField(decimal_places=2, max_digits=14)),
                (
                    "billing_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tax_breakdowns",
                        to="billing.billingdocument",
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_tax_breakdowns",
                        to="core.business",
                    ),
                ),
            ],
            options={
                "verbose_name": "Desglose fiscal de facturación",
                "verbose_name_plural": "Desgloses fiscales de facturación",
                "ordering": ["created_at", "pk"],
                "indexes": [
                    models.Index(
                        fields=["business", "billing_document"],
                        name="idx_billtax_bus_document",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="BillingDocumentRelation",
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
                    "relation_type",
                    models.CharField(
                        choices=[
                            ("substitutes", "Sustituye"),
                            ("rectifies", "Rectifica"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_document_relations",
                        to="core.business",
                    ),
                ),
                (
                    "source_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="outgoing_relations",
                        to="billing.billingdocument",
                    ),
                ),
                (
                    "target_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="incoming_relations",
                        to="billing.billingdocument",
                    ),
                ),
            ],
            options={
                "verbose_name": "Relación entre documentos de facturación",
                "verbose_name_plural": "Relaciones entre documentos de facturación",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("source_document", models.F("target_document")),
                            _negated=True,
                        ),
                        name="chk_billrel_source_ne_target",
                    ),
                    models.UniqueConstraint(
                        fields=("source_document", "target_document", "relation_type"),
                        name="uniq_billrel_source_target_type",
                    ),
                ],
            },
        ),
    ]
