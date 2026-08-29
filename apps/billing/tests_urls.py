from django.test import SimpleTestCase
from django.urls import resolve, reverse

from apps.billing import views


class BillingURLTests(SimpleTestCase):
    def test_document_list_url(self):
        url = reverse("billing:document_list", kwargs={"store_id": 7})
        self.assertEqual(url, "/billing/stores/7/documents/")
        self.assertIs(resolve(url).func.view_class, views.BillingDocumentListView)

    def test_document_detail_url(self):
        url = reverse(
            "billing:document_detail",
            kwargs={"store_id": 7, "document_pk": 11},
        )
        self.assertEqual(url, "/billing/stores/7/documents/11/")
        self.assertIs(resolve(url).func.view_class, views.BillingDocumentDetailView)

    def test_issue_sale_document_url(self):
        url = reverse(
            "billing:issue_sale_document", kwargs={"store_id": 7, "sale_pk": 13}
        )
        self.assertEqual(url, "/billing/stores/7/sales/13/issue/")
        self.assertIs(resolve(url).func.view_class, views.IssueSaleDocumentView)

    def test_substitute_simplified_document_url(self):
        url = reverse(
            "billing:substitute_simplified_document",
            kwargs={"store_id": 7, "sale_pk": 13},
        )
        self.assertEqual(url, "/billing/stores/7/sales/13/substitute/")
        self.assertIs(
            resolve(url).func.view_class, views.SubstituteSimplifiedDocumentView
        )

    def test_issue_sale_return_rectification_url(self):
        url = reverse(
            "billing:issue_sale_return_rectification",
            kwargs={"store_id": 7, "return_pk": 17},
        )
        self.assertEqual(url, "/billing/stores/7/returns/17/rectify/")
        self.assertIs(
            resolve(url).func.view_class, views.IssueSaleReturnRectificationView
        )
