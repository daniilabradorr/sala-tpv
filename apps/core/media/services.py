import logging

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction

from .naming import asset_keys, variant_key
from .processing import process_image
from .validation import validate_image_upload

logger = logging.getLogger(__name__)


class MediaStorageError(Exception):
    """Raised when storage cannot preserve immutable media keys."""


def _validate_business(business, entity):
    if entity.business_id != business.pk:
        raise ValidationError("El registro no pertenece al negocio actual.")


def cleanup_asset(master_key, *, storage=default_storage):
    if not master_key:
        return
    for variant in ("master", "thumb", "detail"):
        try:
            storage.delete(variant_key(master_key, variant))
        except Exception:
            logger.exception(
                "Error limpiando un derivado de media", extra={"asset": master_key}
            )


def replace_media(
    *, business, entity, field_name, entity_kind, upload, storage=default_storage
):
    _validate_business(business, entity)
    validate_image_upload(upload)
    variants = process_image(upload)
    keys = asset_keys(
        business_id=business.pk, entity_kind=entity_kind, entity_id=entity.pk
    )
    saved = []
    try:
        for variant in ("master", "thumb", "detail"):
            expected_key = keys[variant]
            saved_key = storage.save(expected_key, ContentFile(variants[variant]))
            saved.append(saved_key)
            if saved_key != expected_key:
                raise MediaStorageError(
                    "El almacenamiento no conservó la clave inmutable esperada."
                )
    except Exception:
        for key in saved:
            try:
                storage.delete(key)
            except Exception:
                logger.exception("Error limpiando media parcial")
        raise

    model = type(entity)
    try:
        with transaction.atomic():
            locked = model.objects.select_for_update().get(
                pk=entity.pk, business=business
            )
            old_key = getattr(locked, field_name).name
            setattr(locked, field_name, keys["master"])
            update_fields = [field_name]
            if hasattr(locked, "logo_url"):
                locked.logo_url = ""
                update_fields.append("logo_url")
            locked.save(update_fields=update_fields)
            transaction.on_commit(lambda: cleanup_asset(old_key, storage=storage))
    except Exception:
        cleanup_asset(keys["master"], storage=storage)
        raise
    setattr(entity, field_name, keys["master"])
    return locked


def remove_media(*, business, entity, field_name, storage=default_storage):
    _validate_business(business, entity)
    model = type(entity)
    with transaction.atomic():
        locked = model.objects.select_for_update().get(pk=entity.pk, business=business)
        old_key = getattr(locked, field_name).name
        setattr(locked, field_name, "")
        update_fields = [field_name]
        if hasattr(locked, "logo_url"):
            locked.logo_url = ""
            update_fields.append("logo_url")
        locked.save(update_fields=update_fields)
        transaction.on_commit(lambda: cleanup_asset(old_key, storage=storage))
    setattr(entity, field_name, "")
    return locked
