from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import Business, TimeStampedModel
from apps.stores.models import Store


class SaleStatusChoices(models.TextChoices):
    """Estados posibles de una venta."""

    DRAFT = "draft", "Borrador"
    OPEN = "open", "Abierta"
    COMPLETED = "completed", "Completada"
    CANCELLED = "cancelled", "Cancelada"
    RETURNED = "returned", "Devuelta"


class RequestedDocumentTypeChoices(models.TextChoices):
    """Documento que solicita el cliente al realizar la venta."""

    TICKET = "ticket", "Ticket"
    INVOICE = "invoice", "Factura"
    NONE = "none", "Sin documento solicitado"


class PaymentStatusChoices(models.TextChoices):
    """Estado económico de la venta."""

    UNPAID = "unpaid", "Pendiente de pago"
    PARTIAL = "partial", "Pagada parcialmente"
    PAID = "paid", "Pagada"
    REFUNDED = "refunded", "Reembolsada"


class Sale(TimeStampedModel):
    """
    Cabecera de una operación comercial.

    Sale representa la venta antes de convertirse en un documento fiscal.

    IMPORTANTE:
    - Sale no es una factura.
    - Sale no envía directamente información a VeriFactu.
    - Las líneas comerciales vivirán en SaleLine.
    - Los cobros vivirán en Payment.
    - El documento fiscal se generará posteriormente desde billing.
    - Los importes guardados son una fotografía calculada de la venta.
    """

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="sales",
    )

    store = models.ForeignKey(
        Store,
        verbose_name="Tienda",
        on_delete=models.PROTECT,
        related_name="sales",
    )

    cash_register = models.ForeignKey(
        "cash_register.CashRegister",
        verbose_name="Caja",
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
        help_text=(
            "Caja desde la que se realiza la venta. "
            "Puede quedar vacía cuando el negocio no exige trabajar con caja."
        ),
    )

    cash_session = models.ForeignKey(
        "cash_register.CashSession",
        verbose_name="Sesión de caja",
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
        help_text=(
            "Sesión de caja asociada a la venta. "
            "Será obligatoria cuando la configuración exija caja abierta."
        ),
    )

    customer = models.ForeignKey(
        "customers.Customer",
        verbose_name="Cliente",
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
        help_text=(
            "Cliente asociado a la venta. "
            "Es opcional para un ticket normal, pero será necesario "
            "para determinados documentos fiscales."
        ),
    )

    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Abierta por",
        on_delete=models.PROTECT,
        related_name="sales_opened",
    )

    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Cerrada por",
        on_delete=models.PROTECT,
        related_name="sales_closed",
        null=True,
        blank=True,
    )

    status = models.CharField(
        "Estado",
        max_length=20,
        choices=SaleStatusChoices.choices,
        default=SaleStatusChoices.DRAFT,
        db_index=True,
    )

    document_type_requested = models.CharField(
        "Documento solicitado",
        max_length=20,
        choices=RequestedDocumentTypeChoices.choices,
        default=RequestedDocumentTypeChoices.TICKET,
        help_text=(
            "Indica si el cliente solicita ticket, factura o ningún "
            "documento concreto. Billing decidirá posteriormente "
            "el tipo fiscal definitivo."
        ),
    )

    payment_status = models.CharField(
        "Estado del pago",
        max_length=20,
        choices=PaymentStatusChoices.choices,
        default=PaymentStatusChoices.UNPAID,
        db_index=True,
    )

    subtotal_amount = models.DecimalField(
        "Subtotal",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Suma de bases antes de descuentos e impuestos.",
    )

    discount_amount = models.DecimalField(
        "Descuento total",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Suma de los descuentos aplicados a la venta.",
    )

    tax_amount = models.DecimalField(
        "Impuestos",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Suma de impuestos calculados en las líneas.",
    )

    total_amount = models.DecimalField(
        "Total",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Importe final que debe pagar el cliente.",
    )

    pending_amount = models.DecimalField(
        "Importe pendiente",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Importe que todavía queda por cobrar.",
    )

    completed_at = models.DateTimeField(
        "Fecha de finalización",
        null=True,
        blank=True,
        db_index=True,
        help_text="Fecha y hora en la que la venta quedó completada.",
    )

    class Meta:
        verbose_name = "Venta"
        verbose_name_plural = "Ventas"
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.CheckConstraint(
                condition=Q(subtotal_amount__gte=Decimal("0.00")),
                name="chk_sale_subtotal_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount__gte=Decimal("0.00")),
                name="chk_sale_discount_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(tax_amount__gte=Decimal("0.00")),
                name="chk_sale_tax_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=Decimal("0.00")),
                name="chk_sale_total_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(pending_amount__gte=Decimal("0.00")),
                name="chk_sale_pending_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(pending_amount__lte=models.F("total_amount")),
                name="chk_sale_pending_lte_total",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status=SaleStatusChoices.COMPLETED)
                    | Q(completed_at__isnull=False)
                ),
                name="chk_sale_completed_has_date",
            ),
        ]

        indexes = [
            models.Index(
                fields=["business", "store", "status"],
                name="idx_sale_bus_store_status",
            ),
            models.Index(
                fields=["business", "payment_status"],
                name="idx_sale_bus_payment",
            ),
            models.Index(
                fields=["business", "created_at"],
                name="idx_sale_bus_created",
            ),
            models.Index(
                fields=["business", "customer"],
                name="idx_sale_bus_customer",
            ),
        ]

    def __str__(self):
        return f"Venta {self.pk or 'nueva'} · {self.store}"

    @property
    def is_draft(self):
        return self.status == SaleStatusChoices.DRAFT

    @property
    def is_open(self):
        return self.status == SaleStatusChoices.OPEN

    @property
    def is_completed(self):
        return self.status == SaleStatusChoices.COMPLETED

    @property
    def is_cancelled(self):
        return self.status == SaleStatusChoices.CANCELLED

    @property
    def is_returned(self):
        return self.status == SaleStatusChoices.RETURNED

    @property
    def is_editable(self):
        """
        Una venta solo puede modificar sus líneas mientras está
        en borrador o abierta.
        """
        return self.status in {
            SaleStatusChoices.DRAFT,
            SaleStatusChoices.OPEN,
        }

    def clean(self):
        """
        Protege las relaciones y las reglas básicas de la cabecera.

        La lógica completa de apertura, cálculo, cierre y cancelación
        debe vivir en services.py.
        """
        super().clean()

        errors = {}

        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = (
                    "La tienda debe pertenecer al mismo negocio que la venta."
                )

        if self.customer_id and self.business_id:
            if self.customer.business_id != self.business_id:
                errors["customer"] = (
                    "El cliente debe pertenecer al mismo negocio que la venta."
                )

        if self.opened_by_id and self.business_id:
            if (
                not self.opened_by.is_superuser
                and self.opened_by.business_id != self.business_id
            ):
                errors["opened_by"] = (
                    "El usuario que abre la venta debe pertenecer al mismo negocio."
                )

        if self.closed_by_id and self.business_id:
            if (
                not self.closed_by.is_superuser
                and self.closed_by.business_id != self.business_id
            ):
                errors["closed_by"] = (
                    "El usuario que cierra la venta debe pertenecer al mismo negocio."
                )

        if self.cash_register_id:
            if self.cash_register.business_id != self.business_id:
                errors["cash_register"] = (
                    "La caja debe pertenecer al mismo negocio que la venta."
                )

            if self.cash_register.store_id != self.store_id:
                errors["cash_register"] = (
                    "La caja debe pertenecer a la misma tienda que la venta."
                )

        if self.cash_session_id:
            if self.cash_session.business_id != self.business_id:
                errors["cash_session"] = (
                    "La sesión de caja debe pertenecer al mismo negocio."
                )

            if self.cash_session.store_id != self.store_id:
                errors["cash_session"] = (
                    "La sesión de caja debe pertenecer a la misma tienda."
                )

            if (
                self.cash_register_id
                and self.cash_session.cash_register_id != self.cash_register_id
            ):
                errors["cash_session"] = (
                    "La sesión seleccionada no pertenece a la caja de la venta."
                )

        if self.status == SaleStatusChoices.COMPLETED:
            if not self.closed_by_id:
                errors["closed_by"] = (
                    "Una venta completada debe indicar qué usuario la cerró."
                )

            if not self.completed_at:
                errors["completed_at"] = (
                    "Una venta completada debe tener fecha de finalización."
                )

        if (
            self.document_type_requested == RequestedDocumentTypeChoices.INVOICE
            and not self.customer_id
        ):
            errors["customer"] = (
                "Una venta que solicita factura debe tener un cliente asociado."
            )

        if self.discount_amount > self.subtotal_amount:
            errors["discount_amount"] = (
                "El descuento total no puede superar el subtotal de la venta."
            )

        expected_total = self.subtotal_amount - self.discount_amount + self.tax_amount

        if self.total_amount != expected_total:
            errors["total_amount"] = (
                "El total debe ser subtotal menos descuentos más impuestos."
            )

        if self.pending_amount > self.total_amount:
            errors["pending_amount"] = (
                "El importe pendiente no puede superar el total de la venta."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SaleLine(TimeStampedModel):
    """
    Línea comercial de una venta.

    Guarda una fotografía histórica del producto vendido.

    IMPORTANTE:
    - Product contiene la configuración actual.
    - SaleLine conserva nombre, SKU, precio, unidad e impuesto aplicados.
    - Modificar Product posteriormente no debe cambiar una venta anterior.
    - Los cálculos y la creación de líneas deben realizarse desde services.py.
    """

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="sale_lines",
    )

    sale = models.ForeignKey(
        Sale,
        verbose_name="Venta",
        on_delete=models.CASCADE,
        related_name="lines",
    )

    product = models.ForeignKey(
        "catalog.Product",
        verbose_name="Producto original",
        on_delete=models.SET_NULL,
        related_name="sale_lines",
        null=True,
        blank=True,
        help_text=(
            "Producto del catálogo que originó la línea. "
            "Los datos históricos se conservan aunque esta relación desaparezca."
        ),
    )

    product_name = models.CharField(
        "Nombre del producto",
        max_length=180,
        help_text="Nombre congelado en el momento de la venta.",
    )

    sku = models.CharField(
        "SKU",
        max_length=80,
        blank=True,
        help_text="SKU congelado en el momento de la venta.",
    )

    quantity = models.DecimalField(
        "Cantidad",
        max_digits=14,
        decimal_places=3,
        help_text="Cantidad vendida. Permite unidades, peso, horas o servicios.",
    )

    unit = models.CharField(
        "Unidad",
        max_length=20,
        help_text="Unidad congelada: ud, kg, h, servicio, etc.",
    )

    unit_base_price = models.DecimalField(
        "Precio unitario sin IVA",
        max_digits=12,
        decimal_places=2,
        help_text="Precio base unitario sin impuestos aplicado en la venta.",
    )

    discount_amount = models.DecimalField(
        "Descuento de la línea",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Importe total descontado en esta línea.",
    )

    tax_rate = models.DecimalField(
        "Tipo impositivo",
        max_digits=5,
        decimal_places=2,
        help_text="Porcentaje de impuesto congelado en la venta.",
    )

    tax_amount = models.DecimalField(
        "Cuota de impuesto",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Importe de impuesto calculado para la línea.",
    )

    line_total = models.DecimalField(
        "Total de la línea",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Importe final de la línea con descuentos e impuestos.",
    )

    class Meta:
        verbose_name = "Línea de venta"
        verbose_name_plural = "Líneas de venta"
        ordering = ["created_at", "pk"]

        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=Decimal("0.000")),
                name="chk_saleline_quantity_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(unit_base_price__gte=Decimal("0.00")),
                name="chk_saleline_price_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount__gte=Decimal("0.00")),
                name="chk_saleline_discount_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(tax_rate__gte=Decimal("0.00")),
                name="chk_saleline_tax_rate_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(tax_amount__gte=Decimal("0.00")),
                name="chk_saleline_tax_amount_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(line_total__gte=Decimal("0.00")),
                name="chk_saleline_total_gte_0",
            ),
        ]

        indexes = [
            models.Index(
                fields=["business", "sale"],
                name="idx_saleline_bus_sale",
            ),
            models.Index(
                fields=["business", "product"],
                name="idx_saleline_bus_product",
            ),
        ]

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"

    @property
    def gross_base_amount(self):
        """
        Base bruta antes de descuento.

        No se redondea aquí porque la política de redondeo fiscal
        deberá definirse de forma centralizada en services.py.
        """
        return self.unit_base_price * self.quantity

    @property
    def taxable_base_amount(self):
        """Base de la línea después del descuento."""
        return self.gross_base_amount - self.discount_amount

    def clean(self):
        """
        Protege las relaciones y valores esenciales.

        El cálculo definitivo y su redondeo no deben implementarse aquí.
        """
        super().clean()

        errors = {}

        self.product_name = (self.product_name or "").strip()
        self.sku = (self.sku or "").strip().upper()
        self.unit = (self.unit or "").strip()

        if self.sale_id and self.business_id:
            if self.sale.business_id != self.business_id:
                errors["sale"] = (
                    "La venta debe pertenecer al mismo negocio que la línea."
                )

        if self.product_id and self.business_id:
            if self.product.business_id != self.business_id:
                errors["product"] = (
                    "El producto debe pertenecer al mismo negocio que la línea."
                )

        if not self.product_name:
            errors["product_name"] = (
                "La línea debe conservar el nombre histórico del producto."
            )

        if not self.unit:
            errors["unit"] = "La unidad de la línea es obligatoria."

        if self.quantity is None or self.quantity <= Decimal("0.000"):
            errors["quantity"] = "La cantidad debe ser mayor que cero."

        if self.unit_base_price is not None and self.unit_base_price < Decimal("0.00"):
            errors["unit_base_price"] = "El precio unitario no puede ser negativo."

        if self.discount_amount is not None and self.discount_amount < Decimal("0.00"):
            errors["discount_amount"] = (
                "El descuento de la línea no puede ser negativo."
            )

        if (
            self.quantity is not None
            and self.unit_base_price is not None
            and self.discount_amount is not None
        ):
            gross_amount = self.unit_base_price * self.quantity

            if self.discount_amount > gross_amount:
                errors["discount_amount"] = (
                    "El descuento no puede superar la base bruta de la línea."
                )

        if self.tax_rate is not None and self.tax_rate < Decimal("0.00"):
            errors["tax_rate"] = "El tipo impositivo no puede ser negativo."

        if self.tax_amount is not None and self.tax_amount < Decimal("0.00"):
            errors["tax_amount"] = "La cuota del impuesto no puede ser negativa."

        if self.line_total is not None and self.line_total < Decimal("0.00"):
            errors["line_total"] = "El total de la línea no puede ser negativo."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SaleReturnStatusChoices(models.TextChoices):
    """Estados posibles de una devolución."""

    DRAFT = "draft", "Borrador"
    COMPLETED = "completed", "Completada"
    CANCELLED = "cancelled", "Cancelada"


class SaleReturn(TimeStampedModel):
    """
    Cabecera de una devolución de venta.

    IMPORTANTE:
    - Toda devolución debe partir de una venta original.
    - Completarla podrá generar entrada de stock.
    - Payments gestionará el reembolso económico.
    - Billing deberá generar el documento fiscal rectificativo.
    """

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="sale_returns",
    )

    store = models.ForeignKey(
        Store,
        verbose_name="Tienda",
        on_delete=models.PROTECT,
        related_name="sale_returns",
    )

    original_sale = models.ForeignKey(
        Sale,
        verbose_name="Venta original",
        on_delete=models.PROTECT,
        related_name="returns",
        help_text="Venta sobre la que se realiza la devolución.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Creada por",
        on_delete=models.PROTECT,
        related_name="sale_returns_created",
    )

    reason = models.TextField(
        "Motivo",
        help_text=(
            "Motivo comercial de la devolución. "
            "Será necesario para la trazabilidad y la rectificativa."
        ),
    )

    status = models.CharField(
        "Estado",
        max_length=20,
        choices=SaleReturnStatusChoices.choices,
        default=SaleReturnStatusChoices.DRAFT,
        db_index=True,
    )

    total_amount = models.DecimalField(
        "Total devuelto",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Importe total de las líneas devueltas.",
    )

    class Meta:
        verbose_name = "Devolución de venta"
        verbose_name_plural = "Devoluciones de venta"
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.CheckConstraint(
                condition=Q(total_amount__gte=Decimal("0.00")),
                name="chk_salereturn_total_gte_0",
            ),
        ]

        indexes = [
            models.Index(
                fields=["business", "store", "status"],
                name="idx_salereturn_bus_store",
            ),
            models.Index(
                fields=["business", "original_sale"],
                name="idx_salereturn_bus_sale",
            ),
            models.Index(
                fields=["business", "created_at"],
                name="idx_salereturn_bus_created",
            ),
        ]

    def __str__(self):
        return (
            f"Devolución {self.pk or 'nueva'} de venta {self.original_sale_id or '-'}"
        )

    @property
    def is_draft(self):
        return self.status == SaleReturnStatusChoices.DRAFT

    @property
    def is_completed(self):
        return self.status == SaleReturnStatusChoices.COMPLETED

    @property
    def is_cancelled(self):
        return self.status == SaleReturnStatusChoices.CANCELLED

    @property
    def is_editable(self):
        return self.status == SaleReturnStatusChoices.DRAFT

    def clean(self):
        """Valida la coherencia básica de la devolución."""
        super().clean()

        errors = {}

        self.reason = (self.reason or "").strip()

        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = (
                    "La tienda debe pertenecer al mismo negocio que la devolución."
                )

        if self.original_sale_id and self.business_id:
            if self.original_sale.business_id != self.business_id:
                errors["original_sale"] = (
                    "La venta original debe pertenecer al mismo negocio."
                )

            if self.store_id and self.original_sale.store_id != self.store_id:
                errors["store"] = (
                    "La devolución debe realizarse en la tienda de la venta original."
                )

        if self.created_by_id and self.business_id:
            if (
                not self.created_by.is_superuser
                and self.created_by.business_id != self.business_id
            ):
                errors["created_by"] = (
                    "El usuario debe pertenecer al mismo negocio que la devolución."
                )

        if not self.reason:
            errors["reason"] = "Debes indicar el motivo de la devolución."

        if self.total_amount is not None and self.total_amount < Decimal("0.00"):
            errors["total_amount"] = "El importe total devuelto no puede ser negativo."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SaleReturnLine(TimeStampedModel):
    """
    Línea concreta de una devolución.

    Relaciona la cantidad devuelta con la línea original de venta.

    El control acumulado de cantidades debe hacerse desde services.py
    dentro de una transacción, porque pueden existir varias devoluciones.
    """

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="sale_return_lines",
    )

    return_doc = models.ForeignKey(
        SaleReturn,
        verbose_name="Devolución",
        on_delete=models.CASCADE,
        related_name="lines",
    )

    original_line = models.ForeignKey(
        SaleLine,
        verbose_name="Línea original",
        on_delete=models.PROTECT,
        related_name="return_lines",
    )

    quantity = models.DecimalField(
        "Cantidad devuelta",
        max_digits=14,
        decimal_places=3,
        help_text="Cantidad devuelta de la línea original.",
    )

    amount = models.DecimalField(
        "Importe devuelto",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Importe económico correspondiente a la cantidad devuelta.",
    )

    class Meta:
        verbose_name = "Línea de devolución"
        verbose_name_plural = "Líneas de devolución"
        ordering = ["created_at", "pk"]

        constraints = [
            models.UniqueConstraint(
                fields=["return_doc", "original_line"],
                name="uniq_return_original_line",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=Decimal("0.000")),
                name="chk_returnline_quantity_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(amount__gte=Decimal("0.00")),
                name="chk_returnline_amount_gte_0",
            ),
        ]

        indexes = [
            models.Index(
                fields=["business", "return_doc"],
                name="idx_returnline_bus_return",
            ),
            models.Index(
                fields=["business", "original_line"],
                name="idx_returnline_bus_line",
            ),
        ]

    def __str__(self):
        return f"Devolución de {self.original_line.product_name} × {self.quantity}"

    def clean(self):
        """
        Valida la relación con la devolución y la venta original.

        No comprueba aquí la suma de todas las devoluciones anteriores.
        Esa validación requiere bloqueo transaccional en services.py.
        """
        super().clean()

        errors = {}

        if self.return_doc_id and self.business_id:
            if self.return_doc.business_id != self.business_id:
                errors["return_doc"] = (
                    "La devolución debe pertenecer al mismo negocio que la línea."
                )

        if self.original_line_id and self.business_id:
            if self.original_line.business_id != self.business_id:
                errors["original_line"] = (
                    "La línea original debe pertenecer al mismo negocio."
                )

        if self.return_doc_id and self.original_line_id:
            if self.original_line.sale_id != self.return_doc.original_sale_id:
                errors["original_line"] = (
                    "La línea seleccionada no pertenece a la venta original "
                    "de esta devolución."
                )

        if self.quantity is None or self.quantity <= Decimal("0.000"):
            errors["quantity"] = "La cantidad devuelta debe ser mayor que cero."

        if (
            self.quantity is not None
            and self.original_line_id
            and self.quantity > self.original_line.quantity
        ):
            errors["quantity"] = (
                "La cantidad devuelta no puede superar la cantidad "
                "vendida en la línea original."
            )

        if self.amount is not None and self.amount < Decimal("0.00"):
            errors["amount"] = "El importe devuelto no puede ser negativo."

        if (
            self.amount is not None
            and self.original_line_id
            and self.amount > self.original_line.line_total
        ):
            errors["amount"] = (
                "El importe devuelto no puede superar el total de la línea original."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
