import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.models import Business, TimeStampedModel
from apps.stores.models import Store


class InventoryItem(TimeStampedModel):
    """
    Stock actual de un producto dentro de una tienda concreta.

    IMPORTANTE:
    - Product define el producto vendible.
    - InventoryItem define cuánto stock real hay de ese producto.
    - Un mismo producto puede tener stock distinto por tienda.
    - No se debe crear stock para servicios.
    - No se debe crear stock para productos con track_stock=False.
    """

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="inventory_items",
    )

    store = models.ForeignKey(
        Store,
        verbose_name="Tienda",
        on_delete=models.PROTECT,
        related_name="inventory_items",
    )

    product = models.ForeignKey(
        Product,
        verbose_name="Producto",
        on_delete=models.PROTECT,
        related_name="inventory_items",
    )

    current_stock = models.DecimalField(
        "Stock actual",
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Cantidad física actual disponible en tienda o almacén.",
    )

    reserved_stock = models.DecimalField(
        "Stock reservado",
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Cantidad reservada para pedidos pendientes, si aplica.",
    )

    minimum_stock = models.DecimalField(
        "Stock mínimo",
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Cantidad mínima recomendada antes de avisar reposición.",
    )

    maximum_stock = models.DecimalField(
        "Stock máximo",
        max_digits=14,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Cantidad máxima recomendada. Opcional.",
    )

    location = models.CharField(
        "Ubicación interna",
        max_length=120,
        blank=True,
        help_text="Ejemplo: almacén, estantería, cámara, pasillo, etc.",
    )

    is_active = models.BooleanField(
        "Activo",
        default=True,
        help_text="Permite desactivar el control de stock sin borrar histórico.",
    )

    class Meta:
        verbose_name = "Stock de producto"
        verbose_name_plural = "Stock de productos"
        ordering = ["business", "store", "product__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "store", "product"],
                name="uniq_invitem_bus_store_prod",
            ),
            models.CheckConstraint(
                condition=Q(reserved_stock__gte=0),
                name="chk_invitem_res_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(minimum_stock__gte=0),
                name="chk_invitem_min_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(maximum_stock__isnull=True) | Q(maximum_stock__gte=0),
                name="chk_invitem_max_gte_0",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "store", "is_active"],
                name="idx_invitem_bus_store",
            ),
            models.Index(
                fields=["business", "product"],
                name="idx_invitem_bus_prod",
            ),
            models.Index(
                fields=["business", "current_stock"],
                name="idx_invitem_bus_stock",
            ),
        ]

    def __str__(self):
        return f"{self.product} - {self.store} ({self.current_stock})"

    @property
    def available_stock(self):
        """
        Stock disponible real para venta.

        current_stock = stock físico
        reserved_stock = stock apartado/reservado
        """
        return self.current_stock - self.reserved_stock

    @property
    def needs_restock(self):
        """
        Indica si el producto está por debajo del mínimo configurado.
        """
        return self.available_stock <= self.minimum_stock

    def clean(self):
        """
        Validaciones de coherencia del stock actual.
        """
        super().clean()

        errors = {}

        if self.product_id and self.business_id:
            if self.product.business_id != self.business_id:
                errors["product"] = "El producto debe pertenecer al mismo negocio."

        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = "La tienda debe pertenecer al mismo negocio."

        if self.product_id:
            if self.product.is_service:
                errors["product"] = "No se puede controlar stock de un servicio."

            if not self.product.track_stock:
                errors["product"] = (
                    "No se puede crear inventario para un producto que no controla stock."
                )

        if self.reserved_stock is not None and self.reserved_stock < Decimal("0.000"):
            errors["reserved_stock"] = "El stock reservado no puede ser negativo."

        if self.minimum_stock is not None and self.minimum_stock < Decimal("0.000"):
            errors["minimum_stock"] = "El stock mínimo no puede ser negativo."

        if self.maximum_stock is not None and self.maximum_stock < Decimal("0.000"):
            errors["maximum_stock"] = "El stock máximo no puede ser negativo."

        if (
            self.maximum_stock is not None
            and self.minimum_stock is not None
            and self.maximum_stock < self.minimum_stock
        ):
            errors["maximum_stock"] = (
                "El stock máximo no puede ser menor que el stock mínimo."
            )

        if self.location:
            self.location = self.location.strip()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StockAdjustment(TimeStampedModel):
    """
    Cabecera de un ajuste de stock.

    Representa una operación manual de corrección de inventario.

    IMPORTANTE:
    - Crear un StockAdjustment NO modifica stock.
    - Añadir líneas NO modifica stock.
    - El stock solo debe modificarse al confirmar el ajuste desde services.py.
    """

    STATUS_DRAFT = "draft"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Borrador"),
        (STATUS_CONFIRMED, "Confirmado"),
        (STATUS_CANCELLED, "Cancelado"),
    ]

    REASON_STOCKTAKE = "stocktake"
    REASON_LOSS = "loss"
    REASON_BREAKAGE = "breakage"
    REASON_ERROR = "error"
    REASON_OTHER = "other"

    REASON_CHOICES = [
        (REASON_STOCKTAKE, "Recuento de inventario"),
        (REASON_LOSS, "Pérdida o merma"),
        (REASON_BREAKAGE, "Rotura"),
        (REASON_ERROR, "Error de stock"),
        (REASON_OTHER, "Otro motivo"),
    ]

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="stock_adjustments",
    )

    store = models.ForeignKey(
        Store,
        verbose_name="Tienda",
        on_delete=models.PROTECT,
        related_name="stock_adjustments",
    )

    code = models.CharField(
        "Código de ajuste",
        max_length=40,
        blank=True,
        help_text="Código interno del ajuste. Si se deja vacío, se genera automáticamente.",
    )

    status = models.CharField(
        "Estado",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )

    reason = models.CharField(
        "Motivo",
        max_length=30,
        choices=REASON_CHOICES,
        default=REASON_STOCKTAKE,
    )

    notes = models.TextField(
        "Notas",
        blank=True,
    )

    confirmed_at = models.DateTimeField(
        "Fecha de confirmación",
        blank=True,
        null=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Creado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_stock_adjustments",
    )

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Confirmado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_stock_adjustments",
    )

    class Meta:
        verbose_name = "Ajuste de stock"
        verbose_name_plural = "Ajustes de stock"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"],
                name="uniq_stadj_bus_code",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "store", "status"],
                name="idx_stadj_bus_store_st",
            ),
            models.Index(
                fields=["business", "created_at"],
                name="idx_stadj_bus_created",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.store}"

    @property
    def is_draft(self):
        return self.status == self.STATUS_DRAFT

    @property
    def is_confirmed(self):
        return self.status == self.STATUS_CONFIRMED

    @property
    def is_cancelled(self):
        return self.status == self.STATUS_CANCELLED

    def clean(self):
        """
        Validaciones de cabecera del ajuste.
        """
        super().clean()

        errors = {}

        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = "La tienda debe pertenecer al mismo negocio."

        if self.status == self.STATUS_CONFIRMED and not self.confirmed_at:
            errors["confirmed_at"] = (
                "Un ajuste confirmado debe tener fecha de confirmación."
            )

        if self.status != self.STATUS_CONFIRMED:
            self.confirmed_at = None
            self.confirmed_by = None

        if self.notes:
            self.notes = self.notes.strip()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.code and self.business_id:
            self.code = self._generate_unique_code()

        self.full_clean()
        return super().save(*args, **kwargs)

    def _generate_unique_code(self):
        """
        Genera un código único por negocio.

        Ejemplo:
        ADJ000001
        ADJ000002
        ADJ000003
        """
        prefix = "ADJ"
        counter = 1

        while True:
            code = f"{prefix}{counter:06d}"

            exists = (
                StockAdjustment.objects.filter(
                    business=self.business,
                    code=code,
                )
                .exclude(pk=self.pk)
                .exists()
            )

            if not exists:
                return code

            counter += 1


class StockAdjustmentLine(TimeStampedModel):
    """
    Línea de un ajuste de stock.

    Guarda la comparación entre:
    - stock que decía el sistema
    - stock contado realmente
    - diferencia resultante

    IMPORTANTE:
    - Esta línea por sí sola NO modifica stock.
    - El stock se modifica al confirmar el StockAdjustment desde services.py.
    """

    adjustment = models.ForeignKey(
        StockAdjustment,
        verbose_name="Ajuste",
        on_delete=models.CASCADE,
        related_name="lines",
    )

    inventory_item = models.ForeignKey(
        InventoryItem,
        verbose_name="Stock afectado",
        on_delete=models.PROTECT,
        related_name="adjustment_lines",
    )

    product = models.ForeignKey(
        Product,
        verbose_name="Producto",
        on_delete=models.PROTECT,
        related_name="stock_adjustment_lines",
    )

    system_stock = models.DecimalField(
        "Stock en sistema",
        max_digits=14,
        decimal_places=3,
        help_text="Stock que tenía el sistema antes del recuento.",
    )

    counted_stock = models.DecimalField(
        "Stock contado",
        max_digits=14,
        decimal_places=3,
        help_text="Stock real contado físicamente.",
    )

    difference = models.DecimalField(
        "Diferencia",
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        editable=False,
        help_text="Diferencia entre stock contado y stock en sistema.",
    )

    notes = models.CharField(
        "Notas",
        max_length=180,
        blank=True,
    )

    class Meta:
        verbose_name = "Línea de ajuste de stock"
        verbose_name_plural = "Líneas de ajuste de stock"
        ordering = ["product__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["adjustment", "inventory_item"],
                name="uniq_stadjline_adj_item",
            ),
            models.CheckConstraint(
                condition=Q(counted_stock__gte=0),
                name="chk_stadjline_cnt_gte_0",
            ),
        ]
        indexes = [
            models.Index(
                fields=["adjustment", "product"],
                name="idx_stadjline_adj_prod",
            ),
        ]

    def __str__(self):
        return f"{self.product} ({self.difference})"

    def clean(self):
        """
        Validaciones de la línea de ajuste.
        """
        super().clean()

        errors = {}

        if (
            self.adjustment_id
            and self.adjustment.status != StockAdjustment.STATUS_DRAFT
        ):
            errors["adjustment"] = (
                "Solo se pueden editar líneas de ajustes en borrador."
            )

        if self.adjustment_id and self.inventory_item_id:
            if self.adjustment.business_id != self.inventory_item.business_id:
                errors["inventory_item"] = (
                    "El stock afectado debe pertenecer al mismo negocio que el ajuste."
                )

            if self.adjustment.store_id != self.inventory_item.store_id:
                errors["inventory_item"] = (
                    "El stock afectado debe pertenecer a la misma tienda que el ajuste."
                )

        if self.inventory_item_id and self.product_id:
            if self.inventory_item.product_id != self.product_id:
                errors["product"] = (
                    "El producto debe coincidir con el producto del stock afectado."
                )

        if self.product_id:
            if self.product.is_service:
                errors["product"] = "No se puede ajustar stock de un servicio."

            if not self.product.track_stock:
                errors["product"] = (
                    "No se puede ajustar stock de un producto que no controla stock."
                )

        if self.system_stock is None:
            errors["system_stock"] = "El stock en sistema es obligatorio."

        if self.counted_stock is None:
            errors["counted_stock"] = "El stock contado es obligatorio."

        elif self.counted_stock < Decimal("0.000"):
            errors["counted_stock"] = "El stock contado no puede ser negativo."

        if self.system_stock is not None and self.counted_stock is not None:
            self.difference = self.counted_stock - self.system_stock

        if self.notes:
            self.notes = self.notes.strip()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.inventory_item_id:
            self.product = self.inventory_item.product

        self.full_clean()
        return super().save(*args, **kwargs)


class StockMovement(TimeStampedModel):
    """
    Movimiento histórico de stock.

    IMPORTANTE:
    - Este modelo NO es el stock actual.
    - Este modelo es el histórico/auditoría de lo que ha pasado.
    - InventoryItem guarda la foto actual.
    - StockMovement guarda cada entrada, salida o ajuste.
    """

    TYPE_INITIAL = "initial"
    TYPE_PURCHASE_RECEIPT = "purchase_receipt"
    TYPE_SALE = "sale"
    TYPE_SALE_RETURN = "sale_return"
    TYPE_PURCHASE_RETURN = "purchase_return"
    TYPE_ADJUSTMENT_IN = "adjustment_in"
    TYPE_ADJUSTMENT_OUT = "adjustment_out"
    TYPE_TRANSFER_IN = "transfer_in"
    TYPE_TRANSFER_OUT = "transfer_out"
    TYPE_STOCKTAKE = "stocktake"
    TYPE_LOSS = "loss"

    MOVEMENT_TYPE_CHOICES = [
        (TYPE_INITIAL, "Inventario inicial"),
        (TYPE_PURCHASE_RECEIPT, "Entrada por compra recibida"),
        (TYPE_SALE, "Salida por venta"),
        (TYPE_SALE_RETURN, "Entrada por devolución de venta"),
        (TYPE_PURCHASE_RETURN, "Salida por devolución a proveedor"),
        (TYPE_ADJUSTMENT_IN, "Ajuste positivo"),
        (TYPE_ADJUSTMENT_OUT, "Ajuste negativo"),
        (TYPE_TRANSFER_IN, "Entrada por traspaso"),
        (TYPE_TRANSFER_OUT, "Salida por traspaso"),
        (TYPE_STOCKTAKE, "Regularización por recuento"),
        (TYPE_LOSS, "Merma o pérdida"),
    ]

    IN_TYPES = {
        TYPE_INITIAL,
        TYPE_PURCHASE_RECEIPT,
        TYPE_SALE_RETURN,
        TYPE_ADJUSTMENT_IN,
        TYPE_TRANSFER_IN,
    }

    OUT_TYPES = {
        TYPE_SALE,
        TYPE_PURCHASE_RETURN,
        TYPE_ADJUSTMENT_OUT,
        TYPE_TRANSFER_OUT,
        TYPE_LOSS,
    }

    FLEXIBLE_TYPES = {
        TYPE_STOCKTAKE,
    }

    REF_MANUAL = "manual"
    REF_SALE = "sale"
    REF_PURCHASE = "purchase"
    REF_TRANSFER = "transfer"
    REF_STOCK_ADJUSTMENT = "stock_adjustment"
    REF_SYSTEM = "system"

    REFERENCE_TYPE_CHOICES = [
        (REF_MANUAL, "Manual"),
        (REF_SALE, "Venta"),
        (REF_PURCHASE, "Compra"),
        (REF_TRANSFER, "Traspaso"),
        (REF_STOCK_ADJUSTMENT, "Ajuste de stock"),
        (REF_SYSTEM, "Sistema"),
    ]

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="stock_movements",
    )

    sale = models.ForeignKey(
        "sales.Sale",
        verbose_name="Venta",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    sale_line = models.ForeignKey(
        "sales.SaleLine",
        verbose_name="Línea de venta",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    sale_return = models.ForeignKey(
        "sales.SaleReturn",
        verbose_name="Devolución de venta",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    sale_return_line = models.ForeignKey(
        "sales.SaleReturnLine",
        verbose_name="Línea de devolución",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )

    inventory_item = models.ForeignKey(
        InventoryItem,
        verbose_name="Stock afectado",
        on_delete=models.PROTECT,
        related_name="movements",
    )

    store = models.ForeignKey(
        Store,
        verbose_name="Tienda",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )

    product = models.ForeignKey(
        Product,
        verbose_name="Producto",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )

    stock_adjustment_line = models.ForeignKey(
        StockAdjustmentLine,
        verbose_name="Línea de ajuste",
        on_delete=models.PROTECT,
        related_name="stock_movements",
        blank=True,
        null=True,
        help_text="Línea de ajuste que originó el movimiento, si aplica.",
    )

    movement_type = models.CharField(
        "Tipo de movimiento",
        max_length=30,
        choices=MOVEMENT_TYPE_CHOICES,
    )

    quantity = models.DecimalField(
        "Cantidad",
        max_digits=14,
        decimal_places=3,
        help_text="Cantidad movida. Siempre positiva.",
    )

    stock_before = models.DecimalField(
        "Stock antes",
        max_digits=14,
        decimal_places=3,
        help_text="Stock que había antes del movimiento.",
    )

    stock_after = models.DecimalField(
        "Stock después",
        max_digits=14,
        decimal_places=3,
        help_text="Stock resultante después del movimiento.",
    )

    unit_cost = models.DecimalField(
        "Coste unitario",
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Coste unitario asociado al movimiento, si aplica.",
    )

    reference_type = models.CharField(
        "Tipo de referencia",
        max_length=30,
        choices=REFERENCE_TYPE_CHOICES,
        blank=True,
        help_text="Origen del movimiento: venta, compra, ajuste manual, etc.",
    )

    reference_id = models.CharField(
        "ID de referencia",
        max_length=80,
        blank=True,
        help_text=(
            "ID externo o interno del documento relacionado. "
            "Se conserva como referencia genérica y por compatibilidad."
        ),
    )

    operation_id = models.UUIDField(
        "ID de operación",
        default=uuid.uuid4,
        db_index=True,
        help_text="Agrupa movimientos relacionados, por ejemplo un traspaso entre tiendas.",
    )

    reason = models.CharField(
        "Motivo",
        max_length=180,
        blank=True,
        help_text="Motivo breve del movimiento.",
    )

    notes = models.TextField(
        "Notas",
        blank=True,
    )

    occurred_at = models.DateTimeField(
        "Fecha del movimiento",
        default=timezone.now,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Creado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )

    class Meta:
        verbose_name = "Movimiento de stock"
        verbose_name_plural = "Movimientos de stock"
        ordering = ["-occurred_at", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="chk_stmov_qty_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(unit_cost__isnull=True) | Q(unit_cost__gte=0),
                name="chk_stmov_cost_gte_0",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "store", "occurred_at"],
                name="idx_stmov_bus_store_dt",
            ),
            models.Index(
                fields=["business", "product", "occurred_at"],
                name="idx_stmov_bus_prod_dt",
            ),
            models.Index(
                fields=["operation_id"],
                name="idx_stmov_operation",
            ),
            models.Index(
                fields=["reference_type", "reference_id"],
                name="idx_stmov_reference",
            ),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} - {self.product} ({self.quantity})"

    @property
    def is_incoming(self):
        return self.movement_type in self.IN_TYPES

    @property
    def is_outgoing(self):
        return self.movement_type in self.OUT_TYPES

    def clean(self):
        """
        Validaciones del movimiento de stock.

        La lógica fuerte de crear movimientos debe vivir en services.py,
        pero el modelo protege las reglas críticas.
        """
        super().clean()

        errors = {}

        if self.inventory_item_id:
            if self.business_id and self.inventory_item.business_id != self.business_id:
                errors["inventory_item"] = (
                    "El stock afectado debe pertenecer al mismo negocio."
                )

            if self.store_id and self.inventory_item.store_id != self.store_id:
                errors["store"] = (
                    "La tienda del movimiento debe coincidir con la tienda del stock."
                )

            if self.product_id and self.inventory_item.product_id != self.product_id:
                errors["product"] = (
                    "El producto del movimiento debe coincidir con el producto del stock."
                )

        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = "La tienda debe pertenecer al mismo negocio."

        if self.product_id and self.business_id:
            if self.product.business_id != self.business_id:
                errors["product"] = "El producto debe pertenecer al mismo negocio."

        if self.product_id:
            if self.product.is_service:
                errors["product"] = (
                    "No se pueden crear movimientos de stock para servicios."
                )

            if not self.product.track_stock:
                errors["product"] = (
                    "No se pueden crear movimientos para productos que no controlan stock."
                )

        if self.stock_adjustment_line_id:
            if self.stock_adjustment_line.adjustment.business_id != self.business_id:
                errors["stock_adjustment_line"] = (
                    "La línea de ajuste debe pertenecer al mismo negocio."
                )

            if self.stock_adjustment_line.inventory_item_id != self.inventory_item_id:
                errors["stock_adjustment_line"] = (
                    "La línea de ajuste debe coincidir con el stock afectado."
                )

        sales_objects = {
            "sale": self.sale if self.sale_id else None,
            "sale_line": self.sale_line if self.sale_line_id else None,
            "sale_return": self.sale_return if self.sale_return_id else None,
            "sale_return_line": (
                self.sale_return_line if self.sale_return_line_id else None
            ),
        }
        for field, obj in sales_objects.items():
            if obj is not None and obj.business_id != self.business_id:
                errors[field] = "La referencia debe pertenecer al mismo negocio."

        if self.sale_id and self.sale.store_id != self.store_id:
            errors["sale"] = "La venta debe pertenecer a la misma tienda."
        if self.sale_line_id:
            if not self.sale_id or self.sale_line.sale_id != self.sale_id:
                errors["sale_line"] = "La línea debe pertenecer a la venta indicada."
            if (
                self.sale_line.product_id
                and self.sale_line.product_id != self.product_id
            ):
                errors["product"] = "El producto debe coincidir con la línea de venta."
        if self.sale_return_id:
            if not self.sale_id or self.sale_return.original_sale_id != self.sale_id:
                errors["sale_return"] = (
                    "La devolución debe corresponder a la venta indicada."
                )
            if self.sale_return.store_id != self.store_id:
                errors["sale_return"] = (
                    "La devolución debe pertenecer a la misma tienda."
                )
        if self.sale_return_line_id:
            if (
                not self.sale_return_id
                or self.sale_return_line.return_doc_id != self.sale_return_id
            ):
                errors["sale_return_line"] = (
                    "La línea debe pertenecer a la devolución indicada."
                )
            if (
                self.sale_line_id
                and self.sale_return_line.original_line_id != self.sale_line_id
            ):
                errors["sale_return_line"] = (
                    "La línea devuelta debe coincidir con la línea de venta."
                )

        if self.quantity is None or self.quantity <= Decimal("0.000"):
            errors["quantity"] = "La cantidad del movimiento debe ser mayor que cero."

        if self.stock_before is None:
            errors["stock_before"] = "El stock anterior es obligatorio."

        if self.stock_after is None:
            errors["stock_after"] = "El stock posterior es obligatorio."

        if self.unit_cost is not None and self.unit_cost < Decimal("0.00"):
            errors["unit_cost"] = "El coste unitario no puede ser negativo."

        if (
            self.movement_type in self.IN_TYPES
            and self.stock_before is not None
            and self.quantity is not None
            and self.stock_after is not None
        ):
            expected_stock = self.stock_before + self.quantity

            if self.stock_after != expected_stock:
                errors["stock_after"] = (
                    "En una entrada, el stock posterior debe ser stock_before + quantity."
                )

        if (
            self.movement_type in self.OUT_TYPES
            and self.stock_before is not None
            and self.quantity is not None
            and self.stock_after is not None
        ):
            expected_stock = self.stock_before - self.quantity

            if self.stock_after != expected_stock:
                errors["stock_after"] = (
                    "En una salida, el stock posterior debe ser stock_before - quantity."
                )

        if (
            self.movement_type in self.FLEXIBLE_TYPES
            and self.stock_before is not None
            and self.quantity is not None
            and self.stock_after is not None
        ):
            expected_quantity = abs(self.stock_after - self.stock_before)

            if self.quantity != expected_quantity:
                errors["quantity"] = (
                    "En una regularización, quantity debe ser la diferencia absoluta "
                    "entre stock_before y stock_after."
                )

        if self.reference_id and not self.reference_type:
            errors["reference_type"] = (
                "Si informas una referencia, debes indicar el tipo de referencia."
            )

        if self.reason:
            self.reason = self.reason.strip()

        if self.notes:
            self.notes = self.notes.strip()

        if self.reference_id:
            self.reference_id = self.reference_id.strip()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.inventory_item_id:
            self.product = self.inventory_item.product
            self.store = self.inventory_item.store
            self.business = self.inventory_item.business

        self.full_clean()
        return super().save(*args, **kwargs)
