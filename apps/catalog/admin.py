from django.contrib import admin

from apps.catalog.models import Category, Tax, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """
    Admin de las categorías de productos/servicios de un negocio.

    Permite gestionar las categorías por empresa, consultar sus datos
    y modificarlos.
    """

    list_display = (
        "name",
        "slug",
        "business",
        "parent",
        "sort_order",
        "is_active",
    )

    list_display_links = ("name",)

    list_editable = (
        "sort_order",
        "is_active",
    )

    list_filter = (
        "business",
        "parent",
        "is_active",
    )

    search_fields = (
        "name",
        "slug",
        "parent__name",
        "business__name",
    )

    ordering = (
        "business",
        "sort_order",
        "name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "business",
        "parent",
    )

    list_per_page = 25

    fieldsets = (
        (
            "Datos principales",
            {
                "fields": (
                    "business",
                    "name",
                    "slug",
                    "parent",
                )
            },
        ),
        (
            "Visualización",
            {
                "fields": (
                    "sort_order",
                    "is_active",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    autocomplete_fields = (
        "business",
        "parent",
    )


@admin.register(Tax)
class TaxAdmin(admin.ModelAdmin):
    """
    Admin de impuestos/tratamientos fiscales.

    Aquí se configuran los impuestos disponibles por negocio:
    IVA 21%, IVA 10%, IVA 4%, exentos, no sujetos, etc.
    """

    list_display = (
        "name",
        "code",
        "business",
        "tax_type",
        "rate",
        "clave_regimen",
        "calificacion_operacion",
        "operacion_exenta",
        "has_equivalence_surcharge",
        "equivalence_surcharge_rate",
        "is_default",
        "is_active",
    )

    list_display_links = ("name",)

    list_filter = (
        "business",
        "tax_type",
        "clave_regimen",
        "calificacion_operacion",
        "operacion_exenta",
        "is_default",
        "is_active",
        "has_equivalence_surcharge",
    )

    search_fields = (
        "name",
        "code",
        "business__name",
    )

    ordering = (
        "business",
        "-is_default",
        "name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = ("business",)

    list_per_page = 25

    fieldsets = (
        (
            "Datos principales",
            {
                "fields": (
                    "business",
                    "name",
                    "code",
                    "tax_type",
                    "rate",
                )
            },
        ),
        (
            "Configuración fiscal Verifactu",
            {
                "fields": (
                    "clave_regimen",
                    "calificacion_operacion",
                    "operacion_exenta",
                )
            },
        ),
        (
            "Recargo de equivalencia",
            {
                "fields": (
                    "has_equivalence_surcharge",
                    "equivalence_surcharge_rate",
                )
            },
        ),
        (
            "Estado",
            {
                "fields": (
                    "is_default",
                    "is_active",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    autocomplete_fields = ("business",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Admin de productos y servicios vendibles en el TPV.

    Product guarda configuración actual.
    SaleLine guardará la foto histórica cuando se venda.
    """

    list_display = (
        "name",
        "sku",
        "barcode",
        "business",
        "category",
        "tax",
        "base_price",
        "sort_order",
        "cost_price",
        "unit",
        "track_stock",
        "is_service",
        "is_active",
    )

    list_display_links = ("name",)

    list_editable = (
        "is_active",
        "sort_order",
    )

    list_filter = (
        "business",
        "category",
        "tax",
        "unit",
        "track_stock",
        "is_service",
        "is_active",
    )

    search_fields = (
        "name",
        "sku",
        "barcode",
        "category__name",
        "tax__name",
        "business__name",
    )

    ordering = (
        "business",
        "name",
        "category",
        "sort_order",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "business",
        "category",
        "tax",
    )

    list_per_page = 25

    fieldsets = (
        (
            "Datos principales",
            {
                "fields": (
                    "business",
                    "name",
                    "sku",
                    "barcode",
                    "category",
                    "tax",
                )
            },
        ),
        (
            "Precios",
            {
                "fields": (
                    "base_price",
                    "cost_price",
                )
            },
        ),
        (
            "Tipo de producto",
            {
                "fields": (
                    "unit",
                    "is_service",
                    "track_stock",
                )
            },
        ),
        (
            "Visualización",
            {"fields": ("sort_order",)},
        ),
        (
            "Estado",
            {"fields": ("is_active",)},
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    autocomplete_fields = (
        "business",
        "category",
        "tax",
    )
