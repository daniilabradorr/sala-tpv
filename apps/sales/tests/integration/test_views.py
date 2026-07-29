"""Tests de integración HTTP para las views del módulo sales."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.inventory.models import StockMovement
from apps.sales.models import Sale, SaleReturn, SaleStatusChoices
from apps.sales.services import add_sale_line, complete_sale, open_sale
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sales_business,
    create_sales_inventory_item,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)
from apps.users.models import RoleChoices


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
                        "sales/sale_list.html": (
                            "{% for sale in sales %}{{ sale.pk }} {% endfor %}"
                        ),
                        "sales/sale_detail.html": (
                            "{{ sale.pk }} {% for line in lines %}{{ line.pk }} {% endfor %}"
                        ),
                        "sales/sale_open.html": "{{ form.errors }}",
                        "sales/sale_header_form.html": "{{ form.errors }}",
                        "sales/sale_line_form.html": "{{ form.errors }}",
                        "sales/sale_cancel_confirm.html": "{{ form.errors }}",
                        "sales/return_list.html": (
                            "{% for return_doc in returns %}{{ return_doc.pk }} {% endfor %}"
                        ),
                        "sales/return_detail.html": (
                            "{{ return_doc.pk }} {% for line in lines %}{{ line.pk }} {% endfor %}"
                        ),
                        "sales/return_form.html": "{{ form.errors }}",
                        "sales/return_line_form.html": "{{ form.errors }}",
                        "sales/return_cancel_confirm.html": "{{ form.errors }}",
                    },
                )
            ],
        },
    }
]


@override_settings(
    ROOT_URLCONF="config.urls",
    TEMPLATES=TEST_TEMPLATES,
    LOGIN_URL="/users/login/",
)
class SaleViewsIntegrationTests(TestCase):
    password = "testpass123"

    def setUp(self):  # noqa: N802
        self.business = create_sales_business(name="Negocio HTTP A")
        self.other_business = create_sales_business(name="Negocio HTTP B")
        self.store = create_sales_store(business=self.business, name="Tienda A")
        self.other_store = create_sales_store(
            business=self.other_business,
            name="Tienda B",
        )
        self.owner = create_sales_user(
            business=self.business,
            role=RoleChoices.OWNER,
            password=self.password,
        )
        self.cashier_without_access = create_sales_user(
            business=self.business,
            role=RoleChoices.CASHIER,
            password=self.password,
        )
        create_pos_settings(
            business=self.business,
            require_open_cash_register=False,
            require_pin_for_sensitive_actions=False,
            enable_stock_control=True,
        )
        create_pos_settings(
            business=self.other_business,
            require_open_cash_register=False,
            require_pin_for_sensitive_actions=False,
        )
        self.tax = create_sales_tax(business=self.business)
        self.other_tax = create_sales_tax(business=self.other_business)
        self.product = create_sales_product(
            business=self.business,
            tax=self.tax,
            name="Producto A",
            base_price=Decimal("10.00"),
        )
        self.other_product = create_sales_product(
            business=self.other_business,
            tax=self.other_tax,
            name="Producto B",
        )
        self.inventory_item = create_sales_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("10.000"),
        )

    def test_real_urlconf_reverses_all_sales_routes(self):
        route_kwargs = {
            "sale_list": {"store_id": 1},
            "sale_open": {"store_id": 1},
            "sale_detail": {"store_id": 1, "sale_pk": 2},
            "sale_header_update": {"store_id": 1, "sale_pk": 2},
            "sale_line_add": {"store_id": 1, "sale_pk": 2},
            "sale_line_update": {"store_id": 1, "sale_pk": 2, "line_pk": 3},
            "sale_line_delete": {"store_id": 1, "sale_pk": 2, "line_pk": 3},
            "sale_complete": {"store_id": 1, "sale_pk": 2},
            "sale_cancel": {"store_id": 1, "sale_pk": 2},
            "return_list": {"store_id": 1},
            "return_create": {"store_id": 1, "sale_pk": 2},
            "return_detail": {"store_id": 1, "return_pk": 4},
            "return_line_add": {"store_id": 1, "return_pk": 4},
            "return_line_update": {"store_id": 1, "return_pk": 4, "line_pk": 3},
            "return_line_delete": {"store_id": 1, "return_pk": 4, "line_pk": 3},
            "return_complete": {"store_id": 1, "return_pk": 4},
            "return_cancel": {"store_id": 1, "return_pk": 4},
        }

        reversed_urls = {
            name: reverse(f"sales:{name}", kwargs=kwargs)
            for name, kwargs in route_kwargs.items()
        }

        self.assertEqual(len(reversed_urls), 17)
        self.assertEqual(len(set(reversed_urls.values())), 17)
        for url in reversed_urls.values():
            self.assertTrue(url.startswith("/stores/1/"))

    def login_as(self, user):
        logged_in = self.client.login(
            email=user.email,
            password=self.password,
        )
        self.assertTrue(logged_in)

    def create_open_sale_with_line(self, quantity=Decimal("1.000")):
        sale = open_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
        )
        line = add_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            quantity=quantity,
            user=self.owner,
        )
        return sale, line

    def test_unauthenticated_user_is_redirected_from_sale_list(self):
        response = self.client.get(
            reverse("sales:sale_list", kwargs={"store_id": self.store.pk})
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/users/login/", response.url)

    def test_owner_can_open_sale(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("sales:sale_open", kwargs={"store_id": self.store.pk}),
            data={
                "document_type_requested": "ticket",
                "customer": "",
                "cash_register": "",
                "cash_session": "",
            },
        )

        sale = Sale.objects.get(business=self.business)

        self.assertRedirects(
            response,
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(sale.status, SaleStatusChoices.OPEN)
        self.assertEqual(sale.opened_by, self.owner)

    def test_cashier_without_store_access_cannot_open_sale(self):
        self.login_as(self.cashier_without_access)

        response = self.client.post(
            reverse("sales:sale_open", kwargs={"store_id": self.store.pk}),
            data={"document_type_requested": "ticket"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Sale.objects.exists())

    def test_add_line_view_creates_snapshot_and_updates_totals(self):
        self.login_as(self.owner)
        sale = open_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
        )

        response = self.client.post(
            reverse(
                "sales:sale_line_add",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            data={
                "product": self.product.pk,
                "quantity": "2.000",
                "unit_base_price": "10.00",
                "discount_amount": "0.00",
            },
        )

        sale.refresh_from_db()
        line = sale.lines.get()

        self.assertRedirects(
            response,
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(line.product_name, self.product.name)
        self.assertEqual(sale.total_amount, Decimal("24.20"))

    def test_line_add_rejects_product_from_other_business(self):
        self.login_as(self.owner)
        sale = open_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
        )

        response = self.client.post(
            reverse(
                "sales:sale_line_add",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            data={
                "product": self.other_product.pk,
                "quantity": "1.000",
                "unit_base_price": "10.00",
                "discount_amount": "0.00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sale.lines.count(), 0)

    def test_complete_sale_view_changes_status_stock_and_movement(self):
        self.login_as(self.owner)
        sale, _line = self.create_open_sale_with_line(quantity=Decimal("2.000"))

        response = self.client.post(
            reverse(
                "sales:sale_complete",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            )
        )

        sale.refresh_from_db()
        self.inventory_item.refresh_from_db()

        self.assertRedirects(
            response,
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(sale.status, SaleStatusChoices.COMPLETED)
        self.assertEqual(self.inventory_item.current_stock, Decimal("8.000"))
        self.assertTrue(
            StockMovement.objects.filter(
                movement_type=StockMovement.TYPE_SALE,
                reference_type=StockMovement.REF_SALE,
            ).exists()
        )

    def test_sale_detail_returns_404_for_sale_from_other_business(self):
        self.login_as(self.owner)
        other_owner = create_sales_user(
            business=self.other_business,
            role=RoleChoices.OWNER,
        )
        other_sale = open_sale(
            business=self.other_business,
            store=self.other_store,
            opened_by=other_owner,
        )

        response = self.client.get(
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": other_sale.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_full_return_flow_restores_stock_and_marks_sale_returned(self):
        self.login_as(self.owner)
        sale, sale_line = self.create_open_sale_with_line(quantity=Decimal("2.000"))
        complete_sale(
            business=self.business,
            sale=sale,
            closed_by=self.owner,
        )
        self.inventory_item.refresh_from_db()
        self.assertEqual(self.inventory_item.current_stock, Decimal("8.000"))

        create_response = self.client.post(
            reverse(
                "sales:return_create",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            data={"reason": "Producto defectuoso"},
        )
        return_doc = SaleReturn.objects.get(original_sale=sale)
        self.assertRedirects(
            create_response,
            reverse(
                "sales:return_detail",
                kwargs={"store_id": self.store.pk, "return_pk": return_doc.pk},
            ),
            fetch_redirect_response=False,
        )

        add_response = self.client.post(
            reverse(
                "sales:return_line_add",
                kwargs={"store_id": self.store.pk, "return_pk": return_doc.pk},
            ),
            data={
                "original_line": sale_line.pk,
                "quantity": "2.000",
            },
        )
        self.assertEqual(add_response.status_code, 302)

        complete_response = self.client.post(
            reverse(
                "sales:return_complete",
                kwargs={"store_id": self.store.pk, "return_pk": return_doc.pk},
            ),
            data={},
        )

        sale.refresh_from_db()
        return_doc.refresh_from_db()
        self.inventory_item.refresh_from_db()

        self.assertRedirects(
            complete_response,
            reverse(
                "sales:return_detail",
                kwargs={"store_id": self.store.pk, "return_pk": return_doc.pk},
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(return_doc.status, "completed")
        self.assertEqual(sale.status, SaleStatusChoices.RETURNED)
        self.assertEqual(self.inventory_item.current_stock, Decimal("10.000"))
