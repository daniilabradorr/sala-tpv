from django.contrib import admin

from apps.customers.models import Customer, CustomerAccount, CustomerAccountEntry


class BusinessScopedAdminMixin:
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(business=request.user.business)


@admin.register(Customer)
class CustomerAdmin(BusinessScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "business", "customer_type", "tax_identifier", "is_active")
    list_filter = ("is_active", "customer_type")
    search_fields = (
        "name",
        "legal_name",
        "tax_identifier",
        "foreign_id",
        "email",
        "phone",
    )
    readonly_fields = ("business", "created_at", "updated_at")
    actions = ("activate_customers", "deactivate_customers")

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Activar clientes seleccionados")
    def activate_customers(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Desactivar clientes seleccionados")
    def deactivate_customers(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(CustomerAccount)
class CustomerAccountAdmin(BusinessScopedAdminMixin, admin.ModelAdmin):
    list_display = ("customer", "business", "balance", "credit_limit", "is_blocked")
    readonly_fields = ("business", "customer", "balance", "created_at", "updated_at")
    search_fields = ("customer__name", "customer__tax_identifier")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("business", "customer")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CustomerAccountEntry)
class CustomerAccountEntryAdmin(BusinessScopedAdminMixin, admin.ModelAdmin):
    list_display = (
        "account",
        "business",
        "entry_type",
        "amount",
        "balance_after",
        "created_at",
        "created_by",
    )
    readonly_fields = (
        "business",
        "account",
        "entry_type",
        "amount",
        "balance_after",
        "notes",
        "created_by",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("business", "account", "created_by")
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
