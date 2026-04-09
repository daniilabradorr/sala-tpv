from django.contrib import admin

from apps.business_config.forms import BusinessProfileForm, POSSettingsForm
from apps.business_config.models import BusinessProfile, POSSettings


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    form = BusinessProfileForm

    list_display = (
        "business",
        "legal_name",
        "trade_name",
        "tax_identifier",
        "currency_code",
        "default_tax_rate",
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
                    "default_tax_rate",
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
