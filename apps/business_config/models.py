from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.business_config.helpers import (
    calculate_final_price as calculate_final_price_value,
    get_business_default_tax_rate,
    get_display_price as get_display_price_value,
    resolve_tax_rate,
)
from apps.core.models import Business, TimeStampedModel


class BusinessProfile(TimeStampedModel):
    business = models.OneToOneField(
        Business,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    legal_name = models.CharField("razón social", max_length=150)
    tax_identifier = models.CharField("NIF/CIF", max_length=20, blank=True)
    trade_name = models.CharField("nombre comercial", max_length=150, blank=True)
    phone = models.CharField("teléfono", max_length=30, blank=True)
    email = models.EmailField("email", blank=True)
    website = models.URLField("web", blank=True)

    address_line_1 = models.CharField("dirección", max_length=255, blank=True)
    address_line_2 = models.CharField("dirección extra", max_length=255, blank=True)
    postal_code = models.CharField("código postal", max_length=12, blank=True)
    city = models.CharField("ciudad", max_length=100, blank=True)
    province = models.CharField("provincia", max_length=100, blank=True)
    country_code = models.CharField("país", max_length=2, default="ES")

    currency_code = models.CharField("moneda", max_length=3, default="EUR")
    brand_name = models.CharField("marca", max_length=150, blank=True)
    logo_url = models.URLField("logo", blank=True)

    receipt_footer = models.TextField("pie de ticket", blank=True)
    return_policy = models.TextField("política de devoluciones", blank=True)

    default_tax_rate = models.DecimalField(
        "IVA por defecto",
        max_digits=5,
        decimal_places=2,
        default=Decimal("21.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
        help_text=(
            "IVA por defecto del negocio. Se usa como fallback si el producto "
            "o servicio no tiene un impuesto específico."
        ),
    )

    class Meta:
        verbose_name = "perfil de negocio"
        verbose_name_plural = "perfiles de negocio"

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def resolve_tax_rate(self, explicit_tax_rate=None):
        return resolve_tax_rate(explicit_tax_rate, self.default_tax_rate)

    def __str__(self) -> str:
        return f"Perfil · {self.business.name}"


class POSSettings(TimeStampedModel):
    business = models.OneToOneField(
        Business,
        on_delete=models.CASCADE,
        related_name="pos_settings",
    )
    prices_include_tax = models.BooleanField(
        "mostrar precios con IVA",
        default=True,
        help_text=(
            "Solo afecta a la visualización/interpretación comercial del precio. "
            "No cambia cómo se almacena el precio base."
        ),
    )
    allow_sale_without_stock = models.BooleanField(
        "permitir venta sin stock",
        default=False,
    )
    allow_manual_price = models.BooleanField(
        "permitir precio manual",
        default=False,
    )
    allow_manual_discounts = models.BooleanField(
        "permitir descuentos manuales",
        default=True,
    )
    max_manual_discount_percent = models.DecimalField(
        "descuento manual máximo %",
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    require_open_cash_register = models.BooleanField(
        "requiere caja abierta",
        default=True,
    )
    allow_split_payments = models.BooleanField(
        "permitir pagos divididos",
        default=True,
    )
    require_pin_for_sensitive_actions = models.BooleanField(
        "requerir PIN en acciones sensibles",
        default=True,
    )

    class Meta:
        verbose_name = "configuración TPV"
        verbose_name_plural = "configuraciones TPV"

    def clean(self):
        super().clean()

        if (
            not self.allow_manual_discounts
            and self.max_manual_discount_percent != Decimal("0.00")
        ):
            raise ValidationError(
                {
                    "max_manual_discount_percent": (
                        "Debe ser 0 si los descuentos manuales están desactivados."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def resolve_tax_rate(self, explicit_tax_rate=None):
        default_tax_rate = get_business_default_tax_rate(self.business)
        return resolve_tax_rate(explicit_tax_rate, default_tax_rate)

    def calculate_final_price(self, base_price, explicit_tax_rate=None):
        effective_tax_rate = self.resolve_tax_rate(explicit_tax_rate)
        return calculate_final_price_value(base_price, effective_tax_rate)

    def get_display_price(self, base_price, explicit_tax_rate=None):
        effective_tax_rate = self.resolve_tax_rate(explicit_tax_rate)
        return get_display_price_value(
            base_price=base_price,
            tax_rate=effective_tax_rate,
            prices_include_tax=self.prices_include_tax,
        )

    def sale_requires_open_cash_register(self) -> bool:
        return self.require_open_cash_register

    def __str__(self) -> str:
        return f"TPV · {self.business.name}"
