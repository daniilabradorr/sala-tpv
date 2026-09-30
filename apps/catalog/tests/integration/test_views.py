from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from decimal import Decimal
from apps.catalog.models import Category, Tax, Product
from apps.catalog.tests.factories import create_category, create_tax, create_product
from apps.inventory.models import InventoryItem, StockMovement
from apps.sales.services import add_sale_line, open_sale
from apps.sales.tests.factories import create_pos_settings
from apps.users.models import RoleChoices
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_store_access,
    create_user,
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

        self.assertRedirects(response, reverse("catalog:product_list"))

    def test_product_list_searches_and_filters_server_side(self):
        self.login_as(self.cashier)
        response = self.client.get(
            reverse("catalog:product_list"),
            {
                "q": "PRD000001",
                "category": self.category.pk,
                "type": "physical",
                "status": "active",
                "stock": "tracked",
            },
        )
        self.assertContains(response, self.product.name)
        self.assertNotContains(response, self.other_product.name)

    def test_product_list_htmx_returns_results_partial_and_varies(self):
        self.login_as(self.cashier)
        response = self.client.get(
            reverse("catalog:product_list"), HTTP_HX_REQUEST="true"
        )
        self.assertTemplateUsed(
            response, "catalog/products/partials/_product_results.html"
        )
        self.assertNotContains(response, "<html")
        self.assertIn("HX-Request", response.headers["Vary"])
        self.assertContains(response, 'id="product-results"', count=1)

    def test_product_list_full_page_has_one_outer_swap_target(self):
        self.login_as(self.cashier)
        response = self.client.get(reverse("catalog:product_list"))
        self.assertTemplateUsed(response, "catalog/products/product_list.html")
        self.assertContains(response, 'id="product-results"', count=1)
        self.assertContains(response, 'hx-swap="outerHTML"')

    def test_product_list_individual_filters_and_combination(self):
        service = create_product(
            business=self.business,
            name="Asesoría especial",
            sku="SERV-42",
            barcode=None,
            is_service=True,
            track_stock=False,
            is_active=False,
        )
        cases = (
            ({"q": "Coca-Cola"}, self.product.name, service.name),
            ({"q": "COCA_500"}, self.product.name, service.name),
            ({"q": "PRD000001"}, self.product.name, service.name),
            ({"category": self.category.pk}, self.product.name, service.name),
            ({"type": "physical"}, self.product.name, service.name),
            ({"type": "service"}, service.name, self.product.name),
            ({"status": "active"}, self.product.name, service.name),
            ({"status": "inactive"}, service.name, self.product.name),
            ({"stock": "tracked"}, self.product.name, service.name),
            ({"stock": "untracked"}, service.name, self.product.name),
            (
                {
                    "q": "asesoría",
                    "type": "service",
                    "status": "inactive",
                    "stock": "untracked",
                },
                service.name,
                self.product.name,
            ),
        )
        self.login_as(self.cashier)
        for params, included, excluded in cases:
            with self.subTest(params=params):
                response = self.client.get(reverse("catalog:product_list"), params)
                self.assertContains(response, included)
                self.assertNotContains(response, excluded)

    def test_product_list_paginates_25_and_preserves_filters(self):
        for index in range(30):
            create_product(
                business=self.business,
                name=f"Producto paginado {index:02d}",
                sku=f"PAGE-{index:02d}",
                barcode=f"PAGECODE{index:02d}",
            )
        self.login_as(self.cashier)
        response = self.client.get(
            reverse("catalog:product_list"), {"q": "Producto paginado", "page": 2}
        )
        self.assertEqual(len(response.context["products"]), 5)
        self.assertContains(response, "q=Producto+paginado&amp;page=1")

    def test_product_list_related_data_does_not_add_queries_per_row(self):
        self.login_as(self.cashier)
        with CaptureQueriesContext(connection) as baseline:
            response = self.client.get(reverse("catalog:product_list"))
            self.assertEqual(response.status_code, 200)
        baseline_count = len(baseline)
        for index in range(10):
            create_product(
                business=self.business,
                category=self.category,
                tax=self.tax,
                name=f"Query product {index}",
                sku=f"QUERY-{index}",
                barcode=f"QUERYCODE-{index}",
            )
        with CaptureQueriesContext(connection) as populated:
            response = self.client.get(reverse("catalog:product_list"))
            self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(populated), baseline_count + 1)

    def test_category_search_htmx_is_scoped_partial_and_varies(self):
        self.login_as(self.cashier)
        response = self.client.get(
            reverse("catalog:category_list"),
            {"q": "Beb"},
            HTTP_HX_REQUEST="true",
        )
        self.assertTemplateUsed(
            response, "catalog/categories/partials/_category_results.html"
        )
        self.assertContains(response, "Bebidas")
        self.assertNotContains(response, "Categoría Otro Negocio")
        self.assertContains(response, 'id="category-results"', count=1)
        self.assertIn("HX-Request", response.headers["Vary"])

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

    def test_default_tax_cannot_be_deactivated_through_update(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("catalog:tax_update", kwargs={"pk": self.tax.pk}),
            data={**self.valid_tax_data(name=self.tax.name, code=self.tax.code)},
        )

        self.tax.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("catalog:tax_detail", kwargs={"pk": self.tax.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.tax.is_active)

    def test_mutation_endpoints_reject_get(self):
        self.login_as(self.owner)
        urls = [
            reverse("catalog:category_activate", kwargs={"pk": self.category.pk}),
            reverse("catalog:category_deactivate", kwargs={"pk": self.category.pk}),
            reverse("catalog:tax_activate", kwargs={"pk": self.tax.pk}),
            reverse("catalog:tax_deactivate", kwargs={"pk": self.tax.pk}),
            reverse("catalog:tax_set_default", kwargs={"pk": self.tax.pk}),
            reverse("catalog:product_activate", kwargs={"pk": self.product.pk}),
            reverse("catalog:product_deactivate", kwargs={"pk": self.product.pk}),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

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

    def test_tracked_product_detail_reads_inventory_for_owner_and_manager(self):
        first = create_store(business=self.business, name="Centro", code="CENTRO")
        second = create_store(business=self.business, name="Norte", code="NORTE")
        InventoryItem.objects.create(
            business=self.business,
            store=first,
            product=self.product,
            current_stock=Decimal("8"),
            reserved_stock=Decimal("2"),
        )
        InventoryItem.objects.create(
            business=self.business,
            store=second,
            product=self.product,
            current_stock=Decimal("4"),
            reserved_stock=Decimal("1"),
        )
        for user in (self.owner, self.manager):
            with self.subTest(role=user.role):
                self.login_as(user)
                response = self.client.get(
                    reverse("catalog:product_detail", kwargs={"pk": self.product.pk})
                )
                self.assertContains(response, "Centro")
                self.assertContains(response, "Norte")
                self.assertEqual(StockMovement.objects.count(), 0)
                self.client.logout()

    def test_cashier_only_reads_inventory_in_accessible_stores(self):
        visible = create_store(business=self.business, name="Visible", code="VISIBLE")
        hidden = create_store(business=self.business, name="Oculta", code="HIDDEN")
        create_store_access(business=self.business, user=self.cashier, store=visible)
        for store in (visible, hidden):
            InventoryItem.objects.create(
                business=self.business, store=store, product=self.product
            )
        other_store = create_store(
            business=self.other_business, name="Negocio ajeno", code="OTHER"
        )
        InventoryItem.objects.create(
            business=self.other_business,
            store=other_store,
            product=self.other_product,
        )
        self.login_as(self.cashier)

        response = self.client.get(
            reverse("catalog:product_detail", kwargs={"pk": self.product.pk})
        )

        self.assertContains(response, "Visible")
        self.assertNotContains(response, "Oculta")
        self.assertNotContains(response, "Negocio ajeno")

    def test_service_and_untracked_product_do_not_show_inventory_rows(self):
        service = create_product(
            business=self.business,
            name="Servicio",
            sku="SERVICE",
            barcode=None,
            is_service=True,
            track_stock=False,
        )
        untracked = create_product(
            business=self.business,
            name="Producto sin stock",
            sku="UNTRACKED",
            barcode="UNTRACKED-CODE",
            track_stock=False,
        )
        self.login_as(self.cashier)
        service_response = self.client.get(
            reverse("catalog:product_detail", kwargs={"pk": service.pk})
        )
        untracked_response = self.client.get(
            reverse("catalog:product_detail", kwargs={"pk": untracked.pk})
        )
        self.assertContains(service_response, "no requiere inventario físico")
        self.assertEqual(service_response.context["inventory_items"], [])
        self.assertNotContains(service_response, "Stock actual")
        self.assertContains(untracked_response, "no controla stock")
        self.assertEqual(untracked_response.context["inventory_items"], [])
        self.assertNotContains(untracked_response, "Stock actual")

    def test_owner_can_create_product_and_manipulated_business_is_ignored(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("catalog:product_create"),
            data={
                **self.valid_product_data(),
                "business": str(self.other_business.pk),
                "is_active": "on",
                "track_stock": "on",
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

    def test_owner_catalog_lists_expose_complete_management_actions(self):
        self.login_as(self.owner)
        expectations = (
            ("category_list", ("Nueva categoría", "Ver", "Editar", "Eliminar")),
            ("product_list", ("Nuevo producto", "Ver", "Editar", "Eliminar")),
            (
                "tax_list",
                (
                    "Nuevo impuesto",
                    "Ver",
                    "Editar",
                    "Eliminar",
                    "Establecer como predeterminado",
                ),
            ),
        )
        extra_tax = create_tax(
            business=self.business, name="IVA 10%", code="IVA_10", is_default=False
        )
        self.assertFalse(extra_tax.is_default)
        for route, labels in expectations:
            with self.subTest(route=route):
                response = self.client.get(reverse(f"catalog:{route}"))
                for label in labels:
                    self.assertContains(response, label)

    def test_category_delete_is_real_post_only_and_sets_products_category_null(self):
        self.login_as(self.owner)
        url = reverse("catalog:category_delete", kwargs={"pk": self.category.pk})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())

        response = self.client.post(url)

        self.assertRedirects(response, reverse("catalog:category_list"))
        self.assertFalse(Category.objects.filter(pk=self.category.pk).exists())
        self.product.refresh_from_db()
        self.assertIsNone(self.product.category)

    def test_category_delete_is_tenant_scoped_and_permission_protected(self):
        self.login_as(self.owner)
        other_url = reverse(
            "catalog:category_delete", kwargs={"pk": self.other_category.pk}
        )
        self.assertEqual(self.client.post(other_url).status_code, 404)
        self.client.logout()
        self.login_as(self.cashier)
        own_url = reverse("catalog:category_delete", kwargs={"pk": self.category.pk})
        self.assertEqual(self.client.post(own_url).status_code, 403)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())

    def test_product_delete_preserves_sale_line_snapshot(self):
        create_pos_settings(
            business=self.business,
            require_open_cash_register=False,
            enable_stock_control=False,
        )
        store = create_store(
            business=self.business, name="Tienda ventas", code="VENTAS"
        )
        sale = open_sale(business=self.business, store=store, opened_by=self.owner)
        line = add_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            quantity=Decimal("2.000"),
            user=self.owner,
        )
        snapshot = (
            line.product_name,
            line.sku,
            line.quantity,
            line.unit_base_price,
            line.tax_rate,
            line.line_total,
        )
        self.login_as(self.owner)
        url = reverse("catalog:product_delete", kwargs={"pk": self.product.pk})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

        response = self.client.post(url)

        self.assertRedirects(response, reverse("catalog:product_list"))
        self.assertFalse(Product.objects.filter(pk=self.product.pk).exists())
        line.refresh_from_db()
        self.assertIsNone(line.product)
        self.assertEqual(
            (
                line.product_name,
                line.sku,
                line.quantity,
                line.unit_base_price,
                line.tax_rate,
                line.line_total,
            ),
            snapshot,
        )
        self.assertTrue(type(sale).objects.filter(pk=sale.pk).exists())

    def test_product_delete_is_tenant_scoped_permission_protected_and_safe(self):
        self.login_as(self.owner)
        self.assertEqual(
            self.client.post(
                reverse("catalog:product_delete", kwargs={"pk": self.other_product.pk})
            ).status_code,
            404,
        )
        store = create_store(business=self.business, name="Inventario", code="INV")
        item = InventoryItem.objects.create(
            business=self.business, store=store, product=self.product
        )
        response = self.client.post(
            reverse("catalog:product_delete", kwargs={"pk": self.product.pk}),
            follow=True,
        )
        self.assertContains(response, "información relacionada que debe conservarse")
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
        self.assertTrue(InventoryItem.objects.filter(pk=item.pk).exists())
        self.client.logout()
        self.login_as(self.cashier)
        self.assertEqual(
            self.client.post(
                reverse("catalog:product_delete", kwargs={"pk": self.product.pk})
            ).status_code,
            403,
        )

    def test_tax_delete_contract_default_product_and_explicit_replacement(self):
        removable = create_tax(
            business=self.business, name="IVA 4%", code="IVA_4", is_default=False
        )
        self.login_as(self.owner)
        removable_url = reverse("catalog:tax_delete", kwargs={"pk": removable.pk})
        self.assertEqual(self.client.get(removable_url).status_code, 200)
        self.assertTrue(Tax.objects.filter(pk=removable.pk).exists())
        self.assertRedirects(
            self.client.post(removable_url), reverse("catalog:tax_list")
        )
        self.assertFalse(Tax.objects.filter(pk=removable.pk).exists())

        default_url = reverse("catalog:tax_delete", kwargs={"pk": self.tax.pk})
        response = self.client.post(default_url, follow=True)
        self.assertContains(response, "impuesto predeterminado")
        self.assertTrue(Tax.objects.filter(pk=self.tax.pk).exists())

        replacement = create_tax(
            business=self.business, name="IVA 10%", code="IVA_10", is_default=False
        )
        self.client.post(
            reverse("catalog:tax_set_default", kwargs={"pk": replacement.pk})
        )
        response = self.client.post(default_url, follow=True)
        self.assertContains(response, "asignado a uno o más productos")
        self.assertTrue(Tax.objects.filter(pk=self.tax.pk).exists())
        self.product.tax = None
        self.product.save(update_fields=["tax", "updated_at"])
        self.assertRedirects(self.client.post(default_url), reverse("catalog:tax_list"))
        self.assertFalse(Tax.objects.filter(pk=self.tax.pk).exists())

    def test_tax_delete_is_tenant_scoped_and_permission_protected(self):
        self.login_as(self.owner)
        self.assertEqual(
            self.client.post(
                reverse("catalog:tax_delete", kwargs={"pk": self.other_tax.pk})
            ).status_code,
            404,
        )
        self.client.logout()
        self.login_as(self.cashier)
        self.assertEqual(
            self.client.post(
                reverse("catalog:tax_delete", kwargs={"pk": self.tax.pk})
            ).status_code,
            403,
        )
