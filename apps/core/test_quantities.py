from decimal import Decimal

from django.template import Context, Template
from django.test import SimpleTestCase
from django.utils.translation import override

from apps.core.quantities import quantity, quantity_input


class QuantityPresentationTests(SimpleTestCase):
    def test_exact_html_and_localized_formats(self):
        with override("es"):
            for source, html, human in (
                ("1.000", "1", "1"),
                ("2.000", "2", "2"),
                ("1.500", "1.5", "1,5"),
                ("0.750", "0.75", "0,75"),
                ("0.125", "0.125", "0,125"),
                ("0.001", "0.001", "0,001"),
                ("99999999999.999", "99999999999.999", "99999999999,999"),
                ("100.000", "100", "100"),
                ("-0.000", "0", "0"),
            ):
                with self.subTest(source=source):
                    amount = Decimal(source)
                    self.assertEqual(quantity_input(amount), html)
                    self.assertEqual(quantity(amount), human)
                    self.assertEqual(
                        Template(
                            "{% load quantities %}{{ q|quantity_input }} / {{ q|quantity }}"
                        ).render(Context({"q": amount})),
                        f"{html} / {human}",
                    )

    def test_invalid_or_nonfinite_values_are_empty(self):
        for value in (None, "invalid", Decimal("NaN"), Decimal("Infinity")):
            self.assertEqual(quantity_input(value), "")

    def test_billing_filter_uses_shared_format(self):
        with override("es"):
            self.assertEqual(
                Template("{% load billing_print %}{{ q|quantity }}").render(
                    Context({"q": Decimal("0.001")})
                ),
                "0,001",
            )
