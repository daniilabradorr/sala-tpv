"""Este módulo proporciona funciones para validar que los objetos relacionados pertenecen
a la misma empresa (business) en un contexto de aislamiento de datos.
"""
from django.core.exceptions import ValidationError


def get_business_id(business):
    if business is None:
        raise ValueError("business es obligatorio")

    if hasattr(business, "business_id"):
        return business.business_id

    if hasattr(business, "pk"):
        return business.pk

    return business


def validate_same_business(instance, *field_names):
    current_business_id = getattr(instance, "business_id", None)
    if current_business_id is None:
        return

    errors = {}

    for field_name in field_names:
        related_obj = getattr(instance, field_name, None)
        if related_obj is None:
            continue

        related_business_id = get_business_id(related_obj)

        if related_business_id != current_business_id:
            errors[field_name] = "El objeto relacionado pertenece a otra empresa."

    if errors:
        raise ValidationError(errors)