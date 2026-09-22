"""Regression coverage for the FE-09 sales history contract."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.sales.models import PaymentStatusChoices, RequestedDocumentTypeChoices, Sale
from apps.sales.tests.factories import (
    create_sale,
    create_sales_business,
    create_sales_customer,
    create_sales_store,
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
        self.assertNotContains(response, "<html")

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
