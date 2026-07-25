import re

from django.db import models
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.db.models import Q
from django.db import transaction

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
        address_line_1 (CharField): Dirección principal de la tienda.
        address_line_2 (CharField): Dirección secundaria de la tienda.
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
    )
    is_default = models.BooleanField(
        "Tienda predeterminada",
        default=False,
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
        default=True,
    )

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
            models.UniqueConstraint(
                fields=["business"],
                condition=Q(is_default=True),
                name="unique_default_store_per_business",
            ),
            models.CheckConstraint(
                condition=Q(code__isnull=False) & ~Q(code=""),
                name="store_code_not_null_or_empty",
            ),
            models.CheckConstraint(
                condition=Q(is_default=False) | Q(is_active=True),
                name="store_default_requires_active",
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

    def _build_base_code(self) -> str:
        """Genera la base del código antes de aplicar unicidad."""

        business_name = getattr(self.business, "name", "") or ""
        store_name = self.name or ""

        b_slug = slugify(business_name)[:10].upper().replace("-", "")
        s_slug = slugify(store_name)[:10].upper().replace("-", "")

        if not b_slug:
            b_slug = "BUSINESS"

        if not s_slug:
            s_slug = "STORE"

        base_code = f"{b_slug}-{s_slug}"[:20]

        if base_code.endswith("-"):
            base_code = base_code[:-1]

        return base_code or "STORE"

    def generate_unique_code(self) -> str:
        """
        Genera un código único para la tienda basado en el nombre de la tienda y el negocio.
        Si el código generado ya existe, se añade un sufijo numérico para garantizar la unicidad.

        Returns:
            str: Código único generado para la tienda.
        """
        base_code = self._build_base_code()
        candidate_code = base_code
        counter = 2

        queryset = Store.objects.filter(
            business_id=self.business_id,
            code=candidate_code,
        )

        if self.pk:
            queryset = queryset.exclude(pk=self.pk)

        while queryset.exists():
            suffix = f"-{counter}"
            max_base_len = 20 - len(suffix)
            candidate_code = f"{base_code[:max_base_len]}{suffix}"

            queryset = Store.objects.filter(
                business_id=self.business_id,
                code=candidate_code,
            )

            if self.pk:
                queryset = queryset.exclude(pk=self.pk)

            counter += 1

        return candidate_code

    def clean(self):
        """
        Validaciones del modelo.

        Normaliza entradas y valida reglas de dominio.
        """
        super().clean()

        errors = {}

        if self.name:
            self.name = self.name.strip()

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

        if self.business_id and self.name and not self.code:
            self.code = self.generate_unique_code()

        if not self.name:
            errors["name"] = "El nombre de la tienda es obligatorio."

        if not self.business_id:
            errors["business"] = "La tienda debe pertenecer a un negocio."

        if not self.code:
            errors["code"] = "El código de tienda es obligatorio."

        if self.code and len(self.code) > 20:
            errors["code"] = "El código de tienda no puede superar 20 caracteres."

        if self.code and not re.fullmatch(r"[A-Z0-9_-]+", self.code):
            errors["code"] = (
                "El código de tienda solo puede contener letras mayúsculas, "
                "números, guiones y guiones bajos."
            )

        if self.is_default and not self.is_active:
            errors["is_default"] = (
                "No se puede marcar como predeterminada una tienda inactiva."
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
        """Guarda la tienda preservando invariantes de código y predeterminada."""
        with transaction.atomic():
            if self.business_id:
                try:
                    Business.objects.select_for_update().only("pk").get(
                        pk=self.business_id
                    )
                except Business.DoesNotExist as exc:
                    raise ValidationError(
                        {"business": "La tienda debe pertenecer a un negocio valido."}
                    ) from exc

            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                update_fields = set(update_fields)

            if self.business_id and self.name and not self.code:
                self.code = self.generate_unique_code()

                if update_fields is not None:
                    update_fields.add("code")

            if not self.is_active and self.is_default:
                self.is_default = False

                if update_fields is not None:
                    update_fields.add("is_default")

            if self.business_id and self.is_active and not self.is_default:
                default_exists = Store.objects.filter(
                    business_id=self.business_id,
                    is_default=True,
                    is_active=True,
                )

                if self.pk:
                    default_exists = default_exists.exclude(pk=self.pk)

                if not default_exists.exists():
                    self.is_default = True

                    if update_fields is not None:
                        update_fields.add("is_default")

            self.full_clean()

            if update_fields is not None:
                kwargs["update_fields"] = list(update_fields)

            return super().save(*args, **kwargs)
