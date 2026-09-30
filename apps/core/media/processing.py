from io import BytesIO

from PIL import Image, ImageOps

from .constants import VARIANT_SIZES


def process_image(upload):
    """Return metadata-free WebP variants, preserving alpha and aspect ratio."""
    upload.seek(0)
    with Image.open(upload) as source:
        source.load()
        image = ImageOps.exif_transpose(source)
        has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        image = image.convert("RGBA" if has_alpha else "RGB")
        variants = {}
        for name, max_side in VARIANT_SIZES.items():
            variant = image.copy()
            variant.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            output = BytesIO()
            variant.save(
                output,
                format="WEBP",
                lossless=has_alpha,
                quality=85,
                method=6,
            )
            variants[name] = output.getvalue()
    upload.seek(0)
    return variants
