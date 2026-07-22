from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BusinessOwnedModel


class CustomerTypeChoices(models.TextChoices):
    INDIVIDUAL = "individual", "Particular"
    COMPANY = "company", "Empresa"
    FOREIGN = "foreign", "Extranjero"


class Customer(BusinessOwnedModel):
    customer_type = models.CharField(
        max_length=20,
        choices=CustomerTypeChoices.choices,
        default=CustomerTypeChoices.INDIVIDUAL,
    )
    name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255, blank=True)
    tax_identifier = models.CharField(max_length=32, blank=True)
    country_code = models.CharField(max_length=2, default="ES")
    foreign_id_type = models.CharField(max_length=32, blank=True)
    foreign_id = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    address_line_1 = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=120, blank=True)
    province = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=["business", "tax_identifier"],
                condition=~Q(tax_identifier=""),
                name="customers_unique_tax_identifier_business",
            ),
            models.UniqueConstraint(
                fields=["business", "foreign_id_type", "foreign_id"],
                condition=~Q(foreign_id_type="") & ~Q(foreign_id=""),
                name="customers_unique_foreign_id_business",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "is_active", "name"],
                name="customers_biz_active_name_idx",
            )
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
        return bool(self.foreign_id_type and self.foreign_id)

    def clean(self):
        super().clean()
        errors = {}
        self.name = (self.name or "").strip()
        self.legal_name = (self.legal_name or "").strip()
        self.tax_identifier = (self.tax_identifier or "").strip().upper()
        self.country_code = (self.country_code or "").strip().upper()
        self.foreign_id_type = (self.foreign_id_type or "").strip().upper()
        self.foreign_id = (self.foreign_id or "").strip().upper()
        self.email = (self.email or "").strip().lower()
        for attr in ["phone", "address_line_1", "postal_code", "city", "province"]:
            setattr(self, attr, (getattr(self, attr) or "").strip())
        if not self.name:
            errors["name"] = "El nombre es obligatorio."
        if len(self.country_code) != 2 or not self.country_code.isalpha():
            errors["country_code"] = "El código de país debe tener dos letras."
        if bool(self.foreign_id_type) != bool(self.foreign_id):
            errors["foreign_id"] = (
                "Tipo e identificación extranjera deben informarse conjuntamente."
            )
        if self.business_id and self.tax_identifier:
            qs = Customer.objects.filter(
                business_id=self.business_id, tax_identifier=self.tax_identifier
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                errors["tax_identifier"] = (
                    "Ya existe un cliente con este identificador fiscal en el negocio."
                )
        if self.business_id and self.foreign_id_type and self.foreign_id:
            qs = Customer.objects.filter(
                business_id=self.business_id,
                foreign_id_type=self.foreign_id_type,
                foreign_id=self.foreign_id,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                errors["foreign_id"] = (
                    "Ya existe un cliente con esta identificación extranjera en el negocio."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CustomerAccount(BusinessOwnedModel):
    customer = models.OneToOneField(
        Customer, on_delete=models.PROTECT, related_name="account"
    )
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    credit_limit = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    is_blocked = models.BooleanField(default=False)

    @property
    def available_credit(self):
        return self.credit_limit - self.balance

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.customer_id
            and self.business_id
            and self.customer.business_id != self.business_id
        ):
            errors["customer"] = "El cliente debe pertenecer al mismo negocio."
        if self.credit_limit < Decimal("0.00"):
            errors["credit_limit"] = "El límite de crédito no puede ser negativo."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CustomerAccountEntryTypeChoices(models.TextChoices):
    CHARGE = "charge", "Cargo"
    PAYMENT = "payment", "Pago"
    REFUND = "refund", "Reembolso"
    ADJUSTMENT = "adjustment", "Ajuste"


class CustomerAccountEntry(BusinessOwnedModel):
    account = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="entries"
    )
    entry_type = models.CharField(
        max_length=20, choices=CustomerAccountEntryTypeChoices.choices
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="customer_account_entries",
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=["business", "account", "-created_at"],
                name="cust_entry_biz_account_idx",
            )
        ]

    def clean(self):
        super().clean()
        errors = {}
        self.notes = (self.notes or "").strip()
        if (
            self.account_id
            and self.business_id
            and self.account.business_id != self.business_id
        ):
            errors["account"] = "La cuenta debe pertenecer al mismo negocio."
        if self.created_by_id and self.business_id:
            if (
                not self.created_by.is_superuser
                and self.created_by.business_id != self.business_id
            ):
                errors["created_by"] = "El usuario debe pertenecer al mismo negocio."
        if self.amount == Decimal("0.00"):
            errors["amount"] = "El importe no puede ser cero."
        elif (
            self.entry_type == CustomerAccountEntryTypeChoices.CHARGE
            and self.amount <= 0
        ):
            errors["amount"] = "Los cargos deben tener importe positivo."
        elif (
            self.entry_type
            in [
                CustomerAccountEntryTypeChoices.PAYMENT,
                CustomerAccountEntryTypeChoices.REFUND,
            ]
            and self.amount >= 0
        ):
            errors["amount"] = "Pagos y reembolsos deben tener importe negativo."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
