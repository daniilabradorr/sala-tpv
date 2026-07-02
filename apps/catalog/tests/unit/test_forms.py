from django.test import TestCase

from apps.catalog.forms import (
    CategoryCreateForm,
    CategoryUpdateForm,
    TaxCreateForm,
    TaxUpdateForm,
    ProductCreateForm,
    ProductUpdateForm,
)
from apps.catalog.models import Tax, Product
from apps.catalog.tests.factories import create_category, create_tax, create_product
from apps.users.tests.factories import create_business


class CategoryFormTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )
        self.other_business = create_business(
            name="Negocio B",
            slug="negocio-b",
        )
        self.parent = create_category(
            business=self.business,
            name="Comida",
            slug="comida",
        )
        self.other_parent = create_category(
            business=self.other_business,
            name="Otra Comida",
            slug="otra-comida",
        )

    def test_category_create_form_is_valid_with_correct_data(self):
        form = CategoryCreateForm(
            data={
                "name": "Bebidas",
                "slug": "",
                "parent": self.parent.pk,
                "sort_order": 1,
            },
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_category_create_form_assigns_business_to_instance(self):
        form = CategoryCreateForm(
            data={
                "name": "Bebidas",
                "slug": "",
                "parent": "",
                "sort_order": 1,
            },
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())
        category = form.save()

        self.assertEqual(category.business, self.business)

    def test_category_create_form_does_not_expose_business_or_is_active(self):
        form = CategoryCreateForm(business=self.business)

        self.assertNotIn("business", form.fields)
        self.assertNotIn("is_active", form.fields)

    def test_category_parent_queryset_is_limited_to_same_business(self):
        form = CategoryCreateForm(business=self.business)

        self.assertIn(self.parent, form.fields["parent"].queryset)
        self.assertNotIn(self.other_parent, form.fields["parent"].queryset)

    def test_category_create_form_rejects_parent_from_other_business(self):
        form = CategoryCreateForm(
            data={
                "name": "Bebidas",
                "slug": "",
                "parent": self.other_parent.pk,
                "sort_order": 1,
            },
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("parent", form.errors)

    def test_category_update_form_exposes_is_active_but_not_business(self):
        category = create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )

        form = CategoryUpdateForm(
            instance=category,
            business=self.business,
        )

        self.assertIn("is_active", form.fields)
        self.assertNotIn("business", form.fields)

    def test_category_update_form_excludes_itself_from_parent_queryset(self):
        category = create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )

        form = CategoryUpdateForm(
            instance=category,
            business=self.business,
        )

        self.assertNotIn(category, form.fields["parent"].queryset)


class TaxFormTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )

    def valid_tax_data(self, **overrides):
        data = {
            "name": "IVA 21%",
            "code": "",
            "tax_type": Tax.TAX_TYPE_IVA,
            "rate": "21.00",
            "clave_regimen": "01",
            "calificacion_operacion": "S1",
            "operacion_exenta": "",
            "has_equivalence_surcharge": "",
            "equivalence_surcharge_rate": "",
        }
        data.update(overrides)
        return data

    def test_tax_create_form_is_valid_with_correct_data(self):
        form = TaxCreateForm(
            data=self.valid_tax_data(),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_tax_create_form_assigns_business_to_instance(self):
        form = TaxCreateForm(
            data=self.valid_tax_data(),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())
        tax = form.save()

        self.assertEqual(tax.business, self.business)

    def test_tax_create_form_does_not_expose_business_is_default_or_is_active(self):
        form = TaxCreateForm(business=self.business)

        self.assertNotIn("business", form.fields)
        self.assertNotIn("is_default", form.fields)
        self.assertNotIn("is_active", form.fields)

    def test_tax_update_form_exposes_is_active_but_not_business_or_is_default(self):
        tax = create_tax(
            business=self.business,
            code="IVA_21",
        )

        form = TaxUpdateForm(
            instance=tax,
            business=self.business,
        )

        self.assertIn("is_active", form.fields)
        self.assertNotIn("business", form.fields)
        self.assertNotIn("is_default", form.fields)

    def test_tax_form_normalizes_code_to_uppercase(self):
        form = TaxCreateForm(
            data=self.valid_tax_data(code=" iva_21 "),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())

        self.assertEqual(form.cleaned_data["code"], "IVA_21")

    def test_tax_form_rejects_exempt_operation_with_non_zero_rate(self):
        form = TaxCreateForm(
            data=self.valid_tax_data(
                name="Exento incorrecto",
                code="EXENTO_BAD",
                rate="21.00",
                calificacion_operacion="",
                operacion_exenta="E1",
            ),
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("rate", form.errors)

    def test_tax_form_rejects_non_subject_operation_with_non_zero_rate(self):
        form = TaxCreateForm(
            data=self.valid_tax_data(
                name="No sujeto incorrecto",
                code="NO_SUJETO_BAD",
                rate="21.00",
                calificacion_operacion="N1",
                operacion_exenta="",
            ),
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("rate", form.errors)

    def test_tax_form_rejects_surcharge_without_surcharge_rate(self):
        form = TaxCreateForm(
            data=self.valid_tax_data(
                name="IVA con recargo",
                code="IVA_RE",
                has_equivalence_surcharge="on",
                equivalence_surcharge_rate="",
            ),
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("equivalence_surcharge_rate", form.errors)


class ProductFormTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )
        self.other_business = create_business(
            name="Negocio B",
            slug="negocio-b",
        )

        self.category = create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )
        self.other_category = create_category(
            business=self.other_business,
            name="Otra Categoría",
            slug="otra-categoria",
        )

        self.tax = create_tax(
            business=self.business,
            code="IVA_21",
            is_default=True,
        )
        self.other_tax = create_tax(
            business=self.other_business,
            code="IVA_21",
        )

    def valid_product_data(self, **overrides):
        data = {
            "name": "Coca-Cola 500ml",
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

    def test_product_create_form_is_valid_with_correct_data(self):
        form = ProductCreateForm(
            data=self.valid_product_data(),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_product_create_form_assigns_business_to_instance(self):
        form = ProductCreateForm(
            data=self.valid_product_data(),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())
        product = form.save()

        self.assertEqual(product.business, self.business)

    def test_product_create_form_does_not_expose_business_is_active_or_track_stock(
        self,
    ):
        form = ProductCreateForm(business=self.business)

        self.assertNotIn("business", form.fields)
        self.assertNotIn("is_active", form.fields)
        self.assertNotIn("track_stock", form.fields)

    def test_product_update_form_exposes_is_active_and_track_stock(self):
        product = create_product(
            business=self.business,
            category=self.category,
            tax=self.tax,
        )

        form = ProductUpdateForm(
            instance=product,
            business=self.business,
        )

        self.assertIn("is_active", form.fields)
        self.assertIn("track_stock", form.fields)
        self.assertNotIn("business", form.fields)

    def test_product_form_limits_category_and_tax_to_current_business(self):
        form = ProductCreateForm(business=self.business)

        self.assertIn(self.category, form.fields["category"].queryset)
        self.assertNotIn(self.other_category, form.fields["category"].queryset)

        self.assertIn(self.tax, form.fields["tax"].queryset)
        self.assertNotIn(self.other_tax, form.fields["tax"].queryset)

    def test_product_form_rejects_category_from_other_business(self):
        form = ProductCreateForm(
            data=self.valid_product_data(category=self.other_category.pk),
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("category", form.errors)

    def test_product_form_rejects_tax_from_other_business(self):
        form = ProductCreateForm(
            data=self.valid_product_data(tax=self.other_tax.pk),
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("tax", form.errors)

    def test_product_form_rejects_inactive_tax(self):
        inactive_tax = create_tax(
            business=self.business,
            name="IVA inactivo",
            code="IVA_INACTIVO",
            is_active=False,
        )

        form = ProductCreateForm(
            data=self.valid_product_data(tax=inactive_tax.pk),
            business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("tax", form.errors)

    def test_product_create_form_uses_model_default_track_stock(self):
        form = ProductCreateForm(
            data=self.valid_product_data(),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())
        product = form.save()

        self.assertTrue(product.track_stock)

    def test_product_create_form_service_forces_no_stock(self):
        form = ProductCreateForm(
            data=self.valid_product_data(
                name="Servicio instalación",
                sku="SERV_INST",
                barcode="",
                is_service="on",
            ),
            business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors.as_data())
        product = form.save()

        self.assertTrue(product.is_service)
        self.assertFalse(product.track_stock)
        self.assertIsNone(product.barcode)
