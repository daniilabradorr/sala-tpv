import re

from django.db import models
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from apps.core.models import Business, TimeStampedModel


class Store(TimeStampedModel):
    """
    Modelo para representar una tienda asociada a un negocio.
    Cada tienda tiene un nombre, un código único dentro del negocio, y puede tener
    información de contacto y ubicación.
    Attributes:
        business (ForeignKey): Relación con el modelo Business.
        name (CharField): Nombre de la tienda.
        code (CharField): Código único de la tienda dentro del negocio.
        adress_line_1 (CharField): Dirección principal de la tienda.
        adress_line_2 (CharField): Dirección secundaria de la tienda.
        postal_code (CharField): Código postal de la tienda.
        city (CharField): Ciudad donde se encuentra la tienda.
        province (CharField): Provincia donde se encuentra la tienda.
        country_code (CharField): Código de país ISO de la tienda.
        phone_store (CharField): Teléfono de contacto de la tienda.
        email_store (CharField): Correo electrónico de contacto de la tienda.
        is_active (BooleanField): Indica si la tienda está activa o no.
    """

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="stores",
    )

    name = models.CharField(
        "Nombre de la tienda",
        max_length=150,
        # Antes este campo tenía unique=True.
        # Lo quitamos porque en un sistema multiempresa no interesa que el nombre
        # de tienda sea único globalmente.
        #
        # Ejemplo:
        # - Negocio A puede tener una tienda llamada "Centro"
        # - Negocio B también puede tener una tienda llamada "Centro"
        #
        # La unicidad correcta será:
        #   business + name
        #
        # Eso lo definimos abajo con UniqueConstraint.
    )

    code = models.CharField(
        "Código de tienda",
        max_length=20,
        # TEMPORAL:
        # Permitimos blank=True porque estamos añadiendo el campo a un modelo
        # que ya existía.
        #
        # Más adelante, cuando stores esté bien implementado, este campo debería
        # ser obligatorio.
        blank=True,
        # TEMPORAL:
        # Este default evita que makemigrations te pida:
        # "¿Qué valor pongo para code en las filas antiguas?"
        #
        # Django necesita un valor para rellenar las tiendas que ya existían
        # según las migraciones antiguas.
        default="",
    )

    address_line_1 = models.CharField("Dirección Principal", max_length=150, blank=True)
    address_line_2 = models.CharField(
        "Dirección Secundaria", max_length=150, blank=True
    )

    postal_code = models.CharField("Código Postal", max_length=10, blank=True)
    city = models.CharField("Ciudad", max_length=120, blank=True)
    province = models.CharField("Provincia", max_length=120, blank=True)

    country_code = models.CharField(
        "Código país ISO", max_length=2, blank=False, null=False, default="ES"
    )

    phone_store = models.CharField("Teléfono de la tienda", max_length=30, blank=True)
    email_store = models.EmailField("email de la tienda", max_length=120, blank=True)
    is_active = models.BooleanField(
        "Activa",
        blank=False,
        # pongo default True para que las tiendas antiguas no se queden inactivas al migrar
        default=True,
        # deberia de ser unica  pero no obligatoriamente, ya que puede haber tiendas inactivas con el mismo nombre y codigo
    )
    # no pongo created_at y updated_at porque hereda de TimeStampedModel

    @property
    def contact_phone(self):
        if self.phone_store:
            return self.phone_store

        profile = getattr(self.business, "profile", None)

        if profile:
            return profile.phone

        return ""

    @property
    def contact_email(self):
        if self.email_store:
            return self.email_store

        profile = getattr(self.business, "profile", None)

        if profile:
            return profile.email

        return ""

    class Meta:
        verbose_name = "tienda"
        verbose_name_plural = "tiendas"

        ordering = (
            "business",
            "name",
        )

        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"],
                name="unique_store_code_per_business",
            ),
            models.UniqueConstraint(
                fields=["business", "name"],
                name="unique_store_name_per_business",
            ),
        ]

        indexes = [
            models.Index(
                fields=["business", "is_active"],
                name="stores_biz_active_idx",
            ),
            models.Index(
                fields=["business", "code"],
                name="stores_biz_code_idx",
            ),
            models.Index(
                fields=["business", "name"],
                name="stores_biz_name_idx",
            ),
        ]

    def __str__(self):
        """
        Representación legible de la tienda.

        Si tiene código:
            "Tienda Centro (CENTRO)"

        Si todavía no tiene código:
            "Tienda Centro"

        Esto es útil en admin, selects, logs y debugging.
        """
        if self.code:
            return f"{self.name} ({self.code})"

        return self.name

    def clean(self):
        """
        Validaciones del modelo.

        IMPORTANTE:
        En esta versión puente NO obligamos todavía a que business exista.

        ¿Por qué?
        ---------
        Porque hemos dejado business con null=True temporalmente para poder hacer
        la migración sin que Django pida un default.

        En la lógica real del TPV, business será obligatorio más adelante.

        De momento validamos solo:
        - normalizar code a mayúsculas
        - que name exista

        El campo name ya es obligatorio por CharField(blank=False), pero dejamos
        la validación explícita para que el error sea más claro.
        """
        super().clean()

        errors = {}

        if self.name:
            self.name = self.name.strip()

        # normalizo code a mayúsculas y elimino espacios
        if self.code:
            self.code = self.code.strip().upper()

        if self.address_line_1:
            self.address_line_1 = self.address_line_1.strip()

        if self.address_line_2:
            self.address_line_2 = self.address_line_2.strip()

        if self.postal_code:
            self.postal_code = self.postal_code.strip()

        if self.city:
            self.city = self.city.strip()

        if self.province:
            self.province = self.province.strip()

        if self.country_code:
            self.country_code = self.country_code.strip().upper()
        else:
            self.country_code = "ES"

        if self.phone_store:
            self.phone_store = self.phone_store.strip()

        if self.email_store:
            self.email_store = self.email_store.strip().lower()

        # Generar código automáticamente si está vacío
        if not self.code and self.name and self.business_id:
            business_slug = slugify(self.business.name)[:4].upper()
            store_slug = slugify(self.name)[:4].upper()
            self.code = f"{business_slug}-{store_slug}"

        if not self.name:
            errors["name"] = "El nombre de la tienda es obligatorio."

        if not self.business_id:
            errors["business"] = "La tienda debe pertenecer a un negocio."

        if not self.code:
            errors["code"] = "El código de tienda es obligatorio."

        if self.code and not re.fullmatch(r"[A-Z0-9_-]+", self.code):
            errors["code"] = (
                "El código de tienda solo puede contener letras mayúsculas, "
                "números, guiones y guiones bajos."
            )

        if not self.country_code:
            errors["country_code"] = "El código de país es obligatorio."

        elif len(self.country_code) != 2 or not self.country_code.isalpha():
            errors["country_code"] = (
                "El código de país debe tener 2 letras. Ejemplo: ES."
            )

        if self.postal_code and self.country_code == "ES":
            if len(self.postal_code) != 5 or not self.postal_code.isdigit():
                errors["postal_code"] = (
                    "El código postal debe tener exactamente 5 caracteres "
                    "y contener solo dígitos."
                )

        if self.phone_store:
            if not re.fullmatch(r"[0-9+\-\s()]{6,30}", self.phone_store):
                errors["phone_store"] = (
                    "El teléfono de la tienda solo puede contener números, "
                    "espacios, +, guiones o paréntesis."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        Ejecutamos full_clean antes de guardar.

        El código se genera automáticamente dentro de clean() si no existe.

        Esto mantiene el mismo estilo que ya tienes en otros modelos del proyecto,
        como CustomUser y UserStoreAccess.
        """
        self.full_clean()
        return super().save(*args, **kwargs)
