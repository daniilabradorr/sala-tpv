"""Real-template coverage for independent customer/document draft choices."""

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.sales.forms import SaleHeaderUpdateForm
from apps.sales.models import Sale
from apps.sales.services import open_sale, update_sale_header
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sales_business,
    create_sales_customer,
    create_sales_store,
    create_sales_user,
)


class HeaderAutosaveTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        create_pos_settings(business=self.business, require_open_cash_register=False)
        self.customer = create_sales_customer(business=self.business, name="Ana")
        self.foreign = create_sales_customer(business=create_sales_business())
        self.inactive = create_sales_customer(business=self.business, is_active=False)
        self.sale = open_sale(
            business=self.business, store=self.store, opened_by=self.user
        )
        self.url = reverse(
            "sales:sale_header_update", args=[self.store.pk, self.sale.pk]
        )
        self.client.force_login(self.user)

    def form(self, data=None):
        return SaleHeaderUpdateForm(
            data, business=self.business, store=self.store, sale=self.sale
        )

    def test_form_has_only_two_fields_and_scoped_nullable_customer(self):
        form = self.form()
        self.assertEqual(set(form.fields), {"customer", "document_type_requested"})
        self.assertEqual(form.fields["customer"].empty_label, "Sin cliente")
        self.assertFalse(form.fields["customer"].required)
        self.assertEqual(
            [value for value, _label in form.fields["document_type_requested"].choices],
            ["ticket", "invoice"],
        )
        self.assertEqual(list(form.fields["customer"].queryset), [self.customer])
        for customer in (self.foreign, self.inactive):
            with self.subTest(customer=customer):
                form = self.form(
                    {"customer": customer.pk, "document_type_requested": "ticket"}
                )
                self.assertFalse(form.is_valid())
                self.assertIn("customer", form.errors)
                with self.assertRaises(ValidationError):
                    update_sale_header(
                        business=self.business,
                        sale=self.sale,
                        customer=customer,
                        document_type_requested="ticket",
                        updated_by=self.user,
                    )

    def test_all_four_draft_states_are_independent_and_header_only(self):
        count = self.business.customers.count()
        for customer, document in (
            (None, "ticket"),
            (self.customer, "ticket"),
            (self.customer, "invoice"),
            (None, "invoice"),
            (self.customer, "invoice"),
            (self.customer, "ticket"),
        ):
            with self.subTest(customer=customer, document=document):
                data = {
                    "customer": customer.pk if customer else "",
                    "document_type_requested": document,
                }
                self.assertTrue(self.form(data).is_valid())
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.post(self.url, data, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(
                    response, "sales/partials/_workspace_header.html"
                )
                self.assertContains(response, 'id="workspace-header"')
                self.assertNotContains(response, "<!DOCTYPE")
                for region in (
                    'id="product-grid"',
                    'id="sale-cart"',
                    'id="checkout-panel"',
                ):
                    self.assertNotContains(response, region)
                self.assertNotIn("HX-Trigger", response)
                sql = " ".join(q["sql"] for q in queries.captured_queries)
                for table in (
                    '"sales_saleline"',
                    '"sales_salereturn"',
                    '"catalog_product"',
                    '"billing_billingdocument"',
                    '"payments_paymentmethod"',
                ):
                    self.assertNotIn(table, sql)
                self.sale.refresh_from_db()
                self.assertEqual(self.sale.customer, customer)
                self.assertEqual(self.sale.document_type_requested, document)
        self.assertEqual(self.business.customers.count(), count)

    def test_header_has_autosave_semantics_and_noscript_fallback(self):
        response = self.client.post(
            self.url,
            {"customer": "", "document_type_requested": "invoice"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, 'hx-trigger="change, submit"')
        self.assertContains(response, 'hx-sync=".tpv:queue last"')
        self.assertContains(response, 'hx-target="#workspace-header"')
        self.assertContains(response, "<legend>Documento</legend>")
        self.assertContains(response, '<label for="id_customer">Cliente</label>')
        self.assertContains(response, 'role="status"')
        self.assertContains(response, "Puedes seguir añadiendo productos.")
        self.assertNotContains(response, 'role="alert"')
        self.assertNotContains(response, "customer_mode")
        self.assertNotContains(response, "Mostrador")
        self.assertNotContains(response, "<legend>Tipo</legend>")
        html = response.content.decode()
        before, rest = html.split("<noscript>")
        fallback, after = rest.split("</noscript>")
        self.assertIn("Guardar", fallback)
        self.assertNotIn("Guardar", before + after)
        response = self.client.post(
            self.url,
            {"customer": self.customer.pk, "document_type_requested": "ticket"},
        )
        self.assertRedirects(
            response, reverse("sales:sale_detail", args=[self.store.pk, self.sale.pk])
        )

    def test_invalid_changes_render_authoritative_controls_and_422_errors(self):
        update_sale_header(
            business=self.business,
            sale=self.sale,
            customer=self.customer,
            document_type_requested="invoice",
            updated_by=self.user,
        )
        for data in (
            {"customer": self.foreign.pk, "document_type_requested": "ticket"},
            {"customer": self.inactive.pk, "document_type_requested": "ticket"},
            {"customer": "", "document_type_requested": "invalid"},
        ):
            with self.subTest(data=data):
                response = self.client.post(self.url, data, HTTP_HX_REQUEST="true")
                self.assertContains(response, 'role="alert"', status_code=422)
                self.assertTemplateUsed(
                    response, "sales/partials/_workspace_header.html"
                )
                self.assertEqual(
                    response.context["header_form"]["customer"].value(),
                    self.customer.pk,
                )
                self.assertEqual(
                    response.context["header_form"]["document_type_requested"].value(),
                    "invoice",
                )
                self.sale.refresh_from_db()
                self.assertEqual(self.sale.customer, self.customer)
                self.assertEqual(self.sale.document_type_requested, "invoice")

    @patch(
        "apps.sales.views.update_sale_header",
        side_effect=ValidationError("Cambio rechazado."),
    )
    def test_service_error_also_restores_authoritative_header(self, _update):
        response = self.client.post(
            self.url,
            {"customer": self.customer.pk, "document_type_requested": "invoice"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "Cambio rechazado.", status_code=422)
        self.assertIsNone(response.context["header_form"]["customer"].value())
        self.assertEqual(
            response.context["header_form"]["document_type_requested"].value(), "ticket"
        )

    def test_quick_customer_preserves_both_document_types_and_existing_sale(self):
        url = reverse("sales:quick_customer_create", args=[self.store.pk, self.sale.pk])
        for document in ("ticket", "invoice"):
            with self.subTest(document=document):
                update_sale_header(
                    business=self.business,
                    sale=self.sale,
                    customer=None,
                    document_type_requested=document,
                    updated_by=self.user,
                )
                response = self.client.post(
                    url,
                    {
                        "name": f"Nuevo {document}",
                        "customer_type": "person",
                        "country_code": "ES",
                    },
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["HX-Retarget"], "#workspace-header")
                self.assertEqual(response["HX-Reswap"], "outerHTML")
                self.sale.refresh_from_db()
                self.assertEqual(self.sale.customer.name, f"Nuevo {document}")
                self.assertEqual(self.sale.document_type_requested, document)
                self.assertEqual(Sale.objects.count(), 1)

    def test_header_and_quick_customer_enforce_store_and_business_isolation(self):
        for store in (
            create_sales_store(business=self.business),
            create_sales_store(business=self.foreign.business),
        ):
            for route in ("sale_header_update", "quick_customer_create"):
                with self.subTest(store=store, route=route):
                    response = self.client.post(
                        reverse(f"sales:{route}", args=[store.pk, self.sale.pk]),
                        {},
                        HTTP_HX_REQUEST="true",
                    )
                    self.assertEqual(
                        response.status_code,
                        404 if store.business_id == self.business.pk else 403,
                    )
