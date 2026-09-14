from django.contrib import admin

from apps.purchases.models import (
    Purchase,
    PurchaseLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    Supplier,
)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "legal_name", "tax_identifier", "business", "is_active")
    list_filter = ("is_active", "business")
    search_fields = ("name", "legal_name", "tax_identifier", "email", "phone")
    list_select_related = ("business",)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Purchase)
class PurchaseAdmin(ReadOnlyAdmin):
    list_display = ("id", "supplier", "store", "status", "total_amount", "ordered_at")
    list_filter = ("status", "business", "store")
    search_fields = ("reference", "supplier__name", "supplier__tax_identifier")
    list_select_related = ("business", "store", "supplier", "created_by")


@admin.register(PurchaseLine)
class PurchaseLineAdmin(ReadOnlyAdmin):
    list_display = (
        "id",
        "purchase",
        "product_name",
        "quantity_ordered",
        "quantity_received",
        "unit_cost",
    )
    list_filter = ("business",)
    search_fields = ("product_name", "sku", "purchase__reference")
    list_select_related = ("business", "purchase", "product")


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(ReadOnlyAdmin):
    list_display = (
        "id",
        "purchase",
        "store",
        "received_by",
        "received_at",
        "idempotency_key",
    )
    list_filter = ("business", "store")
    search_fields = ("purchase__reference", "idempotency_key")
    list_select_related = ("business", "store", "purchase", "received_by")


@admin.register(PurchaseReceiptLine)
class PurchaseReceiptLineAdmin(ReadOnlyAdmin):
    list_display = ("id", "receipt", "purchase_line", "quantity_received")
    list_filter = ("business",)
    search_fields = ("receipt__purchase__reference", "purchase_line__product_name")
    list_select_related = ("business", "receipt", "purchase_line")
