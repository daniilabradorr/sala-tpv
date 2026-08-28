import uuid
from unittest.mock import patch

from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.billing.models import (
    BillingDocument,
    BillingDocumentRelationTypeChoices,
    BillingDocumentTypeChoices,
)
from apps.billing.services import issue_sale_document
from apps.billing.tests_forms import BillingFormsFixture
from apps.sales.models import RequestedDocumentTypeChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sales_store,
    create_sales_user,
)


class BillingHTTPTests(BillingFormsFixture):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def list_url(self, store=None):
        return reverse(
            "billing:document_list", kwargs={"store_id": (store or self.store).pk}
        )

    def detail_url(self, document, store=None):
        return reverse(
            "billing:document_detail",
            kwargs={
                "store_id": (store or self.store).pk,
                "document_pk": document.pk,
            },
        )

    def issue_url(self, sale, store=None):
        return reverse(
            "billing:issue_sale_document",
            kwargs={
                "store_id": (store or self.store).pk,
                "sale_pk": sale.pk,
            },
        )

    def substitute_url(self, sale):
        return reverse(
            "billing:substitute_simplified_document",
            kwargs={
                "store_id": self.store.pk,
                "sale_pk": sale.pk,
            },
        )

    def rectify_url(self, return_doc, store=None):
        return reverse(
            "billing:issue_sale_return_rectification",
            kwargs={
                "store_id": (store or self.store).pk,
                "return_pk": return_doc.pk,
            },
        )

    def test_list_is_tenant_and_store_scoped_and_filters(self):
        self.customer.name = "Cliente Empresa A"
        self.customer.save()
        self.other_customer.name = "Cliente Empresa B"
        self.other_customer.save()
        sale = self.sale(customer=self.customer)
        own = self.issued_original(sale, BillingDocumentTypeChoices.F2)
        other_store_sale = self.sale(store=self.other_store)
        other_store_doc = issue_sale_document(
            business=self.business,
            sale_id=other_store_sale.pk,
            series_id=self.series("F2", store=self.other_store).pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        response = self.client.get(
            self.list_url(),
            {
                "customer": self.customer.pk,
                "document_type": "F2",
                "status": "issued",
                "date_from": own.operation_date,
                "date_to": own.operation_date,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(
            response.context["documents"], [own], transform=lambda x: x
        )
        self.assertNotIn(other_store_doc, response.context["documents"])
        self.assertNotIn(
            self.other_customer,
            response.context["form"].fields["customer"].queryset,
        )
        self.assertNotContains(response, self.other_customer.name)

    def test_invalid_list_filter_keeps_safe_scope(self):
        own = self.issued_original(self.sale(), BillingDocumentTypeChoices.F2)
        response = self.client.get(
            self.list_url(), {"date_from": "2026-02-02", "date_to": "2026-01-01"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertContains(response, str(own))

    def test_business_and_store_access_are_enforced(self):
        foreign_store = create_sales_store(business=self.other_business)
        self.assertEqual(self.client.get(self.list_url(foreign_store)).status_code, 403)

    def test_detail_is_read_only_and_rejects_wrong_store(self):
        document = self.issued_original(self.sale(), BillingDocumentTypeChoices.F2)
        count = BillingDocument.objects.count()
        response = self.client.get(self.detail_url(document))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, document.issuer_legal_name)
        self.assertEqual(
            response.context["document"].total_amount, document.total_amount
        )
        self.assertEqual(BillingDocument.objects.count(), count)
        self.assertEqual(
            self.client.get(self.detail_url(document, self.other_store)).status_code,
            404,
        )

    def test_detail_rejects_cross_tenant_document(self):
        other_store = create_sales_store(business=self.other_business)
        document = self.issued_original(self.sale(), BillingDocumentTypeChoices.F2)
        self.assertEqual(
            self.client.get(self.detail_url(document, other_store)).status_code, 403
        )

    def test_issue_get_has_hidden_uuid_and_no_side_effect(self):
        sale = self.sale()
        self.series("F2")
        before = BillingDocument.objects.count()
        response = self.client.get(self.issue_url(sale))
        self.assertEqual(response.status_code, 200)
        field = response.context["form"].fields["idempotency_key"]
        self.assertIsInstance(field.widget, forms.HiddenInput)
        uuid.UUID(str(response.context["form"].initial["idempotency_key"]))
        self.assertEqual(BillingDocument.objects.count(), before)

    def test_issue_f1_and_f2_use_prg(self):
        for requested, kind, customer in [
            (RequestedDocumentTypeChoices.TICKET, "F2", None),
            (RequestedDocumentTypeChoices.INVOICE, "F1", self.customer),
        ]:
            with self.subTest(kind=kind):
                sale = self.sale(requested, customer)
                series = self.series(kind)
                response = self.client.post(
                    self.issue_url(sale),
                    {
                        "series": series.pk,
                        "idempotency_key": uuid.uuid4(),
                    },
                )
                document = BillingDocument.objects.get(sale=sale, document_type=kind)
                self.assertRedirects(
                    response, self.detail_url(document), fetch_redirect_response=False
                )
                self.assertEqual(self.client.get(response.url).status_code, 200)
                count = BillingDocument.objects.count()
                self.client.get(response.url)
                self.assertEqual(BillingDocument.objects.count(), count)

    def test_invalid_post_preserves_key(self):
        sale = self.sale()
        key = (
            self.client.get(self.issue_url(sale))
            .context["form"]
            .initial["idempotency_key"]
        )
        response = self.client.post(self.issue_url(sale), {"idempotency_key": key})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["idempotency_key"].value(), str(key))
        self.assertFalse(BillingDocument.objects.filter(sale=sale).exists())

    def test_same_http_intention_is_idempotent_and_ignores_extra_fields(self):
        sale, series, key = self.sale(), self.series("F2"), uuid.uuid4()
        data = {
            "series": series.pk,
            "idempotency_key": key,
            "business_id": self.other_business.pk,
            "sale_id": 999999,
            "document_type": "R5",
            "total": "0.01",
            "tax": "0",
            "status": "draft",
        }
        first = self.client.post(self.issue_url(sale), data)
        second = self.client.post(self.issue_url(sale), data)
        document = BillingDocument.objects.get(sale=sale)
        self.assertEqual(first.url, self.detail_url(document))
        self.assertEqual(second.url, self.detail_url(document))
        self.assertEqual(BillingDocument.objects.filter(sale=sale).count(), 1)
        self.assertEqual(document.document_type, BillingDocumentTypeChoices.F2)
        self.assertEqual(document.business, self.business)

    def test_sale_and_store_url_tampering_is_rejected(self):
        sale = self.sale()
        self.assertEqual(
            self.client.get(self.issue_url(sale, self.other_store)).status_code, 404
        )
        foreign_user = create_sales_user(business=self.other_business)
        foreign_store = create_sales_store(business=self.other_business)
        foreign_sale = create_sale(
            business=self.other_business,
            store=foreign_store,
            opened_by=foreign_user,
        )
        self.assertEqual(
            self.client.get(self.issue_url(foreign_sale, foreign_store)).status_code,
            403,
        )

    def test_substitute_get_and_cross_tenant_customer_post(self):
        sale = self.sale(customer=self.customer)
        self.issued_original(sale, BillingDocumentTypeChoices.F2)
        series = self.series("F3")
        before = BillingDocument.objects.count()
        response = self.client.get(self.substitute_url(sale))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(BillingDocument.objects.count(), before)
        response = self.client.post(
            self.substitute_url(sale),
            {
                "customer": self.other_customer.pk,
                "series": series.pk,
                "idempotency_key": uuid.uuid4(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("customer", response.context["form"].errors)

    def test_substitute_happy_path_is_idempotent_prg(self):
        sale = self.sale(customer=self.customer)
        self.issued_original(sale, BillingDocumentTypeChoices.F2)
        series, key = self.series("F3"), uuid.uuid4()
        data = {
            "customer": self.customer.pk,
            "series": series.pk,
            "idempotency_key": key,
        }
        first = self.client.post(self.substitute_url(sale), data)
        second = self.client.post(self.substitute_url(sale), data)
        document = BillingDocument.objects.get(sale=sale, document_type="F3")
        self.assertEqual(first.url, self.detail_url(document))
        self.assertEqual(second.url, first.url)

    def test_rectification_get_post_and_retry(self):
        sale = self.sale()
        self.issued_original(sale, BillingDocumentTypeChoices.F2)
        return_doc = self.completed_return(sale)
        series, key = self.series("R5"), uuid.uuid4()
        before = BillingDocument.objects.count()
        self.assertEqual(self.client.get(self.rectify_url(return_doc)).status_code, 200)
        self.assertEqual(BillingDocument.objects.count(), before)
        data = {"series": series.pk, "idempotency_key": key}
        first = self.client.post(self.rectify_url(return_doc), data)
        second = self.client.post(self.rectify_url(return_doc), data)
        rectification = BillingDocument.objects.get(sale_return=return_doc)
        self.assertEqual(rectification.document_type, BillingDocumentTypeChoices.R5)
        self.assertEqual(first.url, self.detail_url(rectification))
        self.assertEqual(second.url, first.url)

    def test_r1_rectification_uses_prg(self):
        sale = self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer)
        self.issued_original(sale, BillingDocumentTypeChoices.F1)
        return_doc = self.completed_return(sale)
        response = self.client.post(
            self.rectify_url(return_doc),
            {"series": self.series("R1").pk, "idempotency_key": uuid.uuid4()},
        )
        rectification = BillingDocument.objects.get(sale_return=return_doc)
        self.assertEqual(rectification.document_type, BillingDocumentTypeChoices.R1)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.detail_url(rectification))

    def test_r5_with_historical_f3_issues_companion(self):
        sale = self.sale(customer=self.customer)
        self.issued_original(sale, BillingDocumentTypeChoices.F2)
        f3_series = self.series("F3")
        self.client.post(
            self.substitute_url(sale),
            {
                "customer": self.customer.pk,
                "series": f3_series.pk,
                "idempotency_key": uuid.uuid4(),
            },
        )
        return_doc = self.completed_return(sale)
        response = self.client.post(
            self.rectify_url(return_doc),
            {
                "series": self.series("R5").pk,
                "companion_f3_series": self.series("F3").pk,
                "idempotency_key": uuid.uuid4(),
            },
        )
        rectification = BillingDocument.objects.get(
            sale_return=return_doc,
            document_type=BillingDocumentTypeChoices.R5,
        )
        companion = BillingDocument.objects.get(
            sale_return=return_doc,
            document_type=BillingDocumentTypeChoices.F3,
        )
        self.assertEqual(response.url, self.detail_url(rectification))
        self.assertTrue(
            rectification.outgoing_relations.filter(
                relation_type=BillingDocumentRelationTypeChoices.RECTIFIES,
                target_document__document_type=BillingDocumentTypeChoices.F2,
            ).exists()
        )
        self.assertTrue(
            companion.outgoing_relations.filter(
                relation_type=BillingDocumentRelationTypeChoices.SUBSTITUTES,
                target_document=rectification,
            ).exists()
        )

    def test_sales_action_links_follow_read_only_billing_context(self):
        sale = self.sale(customer=self.customer)
        sale_url = reverse(
            "sales:sale_detail",
            kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
        )
        response = self.client.get(sale_url)
        self.assertTrue(response.context["show_issue_billing_action"])
        self.assertFalse(response.context["show_substitute_f3_action"])
        self.issued_original(sale, BillingDocumentTypeChoices.F2)
        response = self.client.get(sale_url)
        self.assertFalse(response.context["show_issue_billing_action"])
        self.assertTrue(response.context["show_substitute_f3_action"])

    def test_service_errors_map_to_field_and_non_field_errors(self):
        sale, series = self.sale(), self.series("F2")
        for error, field in [
            (ValidationError({"series": ["Serie inválida"]}), "series"),
            (ValidationError({"sale": ["Venta inválida"]}), "__all__"),
            (ValidationError("Error general"), "__all__"),
        ]:
            with (
                self.subTest(field=field),
                patch("apps.billing.views.issue_sale_document", side_effect=error),
            ):
                response = self.client.post(
                    self.issue_url(sale),
                    {
                        "series": series.pk,
                        "idempotency_key": uuid.uuid4(),
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)

    def test_unexpected_exception_is_not_hidden(self):
        sale, series = self.sale(), self.series("F2")
        with patch(
            "apps.billing.views.issue_sale_document", side_effect=RuntimeError("boom")
        ):
            with self.assertRaisesMessage(RuntimeError, "boom"):
                self.client.post(
                    self.issue_url(sale),
                    {
                        "series": series.pk,
                        "idempotency_key": uuid.uuid4(),
                    },
                )
