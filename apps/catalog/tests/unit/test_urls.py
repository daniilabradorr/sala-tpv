from django.test import SimpleTestCase
from django.urls import resolve, reverse

from apps.catalog.views import (
    CatalogDashboardView,
    CategoryListView,
    CategoryDetailView,
    CategoryCreateView,
    CategoryUpdateView,
    CategoryActivateView,
    CategoryDeactivateView,
    TaxListView,
    TaxDetailView,
    TaxCreateView,
    TaxUpdateView,
    TaxActivateView,
    TaxDeactivateView,
    TaxSetDefaultView,
    ProductListView,
    ProductDetailView,
    ProductCreateView,
    ProductUpdateView,
    ProductActivateView,
    ProductDeactivateView,
)


class CatalogUrlsTests(SimpleTestCase):
    def test_catalog_dashboard_url_resolves(self):
        url = reverse("catalog:dashboard")

        self.assertEqual(resolve(url).func.view_class, CatalogDashboardView)

    def test_category_list_url_resolves(self):
        url = reverse("catalog:category_list")

        self.assertEqual(resolve(url).func.view_class, CategoryListView)

    def test_category_create_url_resolves(self):
        url = reverse("catalog:category_create")

        self.assertEqual(resolve(url).func.view_class, CategoryCreateView)

    def test_category_detail_url_resolves(self):
        url = reverse("catalog:category_detail", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, CategoryDetailView)

    def test_category_update_url_resolves(self):
        url = reverse("catalog:category_update", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, CategoryUpdateView)

    def test_category_activate_url_resolves(self):
        url = reverse("catalog:category_activate", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, CategoryActivateView)

    def test_category_deactivate_url_resolves(self):
        url = reverse("catalog:category_deactivate", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, CategoryDeactivateView)

    def test_tax_list_url_resolves(self):
        url = reverse("catalog:tax_list")

        self.assertEqual(resolve(url).func.view_class, TaxListView)

    def test_tax_create_url_resolves(self):
        url = reverse("catalog:tax_create")

        self.assertEqual(resolve(url).func.view_class, TaxCreateView)

    def test_tax_detail_url_resolves(self):
        url = reverse("catalog:tax_detail", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, TaxDetailView)

    def test_tax_update_url_resolves(self):
        url = reverse("catalog:tax_update", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, TaxUpdateView)

    def test_tax_activate_url_resolves(self):
        url = reverse("catalog:tax_activate", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, TaxActivateView)

    def test_tax_deactivate_url_resolves(self):
        url = reverse("catalog:tax_deactivate", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, TaxDeactivateView)

    def test_tax_set_default_url_resolves(self):
        url = reverse("catalog:tax_set_default", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, TaxSetDefaultView)

    def test_product_list_url_resolves(self):
        url = reverse("catalog:product_list")

        self.assertEqual(resolve(url).func.view_class, ProductListView)

    def test_product_create_url_resolves(self):
        url = reverse("catalog:product_create")

        self.assertEqual(resolve(url).func.view_class, ProductCreateView)

    def test_product_detail_url_resolves(self):
        url = reverse("catalog:product_detail", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, ProductDetailView)

    def test_product_update_url_resolves(self):
        url = reverse("catalog:product_update", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, ProductUpdateView)

    def test_product_activate_url_resolves(self):
        url = reverse("catalog:product_activate", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, ProductActivateView)

    def test_product_deactivate_url_resolves(self):
        url = reverse("catalog:product_deactivate", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, ProductDeactivateView)
