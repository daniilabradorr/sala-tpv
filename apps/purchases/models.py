from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import Business, TimeStampedModel


ZERO_MONEY = Decimal("0.00")
ZERO_QUANTITY = Decimal("0.000")


class PurchaseStatusChoices(models.TextChoices):
    """Estados persistidos de una compra."""

    DRAFT = "draft", "Borrador"
    ORDERED = "ordered", "Pedida"
    PARTIALLY_RECEIVED = "partially_received", "Recibida parcialmente"
    RECEIVED = "received", "Recibida"
    CANCELLED = "cancelled", "Cancelada"


class Supplier(TimeStampedModel):
    """Proveedor perteneciente a un negocio."""

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="suppliers"
    )
    name = models.CharField("Nombre comercial", max_length=180)
    legal_name = models.CharField("Razón social", max_length=180, blank=True)
    tax_identifier = models.CharField("Identificador fiscal", max_length=30, blank=True)
    email = models.EmailField("Correo electrónico", blank=True)
    phone = models.CharField("Teléfono", max_length=30, blank=True)
    address = models.TextField("Dirección", blank=True)
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"
        ordering = ["name", "pk"]
        indexes = [
            models.Index(
                fields=["business", "is_active", "name"],
                name="idx_supplier_bus_active_name",
            )
        ]

    def __str__(self):
        return self.name

    def _normalize_fields(self):
        self.name = (self.name or "").strip()
        self.legal_name = (self.legal_name or "").strip()
        self.tax_identifier = (self.tax_identifier or "").strip().upper()
        self.email = (self.email or "").strip().lower()
        self.phone = (self.phone or "").strip()
        self.address = (self.address or "").strip()

    def clean(self):
        super().clean()
        self._normalize_fields()
        if not self.name:
            raise ValidationError({"name": "El nombre comercial es obligatorio."})

    def save(self, *args, **kwargs):
        self._normalize_fields()
        self.full_clean()
        return super().save(*args, **kwargs)


class Purchase(TimeStampedModel):
    """Cabecera de una compra; no produce efectos sobre el inventario."""

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="purchases"
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.PROTECT, related_name="purchases"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchases"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchases_created",
    )
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=PurchaseStatusChoices.choices,
        default=PurchaseStatusChoices.DRAFT,
        db_index=True,
    )
    reference = models.CharField("Referencia", max_length=120, blank=True)
    notes = models.TextField("Notas", blank=True)
    ordered_at = models.DateTimeField("Fecha del pedido", null=True, blank=True)
    subtotal_amount = models.DecimalField(
        "Subtotal", max_digits=14, decimal_places=2, default=ZERO_MONEY, editable=False
    )
    tax_amount = models.DecimalField(
        "Impuestos", max_digits=14, decimal_places=2, default=ZERO_MONEY, editable=False
    )
    total_amount = models.DecimalField(
        "Total", max_digits=14, decimal_places=2, default=ZERO_MONEY, editable=False
    )

    class Meta:
        verbose_name = "Compra"
        verbose_name_plural = "Compras"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(subtotal_amount__gte=ZERO_MONEY),
                name="chk_purchase_subtotal_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(tax_amount__gte=ZERO_MONEY),
                name="chk_purchase_tax_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=ZERO_MONEY),
                name="chk_purchase_total_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(total_amount=F("subtotal_amount") + F("tax_amount")),
                name="chk_purchase_total_sum",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status__in=[
                            PurchaseStatusChoices.DRAFT,
                            PurchaseStatusChoices.CANCELLED,
                        ]
                    )
                    | Q(ordered_at__isnull=False)
                ),
                name="chk_purchase_ordered_has_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "store", "status"],
                name="idx_purchase_bus_store_status",
            ),
            models.Index(
                fields=["business", "supplier", "status"],
                name="idx_purchase_bus_sup_status",
            ),
            models.Index(
                fields=["business", "created_at"], name="idx_purchase_bus_created"
            ),
        ]

    def __str__(self):
        return f"Compra {self.pk or 'nueva'} · {self.supplier}"

    @property
    def is_draft(self):
        return self.status == PurchaseStatusChoices.DRAFT

    @property
    def is_ordered(self):
        return self.status == PurchaseStatusChoices.ORDERED

    @property
    def is_partially_received(self):
        return self.status == PurchaseStatusChoices.PARTIALLY_RECEIVED

    @property
    def is_received(self):
        return self.status == PurchaseStatusChoices.RECEIVED

    @property
    def is_cancelled(self):
        return self.status == PurchaseStatusChoices.CANCELLED

    @property
    def is_editable(self):
        return self.is_draft

    def clean(self):
        super().clean()
        errors = {}
        self.reference = (self.reference or "").strip()
        self.notes = (self.notes or "").strip()

        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = "La tienda debe pertenecer al mismo negocio."
        if self.supplier_id and self.business_id:
            if self.supplier.business_id != self.business_id:
                errors["supplier"] = "El proveedor debe pertenecer al mismo negocio."
        if self.created_by_id and self.business_id:
            if (
                not self.created_by.is_superuser
                and self.created_by.business_id != self.business_id
            ):
                errors["created_by"] = "El usuario debe pertenecer al mismo negocio."
        amounts = {
            "subtotal_amount": self.subtotal_amount,
            "tax_amount": self.tax_amount,
            "total_amount": self.total_amount,
        }
        for field, value in amounts.items():
            if value is not None and value < ZERO_MONEY:
                errors[field] = "El importe no puede ser negativo."
        if all(value is not None for value in amounts.values()):
            if self.total_amount != self.subtotal_amount + self.tax_amount:
                errors["total_amount"] = "El total debe ser subtotal más impuestos."
        if (
            self.status
            in {
                PurchaseStatusChoices.ORDERED,
                PurchaseStatusChoices.PARTIALLY_RECEIVED,
                PurchaseStatusChoices.RECEIVED,
            }
            and not self.ordered_at
        ):
            errors["ordered_at"] = "Este estado requiere fecha de pedido."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PurchaseLine(TimeStampedModel):
    """Línea comercial con una fotografía histórica del producto comprado."""

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="purchase_lines"
    )
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="purchase_lines"
    )
    product_name = models.CharField("Nombre del producto", max_length=180)
    sku = models.CharField("SKU", max_length=80, blank=True)
    unit = models.CharField("Unidad", max_length=20)
    quantity_ordered = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_received = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=ZERO_QUANTITY,
        editable=False,
    )
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO_MONEY)
    line_subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO_MONEY, editable=False
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO_MONEY, editable=False
    )
    line_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO_MONEY, editable=False
    )

    class Meta:
        verbose_name = "Línea de compra"
        verbose_name_plural = "Líneas de compra"
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_ordered__gt=ZERO_QUANTITY),
                name="chk_purchline_qty_ordered_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(quantity_received__gte=ZERO_QUANTITY),
                name="chk_purchline_qty_received_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(quantity_received__lte=F("quantity_ordered")),
                name="chk_purchline_received_lte_ordered",
            ),
            models.CheckConstraint(
                condition=Q(unit_cost__gte=0), name="chk_purchline_cost_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(tax_rate__gte=0), name="chk_purchline_tax_rate_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(line_subtotal__gte=0), name="chk_purchline_subtotal_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(tax_amount__gte=0), name="chk_purchline_tax_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(line_total__gte=0), name="chk_purchline_total_gte_0"
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "purchase"], name="idx_purchline_bus_purchase"
            ),
            models.Index(
                fields=["business", "product"], name="idx_purchline_bus_product"
            ),
        ]

    def __str__(self):
        return f"{self.product_name} × {self.quantity_ordered}"

    def clean(self):
        super().clean()
        errors = {}
        self.product_name = (self.product_name or "").strip()
        self.sku = (self.sku or "").strip().upper()
        self.unit = (self.unit or "").strip()
        if self.purchase_id and self.business_id:
            if self.purchase.business_id != self.business_id:
                errors["purchase"] = "La compra debe pertenecer al mismo negocio."
        if self.product_id and self.business_id:
            if self.product.business_id != self.business_id:
                errors["product"] = "El producto debe pertenecer al mismo negocio."
        if not self.product_name:
            errors["product_name"] = "El nombre histórico del producto es obligatorio."
        if not self.unit:
            errors["unit"] = "La unidad histórica es obligatoria."
        if self.quantity_ordered is None or self.quantity_ordered <= ZERO_QUANTITY:
            errors["quantity_ordered"] = "La cantidad pedida debe ser mayor que cero."
        if self.quantity_received is not None:
            if self.quantity_received < ZERO_QUANTITY:
                errors["quantity_received"] = (
                    "La cantidad recibida no puede ser negativa."
                )
            elif (
                self.quantity_ordered is not None
                and self.quantity_received > self.quantity_ordered
            ):
                errors["quantity_received"] = (
                    "La cantidad recibida no puede superar la pedida."
                )
        for field in (
            "unit_cost",
            "tax_rate",
            "line_subtotal",
            "tax_amount",
            "line_total",
        ):
            value = getattr(self, field)
            if value is not None and value < ZERO_MONEY:
                errors[field] = "El valor no puede ser negativo."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PurchaseReceipt(TimeStampedModel):
    """Evento inmutable de recepción comercial y, cuando aplica, de stock."""

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="purchase_receipts"
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.PROTECT, related_name="purchase_receipts"
    )
    purchase = models.ForeignKey(
        Purchase, on_delete=models.PROTECT, related_name="receipts"
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_receipts_received",
    )
    received_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)
    idempotency_key = models.UUIDField()
    idempotency_fingerprint = models.CharField(max_length=64)

    class Meta:
        verbose_name = "Recepción de compra"
        verbose_name_plural = "Recepciones de compra"
        ordering = ["-received_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "idempotency_key"],
                name="uniq_purchreceipt_bus_idem_key",
            )
        ]
        indexes = [
            models.Index(
                fields=["business", "purchase", "received_at"],
                name="idx_purchreceipt_bus_purchase",
            ),
            models.Index(
                fields=["business", "store", "received_at"],
                name="idx_purchreceipt_bus_store",
            ),
        ]

    def __str__(self):
        return f"Recepción {self.pk or 'nueva'} · {self.purchase}"

    def clean(self):
        super().clean()
        errors = {}
        self.notes = (self.notes or "").strip()
        self.idempotency_fingerprint = (
            (self.idempotency_fingerprint or "").strip().lower()
        )
        if self.purchase_id and self.business_id:
            if self.purchase.business_id != self.business_id:
                errors["purchase"] = "La compra debe pertenecer al mismo negocio."
            if self.store_id and self.purchase.store_id != self.store_id:
                errors["store"] = (
                    "La recepción debe pertenecer a la tienda de la compra."
                )
            if self.purchase.status not in {
                PurchaseStatusChoices.ORDERED,
                PurchaseStatusChoices.PARTIALLY_RECEIVED,
            }:
                errors["purchase"] = (
                    "Solo se pueden recibir compras pedidas o parcialmente recibidas."
                )
        if (
            self.store_id
            and self.business_id
            and self.store.business_id != self.business_id
        ):
            errors["store"] = "La tienda debe pertenecer al mismo negocio."
        if self.received_by_id and self.business_id:
            if (
                not self.received_by.is_superuser
                and self.received_by.business_id != self.business_id
            ):
                errors["received_by"] = "El usuario debe pertenecer al mismo negocio."
        fingerprint = self.idempotency_fingerprint
        if len(fingerprint) != 64 or not set(fingerprint).issubset(
            set("0123456789abcdef")
        ):
            errors["idempotency_fingerprint"] = (
                "El fingerprint SHA-256 debe contener 64 caracteres hexadecimales."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PurchaseReceiptLine(TimeStampedModel):
    """Cantidad de una línea de compra incluida en una recepción concreta."""

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="purchase_receipt_lines"
    )
    receipt = models.ForeignKey(
        PurchaseReceipt, on_delete=models.CASCADE, related_name="lines"
    )
    purchase_line = models.ForeignKey(
        PurchaseLine, on_delete=models.PROTECT, related_name="receipt_lines"
    )
    quantity_received = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        verbose_name = "Línea de recepción de compra"
        verbose_name_plural = "Líneas de recepción de compra"
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_received__gt=ZERO_QUANTITY),
                name="chk_purchreceiptline_qty_gt_0",
            ),
            models.UniqueConstraint(
                fields=["receipt", "purchase_line"],
                name="uniq_purchreceiptline_receipt_line",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "receipt"], name="idx_prec_line_bus_receipt"
            ),
            models.Index(
                fields=["business", "purchase_line"],
                name="idx_purchreceiptline_bus_line",
            ),
        ]

    def __str__(self):
        return f"{self.purchase_line} × {self.quantity_received}"

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.receipt_id
            and self.business_id
            and self.receipt.business_id != self.business_id
        ):
            errors["receipt"] = "La recepción debe pertenecer al mismo negocio."
        if self.purchase_line_id and self.business_id:
            if self.purchase_line.business_id != self.business_id:
                errors["purchase_line"] = (
                    "La línea de compra debe pertenecer al mismo negocio."
                )
        if self.receipt_id and self.purchase_line_id:
            if self.receipt.purchase_id != self.purchase_line.purchase_id:
                errors["purchase_line"] = (
                    "La línea debe pertenecer a la compra de la recepción."
                )
        if self.quantity_received is None or self.quantity_received <= ZERO_QUANTITY:
            errors["quantity_received"] = (
                "La cantidad recibida debe ser mayor que cero."
            )
        elif (
            self.purchase_line_id
            and self.quantity_received > self.purchase_line.quantity_ordered
        ):
            errors["quantity_received"] = (
                "La cantidad de esta recepción no puede superar la pedida."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
