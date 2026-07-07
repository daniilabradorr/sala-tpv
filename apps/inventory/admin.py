"""Admin del módulo inventory.

Reglas importantes:
- InventoryItem muestra la foto actual del stock.
- StockMovement es auditoría: no se edita ni se borra desde admin.
- StockAdjustment puede tener líneas.
- Confirmar ajustes NO se hace desde admin directamente.
- current_stock no se edita manualmente desde admin.
"""

from django.contrib import admin

from apps.inventory.models import (
    InventoryItem,
    StockAdjustment,
    StockAdjustmentLine,
    StockMovement,
)


# ==========================================================
# InventoryItem
# ==========================================================


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    """Admin de fichas de inventario."""

    list_display = (
        "product",
        "store",
        "business",
        "current_stock",
        "reserved_stock",
        "available_stock_display",
        "minimum_stock",
        "maximum_stock",
        "needs_restock_display",
        "location",
        "is_active",
    )

    list_filter = (
        "business",
        "store",
        "is_active",
    )

    search_fields = (
        "product__name",
        "product__sku",
        "product__barcode",
        "store__name",
        "location",
    )

    readonly_fields = (
        "current_stock",
        "reserved_stock",
        "available_stock_display",
        "needs_restock_display",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "business",
        "store",
        "product",
    )

    fieldsets = (
        (
            "Relaciones",
            {
                "fields": (
                    "business",
                    "store",
                    "product",
                )
            },
        ),
        (
            "Stock actual",
            {
                "fields": (
                    "current_stock",
                    "reserved_stock",
                    "available_stock_display",
                )
            },
        ),
        (
            "Configuración",
            {
                "fields": (
                    "minimum_stock",
                    "maximum_stock",
                    "location",
                    "is_active",
                    "needs_restock_display",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def available_stock_display(self, obj):
        """Muestra stock disponible."""

        return obj.available_stock

    available_stock_display.short_description = "Stock disponible"

    def needs_restock_display(self, obj):
        """Indica si necesita reposición."""

        return obj.needs_restock

    needs_restock_display.boolean = True
    needs_restock_display.short_description = "Necesita reposición"


# ==========================================================
# StockAdjustmentLine Inline
# ==========================================================


class StockAdjustmentLineInline(admin.TabularInline):
    """Líneas dentro de un ajuste de stock."""

    model = StockAdjustmentLine
    extra = 0

    fields = (
        "inventory_item",
        "product",
        "system_stock",
        "counted_stock",
        "difference",
        "notes",
    )

    readonly_fields = (
        "product",
        "system_stock",
        "difference",
    )

    autocomplete_fields = ("inventory_item",)

    def get_queryset(self, request):
        """Optimiza consultas de líneas."""

        return (
            super()
            .get_queryset(request)
            .select_related(
                "adjustment",
                "inventory_item",
                "product",
            )
        )

    def get_readonly_fields(self, request, obj=None):
        """Si el ajuste no está en borrador, toda la línea queda bloqueada."""

        base_readonly_fields = list(super().get_readonly_fields(request, obj))

        if obj and not obj.is_draft:
            return (
                "inventory_item",
                "product",
                "system_stock",
                "counted_stock",
                "difference",
                "notes",
            )

        return base_readonly_fields

    def has_add_permission(self, request, obj=None):
        """Solo se pueden añadir líneas si el ajuste está en borrador."""

        if obj and not obj.is_draft:
            return False

        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """Solo se pueden borrar líneas si el ajuste está en borrador."""

        if obj and not obj.is_draft:
            return False

        return super().has_delete_permission(request, obj)


# ==========================================================
# StockAdjustment
# ==========================================================


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    """Admin de ajustes de stock."""

    list_display = (
        "code",
        "business",
        "store",
        "status",
        "reason",
        "created_by",
        "confirmed_by",
        "created_at",
        "confirmed_at",
    )

    list_filter = (
        "business",
        "store",
        "status",
        "reason",
        "created_at",
        "confirmed_at",
    )

    search_fields = (
        "code",
        "store__name",
        "notes",
        "created_by__email",
        "confirmed_by__email",
    )

    readonly_fields = (
        "code",
        "confirmed_at",
        "confirmed_by",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "business",
        "store",
        "created_by",
        "confirmed_by",
    )

    inlines = (StockAdjustmentLineInline,)

    fieldsets = (
        (
            "Datos del ajuste",
            {
                "fields": (
                    "business",
                    "store",
                    "code",
                    "status",
                    "reason",
                    "notes",
                )
            },
        ),
        (
            "Usuarios",
            {
                "fields": (
                    "created_by",
                    "confirmed_by",
                )
            },
        ),
        (
            "Fechas",
            {
                "fields": (
                    "confirmed_at",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """Optimiza consultas de ajustes."""

        return (
            super()
            .get_queryset(request)
            .select_related(
                "business",
                "store",
                "created_by",
                "confirmed_by",
            )
        )

    def get_readonly_fields(self, request, obj=None):
        """Si el ajuste no está en borrador, se bloquea la edición."""

        readonly_fields = list(super().get_readonly_fields(request, obj))

        if obj and not obj.is_draft:
            readonly_fields.extend(
                [
                    "business",
                    "store",
                    "status",
                    "reason",
                    "notes",
                    "created_by",
                ]
            )

        return readonly_fields

    def save_model(self, request, obj, form, change):
        """Asigna created_by automáticamente al crear."""

        if not change and not obj.created_by_id:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)


# ==========================================================
# StockAdjustmentLine
# ==========================================================


@admin.register(StockAdjustmentLine)
class StockAdjustmentLineAdmin(admin.ModelAdmin):
    """Admin independiente de líneas de ajuste."""

    list_display = (
        "adjustment",
        "product",
        "inventory_item",
        "system_stock",
        "counted_stock",
        "difference",
        "created_at",
    )

    list_filter = (
        "adjustment__business",
        "adjustment__store",
        "adjustment__status",
        "created_at",
    )

    search_fields = (
        "adjustment__code",
        "product__name",
        "inventory_item__product__name",
        "notes",
    )

    readonly_fields = (
        "product",
        "system_stock",
        "difference",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "adjustment",
        "inventory_item",
    )

    list_select_related = (
        "adjustment",
        "inventory_item",
        "product",
    )

    fieldsets = (
        (
            "Ajuste",
            {
                "fields": (
                    "adjustment",
                    "inventory_item",
                    "product",
                )
            },
        ),
        (
            "Conteo",
            {
                "fields": (
                    "system_stock",
                    "counted_stock",
                    "difference",
                    "notes",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """Optimiza consultas de líneas."""

        return (
            super()
            .get_queryset(request)
            .select_related(
                "adjustment",
                "inventory_item",
                "product",
            )
        )

    def get_readonly_fields(self, request, obj=None):
        """Si el ajuste no está en borrador, se bloquea toda la línea."""

        readonly_fields = list(super().get_readonly_fields(request, obj))

        if obj and not obj.adjustment.is_draft:
            readonly_fields.extend(
                [
                    "adjustment",
                    "inventory_item",
                    "counted_stock",
                    "notes",
                ]
            )

        return readonly_fields

    def has_delete_permission(self, request, obj=None):
        """Solo permite borrar si el ajuste está en borrador."""

        if obj and not obj.adjustment.is_draft:
            return False

        return super().has_delete_permission(request, obj)


# ==========================================================
# StockMovement
# ==========================================================


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Admin de movimientos de stock.

    IMPORTANTE:
    StockMovement es auditoría.
    No se debe editar ni borrar manualmente.
    """

    list_display = (
        "occurred_at",
        "business",
        "store",
        "product",
        "movement_type",
        "direction_display",
        "quantity",
        "stock_before",
        "stock_after",
        "reference_type",
        "reference_id",
        "created_by",
    )

    list_filter = (
        "business",
        "store",
        "movement_type",
        "reference_type",
        "occurred_at",
    )

    search_fields = (
        "product__name",
        "product__sku",
        "product__barcode",
        "store__name",
        "reference_id",
        "reason",
        "notes",
        "created_by__email",
    )

    readonly_fields = (
        "business",
        "inventory_item",
        "store",
        "product",
        "stock_adjustment_line",
        "movement_type",
        "quantity",
        "stock_before",
        "stock_after",
        "unit_cost",
        "reference_type",
        "reference_id",
        "operation_id",
        "reason",
        "notes",
        "occurred_at",
        "created_by",
        "direction_display",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "business",
        "inventory_item",
        "store",
        "product",
        "created_by",
        "stock_adjustment_line",
    )

    fieldsets = (
        (
            "Movimiento",
            {
                "fields": (
                    "business",
                    "inventory_item",
                    "store",
                    "product",
                    "movement_type",
                    "direction_display",
                    "quantity",
                )
            },
        ),
        (
            "Stock",
            {
                "fields": (
                    "stock_before",
                    "stock_after",
                    "unit_cost",
                )
            },
        ),
        (
            "Referencia",
            {
                "fields": (
                    "reference_type",
                    "reference_id",
                    "operation_id",
                    "stock_adjustment_line",
                )
            },
        ),
        (
            "Información adicional",
            {
                "fields": (
                    "reason",
                    "notes",
                    "occurred_at",
                    "created_by",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def direction_display(self, obj):
        """Muestra si el movimiento es entrada, salida o regularización."""

        if obj.is_incoming:
            return "Entrada"

        if obj.is_outgoing:
            return "Salida"

        return "Regularización"

    direction_display.short_description = "Dirección"

    def has_add_permission(self, request):
        """No se crean movimientos manualmente desde admin."""

        return False

    def has_change_permission(self, request, obj=None):
        """Se permite entrar a ver, pero no editar campos."""

        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """No se borran movimientos de auditoría."""

        return False
