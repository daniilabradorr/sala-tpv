from django.test import TestCase

from apps.catalog.forms import (
    CategoryCreateForm,
    CategoryUpdateForm,
    ProductCreateForm,
    ProductUpdateForm,
)
from apps.users.tests.factories import create_business


class ManagedImageFormContractTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Media Forms",
            slug="media-forms",
        )

    def test_catalog_forms_expose_managed_image_fields(self):
        for form_class in (
            ProductCreateForm,
            ProductUpdateForm,
            CategoryCreateForm,
            CategoryUpdateForm,
        ):
            with self.subTest(form=form_class.__name__):
                form = form_class(business=self.business)

                self.assertIn("image_upload", form.fields)
                self.assertIn("remove_image", form.fields)

                upload = form.fields["image_upload"]
                self.assertEqual(upload.label, "Seleccionar nueva imagen")
                self.assertIn("data-media-upload", upload.widget.attrs)

                accepted = upload.widget.attrs.get("accept", "")
                self.assertIn("image/jpeg", accepted)
                self.assertIn("image/png", accepted)
                self.assertIn("image/webp", accepted)

    def test_upload_and_remove_are_mutually_exclusive(self):
        for form_class in (ProductCreateForm, CategoryCreateForm):
            with self.subTest(form=form_class.__name__):
                form = form_class(
                    data={"remove_image": "on"},
                    files={},
                    business=self.business,
                )
                self.assertNotIn("image_upload", form.errors)
