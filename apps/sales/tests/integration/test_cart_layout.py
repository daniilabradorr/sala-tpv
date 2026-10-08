"""Real ticket structure and bounded rendering with many snapshot lines."""

from decimal import Decimal
from xml.etree import ElementTree

from django.db import connection
from django.template.loader import render_to_string
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.sales.forms import SaleLineQuantityUpdateForm
from apps.sales.selectors import get_sale_cart
from apps.sales.services import open_sale
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sale_line,
    create_sales_business,
    create_sales_product,
    create_sales_store,
    create_sales_user,
)


class CartLayoutTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.settings = create_pos_settings(business=self.business)
        self.sale = open_sale(
            business=self.business, store=self.store, opened_by=self.user
        )
        self.product = create_sales_product(business=self.business, track_stock=False)

    def render_cart(self, *, form=None):
        sale = get_sale_cart(business=self.business, store=self.store, pk=self.sale.pk)
        return render_to_string(
            "sales/partials/_cart_content.html",
            {
                "sale": sale,
                "store": self.store,
                "lines": sale.lines.all(),
                "cart_form": form,
                "pos_settings": self.settings,
            },
        )

    def tree(self, html):
        # Django's HTML parser handles void inputs without requiring XML syntax.
        from django.test.html import parse_html

        def convert(node):
            if isinstance(node, str):
                return None
            el = ElementTree.Element(node.name, dict(node.attributes))
            for child in node.children:
                converted = convert(child)
                if converted is not None:
                    el.append(converted)
            return el

        return convert(parse_html(html))

    def test_header_lines_errors_and_footer_are_separate(self):
        create_sale_line(business=self.business, sale=self.sale, product=self.product)
        form = SaleLineQuantityUpdateForm({"quantity": "0"})
        self.assertFalse(form.is_valid())
        root = self.tree(self.render_cart(form=form))
        self.assertEqual(root.attrib["id"], "sale-cart-content")
        self.assertEqual(root.attrib["data-sale-id"], str(self.sale.pk))
        self.assertEqual([el.tag for el in root], ["header", "div", "footer"])
        heading, region, footer = root
        self.assertIsNotNone(heading.find(".//*[@id='cart-title']"))
        self.assertIn("data-cart-scroll-region", region.attrib)
        self.assertEqual(region.attrib["aria-label"], "Productos del ticket")
        self.assertIsNotNone(region.find(".//*[@role='alert']"))
        self.assertIsNotNone(region.find(".//article"))
        self.assertIsNone(region.find(".//dl"))
        self.assertIsNone(region.find(".//*[@data-checkout-open]"))
        self.assertIsNotNone(footer.find("dl"))
        self.assertIsNotNone(footer.find(".//*[@data-checkout-open]"))
        self.assertIsNotNone(footer.find(".//*[@class='cancel-sale']"))
        self.assertIsNone(footer.find(".//article"))

    def test_empty_ticket_keeps_message_and_disabled_checkout_in_footer(self):
        html = self.render_cart()
        root = self.tree(html)
        self.assertIn("Añade un producto para comenzar.", html)
        self.assertIsNotNone(root.find("./div/div/p"))
        self.assertIn("disabled", root.find("./footer/div/button").attrib)
        self.assertIsNone(root.find(".//*[@data-checkout-open]"))

    def test_discount_row_remains_conditional_in_footer(self):
        line = create_sale_line(
            business=self.business, sale=self.sale, product=self.product
        )
        from apps.sales.services import update_sale_line

        for discount in (Decimal("0"), Decimal("1")):
            with self.subTest(discount=discount):
                update_sale_line(
                    business=self.business,
                    sale=self.sale,
                    line=line,
                    user=self.user,
                    quantity=line.quantity,
                    discount_amount=discount,
                )
                html = self.render_cart()
                self.assertEqual("<dt>Descuento</dt>" in html, discount > 0)

    def test_twenty_line_cart_has_constant_query_count(self):
        def measured():
            with CaptureQueriesContext(connection) as queries:
                html = self.render_cart()
            return len(queries), html

        create_sale_line(business=self.business, sale=self.sale, product=self.product)
        short_queries, _ = measured()
        for index in range(19):
            product = create_sales_product(
                business=self.business, name=f"Ticket {index}", track_stock=False
            )
            create_sale_line(business=self.business, sale=self.sale, product=product)
        long_queries, html = measured()
        self.assertEqual(short_queries, long_queries)
        self.assertEqual(long_queries, 2)
        self.assertEqual(html.count('<article class="cart-line">'), 20)
