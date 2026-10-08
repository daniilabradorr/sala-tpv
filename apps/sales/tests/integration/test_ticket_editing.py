"""Authoritative ticket quantities, independent editor permissions and totals."""

from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection, models
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.sales.forms import SaleLineQuantityUpdateForm, SaleLineUpdateForm
from apps.sales.models import SaleLine
from apps.sales.services import add_sale_line, open_sale, update_sale_line
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sales_business,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


class TicketEditingTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.settings = create_pos_settings(business=self.business)
        self.product = create_sales_product(
            business=self.business,
            base_price=Decimal("10.00"),
            tax=create_sales_tax(business=self.business, rate=Decimal("21.00")),
            track_stock=False,
        )
        self.sale = open_sale(
            business=self.business, store=self.store, opened_by=self.user
        )
        self.line = add_sale_line(
            business=self.business,
            sale=self.sale,
            product=self.product,
            quantity=Decimal("2.000"),
            user=self.user,
        )
        self.client.force_login(self.user)
        self.quantity_url = self.url("sale_line_quantity_update")
        self.editor_url = self.url("sale_line_update")

    def url(self, route, *, store=None, sale=None, line=None):
        return reverse(
            f"sales:{route}",
            args=[
                (store or self.store).pk,
                (sale or self.sale).pk,
                (line or self.line).pk,
            ],
        )

    def quantity(self, value, *, htmx=True):
        return self.client.post(
            self.quantity_url,
            {"quantity": value},
            **({"HTTP_HX_REQUEST": "true"} if htmx else {}),
        )

    def discount(self, value):
        return self.client.post(
            self.editor_url + "?mode=discount",
            {"discount_amount": value},
            HTTP_HX_REQUEST="true",
        )

    def update(self, **kwargs):
        return update_sale_line(
            business=self.business,
            sale=self.sale,
            line=self.line,
            user=self.user,
            quantity=kwargs.pop("quantity", self.line.quantity),
            **kwargs,
        )

    def test_quantity_domain_and_decimal_form_remain_exact(self):
        field = SaleLine._meta.get_field("quantity")
        self.assertIsInstance(field, models.DecimalField)
        self.assertEqual((field.max_digits, field.decimal_places), (14, 3))
        for value in ("1", "1.5", "0.75", "0.125", "0.001"):
            with self.subTest(value=value):
                form = SaleLineQuantityUpdateForm({"quantity": value})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertIsInstance(form.cleaned_data["quantity"], Decimal)
                response = self.quantity(value)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'value="{value}"')
                self.line.refresh_from_db()
                self.assertIsInstance(self.line.quantity, Decimal)
                self.assertEqual(self.line.quantity, Decimal(value))

    def test_invalid_quantities_return_authoritative_cart_and_422(self):
        for value in ("0", "-1", "invalid", "1.2345", ""):
            with self.subTest(value=value):
                response = self.quantity(value)
                self.assertContains(response, 'role="alert"', status_code=422)
                self.assertContains(response, 'value="2"', status_code=422)
                self.line.refresh_from_db()
                self.assertEqual(self.line.quantity, Decimal("2.000"))
                self.sale.refresh_from_db()
                self.assertEqual(self.sale.total_amount, Decimal("24.20"))

    def test_cart_update_is_regional_and_noscript_post_works(self):
        response = self.quantity("1")
        self.assertContains(response, 'hx-sync="#sale-cart:queue all"')
        self.assertNotContains(response, "<!DOCTYPE")
        for region in (
            'id="product-grid"',
            'id="workspace-header"',
            'id="checkout-panel"',
        ):
            self.assertNotContains(response, region)
        html = response.content.decode()
        before, rest = html.split("<noscript>")
        fallback, after = rest.split("</noscript>")
        self.assertIn("Aplicar", fallback)
        self.assertNotIn("Aplicar", before + after)
        self.assertRedirects(
            self.quantity("0.125", htmx=False),
            reverse("sales:sale_detail", args=[self.store.pk, self.sale.pk]),
        )
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, Decimal("0.125"))

    def test_independent_price_and_discount_actions(self):
        for price, discount in (
            (True, True),
            (False, True),
            (True, False),
            (False, False),
        ):
            with self.subTest(price=price, discount=discount):
                self.settings.allow_manual_price = price
                self.settings.allow_manual_discounts = discount
                self.settings.max_manual_discount_percent = (
                    Decimal("20") if discount else Decimal("0")
                )
                self.settings.save()
                html = self.quantity("2").content.decode()
                self.assertEqual(">Editar precio</a>" in html, price)
                self.assertEqual(">Descuento</a>" in html, discount)
                self.assertNotIn(">Editar</a>", html)
                response = self.client.get(self.editor_url, HTTP_HX_REQUEST="true")
                self.assertEqual(
                    "discount_amount" in response.context["form"].fields, discount
                )
                self.assertEqual(
                    "unit_base_price" in response.context["form"].fields, price
                )

    def test_discount_editor_is_focused_accessible_and_does_not_load_catalogue(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                self.editor_url + "?mode=discount", HTTP_HX_REQUEST="true"
            )
        self.assertContains(response, "Descuento de")
        self.assertContains(response, "Descuento (€)")
        self.assertContains(response, "autofocus")
        form = response.context["form"]
        self.assertEqual([f.name for f in form.visible_fields()], ["discount_amount"])
        self.assertContains(
            response,
            "Importe total del descuento de la línea. Máximo permitido: 20 %.",
        )
        sql = " ".join(q["sql"] for q in queries.captured_queries)
        for table in (
            '"catalog_product"',
            '"sales_salereturn"',
            '"payments_paymentmethod"',
            '"billing_billingdocument"',
        ):
            self.assertNotIn(table, sql)
        self.assertEqual(sql.count('FROM "business_config_possettings"'), 1)

    def test_permitted_discount_and_removal_update_all_amounts(self):
        response = self.discount("4")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Descuento: −4,00 €")
        self.assertContains(response, ">Editar descuento</a>")
        self.assertContains(response, "<dt>Descuento</dt>")
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertIn("nx:close-modal", response["HX-Trigger"])
        self.line.refresh_from_db()
        self.sale.refresh_from_db()
        self.assertEqual(self.line.discount_amount, Decimal("4.00"))
        self.assertEqual(self.line.tax_amount, Decimal("3.36"))
        self.assertEqual(self.line.line_total, Decimal("19.36"))
        self.assertEqual(self.sale.subtotal_amount, Decimal("20.00"))
        self.assertEqual(self.sale.discount_amount, Decimal("4.00"))
        self.assertEqual(self.sale.tax_amount, Decimal("3.36"))
        self.assertEqual(self.sale.total_amount, Decimal("19.36"))
        self.assertEqual(self.sale.pending_amount, Decimal("19.36"))
        response = self.discount("0.00")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Descuento:")
        self.assertNotContains(response, "<dt>Descuento</dt>")
        self.line.refresh_from_db()
        self.assertEqual(self.line.discount_amount, Decimal("0.00"))

    def test_negative_above_gross_and_above_maximum_discounts_are_rejected(self):
        for value in ("-1", "21", "5"):
            with self.subTest(value=value):
                response = self.discount(value)
                self.assertEqual(response.status_code, 422)
                self.assertContains(
                    response, 'id="id_discount_amount-errors"', status_code=422
                )
                self.assertContains(response, 'aria-invalid="true"', status_code=422)
                self.assertNotIn("HX-Trigger", response)
                self.line.refresh_from_db()
                self.assertEqual(self.line.discount_amount, Decimal("0.00"))
                with self.assertRaises(ValidationError):
                    self.update(discount_amount=Decimal(value))

    def test_disabled_discounts_reject_tampered_post_and_service(self):
        self.settings.allow_manual_discounts = False
        self.settings.max_manual_discount_percent = Decimal("0")
        self.settings.save()
        for suffix in ("", "?mode=discount"):
            response = self.client.post(
                self.editor_url + suffix,
                {"quantity": "2", "discount_amount": "1"},
                HTTP_HX_REQUEST="true",
            )
            self.assertContains(
                response, "no permite descuentos manuales", status_code=422
            )
        with self.assertRaisesMessage(
            ValidationError, "no permite descuentos manuales"
        ):
            self.update(discount_amount=Decimal("1"))
        self.line.refresh_from_db()
        self.assertEqual(self.line.discount_amount, Decimal("0"))

    def test_quantity_preserves_total_discount_and_rejects_new_invalid_percentage(self):
        self.update(discount_amount=Decimal("4"))
        response = self.quantity("1")
        self.assertContains(response, "máximo permitido", status_code=422)
        self.assertContains(response, 'value="2"', status_code=422)
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, Decimal("2"))
        self.assertEqual(self.line.discount_amount, Decimal("4"))
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.total_amount, Decimal("19.36"))
        self.assertEqual(self.quantity("3").status_code, 200)
        self.line.refresh_from_db()
        self.assertEqual(self.line.discount_amount, Decimal("4"))
        self.assertEqual(self.line.line_total, Decimal("31.46"))

    def test_modes_preserve_other_fields_and_use_same_service(self):
        response = self.client.post(
            self.editor_url + "?mode=discount",
            {"quantity": "99", "unit_base_price": "100", "discount_amount": "2"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, Decimal("2"))
        self.assertEqual(self.line.unit_base_price, Decimal("10"))
        response = self.client.post(
            self.editor_url + "?mode=price",
            {"unit_base_price": "12", "discount_amount": "0"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.line.refresh_from_db()
        self.assertEqual(self.line.discount_amount, Decimal("2"))

    def test_update_form_validates_discount_at_limit(self):
        form = SaleLineUpdateForm(
            {"discount_amount": "4"},
            business=self.business,
            store=self.store,
            sale=self.sale,
            line=self.line,
            user=self.user,
            mode="discount",
        )
        self.assertTrue(form.is_valid(), form.errors)

    @patch(
        "apps.sales.views.update_sale_line",
        side_effect=ValidationError("Cambio rechazado."),
    )
    def test_service_error_returns_422_without_changing_cart(self, _update):
        self.assertContains(self.quantity("3"), "Cambio rechazado.", status_code=422)
        self.assertContains(self.discount("2"), "Cambio rechazado.", status_code=422)
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, Decimal("2"))
        self.assertEqual(self.line.discount_amount, Decimal("0"))

    def test_store_business_and_sale_isolation_for_both_endpoints(self):
        other_business = create_sales_business()
        other_store = create_sales_store(business=other_business)
        wrong_store = create_sales_store(business=self.business)
        another_sale = open_sale(
            business=self.business, store=self.store, opened_by=self.user
        )
        for route in ("sale_line_update", "sale_line_quantity_update"):
            for store, sale, status in (
                (other_store, self.sale, 403),
                (wrong_store, self.sale, 404),
                (self.store, another_sale, 404),
            ):
                with self.subTest(route=route, store=store, sale=sale):
                    response = self.client.post(
                        self.url(route, store=store, sale=sale),
                        {"quantity": "5", "discount_amount": "1"},
                        HTTP_HX_REQUEST="true",
                    )
                    self.assertEqual(response.status_code, status)
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, Decimal("2"))
