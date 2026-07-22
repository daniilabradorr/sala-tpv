"""Admin del módulo customers.

Reglas importantes:

- Customer representa la ficha actual del cliente.
- CustomerAccount representa el saldo actual.
- CustomerAccountEntry representa el historial de movimientos.
- El balance no se modifica manualmente desde el admin.
- Los movimientos de cuenta son auditoría y son de solo lectura.
- Los clientes se desactivan; no se eliminan físicamente.
"""

from decimal import Decimal

from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.customers.models import (
    Customer,
    CustomerAccount,
    CustomerAccountEntry,
)


# ==========================================================
# Aislamiento multiempresa
# ==========================================================


class BusinessScopedAdminMixin:
    """Limita el admin al negocio del usuario autenticado.

    Los superusuarios pueden consultar todos los negocios.
    """

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        business_id = getattr(request.user, "business_id", None)

        if not business_id:
            return queryset.none()

        return queryset.filter(business_id=business_id)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Limita las relaciones al negocio del usuario."""

        if request.user.is_superuser:
            return super().formfield_for_foreignkey(
                db_field,
                request,
                **kwargs,
            )

        business_id = getattr(request.user, "business_id", None)

        if db_field.name == "business" and business_id:
            kwargs["queryset"] = db_field.remote_field.model.objects.filter(
                pk=business_id,
            )

        if db_field.name == "customer" and business_id:
            kwargs["queryset"] = Customer.objects.filter(
                business_id=business_id,
            )

        if db_field.name == "account" and business_id:
            kwargs["queryset"] = CustomerAccount.objects.filter(
                business_id=business_id,
            )

        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs,
        )

    def _user_can_access_object(self, request, obj):
        """Comprueba que el objeto pertenezca al negocio del usuario."""

        if obj is None or request.user.is_superuser:
            return True

        business_id = getattr(request.user, "business_id", None)

        return bool(business_id and getattr(obj, "business_id", None) == business_id)

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(
            request, obj
        ) and self._user_can_access_object(request, obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(
            request, obj
        ) and self._user_can_access_object(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(
            request, obj
        ) and self._user_can_access_object(request, obj)


# ==========================================================
# Cuenta dentro de Customer
# ==========================================================


class CustomerAccountInline(admin.StackedInline):
    """Resumen de la cuenta dentro de la ficha del cliente.

    Es de solo lectura. La configuración se modifica desde el admin
    independiente de CustomerAccount.
    """

    model = CustomerAccount
    fk_name = "customer"

    extra = 0
    max_num = 1
    can_delete = False
    show_change_link = True

    fields = (
        "balance",
        "credit_limit",
        "available_credit_display",
        "is_blocked",
        "created_at",
        "updated_at",
    )

    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Crédito disponible")
    def available_credit_display(self, obj):
        if not obj:
            return Decimal("0.00")

        return obj.available_credit


# ==========================================================
# Customer
# ==========================================================


@admin.register(Customer)
class CustomerAdmin(BusinessScopedAdminMixin, admin.ModelAdmin):
    """Admin principal de clientes."""

    list_display = (
        "name",
        "customer_type",
        "tax_identifier",
        "phone",
        "email",
        "account_balance_display",
        "account_blocked_display",
        "is_active",
        "business",
    )

    list_filter = (
        "business",
        "customer_type",
        "is_active",
        "country_code",
        "created_at",
    )

    search_fields = (
        "name",
        "legal_name",
        "tax_identifier",
        "foreign_id",
        "phone",
        "email",
        "city",
        "province",
    )

    readonly_fields = (
        "account_link",
        "account_balance_display",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "business",
        "account",
    )

    inlines = (CustomerAccountInline,)

    actions = (
        "deactivate_customers",
        "reactivate_customers",
    )

    list_per_page = 50

    fieldsets = (
        (
            "Negocio",
            {
                "fields": (
                    "business",
                    "customer_type",
                    "is_active",
                )
            },
        ),
        (
            "Identificación",
            {
                "fields": (
                    "name",
                    "legal_name",
                    "tax_identifier",
                    "country_code",
                    "foreign_id_type",
                    "foreign_id",
                )
            },
        ),
        (
            "Contacto",
            {
                "fields": (
                    "email",
                    "phone",
                )
            },
        ),
        (
            "Dirección",
            {
                "fields": (
                    "address_line_1",
                    "postal_code",
                    "city",
                    "province",
                )
            },
        ),
        (
            "Cuenta del cliente",
            {
                "fields": (
                    "account_link",
                    "account_balance_display",
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
        """Evita consultas adicionales al mostrar la cuenta."""

        return (
            super()
            .get_queryset(request)
            .select_related(
                "business",
                "account",
            )
        )

    def get_readonly_fields(self, request, obj=None):
        """Impide cambiar el negocio de un cliente existente."""

        readonly_fields = list(super().get_readonly_fields(request, obj))

        if obj is not None or not request.user.is_superuser:
            readonly_fields.append("business")

        return readonly_fields

    def save_model(self, request, obj, form, change):
        """Guarda el cliente y garantiza que tenga una cuenta."""

        if not request.user.is_superuser:
            obj.business = request.user.business

        super().save_model(request, obj, form, change)

        CustomerAccount.objects.get_or_create(
            business=obj.business,
            customer=obj,
            defaults={
                "balance": Decimal("0.00"),
                "credit_limit": Decimal("0.00"),
                "is_blocked": False,
            },
        )

    @admin.display(description="Cuenta")
    def account_link(self, obj):
        """Enlace al admin de la cuenta."""

        account = getattr(obj, "account", None)

        if not account:
            return "Sin cuenta"

        url = reverse(
            "admin:customers_customeraccount_change",
            args=[account.pk],
        )

        return format_html(
            '<a href="{}">Abrir cuenta del cliente</a>',
            url,
        )

    @admin.display(description="Saldo")
    def account_balance_display(self, obj):
        account = getattr(obj, "account", None)

        if not account:
            return "—"

        return account.balance

    @admin.display(
        boolean=True,
        description="Cuenta bloqueada",
    )
    def account_blocked_display(self, obj):
        account = getattr(obj, "account", None)

        if not account:
            return None

        return account.is_blocked

    @admin.action(description="Desactivar clientes seleccionados")
    def deactivate_customers(self, request, queryset):
        updated = queryset.filter(
            is_active=True,
        ).update(
            is_active=False,
            updated_at=timezone.now(),
        )

        self.message_user(
            request,
            f"{updated} cliente(s) desactivado(s).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Reactivar clientes seleccionados")
    def reactivate_customers(self, request, queryset):
        updated = queryset.filter(
            is_active=False,
        ).update(
            is_active=True,
            updated_at=timezone.now(),
        )

        self.message_user(
            request,
            f"{updated} cliente(s) reactivado(s).",
            level=messages.SUCCESS,
        )


# ==========================================================
# Movimientos dentro de CustomerAccount
# ==========================================================


class CustomerAccountEntryInline(admin.TabularInline):
    """Movimientos históricos de la cuenta.

    El inline es exclusivamente de lectura.
    """

    model = CustomerAccountEntry
    fk_name = "account"

    extra = 0
    can_delete = False
    show_change_link = True

    fields = (
        "created_at",
        "entry_type",
        "amount",
        "balance_after",
        "created_by",
        "notes",
    )

    readonly_fields = fields

    ordering = (
        "-created_at",
        "-pk",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "business",
                "account",
                "created_by",
            )
        )


# ==========================================================
# CustomerAccount
# ==========================================================


@admin.register(CustomerAccount)
class CustomerAccountAdmin(
    BusinessScopedAdminMixin,
    admin.ModelAdmin,
):
    """Admin de la fotografía actual de la cuenta."""

    list_display = (
        "customer",
        "business",
        "balance",
        "credit_limit",
        "available_credit_display",
        "is_blocked",
        "customer_active_display",
        "updated_at",
    )

    list_filter = (
        "business",
        "is_blocked",
        "customer__is_active",
        "updated_at",
    )

    search_fields = (
        "customer__name",
        "customer__legal_name",
        "customer__tax_identifier",
        "customer__phone",
        "customer__email",
    )

    readonly_fields = (
        "business",
        "customer",
        "balance",
        "available_credit_display",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "business",
        "customer",
    )

    inlines = (CustomerAccountEntryInline,)

    list_per_page = 50

    fieldsets = (
        (
            "Cliente",
            {
                "fields": (
                    "business",
                    "customer",
                )
            },
        ),
        (
            "Estado de la cuenta",
            {
                "fields": (
                    "balance",
                    "credit_limit",
                    "available_credit_display",
                    "is_blocked",
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
        return (
            super()
            .get_queryset(request)
            .select_related(
                "business",
                "customer",
            )
        )

    def has_add_permission(self, request):
        """Las cuentas se crean junto con el cliente."""

        return False

    def has_delete_permission(self, request, obj=None):
        """Una cuenta con histórico no debe eliminarse."""

        return False

    @admin.display(description="Crédito disponible")
    def available_credit_display(self, obj):
        return obj.available_credit

    @admin.display(
        boolean=True,
        description="Cliente activo",
    )
    def customer_active_display(self, obj):
        return obj.customer.is_active


# ==========================================================
# CustomerAccountEntry
# ==========================================================


@admin.register(CustomerAccountEntry)
class CustomerAccountEntryAdmin(
    BusinessScopedAdminMixin,
    admin.ModelAdmin,
):
    """Admin de movimientos históricos.

    CustomerAccountEntry es auditoría y queda completamente
    bloqueado para escritura manual.
    """

    list_display = (
        "created_at",
        "customer_display",
        "entry_type",
        "amount",
        "balance_after",
        "business",
        "created_by",
    )

    list_filter = (
        "business",
        "entry_type",
        "created_at",
    )

    search_fields = (
        "account__customer__name",
        "account__customer__legal_name",
        "account__customer__tax_identifier",
        "notes",
        "created_by__email",
    )

    readonly_fields = (
        "business",
        "account",
        "entry_type",
        "amount",
        "balance_after",
        "created_by",
        "notes",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "business",
        "account",
        "account__customer",
        "created_by",
    )

    date_hierarchy = "created_at"
    list_per_page = 100
    actions = None

    fieldsets = (
        (
            "Movimiento",
            {
                "fields": (
                    "business",
                    "account",
                    "entry_type",
                    "amount",
                    "balance_after",
                )
            },
        ),
        (
            "Trazabilidad",
            {
                "fields": (
                    "created_by",
                    "notes",
                )
            },
        ),
        (
            "Fechas",
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
        return (
            super()
            .get_queryset(request)
            .select_related(
                "business",
                "account",
                "account__customer",
                "created_by",
            )
        )

    def has_add_permission(self, request):
        """Los movimientos solo se crean mediante services.py."""

        return False

    def has_change_permission(self, request, obj=None):
        """Los movimientos históricos son inmutables."""

        return False

    def has_delete_permission(self, request, obj=None):
        """Los movimientos históricos nunca se eliminan."""

        return False

    @admin.display(description="Cliente")
    def customer_display(self, obj):
        return obj.account.customer
