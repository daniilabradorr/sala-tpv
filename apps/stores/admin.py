from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from apps.stores.models import Store
from apps.stores.services import (
    activate_store,
    deactivate_store,
    set_default_store,
)


@admin.register(Store)
class StoresAdmin(admin.ModelAdmin):
    """
    Administración de tiendas y sedes.

    Las operaciones de activación, desactivación y cambio de tienda
    predeterminada utilizan los servicios del dominio, evitando
    modificar directamente el modelo desde el admin.
    """

    list_display = (
        "name",
        "code",
        "business",
        "city",
        "province",
        "country_code",
        "is_default",
        "is_active",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "business",
        "is_default",
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
        "-is_default",
        "name",
    )

    list_select_related = ("business",)

    date_hierarchy = "created_at"

    actions = (
        "set_selected_store_as_default",
        "activate_selected_stores",
        "deactivate_selected_stores",
    )

    fieldsets = (
        (
            "Datos principales",
            {
                "fields": (
                    "business",
                    "name",
                    "code",
                    "is_default",
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
                    "se utilizan los datos generales del BusinessProfile."
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

    def get_readonly_fields(self, request, obj=None):
        """
        is_default se modifica mediante set_default_store().

        El business puede elegirse al crear una tienda desde el admin,
        pero no puede cambiarse después porque mover una tienda a otro
        negocio rompería su aislamiento y sus relaciones históricas.
        """
        readonly_fields = [
            "is_default",
            "created_at",
            "updated_at",
            "contact_phone",
            "contact_email",
        ]

        if obj is not None:
            readonly_fields.append("business")

        return tuple(readonly_fields)

    def has_delete_permission(self, request, obj=None):
        """
        Impide el borrado físico desde Django Admin.

        Una tienda con actividad debe desactivarse. El borrado controlado
        seguirá disponible mediante el servicio y la vista específica.
        """
        return False

    @admin.action(description="Marcar la tienda seleccionada como predeterminada")
    def set_selected_store_as_default(self, request, queryset):
        """
        Solo se puede seleccionar una tienda porque un negocio no puede
        tener varias tiendas predeterminadas.
        """
        selected_stores = list(queryset.select_related("business"))

        if len(selected_stores) != 1:
            self.message_user(
                request,
                (
                    "Debes seleccionar exactamente una tienda para "
                    "marcarla como predeterminada."
                ),
                level=messages.ERROR,
            )
            return

        store = selected_stores[0]

        try:
            store = set_default_store(
                business=store.business,
                store=store,
            )
        except ValidationError as exc:
            self.message_user(
                request,
                " ".join(exc.messages),
                level=messages.ERROR,
            )
            return

        self.message_user(
            request,
            (
                f"La tienda '{store.name}' es ahora la "
                "predeterminada de '{store.business.name}'."
            ),
            level=messages.SUCCESS,
        )

    @admin.action(description="Activar las tiendas seleccionadas")
    def activate_selected_stores(self, request, queryset):
        selected_stores = list(queryset.select_related("business"))

        activated_count = 0
        errors = []

        for store in selected_stores:
            was_active = store.is_active

            try:
                activate_store(
                    business=store.business,
                    store=store,
                )
            except ValidationError as exc:
                errors.append(f"{store.name}: {' '.join(exc.messages)}")
                continue

            if not was_active:
                activated_count += 1

        if activated_count:
            self.message_user(
                request,
                (f"Se han activado {activated_count} tiendas correctamente."),
                level=messages.SUCCESS,
            )

        if errors:
            self.message_user(
                request,
                " | ".join(errors),
                level=messages.ERROR,
            )

        if not activated_count and not errors:
            self.message_user(
                request,
                "Las tiendas seleccionadas ya estaban activas.",
                level=messages.INFO,
            )

    @admin.action(description="Desactivar las tiendas seleccionadas")
    def deactivate_selected_stores(self, request, queryset):
        selected_stores = list(queryset.select_related("business"))

        deactivated_count = 0
        errors = []

        for store in selected_stores:
            was_active = store.is_active

            try:
                deactivate_store(
                    business=store.business,
                    store=store,
                )
            except ValidationError as exc:
                errors.append(f"{store.name}: {' '.join(exc.messages)}")
                continue

            if was_active:
                deactivated_count += 1

        if deactivated_count:
            self.message_user(
                request,
                (f"Se han desactivado {deactivated_count} tiendas correctamente."),
                level=messages.SUCCESS,
            )

        if errors:
            self.message_user(
                request,
                " | ".join(errors),
                level=messages.ERROR,
            )

        if not deactivated_count and not errors:
            self.message_user(
                request,
                "Las tiendas seleccionadas ya estaban desactivadas.",
                level=messages.INFO,
            )
