"""Tests de integración HTTP para las views del módulo sales."""

from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.cash_register.models import CashRegister, CashSession
from apps.catalog.models import Category
from apps.inventory.models import StockMovement
from apps.sales.models import Sale, SaleReturn, SaleStatusChoices
from apps.sales.services import add_sale_line, complete_sale, open_sale
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sale_return,
    create_sale_return_line,
    create_sales_business,
    create_sales_customer,
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
                        "sales/sale_workspace.html": (
                            "workspace {{ sale.pk }} {% for product in products %}"
                            "{{ product.name }} {{ product.sku }} {{ product.barcode }}"
                            "{% endfor %}"
                        ),
                        "sales/partials/_product_grid.html": (
                            "grid {% for product in products %}{{ product.name }}{% endfor %}"
                        ),
                        "sales/partials/_cart.html": (
                            "<aside id='sale-cart'>cart {{ sale.total_amount }} "
                            "{{ cart_form.errors }}</aside>"
                        ),
                        "sales/partials/_workspace_header.html": (
                            "header {{ sale.customer }} {{ header_form.errors }}"
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
            "sale_line_quantity_update": {
                "store_id": 1,
                "sale_pk": 2,
                "line_pk": 3,
            },
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

        self.assertEqual(len(reversed_urls), 18)
        self.assertEqual(len(set(reversed_urls.values())), 18)
        for url in reversed_urls.values():
            # URLs are included under the `sales/` prefix in config.urls,
            # so assert presence of the expected store fragment instead
            self.assertIn("/stores/1/", url)

    def login_as(self, user):
        logged_in = self.client.login(
            email=user.email,
            password=self.password,
        )
        self.assertTrue(logged_in)

    def create_cash_register(self, *, business=None, store=None, name="Caja HTTP"):
        business = business or self.business
        store = store or self.store
        return CashRegister.objects.create(
            business=business,
            store=store,
            name=name,
            code=f"HTTP-{CashRegister.objects.count() + 1}",
        )

    def create_cash_session(self, *, register, user=None, closed=False):
        user = user or self.owner
        session = CashSession.objects.create(
            business=register.business,
            store=register.store,
            cash_register=register,
            opened_by=user,
        )
        if closed:
            session.status = CashSession.Status.CLOSED
            session.closed_at = timezone.now()
            session.closed_by = user
            session.counted_cash_amount = session.expected_cash_amount
            session.save()
        return session

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

    def test_open_sale_uses_workspace_with_scoped_search_and_htmx_grid(self):
        self.login_as(self.owner)
        sale, _line = self.create_open_sale_with_line()
        create_sales_product(
            business=self.business, tax=self.tax, name="Café Especial", sku="CAF-1"
        )
        inactive = create_sales_product(
            business=self.business, tax=self.tax, name="Café inactivo"
        )
        inactive.is_active = False
        inactive.save(update_fields=["is_active", "updated_at"])

        response = self.client.get(
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            {"q": "CAF-1"},
        )

        self.assertTemplateUsed(response, "sales/sale_workspace.html")
        self.assertContains(response, "Café Especial")
        self.assertNotContains(response, "Café inactivo")
        self.assertNotContains(response, self.other_product.name)

        response = self.client.get(
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            {"q": "Café"},
            HTTP_HX_REQUEST="true",
        )
        self.assertTemplateUsed(response, "sales/partials/_product_grid.html")

    def test_workspace_category_filter_is_tenant_scoped(self):
        self.login_as(self.owner)
        sale, _line = self.create_open_sale_with_line()
        category = Category.objects.create(business=self.business, name="Bebidas")
        product = create_sales_product(
            business=self.business,
            tax=self.tax,
            name="Agua filtrada",
        )
        product.category = category
        product.save(update_fields=["category", "updated_at"])
        response = self.client.get(
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            {"category": category.pk},
        )
        self.assertContains(response, product.name)
        self.assertNotContains(response, self.product.name)

    def test_quantity_endpoint_preserves_price_and_discount_and_supports_htmx(self):
        self.login_as(self.owner)
        sale, line = self.create_open_sale_with_line()
        original_price = line.unit_base_price
        original_discount = line.discount_amount
        url = reverse(
            "sales:sale_line_quantity_update",
            kwargs={
                "store_id": self.store.pk,
                "sale_pk": sale.pk,
                "line_pk": line.pk,
            },
        )
        response = self.client.post(url, {"quantity": "2.500"}, HTTP_HX_REQUEST="true")
        line.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "sales/partials/_cart.html")
        self.assertEqual(line.quantity, Decimal("2.500"))
        self.assertEqual(line.unit_base_price, original_price)
        self.assertEqual(line.discount_amount, original_discount)

        response = self.client.post(url, {"quantity": "3.000"})
        self.assertRedirects(
            response,
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            fetch_redirect_response=False,
        )

    def test_header_customer_mode_is_processed_server_side(self):
        self.login_as(self.owner)
        customer = create_sales_customer(business=self.business)
        sale = open_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
            customer=customer,
        )
        url = reverse(
            "sales:sale_header_update",
            kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
        )

        response = self.client.post(
            url,
            {
                "customer_mode": "counter",
                "customer": customer.pk,
                "document_type_requested": "ticket",
            },
        )
        sale.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(sale.customer)

        response = self.client.post(
            url,
            {
                "customer_mode": "customer",
                "customer": customer.pk,
                "document_type_requested": "ticket",
            },
        )
        sale.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sale.customer, customer)

    def test_header_rejects_invalid_customer_mode_without_modifying_sale(self):
        self.login_as(self.owner)
        customer = create_sales_customer(business=self.business)
        sale = open_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
            customer=customer,
        )
        response = self.client.post(
            reverse(
                "sales:sale_header_update",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            {
                "customer_mode": "invalid",
                "customer": "",
                "document_type_requested": "ticket",
            },
        )
        sale.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertIn("customer_mode", response.context["form"].errors)
        self.assertEqual(sale.customer, customer)

    def test_invoice_without_customer_is_rejected_for_fallback_and_htmx(self):
        self.login_as(self.owner)
        sale = open_sale(business=self.business, store=self.store, opened_by=self.owner)
        url = reverse(
            "sales:sale_header_update",
            kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
        )
        data = {
            "customer_mode": "customer",
            "customer": "",
            "document_type_requested": "invoice",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("customer", response.context["form"].errors)
        response = self.client.post(url, data, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "sales/partials/_workspace_header.html")
        sale.refresh_from_db()
        self.assertEqual(sale.document_type_requested, "ticket")

    def test_quick_add_htmx_keeps_cart_on_error_and_success(self):
        self.login_as(self.owner)
        sale = open_sale(business=self.business, store=self.store, opened_by=self.owner)
        url = reverse(
            "sales:sale_line_add",
            kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
        )
        response = self.client.post(
            url,
            {"product": self.product.pk, "quantity": "0"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "sales/partials/_cart.html")
        self.assertTemplateNotUsed(response, "sales/sale_line_form.html")
        self.assertContains(response, "sale-cart")
        form = response.context["cart_form"]
        self.assertIn("quantity", form.errors)
        self.assertEqual(form.errors.as_data()["quantity"][0].code, "min_value")

        with patch(
            "apps.sales.views.add_sale_line",
            side_effect=ValidationError("No se puede añadir este producto."),
        ):
            response = self.client.post(
                url,
                {"product": self.product.pk, "quantity": "1.000"},
                HTTP_HX_REQUEST="true",
            )
        self.assertTemplateUsed(response, "sales/partials/_cart.html")
        self.assertContains(response, "No se puede añadir este producto.")
        self.assertEqual(sale.lines.count(), 0)

        response = self.client.post(
            url,
            {"product": self.product.pk, "quantity": "1.000"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "sales/partials/_cart.html")
        self.assertEqual(sale.lines.count(), 1)

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

    def test_open_get_initializes_single_register_and_only_exposes_safe_session(self):
        settings = self.business.pos_settings
        settings.require_open_cash_register = True
        settings.save(update_fields=["require_open_cash_register", "updated_at"])
        register = self.create_cash_register()
        self.create_cash_session(register=register, closed=True)
        open_session = self.create_cash_session(register=register)

        other_store = create_sales_store(business=self.business, name="Otra tienda")
        other_store_register = self.create_cash_register(store=other_store)
        self.create_cash_session(register=other_store_register)

        other_owner = create_sales_user(business=self.other_business)
        other_register = self.create_cash_register(
            business=self.other_business,
            store=self.other_store,
            name="Caja ajena",
        )
        self.create_cash_session(register=other_register, user=other_owner)

        inactive_register = self.create_cash_register(name="Caja inactiva")
        inactive_session = self.create_cash_session(register=inactive_register)
        inactive_register.is_active = False
        inactive_register.save(update_fields=["is_active", "updated_at"])

        self.login_as(self.owner)
        response = self.client.get(
            reverse("sales:sale_open", kwargs={"store_id": self.store.pk})
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial["cash_register"], register)
        self.assertEqual(form.initial["cash_session"], open_session)
        self.assertEqual(
            set(form.fields["cash_session"].queryset.values_list("pk", flat=True)),
            {open_session.pk},
        )
        self.assertNotIn(
            inactive_session.pk,
            form.fields["cash_session"].queryset.values_list("pk", flat=True),
        )

    def test_open_get_with_multiple_registers_does_not_choose_one_arbitrarily(self):
        settings = self.business.pos_settings
        settings.require_open_cash_register = True
        settings.save(update_fields=["require_open_cash_register", "updated_at"])
        first_register = self.create_cash_register(name="Caja primera")
        second_register = self.create_cash_register(name="Caja segunda")
        first_session = self.create_cash_session(register=first_register)
        second_session = self.create_cash_session(register=second_register)

        self.login_as(self.owner)
        response = self.client.get(
            reverse("sales:sale_open", kwargs={"store_id": self.store.pk})
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertNotIn("cash_register", form.initial)
        self.assertNotIn("cash_session", form.initial)
        self.assertEqual(
            set(form.fields["cash_session"].queryset.values_list("pk", flat=True)),
            {first_session.pk, second_session.pk},
        )

        mismatch_response = self.client.post(
            reverse("sales:sale_open", kwargs={"store_id": self.store.pk}),
            data={
                "document_type_requested": "ticket",
                "cash_register": first_register.pk,
                "cash_session": second_session.pk,
            },
        )
        self.assertEqual(mismatch_response.status_code, 200)
        self.assertIn("cash_session", mismatch_response.context["form"].errors)
        self.assertFalse(Sale.objects.exists())

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

    def test_open_sale_edit_and_complete_never_require_sensitive_action_pin(self):
        settings = self.business.pos_settings
        settings.require_pin_for_sensitive_actions = True
        settings.save(update_fields=["require_pin_for_sensitive_actions", "updated_at"])
        self.login_as(self.owner)
        sale = open_sale(business=self.business, store=self.store, opened_by=self.owner)

        header_response = self.client.post(
            reverse(
                "sales:sale_header_update",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            data={"customer": "", "document_type_requested": "ticket"},
        )
        self.assertEqual(header_response.status_code, 302)
        add_response = self.client.post(
            reverse(
                "sales:sale_line_add",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            ),
            data={
                "product": self.product.pk,
                "quantity": "1.000",
                "unit_base_price": "10.00",
                "discount_amount": "0.00",
            },
        )
        self.assertEqual(add_response.status_code, 302)
        line = sale.lines.get()
        update_response = self.client.post(
            reverse(
                "sales:sale_line_update",
                kwargs={
                    "store_id": self.store.pk,
                    "sale_pk": sale.pk,
                    "line_pk": line.pk,
                },
            ),
            data={
                "quantity": "2.000",
                "unit_base_price": "10.00",
                "discount_amount": "0.00",
            },
        )
        self.assertEqual(update_response.status_code, 302)
        delete_response = self.client.post(
            reverse(
                "sales:sale_line_delete",
                kwargs={
                    "store_id": self.store.pk,
                    "sale_pk": sale.pk,
                    "line_pk": line.pk,
                },
            )
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(sale.lines.exists())
        add_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            quantity=Decimal("1.000"),
            user=self.owner,
        )
        complete_response = self.client.post(
            reverse(
                "sales:sale_complete",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            )
        )
        self.assertEqual(complete_response.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.status, SaleStatusChoices.COMPLETED)
        self.assertEqual(sale.closed_by, self.owner)

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
                "restock": "on",
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

    def test_full_return_flow_without_restock_marks_returned_without_stock_entry(self):
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
            data={"reason": "Producto no reaprovechable"},
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

        return_line = return_doc.lines.get()
        self.assertFalse(return_line.restock)

        complete_response = self.client.post(
            reverse(
                "sales:return_complete",
                kwargs={"store_id": self.store.pk, "return_pk": return_doc.pk},
            ),
            data={},
        )

        sale.refresh_from_db()
        self.inventory_item.refresh_from_db()

        self.assertRedirects(
            complete_response,
            reverse(
                "sales:return_detail",
                kwargs={"store_id": self.store.pk, "return_pk": return_doc.pk},
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(sale.status, SaleStatusChoices.RETURNED)
        self.assertEqual(self.inventory_item.current_stock, Decimal("8.000"))
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type=StockMovement.TYPE_SALE_RETURN,
                reference_id=f"return:{return_doc.pk}:{return_line.pk}",
            ).exists()
        )

    def test_return_line_update_get_sets_initial_restock_from_line(self):
        self.login_as(self.owner)
        sale, sale_line = self.create_open_sale_with_line(quantity=Decimal("2.000"))
        complete_sale(
            business=self.business,
            sale=sale,
            closed_by=self.owner,
        )
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.owner,
            reason="Revisar inicial",
        )
        return_line = create_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=sale_line,
            quantity=Decimal("1.000"),
            restock=False,
        )

        response = self.client.get(
            reverse(
                "sales:return_line_update",
                kwargs={
                    "store_id": self.store.pk,
                    "return_pk": return_doc.pk,
                    "line_pk": return_line.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.context["form"].initial["restock"], False)

    def test_return_line_update_post_updates_restock(self):
        self.login_as(self.owner)
        sale, sale_line = self.create_open_sale_with_line(quantity=Decimal("2.000"))
        complete_sale(
            business=self.business,
            sale=sale,
            closed_by=self.owner,
        )
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.owner,
            reason="Editar reposición",
        )
        return_line = create_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=sale_line,
            quantity=Decimal("1.000"),
            restock=True,
        )

        response = self.client.post(
            reverse(
                "sales:return_line_update",
                kwargs={
                    "store_id": self.store.pk,
                    "return_pk": return_doc.pk,
                    "line_pk": return_line.pk,
                },
            ),
            data={
                "quantity": "1.000",
            },
        )

        return_line.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertFalse(return_line.restock)
