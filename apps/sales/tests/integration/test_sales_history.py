"""Regression coverage for the FE-09 sales history contract."""

from datetime import timedelta
from decimal import Decimal
import uuid

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import (
    BillingDocument,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingSeries,
)
from apps.cash_register.models import CashRegister, CashSession
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices as TransactionStatusChoices,
    PaymentTypeChoices,
)
from apps.sales.models import (
    PaymentStatusChoices,
    RequestedDocumentTypeChoices,
    Sale,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_business,
    create_sales_customer,
    create_sales_store,
    create_sales_product,
    create_sales_tax,
    create_sales_user,
    create_store_access,
)
from apps.users.models import RoleChoices


class SalesHistoryTests(TestCase):
    password = "testpass123"

    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business, name="Centro")
        self.owner = create_sales_user(
            business=self.business, password=self.password, email="owner@history.test"
        )
        self.customer = create_sales_customer(
            business=self.business, name="Cliente Histórico"
        )
        self.cash_register = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja histórico",
            code="HISTORY",
        )
        self.cash_session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.cash_register,
            opened_by=self.owner,
        )
        self.url = reverse("sales:sale_list", kwargs={"store_id": self.store.pk})
        self.client.login(email=self.owner.email, password=self.password)

    def make_sale(self, **kwargs):
        return create_sale(
            business=self.business, store=self.store, opened_by=self.owner, **kwargs
        )

    def move_sale(self, sale, days):
        created_at = timezone.now() - timedelta(days=days)
        Sale.objects.filter(pk=sale.pk).update(created_at=created_at)
        return sale

    def detail_url(self, sale, store=None):
        return reverse(
            "sales:sale_detail",
            kwargs={"store_id": (store or self.store).pk, "sale_pk": sale.pk},
        )

    def make_product_sale(self, *, quantity=Decimal("2.000")):
        tax = create_sales_tax(business=self.business, rate=Decimal("21.00"))
        product = create_sales_product(
            business=self.business,
            tax=tax,
            name="Producto original",
            base_price=Decimal("10.00"),
        )
        sale = self.make_sale(status=SaleStatusChoices.COMPLETED)
        line = create_sale_line(
            business=self.business,
            sale=sale,
            product=product,
            quantity=quantity,
            unit_base_price=Decimal("10.00"),
            tax_rate=Decimal("21.00"),
        )
        return sale, line, product

    def make_issued_document(self, *, sale, business=None, store=None, number=1):
        business = business or self.business
        store = store or self.store
        series = BillingSeries.objects.create(
            business=business,
            store=store,
            name=f"Serie {number}",
            document_type=BillingDocumentTypeChoices.F2,
            prefix=f"F2-{number}",
            year=timezone.localdate().year,
        )
        return BillingDocument.objects.create(
            business=business,
            store=store,
            sale=sale,
            series=series,
            issued_by=sale.opened_by,
            series_text="F2/2026",
            number=number,
            document_type=BillingDocumentTypeChoices.F2,
            status=BillingDocumentStatusChoices.ISSUED,
            issued_at=timezone.now(),
            operation_date=timezone.localdate(),
            idempotency_key=uuid.uuid4(),
            idempotency_fingerprint="a" * 64,
            description="Venta histórica",
            issuer_legal_name="Negocio histórico",
            issuer_tax_identifier="B12345678",
            issuer_address_line_1="Calle Uno",
            issuer_postal_code="37001",
            issuer_city="Salamanca",
            issuer_province="Salamanca",
            issuer_country_code="ES",
            subtotal_amount=sale.subtotal_amount,
            discount_amount=sale.discount_amount,
            tax_amount=sale.tax_amount,
            total_amount=sale.total_amount,
        )

    def test_default_invalid_and_explicit_quick_periods(self):
        today = self.make_sale()
        eight_days_old = self.move_sale(self.make_sale(), 8)

        for params in ({}, {"period": "today"}, {"period": "invalid"}):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertContains(response, f"#{today.pk}")
                self.assertNotContains(response, f"#{eight_days_old.pk}")

        response = self.client.get(self.url, {"period": "30d"})
        self.assertContains(response, f"#{eight_days_old.pk}")
        response = self.client.get(self.url, {"period": "7d"})
        self.assertNotContains(response, f"#{eight_days_old.pk}")

    def test_filters_compose_with_period_and_manual_dates(self):
        completed = self.make_sale(
            customer=self.customer,
            status="completed",
            payment_status=PaymentStatusChoices.PAID,
            document_type_requested=RequestedDocumentTypeChoices.INVOICE,
        )
        self.make_sale()
        response = self.client.get(
            self.url,
            {
                "period": "7d",
                "status": "completed",
                "payment_status": PaymentStatusChoices.PAID,
                "document_type_requested": RequestedDocumentTypeChoices.INVOICE,
                "opened_by": self.owner.pk,
                "customer": self.customer.pk,
                "query": str(completed.pk),
            },
        )
        self.assertEqual(list(response.context["sales"]), [completed])
        self.assertContains(response, 'name="period" value="7d"')
        self.assertContains(response, "status=completed")

        today = timezone.localdate().isoformat()
        response = self.client.get(
            self.url, {"period": "7d", "date_from": today, "date_to": today}
        )
        self.assertContains(response, 'name="period" value="custom"')
        self.assertContains(response, "Personalizado")

    def test_invalid_date_range_is_visible_and_returns_no_sales_for_htmx(self):
        self.make_sale()
        response = self.client.get(
            self.url,
            {"date_from": "2026-09-20", "date_to": "2026-09-10"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertContains(response, "La fecha inicial no puede ser posterior")
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'id="sales-history-content"', count=1)
        self.assertContains(response, 'name="period" value="custom"')
        self.assertContains(response, "Personalizado")
        self.assertNotContains(response, "<html")

    def test_htmx_history_restore_returns_full_page(self):
        self.make_sale()

        full = self.client.get(self.url, {"period": "7d"})
        self.assertTemplateUsed(full, "sales/sale_list.html")
        self.assertContains(full, 'class="sales-history"')
        self.assertContains(full, "data-app-shell")

        partial = self.client.get(
            self.url,
            {"period": "7d"},
            HTTP_HX_REQUEST="true",
        )
        self.assertTemplateUsed(partial, "sales/partials/_sale_history_content.html")
        self.assertNotContains(partial, 'class="sales-history"')
        self.assertNotContains(partial, "data-app-shell")

        restored = self.client.get(
            self.url,
            {"period": "7d", "status": "completed"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_HISTORY_RESTORE_REQUEST="true",
        )
        self.assertTemplateUsed(restored, "sales/sale_list.html")
        self.assertContains(restored, 'class="sales-history"')
        self.assertContains(restored, "data-app-shell")
        self.assertContains(restored, 'id="sales-history-content"', count=1)

        for response in (full, partial, restored):
            vary = {
                value.strip().lower()
                for value in response.headers.get("Vary", "").split(",")
            }
            self.assertIn("hx-request", vary)
            self.assertIn("hx-history-restore-request", vary)

    def test_pagination_has_progressive_links_and_preserves_filters(self):
        for _ in range(27):
            self.make_sale(status="completed")
        params = {"period": "7d", "status": "completed", "query": "Centro"}
        first = self.client.get(self.url, params)
        self.assertEqual(len(first.context["sales"]), 25)
        self.assertContains(
            first, 'href="?period=7d&amp;status=completed&amp;query=Centro&amp;page=2"'
        )
        self.assertContains(first, 'hx-swap="outerHTML"')
        second = self.client.get(self.url, {**params, "page": 2})
        self.assertEqual(len(second.context["sales"]), 2)

    def test_quick_period_url_preserves_filters_and_removes_dates_and_page(self):
        response = self.client.get(
            self.url,
            {
                "period": "custom",
                "status": "completed",
                "date_from": "2026-09-01",
                "date_to": "2026-09-20",
                "page": 2,
            },
        )
        seven_days = next(
            item for item in response.context["quick_periods"] if item["value"] == "7d"
        )
        self.assertIn("period=7d", seven_days["url"])
        self.assertIn("status=completed", seven_days["url"])
        self.assertNotIn("date_", seven_days["url"])
        self.assertNotIn("page=", seven_days["url"])

    def test_read_only_cashier_can_view_but_not_mutate_closed_sale(self):
        cashier = create_sales_user(
            business=self.business,
            role=RoleChoices.CASHIER,
            password=self.password,
            email="readonly@history.test",
        )
        create_store_access(
            business=self.business, user=cashier, store=self.store, can_sell=False
        )
        sale = self.make_sale(status="completed", total_amount=Decimal("10.00"))
        self.client.login(email=cashier.email, password=self.password)
        response = self.client.get(
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        for action in (
            "Emitir documento fiscal",
            "Emitir F3 sustitutiva",
            "Registrar cobro",
            "Pasar pendiente a cuenta",
            "Crear devolución",
        ):
            self.assertNotContains(response, action)

    def test_historical_detail_uses_sale_line_snapshots(self):
        sale, _line, product = self.make_product_sale()
        product.name = "Producto cambiado"
        product.base_price = Decimal("99.00")
        product.save()

        response = self.client.get(self.detail_url(sale))
        self.assertContains(response, "Producto original")
        self.assertContains(response, "10,00 €")
        self.assertContains(response, "21,00%")
        self.assertNotContains(response, "Producto cambiado")
        self.assertNotContains(response, "99,00 €")

    def test_historical_detail_shows_charges_and_refunds(self):
        sale, line, _product = self.make_product_sale()
        method = PaymentMethod.objects.create(
            business=self.business, name="Tarjeta histórica", code="card"
        )
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.owner,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("5.00"),
        )
        create_sale_return_line(
            business=self.business,
            return_doc=returned,
            original_line=line,
            quantity=Decimal("0.500"),
            amount=Decimal("5.00"),
        )
        for payment_type, amount, sale_return in (
            (PaymentTypeChoices.SALE_PAYMENT, Decimal("24.20"), None),
            (PaymentTypeChoices.REFUND, Decimal("5.00"), returned),
        ):
            Payment.objects.create(
                business=self.business,
                store=self.store,
                sale=sale,
                sale_return=sale_return,
                method=method,
                cash_session=self.cash_session,
                payment_type=payment_type,
                amount=amount,
                status=TransactionStatusChoices.COMPLETED,
                processed_by=self.owner,
                idempotency_key=uuid.uuid4(),
            )

        response = self.client.get(self.detail_url(sale))
        self.assertContains(response, "Tarjeta histórica", count=2)
        self.assertContains(response, "Cobro")
        self.assertContains(response, "Reembolso")
        self.assertContains(response, "−5,00 €")
        self.assertContains(response, str(self.owner))

    def test_billing_documents_are_scoped_and_formatted(self):
        sale, _line, _product = self.make_product_sale()
        response = self.client.get(self.detail_url(sale))
        self.assertContains(response, "No hay ningún documento fiscal emitido.")

        own_document = self.make_issued_document(sale=sale, number=7)
        other_sale = self.make_sale(status=SaleStatusChoices.COMPLETED)
        other_document = self.make_issued_document(sale=other_sale, number=8)
        other_business = create_sales_business(name="Otro negocio")
        other_store = create_sales_store(business=other_business)
        other_user = create_sales_user(business=other_business)
        foreign_sale = create_sale(
            business=other_business,
            store=other_store,
            opened_by=other_user,
            status=SaleStatusChoices.COMPLETED,
        )
        foreign_document = self.make_issued_document(
            sale=foreign_sale,
            business=other_business,
            store=other_store,
            number=9,
        )

        response = self.client.get(self.detail_url(sale))
        self.assertContains(response, "Factura simplificada")
        self.assertContains(response, "F2/2026 / 000007")
        self.assertContains(
            response,
            reverse(
                "billing:document_detail",
                kwargs={"store_id": self.store.pk, "document_pk": own_document.pk},
            ),
        )
        self.assertNotContains(response, f"00000{other_document.number}")
        self.assertNotContains(response, f"00000{foreign_document.number}")

    def test_return_action_tracks_remaining_returnable_quantity(self):
        sale, line, _product = self.make_product_sale(quantity=Decimal("2.000"))
        response = self.client.get(self.detail_url(sale))
        self.assertContains(response, "Crear devolución")

        partial = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.owner,
            status=SaleReturnStatusChoices.COMPLETED,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=partial,
            original_line=line,
            quantity=Decimal("1.000"),
        )
        response = self.client.get(self.detail_url(sale))
        self.assertContains(response, f"Devolución #{partial.pk}")
        self.assertContains(response, "Crear devolución")

        full = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.owner,
            status=SaleReturnStatusChoices.COMPLETED,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=full,
            original_line=line,
            quantity=Decimal("1.000"),
        )
        response = self.client.get(self.detail_url(sale))
        self.assertNotContains(response, "Crear devolución")

    def test_store_and_tenant_isolation(self):
        store_a2 = create_sales_store(business=self.business, name="Sucursal")
        sale_a1 = self.make_sale(status=SaleStatusChoices.COMPLETED)
        sale_a2 = create_sale(
            business=self.business,
            store=store_a2,
            opened_by=self.owner,
            status=SaleStatusChoices.COMPLETED,
        )
        business_b = create_sales_business(name="Negocio B")
        store_b = create_sales_store(business=business_b)
        owner_b = create_sales_user(business=business_b)
        sale_b = create_sale(
            business=business_b,
            store=store_b,
            opened_by=owner_b,
            status=SaleStatusChoices.COMPLETED,
        )
        response = self.client.get(self.url)
        self.assertContains(response, f"#{sale_a1.pk}")
        self.assertNotContains(response, f"#{sale_a2.pk}")
        self.assertNotContains(response, f"#{sale_b.pk}")
        self.assertEqual(self.client.get(self.detail_url(sale_a2)).status_code, 404)
        self.assertEqual(self.client.get(self.detail_url(sale_b)).status_code, 404)

        cashier = create_sales_user(
            business=self.business, role=RoleChoices.CASHIER, password=self.password
        )
        create_store_access(
            business=self.business, user=cashier, store=self.store, can_sell=False
        )
        self.client.login(email=cashier.email, password=self.password)
        manipulated = self.client.get(self.detail_url(sale_a2, store=store_a2))
        self.assertIn(manipulated.status_code, {403, 404})

    def test_list_query_count_does_not_grow_per_row(self):
        self.make_sale()
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url)
        for _ in range(30):
            self.make_sale()
        with CaptureQueriesContext(connection) as full_page:
            self.client.get(self.url)
        self.assertLessEqual(len(full_page), len(small) + 2)

    def test_detail_query_count_is_bounded_for_related_history(self):
        sale, line, product = self.make_product_sale()
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.detail_url(sale))

        method = PaymentMethod.objects.create(
            business=self.business, name="Método consultas", code="bizum"
        )
        for index in range(5):
            create_sale_line(
                business=self.business,
                sale=sale,
                product=product,
                quantity=Decimal("1.000"),
            )
            Payment.objects.create(
                business=self.business,
                store=self.store,
                sale=sale,
                method=method,
                cash_session=self.cash_session,
                amount=Decimal("1.00"),
                status=TransactionStatusChoices.COMPLETED,
                processed_by=self.owner,
                idempotency_key=uuid.uuid4(),
            )
        for _ in range(3):
            return_doc = create_sale_return(
                business=self.business,
                store=self.store,
                original_sale=sale,
                created_by=self.owner,
            )
            create_sale_return_line(
                business=self.business,
                return_doc=return_doc,
                original_line=line,
                quantity=Decimal("0.100"),
            )

        with CaptureQueriesContext(connection) as populated:
            self.client.get(self.detail_url(sale))
        self.assertLessEqual(len(populated), len(small) + 3)
