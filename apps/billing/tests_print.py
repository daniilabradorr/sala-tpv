from decimal import Decimal
import uuid
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils.formats import number_format
from django.utils.translation import override

from apps.billing.models import (
    BillingDocument,
    BillingDocumentTypeChoices,
    BillingTaxBreakdown,
)
from apps.billing.selectors import billing_document_detail
from apps.billing.services import (
    issue_sale_return_rectification,
    substitute_simplified_document,
)
from apps.billing.templatetags.billing_print import quantity
from apps.billing.tests_forms import BillingFormsFixture
from apps.business_config.models import BusinessProfile
from apps.cash_register.models import CashSession
from apps.cash_register.test_factories import create_cash_register
from apps.payments.models import Payment, PaymentMethod
from apps.payments.services import register_sale_payment
from apps.sales.models import Sale
from apps.sales.models import RequestedDocumentTypeChoices
from apps.sales.tests.factories import (
    create_sale_line,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
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
        self.assertNotContains(response, "IMPRIMIR")

    def _assert_repeated_print_gets_are_read_only(self, query=""):
        document = self.ticket()
        method = PaymentMethod.objects.create(
            business=self.business, name="Tarjeta", code="card"
        )
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        register_sale_payment(
            business=self.business,
            sale_id=document.sale_id,
            method_id=method.pk,
            amount=document.total_amount,
            user=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session_id=session.pk,
        )
        models = (Sale, Payment, BillingDocument)
        before = tuple(model.objects.count() for model in models)
        for attempt in range(3):
            with self.subTest(attempt=attempt, query=query):
                response = self.client.get(self.print_url(document) + query)
                self.assertContains(response, document.full_number)
                self.assertEqual(
                    tuple(model.objects.count() for model in models), before
                )

    def test_multiple_print_gets_do_not_change_sale_payment_or_document_counts(self):
        self._assert_repeated_print_gets_are_read_only()

    def test_multiple_autoprint_gets_do_not_change_sale_payment_or_document_counts(
        self,
    ):
        self._assert_repeated_print_gets_are_read_only("?autoprint=1")

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

    def test_no_shell_or_fake_qr_and_print_uses_external_script(self):
        response = self.client.get(self.print_url(self.ticket()))
        for value in (
            "app-sidebar",
            "app-topbar",
            "window.print",
            "QR",
            "VeriFactu",
            "AEAT",
            "<canvas",
        ):
            self.assertNotContains(response, value)
        self.assertContains(response, "Volver al documento")
        self.assertContains(response, "data-print-document")
        self.assertContains(response, static("js/pages/billing-print.js"))
        self.assertNotContains(response, "onclick=")

    def test_detail_links_to_print_view(self):
        document = self.ticket()
        response = self.client.get(
            reverse(
                "billing:document_detail",
                kwargs={"store_id": self.store.pk, "document_pk": document.pk},
            )
        )
        self.assertContains(
            response,
            f'<a class="button button-secondary" href="{self.print_url(document)}?autoprint=1" '
            'target="_blank" rel="noopener" hx-boost="false">IMPRIMIR</a>',
            html=True,
        )
        self.assertNotContains(response, "Vista de impresión")

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

    def test_f2_uses_receipt_blocks_without_invoice_tables(self):
        response = self.client.get(self.print_url(self.ticket()))
        self.assertTemplateUsed(response, "billing/print/_f2_receipt.html")
        self.assertTemplateNotUsed(response, "billing/print/_f1_invoice.html")
        self.assertContains(response, 'class="document-print-receipt-lines"')
        self.assertNotContains(response, "<table")
        self.assertNotContains(response, "document-print--F1")
        self.assertContains(response, "€ base")

    def test_f1_uses_invoice_table_and_all_recipient_snapshots(self):
        # Populate customer data before issuance; presentation reads its snapshot.
        type(self.customer).objects.filter(pk=self.customer.pk).update(
            address_line_1="Calle Cliente Histórico 42",
            postal_code="37002",
            city="Ciudad histórica",
            province="Provincia histórica",
        )
        document = self.issued_original(
            self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer), "F1"
        )
        response = self.client.get(self.print_url(document))
        self.assertTemplateUsed(response, "billing/print/_f1_invoice.html")
        self.assertTemplateNotUsed(response, "billing/print/_f2_receipt.html")
        self.assertNotContains(response, "document-print--F2")
        self.assertNotContains(response, "document-print-receipt-lines")
        for field in (
            "recipient_legal_name",
            "recipient_tax_identifier",
            "recipient_address_line_1",
            "recipient_postal_code",
            "recipient_city",
            "recipient_province",
            "recipient_country_code",
            "issuer_legal_name",
            "issuer_tax_identifier",
            "issuer_address_line_1",
        ):
            self.assertContains(response, getattr(document, field))
        self.assertContains(response, document.lines.get().product_name)
        self.assertContains(response, "TOTAL")
        self.assertContains(response, 'scope="col"')
        self.assertNotContains(response, document.lines.get().sku)

    def test_quantity_rendering_keeps_persisted_decimal_and_units(self):
        for kind in ("F1", "F2"):
            for amount, displayed in (
                ("1.000", "1"),
                ("1.500", "1,5"),
                ("0.750", "0,75"),
            ):
                with self.subTest(kind=kind, amount=amount):
                    sale = self.sale(
                        RequestedDocumentTypeChoices.INVOICE
                        if kind == "F1"
                        else RequestedDocumentTypeChoices.TICKET,
                        self.customer if kind == "F1" else None,
                    )
                    sale.lines.all().delete()
                    create_sale_line(
                        business=self.business,
                        sale=sale,
                        product=self.product,
                        quantity=Decimal(amount),
                    )
                    document = self.issued_original(sale, kind)
                    response = self.client.get(self.print_url(document))
                    self.assertContains(
                        response,
                        f'<span class="document-print-quantity">{displayed}</span>',
                        html=True,
                    )
                    self.assertEqual(document.lines.get().quantity, Decimal(amount))
                    self.assertContains(response, document.lines.get().unit)

    def test_both_layouts_escape_long_product_names(self):
        name = 'Producto <especial> & "artesano" ' + "X" * 140
        type(self.product).objects.filter(pk=self.product.pk).update(name=name)
        self.product.refresh_from_db()
        for kind in ("F1", "F2"):
            with self.subTest(kind=kind):
                document = self.issued_original(
                    self.sale(
                        RequestedDocumentTypeChoices.INVOICE
                        if kind == "F1"
                        else RequestedDocumentTypeChoices.TICKET,
                        self.customer if kind == "F1" else None,
                    ),
                    kind,
                )
                response = self.client.get(self.print_url(document))
                self.assertContains(
                    response, "&lt;especial&gt; &amp; &quot;artesano&quot;"
                )
                self.assertNotContains(response, "<especial>")
                self.assertContains(response, "X" * 140)

    def test_f1_discounts_hide_zero_and_show_positive_snapshot(self):
        sale = self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer)
        document = self.issued_original(sale, "F1")
        response = self.client.get(self.print_url(document))
        self.assertNotContains(response, 'class="document-print-discount"')
        self.assertContains(response, "<td>—</td>", html=True)
        sale = self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer)
        create_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            discount_amount=Decimal("2.00"),
        )
        document = self.issued_original(sale, "F1")
        response = self.client.get(self.print_url(document))
        self.assertContains(response, 'class="document-print-discount"')
        self.assertContains(response, "−2,00 €", count=2)
        self.assertNotContains(response, "−0,00")

    def test_f2_line_discount_only_appears_when_positive(self):
        sale = self.sale()
        create_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            discount_amount=Decimal("2.00"),
        )
        response = self.client.get(self.print_url(self.issued_original(sale, "F2")))
        self.assertContains(response, 'class="document-print-line-discount"', count=1)
        self.assertContains(response, "−2,00 €", count=2)

    def test_both_layouts_render_multiple_taxes_and_fiscal_classification(self):
        tax = create_sales_tax(
            business=self.business,
            rate=Decimal("10.00"),
            has_equivalence_surcharge=True,
            equivalence_surcharge_rate=Decimal("1.40"),
        )
        product = create_sales_product(business=self.business, tax=tax)
        for kind in ("F1", "F2"):
            with self.subTest(kind=kind):
                sale = self.sale(
                    RequestedDocumentTypeChoices.INVOICE
                    if kind == "F1"
                    else RequestedDocumentTypeChoices.TICKET,
                    self.customer if kind == "F1" else None,
                )
                create_sale_line(business=self.business, sale=sale, product=product)
                document = self.issued_original(sale, kind)
                self.assertEqual(document.tax_breakdowns.count(), 2)
                response = self.client.get(self.print_url(document))
                self.assertContains(response, "Desglose fiscal")
                self.assertContains(response, "21 %")
                self.assertContains(response, "10 %")
                for item in document.tax_breakdowns.all():
                    self.assertContains(response, f"Régimen: {item.clave_regimen}")
                    self.assertContains(
                        response, f"Calificación: {item.calificacion_operacion}"
                    )
                    self.assertContains(
                        response,
                        number_format(item.taxable_base_amount, decimal_pos=2) + " €",
                    )
                    self.assertContains(
                        response, number_format(item.tax_amount, decimal_pos=2) + " €"
                    )

    def test_f1_has_no_fake_fiscal_region_or_controls_inside_main(self):
        document = self.issued_original(
            self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer), "F1"
        )
        response = self.client.get(self.print_url(document))
        for text in ("QR", "VERI*FACTU", "VeriFactu", "<canvas", "<iframe"):
            self.assertNotContains(response, text)
        main = response.content.decode().split("<main", 1)[1].split("</main>", 1)[0]
        self.assertNotIn("data-print-document", main)
        self.assertNotIn("Volver al documento", main)

    def test_both_layouts_render_prefetched_snapshots_without_queries(self):
        profile = BusinessProfile.objects.get(business=self.business)
        for kind in ("F1", "F2"):
            sale = self.sale(
                RequestedDocumentTypeChoices.INVOICE
                if kind == "F1"
                else RequestedDocumentTypeChoices.TICKET,
                self.customer if kind == "F1" else None,
            )
            for _ in range(8):
                create_sale_line(
                    business=self.business, sale=sale, product=self.product
                )
            document = self.issued_original(sale, kind)
            selected = billing_document_detail(
                business=self.business, document_id=document.pk
            )
            with self.subTest(kind=kind), self.assertNumQueries(0):
                rendered = render_to_string(
                    "billing/document_print.html",
                    {
                        "document": selected,
                        "store": self.store,
                        "business_profile": profile,
                        "print_logo_url": "",
                    },
                )
            self.assertIn(document.full_number, rendered)

    def test_f3_and_return_rectification_keep_legacy_layout_and_title(self):
        sale = self.sale()
        self.issued_original(sale, "F2")
        f3 = substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=self.customer,
            series_id=self.series("F3").pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        invoice_sale = self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer)
        self.issued_original(invoice_sale, "F1")
        sale_return = self.completed_return(invoice_sale)
        rectification = issue_sale_return_rectification(
            business=self.business,
            sale_return_id=sale_return.pk,
            series_id=self.series("R1").pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        for document in (f3, rectification):
            with self.subTest(kind=document.document_type):
                response = self.client.get(self.print_url(document))
                self.assertTemplateUsed(response, "billing/print/_legacy_document.html")
                self.assertTemplateNotUsed(response, "billing/print/_f1_invoice.html")
                self.assertTemplateNotUsed(response, "billing/print/_f2_receipt.html")
                self.assertContains(
                    response,
                    f"<h1>{document.get_document_type_display().upper()}</h1>",
                    html=True,
                )
                self.assertContains(response, document.full_number)
                self.assertContains(response, document.lines.get().product_name)


class BillingPrintQuantityTests(SimpleTestCase):
    def test_tax_partial_preserves_special_snapshot_fields(self):
        # The issuing service currently rejects these cases. Exercise display
        # of the snapshot shape without broadening supported fiscal operations.
        tax = BillingTaxBreakdown(
            tax_type="IVA",
            tax_rate=Decimal("0.00"),
            operacion_exenta="E1",
            clave_regimen="02",
            calificacion_operacion="N1",
            has_equivalence_surcharge=True,
            equivalence_surcharge_rate=Decimal("1.40"),
            taxable_base_amount=Decimal("10.00"),
            tax_amount=Decimal("0.00"),
        )
        with override("es"):
            for compact in (True, False):
                with self.subTest(compact=compact):
                    rendered = render_to_string(
                        "billing/print/_tax_breakdown.html",
                        {
                            "document": {"tax_breakdowns": {"all": [tax]}},
                            "compact": compact,
                        },
                    )
                    for text in (
                        "Exenta: E1",
                        "Régimen: 02",
                        "Calificación: N1",
                        "Recargo 1,4 %",
                        "10,00 €",
                        "0,00 €",
                    ):
                        self.assertIn(text, rendered)

    def test_spanish_quantities_are_exact_and_have_no_redundant_zeros(self):
        with override("es"):
            for value, expected in (
                ("1.000", "1"),
                ("2.000", "2"),
                ("2.500", "2,5"),
                ("1.500", "1,5"),
                ("0.750", "0,75"),
                ("0.000", "0"),
                ("-0.000", "0"),
                ("-1.500", "-1,5"),
                ("12345678901.123", "12345678901,123"),
                ("1E+3", "1000"),
                ("0.00000000000000000001", "0,00000000000000000001"),
            ):
                with self.subTest(value=value):
                    amount = Decimal(value)
                    self.assertEqual(quantity(amount), expected)
                    self.assertEqual(amount, Decimal(value))

    def test_quantity_uses_active_locale(self):
        with override("en"):
            self.assertEqual(quantity(Decimal("2.500")), "2.5")

    def test_invalid_or_nonfinite_quantity_is_empty(self):
        for value in (None, "", "invalid", Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(value=value):
                self.assertEqual(quantity(value), "")

    def test_print_css_defines_roll_a4_and_pagination_strategy(self):
        css = (
            Path(settings.BASE_DIR) / "static/css/pages/billing-print.css"
        ).read_text()
        for rule in (
            "@page billing-receipt { size: auto; margin: 3mm; }",
            "@page billing-invoice { size: A4 portrait; margin: 14mm; }",
            "width: 80mm",
            "width: 74mm",
            "page: billing-receipt",
            "page: billing-invoice",
            "display: table-header-group",
            "break-inside: avoid",
            "overflow-wrap: anywhere",
            ".document-print-controls, .document-print [data-print-document] { display: none; }",
        ):
            self.assertIn(rule, css)
