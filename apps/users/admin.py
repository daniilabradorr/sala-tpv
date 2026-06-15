from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.users.models import CustomUser, UserStoreAccess


class UserStoreAccessInline(admin.TabularInline):
    model = UserStoreAccess
    extra = 0
    fields = (
        "business",
        "store",
        "can_sell",
        "can_open_cash",
        "can_close_cash",
        "is_active",
    )
    autocomplete_fields = ("business", "store")


@admin.register(CustomUser)
class CustomUserAdmin(DjangoUserAdmin):
    model = CustomUser

    list_display = (
        "email",
        "first_name",
        "last_name",
        "business",
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
        "date_joined",
    )

    list_filter = (
        "business",
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
    )

    search_fields = (
        "email",
        "first_name",
        "last_name",
        "phone",
    )

    ordering = ("email",)

    readonly_fields = (
        "employee_code",
        "date_joined",
        "created_at",
        "updated_at",
        "last_login",
    )

    fieldsets = (
        (
            "Credenciales",
            {
                "fields": (
                    "email",
                    "password",
                    "pin_hash",
                )
            },
        ),
        (
            "Datos personales",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "phone",
                    "employee_code",
                )
            },
        ),
        (
            "Negocio y rol",
            {
                "fields": (
                    "business",
                    "role",
                )
            },
        ),
        (
            "Permisos Django",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Fechas",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            "Crear usuario",
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "business",
                    "role",
                    "first_name",
                    "last_name",
                    "phone",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )

    inlines = (UserStoreAccessInline,)


@admin.register(UserStoreAccess)
class UserStoreAccessAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "business",
        "store",
        "can_sell",
        "can_open_cash",
        "can_close_cash",
        "is_active",
    )

    list_filter = (
        "business",
        "store",
        "can_sell",
        "can_open_cash",
        "can_close_cash",
        "is_active",
    )

    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "store__name",
        "store__code",
    )

    autocomplete_fields = (
        "business",
        "user",
        "store",
    )

    ordering = (
        "business",
        "user__email",
        "store__name",
    )
