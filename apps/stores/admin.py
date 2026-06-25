from django.contrib import admin

from apps.stores.models import Store


@admin.register(Store)
class StoresAdmin(admin.ModelAdmin):
    """
    Admin de tiendas/sedes del negocio.

    Permite gestionar tiendas por empresa, consultar su estado,
    datos de contacto, dirección y trazabilidad temporal.
    """

    list_display = (
        "name",
        "code",
        "business",
        "city",
        "province",
        "country_code",
        "is_active",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "business",
        "is_active",
        "country_code",
        "province",
        "city",
    )

    search_fields = (
        "name",
        "code",
        "business__name",
        "city",
        "province",
        "phone_store",
        "email_store",
    )

    ordering = (
        "business",
        "name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "contact_phone",
        "contact_email",
    )

    list_select_related = ("business",)

    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Datos principales",
            {
                "fields": (
                    "business",
                    "name",
                    "code",
                    "is_active",
                )
            },
        ),
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
            "Contacto propio de la tienda",
            {
                "fields": (
                    "phone_store",
                    "email_store",
                )
            },
        ),
        (
            "Contacto efectivo usado por la tienda",
            {
                "description": (
                    "Si la tienda no tiene teléfono o email propios, "
                    "se usan los datos generales del BusinessProfile."
                ),
                "fields": (
                    "contact_phone",
                    "contact_email",
                ),
            },
        ),
        (
            "Trazabilidad",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
