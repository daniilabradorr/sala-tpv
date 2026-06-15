from django.db import models
from django.core.exceptions import ValidationError

from apps.core.models import Business


class Stores(models.Model):
    """
    Modelo temporal/mínimo de tiendas.

    IMPORTANTE:
    Este modelo está hecho como versión puente para que el módulo users funcione
    mientras todavía no hemos desarrollado el módulo stores completo.

    Ahora mismo users necesita que Store tenga:
    - business
    - name
    - code
    - is_active

    ¿Por qué business permite null=True temporalmente?
    ----------------------------------------------------
    Porque ya existía una migración antigua de Stores solo con el campo name.

    Antes teníamos:

        class Stores(models.Model):
            name = models.CharField(max_length=100, unique=True)

    Ahora estamos añadiendo business.

    Si business fuera obligatorio desde el primer momento:

        business = models.ForeignKey(Business, on_delete=models.CASCADE)

    Django preguntaría:

        "¿Qué business pongo a las tiendas antiguas?"

    Aunque hayas borrado db.sqlite3, las migraciones antiguas siguen existiendo,
    por eso makemigrations sigue detectando que estamos añadiendo un campo
    obligatorio a una tabla/modelo que ya existía.

    Por eso ahora lo dejamos temporalmente así:

        null=True
        blank=True

    Pero funcionalmente, en el TPV real, una tienda SIEMPRE debe pertenecer
    a un negocio.

    Más adelante, cuando desarrollemos stores bien, cambiaremos esto a:

        null=False
        blank=False

    y haremos una migración limpia después de asegurarnos de que todas las
    tiendas tienen business.
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

    is_active = models.BooleanField(
        "Activa",
        default=True,
    )

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
