from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import Business, TimeStampedModel
from apps.stores.models import Store


class PaymentTypeChoices(models.TextChoices):
    """
    Naturaleza económica del Payment.

    SALE_PAYMENT:
    dinero recibido por una venta.

    REFUND:
    dinero devuelto como consecuencia de una devolución comercial.
    """

    SALE_PAYMENT = "sale_payment", "Cobro"
    REFUND = "refund", "Reembolso"


class PaymentMethodCodeChoices(models.TextChoices):
    """
    Métodos de pago soportados en el MVP.

    En futuras versiones podrá evolucionarse hacia métodos
    configurables si el producto lo necesita.
    """

    CASH = "cash", "Efectivo"
    CARD = "card", "Tarjeta"
    BIZUM = "bizum", "Bizum"
    TRANSFER = "transfer", "Transferencia"


class PaymentStatusChoices(models.TextChoices):
    """
    Estado técnico de una operación económica.

    Solo COMPLETED tendrá efecto económico real sobre Sale.
    """

    PENDING = "pending", "Pendiente"
    COMPLETED = "completed", "Completado"
    FAILED = "failed", "Fallido"
    CANCELLED = "cancelled", "Cancelado"


class PaymentMethod(TimeStampedModel):
    """
    Método de pago disponible para un negocio.

    MVP:
    - Efectivo
    - Tarjeta
    - Bizum
    - Transferencia

    IMPORTANTE:
    En esta primera versión, la relación con caja física es
    una invariante conocida del producto:

        cash        -> affects_cash_register = True
        card        -> affects_cash_register = False
        bizum       -> affects_cash_register = False
        transfer    -> affects_cash_register = False

    Por eso el propio modelo calcula automáticamente
    affects_cash_register.

    En una futura versión, si Netxodo permite métodos de pago
    personalizados, esta regla podrá convertirse en configuración.
    """

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="payment_methods",
        verbose_name="Negocio",
    )

    name = models.CharField(
        "Nombre",
        max_length=100,
    )

    code = models.CharField(
        "Código",
        max_length=30,
        choices=PaymentMethodCodeChoices.choices,
    )

    affects_cash_register = models.BooleanField(
        "Afecta a caja física",
        default=False,
        editable=False,
        help_text=(
            "Se determina automáticamente según el método de pago. "
            "En el MVP únicamente el efectivo mueve caja física."
        ),
    )

    allows_refund = models.BooleanField(
        "Permite reembolso",
        default=True,
        help_text=(
            "Indica si este método puede utilizarse para realizar nuevos reembolsos."
        ),
    )

    is_active = models.BooleanField(
        "Activo",
        default=True,
        help_text=(
            "Permite desactivar el método para nuevas operaciones "
            "sin perder su histórico."
        ),
    )

    class Meta:
        verbose_name = "Método de pago"
        verbose_name_plural = "Métodos de pago"
        ordering = ["name", "pk"]

        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"],
                name="uniq_paymentmethod_business_code",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        code=PaymentMethodCodeChoices.CASH,
                        affects_cash_register=True,
                    )
                    | (
                        ~Q(code=PaymentMethodCodeChoices.CASH)
                        & Q(affects_cash_register=False)
                    )
                ),
                name="chk_paymethod_cash_register_effect",
            ),
        ]

        indexes = [
            models.Index(
                fields=["business", "is_active"],
                name="idx_paymethod_bus_active",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """
        Protege las invariantes estructurales del método.

        La posibilidad de utilizar un método concreto en una operación
        deberá comprobarse posteriormente desde services.py.
        """
        super().clean()

        errors = {}

        self.name = (self.name or "").strip()
        self.code = (self.code or "").strip().lower()

        if not self.name:
            errors["name"] = "El nombre del método de pago es obligatorio."

        if not self.code:
            errors["code"] = "El código del método de pago es obligatorio."

        # ----------------------------------------------------------
        # Regla fija del MVP
        # ----------------------------------------------------------

        self.affects_cash_register = self.code == PaymentMethodCodeChoices.CASH

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        Ejecuta las validaciones antes de persistir.

        Si se utiliza update_fields y cambia code, añadimos también
        affects_cash_register porque ambos valores están ligados
        estructuralmente en el MVP.
        """
        self.full_clean()

        update_fields = kwargs.get("update_fields")

        if update_fields is not None:
            update_fields = set(update_fields)

            if "code" in update_fields:
                update_fields.add("affects_cash_register")

            kwargs["update_fields"] = list(update_fields)

        return super().save(*args, **kwargs)


class Payment(TimeStampedModel):
    """
    Cobro o reembolso económico real asociado a una venta.

    Payment representa movimiento real de dinero.

    NO representa:
    - la operación comercial: eso es Sale;
    - la devolución comercial: eso es SaleReturn;
    - el movimiento físico de efectivo: eso será CashMovement;
    - una factura: eso será BillingDocument;
    - una rectificativa fiscal;
    - un envío a VeriFactu.

    IMPORTANTE:
    - amount siempre se almacena como número positivo.
    - payment_type determina si el dinero entra o sale.
    - SALE_PAYMENT representa dinero recibido.
    - REFUND representa dinero devuelto.
    - Solo Payments COMPLETED tendrán efecto económico
      sobre Sale.
    - pending_amount y payment_status serán recalculados
      desde Payments por services.py.
    """

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="payments",
        verbose_name="Negocio",
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="Tienda",
    )

    sale = models.ForeignKey(
        "sales.Sale",
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="Venta",
    )

    method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="Método de pago",
    )

    cash_session = models.ForeignKey(
        "cash_register.CashSession",
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="Sesión de caja",
        null=True,
        blank=True,
        help_text=(
            "Sesión de caja asociada a la operación cuando corresponda. "
            "Será especialmente relevante para efectivo, pero también "
            "puede conservarse como contexto operativo del turno para "
            "tarjeta, Bizum o transferencia."
        ),
    )

    sale_return = models.ForeignKey(
        "sales.SaleReturn",
        on_delete=models.PROTECT,
        related_name="refund_payments",
        verbose_name="Devolución",
        null=True,
        blank=True,
        help_text=(
            "Devolución comercial que origina el reembolso. "
            "Debe existir únicamente en Payments de tipo refund."
        ),
    )

    payment_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=PaymentTypeChoices.choices,
        default=PaymentTypeChoices.SALE_PAYMENT,
        db_index=True,
    )

    amount = models.DecimalField(
        "Importe",
        max_digits=14,
        decimal_places=2,
        help_text=(
            "Importe económico de la operación. "
            "Siempre se almacena como valor positivo."
        ),
    )

    status = models.CharField(
        "Estado",
        max_length=20,
        choices=PaymentStatusChoices.choices,
        default=PaymentStatusChoices.PENDING,
        db_index=True,
    )

    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments_processed",
        verbose_name="Procesado por",
    )

    idempotency_key = models.UUIDField(
        "Clave de idempotencia",
        help_text=(
            "Identificador estable de la operación económica. "
            "Permite detectar reintentos del mismo cobro o reembolso "
            "y evitar duplicados."
        ),
    )

    external_reference = models.CharField(
        "Referencia externa",
        max_length=150,
        blank=True,
        help_text=(
            "Referencia opcional procedente del datáfono, Bizum, "
            "transferencia o una futura pasarela de pago. "
            "No sustituye a la clave de idempotencia."
        ),
    )

    notes = models.TextField(
        "Notas",
        blank=True,
    )

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ["-created_at", "-pk"]

        constraints = [
            # ------------------------------------------------------
            # El importe siempre debe ser positivo.
            # ------------------------------------------------------
            models.CheckConstraint(
                condition=Q(
                    amount__gt=Decimal("0.00"),
                ),
                name="chk_payment_amount_gt_0",
            ),
            # ------------------------------------------------------
            # Relación PaymentType <-> SaleReturn
            #
            # SALE_PAYMENT:
            #     sale_return debe ser NULL.
            #
            # REFUND:
            #     sale_return debe existir.
            # ------------------------------------------------------
            models.CheckConstraint(
                condition=(
                    Q(
                        payment_type=PaymentTypeChoices.REFUND,
                        sale_return__isnull=False,
                    )
                    | Q(
                        payment_type=PaymentTypeChoices.SALE_PAYMENT,
                        sale_return__isnull=True,
                    )
                ),
                name="chk_payment_type_sale_return",
            ),
            # ------------------------------------------------------
            # Una misma operación no puede registrarse dos veces
            # dentro del mismo Business.
            # ------------------------------------------------------
            models.UniqueConstraint(
                fields=[
                    "business",
                    "idempotency_key",
                ],
                name="uniq_payment_business_idempotency",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "business",
                    "store",
                    "status",
                ],
                name="idx_payment_bus_store_status",
            ),
            models.Index(
                fields=[
                    "business",
                    "sale",
                ],
                name="idx_payment_bus_sale",
            ),
            models.Index(
                fields=[
                    "business",
                    "payment_type",
                ],
                name="idx_payment_bus_type",
            ),
            models.Index(
                fields=[
                    "business",
                    "created_at",
                ],
                name="idx_payment_bus_created",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_payment_type_display()} {self.amount} · Venta #{self.sale_id}"
        )

    @property
    def is_sale_payment(self):
        return self.payment_type == PaymentTypeChoices.SALE_PAYMENT

    @property
    def is_refund(self):
        return self.payment_type == PaymentTypeChoices.REFUND

    @property
    def is_pending(self):
        return self.status == PaymentStatusChoices.PENDING

    @property
    def is_completed(self):
        return self.status == PaymentStatusChoices.COMPLETED

    @property
    def is_failed(self):
        return self.status == PaymentStatusChoices.FAILED

    @property
    def is_cancelled(self):
        return self.status == PaymentStatusChoices.CANCELLED

    def clean(self):
        """
        Protege las invariantes estructurales del Payment.

        IMPORTANTE:
        deliberadamente NO valida aquí:

        - Sale.status == completed;
        - method.is_active;
        - method.allows_refund;
        - POSSettings.allow_split_payments;
        - POSSettings.require_open_cash_register;
        - estado abierto de CashSession;
        - permisos de processed_by;
        - PIN de acciones sensibles;
        - sobrepago;
        - capacidad restante de refund;
        - dinero realmente cobrado;
        - idempotencia lógica;
        - concurrencia.

        Esas reglas necesitan información dinámica, locking,
        configuración o cálculos acumulados y deben vivir
        en payments/services.py.
        """
        super().clean()

        errors = {}

        # ==========================================================
        # Importe
        # ==========================================================

        if self.amount is None:
            errors["amount"] = "El importe es obligatorio."

        elif self.amount <= Decimal("0.00"):
            errors["amount"] = "El importe debe ser mayor que cero."

        # ==========================================================
        # Business / Store
        # ==========================================================

        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = (
                    "La tienda debe pertenecer al mismo negocio que el pago."
                )

        if self.sale_id and self.business_id:
            if self.sale.business_id != self.business_id:
                errors["sale"] = (
                    "La venta debe pertenecer al mismo negocio que el pago."
                )

        if self.method_id and self.business_id:
            if self.method.business_id != self.business_id:
                errors["method"] = "El método de pago debe pertenecer al mismo negocio."

        # ==========================================================
        # Sale / Store
        # ==========================================================

        if self.sale_id and self.store_id:
            if self.sale.store_id != self.store_id:
                errors["store"] = (
                    "El pago debe realizarse en la misma tienda que la venta."
                )

        # ==========================================================
        # Usuario
        # ==========================================================

        if self.processed_by_id and self.business_id:
            if (
                not self.processed_by.is_superuser
                and self.processed_by.business_id != self.business_id
            ):
                errors["processed_by"] = (
                    "El usuario que procesa el pago debe pertenecer al mismo negocio."
                )

        # ==========================================================
        # CashSession
        # ==========================================================

        if self.cash_session_id:
            if self.business_id and self.cash_session.business_id != self.business_id:
                errors["cash_session"] = (
                    "La sesión de caja debe pertenecer al mismo negocio."
                )

            if self.store_id and self.cash_session.store_id != self.store_id:
                errors["cash_session"] = (
                    "La sesión de caja debe pertenecer a la misma tienda que el pago."
                )

        # ==========================================================
        # Refund / SaleReturn
        # ==========================================================

        if self.payment_type == PaymentTypeChoices.REFUND:
            if not self.sale_return_id:
                errors["sale_return"] = (
                    "Un reembolso debe estar asociado a una devolución comercial."
                )

        elif self.sale_return_id:
            errors["sale_return"] = (
                "Una devolución comercial solo puede "
                "asociarse a un Payment de tipo refund."
            )

        if self.sale_return_id:
            if self.business_id and self.sale_return.business_id != self.business_id:
                errors["sale_return"] = (
                    "La devolución debe pertenecer al mismo negocio."
                )

            if self.store_id and self.sale_return.store_id != self.store_id:
                errors["sale_return"] = (
                    "La devolución debe pertenecer a la misma tienda."
                )

            if self.sale_id and self.sale_return.original_sale_id != self.sale_id:
                errors["sale_return"] = (
                    "La devolución debe pertenecer a la venta indicada."
                )

        # ==========================================================
        # Normalización
        # ==========================================================

        self.external_reference = (self.external_reference or "").strip()

        self.notes = (self.notes or "").strip()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
