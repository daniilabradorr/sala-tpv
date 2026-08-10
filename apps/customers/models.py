"""Modelos del módulo customers."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import Business, TimeStampedModel


class CustomerTypeChoices(models.TextChoices):
    """Tipos de cliente admitidos."""

    PERSON = "person", "Persona"
    COMPANY = "company", "Empresa"


class EntryTypeChoices(models.TextChoices):
    """Tipos de movimiento de una cuenta de cliente."""

    CHARGE = "charge", "Cargo"
    PAYMENT = "payment", "Pago"
    REFUND = "refund", "Reembolso"
    ADJUSTMENT = "adjustment", "Ajuste"


class Customer(TimeStampedModel):
    """Cliente particular o empresa perteneciente a un negocio."""

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="customers",
    )
    customer_type = models.CharField(
        "Tipo de cliente",
        max_length=20,
        choices=CustomerTypeChoices.choices,
        default=CustomerTypeChoices.PERSON,
    )
    name = models.CharField(
        "Nombre",
        max_length=180,
        help_text="Nombre completo o nombre comercial mostrado en el TPV.",
    )
    legal_name = models.CharField(
        "Nombre o razón social fiscal",
        max_length=180,
        blank=True,
        help_text="Nombre fiscal utilizado en facturas completas.",
    )
    tax_identifier = models.CharField(
        "NIF/CIF/NIE",
        max_length=30,
        blank=True,
        help_text="Identificador fiscal nacional, si corresponde.",
    )
    country_code = models.CharField(
        "Código de país",
        max_length=2,
        default="ES",
        help_text="Código ISO de dos letras. Ejemplos: ES, PT o FR.",
    )
    foreign_id_type = models.CharField(
        "Tipo de documento extranjero",
        max_length=50,
        blank=True,
        help_text="Tipo de identificación extranjera, si corresponde.",
    )
    foreign_id = models.CharField(
        "Identificador extranjero",
        max_length=50,
        blank=True,
        help_text="Número del documento extranjero, si corresponde.",
    )
    email = models.EmailField("Correo electrónico", blank=True)
    phone = models.CharField("Teléfono", max_length=30, blank=True)
    address_line_1 = models.CharField("Dirección", max_length=255, blank=True)
    postal_code = models.CharField("Código postal", max_length=12, blank=True)
    city = models.CharField("Ciudad", max_length=100, blank=True)
    province = models.CharField("Provincia", max_length=100, blank=True)
    is_active = models.BooleanField(
        "Activo",
        default=True,
        help_text="Desactiva al cliente sin eliminar su histórico.",
    )

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "tax_identifier"],
                condition=~Q(tax_identifier=""),
                name="uniq_cust_bus_taxid",
            ),
            models.UniqueConstraint(
                fields=["business", "country_code", "foreign_id_type", "foreign_id"],
                condition=~Q(foreign_id=""),
                name="uniq_cust_bus_foreign_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "is_active", "name"],
                name="idx_cust_bus_active_name",
            ),
            models.Index(
                fields=["business", "tax_identifier"],
                name="idx_cust_bus_taxid",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def fiscal_name(self):
        return self.legal_name or self.name

    @property
    def has_national_tax_data(self):
        return self.country_code == "ES" and bool(self.tax_identifier)

    @property
    def has_foreign_tax_data(self):
        return self.country_code != "ES" and bool(
            self.foreign_id_type and self.foreign_id
        )

    @property
    def has_complete_fiscal_identity(self):
        return self.has_national_tax_data or self.has_foreign_tax_data

    def _normalize_fields(self):
        self.name = (self.name or "").strip()
        self.legal_name = (self.legal_name or "").strip()
        self.tax_identifier = (self.tax_identifier or "").strip().upper()
        self.country_code = (self.country_code or "").strip().upper()
        self.foreign_id_type = (self.foreign_id_type or "").strip().upper()
        self.foreign_id = (self.foreign_id or "").strip().upper()
        self.email = (self.email or "").strip().lower()
        self.phone = (self.phone or "").strip()
        self.address_line_1 = (self.address_line_1 or "").strip()
        self.postal_code = (self.postal_code or "").strip()
        self.city = (self.city or "").strip()
        self.province = (self.province or "").strip()

    def clean(self):
        super().clean()
        self._normalize_fields()
        errors = {}
        if not self.name:
            errors["name"] = "El nombre del cliente es obligatorio."
        if len(self.country_code) != 2 or not self.country_code.isalpha():
            errors["country_code"] = (
                "El código de país debe contener exactamente dos letras."
            )
        if bool(self.foreign_id_type) != bool(self.foreign_id):
            message = (
                "El tipo y el número del documento extranjero "
                "deben informarse conjuntamente."
            )
            errors["foreign_id_type"] = message
            errors["foreign_id"] = message
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self._normalize_fields()
        self.full_clean()
        return super().save(*args, **kwargs)


class CustomerAccount(TimeStampedModel):
    """Cuenta corriente asociada a un cliente."""

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="customer_accounts",
    )
    customer = models.OneToOneField(
        Customer,
        verbose_name="Cliente",
        on_delete=models.PROTECT,
        related_name="account",
    )
    balance = models.DecimalField(
        "Saldo pendiente",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Saldo actual. Positivo significa deuda; negativo saldo a favor.",
    )
    credit_limit = models.DecimalField(
        "Límite de crédito",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Máxima deuda permitida para nuevas ventas a cuenta.",
    )
    is_blocked = models.BooleanField(
        "Ventas a cuenta bloqueadas",
        default=False,
        help_text="Impide generar nuevos cargos en esta cuenta.",
    )

    class Meta:
        verbose_name = "Cuenta de cliente"
        verbose_name_plural = "Cuentas de clientes"
        ordering = ["customer__name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(credit_limit__gte=0),
                name="chk_custacc_credit_gte_0",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "is_blocked"],
                name="idx_custacc_bus_blocked",
            ),
        ]

    def __str__(self):
        return f"Cuenta de {self.customer}"

    @property
    def available_credit(self):
        current_debt = max(self.balance, Decimal("0.00"))
        return self.credit_limit - current_debt

    def clean(self):
        super().clean()
        errors = {}
        if self.customer_id and self.business_id:
            if self.customer.business_id != self.business_id:
                errors["customer"] = (
                    "El cliente debe pertenecer al mismo negocio que la cuenta."
                )
        if self.credit_limit is not None and self.credit_limit < Decimal("0.00"):
            errors["credit_limit"] = "El límite de crédito no puede ser negativo."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CustomerAccountEntry(TimeStampedModel):
    """Movimiento histórico de una cuenta de cliente."""

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="customer_account_entries",
    )
    account = models.ForeignKey(
        CustomerAccount,
        verbose_name="Cuenta de cliente",
        on_delete=models.PROTECT,
        related_name="entries",
    )
    sale = models.ForeignKey(
        "sales.Sale",
        verbose_name="Venta",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="customer_account_entries",
    )
    entry_type = models.CharField(
        "Tipo de movimiento",
        max_length=20,
        choices=EntryTypeChoices.choices,
    )
    amount = models.DecimalField(
        "Importe del movimiento",
        max_digits=12,
        decimal_places=2,
        help_text="Variación aplicada al saldo. Nunca puede ser cero.",
    )
    balance_after = models.DecimalField(
        "Saldo después del movimiento",
        max_digits=12,
        decimal_places=2,
        editable=False,
        help_text="Fotografía del saldo tras aplicar este movimiento.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Creado por",
        on_delete=models.SET_NULL,
        related_name="customer_account_entries",
        null=True,
        blank=True,
    )
    notes = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Movimiento de cuenta de cliente"
        verbose_name_plural = "Movimientos de cuentas de clientes"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(amount=0),
                name="chk_custentry_amount_not_0",
            ),
            models.CheckConstraint(
                condition=(
                    Q(entry_type=EntryTypeChoices.CHARGE, amount__gt=0)
                    | Q(
                        entry_type__in=[
                            EntryTypeChoices.PAYMENT,
                            EntryTypeChoices.REFUND,
                        ],
                        amount__lt=0,
                    )
                    | (Q(entry_type=EntryTypeChoices.ADJUSTMENT) & ~Q(amount=0))
                ),
                name="chk_custentry_type_sign",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "account", "created_at"],
                name="idx_custentry_acc_created",
            ),
            models.Index(
                fields=["business", "entry_type", "created_at"],
                name="idx_custentry_bus_type",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_entry_type_display()} - {self.account.customer} ({self.amount})"
        )

    @property
    def is_charge(self):
        return self.entry_type == EntryTypeChoices.CHARGE

    @property
    def is_payment(self):
        return self.entry_type == EntryTypeChoices.PAYMENT

    @property
    def is_refund(self):
        return self.entry_type == EntryTypeChoices.REFUND

    @property
    def is_adjustment(self):
        return self.entry_type == EntryTypeChoices.ADJUSTMENT

    def clean(self):
        super().clean()
        errors = {}
        if self.account_id and self.business_id:
            if self.account.business_id != self.business_id:
                errors["account"] = (
                    "La cuenta debe pertenecer al mismo negocio que el movimiento."
                )
        if self.sale_id and self.business_id:
            if self.sale.business_id != self.business_id:
                errors["sale"] = "La venta debe pertenecer al mismo negocio."
            elif (
                self.sale.customer_id
                and self.account_id
                and self.sale.customer_id != self.account.customer_id
            ):
                errors["sale"] = "La venta debe pertenecer al cliente de la cuenta."
        if self.created_by_id:
            if not self.created_by.is_superuser:
                if self.created_by.business_id != self.business_id:
                    errors["created_by"] = (
                        "El usuario debe pertenecer al mismo negocio."
                    )
        if self.amount is None:
            errors["amount"] = "El importe del movimiento es obligatorio."
        elif self.amount == Decimal("0.00"):
            errors["amount"] = "El importe del movimiento no puede ser cero."
        elif self.entry_type == EntryTypeChoices.CHARGE and self.amount < Decimal(
            "0.00"
        ):
            errors["amount"] = "Un cargo debe tener un importe positivo."
        elif self.entry_type in {
            EntryTypeChoices.PAYMENT,
            EntryTypeChoices.REFUND,
        } and self.amount > Decimal("0.00"):
            errors["amount"] = "Los pagos y reembolsos deben tener un importe negativo."
        if self.notes:
            self.notes = self.notes.strip()
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
