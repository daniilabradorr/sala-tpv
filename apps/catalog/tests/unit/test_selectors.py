from django.test import TestCase

from apps.catalog.selectors import get_category_rows
from apps.catalog.tests.factories import create_category
from apps.users.tests.factories import create_business


class CategorySelectorTests(TestCase):
    def test_hierarchy_supports_arbitrary_depth(self):
        business = create_business(name="Jerarquía", slug="jerarquia")
        root = create_category(business=business, name="Raíz", slug="raiz")
        child = create_category(
            business=business, name="Hija", slug="hija", parent=root
        )
        create_category(business=business, name="Nieta", slug="nieta", parent=child)

        self.assertEqual(
            [
                (row["category"].name, row["depth"])
                for row in get_category_rows(business)
            ],
            [("Raíz", 0), ("Hija", 1), ("Nieta", 2)],
        )

    def test_corrupt_indirect_cycle_is_returned_once_without_recursing_forever(self):
        business = create_business(name="Ciclo", slug="ciclo")
        first = create_category(business=business, name="A", slug="a")
        second = create_category(business=business, name="B", slug="b", parent=first)
        type(first).objects.filter(pk=first.pk).update(parent=second)

        rows = get_category_rows(business)

        self.assertCountEqual(
            [row["category"].pk for row in rows], [first.pk, second.pk]
        )
        self.assertEqual(len(rows), 2)

    def test_search_keeps_the_matching_category_path(self):
        business = create_business(name="Buscar", slug="buscar")
        root = create_category(business=business, name="Bebidas", slug="bebidas")
        child = create_category(
            business=business, name="Refrescos", slug="refrescos", parent=root
        )

        rows = get_category_rows(business, "refres")

        self.assertEqual(rows[0]["category"], child)
        self.assertEqual(rows[0]["path"], "Bebidas / Refrescos")
