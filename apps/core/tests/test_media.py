from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from apps.core.media.naming import asset_keys, variant_key
from apps.core.media.processing import process_image
from apps.core.media.validation import validate_image_upload


def image_upload(fmt="PNG", name="image.png", size=(1200, 600), mode="RGB"):
    data = BytesIO()
    color = (10, 20, 30, 0) if mode == "RGBA" else (10, 20, 30)
    Image.new(mode, size, color).save(data, fmt)
    return SimpleUploadedFile(name, data.getvalue(), content_type="text/html")


class MediaValidationTests(SimpleTestCase):
    def test_decodes_allowed_formats_without_trusting_content_type(self):
        for fmt, suffix in (("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")):
            upload = image_upload(fmt, f"image.{suffix}")
            self.assertIs(validate_image_upload(upload), upload)

    def test_rejects_fake_image_and_extension_mismatch(self):
        with self.assertRaisesMessage(ValidationError, "imagen válida"):
            validate_image_upload(SimpleUploadedFile("evil.jpg", b"<html>bad</html>"))
        with self.assertRaisesMessage(ValidationError, "no coincide"):
            validate_image_upload(image_upload("PNG", "fake.jpg"))

    def test_rejects_svg_gif_and_too_large_upload(self):
        for upload in (
            SimpleUploadedFile("image.svg", b"<svg/>"),
            image_upload("GIF", "image.gif"),
            SimpleUploadedFile("large.jpg", b"x" * (5 * 1024 * 1024 + 1)),
        ):
            with self.assertRaises(ValidationError):
                validate_image_upload(upload)


class MediaProcessingTests(SimpleTestCase):
    def test_webp_variants_have_bounded_dimensions(self):
        variants = process_image(image_upload(size=(3000, 1500)))
        for name, limit in (("master", 2400), ("detail", 800), ("thumb", 320)):
            with Image.open(BytesIO(variants[name])) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertLessEqual(max(image.size), limit)
                self.assertAlmostEqual(image.width / image.height, 2, places=1)

    def test_alpha_is_preserved(self):
        variants = process_image(image_upload(mode="RGBA"))
        with Image.open(BytesIO(variants["thumb"])) as image:
            self.assertIn("A", image.getbands())

    def test_server_generated_multitenant_naming(self):
        first = asset_keys(business_id=7, entity_kind="products", entity_id=9)
        second = asset_keys(business_id=7, entity_kind="products", entity_id=9)
        self.assertIn("businesses/7/products/9/", first["master"])
        self.assertNotEqual(first["master"], second["master"])
        self.assertEqual(variant_key(first["master"], "thumb"), first["thumb"])
        self.assertNotIn("factura-secreta", first["master"])
