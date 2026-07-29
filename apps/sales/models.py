from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import Business, TimeStampedModel


class Sale(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        COMPLETED = "completed", "Completada"
        CANCELLED = "cancelled", "Cancelada"

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="sales"
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.PROTECT, related_name="sales"
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
    )
    cash_register = models.ForeignKey(
        "cash_register.CashRegister",
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
    )
    cash_session = models.ForeignKey(
        "cash_register.CashSession",
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN
    )
    requires_invoice = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    tax_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_sales"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)

    def __str__(self):
        return f"Venta #{self.pk or 'nueva'}"

    def clean(self):
        super().clean()
        errors = {}
        for field in (
            "store",
            "customer",
            "cash_register",
            "cash_session",
            "created_by",
        ):
            obj = getattr(self, field, None)
            if obj and self.business_id and obj.business_id != self.business_id:
                errors[field] = "Debe pertenecer al mismo negocio."
        if (
            self.cash_session_id
            and self.cash_register_id
            and self.cash_session.cash_register_id != self.cash_register_id
        ):
            errors["cash_session"] = "La sesión no pertenece a la caja seleccionada."
        if bool(self.cash_register_id) != bool(self.cash_session_id):
            errors["cash_session"] = (
                "La caja y la sesión deben indicarse conjuntamente."
            )
        if self.requires_invoice and not self.customer_id:
            errors["customer"] = "La factura requiere un cliente."
        if errors:
            raise ValidationError(errors)


class SaleLine(TimeStampedModel):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="sale_lines"
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    tax_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    def __str__(self):
        return self.description


class SaleReturn(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        COMPLETED = "completed", "Completada"
        CANCELLED = "cancelled", "Cancelada"

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="sale_returns"
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.PROTECT, related_name="sale_returns"
    )
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="returns")
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN
    )
    reason = models.TextField()
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_sale_returns",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)

    def __str__(self):
        return f"Devolución #{self.pk or 'nueva'}"


class SaleReturnLine(TimeStampedModel):
    sale_return = models.ForeignKey(
        SaleReturn, on_delete=models.CASCADE, related_name="lines"
    )
    sale_line = models.ForeignKey(
        SaleLine, on_delete=models.PROTECT, related_name="return_lines"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    def __str__(self):
        return f"{self.sale_line} × {self.quantity}"
