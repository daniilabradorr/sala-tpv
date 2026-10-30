from django.contrib import admin
from django.core.exceptions import PermissionDenied

from apps.business_config.currency import CURRENCY_BLOCK_MESSAGE

from apps.business_config.forms import BusinessProfileForm, POSSettingsForm
from apps.business_config.models import BusinessProfile, POSSettings


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    form = BusinessProfileForm

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.currency_code != "EUR":
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        # Admin bulk deletion skips Model.delete. Check the entire selection
        # before deleting anything, keeping the existing EUR deletion contract.
        if queryset.exclude(currency_code="EUR").exists():
            raise PermissionDenied(CURRENCY_BLOCK_MESSAGE)
        return super().delete_queryset(request, queryset)

    list_display = (
        "business",
        "legal_name",
        "trade_name",
        "tax_identifier",
        "currency_code",
        "updated_at",
    )
    search_fields = (
        "business__name",
        "legal_name",
        "trade_name",
        "tax_identifier",
        "email",
    )
    list_select_related = ("business",)
    readonly_fields = ("business", "created_at", "updated_at")

    fieldsets = (
        ("Negocio", {"fields": ("business",)}),
        (
            "Datos legales y fiscales",
            {
                "fields": (
                    "legal_name",
                    "tax_identifier",
                    "trade_name",
                )
            },
        ),
        ("Contacto", {"fields": ("phone", "email", "website")}),
        (
            "Dirección",
            {
                "fields": (
                    "address_line_1",
                    "address_line_2",
                    "postal_code",
                    "city",
                    "province",
                    "country_code",
                )
            },
        ),
        (
            "Branding y ticket",
            {
                "fields": (
                    "currency_code",
                    "brand_name",
                    "logo_url",
                    "receipt_footer",
                    "return_policy",
                )
            },
        ),
        ("Auditoría", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(POSSettings)
class POSSettingsAdmin(admin.ModelAdmin):
    form = POSSettingsForm

    list_display = (
        "business",
        "prices_include_tax",
        "enable_stock_control",
        "allow_sale_without_stock",
        "allow_manual_price",
        "allow_manual_discounts",
        "max_manual_discount_percent",
        "require_open_cash_register",
        "allow_split_payments",
        "require_pin_for_sensitive_actions",
        "updated_at",
    )
    list_filter = (
        "prices_include_tax",
        "enable_stock_control",
        "allow_sale_without_stock",
        "allow_manual_price",
        "allow_manual_discounts",
        "require_open_cash_register",
        "allow_split_payments",
        "require_pin_for_sensitive_actions",
    )
    search_fields = ("business__name",)
    list_select_related = ("business",)
    readonly_fields = ("business", "created_at", "updated_at")

    fieldsets = (
        ("Negocio", {"fields": ("business",)}),
        (
            "Operativa del TPV",
            {
                "fields": (
                    "prices_include_tax",
                    "enable_stock_control",
                    "allow_sale_without_stock",
                    "allow_manual_price",
                    "allow_manual_discounts",
                    "max_manual_discount_percent",
                    "require_open_cash_register",
                    "allow_split_payments",
                    "require_pin_for_sensitive_actions",
                )
            },
        ),
        ("Auditoría", {"fields": ("created_at", "updated_at")}),
    )
