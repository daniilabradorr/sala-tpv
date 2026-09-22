"""Real Chromium coverage for managed product and business media."""

import tempfile
from io import BytesIO
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(ROOT_URLCONF="e2e.media_urls", STORAGES=TEST_STORAGES)
class BrowserMediaTests(StaticLiveServerTestCase):
    email = "media.e2e@example.com"
    password = "Media-E2E-Password-123!"

    @classmethod
    def setUpClass(cls):
        cls._media_directory = tempfile.TemporaryDirectory()
        cls._override_media = override_settings(MEDIA_ROOT=cls._media_directory.name)
        cls._override_media.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override_media.disable()
        cls._media_directory.cleanup()

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Media E2E SL",
            trade_name="Media E2E",
            tax_identifier="B12345672",
            phone="923333334",
            email="business-media@example.com",
            address_line_1="Calle Media 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Media",
            owner_first_name="Media",
            owner_last_name="Owner",
            owner_email=self.email,
            owner_phone="600000003",
            owner_password=self.password,
            owner_pin="1357",
        )
        self.business = result.business

    def _image(self, name, color):
        output = BytesIO()
        Image.new("RGB", (80, 40), color).save(output, "PNG")
        path = Path(self._media_directory.name) / name
        path.write_bytes(output.getvalue())
        return path

    def _login(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_url(f"{self.live_server_url}/")

    def _wait_for_loaded_image(self, page, image):
        expect(image).to_be_visible()
        page.wait_for_function(
            "(img) => img.complete && img.naturalWidth > 0",
            arg=image.element_handle(),
        )
        self.assertGreater(image.evaluate("img => img.naturalWidth"), 0)

    def test_product_upload_replace_remove_invalid_and_responsive(self):
        from apps.catalog.tests.factories import create_product

        product = create_product(business=self.business, name="Producto Media")
        first_file = self._image("first.png", "red")
        second_file = self._image("second.png", "blue")
        invalid_file = Path(self._media_directory.name) / "evil.jpg"
        invalid_file.write_text("<html>not an image</html>")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 375, "height": 812})
            try:
                self._login(page)
                edit_url = f"{self.live_server_url}/catalog/products/{product.pk}/edit/"
                page.goto(edit_url)
                page.get_by_label("Seleccionar nueva imagen").set_input_files(
                    first_file
                )
                page.get_by_role("button", name="Guardar producto").click()
                image = page.locator("img.media-preview")
                self._wait_for_loaded_image(page, image)
                source_a = image.get_attribute("src")

                page.goto(edit_url)
                page.get_by_label("Seleccionar nueva imagen").set_input_files(
                    second_file
                )
                page.get_by_role("button", name="Guardar producto").click()
                source_b = page.locator("img.media-preview").get_attribute("src")
                self.assertNotEqual(source_a, source_b)

                page.goto(edit_url)
                page.get_by_label("Eliminar imagen").check()
                page.get_by_role("button", name="Guardar producto").click()
                self.assertIn(
                    "media-placeholder",
                    page.locator("img.media-preview").get_attribute("src"),
                )

                page.goto(edit_url)
                page.get_by_label("Seleccionar nueva imagen").set_input_files(
                    invalid_file
                )
                page.get_by_role("button", name="Guardar producto").click()
                expect(
                    page.get_by_text("El archivo no contiene una imagen válida.")
                ).to_be_visible()
                self.assertIn(
                    "media-placeholder",
                    page.locator("img.media-preview").get_attribute("src"),
                )
                for width, height in ((375, 812), (1440, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
            finally:
                browser.close()

        product.refresh_from_db()
        self.assertFalse(product.image)

    def test_business_logo_upload_replace_and_remove(self):
        first_file = self._image("logo-first.png", "green")
        second_file = self._image("logo-second.png", "purple")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            try:
                self._login(page)
                profile_url = f"{self.live_server_url}/config/profile/"
                page.goto(profile_url)
                page.get_by_label("Seleccionar nuevo logo").set_input_files(first_file)
                page.get_by_role("button", name="Guardar cambios").click()
                page.goto(profile_url)
                logo = page.locator("img.media-preview--logo")
                self._wait_for_loaded_image(page, logo)
                source_a = logo.get_attribute("src")
                page.get_by_label("Seleccionar nuevo logo").set_input_files(second_file)
                page.get_by_role("button", name="Guardar cambios").click()
                page.goto(profile_url)
                self.assertNotEqual(
                    source_a,
                    page.locator("img.media-preview--logo").get_attribute("src"),
                )
                page.get_by_label("Eliminar logo").check()
                page.get_by_role("button", name="Guardar cambios").click()
                page.goto(profile_url)
                self.assertIn(
                    "media-placeholder",
                    page.locator("img.media-preview--logo").get_attribute("src"),
                )
            finally:
                browser.close()
