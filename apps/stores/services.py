from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.stores.models import Store

from apps.stores.selectors import (
    get_default_store_for_business,
    get_next_active_store_for_business,
    get_store_for_business,
    get_stores_for_business,
)


def _get_locked_store(*, business, store):
    """
    Recupera y bloquea una tienda del negocio indicado.

    El bloqueo evita que dos peticiones modifiquen la misma tienda
    simultáneamente.

    También protege el aislamiento multiempresa: una tienda de otro
    negocio nunca puede ser modificada desde este servicio.
    """
    if business is None or not getattr(business, "pk", None):
        raise ValidationError("Debes indicar un negocio válido.")

    if store is None or not getattr(store, "pk", None):
        raise ValidationError("Debes indicar una tienda guardada.")

    locked_store = get_store_for_business(
        business=business,
        store=store,
        for_update=True,
    )

    if locked_store is None:
        raise ValidationError("La tienda no existe o no pertenece al negocio indicado.")

    return locked_store


@transaction.atomic
def set_default_store(*, business, store):
    """
    Convierte una tienda activa en la predeterminada del negocio.

    Esta operación es idempotente:
    si la tienda ya es predeterminada y no hay inconsistencias,
    no hace cambios.
    """
    locked_store = _get_locked_store(
        business=business,
        store=store,
    )

    list(
        get_stores_for_business(
            business=business,
            for_update=True,
        ).values_list("pk", flat=True)
    )

    if not locked_store.is_active:
        raise ValidationError(
            {
                "is_default": (
                    "No se puede marcar como predeterminada una tienda inactiva."
                )
            }
        )

    current_default = get_default_store_for_business(
        business=business,
        for_update=True,
        excluded_store=locked_store,
    )

    if locked_store.is_default and current_default is None:
        return locked_store

    if current_default is not None:
        Store.objects.filter(pk=current_default.pk).update(
            is_default=False,
            updated_at=timezone.now(),
        )

    locked_store.is_default = True
    locked_store.save(
        update_fields=[
            "is_default",
            "updated_at",
        ]
    )

    locked_store.refresh_from_db(
        fields=[
            "is_active",
            "is_default",
            "updated_at",
        ]
    )

    return locked_store


@transaction.atomic
def activate_store(*, business, store):
    """
    Activa una tienda y asigna predeterminada cuando sea necesario.

    Es idempotente:
    activar una tienda ya activa no produce error.
    """
    locked_store = _get_locked_store(
        business=business,
        store=store,
    )

    list(
        get_stores_for_business(
            business=business,
            for_update=True,
        ).values_list("pk", flat=True)
    )

    current_default = get_default_store_for_business(
        business=business,
        for_update=True,
        only_active=True,
        excluded_store=locked_store,
    )

    if locked_store.is_active:
        if locked_store.is_default or current_default is not None:
            return locked_store

        locked_store.is_default = True
        locked_store.save(
            update_fields=[
                "is_default",
                "updated_at",
            ]
        )
    else:
        locked_store.is_active = True

        if current_default is None:
            locked_store.is_default = True
            locked_store.save(
                update_fields=[
                    "is_active",
                    "is_default",
                    "updated_at",
                ]
            )
        else:
            locked_store.save(
                update_fields=[
                    "is_active",
                    "updated_at",
                ]
            )

    locked_store.refresh_from_db(
        fields=[
            "is_active",
            "is_default",
            "updated_at",
        ]
    )

    return locked_store


@transaction.atomic
def deactivate_store(*, business, store):
    """
    Desactiva una tienda sin eliminarla.

    Si era la tienda predeterminada, selecciona como predeterminada
    otra tienda activa del mismo negocio.

    Es idempotente:
    desactivar una tienda ya inactiva no produce error.
    """
    locked_store = _get_locked_store(
        business=business,
        store=store,
    )

    list(
        get_stores_for_business(
            business=business,
            for_update=True,
        ).values_list("pk", flat=True)
    )

    if not locked_store.is_active:
        return locked_store

    was_default = locked_store.is_default

    locked_store.is_default = False
    locked_store.is_active = False

    locked_store.save(
        update_fields=[
            "is_default",
            "is_active",
            "updated_at",
        ]
    )

    if was_default:
        replacement = get_next_active_store_for_business(
            business=business,
            excluded_store=locked_store,
            for_update=True,
        )

        if replacement is not None:
            replacement.is_default = True
            replacement.save(
                update_fields=[
                    "is_default",
                    "updated_at",
                ]
            )

    locked_store.refresh_from_db(
        fields=[
            "is_active",
            "is_default",
            "updated_at",
        ]
    )

    return locked_store


@transaction.atomic
def delete_store(*, business, store):
    """
    Elimina físicamente una tienda creada por error.

    No debe utilizarse para tiendas con histórico. En ese caso debe
    usarse deactivate_store().

    Si la tienda eliminada era la predeterminada, se selecciona otra
    tienda activa como predeterminada.
    """
    locked_store = _get_locked_store(
        business=business,
        store=store,
    )

    list(
        get_stores_for_business(
            business=business,
            for_update=True,
        ).values_list("pk", flat=True)
    )

    store_name = locked_store.name
    was_default = locked_store.is_default

    replacement = None

    if was_default:
        replacement = get_next_active_store_for_business(
            business=business,
            excluded_store=locked_store,
            for_update=True,
        )

    try:
        locked_store.delete()
    except ProtectedError as exc:
        raise ValidationError(
            (
                "No se puede eliminar esta tienda porque tiene "
                "datos relacionados. Desactívala para conservar "
                "el histórico."
            )
        ) from exc

    if replacement is not None:
        replacement.is_default = True
        replacement.save(
            update_fields=[
                "is_default",
                "updated_at",
            ]
        )

    return store_name
