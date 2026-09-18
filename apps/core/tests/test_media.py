from io import BytesIO

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.test import SimpleTestCase, TestCase
from PIL import Image

from apps.core.media.naming import asset_keys, variant_key
from apps.core.media.processing import process_image
from apps.core.media.validation import validate_image_upload
from apps.core.media.services import MediaStorageError, remove_media, replace_media
from apps.core.media.storage import build_media_storage_config
from apps.catalog.tests.factories import create_product
from apps.users.tests.factories import create_business


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

    def test_rejects_dimensions_before_verify_or_decode(self):
        scenarios = ((6001, 10), (10, 6001), (6000, 6001))
        for dimensions in scenarios:
            upload = image_upload(size=(10, 10))
            mocked_image = patch("apps.core.media.validation.Image.open").start()
            opened = mocked_image.return_value.__enter__.return_value
            opened.format = "PNG"
            opened.size = dimensions
            opened.is_animated = False
            try:
                with self.assertRaisesMessage(ValidationError, "dimensiones"):
                    validate_image_upload(upload)
                opened.verify.assert_not_called()
            finally:
                patch.stopall()


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

    def test_exif_orientation_is_applied_and_metadata_removed(self):
        data = BytesIO()
        source = Image.new("RGB", (20, 10), "red")
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "sensitive author"
        source.save(data, "JPEG", exif=exif)
        variants = process_image(SimpleUploadedFile("oriented.jpg", data.getvalue()))
        for payload in variants.values():
            with Image.open(BytesIO(payload)) as image:
                self.assertEqual(image.size, (10, 20))
                self.assertFalse(image.getexif())

    def test_server_generated_multitenant_naming(self):
        first = asset_keys(business_id=7, entity_kind="products", entity_id=9)
        second = asset_keys(business_id=7, entity_kind="products", entity_id=9)
        self.assertIn("businesses/7/products/9/", first["master"])
        self.assertNotEqual(first["master"], second["master"])
        self.assertEqual(variant_key(first["master"], "thumb"), first["thumb"])
        self.assertNotIn("factura-secreta", first["master"])


class MediaStorageConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.env = {
            "MEDIA_STORAGE_ENDPOINT_URL": "https://objects.invalid",
            "MEDIA_STORAGE_ACCESS_KEY": "access-value",
            "MEDIA_STORAGE_SECRET_KEY": "secret-value",
            "MEDIA_STORAGE_BUCKET_NAME": "media",
        }

    def test_missing_configuration_fails_without_secret_values(self):
        incomplete = self.env | {"MEDIA_STORAGE_BUCKET_NAME": ""}
        with self.assertRaises(ImproperlyConfigured) as caught:
            build_media_storage_config(incomplete)
        self.assertNotIn("access-value", str(caught.exception))
        self.assertNotIn("secret-value", str(caught.exception))

    def test_public_and_private_cache_configuration(self):
        public = build_media_storage_config(self.env)
        private = build_media_storage_config(
            self.env | {"MEDIA_STORAGE_PUBLIC_READ": "0"}
        )
        self.assertEqual(public["BACKEND"], "storages.backends.s3.S3Storage")
        self.assertFalse(public["OPTIONS"]["querystring_auth"])
        self.assertTrue(
            public["OPTIONS"]["object_parameters"]["CacheControl"].startswith("public,")
        )
        self.assertTrue(private["OPTIONS"]["querystring_auth"])
        self.assertTrue(
            private["OPTIONS"]["object_parameters"]["CacheControl"].startswith(
                "private,"
            )
        )


class RenamingStorage(FileSystemStorage):
    def save(self, name, content, max_length=None):
        return super().save(f"renamed/{name}", content, max_length=max_length)


class FailingStorage(FileSystemStorage):
    def __init__(self, *args, fail_on=2, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_on = fail_on
        self.save_count = 0

    def save(self, name, content, max_length=None):
        self.save_count += 1
        if self.save_count == self.fail_on:
            raise OSError("controlled storage failure")
        return super().save(name, content, max_length=max_length)


class MediaLifecycleTests(TestCase):
    def setUp(self):
        self.business = create_business(name="Media A", slug="media-a")
        self.other_business = create_business(name="Media B", slug="media-b")
        self.product = create_product(business=self.business)

    def test_replace_replace_remove_lifecycle(self):
        with self.settings(MEDIA_ROOT=self._temp_dir()):
            storage = FileSystemStorage(location=self._media_root)
            replace_media(
                business=self.business,
                entity=self.product,
                field_name="image",
                entity_kind="products",
                upload=image_upload(),
                storage=storage,
            )
            first = self.product.image.name
            self.assertTrue(
                all(
                    storage.exists(variant_key(first, name))
                    for name in ("master", "thumb", "detail")
                )
            )
            with self.captureOnCommitCallbacks(execute=True):
                replace_media(
                    business=self.business,
                    entity=self.product,
                    field_name="image",
                    entity_kind="products",
                    upload=image_upload(),
                    storage=storage,
                )
            second = self.product.image.name
            self.assertNotEqual(first, second)
            self.assertFalse(storage.exists(first))
            with self.captureOnCommitCallbacks(execute=True):
                remove_media(
                    business=self.business,
                    entity=self.product,
                    field_name="image",
                    storage=storage,
                )
            self.product.refresh_from_db()
            self.assertFalse(self.product.image)
            remove_media(
                business=self.business,
                entity=self.product,
                field_name="image",
                storage=storage,
            )

    def test_cross_business_and_renamed_key_are_rejected(self):
        with self.settings(MEDIA_ROOT=self._temp_dir()):
            with self.assertRaises(ValidationError):
                replace_media(
                    business=self.other_business,
                    entity=self.product,
                    field_name="image",
                    entity_kind="products",
                    upload=image_upload(),
                )
            with self.assertRaises(ValidationError):
                remove_media(
                    business=self.other_business,
                    entity=self.product,
                    field_name="image",
                )
            with self.assertRaises(MediaStorageError):
                replace_media(
                    business=self.business,
                    entity=self.product,
                    field_name="image",
                    entity_kind="products",
                    upload=image_upload(),
                    storage=RenamingStorage(location=self._media_root),
                )
            self.product.refresh_from_db()
            self.assertFalse(self.product.image)

    def test_db_failure_cleans_new_asset(self):
        with self.settings(MEDIA_ROOT=self._temp_dir()):
            storage = FileSystemStorage(location=self._media_root)
            with patch.object(
                type(self.product), "save", side_effect=RuntimeError("db")
            ):
                with self.assertRaises(RuntimeError):
                    replace_media(
                        business=self.business,
                        entity=self.product,
                        field_name="image",
                        entity_kind="products",
                        upload=image_upload(),
                        storage=storage,
                    )
            self.assert_no_stored_files()

    def test_partial_storage_failure_preserves_reference_and_cleans_files(self):
        with self.settings(MEDIA_ROOT=self._temp_dir()):
            for failure_position in (2, 3):
                storage = FailingStorage(
                    location=self._media_root, fail_on=failure_position
                )
                with self.assertRaises(OSError):
                    replace_media(
                        business=self.business,
                        entity=self.product,
                        field_name="image",
                        entity_kind="products",
                        upload=image_upload(),
                        storage=storage,
                    )
                self.product.refresh_from_db()
                self.assertFalse(self.product.image)
                self.assert_no_stored_files()

    def assert_no_stored_files(self):
        import os

        self.assertFalse(
            any(files for _root, _directories, files in os.walk(self._media_root))
        )

    def _temp_dir(self):
        import tempfile

        self._temporary = tempfile.TemporaryDirectory()
        self._media_root = self._temporary.name
        self.addCleanup(self._temporary.cleanup)
        return self._media_root
