import warnings
from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from .constants import (
    ALLOWED_FORMAT_EXTENSIONS,
    MAX_HEIGHT,
    MAX_PIXELS,
    MAX_UPLOAD_BYTES,
    MAX_WIDTH,
)


def validate_image_upload(upload):
    """Decode an upload and enforce format, size and dimension policy."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("La imagen supera el tamaño máximo de 5 MB.")
    extension = Path(upload.name).suffix.lower()
    allowed_extensions = {
        ext for values in ALLOWED_FORMAT_EXTENSIONS.values() for ext in values
    }
    if extension not in allowed_extensions:
        raise ValidationError("El formato de imagen no está permitido.")
    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as image:
                image.load()
                image_format = image.format
                width, height = image.size
                animated = getattr(image, "is_animated", False)
        if image_format not in ALLOWED_FORMAT_EXTENSIONS:
            raise ValidationError("El formato de imagen no está permitido.")
        if extension not in ALLOWED_FORMAT_EXTENSIONS[image_format]:
            raise ValidationError(
                "La extensión no coincide con el contenido de la imagen."
            )
        if animated:
            raise ValidationError("Las imágenes animadas no están permitidas.")
        if width > MAX_WIDTH or height > MAX_HEIGHT or width * height > MAX_PIXELS:
            raise ValidationError("La imagen tiene unas dimensiones demasiado grandes.")
    except ValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError(
            "La imagen tiene unas dimensiones demasiado grandes."
        ) from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError("El archivo no contiene una imagen válida.") from None
    finally:
        upload.seek(0)
    return upload
