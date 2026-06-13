"""Este módulo proporciona funciones para validar que los objetos relacionados pertenecen
a la misma empresa (business) en un contexto de aislamiento de datos.
"""


def get_customUser_id(customUser):
    if customUser is None:
        raise ValueError("customUser es obligatorio")

    if hasattr(customUser, "business_id"):
        return customUser.business_id

    if hasattr(customUser, "pk"):
        return customUser.pk

    return customUser