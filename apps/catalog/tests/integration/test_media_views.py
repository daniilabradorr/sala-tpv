import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.catalog.models import Category, Product
from apps.catalog.tests.factories import create_category, create_product, create_tax
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_user


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def image_upload(name="image.png", color="red"):
    output = BytesIO()
    Image.new("RGB", (80, 40), color).save(output, "PNG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/png")


class CatalogManagedMediaViewTests(TestCase):
    password = "testpass123"

    def setUp(self):
        self._media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._media_directory.cleanup)
        self._settings = override_settings(
            MEDIA_ROOT=self._media_directory.name,
            STORAGES=TEST_STORAGES,
        )
        self._settings.enable()
        self.addCleanup(self._settings.disable)

        self.business = create_business(name="Media Catalog", slug="media-catalog")
        self.category = create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas-media",
        )
        self.tax = create_tax(
            business=self.business,
            name="IVA Media",
            code="IVA_MEDIA",
            is_default=True,
        )
        self.owner = create_user(
            business=self.business,
            email="owner-media@example.com",
            password=self.password,
            role=RoleChoices.OWNER,
        )
        self.cashier = create_user(
            business=self.business,
            email="cashier-media@example.com",
            password=self.password,
            role=RoleChoices.CASHIER,
        )

    def product_data(self, **overrides):
        data = {
            "name": "Producto Media",
            "sku": "",
            "barcode": "",
            "category": self.category.pk,
            "tax": self.tax.pk,
            "base_price": "2.00",
            "cost_price": "1.00",
            "unit": Product.UNIT_UNIDAD,
            "sort_order": 1,
            "is_service": "",
        }
        data.update(overrides)
        return data

    def product_update_data(self, product, **overrides):
        data = self.product_data(
            name=product.name,
            sku=product.sku,
            barcode=product.barcode or "",
            track_stock="on" if product.track_stock else "",
            is_service="on" if product.is_service else "",
            is_active="on" if product.is_active else "",
        )
        data.update(overrides)
        return data

    def category_data(self, **overrides):
        data = {
            "name": "Categoria Media",
            "slug": "categoria-media",
            "parent": "",
            "sort_order": 1,
        }
        data.update(overrides)
        return data

    def category_update_data(self, category, **overrides):
        data = {
            "name": category.name,
            "slug": category.slug,
            "parent": "",
            "sort_order": category.sort_order,
            "is_active": "on" if category.is_active else "",
        }
        data.update(overrides)
        return data

    def test_product_create_replace_remove_and_invalid_upload(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("catalog:product_create"),
            data=self.product_data(image_upload=image_upload("first.png", "red")),
        )
        self.assertEqual(response.status_code, 302)

        product = Product.objects.get(name="Producto Media")
        first_key = product.image.name
        self.assertTrue(first_key.endswith("/master.webp"))

        response = self.client.post(
            reverse("catalog:product_update", kwargs={"pk": product.pk}),
            data=self.product_update_data(
                product,
                image_upload=image_upload("second.png", "blue"),
            ),
        )
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        second_key = product.image.name
        self.assertNotEqual(first_key, second_key)

        response = self.client.post(
            reverse("catalog:product_update", kwargs={"pk": product.pk}),
            data=self.product_update_data(product, remove_image="on"),
        )
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertFalse(product.image)

        response = self.client.post(
            reverse("catalog:product_update", kwargs={"pk": product.pk}),
            data=self.product_update_data(
                product,
                image_upload=SimpleUploadedFile(
                    "evil.jpg",
                    b"<html>not an image</html>",
                    content_type="image/jpeg",
                ),
            ),
        )
        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertFalse(product.image)
        self.assertContains(response, "El archivo no contiene una imagen válida.")

    def test_category_create_replace_and_remove(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("catalog:category_create"),
            data=self.category_data(
                image_upload=image_upload("category-a.png", "green")
            ),
        )
        self.assertEqual(response.status_code, 302)

        category = Category.objects.get(name="Categoria Media")
        first_key = category.image.name
        self.assertTrue(first_key.endswith("/master.webp"))

        response = self.client.post(
            reverse("catalog:category_update", kwargs={"pk": category.pk}),
            data=self.category_update_data(
                category,
                image_upload=image_upload("category-b.png", "purple"),
            ),
        )
        self.assertEqual(response.status_code, 302)
        category.refresh_from_db()
        self.assertNotEqual(first_key, category.image.name)

        response = self.client.post(
            reverse("catalog:category_update", kwargs={"pk": category.pk}),
            data=self.category_update_data(category, remove_image="on"),
        )
        self.assertEqual(response.status_code, 302)
        category.refresh_from_db()
        self.assertFalse(category.image)

    def test_cashier_cannot_mutate_product_media(self):
        product = create_product(
            business=self.business,
            category=self.category,
            tax=self.tax,
            name="Producto protegido",
        )
        self.client.force_login(self.cashier)

        response = self.client.post(
            reverse("catalog:product_update", kwargs={"pk": product.pk}),
            data=self.product_update_data(
                product,
                image_upload=image_upload("forbidden.png"),
            ),
        )

        self.assertEqual(response.status_code, 403)
        product.refresh_from_db()
        self.assertFalse(product.image)
