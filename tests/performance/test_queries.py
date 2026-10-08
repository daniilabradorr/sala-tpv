"""Structural regressions measured first on PostgreSQL 16; no timing gates."""

from django.db import connection
from django.template.loader import render_to_string
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tests.performance.dataset import Dataset
from apps.sales.selectors import get_sale_cart


class TPVQueryGrowthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset(50, label="query-regression")

    def setUp(self):
        self.client.force_login(self.dataset.user)
        # Establish the session's active store outside the warm query gates.
        # The first request's session write is retained in the JSON baseline.
        sale, _ = self.dataset.sale()
        self.assertEqual(self.measure("sale_detail", sale)[0].status_code, 200)

    def measure(self, endpoint, sale, *, line=None, data=None):
        args = [self.dataset.store.pk, sale.pk]
        if line:
            args.append(line.pk)
        path = reverse(f"sales:{endpoint}", args=args)
        with CaptureQueriesContext(connection) as queries:
            response = (
                self.client.get(path, HTTP_HX_REQUEST="true")
                if data is None
                else self.client.post(path, data, HTTP_HX_REQUEST="true")
            )
        self.assertEqual(response.status_code, 200)
        return response, queries.captured_queries

    def test_paged_grid_queries_do_not_grow_with_catalog(self):
        sale, _ = self.dataset.sale(5)
        counts = []
        for size in (50, 250, 1000):
            self.dataset.grow_catalog(size)
            response, queries = self.measure("sale_detail", sale)
            self.assertTemplateUsed(response, "sales/partials/_product_grid.html")
            self.assertEqual(response.content.count(b'class="product-card"'), 24)
            self.assertLessEqual(len(queries), 13)
            counts.append(len(queries))
        self.assertEqual(len(set(counts)), 1, counts)

    def test_profiler_handles_a_full_django_query_buffer(self):
        from tests.performance.baseline import measure

        sale, _ = self.dataset.sale(5)
        path = reverse("sales:sale_detail", args=[self.dataset.store.pk, sale.pk])
        connection.queries_log.extend(
            {"sql": "SELECT 0", "time": "0.000"}
            for _ in range(connection.queries_log.maxlen)
        )
        result = measure(self.client, ("GET", path, {}, True))
        self.assertEqual(result["queries"]["count"], 13)
        self.assertEqual(result["queries"]["unique_exact"], 13)

    def test_cart_selector_and_render_remain_two_queries_through_fifty_lines(self):
        for size in (1, 5, 20, 50):
            sale, _ = self.dataset.sale(size)
            with CaptureQueriesContext(connection) as queries:
                current = get_sale_cart(
                    business=self.dataset.business, store=self.dataset.store, pk=sale.pk
                )
                html = render_to_string(
                    "sales/partials/_cart_content.html",
                    {
                        "store": self.dataset.store,
                        "sale": current,
                        "lines": current.lines.all(),
                        "pos_settings": self.dataset.settings,
                    },
                )
            self.assertEqual(len(queries), 2)
            self.assertEqual(html.count('<article class="cart-line">'), size)

    def test_header_autosave_does_not_load_cart_or_catalog(self):
        sale, _ = self.dataset.sale(20)
        response, queries = self.measure(
            "sale_header_update",
            sale,
            data={
                "customer": self.dataset.customers[0].pk,
                "document_type_requested": "invoice",
            },
        )
        self.assertTemplateUsed(response, "sales/partials/_workspace_header.html")
        self.assertLessEqual(len(queries), 40)
        for query in queries:
            self.assertNotIn('"catalog_product"', query["sql"])
            self.assertNotIn('"sales_saleline"', query["sql"])
        sale.refresh_from_db()
        self.assertEqual(sale.customer_id, self.dataset.customers[0].pk)
        self.assertEqual(sale.document_type_requested, "invoice")

    def test_quantity_queries_do_not_grow_with_whole_catalog(self):
        counts = []
        for size in (50, 1000):
            self.dataset.grow_catalog(size)
            sale, lines = self.dataset.sale(5)
            response, queries = self.measure(
                "sale_line_quantity_update",
                sale,
                line=lines[0],
                data={"quantity": "1.5"},
            )
            self.assertTemplateUsed(response, "sales/partials/_cart_content.html")
            self.assertLessEqual(len(queries), 66)
            counts.append(len(queries))
            lines[0].refresh_from_db()
            self.assertEqual(str(lines[0].quantity), "1.500")
            # A lookup for the edited product is expected; an unbounded catalogue
            # evaluation or product pagination must not occur on this path.
            for query in queries:
                if 'FROM "catalog_product"' in query["sql"]:
                    self.assertIn('"catalog_product"."id" =', query["sql"])
        self.assertEqual(counts[0], counts[1])

    def test_checkout_get_queries_do_not_grow_with_lines(self):
        counts = []
        for size in (1, 20):
            sale, _ = self.dataset.sale(size)
            response, queries = self.measure("sale_checkout", sale)
            self.assertTemplateUsed(response, "sales/partials/_checkout.html")
            self.assertContains(response, "data-checkout")
            self.assertLessEqual(len(queries), 18)
            counts.append(len(queries))
        self.assertEqual(counts[0], counts[1])
