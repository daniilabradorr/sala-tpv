from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import Business, TimeStampedModel
from apps.stores.models import Store


ZERO = Decimal("0.00")
MIN_CASH_AMOUNT = Decimal("0.01")


def _user_belongs_to_business(user, business_id):
    """
    Comprueba pertenencia estructural del usuario al Business.

    El superusuario se permite para no romper operaciones
    administrativas internas.
    """
    if user is None or business_id is None:
        return True

    if getattr(user, "is_superuser", False):
        return True

    return user.business_id == business_id


class CashRegister(TimeStampedModel):
    """
    Caja física / terminal de cobro perteneciente a una Store.

    Una Store puede tener varias cajas:

        Salamanca
        ├── CAJA-01
        └── CAJA-02

        Madrid
        └── CAJA-01

    El código es único dentro de cada Store.
    """

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="cash_registers",
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="cash_registers",
    )

    name = models.CharField(
        "Nombre",
        max_length=100,
    )

    code = models.CharField(
        "Código",
        max_length=30,
        help_text=("Código corto de la caja dentro de la tienda. Ejemplo: CAJA-01."),
    )

    is_active = models.BooleanField(
        "Activa",
        default=True,
    )

    class Meta:
        verbose_name = "Caja"
        verbose_name_plural = "Cajas"

        ordering = (
            "name",
            "pk",
        )

        constraints = [
            models.UniqueConstraint(
                fields=(
                    "business",
                    "store",
                    "name",
                ),
                name="uniq_cashreg_bus_store_name",
            ),
            models.UniqueConstraint(
                fields=(
                    "store",
                    "code",
                ),
                name="uniq_cashreg_store_code",
            ),
        ]

        indexes = [
            models.Index(
                fields=(
                    "business",
                    "store",
                    "is_active",
                ),
                name="idx_cashreg_bus_store_act",
            ),
        ]

    def __str__(self):
        return f"{self.name} [{self.code}] · {self.store}"

    def clean(self):
        super().clean()

        errors = {}

        self.name = (self.name or "").strip()
        self.code = (self.code or "").strip().upper()

        if not self.name:
            errors["name"] = "El nombre de la caja es obligatorio."

        if not self.code:
            errors["code"] = "El código de la caja es obligatorio."

        if (
            self.store_id
            and self.business_id
            and self.store.business_id != self.business_id
        ):
            errors["store"] = "La tienda debe pertenecer al mismo negocio."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()

        return super().save(*args, **kwargs)


class CashSession(TimeStampedModel):
    """
    Turno concreto de una CashRegister.

    Al abrir:

        opening_amount = X
        expected_cash_amount = X
        counted_cash_amount = NULL
        difference_amount = 0
        status = OPEN

    Al cerrar:

        counted_cash_amount = cantidad contada
        difference_amount = counted - expected
        closed_by = usuario
        closed_at = fecha
        status = CLOSED
    """

    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        CLOSED = "closed", "Cerrada"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="cash_sessions",
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="cash_sessions",
    )

    cash_register = models.ForeignKey(
        CashRegister,
        on_delete=models.PROTECT,
        related_name="sessions",
    )

    status = models.CharField(
        "Estado",
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )

    opened_at = models.DateTimeField(
        "Fecha de apertura",
        default=timezone.now,
    )

    closed_at = models.DateTimeField(
        "Fecha de cierre",
        null=True,
        blank=True,
    )

    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="opened_cash_sessions",
    )

    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="closed_cash_sessions",
        null=True,
        blank=True,
    )

    opening_amount = models.DecimalField(
        "Efectivo inicial",
        max_digits=14,
        decimal_places=2,
        default=ZERO,
        validators=[
            MinValueValidator(ZERO),
        ],
    )

    expected_cash_amount = models.DecimalField(
        "Efectivo esperado",
        max_digits=14,
        decimal_places=2,
        default=ZERO,
    )

    counted_cash_amount = models.DecimalField(
        "Efectivo contado",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(ZERO),
        ],
    )

    difference_amount = models.DecimalField(
        "Diferencia de efectivo",
        max_digits=14,
        decimal_places=2,
        default=ZERO,
    )

    class Meta:
        verbose_name = "Sesión de caja"
        verbose_name_plural = "Sesiones de caja"

        ordering = (
            "-opened_at",
            "-pk",
        )

        constraints = [
            models.UniqueConstraint(
                fields=("cash_register",),
                condition=Q(status="open"),
                name="uniq_cashsession_open_reg",
            ),
            models.CheckConstraint(
                condition=Q(
                    opening_amount__gte=ZERO,
                ),
                name="chk_cashsession_opening_gte0",
            ),
            models.CheckConstraint(
                condition=(
                    Q(counted_cash_amount__isnull=True)
                    | Q(counted_cash_amount__gte=ZERO)
                ),
                name="chk_cashsession_counted_gte0",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="open",
                        closed_at__isnull=True,
                        closed_by__isnull=True,
                        counted_cash_amount__isnull=True,
                        difference_amount=ZERO,
                    )
                    | Q(
                        status="closed",
                        closed_at__isnull=False,
                        closed_by__isnull=False,
                        counted_cash_amount__isnull=False,
                    )
                ),
                name="chk_cashsession_state_fields",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="open")
                    | Q(
                        difference_amount=(
                            F("counted_cash_amount") - F("expected_cash_amount")
                        )
                    )
                ),
                name="chk_cashsession_difference",
            ),
            models.CheckConstraint(
                condition=(
                    Q(closed_at__isnull=True)
                    | Q(
                        closed_at__gte=F("opened_at"),
                    )
                ),
                name="chk_cashsession_dates",
            ),
        ]

        indexes = [
            models.Index(
                fields=(
                    "business",
                    "store",
                    "status",
                ),
                name="idx_cashsess_bus_store_st",
            ),
            models.Index(
                fields=(
                    "cash_register",
                    "status",
                ),
                name="idx_cashsess_reg_status",
            ),
        ]

    @property
    def is_open(self):
        return self.status == self.Status.OPEN and self.closed_at is None

    def __str__(self):
        return f"{self.cash_register} · {self.get_status_display()}"

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.store_id
            and self.business_id
            and self.store.business_id != self.business_id
        ):
            errors["store"] = "La tienda debe pertenecer al mismo negocio."

        if self.cash_register_id:
            if self.business_id and self.cash_register.business_id != self.business_id:
                errors["cash_register"] = "La caja debe pertenecer al mismo negocio."

            if self.store_id and self.cash_register.store_id != self.store_id:
                errors["cash_register"] = "La caja debe pertenecer a la misma tienda."

        if self.opened_by_id and not _user_belongs_to_business(
            self.opened_by,
            self.business_id,
        ):
            errors["opened_by"] = (
                "El usuario que abre la caja debe pertenecer al mismo negocio."
            )

        if self.closed_by_id and not _user_belongs_to_business(
            self.closed_by,
            self.business_id,
        ):
            errors["closed_by"] = (
                "El usuario que cierra la caja debe pertenecer al mismo negocio."
            )

        if self.opening_amount is not None and self.opening_amount < ZERO:
            errors["opening_amount"] = "El efectivo inicial no puede ser negativo."

        if self.counted_cash_amount is not None and self.counted_cash_amount < ZERO:
            errors["counted_cash_amount"] = "El efectivo contado no puede ser negativo."

        if self.status == self.Status.OPEN:
            if self.closed_at is not None:
                errors["closed_at"] = (
                    "Una sesión abierta no puede tener fecha de cierre."
                )

            if self.closed_by_id is not None:
                errors["closed_by"] = (
                    "Una sesión abierta no puede tener usuario de cierre."
                )

            if self.counted_cash_amount is not None:
                errors["counted_cash_amount"] = (
                    "Una sesión abierta no guarda todavía el conteo final."
                )

            if self.difference_amount != ZERO:
                errors["difference_amount"] = (
                    "Una sesión abierta debe tener diferencia 0."
                )

        elif self.status == self.Status.CLOSED:
            if self.closed_at is None:
                errors["closed_at"] = "Una sesión cerrada debe tener fecha de cierre."

            if self.closed_by_id is None:
                errors["closed_by"] = "Una sesión cerrada debe indicar quién la cerró."

            if self.counted_cash_amount is None:
                errors["counted_cash_amount"] = (
                    "Una sesión cerrada debe guardar el efectivo contado."
                )

            if (
                self.counted_cash_amount is not None
                and self.expected_cash_amount is not None
            ):
                expected_difference = (
                    self.counted_cash_amount - self.expected_cash_amount
                )

                if self.difference_amount != expected_difference:
                    errors["difference_amount"] = (
                        "La diferencia debe ser contado - esperado."
                    )

        if (
            self.closed_at is not None
            and self.opened_at is not None
            and self.closed_at < self.opened_at
        ):
            errors["closed_at"] = (
                "La fecha de cierre no puede ser anterior a la apertura."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.get(pk=self.pk)
            if original.status == self.Status.CLOSED:
                protected = (
                    "opening_amount",
                    "expected_cash_amount",
                    "counted_cash_amount",
                    "difference_amount",
                    "closed_at",
                    "closed_by_id",
                    "status",
                )
                if any(
                    getattr(self, field) != getattr(original, field)
                    for field in protected
                ):
                    raise ValidationError(
                        "Una sesión cerrada es económicamente inmutable."
                    )
        self.full_clean()

        return super().save(*args, **kwargs)


class CashMovement(TimeStampedModel):
    """
    Movimiento REAL de efectivo físico.

    NO representa:

    - tarjeta;
    - Bizum;
    - transferencia;
    - el Payment económico completo;
    - la Sale;
    - el arqueo.

    amount se almacena siempre positivo.

    movement_type determina si entra o sale dinero.
    """

    class MovementType(models.TextChoices):
        SALE_CASH = (
            "sale_cash",
            "Cobro de venta en efectivo",
        )
        REFUND_CASH = (
            "refund_cash",
            "Reembolso en efectivo",
        )
        CASH_IN = (
            "cash_in",
            "Entrada manual de efectivo",
        )
        CASH_OUT = (
            "cash_out",
            "Salida manual de efectivo",
        )
        ADJUSTMENT = (
            "adjustment",
            "Ajuste",
        )

    class AdjustmentDirection(models.TextChoices):
        IN = "in", "Entrada"
        OUT = "out", "Salida"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="cash_movements",
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="cash_movements",
    )

    cash_session = models.ForeignKey(
        CashSession,
        on_delete=models.PROTECT,
        related_name="movements",
    )

    movement_type = models.CharField(
        "Tipo de movimiento",
        max_length=20,
        choices=MovementType.choices,
        db_index=True,
    )

    adjustment_direction = models.CharField(
        "Dirección del ajuste",
        max_length=3,
        choices=AdjustmentDirection.choices,
        null=True,
        blank=True,
    )

    amount = models.DecimalField(
        "Importe",
        max_digits=14,
        decimal_places=2,
        validators=[
            MinValueValidator(MIN_CASH_AMOUNT),
        ],
        help_text=("Siempre se almacena positivo. El tipo indica entrada o salida."),
    )

    balance_after = models.DecimalField(
        "Efectivo esperado después",
        max_digits=14,
        decimal_places=2,
        help_text=(
            "Snapshot del efectivo esperado después de aplicar este movimiento."
        ),
    )

    sale = models.ForeignKey(
        "sales.Sale",
        on_delete=models.PROTECT,
        related_name="cash_movements",
        null=True,
        blank=True,
    )

    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.PROTECT,
        related_name="cash_movements",
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cash_movements_created",
    )

    reason = models.TextField(
        "Motivo",
        blank=True,
    )

    class Meta:
        verbose_name = "Movimiento de caja"
        verbose_name_plural = "Movimientos de caja"

        ordering = (
            "-created_at",
            "-pk",
        )

        constraints = [
            models.CheckConstraint(
                condition=Q(
                    amount__gt=ZERO,
                ),
                name="chk_cashmovement_amount_gt0",
            ),
            models.UniqueConstraint(
                fields=("payment",),
                condition=Q(
                    payment__isnull=False,
                ),
                name="uniq_cashmovement_payment",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        movement_type__in=(
                            "sale_cash",
                            "refund_cash",
                        ),
                        payment__isnull=False,
                        sale__isnull=False,
                    )
                    | Q(
                        movement_type__in=(
                            "cash_in",
                            "cash_out",
                        ),
                        payment__isnull=True,
                        sale__isnull=True,
                    )
                    | Q(
                        movement_type="adjustment",
                    )
                ),
                name="chk_cashmovement_origin",
            ),
            models.CheckConstraint(
                condition=(
                    Q(movement_type="adjustment", adjustment_direction__isnull=False)
                    | (
                        ~Q(movement_type="adjustment")
                        & Q(adjustment_direction__isnull=True)
                    )
                ),
                name="chk_cashmovement_adjust_dir",
            ),
        ]

        indexes = [
            models.Index(
                fields=(
                    "business",
                    "store",
                    "cash_session",
                ),
                name="idx_cashmov_bus_store_sess",
            ),
            models.Index(
                fields=(
                    "cash_session",
                    "movement_type",
                ),
                name="idx_cashmov_sess_type",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_movement_type_display()} · "
            f"{self.amount} · "
            f"sesión #{self.cash_session_id}"
        )

    def clean(self):
        super().clean()

        errors = {}

        if self.cash_session_id and not self.cash_session.is_open:
            errors["cash_session"] = (
                "No se pueden añadir movimientos a una sesión cerrada."
            )

        if self.amount is not None and self.amount <= ZERO:
            errors["amount"] = "El importe debe ser mayor que cero."

        if (
            self.store_id
            and self.business_id
            and self.store.business_id != self.business_id
        ):
            errors["store"] = "La tienda debe pertenecer al mismo negocio."

        if self.cash_session_id:
            if self.business_id and self.cash_session.business_id != self.business_id:
                errors["cash_session"] = "La sesión debe pertenecer al mismo negocio."

            if self.store_id and self.cash_session.store_id != self.store_id:
                errors["cash_session"] = "La sesión debe pertenecer a la misma tienda."

        if self.sale_id:
            if self.business_id and self.sale.business_id != self.business_id:
                errors["sale"] = "La venta debe pertenecer al mismo negocio."

            if self.store_id and self.sale.store_id != self.store_id:
                errors["sale"] = "La venta debe pertenecer a la misma tienda."

        if self.payment_id:
            if self.business_id and self.payment.business_id != self.business_id:
                errors["payment"] = "El pago debe pertenecer al mismo negocio."

            if self.store_id and self.payment.store_id != self.store_id:
                errors["payment"] = "El pago debe pertenecer a la misma tienda."

            if self.payment.cash_session_id != self.cash_session_id:
                errors["payment"] = "El pago debe pertenecer a la misma sesión de caja."

            if self.payment.sale_id != self.sale_id:
                errors["sale"] = (
                    "La venta del movimiento debe coincidir con la venta del pago."
                )

            if not self.payment.method.affects_cash_register:
                errors["payment"] = "El método de pago no afecta a efectivo físico."

            from apps.payments.models import (
                PaymentStatusChoices,
                PaymentTypeChoices,
            )

            if self.payment.status != PaymentStatusChoices.COMPLETED:
                errors["payment"] = (
                    "Solo un pago completado puede generar movimiento de efectivo."
                )

            if self.movement_type in (
                self.MovementType.SALE_CASH,
                self.MovementType.REFUND_CASH,
            ):
                expected_movement_type = {
                    PaymentTypeChoices.SALE_PAYMENT: (self.MovementType.SALE_CASH),
                    PaymentTypeChoices.REFUND: (self.MovementType.REFUND_CASH),
                }.get(self.payment.payment_type)

                if self.movement_type != expected_movement_type:
                    errors["movement_type"] = (
                        "El tipo de movimiento no coincide con la naturaleza del pago."
                    )

        if self.movement_type in (
            self.MovementType.SALE_CASH,
            self.MovementType.REFUND_CASH,
        ):
            if not self.payment_id:
                errors["payment"] = (
                    "Los movimientos de cobro/reembolso requieren Payment."
                )

            if not self.sale_id:
                errors["sale"] = "Los movimientos de cobro/reembolso requieren Sale."

        elif self.movement_type in (
            self.MovementType.CASH_IN,
            self.MovementType.CASH_OUT,
        ):
            if self.payment_id:
                errors["payment"] = (
                    "Las entradas y salidas manuales no deben tener Payment."
                )

            if self.sale_id:
                errors["sale"] = "Las entradas y salidas manuales no deben tener Sale."

        if self.movement_type == self.MovementType.ADJUSTMENT:
            if not self.adjustment_direction:
                errors["adjustment_direction"] = "Un ajuste requiere dirección."
            if self.payment_id or self.sale_id:
                errors["payment"] = "Un ajuste manual no debe tener Payment ni Sale."
        elif self.adjustment_direction is not None:
            errors["adjustment_direction"] = "Solo un ajuste puede indicar dirección."

        if self.created_by_id and not _user_belongs_to_business(
            self.created_by,
            self.business_id,
        ):
            errors["created_by"] = "El usuario debe pertenecer al mismo negocio."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()

        return super().save(*args, **kwargs)


class CashCount(TimeStampedModel):
    """
    Fotografía de un arqueo de una CashSession.

    difference_amount:

        counted_amount - expected_amount

    IMPORTANTE:

    No impongo UniqueConstraint(cash_session).

    El contrato todavía debe decidir si tendremos:

        - un único arqueo final;
        - varios recuentos/revisiones.

    Por tanto Models no debe tomar esa decisión
    silenciosamente.
    """

    class CountType(models.TextChoices):
        REVIEW = "review", "Revisión"
        CLOSING = "closing", "Cierre"

    count_type = models.CharField(
        "Tipo de arqueo",
        max_length=10,
        choices=CountType.choices,
        default=CountType.REVIEW,
        db_index=True,
    )

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="cash_counts",
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="cash_counts",
    )

    cash_session = models.ForeignKey(
        CashSession,
        on_delete=models.PROTECT,
        related_name="counts",
    )

    counted_amount = models.DecimalField(
        "Efectivo contado",
        max_digits=14,
        decimal_places=2,
        validators=[
            MinValueValidator(ZERO),
        ],
    )

    expected_amount = models.DecimalField(
        "Efectivo esperado",
        max_digits=14,
        decimal_places=2,
    )

    difference_amount = models.DecimalField(
        "Diferencia",
        max_digits=14,
        decimal_places=2,
    )

    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cash_counts",
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    class Meta:
        verbose_name = "Arqueo de caja"
        verbose_name_plural = "Arqueos de caja"

        ordering = (
            "-created_at",
            "-pk",
        )

        constraints = [
            models.UniqueConstraint(
                fields=("cash_session",),
                condition=Q(count_type="closing"),
                name="uniq_cashcount_closing_session",
            ),
            models.CheckConstraint(
                condition=Q(
                    counted_amount__gte=ZERO,
                ),
                name="chk_cashcount_counted_gte0",
            ),
            models.CheckConstraint(
                condition=Q(
                    difference_amount=(F("counted_amount") - F("expected_amount"))
                ),
                name="chk_cashcount_difference",
            ),
        ]

        indexes = [
            models.Index(
                fields=(
                    "business",
                    "store",
                    "cash_session",
                ),
                name="idx_cashcount_bus_store_sess",
            ),
        ]

    def __str__(self):
        return (
            f"Arqueo · sesión #{self.cash_session_id} · contado {self.counted_amount}"
        )

    def clean(self):
        super().clean()

        errors = {}

        if self.counted_amount is not None and self.counted_amount < ZERO:
            errors["counted_amount"] = "El efectivo contado no puede ser negativo."

        if self.counted_amount is not None and self.expected_amount is not None:
            expected_difference = self.counted_amount - self.expected_amount

            if self.difference_amount != expected_difference:
                errors["difference_amount"] = (
                    "La diferencia debe ser contado - esperado."
                )

        if (
            self.store_id
            and self.business_id
            and self.store.business_id != self.business_id
        ):
            errors["store"] = "La tienda debe pertenecer al mismo negocio."

        if self.cash_session_id:
            if self.business_id and self.cash_session.business_id != self.business_id:
                errors["cash_session"] = "La sesión debe pertenecer al mismo negocio."

            if self.store_id and self.cash_session.store_id != self.store_id:
                errors["cash_session"] = "La sesión debe pertenecer a la misma tienda."

        if self.counted_by_id and not _user_belongs_to_business(
            self.counted_by,
            self.business_id,
        ):
            errors["counted_by"] = "El usuario debe pertenecer al mismo negocio."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        CashCount representa una fotografía histórica.

        Una vez creado no debe editarse.
        Si existe un nuevo recuento se crea otro CashCount,
        hasta que decidamos el contrato final de cardinalidad.
        """

        if not self._state.adding:
            raise ValidationError("Un arqueo histórico no debe modificarse.")

        self.full_clean()

        return super().save(*args, **kwargs)
