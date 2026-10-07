from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from django.utils.formats import number_format

from apps.billing.models import BillingDocument, BillingDocumentTypeChoices
from apps.billing.selectors import billing_document_detail
from apps.billing.tests_forms import BillingFormsFixture
from apps.business_config.models import BusinessProfile
from apps.sales.models import RequestedDocumentTypeChoices
from apps.sales.tests.factories import (
    create_sale_line,
    create_sales_store,
    create_sales_user,
    create_store_access,
)
from apps.users.models import RoleChoices


class BillingDocumentPrintTests(BillingFormsFixture):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def print_url(self, document, store=None):
        return reverse(
            "billing:document_print",
            kwargs={
                "store_id": (store or self.store).pk,
                "document_pk": document.pk,
            },
        )

    def ticket(self):
        return self.issued_original(self.sale(), BillingDocumentTypeChoices.F2)

    def test_issued_ticket_renders_snapshots_lines_taxes_and_total(self):
        document = self.ticket()
        response = self.client.get(self.print_url(document))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "billing/document_print.html")
        for value in (
            "FACTURA SIMPLIFICADA",
            document.issuer_legal_name,
            document.issuer_tax_identifier,
            document.issuer_address_line_1,
            document.full_number,
            document.series_text,
            str(document.number),
            document.lines.get().product_name,
            document.tax_breakdowns.get().tax_type,
            number_format(document.total_amount, decimal_pos=2) + " €",
            number_format(
                document.tax_breakdowns.get().taxable_base_amount, decimal_pos=2
            )
            + " €",
            document.operation_date.strftime("%d/%m/%Y"),
        ):
            self.assertContains(response, value)
        self.assertContains(response, 'class="document-print document-print--F2"')
        self.assertNotContains(response, 'id="recipient-title"')

    def test_f1_shows_persisted_recipient(self):
        document = self.issued_original(
            self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer), "F1"
        )
        response = self.client.get(self.print_url(document))
        self.assertContains(response, "<h1>FACTURA</h1>", html=True)
        self.assertContains(response, document.recipient_legal_name)
        self.assertContains(response, document.recipient_tax_identifier)
        self.assertContains(response, document.recipient_address_line_1)
        self.assertContains(response, 'class="document-print document-print--F1"')

    def test_anonymous_redirects_to_login(self):
        document = self.ticket()
        self.client.logout()
        response = self.client.get(self.print_url(document))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response.url)

    def test_store_access_is_required_and_granted_access_works(self):
        document = self.ticket()
        cashier = create_sales_user(business=self.business, role=RoleChoices.CASHIER)
        self.client.force_login(cashier)
        self.assertEqual(self.client.get(self.print_url(document)).status_code, 403)
        create_store_access(business=self.business, user=cashier, store=self.store)
        self.assertEqual(self.client.get(self.print_url(document)).status_code, 200)

    def test_cross_tenant_document_under_own_store_is_404(self):
        document = self.ticket()
        foreign_store = create_sales_store(business=self.other_business)
        foreign_user = create_sales_user(business=self.other_business)
        self.client.force_login(foreign_user)
        self.assertEqual(
            self.client.get(self.print_url(document, foreign_store)).status_code, 404
        )
        self.assertEqual(self.client.get(self.print_url(document)).status_code, 403)

    def test_wrong_store_and_missing_document_are_404(self):
        document = self.ticket()
        self.assertEqual(
            self.client.get(self.print_url(document, self.other_store)).status_code, 404
        )
        url = reverse(
            "billing:document_print",
            kwargs={"store_id": self.store.pk, "document_pk": document.pk + 1000},
        )
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_draft_is_not_printable_or_linked(self):
        draft = BillingDocument.objects.create(
            business=self.business,
            store=self.store,
            series=self.series("F2"),
            document_type="F2",
        )
        self.assertEqual(self.client.get(self.print_url(draft)).status_code, 404)
        response = self.client.get(
            reverse(
                "billing:document_detail",
                kwargs={"store_id": self.store.pk, "document_pk": draft.pk},
            )
        )
        self.assertNotContains(response, "Vista de impresión")

    def test_read_only_endpoint_rejects_mutating_methods(self):
        document = self.ticket()
        before = BillingDocument.objects.count()
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertEqual(
                    getattr(self.client, method)(self.print_url(document)).status_code,
                    405,
                )
        self.assertEqual(BillingDocument.objects.count(), before)

    def test_zero_discount_has_no_visual_discount_row(self):
        response = self.client.get(self.print_url(self.ticket()))
        self.assertNotContains(response, 'class="document-print-discount"')
        self.assertNotContains(response, "-0,00")
        self.assertNotContains(response, "−0,00")

    def test_positive_discount_renders_persisted_amount(self):
        sale = self.sale()
        create_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            unit_base_price=Decimal("10.00"),
            discount_amount=Decimal("2.00"),
        )
        document = self.issued_original(sale, "F2")
        response = self.client.get(self.print_url(document))
        self.assertContains(response, 'class="document-print-discount"')
        self.assertContains(response, "−2,00 €")
        self.assertContains(response, "2,00 €")

    def test_current_fiscal_data_never_replaces_document_snapshots(self):
        document = self.issued_original(
            self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer), "F1"
        )
        line = document.lines.get()
        BusinessProfile.objects.filter(business=self.business).update(
            legal_name="Nuevo emisor fiscal",
            tax_identifier="B99999999",
            address_line_1="Nueva dirección fiscal",
            brand_name="Marca actual",
            receipt_footer="Gracias por su visita",
        )
        type(self.customer).objects.filter(pk=self.customer.pk).update(
            legal_name="Nuevo cliente fiscal", tax_identifier="B00000000"
        )
        type(self.product).objects.filter(pk=self.product.pk).update(
            name="Nuevo producto comercial"
        )
        response = self.client.get(self.print_url(document))
        for value in (
            document.issuer_legal_name,
            document.issuer_tax_identifier,
            document.issuer_address_line_1,
            document.recipient_legal_name,
            document.recipient_tax_identifier,
            line.product_name,
            "Marca actual",
            "Gracias por su visita",
        ):
            self.assertContains(response, value)
        for value in (
            "Nuevo emisor fiscal",
            "B99999999",
            "Nueva dirección fiscal",
            "Nuevo cliente fiscal",
            "B00000000",
            "Nuevo producto comercial",
        ):
            self.assertNotContains(response, value)

    def test_branding_escapes_text_and_rejects_unsafe_logo_urls(self):
        document = self.ticket()
        for url in (
            "javascript:alert(1)",
            "data:image/svg+xml,unsafe",
            "//evil.test/logo",
        ):
            with self.subTest(url=url):
                BusinessProfile.objects.filter(business=self.business).update(
                    logo_url=url, receipt_footer="<script>alert(1)</script>"
                )
                response = self.client.get(self.print_url(document))
                self.assertNotContains(response, 'class="document-print-logo"')
                self.assertContains(response, "&lt;script&gt;")
                self.assertNotContains(response, "<script>")

    def test_managed_logo_takes_precedence_over_legacy_url(self):
        document = self.ticket()
        BusinessProfile.objects.filter(business=self.business).update(
            logo="business/logo/master.webp", logo_url="https://legacy.test/logo.png"
        )
        with patch(
            "django.core.files.storage.FileSystemStorage.url",
            return_value="/media/business/logo/master.webp",
        ):
            response = self.client.get(self.print_url(document))
        self.assertContains(response, 'src="/media/business/logo/master.webp"')
        self.assertNotContains(response, "legacy.test")

    def test_legacy_logo_and_trade_name_are_optional_branding(self):
        document = self.ticket()
        BusinessProfile.objects.filter(business=self.business).update(
            trade_name="Comercio local", logo_url="https://example.test/logo.png"
        )
        response = self.client.get(self.print_url(document))
        self.assertContains(response, "Comercio local")
        self.assertContains(response, 'src="https://example.test/logo.png"')
        self.assertContains(response, 'referrerpolicy="no-referrer"')

    def test_missing_profile_does_not_prevent_printing_issued_document(self):
        document = self.ticket()
        BusinessProfile.objects.filter(business=self.business).delete()
        response = self.client.get(self.print_url(document))
        self.assertContains(response, document.issuer_legal_name)
        self.assertNotContains(response, 'class="document-print-logo"')

    def test_no_shell_fake_qr_or_print_execution(self):
        response = self.client.get(self.print_url(self.ticket()))
        for value in (
            "app-sidebar",
            "app-topbar",
            "window.print",
            "<script",
            "QR",
            "VeriFactu",
            "AEAT",
            "<canvas",
        ):
            self.assertNotContains(response, value)
        self.assertContains(response, "Volver al documento")

    def test_detail_links_to_print_view(self):
        document = self.ticket()
        response = self.client.get(
            reverse(
                "billing:document_detail",
                kwargs={"store_id": self.store.pk, "document_pk": document.pk},
            )
        )
        self.assertContains(response, f'href="{self.print_url(document)}"')
        self.assertContains(response, "Vista de impresión")

    def test_selector_prefetches_lines_and_tax_breakdowns(self):
        sale = self.sale()
        for _ in range(5):
            create_sale_line(business=self.business, sale=sale, product=self.product)
        document = self.issued_original(sale, "F2")
        selected = billing_document_detail(
            business=self.business, document_id=document.pk
        )
        with self.assertNumQueries(0):
            self.assertEqual(len(list(selected.lines.all())), 6)
            self.assertEqual(len(list(selected.tax_breakdowns.all())), 1)
