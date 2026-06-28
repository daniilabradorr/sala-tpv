from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from apps.core.models import Business, TimeStampedModel
from decimal import Decimal


class Category(TimeStampedModel):
    """
    Categoría comercial de productos/servicios.

    Sirve para organizar el catálogo dentro de cada negocio.
    Ejemplos:
    - Bebidas
    - Ropa
    - Servicios
    - Accesorios
    """

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="categories",
    )
    name = models.CharField(
        "Nombre de la categoria",
        max_length=150,
        blank=False,
    )
    slug = models.SlugField(
        "Etiqueta de la categoria",
        max_length=150,
        blank=True,
    )
    parent = models.ForeignKey(
        "self",
        verbose_name="Categoría padre",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    sort_order = models.PositiveIntegerField(
        "Orden visual",
        blank=True,
        default=0,
    )
    is_active = models.BooleanField(
        "Esta activa la categoria?",
        blank=True,
        default=True,
    )

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "slug"],
                name="unique_category_slug_per_business",
            )
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        if self.parent and self.parent == self:
            raise ValidationError(
                {"parent": "Una categoría no puede ser padre de sí misma."}
            )

        if self.parent and self.parent.business_id != self.business_id:
            raise ValidationError(
                {"parent": "La categoría padre debe pertenecer al mismo negocio."}
            )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()

        self.full_clean()
        super().save(*args, **kwargs)

    def _generate_unique_slug(self):
        base_slug = slugify(self.name)
        slug = base_slug
        counter = 1

        while (
            Category.objects.filter(
                business=self.business,
                slug=slug,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            counter += 1
            slug = f"{base_slug}-{counter}"

        return slug


# el modelo de impuesto
"""Este modelo tendra uno genraciñopn por dfecto y el primoridal
    que sera el IVA, ya que en españa es 100% obligatorio.
    
    Luego teng qu ejugar de si mostrar los percios con o sin iva y si hacer yo mismo los calculos
"""


class Tax(TimeStampedModel):
    """
    Impuesto o tratamiento fiscal aplicable a productos/servicios.

    IMPORTANTE:
    Este modelo NO representa una factura.
    Este modelo representa cómo tributa un producto o servicio.

    Ejemplos:
    - IVA 21%
    - IVA 10%
    - IVA 4%
    - Exento IVA art. 20
    - No sujeto por reglas de localización
    - Inversión del sujeto pasivo

    Luego, cuando vendas un producto:
    Product -> Tax -> SaleLine -> BillingDocumentLine -> BillingTaxBreakdown -> Verifacti

    Tax funciona como una plantilla fiscal.
    En la venta/factura deberás copiar sus valores para guardar histórico.
    """

    # ==========================================================
    # 1. TIPO DE IMPUESTO
    # ==========================================================
    #
    # Esto responde a:
    # "¿Qué impuesto estamos usando?"
    #
    # Según la lista oficial:
    # 01 = IVA
    # 02 = IPSI Ceuta/Melilla
    # 03 = IGIC Canarias
    # 05 = Otros
    #
    # Para tu MVP en España península/Baleares:
    # normalmente usarás IVA.
    # ==========================================================

    TAX_TYPE_IVA = "IVA"
    TAX_TYPE_IGIC = "IGIC"
    TAX_TYPE_IPSI = "IPSI"
    TAX_TYPE_OTHER = "OTHER"

    TAX_TYPE_CHOICES = [
        (TAX_TYPE_IVA, "IVA - Impuesto sobre el Valor Añadido"),
        (TAX_TYPE_IGIC, "IGIC - Canarias"),
        (TAX_TYPE_IPSI, "IPSI - Ceuta/Melilla"),
        (TAX_TYPE_OTHER, "Otro impuesto"),
    ]

    # ==========================================================
    # 2. CLAVE DE RÉGIMEN
    # ==========================================================
    #
    # Esto responde a:
    # "¿La operación va por régimen general o por algún régimen especial?"
    #
    # Para un TPV normal:
    # 01 = Operación de régimen general
    #
    # Ese será el caso habitual:
    # - tienda de ropa
    # - bar
    # - peluquería
    # - ferretería
    # - taller
    # - venta normal con IVA
    #
    # Otros casos:
    # 02 = Exportación
    # 03 = Bienes usados / objetos de arte / antigüedades / colección
    # 04 = Oro de inversión
    # 05 = Agencias de viajes
    # 06 = Grupo de entidades IVA
    # 07 = Criterio de caja
    # 08 = Operaciones sujetas a IPSI/IGIC
    # 09 = Servicios de agencias de viaje mediadoras
    # 10 = Cobros por cuenta de terceros
    # 11 = Arrendamiento de local de negocio
    # 14 = IVA pendiente de devengo en certificaciones de obra pública
    # 15 = IVA pendiente de devengo en operaciones de tracto sucesivo
    # 17 = OSS / IOSS
    # 18 = Recargo de equivalencia
    # 19 = REAGYP
    # 20 = Régimen simplificado
    #
    # Recomendación MVP:
    # Puedes guardar "01" en los impuestos normales,
    # o dejarlo null y que el builder de Verifacti envíe "01" por defecto.
    # Yo prefiero guardarlo ya como "01" para IVA normal.
    # ==========================================================

    REGIMEN_GENERAL = "01"
    REGIMEN_EXPORTACION = "02"
    REGIMEN_BIENES_USADOS = "03"
    REGIMEN_ORO_INVERSION = "04"
    REGIMEN_AGENCIAS_VIAJES = "05"
    REGIMEN_GRUPO_ENTIDADES = "06"
    REGIMEN_CRITERIO_CAJA = "07"
    REGIMEN_IPSI_IGIC = "08"
    REGIMEN_AGENCIAS_VIAJE_MEDIADORAS = "09"
    REGIMEN_COBROS_TERCEROS = "10"
    REGIMEN_ARRENDAMIENTO_LOCAL = "11"
    REGIMEN_OBRA_PUBLICA_IVA_PENDIENTE = "14"
    REGIMEN_TRACTO_SUCESIVO_IVA_PENDIENTE = "15"
    REGIMEN_OSS_IOSS = "17"
    REGIMEN_RECARGO_EQUIVALENCIA = "18"
    REGIMEN_REAGYP = "19"
    REGIMEN_SIMPLIFICADO = "20"

    CLAVE_REGIMEN_CHOICES = [
        (REGIMEN_GENERAL, "01 - Operación de régimen general"),
        (REGIMEN_EXPORTACION, "02 - Exportación"),
        (
            REGIMEN_BIENES_USADOS,
            "03 - Régimen especial de bienes usados, arte, antigüedades y colección",
        ),
        (REGIMEN_ORO_INVERSION, "04 - Régimen especial del oro de inversión"),
        (REGIMEN_AGENCIAS_VIAJES, "05 - Régimen especial de agencias de viajes"),
        (REGIMEN_GRUPO_ENTIDADES, "06 - Grupo de entidades en IVA"),
        (REGIMEN_CRITERIO_CAJA, "07 - Régimen especial del criterio de caja"),
        (REGIMEN_IPSI_IGIC, "08 - Operaciones sujetas a IPSI/IGIC"),
        (
            REGIMEN_AGENCIAS_VIAJE_MEDIADORAS,
            "09 - Agencias de viaje mediadoras en nombre y por cuenta ajena",
        ),
        (REGIMEN_COBROS_TERCEROS, "10 - Cobros por cuenta de terceros"),
        (REGIMEN_ARRENDAMIENTO_LOCAL, "11 - Arrendamiento de local de negocio"),
        (
            REGIMEN_OBRA_PUBLICA_IVA_PENDIENTE,
            "14 - IVA pendiente de devengo en certificaciones de obra pública",
        ),
        (
            REGIMEN_TRACTO_SUCESIVO_IVA_PENDIENTE,
            "15 - IVA pendiente de devengo en operaciones de tracto sucesivo",
        ),
        (REGIMEN_OSS_IOSS, "17 - OSS / IOSS"),
        (REGIMEN_RECARGO_EQUIVALENCIA, "18 - Recargo de equivalencia"),
        (
            REGIMEN_REAGYP,
            "19 - Régimen especial de agricultura, ganadería y pesca",
        ),
        (REGIMEN_SIMPLIFICADO, "20 - Régimen simplificado"),
    ]

    # ==========================================================
    # 3. CALIFICACIÓN DE OPERACIÓN
    # ==========================================================
    #
    # Esto responde a:
    # "Fiscalmente, esta línea está sujeta, no sujeta o con inversión?"
    #
    # NO es el tipo de factura.
    #
    # Tipos de factura:
    # F1, F2, F3, R1, R2, R3, R4, R5
    # -> Eso va en BillingDocument.
    #
    # Calificación de operación:
    # S1, S2, N1, N2
    # -> Esto va en Tax / SaleLine / BillingTaxBreakdown.
    #
    # S1:
    # Operación sujeta y no exenta, sin inversión del sujeto pasivo.
    # Es la venta normal con IVA.
    #
    # S2:
    # Operación sujeta y no exenta, con inversión del sujeto pasivo.
    # El vendedor no repercute/cobra IVA; lo declara el destinatario.
    #
    # N1:
    # Operación no sujeta por artículo 7, 14 u otros.
    # No entra en el IVA por causa legal.
    #
    # N2:
    # Operación no sujeta por reglas de localización.
    # Por ejemplo, ciertos servicios a clientes extranjeros.
    #
    # Para tu MVP:
    # IVA 21%, IVA 10%, IVA 4% => S1.
    # ==========================================================

    CALIFICACION_SUJETA_NO_EXENTA = "S1"
    CALIFICACION_INVERSION_SUJETO_PASIVO = "S2"
    CALIFICACION_NO_SUJETA_ART_7_14 = "N1"
    CALIFICACION_NO_SUJETA_LOCALIZACION = "N2"

    CALIFICACION_OPERACION_CHOICES = [
        (
            CALIFICACION_SUJETA_NO_EXENTA,
            "S1 - Sujeta y no exenta, sin inversión del sujeto pasivo",
        ),
        (
            CALIFICACION_INVERSION_SUJETO_PASIVO,
            "S2 - Sujeta y no exenta, con inversión del sujeto pasivo",
        ),
        (
            CALIFICACION_NO_SUJETA_ART_7_14,
            "N1 - No sujeta por artículo 7, 14 u otros",
        ),
        (
            CALIFICACION_NO_SUJETA_LOCALIZACION,
            "N2 - No sujeta por reglas de localización",
        ),
    ]

    # ==========================================================
    # 4. OPERACIÓN EXENTA
    # ==========================================================
    #
    # Esto responde a:
    # "Si esta operación está exenta de IVA, ¿por qué artículo/causa?"
    #
    # OJO:
    # Exenta NO es lo mismo que No Sujeta.
    #
    # Exenta:
    # Está dentro del ámbito del IVA, pero la ley dice que no se cobra IVA.
    #
    # No sujeta:
    # Directamente no entra en el IVA.
    #
    # Claves:
    # E1 = Exenta por artículo 20
    # E2 = Exenta por artículo 21
    # E3 = Exenta por artículo 22
    # E4 = Exenta por artículos 23 y 24
    # E5 = Exenta por artículo 25
    # E6 = Exenta por otros
    #
    # Regla:
    # Si operacion_exenta tiene valor, normalmente rate debe ser 0.00
    # y calificacion_operacion debe quedar vacía.
    #
    # Para IVA normal:
    # operacion_exenta = None
    # ==========================================================

    EXENTA_ART_20 = "E1"
    EXENTA_ART_21 = "E2"
    EXENTA_ART_22 = "E3"
    EXENTA_ART_23_24 = "E4"
    EXENTA_ART_25 = "E5"
    EXENTA_OTRAS = "E6"

    OPERACION_EXENTA_CHOICES = [
        (EXENTA_ART_20, "E1 - Exenta por artículo 20"),
        (EXENTA_ART_21, "E2 - Exenta por artículo 21"),
        (EXENTA_ART_22, "E3 - Exenta por artículo 22"),
        (EXENTA_ART_23_24, "E4 - Exenta por artículos 23 y 24"),
        (EXENTA_ART_25, "E5 - Exenta por artículo 25"),
        (EXENTA_OTRAS, "E6 - Exenta por otros"),
    ]

    # ==========================================================
    # CAMPOS DEL MODELO
    # ==========================================================

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="taxes",
    )

    name = models.CharField(
        "Nombre del impuesto",
        max_length=100,
        help_text="Ejemplo: IVA 21%, IVA 10%, IVA 4%, Exento IVA art. 20.",
    )

    code = models.CharField(
        "Código interno del impuesto",
        max_length=30,
        blank=True,
        help_text="Ejemplo: IVA_21, IVA_10, IVA_4, EXENTO_E1.",
    )

    tax_type = models.CharField(
        "Tipo de impuesto",
        max_length=20,
        choices=TAX_TYPE_CHOICES,
        default=TAX_TYPE_IVA,
        help_text="Normalmente IVA para península/Baleares.",
    )

    rate = models.DecimalField(
        "Porcentaje impositivo",
        max_digits=5,
        decimal_places=2,
        help_text="Ejemplo: 21.00, 10.00, 4.00, 0.00.",
    )

    clave_regimen = models.CharField(
        "Clave de régimen",
        max_length=2,
        choices=CLAVE_REGIMEN_CHOICES,
        default=REGIMEN_GENERAL,
        blank=True,
        null=True,
        help_text=("Régimen fiscal aplicable. Para venta normal con IVA, usar 01."),
    )

    calificacion_operacion = models.CharField(
        "Calificación de la operación",
        max_length=2,
        choices=CALIFICACION_OPERACION_CHOICES,
        default=CALIFICACION_SUJETA_NO_EXENTA,
        blank=True,
        null=True,
        help_text=(
            "S1 para venta normal con IVA. "
            "S2 para inversión sujeto pasivo. "
            "N1/N2 para operaciones no sujetas."
        ),
    )

    operacion_exenta = models.CharField(
        "Causa de operación exenta",
        max_length=2,
        choices=OPERACION_EXENTA_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Solo se rellena si la operación está exenta. "
            "Ejemplo: E1 para exenta por artículo 20."
        ),
    )

    has_equivalence_surcharge = models.BooleanField(
        "Tiene recargo de equivalencia",
        default=False,
        help_text=(
            "Marcar solo si aplica recargo de equivalencia. "
            "Para MVP normal suele ser False."
        ),
    )

    equivalence_surcharge_rate = models.DecimalField(
        "Porcentaje de recargo de equivalencia",
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Ejemplo: 5.20. Solo si has_equivalence_surcharge=True.",
    )

    is_default = models.BooleanField(
        "Impuesto por defecto",
        default=False,
        help_text=(
            "Solo debe haber un impuesto por defecto por negocio. Normalmente IVA 21%."
        ),
    )

    is_active = models.BooleanField(
        "Impuesto activo",
        default=True,
        help_text=(
            "No borrar impuestos usados históricamente. "
            "Desactivar si ya no se quiere usar."
        ),
    )

    class Meta:
        verbose_name = "Impuesto"
        verbose_name_plural = "Impuestos"
        ordering = ["-is_default", "name"]

        constraints = [
            # Dentro del mismo negocio no puede haber dos impuestos
            # con el mismo código interno.
            models.UniqueConstraint(
                fields=["business", "code"],
                name="unique_tax_code_per_business",
            ),
            # Solo puede haber un impuesto por defecto por negocio.
            #
            # Ejemplo correcto:
            # IVA 21% -> is_default=True
            # IVA 10% -> is_default=False
            # IVA 4%  -> is_default=False
            #
            # Ejemplo incorrecto:
            # IVA 21% -> is_default=True
            # IVA 10% -> is_default=True
            models.UniqueConstraint(
                fields=["business"],
                condition=Q(is_default=True),
                name="unique_default_tax_per_business",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.rate}%)"

    def clean(self):
        """
        Validaciones fiscales básicas.

        OJO:
        Esto no sustituye la validación final del builder de Verifacti.
        Esto solo evita configuraciones claramente incoherentes.
        """

        super().clean()

        if self.rate is None:
            raise ValidationError({"rate": "Debes indicar el porcentaje impositivo."})

        if self.rate < Decimal("0.00"):
            raise ValidationError(
                {"rate": "El porcentaje del impuesto no puede ser negativo."}
            )

        # Si hay operación exenta, normalmente no debe haber calificación S1/S2/N1/N2.
        #
        # Ejemplo correcto:
        # Exento art. 20:
        #   rate = 0.00
        #   calificacion_operacion = None
        #   operacion_exenta = E1
        #
        # Ejemplo incorrecto:
        #   calificacion_operacion = S1
        #   operacion_exenta = E1
        #
        # Como el campo calificacion_operacion tiene default S1, permitimos
        # que si el usuario marca exenta y no ha tocado nada, se limpie.
        if self.operacion_exenta:
            if self.calificacion_operacion not in (
                None,
                "",
                self.CALIFICACION_SUJETA_NO_EXENTA,
            ):
                raise ValidationError(
                    {
                        "calificacion_operacion": (
                            "No puedes informar calificación de operación y "
                            "operación exenta a la vez."
                        )
                    }
                )

            self.calificacion_operacion = None

            if self.rate != Decimal("0.00"):
                raise ValidationError(
                    {
                        "rate": (
                            "Si la operación está exenta, el porcentaje debe ser 0.00."
                        )
                    }
                )

        # Si NO hay operación exenta, debe haber una calificación.
        #
        # Para venta normal:
        #   calificacion_operacion = S1
        #   operacion_exenta = None
        if not self.operacion_exenta and not self.calificacion_operacion:
            self.calificacion_operacion = self.CALIFICACION_SUJETA_NO_EXENTA

        # Operaciones no sujetas: N1/N2.
        #
        # Normalmente no llevan tipo impositivo ni cuota repercutida.
        # En el catálogo las representamos con rate=0.00 para que el cálculo
        # interno no genere cuota.
        if self.calificacion_operacion in (
            self.CALIFICACION_NO_SUJETA_ART_7_14,
            self.CALIFICACION_NO_SUJETA_LOCALIZACION,
        ):
            if self.rate != Decimal("0.00"):
                raise ValidationError(
                    {
                        "rate": (
                            "Si la operación es no sujeta N1/N2, "
                            "el porcentaje debe ser 0.00."
                        )
                    }
                )

        # Recargo de equivalencia.
        #
        # Si no está marcado, no debe tener porcentaje.
        if not self.has_equivalence_surcharge and self.equivalence_surcharge_rate:
            raise ValidationError(
                {
                    "equivalence_surcharge_rate": (
                        "No puedes informar recargo si el impuesto no tiene "
                        "recargo de equivalencia."
                    )
                }
            )

        # Si está marcado, debe tener porcentaje.
        if self.has_equivalence_surcharge and self.equivalence_surcharge_rate is None:
            raise ValidationError(
                {
                    "equivalence_surcharge_rate": (
                        "Debes indicar el porcentaje de recargo de equivalencia."
                    )
                }
            )

        if (
            self.equivalence_surcharge_rate is not None
            and self.equivalence_surcharge_rate < Decimal("0.00")
        ):
            raise ValidationError(
                {
                    "equivalence_surcharge_rate": (
                        "El porcentaje de recargo no puede ser negativo."
                    )
                }
            )

        # Si tiene recargo de equivalencia, normalmente la clave de régimen
        # será 18. Lo dejo como validación suave: lo autocorrige.
        if self.has_equivalence_surcharge:
            self.clave_regimen = self.REGIMEN_RECARGO_EQUIVALENCIA

    def save(self, *args, **kwargs):
        """
        Genera code automático si no se informa.

        Ejemplo:
        name = "IVA 21%" -> code = "IVA_21"
        name = "Exento IVA art. 20" -> code = "EXENTO_IVA_ART_20"
        """

        if not self.code:
            self.code = self._generate_unique_code()

        self.full_clean()
        super().save(*args, **kwargs)

    def _generate_unique_code(self):
        base_code = slugify(self.name).upper().replace("-", "_")

        if not base_code:
            base_code = "TAX"

        code = base_code
        counter = 1

        while (
            Tax.objects.filter(
                business=self.business,
                code=code,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            counter += 1
            code = f"{base_code}_{counter}"

        return code


# ahora el modelo de los produtos
class Product(TimeStampedModel):
    """
    Producto o servicio vendible en el TPV.

    IMPORTANTE:
    - Product guarda configuración actual del producto.
    - NO guarda el precio final con IVA.
    - base_price siempre es precio base sin IVA.
    - SaleLine guardará la foto histórica cuando se venda.
    - BillingDocumentLine guardará la foto fiscal cuando se facture.
    """

    UNIT_UNIDAD = "ud"
    UNIT_KG = "kg"
    UNIT_GRAMO = "g"
    UNIT_LITRO = "l"
    UNIT_METRO = "m"
    UNIT_HORA = "h"
    UNIT_SERVICIO = "servicio"

    UNIT_CHOICES = [
        (UNIT_UNIDAD, "Unidad"),
        (UNIT_KG, "Kilogramo"),
        (UNIT_GRAMO, "Gramo"),
        (UNIT_LITRO, "Litro"),
        (UNIT_METRO, "Metro"),
        (UNIT_HORA, "Hora"),
        (UNIT_SERVICIO, "Servicio"),
    ]

    business = models.ForeignKey(
        Business,
        verbose_name="Negocio",
        on_delete=models.CASCADE,
        related_name="products",
    )

    category = models.ForeignKey(
        Category,
        verbose_name="Categoría",
        on_delete=models.SET_NULL,
        related_name="products",
        blank=True,
        null=True,
        help_text="Categoría comercial del producto. Opcional.",
    )

    tax = models.ForeignKey(
        Tax,
        verbose_name="Impuesto",
        on_delete=models.PROTECT,
        related_name="products",
        blank=True,
        null=True,
        help_text=(
            "Impuesto específico del producto. "
            "Si se deja vacío, se usará el impuesto por defecto del negocio."
        ),
    )

    name = models.CharField(
        "Nombre del producto",
        max_length=180,
        help_text="Nombre visible en catálogo, venta y ticket.",
    )

    sku = models.CharField(
        "Código interno del producto",
        max_length=80,
        blank=True,
        help_text=(
            "Código interno del producto. "
            "Si se deja vacío, se generará automáticamente."
        ),
    )

    barcode = models.CharField(
        "Código de barras",
        max_length=80,
        blank=True,
        null=True,
        db_index=True,
        help_text=(
            "Código de barras del producto. "
            "Si se deja vacío en productos físicos, se generará uno interno automáticamente. "
            "En servicios no se genera."
        ),
    )

    base_price = models.DecimalField(
        "Precio base sin IVA",
        max_digits=12,
        decimal_places=2,
        help_text=(
            "Precio base sin IVA. "
            "El precio con IVA se calcula en services/views según POSSettings."
        ),
    )

    cost_price = models.DecimalField(
        "Coste de compra",
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Coste del producto para márgenes y reporting. "
            "No se usa para calcular el precio de venta."
        ),
    )

    unit = models.CharField(
        "Unidad",
        max_length=20,
        choices=UNIT_CHOICES,
        default=UNIT_UNIDAD,
        help_text="Unidad de venta: unidad, kg, hora, servicio, etc.",
    )

    track_stock = models.BooleanField(
        "Controla stock",
        default=True,
        help_text=(
            "Indica si este producto afecta al inventario. "
            "Los servicios normalmente no controlan stock."
        ),
    )

    is_service = models.BooleanField(
        "Es un servicio",
        default=False,
        help_text=(
            "Marca si no es un producto físico. "
            "Si es servicio, normalmente track_stock será False."
        ),
    )

    is_active = models.BooleanField(
        "Disponible para venta",
        default=True,
        help_text=(
            "Si está desactivado no aparece para nuevas ventas. "
            "No borrar productos usados históricamente."
        ),
    )

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "sku"],
                name="unique_product_sku_per_business",
            ),
            models.UniqueConstraint(
                fields=["business", "barcode"],
                condition=Q(barcode__isnull=False),
                name="unique_product_barcode_per_business",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """
        Validaciones de coherencia del producto.

        Aquí no calculamos IVA final.
        Eso se hará en services al mostrar o vender.
        """

        super().clean()

        if self.base_price is None:
            raise ValidationError(
                {"base_price": "Debes indicar el precio base sin IVA."}
            )

        if self.base_price < Decimal("0.00"):
            raise ValidationError(
                {"base_price": "El precio base no puede ser negativo."}
            )

        if self.cost_price is not None and self.cost_price < Decimal("0.00"):
            raise ValidationError(
                {"cost_price": "El coste del producto no puede ser negativo."}
            )

        # Normalizamos barcode vacío.
        # Mejor None que string vacío para que la constraint funcione bien.
        if self.barcode == "":
            self.barcode = None

        # Si tiene categoría, debe pertenecer al mismo negocio.
        if self.category and self.category.business_id != self.business_id:
            raise ValidationError(
                {"category": "La categoría debe pertenecer al mismo negocio."}
            )

        # Si tiene impuesto específico, debe pertenecer al mismo negocio.
        if self.tax and self.tax.business_id != self.business_id:
            raise ValidationError(
                {"tax": "El impuesto debe pertenecer al mismo negocio."}
            )

        # Si el impuesto está desactivado, no debería asignarse a productos nuevos.
        if self.tax and not self.tax.is_active:
            raise ValidationError(
                {"tax": "No puedes asignar un impuesto inactivo al producto."}
            )

        # Si es servicio:
        # - No controla stock.
        # - No tiene barcode.
        # - Si no tiene unidad, usamos "servicio".
        if self.is_service:
            self.track_stock = False
            self.barcode = None

            if not self.unit:
                self.unit = self.UNIT_SERVICIO

    def save(self, *args, **kwargs):
        """
        Genera SKU automático si viene vacío.
        Genera barcode interno automático si viene vacío y es producto físico.

        OJO:
        - SKU = código interno del catálogo.
        - barcode = código escaneable.
        - Si el usuario mete un barcode real del fabricante, se respeta.
        - Si es servicio, no se genera barcode.
        """

        if not self.sku:
            self.sku = self._generate_unique_sku()

        if self.barcode == "":
            self.barcode = None

        if not self.barcode and not self.is_service:
            self.barcode = self._generate_unique_barcode()

        self.full_clean()
        super().save(*args, **kwargs)

    def _generate_unique_sku(self):
        """
        Genera un SKU único por negocio a partir del nombre.

        Ejemplo:
        name = "Coca-Cola 500ml"
        sku = "COCA_COLA_500ML"

        Si ya existe:
        COCA_COLA_500ML_2
        COCA_COLA_500ML_3
        """

        base_sku = slugify(self.name).upper().replace("-", "_")

        if not base_sku:
            base_sku = "PRODUCT"

        sku = base_sku
        counter = 1

        while (
            Product.objects.filter(
                business=self.business,
                sku=sku,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            counter += 1
            sku = f"{base_sku}_{counter}"

        return sku

    def _generate_unique_barcode(self):
        """
        Genera un código de barras interno único por negocio.

        IMPORTANTE:
        Esto NO es un EAN oficial de fabricante.
        Es un código interno del TPV para poder imprimir etiquetas
        y escanearlas con una lectora compatible con Code128.

        Ejemplo:
        PRD000001
        PRD000002
        PRD000003
        """

        prefix = "PRD"
        counter = 1

        while True:
            barcode = f"{prefix}{counter:06d}"

            exists = (
                Product.objects.filter(
                    business=self.business,
                    barcode=barcode,
                )
                .exclude(pk=self.pk)
                .exists()
            )

            if not exists:
                return barcode

            counter += 1
