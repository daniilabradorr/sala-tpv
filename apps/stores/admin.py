from django.contrib import admin

from apps.stores.models import Stores


@admin.register(Stores)
class StoresAdmin(admin.ModelAdmin):
    """
    Admin temporal/mínimo para Stores.

    Ahora mismo el modelo Stores todavía es provisional, así que no usamos
    created_at ni updated_at porque el modelo actual no los tiene.

    Más adelante, cuando desarrollemos el módulo stores completo, podremos hacer
    que Stores herede de TimeStampedModel y entonces sí añadiremos esos campos
    al admin.
    """

    list_display = (
        "name",
        "code",
        "business",
        "is_active",
    )

    list_filter = (
        "business",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "business__name",
    )

    ordering = (
        "business",
        "name",
    )

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
    )
