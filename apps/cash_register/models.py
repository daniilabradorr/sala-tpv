from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import Business, TimeStampedModel
from apps.stores.models import Store


class CashRegister(TimeStampedModel):
    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="cash_registers"
    )
    store = models.ForeignKey(
        Store, on_delete=models.PROTECT, related_name="cash_registers"
    )
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("business", "store", "name"), name="uniq_cashreg_bus_store_name"
            )
        ]

    def __str__(self):
        return f"{self.name} · {self.store}"

    def clean(self):
        super().clean()
        if (
            self.store_id
            and self.business_id
            and self.store.business_id != self.business_id
        ):
            raise ValidationError(
                {"store": "La tienda debe pertenecer al mismo negocio."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CashSession(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        CLOSED = "closed", "Cerrada"

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="cash_sessions"
    )
    store = models.ForeignKey(
        Store, on_delete=models.PROTECT, related_name="cash_sessions"
    )
    cash_register = models.ForeignKey(
        CashRegister, on_delete=models.PROTECT, related_name="sessions"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
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

    class Meta:
        ordering = ("-opened_at", "-pk")

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
        if self.status == self.Status.OPEN and self.closed_at is not None:
            errors["closed_at"] = "Una sesión abierta no puede tener fecha de cierre."
        if self.status == self.Status.CLOSED and self.closed_at is None:
            errors["closed_at"] = "Una sesión cerrada debe tener fecha de cierre."
        if (
            self.opened_by_id
            and self.business_id
            and self.opened_by.business_id != self.business_id
        ):
            errors["opened_by"] = "El usuario debe pertenecer al mismo negocio."
        if (
            self.closed_by_id
            and self.business_id
            and self.closed_by.business_id != self.business_id
        ):
            errors["closed_by"] = "El usuario debe pertenecer al mismo negocio."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
