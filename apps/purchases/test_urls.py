from django.test import SimpleTestCase
from django.urls import resolve, reverse

from apps.purchases import views


class PurchaseURLTests(SimpleTestCase):
    cases = (
        ("purchase_list", {}, views.PurchaseListView),
        ("purchase_create", {}, views.PurchaseCreateView),
        ("purchase_detail", {"pk": 7}, views.PurchaseDetailView),
        ("purchase_update", {"pk": 7}, views.PurchaseUpdateView),
        ("purchase_order", {"pk": 7}, views.PurchaseOrderView),
        ("purchase_cancel", {"pk": 7}, views.PurchaseCancelView),
        ("purchase_receive", {"pk": 7}, views.PurchaseReceiptCreateView),
        ("purchase_line_create", {"purchase_pk": 7}, views.PurchaseLineCreateView),
        (
            "purchase_line_update",
            {"purchase_pk": 7, "line_pk": 9},
            views.PurchaseLineUpdateView,
        ),
        (
            "purchase_line_delete",
            {"purchase_pk": 7, "line_pk": 9},
            views.PurchaseLineDeleteView,
        ),
        ("supplier_list", {}, views.SupplierListView),
        ("supplier_create", {}, views.SupplierCreateView),
        ("supplier_update", {"pk": 4}, views.SupplierUpdateView),
    )

    def test_all_purchase_routes_reverse_and_resolve(self):
        for name, kwargs, view_class in self.cases:
            with self.subTest(name=name):
                match = resolve(reverse(f"purchases:{name}", kwargs=kwargs))
                self.assertEqual(match.func.view_class, view_class)

    def test_mutating_actions_are_post_only(self):
        for view_class in (
            views.PurchaseOrderView,
            views.PurchaseCancelView,
            views.PurchaseLineDeleteView,
        ):
            self.assertEqual(view_class.http_method_names, ["post"])
