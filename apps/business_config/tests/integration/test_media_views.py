import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.business_config.forms import BusinessProfileForm
from apps.business_config.services import create_business_configuration
from apps.core.models import Business
from apps.users.models import CustomUser, RoleChoices


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def logo_upload(name="logo.png"):
    output = BytesIO()
    Image.new("RGBA", (80, 40), (10, 20, 30, 0)).save(output, "PNG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/png")


class BusinessLogoLegacyTests(TestCase):
    password = "test-password-123"

    def setUp(self):
        self._media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._media_directory.cleanup)
        self._settings = override_settings(
            MEDIA_ROOT=self._media_directory.name,
            STORAGES=TEST_STORAGES,
        )
        self._settings.enable()
        self.addCleanup(self._settings.disable)

        self.business = Business.objects.create(
            name="Logo Legacy",
            slug="logo-legacy",
        )
        self.profile, _ = create_business_configuration(
            business=self.business,
            legal_name="Logo Legacy SL",
            tax_identifier="B12345678",
            phone="600123123",
            email="legacy@example.com",
            address_line_1="Calle Logo 1",
            postal_code="28001",
            city="Madrid",
            province="Madrid",
            trade_name="Logo Legacy",
            logo_url="https://legacy.example/logo.png",
        )
        self.owner = CustomUser.objects.create_user(
            email="owner-logo@example.com",
            password=self.password,
            business=self.business,
            role=RoleChoices.OWNER,
            first_name="Logo",
            last_name="Owner",
            phone="600000001",
        )
        self.url = reverse("business_config:profile")

    def profile_data(self, **overrides):
        data = {
            field: getattr(self.profile, field)
            for field in BusinessProfileForm.Meta.fields
        }
        data.update(overrides)
        return data

    def test_legacy_fallback_upload_priority_and_explicit_remove(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.url)
        self.assertContains(response, "https://legacy.example/logo.png")

        response = self.client.post(
            self.url,
            data=self.profile_data(logo_upload=logo_upload()),
        )
        self.assertEqual(response.status_code, 302)

        self.profile.refresh_from_db()
        self.assertTrue(self.profile.logo)
        self.assertEqual(self.profile.logo_url, "")
        managed_key = self.profile.logo.name

        response = self.client.get(self.url)
        self.assertNotContains(response, "https://legacy.example/logo.png")
        self.assertContains(response, managed_key.rsplit("/", 1)[0])

        response = self.client.post(
            self.url,
            data=self.profile_data(remove_logo="on"),
        )
        self.assertEqual(response.status_code, 302)

        self.profile.refresh_from_db()
        self.assertFalse(self.profile.logo)
        self.assertEqual(self.profile.logo_url, "")

        response = self.client.get(self.url)
        self.assertNotContains(response, "https://legacy.example/logo.png")
        self.assertContains(response, "media-placeholder")
