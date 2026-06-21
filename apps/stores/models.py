from django.db import models
from django.core.exceptions import ValidationError

from apps.core.models import Business, TimeStampedModel


class Stores(TimeStampedModel):
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
        # TEMPORAL:
        # Permitimos NULL en base de datos para que Django pueda crear la migración
        # sin pedir un valor por defecto para tiendas antiguas.
        null=True,
        # TEMPORAL:
        # Permitimos dejarlo vacío en formularios/admin durante esta fase puente.
        blank=True,
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

    adress_line_1 = models.CharField(
        "Dirección Principal", max_length=150, blank=True, null=True
    )
    adress_line_2 = models.CharField(
        "Dirección Secundaria", max_length=150, blank=True, null=True
    )

    postal_code = models.CharField(
        "Código Postal", max_length=10, blank=True, null=True
    )
    city = models.CharField("Ciudad", max_length=120, blank=True, null=True)
    province = models.CharField("Provincia", max_length=120, blank=True, null=True)

    country_code = models.CharField(
        "Código país ISO", max_length=4, blank=False, null=False, default="ES"
    )

    phone_store = models.CharField(
        "Teléfono de la tienda", max_length=12, blank=True, null=True
    )
    email_store = models.CharField(
        "email de la tienda", max_length=120, blank=True, null=True
    )
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
        if self.business and self.business.profile:
            return self.business.profile.phone
        return ""

    @property
    def contact_email(self):
        if self.email_store:
            return self.email_store
        if self.business and self.business.profile:
            return self.business.profile.email
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

        if self.code:
            self.code = self.code.strip().upper()

        if not self.name:
            errors["name"] = "El nombre de la tienda es obligatorio."

        # NO validamos todavía:
        #
        # if not self.business_id:
        #     errors["business"] = "La tienda debe pertenecer a un negocio."
        #
        # Esto lo activaremos más adelante cuando stores esté bien implementado
        # y hayamos hecho una migración de datos para rellenar business en todas
        # las tiendas existentes.

        # NO validamos todavía:
        #
        # if not self.code:
        #     errors["code"] = "El código de tienda es obligatorio."
        #
        # Esto también lo activaremos más adelante.
        # Ahora code tiene default="" para evitar problemas de migración.

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        Ejecutamos full_clean antes de guardar.

        Esto mantiene el mismo estilo que ya tienes en otros modelos del proyecto,
        como CustomUser y UserStoreAccess.

        Así, aunque se cree una tienda desde shell, admin o código interno,
        se aplican las validaciones del modelo.
        """
        self.full_clean()
        return super().save(*args, **kwargs)
