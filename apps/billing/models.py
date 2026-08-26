from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel


ZERO = Decimal("0.00")


def current_local_year():
    """Return the current local year as a migration-serializable callable."""
    return timezone.localdate().year


class BillingDocumentTypeChoices(models.TextChoices):
    F1 = "F1", "Factura completa"
    F2 = "F2", "Factura simplificada"
    F3 = "F3", "Factura en sustitución de simplificada"
    R1 = "R1", "Rectificativa R1"
    R2 = "R2", "Rectificativa R2"
    R3 = "R3", "Rectificativa R3"
    R4 = "R4", "Rectificativa R4"
    R5 = "R5", "Rectificativa R5"


class BillingDocumentStatusChoices(models.TextChoices):
    DRAFT = "draft", "Borrador"
    ISSUED = "issued", "Emitido"


class BillingDocumentRelationTypeChoices(models.TextChoices):
    SUBSTITUTES = "substitutes", "Sustituye"
    RECTIFIES = "rectifies", "Rectifica"


class BillingSeries(TimeStampedModel):
    """Fiscal numbering series. Number allocation belongs to the billing service.

    Because numbering may restart each year, the service must derive an
    unambiguous visible identity from ``prefix`` and ``year`` (or an equivalent
    approved representation). It must not duplicate the year when the configured
    prefix already contains it.

    Once this series has issued documents, normal ``save()`` calls cannot alter
    its fiscal identity. Bulk queryset operations bypass model methods, so
    services and admin code must not use them for those critical fields.
    """

    IMMUTABLE_IDENTITY_FIELDS = (
        "business_id",
        "store_id",
        "cash_register_id",
        "document_type",
        "prefix",
        "year",
        "padding",
    )

    business = models.ForeignKey(
        "core.Business", on_delete=models.PROTECT, related_name="billing_series"
    )
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.PROTECT,
        related_name="billing_series",
        null=True,
        blank=True,
    )
    cash_register = models.ForeignKey(
        "cash_register.CashRegister",
        on_delete=models.PROTECT,
        related_name="billing_series",
        null=True,
        blank=True,
    )
    name = models.CharField("Nombre", max_length=150)
    document_type = models.CharField(
        "Tipo de documento", max_length=2, choices=BillingDocumentTypeChoices.choices
    )
    prefix = models.CharField("Prefijo", max_length=50)
    year = models.PositiveIntegerField("Año", default=current_local_year)
    current_number = models.PositiveBigIntegerField("Último número", default=0)
    padding = models.PositiveSmallIntegerField("Relleno numérico", default=6)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        verbose_name = "Serie de facturación"
        verbose_name_plural = "Series de facturación"
        ordering = ["-year", "prefix", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "prefix", "year"],
                name="uniq_billseries_bus_prefix_year",
            ),
            models.CheckConstraint(
                condition=Q(current_number__gte=0),
                name="chk_billseries_number_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(padding__gt=0), name="chk_billseries_padding_gt_0"
            ),
            models.CheckConstraint(
                condition=Q(cash_register__isnull=True) | Q(store__isnull=False),
                name="chk_billseries_cash_has_store",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "is_active"], name="idx_billseries_bus_active"
            ),
            models.Index(
                fields=["business", "document_type"],
                name="idx_billseries_bus_type",
            ),
        ]

    def __str__(self):
        return f"{self.prefix} ({self.year})"

    def clean(self):
        super().clean()
        errors = {}
        self.name = (self.name or "").strip()
        self.prefix = (self.prefix or "").strip().upper()
        if not self.name:
            errors["name"] = "El nombre de la serie es obligatorio."
        if not self.prefix:
            errors["prefix"] = "El prefijo de la serie es obligatorio."
        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = "La tienda debe pertenecer al mismo negocio."
        if self.cash_register_id:
            if not self.store_id:
                errors["store"] = "Una serie asociada a una caja requiere tienda."
            if self.cash_register.business_id != self.business_id:
                errors["cash_register"] = "La caja debe pertenecer al mismo negocio."
            if self.cash_register.store_id != self.store_id:
                errors["cash_register"] = "La caja debe pertenecer a la misma tienda."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            original = (
                type(self)
                .objects.filter(pk=self.pk)
                .values(*self.IMMUTABLE_IDENTITY_FIELDS)
                .first()
            )
            has_issued_documents = (
                original
                and BillingDocument.objects.filter(
                    series_id=self.pk,
                    status=BillingDocumentStatusChoices.ISSUED,
                ).exists()
            )
            if has_issued_documents and any(
                original[field] != getattr(self, field)
                for field in self.IMMUTABLE_IDENTITY_FIELDS
            ):
                raise ValidationError(
                    "No se puede modificar la identidad de una serie que ya tiene "
                    "documentos emitidos."
                )
        self.full_clean()
        return super().save(*args, **kwargs)


class BillingDocument(TimeStampedModel):
    """Stable internal fiscal document, independent from external submissions.

    Issued rows are immutable through ``save()`` and ``delete()``. As with every
    model-level guard, bulk queryset operations bypass it; services and admin
    code must preserve the same rule.
    """

    business = models.ForeignKey(
        "core.Business", on_delete=models.PROTECT, related_name="billing_documents"
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.PROTECT, related_name="billing_documents"
    )
    cash_register = models.ForeignKey(
        "cash_register.CashRegister",
        on_delete=models.PROTECT,
        related_name="billing_documents",
        null=True,
        blank=True,
    )
    cash_session = models.ForeignKey(
        "cash_register.CashSession",
        on_delete=models.PROTECT,
        related_name="billing_documents",
        null=True,
        blank=True,
    )
    sale = models.ForeignKey(
        "sales.Sale",
        on_delete=models.PROTECT,
        related_name="billing_documents",
        null=True,
        blank=True,
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="billing_documents",
        null=True,
        blank=True,
    )
    series = models.ForeignKey(
        BillingSeries, on_delete=models.PROTECT, related_name="documents"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="billing_documents_issued",
        null=True,
        blank=True,
    )

    series_text = models.CharField(
        "Serie emitida",
        max_length=64,
        blank=True,
        help_text=(
            "Snapshot de la identidad fiscal visible e inequívoca de la serie. "
            "El servicio de emisión debe construirla a partir del prefijo y el "
            "año, o una representación equivalente aprobada, sin duplicar el año."
        ),
    )
    number = models.PositiveBigIntegerField("Número", null=True, blank=True)
    document_type = models.CharField(
        "Tipo de documento", max_length=2, choices=BillingDocumentTypeChoices.choices
    )
    status = models.CharField(
        "Estado",
        max_length=10,
        choices=BillingDocumentStatusChoices.choices,
        default=BillingDocumentStatusChoices.DRAFT,
    )
    issued_at = models.DateTimeField("Fecha de emisión", null=True, blank=True)
    operation_date = models.DateField("Fecha de operación", null=True, blank=True)
    description = models.TextField("Descripción", blank=True)
    idempotency_key = models.UUIDField(null=True, blank=True)
    idempotency_fingerprint = models.CharField(max_length=64, blank=True)

    issuer_legal_name = models.CharField(max_length=150, blank=True)
    issuer_tax_identifier = models.CharField(max_length=20, blank=True)
    issuer_address_line_1 = models.CharField(max_length=255, blank=True)
    issuer_address_line_2 = models.CharField(max_length=255, blank=True)
    issuer_postal_code = models.CharField(max_length=12, blank=True)
    issuer_city = models.CharField(max_length=100, blank=True)
    issuer_province = models.CharField(max_length=100, blank=True)
    issuer_country_code = models.CharField(max_length=2, blank=True)

    recipient_name = models.CharField(max_length=180, blank=True)
    recipient_legal_name = models.CharField(max_length=180, blank=True)
    recipient_tax_identifier = models.CharField(max_length=30, blank=True)
    recipient_country_code = models.CharField(max_length=2, blank=True)
    recipient_foreign_id_type = models.CharField(max_length=50, blank=True)
    recipient_foreign_id = models.CharField(max_length=50, blank=True)
    recipient_address_line_1 = models.CharField(max_length=255, blank=True)
    recipient_postal_code = models.CharField(max_length=12, blank=True)
    recipient_city = models.CharField(max_length=100, blank=True)
    recipient_province = models.CharField(max_length=100, blank=True)

    subtotal_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)

    class Meta:
        verbose_name = "Documento de facturación"
        verbose_name_plural = "Documentos de facturación"
        ordering = ["-issued_at", "-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "idempotency_key"],
                condition=Q(idempotency_key__isnull=False),
                name="uniq_billdoc_bus_idem_key",
            ),
            models.UniqueConstraint(
                fields=["series", "number"],
                condition=Q(number__isnull=False),
                name="uniq_billdoc_series_number",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=BillingDocumentStatusChoices.DRAFT,
                        number__isnull=True,
                        issued_at__isnull=True,
                    )
                    | Q(
                        status=BillingDocumentStatusChoices.ISSUED,
                        number__isnull=False,
                        issued_at__isnull=False,
                        operation_date__isnull=False,
                        issued_by__isnull=False,
                        idempotency_key__isnull=False,
                    )
                    & ~Q(series_text="")
                    & ~Q(idempotency_fingerprint="")
                ),
                name="chk_billdoc_draft_issued_shape",
            ),
            models.CheckConstraint(
                condition=Q(number__isnull=True) | Q(number__gt=0),
                name="chk_billdoc_number_gt_0",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "store", "issued_at"],
                name="idx_billdoc_bus_store_date",
            ),
            models.Index(
                fields=["business", "document_type", "status"],
                name="idx_billdoc_bus_type_status",
            ),
            models.Index(fields=["business", "sale"], name="idx_billdoc_bus_sale"),
            models.Index(
                fields=["business", "customer"], name="idx_billdoc_bus_customer"
            ),
        ]

    def __str__(self):
        if self.number is None:
            return f"{self.get_document_type_display()} · borrador"
        return f"{self.series_text}-{self.number}"

    def _was_issued(self):
        if not self.pk:
            return False
        return (
            type(self)
            .objects.filter(pk=self.pk, status=BillingDocumentStatusChoices.ISSUED)
            .exists()
        )

    def clean(self):
        super().clean()
        errors = {}
        self.series_text = (self.series_text or "").strip().upper()
        self.description = (self.description or "").strip()
        self.idempotency_fingerprint = (
            (self.idempotency_fingerprint or "").strip().lower()
        )
        issuer_fields = (
            "issuer_legal_name",
            "issuer_tax_identifier",
            "issuer_address_line_1",
            "issuer_address_line_2",
            "issuer_postal_code",
            "issuer_city",
            "issuer_province",
            "issuer_country_code",
        )
        for field in issuer_fields:
            value = (getattr(self, field) or "").strip()
            if field in {"issuer_tax_identifier", "issuer_country_code"}:
                value = value.upper()
            setattr(self, field, value)

        if (
            self.store_id
            and self.business_id
            and self.store.business_id != self.business_id
        ):
            errors["store"] = "La tienda debe pertenecer al mismo negocio."
        if self.series_id and self.business_id:
            if self.series.business_id != self.business_id:
                errors["series"] = "La serie debe pertenecer al mismo negocio."
            elif self.series.store_id and self.series.store_id != self.store_id:
                errors["series"] = "La serie debe pertenecer a la tienda del documento."
            if self.series.document_type != self.document_type:
                errors["series"] = (
                    "El tipo de documento debe coincidir con el tipo de la serie."
                )
            if (
                self.series.cash_register_id != self.cash_register_id
                and self.series.cash_register_id
            ):
                errors["cash_register"] = "El documento debe usar la caja de su serie."
        if self.cash_register_id:
            if self.cash_register.business_id != self.business_id:
                errors["cash_register"] = "La caja debe pertenecer al mismo negocio."
            if self.cash_register.store_id != self.store_id:
                errors["cash_register"] = "La caja debe pertenecer a la misma tienda."
        if self.cash_session_id:
            if self.cash_session.business_id != self.business_id:
                errors["cash_session"] = "La sesión debe pertenecer al mismo negocio."
            if self.cash_session.store_id != self.store_id:
                errors["cash_session"] = "La sesión debe pertenecer a la misma tienda."
            if (
                self.cash_register_id
                and self.cash_session.cash_register_id != self.cash_register_id
            ):
                errors["cash_session"] = "La sesión debe pertenecer a la caja indicada."
        if self.sale_id:
            if self.sale.business_id != self.business_id:
                errors["sale"] = "La venta debe pertenecer al mismo negocio."
            if self.sale.store_id != self.store_id:
                errors["sale"] = "La venta debe pertenecer a la misma tienda."
            if (
                self.sale.cash_register_id
                and self.sale.cash_register_id != self.cash_register_id
            ):
                errors["cash_register"] = "La caja debe coincidir con la de la venta."
            if (
                self.sale.cash_session_id
                and self.sale.cash_session_id != self.cash_session_id
            ):
                errors["cash_session"] = "La sesión debe coincidir con la de la venta."
        if self.customer_id and self.customer.business_id != self.business_id:
            errors["customer"] = "El cliente debe pertenecer al mismo negocio."
        if self.issued_by_id and not self.issued_by.is_superuser:
            if self.issued_by.business_id != self.business_id:
                errors["issued_by"] = "El usuario debe pertenecer al mismo negocio."

        if self.status == BillingDocumentStatusChoices.DRAFT:
            if self.number is not None:
                errors["number"] = "Un borrador no puede tener número fiscal."
            if self.issued_at is not None:
                errors["issued_at"] = "Un borrador no puede tener fecha de emisión."
        elif self.status == BillingDocumentStatusChoices.ISSUED:
            required = {
                "number": self.number,
                "series_text": self.series_text,
                "issued_at": self.issued_at,
                "operation_date": self.operation_date,
                "issued_by": self.issued_by_id,
                "idempotency_key": self.idempotency_key,
                "idempotency_fingerprint": self.idempotency_fingerprint,
                "description": self.description,
                "issuer_legal_name": self.issuer_legal_name,
                "issuer_tax_identifier": self.issuer_tax_identifier,
                "issuer_address_line_1": self.issuer_address_line_1,
                "issuer_postal_code": self.issuer_postal_code,
                "issuer_city": self.issuer_city,
                "issuer_province": self.issuer_province,
                "issuer_country_code": self.issuer_country_code,
            }
            for field, value in required.items():
                if value in (None, ""):
                    errors[field] = "Este campo es obligatorio al emitir."
            if self.number is not None and self.number <= 0:
                errors["number"] = "El número fiscal debe ser mayor que cero."
            if self.idempotency_fingerprint and len(self.idempotency_fingerprint) != 64:
                errors["idempotency_fingerprint"] = (
                    "El fingerprint SHA-256 debe tener 64 caracteres."
                )
            elif self.idempotency_fingerprint and not set(
                self.idempotency_fingerprint
            ).issubset(set("0123456789abcdef")):
                errors["idempotency_fingerprint"] = (
                    "El fingerprint SHA-256 debe ser hexadecimal."
                )
            if (
                self.document_type
                in {
                    BillingDocumentTypeChoices.F1,
                    BillingDocumentTypeChoices.F3,
                }
                and not self.customer_id
            ):
                errors["customer"] = (
                    "Los documentos F1 y F3 emitidos requieren un cliente."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._was_issued():
            raise ValidationError("Un documento emitido no puede modificarse.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == BillingDocumentStatusChoices.ISSUED or self._was_issued():
            raise ValidationError("Un documento emitido no puede eliminarse.")
        return super().delete(*args, **kwargs)


class IssuedDocumentChildMixin:
    """Guard normal writes to snapshots owned by an issued document.

    Bulk queryset operations bypass model methods. Services and admin code must
    therefore never use them to mutate historical fiscal document children.
    """

    def _ensure_document_is_editable(self):
        if self.pk:
            original_document_id = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("billing_document_id", flat=True)
                .first()
            )
            if (
                original_document_id
                and BillingDocument.objects.filter(
                    pk=original_document_id,
                    status=BillingDocumentStatusChoices.ISSUED,
                ).exists()
            ):
                raise ValidationError(
                    "No se puede modificar el contenido de un documento emitido."
                )
        if (
            self.billing_document_id
            and self.billing_document.status == BillingDocumentStatusChoices.ISSUED
        ):
            raise ValidationError(
                "No se puede modificar el contenido de un documento emitido."
            )

    def save(self, *args, **kwargs):
        self._ensure_document_is_editable()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_document_is_editable()
        return super().delete(*args, **kwargs)


class BillingDocumentLine(IssuedDocumentChildMixin, TimeStampedModel):
    business = models.ForeignKey(
        "core.Business", on_delete=models.PROTECT, related_name="billing_document_lines"
    )
    billing_document = models.ForeignKey(
        BillingDocument, on_delete=models.PROTECT, related_name="lines"
    )
    product_name = models.CharField(max_length=180)
    sku = models.CharField(max_length=80, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.CharField(max_length=20)
    unit_base_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    gross_base_amount = models.DecimalField(max_digits=14, decimal_places=2)
    taxable_base_amount = models.DecimalField(max_digits=14, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    tax_type = models.CharField(max_length=20)
    clave_regimen = models.CharField(max_length=2, null=True, blank=True)
    calificacion_operacion = models.CharField(max_length=2, null=True, blank=True)
    operacion_exenta = models.CharField(max_length=2, null=True, blank=True)
    has_equivalence_surcharge = models.BooleanField(default=False)
    equivalence_surcharge_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)

    class Meta:
        verbose_name = "Línea de documento de facturación"
        verbose_name_plural = "Líneas de documentos de facturación"
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(
                fields=["business", "billing_document"],
                name="idx_billline_bus_document",
            )
        ]

    def clean(self):
        super().clean()
        self.product_name = (self.product_name or "").strip()
        self.sku = (self.sku or "").strip().upper()
        self.unit = (self.unit or "").strip()
        errors = {}
        if (
            self.billing_document_id
            and self.billing_document.business_id != self.business_id
        ):
            errors["billing_document"] = (
                "El documento debe pertenecer al mismo negocio."
            )
        if not self.product_name:
            errors["product_name"] = "El nombre histórico del producto es obligatorio."
        if not self.unit:
            errors["unit"] = "La unidad histórica es obligatoria."
        if errors:
            raise ValidationError(errors)


class BillingTaxBreakdown(IssuedDocumentChildMixin, TimeStampedModel):
    """Aggregate snapshot keyed by the complete fiscal classification."""

    business = models.ForeignKey(
        "core.Business", on_delete=models.PROTECT, related_name="billing_tax_breakdowns"
    )
    billing_document = models.ForeignKey(
        BillingDocument, on_delete=models.PROTECT, related_name="tax_breakdowns"
    )
    tax_type = models.CharField(max_length=20)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    clave_regimen = models.CharField(max_length=2, null=True, blank=True)
    calificacion_operacion = models.CharField(max_length=2, null=True, blank=True)
    operacion_exenta = models.CharField(max_length=2, null=True, blank=True)
    has_equivalence_surcharge = models.BooleanField(default=False)
    equivalence_surcharge_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    taxable_base_amount = models.DecimalField(max_digits=14, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = "Desglose fiscal de facturación"
        verbose_name_plural = "Desgloses fiscales de facturación"
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(
                fields=["business", "billing_document"], name="idx_billtax_bus_document"
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.billing_document_id
            and self.billing_document.business_id != self.business_id
        ):
            raise ValidationError(
                {"billing_document": "El documento debe pertenecer al mismo negocio."}
            )


class BillingDocumentRelation(TimeStampedModel):
    """Historical link from the new document to the original document.

    Once the source document is issued, normal ``save()`` and ``delete()`` calls
    cannot rewrite this history. Bulk queryset operations bypass this guard and
    must not be used for historical fiscal relations.
    """

    business = models.ForeignKey(
        "core.Business",
        on_delete=models.PROTECT,
        related_name="billing_document_relations",
    )
    source_document = models.ForeignKey(
        BillingDocument, on_delete=models.PROTECT, related_name="outgoing_relations"
    )
    target_document = models.ForeignKey(
        BillingDocument, on_delete=models.PROTECT, related_name="incoming_relations"
    )
    relation_type = models.CharField(
        max_length=20, choices=BillingDocumentRelationTypeChoices.choices
    )

    class Meta:
        verbose_name = "Relación entre documentos de facturación"
        verbose_name_plural = "Relaciones entre documentos de facturación"
        constraints = [
            models.CheckConstraint(
                condition=~Q(source_document=models.F("target_document")),
                name="chk_billrel_source_ne_target",
            ),
            models.UniqueConstraint(
                fields=["source_document", "target_document", "relation_type"],
                name="uniq_billrel_source_target_type",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.source_document_id:
            if self.source_document.business_id != self.business_id:
                errors["source_document"] = (
                    "El documento nuevo debe pertenecer al mismo negocio."
                )
        if self.target_document_id:
            if self.target_document.business_id != self.business_id:
                errors["target_document"] = (
                    "El documento original debe pertenecer al mismo negocio."
                )
        if (
            self.source_document_id
            and self.source_document_id == self.target_document_id
        ):
            errors["target_document"] = (
                "Un documento no puede relacionarse consigo mismo."
            )
        if errors:
            raise ValidationError(errors)

    def _ensure_source_is_editable(self):
        if self.pk:
            original_source_id = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("source_document_id", flat=True)
                .first()
            )
            if (
                original_source_id
                and BillingDocument.objects.filter(
                    pk=original_source_id,
                    status=BillingDocumentStatusChoices.ISSUED,
                ).exists()
            ):
                raise ValidationError(
                    "No se puede modificar una relación cuyo documento origen "
                    "ya fue emitido."
                )
        if (
            self.source_document_id
            and self.source_document.status == BillingDocumentStatusChoices.ISSUED
        ):
            raise ValidationError(
                "No se puede modificar una relación cuyo documento origen "
                "ya fue emitido."
            )

    def save(self, *args, **kwargs):
        self._ensure_source_is_editable()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_source_is_editable()
        return super().delete(*args, **kwargs)
