from django.test import TestCase, override_settings
from django.urls import reverse
from decimal import Decimal
from apps.catalog.models import Category, Tax, Product
from apps.catalog.tests.factories import create_category, create_tax, create_product
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_user


TEST_TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": False,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
            "loaders": [
                (
                    "django.template.loaders.locmem.Loader",
                    {
                        "catalog/dashboard.html": "{{ page_title }}",
                        "catalog/categories/category_list.html": "{% for category in categories %}{{ category.name }} {% endfor %}",
                        "catalog/categories/category_detail.html": "{{ category.name }}",
                        "catalog/categories/category_form.html": "{{ form.errors }}",
                        "catalog/taxes/tax_list.html": "{% for tax in taxes %}{{ tax.name }} {% endfor %}",
                        "catalog/taxes/tax_detail.html": "{{ tax.name }}",
                        "catalog/taxes/tax_form.html": "{{ form.errors }}",
                        "catalog/products/product_list.html": "{% for product in products %}{{ product.name }} {% endfor %}",
                        "catalog/products/product_detail.html": "{{ product.name }}",
                        "catalog/products/product_form.html": "{{ form.errors }}",
                    },
                )
            ],
        },
    }
]


@override_settings(
    TEMPLATES=TEST_TEMPLATES,
    LOGIN_URL="/users/login/",
)
class CatalogViewsIntegrationTests(TestCase):
    password = "testpass123"

    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )
        self.other_business = create_business(
            name="Negocio B",
            slug="negocio-b",
        )

        self.owner = create_user(
            business=self.business,
            email="owner@catalog.com",
            password=self.password,
            role=RoleChoices.OWNER,
        )
        self.manager = create_user(
            business=self.business,
            email="manager@catalog.com",
            password=self.password,
            role=RoleChoices.MANAGER,
        )
        self.cashier = create_user(
            business=self.business,
            email="cashier@catalog.com",
            password=self.password,
            role=RoleChoices.CASHIER,
        )

        self.category = create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )
        self.other_category = create_category(
            business=self.other_business,
            name="Categoría Otro Negocio",
            slug="categoria-otro-negocio",
        )

        self.tax = create_tax(
            business=self.business,
            name="IVA 21%",
            code="IVA_21",
            is_default=True,
        )
        self.other_tax = create_tax(
            business=self.other_business,
            name="IVA Otro Negocio",
            code="IVA_21",
        )

        self.product = create_product(
            business=self.business,
            category=self.category,
            tax=self.tax,
            name="Coca-Cola 500ml",
            sku="COCA_500",
            barcode="PRD000001",
        )
        self.other_product = create_product(
            business=self.other_business,
            category=self.other_category,
            tax=self.other_tax,
            name="Producto Otro Negocio",
            sku="OTRO",
            barcode="PRD999999",
        )

    def login_as(self, user):
        logged_in = self.client.login(
            email=user.email,
            password=self.password,
        )
        self.assertTrue(logged_in)

    def valid_category_data(self, **overrides):
        data = {
            "name": "Zumos",
            "slug": "",
            "parent": "",
            "sort_order": 2,
        }
        data.update(overrides)
        return data

    def valid_tax_data(self, **overrides):
        data = {
            "name": "IVA 10%",
            "code": "",
            "tax_type": Tax.TAX_TYPE_IVA,
            "rate": "10.00",
            "clave_regimen": "01",
            "calificacion_operacion": "S1",
            "operacion_exenta": "",
            "has_equivalence_surcharge": "",
            "equivalence_surcharge_rate": "",
        }
        data.update(overrides)
        return data

    def valid_product_data(self, **overrides):
        data = {
            "name": "Fanta Naranja",
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

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("catalog:dashboard"))

        self.assertEqual(response.status_code, 302)

    def test_dashboard_is_available_for_logged_user_with_business(self):
        self.login_as(self.cashier)

        response = self.client.get(reverse("catalog:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard del catálogo")

    def test_category_list_only_shows_categories_from_current_business(self):
        self.login_as(self.cashier)

        response = self.client.get(reverse("catalog:category_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bebidas")
        self.assertNotContains(response, "Categoría Otro Negocio")

    def test_category_detail_does_not_allow_cross_business_access(self):
        self.login_as(self.cashier)

        response = self.client.get(
            reverse("catalog:category_detail", kwargs={"pk": self.other_category.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_can_create_category_and_manipulated_business_is_ignored(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("catalog:category_create"),
            data={
                **self.valid_category_data(),
                "business": str(self.other_business.pk),
                "is_active": "",
            },
        )

        category = Category.objects.get(name="Zumos")

        self.assertRedirects(
            response,
            reverse("catalog:category_detail", kwargs={"pk": category.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(category.business, self.business)
        self.assertNotEqual(category.business, self.other_business)
        self.assertTrue(category.is_active)

    def test_cashier_cannot_create_category(self):
        self.login_as(self.cashier)

        response = self.client.post(
            reverse("catalog:category_create"),
            data=self.valid_category_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_manager_can_update_category(self):
        self.login_as(self.manager)

        response = self.client.post(
            reverse("catalog:category_update", kwargs={"pk": self.category.pk}),
            data={
                "name": "Bebidas editadas",
                "slug": "bebidas-editadas",
                "parent": "",
                "sort_order": 5,
                "is_active": "on",
            },
        )

        self.category.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:category_detail", kwargs={"pk": self.category.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.category.name, "Bebidas editadas")
        self.assertEqual(self.category.sort_order, 5)

    def test_owner_can_deactivate_and_activate_category(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("catalog:category_deactivate", kwargs={"pk": self.category.pk})
        )

        self.category.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:category_detail", kwargs={"pk": self.category.pk}),
            fetch_redirect_response=False,
        )
        self.assertFalse(self.category.is_active)

        response = self.client.post(
            reverse("catalog:category_activate", kwargs={"pk": self.category.pk})
        )

        self.category.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:category_detail", kwargs={"pk": self.category.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.category.is_active)

    def test_tax_list_only_shows_taxes_from_current_business(self):
        self.login_as(self.cashier)

        response = self.client.get(reverse("catalog:tax_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "IVA 21%")
        self.assertNotContains(response, "IVA Otro Negocio")

    def test_owner_can_create_tax_and_manipulated_business_is_ignored(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("catalog:tax_create"),
            data={
                **self.valid_tax_data(),
                "business": str(self.other_business.pk),
                "is_default": "on",
                "is_active": "",
            },
        )

        tax = Tax.objects.get(name="IVA 10%")

        self.assertRedirects(
            response,
            reverse("catalog:tax_detail", kwargs={"pk": tax.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(tax.business, self.business)
        self.assertNotEqual(tax.business, self.other_business)
        self.assertFalse(tax.is_default)
        self.assertTrue(tax.is_active)

    def test_cashier_cannot_create_tax(self):
        self.login_as(self.cashier)

        response = self.client.post(
            reverse("catalog:tax_create"),
            data=self.valid_tax_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_set_default_tax_changes_default_inside_current_business(self):
        self.login_as(self.owner)

        new_tax = create_tax(
            business=self.business,
            name="IVA 10%",
            code="IVA_10",
            rate="10.00",
            is_default=False,
            is_active=False,
        )

        response = self.client.post(
            reverse("catalog:tax_set_default", kwargs={"pk": new_tax.pk})
        )

        self.tax.refresh_from_db()
        new_tax.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:tax_detail", kwargs={"pk": new_tax.pk}),
            fetch_redirect_response=False,
        )
        self.assertFalse(self.tax.is_default)
        self.assertTrue(new_tax.is_default)
        self.assertTrue(new_tax.is_active)

    def test_default_tax_cannot_be_deactivated(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("catalog:tax_deactivate", kwargs={"pk": self.tax.pk})
        )

        self.tax.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:tax_detail", kwargs={"pk": self.tax.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.tax.is_active)

    def test_non_default_tax_can_be_deactivated_and_activated(self):
        self.login_as(self.owner)

        tax = create_tax(
            business=self.business,
            name="IVA 4%",
            code="IVA_4",
            rate="4.00",
            is_default=False,
        )

        response = self.client.post(
            reverse("catalog:tax_deactivate", kwargs={"pk": tax.pk})
        )

        tax.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:tax_detail", kwargs={"pk": tax.pk}),
            fetch_redirect_response=False,
        )
        self.assertFalse(tax.is_active)

        response = self.client.post(
            reverse("catalog:tax_activate", kwargs={"pk": tax.pk})
        )

        tax.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:tax_detail", kwargs={"pk": tax.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(tax.is_active)

    def test_product_list_only_shows_products_from_current_business(self):
        self.login_as(self.cashier)

        response = self.client.get(reverse("catalog:product_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Coca-Cola 500ml")
        self.assertNotContains(response, "Producto Otro Negocio")

    def test_product_detail_does_not_allow_cross_business_access(self):
        self.login_as(self.cashier)

        response = self.client.get(
            reverse("catalog:product_detail", kwargs={"pk": self.other_product.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_can_create_product_and_manipulated_business_is_ignored(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("catalog:product_create"),
            data={
                **self.valid_product_data(),
                "business": str(self.other_business.pk),
                "is_active": "",
                "track_stock": "",
            },
        )

        product = Product.objects.get(name="Fanta Naranja")

        self.assertRedirects(
            response,
            reverse("catalog:product_detail", kwargs={"pk": product.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(product.business, self.business)
        self.assertNotEqual(product.business, self.other_business)
        self.assertTrue(product.is_active)
        self.assertTrue(product.track_stock)

    def test_cashier_cannot_create_product(self):
        self.login_as(self.cashier)

        response = self.client.post(
            reverse("catalog:product_create"),
            data=self.valid_product_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_manager_can_update_product(self):
        self.login_as(self.manager)

        response = self.client.post(
            reverse("catalog:product_update", kwargs={"pk": self.product.pk}),
            data={
                "name": "Coca-Cola editada",
                "sku": "COCA_EDIT",
                "barcode": "PRD000002",
                "category": self.category.pk,
                "tax": self.tax.pk,
                "base_price": "2.50",
                "cost_price": "1.20",
                "unit": Product.UNIT_UNIDAD,
                "sort_order": 3,
                "track_stock": "on",
                "is_service": "",
                "is_active": "on",
            },
        )

        self.product.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:product_detail", kwargs={"pk": self.product.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.product.name, "Coca-Cola editada")
        self.assertEqual(self.product.base_price, Decimal("2.50"))

    def test_owner_can_deactivate_and_activate_product(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("catalog:product_deactivate", kwargs={"pk": self.product.pk})
        )

        self.product.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:product_detail", kwargs={"pk": self.product.pk}),
            fetch_redirect_response=False,
        )
        self.assertFalse(self.product.is_active)

        response = self.client.post(
            reverse("catalog:product_activate", kwargs={"pk": self.product.pk})
        )

        self.product.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("catalog:product_detail", kwargs={"pk": self.product.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.product.is_active)
