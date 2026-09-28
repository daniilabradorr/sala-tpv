from uuid import uuid4
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.business_config.models import POSSettings
from apps.catalog.models import Product
from apps.core.models import Business
from apps.core.shell import ACTIVE_STORE_SESSION_KEY
from apps.inventory.models import InventoryItem, StockMovement
from apps.purchases.models import (
    Purchase,
    PurchaseReceipt,
    PurchaseReceiptLine,
    PurchaseStatusChoices,
    Supplier,
)
from apps.purchases.services import add_purchase_line, order_purchase
from apps.stores.models import Store
from apps.users.models import RoleChoices, UserStoreAccess
from apps.users.tests.factories import create_user


class PurchaseViewAccessTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="A", slug=f"a-{uuid4().hex}")
        self.store = Store.objects.create(business=self.business, name="A", code="A1")
        self.supplier = Supplier.objects.create(
            business=self.business, name="Proveedor"
        )
        self.owner = create_user(
            business=self.business,
            role=RoleChoices.OWNER,
            email="views-owner@test.com",
        )
        self.manager = create_user(
            business=self.business,
            role=RoleChoices.MANAGER,
            email="views-manager@test.com",
        )
        self.cashier = create_user(
            business=self.business,
            role=RoleChoices.CASHIER,
            email="views-cashier@test.com",
        )
        self.purchase = Purchase.objects.create(
            business=self.business,
            store=self.store,
            supplier=self.supplier,
            created_by=self.owner,
            reference="BASE-PURCHASE",
        )
        POSSettings.objects.create(business=self.business, enable_stock_control=True)

    def test_owner_can_open_purchase_list(self):
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("purchases:purchase_list")).status_code, 200
        )

    def test_active_store_is_explicit_and_all_stores_is_local(self):
        other_store = Store.objects.create(business=self.business, name="B", code="B2")
        Purchase.objects.create(
            business=self.business,
            store=other_store,
            supplier=self.supplier,
            created_by=self.owner,
            reference="OTHER-STORE",
        )
        Purchase.objects.bulk_create(
            [
                Purchase(
                    business=self.business,
                    store=self.store,
                    supplier=self.supplier,
                    created_by=self.owner,
                    reference=f"PAGE-{index:02d}",
                )
                for index in range(26)
            ]
        )
        session = self.client.session
        session[ACTIVE_STORE_SESSION_KEY] = self.store.pk
        session.save()
        self.client.force_login(self.owner)
        response = self.client.get(reverse("purchases:purchase_list"))
        self.assertContains(response, self.purchase.reference)
        self.assertNotContains(response, "OTHER-STORE")
        self.assertEqual(response.context["filter_form"].initial["store"], self.store)
        paged = self.client.get(f"{reverse('purchases:purchase_list')}?page=2")
        self.assertEqual(
            paged.context["filter_form"]["store"].value(), str(self.store.pk)
        )
        self.assertIn(f"store={self.store.pk}", paged.context["page_query"])
        self.assertNotContains(paged, "OTHER-STORE")
        response = self.client.get(f"{reverse('purchases:purchase_list')}?store=")
        self.assertContains(response, "OTHER-STORE")
        self.assertIn("store=&", response.context["page_query"])
        self.assertEqual(self.client.session[ACTIVE_STORE_SESSION_KEY], self.store.pk)
        scoped = self.client.get(
            f"{reverse('purchases:purchase_list')}?store={other_store.pk}"
        )
        self.assertContains(scoped, "OTHER-STORE")
        self.assertNotContains(scoped, self.purchase.reference)
        self.assertEqual(self.client.session[ACTIVE_STORE_SESSION_KEY], self.store.pk)

    def test_cashier_is_forbidden(self):
        self.client.force_login(self.cashier)
        self.assertEqual(
            self.client.get(reverse("purchases:purchase_list")).status_code, 403
        )

    def test_cross_business_supplier_and_purchase_are_not_found(self):
        other = Business.objects.create(name="B", slug=f"b-{uuid4().hex}")
        other_store = Store.objects.create(business=other, name="B", code="OTHER")
        other_supplier = Supplier.objects.create(business=other, name="Ajeno")
        other_owner = create_user(
            business=other,
            role=RoleChoices.OWNER,
            email="views-other-owner@test.com",
        )
        other_purchase = Purchase.objects.create(
            business=other,
            store=other_store,
            supplier=other_supplier,
            created_by=other_owner,
        )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(
                reverse("purchases:supplier_detail", kwargs={"pk": other_supplier.pk})
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("purchases:purchase_detail", kwargs={"pk": other_purchase.pk})
            ).status_code,
            404,
        )

    def test_manager_without_store_access_gets_404_for_detail(self):
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(
                reverse("purchases:purchase_detail", kwargs={"pk": self.purchase.pk})
            ).status_code,
            404,
        )

    def test_actions_reject_get(self):
        self.client.force_login(self.owner)
        actions = (
            ("purchase_cancel", {"pk": self.purchase.pk}),
            (
                "purchase_line_delete",
                {"purchase_pk": self.purchase.pk, "line_pk": 999},
            ),
        )
        for name, kwargs in actions:
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(
                        reverse(f"purchases:{name}", kwargs=kwargs)
                    ).status_code,
                    405,
                )

    def test_owner_creates_supplier_and_purchase_over_http_without_stock(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("purchases:supplier_create"),
            {"name": "Nuevo proveedor", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        supplier = Supplier.objects.get(name="Nuevo proveedor")
        response = self.client.post(
            reverse("purchases:purchase_create"),
            {"store": self.store.pk, "supplier": supplier.pk, "reference": "HTTP"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Purchase.objects.filter(reference="HTTP").exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_quick_supplier_invalid_is_partial_and_valid_selects_supplier(self):
        self.client.force_login(self.owner)
        url = reverse("purchases:supplier_quick_create")
        invalid = self.client.post(url, {"name": ""}, HTTP_HX_REQUEST="true")
        self.assertEqual(invalid.status_code, 422)
        self.assertTemplateUsed(invalid, "purchases/partials/_quick_supplier_form.html")
        self.assertNotContains(invalid, "<html", html=False, status_code=422)
        valid = self.client.post(
            url,
            {"name": "Proveedor rápido", "is_active": "on"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(valid.status_code, 200)
        supplier = Supplier.objects.get(name="Proveedor rápido")
        self.assertTrue(supplier.is_active)
        self.assertIn("nx:close-modal", valid.headers["HX-Trigger"])
        self.assertIn("purchases:supplier-selected", valid.headers["HX-Trigger"])

    def test_product_search_is_limited_and_tenant_scoped(self):
        product = Product.objects.create(
            business=self.business,
            name="Café buscable",
            sku="SEARCH-CAFE",
            barcode="8412345678901",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
        )
        other_business = Business.objects.create(
            name="Other search", slug=f"other-search-{uuid4().hex}"
        )
        foreign = Product.objects.create(
            business=other_business,
            name="Café ajeno",
            sku="SEARCH-CAFE-FOREIGN",
            barcode="8412345678999",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
        )
        inactive = Product.objects.create(
            business=self.business,
            name="Café inactivo",
            sku="SEARCH-CAFE-INACTIVE",
            barcode="8412345678982",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
            is_active=False,
        )
        self.client.force_login(self.owner)
        url = reverse(
            "purchases:product_search", kwargs={"purchase_pk": self.purchase.pk}
        )
        for query in ("buscable", "SEARCH-CAFE", "8412345678901"):
            with self.subTest(query=query):
                response = self.client.get(
                    url, {"product_query": query}, HTTP_HX_REQUEST="true"
                )
                self.assertContains(response, product.name)
                self.assertContains(response, f'data-product-id="{product.pk}"')
                self.assertNotContains(response, foreign.name)
                self.assertNotContains(response, inactive.name)
        line_form = self.client.get(
            reverse(
                "purchases:purchase_line_create",
                kwargs={"purchase_pk": self.purchase.pk},
            ),
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(line_form, 'hx-trigger="input changed delay:300ms, search"')

    def test_invalid_line_create_and_update_retarget_modal(self):
        product = Product.objects.create(
            business=self.business,
            name="Modal",
            sku=f"MODAL-{uuid4().hex[:6]}",
            barcode=f"4{uuid4().int % 10**12:012d}",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
        )
        self.client.force_login(self.owner)
        create_url = reverse(
            "purchases:purchase_line_create",
            kwargs={"purchase_pk": self.purchase.pk},
        )
        invalid = self.client.post(
            create_url,
            {"product": product.pk, "quantity": "", "unit_cost": ""},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertTemplateUsed(invalid, "purchases/partials/_purchase_line_form.html")
        self.assertEqual(invalid.headers["HX-Retarget"], "#purchase-line-modal-body")
        self.assertEqual(invalid.headers["HX-Reswap"], "innerHTML")
        self.assertNotContains(invalid, 'id="purchase-workspace"', status_code=422)

        line = add_purchase_line(
            business=self.business,
            purchase=self.purchase,
            product=product,
            quantity=1,
            unit_cost=1,
            user=self.owner,
        )
        update_url = reverse(
            "purchases:purchase_line_update",
            kwargs={"purchase_pk": self.purchase.pk, "line_pk": line.pk},
        )
        invalid = self.client.post(
            update_url,
            {"quantity": "", "unit_cost": "", "tax_rate": "0"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.headers["HX-Retarget"], "#purchase-line-modal-body")
        self.assertEqual(invalid.headers["HX-Reswap"], "innerHTML")

    def test_receipt_post_rejects_non_receivable_states(self):
        self.client.force_login(self.owner)
        url = reverse("purchases:purchase_receive", kwargs={"pk": self.purchase.pk})
        for status in (
            PurchaseStatusChoices.DRAFT,
            PurchaseStatusChoices.RECEIVED,
            PurchaseStatusChoices.CANCELLED,
        ):
            Purchase.objects.filter(pk=self.purchase.pk).update(
                status=status,
                ordered_at=(
                    timezone.now() if status == PurchaseStatusChoices.RECEIVED else None
                ),
            )
            self.purchase.refresh_from_db()
            with self.subTest(status=status):
                self.assertEqual(
                    self.client.post(url, {"idempotency_key": uuid4()}).status_code,
                    403,
                )

    def test_order_get_is_review_and_post_mutates(self):
        self.client.force_login(self.owner)
        url = reverse("purchases:purchase_order", kwargs={"pk": self.purchase.pk})
        review = self.client.get(url)
        self.assertEqual(review.status_code, 200)
        self.assertContains(review, "líneas comerciales quedarán fijadas")

    def test_commercial_edit_views_deny_non_draft_purchase(self):
        product = Product.objects.create(
            business=self.business,
            name="Fijado",
            sku=f"LOCKED-{uuid4().hex[:6]}",
            barcode=f"7{uuid4().int % 10**12:012d}",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
        )
        line = add_purchase_line(
            business=self.business,
            purchase=self.purchase,
            product=product,
            quantity=1,
            unit_cost=1,
            user=self.owner,
        )
        order_purchase(
            business=self.business, purchase=self.purchase, ordered_by=self.owner
        )
        self.client.force_login(self.owner)
        requests = (
            (
                "get",
                reverse("purchases:purchase_update", kwargs={"pk": self.purchase.pk}),
                {},
            ),
            (
                "post",
                reverse("purchases:purchase_update", kwargs={"pk": self.purchase.pk}),
                {},
            ),
            (
                "get",
                reverse(
                    "purchases:purchase_line_update",
                    kwargs={"purchase_pk": self.purchase.pk, "line_pk": line.pk},
                ),
                {},
            ),
            (
                "post",
                reverse(
                    "purchases:purchase_line_update",
                    kwargs={"purchase_pk": self.purchase.pk, "line_pk": line.pk},
                ),
                {"quantity": "2", "unit_cost": "1", "tax_rate": "0"},
            ),
            (
                "get",
                reverse(
                    "purchases:purchase_line_create",
                    kwargs={"purchase_pk": self.purchase.pk},
                ),
                {},
            ),
            (
                "post",
                reverse(
                    "purchases:purchase_line_delete",
                    kwargs={"purchase_pk": self.purchase.pk, "line_pk": line.pk},
                ),
                {},
            ),
        )
        for method, url, data in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, data)
                self.assertEqual(response.status_code, 403)

    def test_manager_with_access_can_open_detail(self):
        UserStoreAccess.objects.create(
            business=self.business, user=self.manager, store=self.store
        )
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(
                reverse("purchases:purchase_detail", kwargs={"pk": self.purchase.pk})
            ).status_code,
            200,
        )

    def test_add_line_and_order_over_http_are_stock_neutral(self):
        product = Product.objects.create(
            business=self.business,
            name="Producto HTTP",
            sku=f"HTTP-{uuid4().hex[:6]}",
            barcode=f"5{uuid4().int % 10**12:012d}",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
            track_stock=True,
        )
        inventory = InventoryItem.objects.create(
            business=self.business,
            store=self.store,
            product=product,
            current_stock=7,
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse(
                "purchases:purchase_line_create",
                kwargs={"purchase_pk": self.purchase.pk},
            ),
            {
                "product": product.pk,
                "quantity": "2.000",
                "unit_cost": "3.00",
                "tax_rate": "0.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        review = self.client.get(
            reverse("purchases:purchase_order", kwargs={"pk": self.purchase.pk})
        )
        self.assertEqual(review.context["progress"]["ordered"], Decimal("2"))
        self.assertContains(review, "unidades")
        response = self.client.post(
            reverse("purchases:purchase_order", kwargs={"pk": self.purchase.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.purchase.refresh_from_db()
        inventory.refresh_from_db()
        self.assertEqual(self.purchase.status, PurchaseStatusChoices.ORDERED)
        self.assertEqual(inventory.current_stock, 7)
        self.assertFalse(StockMovement.objects.exists())

    def test_invalid_list_filters_return_empty_page_without_error(self):
        self.client.force_login(self.owner)
        for query in ("store=abc", "supplier=abc"):
            response = self.client.get(f"{reverse('purchases:purchase_list')}?{query}")
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, self.purchase.reference)

    def test_http_receipt_retry_is_idempotent_and_traced(self):
        product = Product.objects.create(
            business=self.business,
            name="Stock",
            sku=f"ST-{uuid4().hex[:6]}",
            barcode=f"6{uuid4().int % 10**12:012d}",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
            track_stock=True,
        )
        line = add_purchase_line(
            business=self.business,
            purchase=self.purchase,
            product=product,
            quantity=2,
            unit_cost=3,
            user=self.owner,
        )
        order_purchase(
            business=self.business,
            purchase=self.purchase,
            ordered_by=self.owner,
        )
        key = uuid4()
        payload = {
            "idempotency_key": str(key),
            f"line_{line.pk}": "2.000",
            "notes": "Entrega 1",
        }
        self.client.force_login(self.owner)
        url = reverse("purchases:purchase_receive", kwargs={"pk": self.purchase.pk})
        review = self.client.post(url, payload)
        self.assertEqual(review.status_code, 200)
        self.assertContains(review, str(key))
        self.assertContains(review, "data-nx-critical-form")
        self.assertContains(review, 'hx-post="')
        edit = self.client.post(url, {**payload, "step": "edit"})
        self.assertEqual(edit.status_code, 200)
        self.assertContains(edit, str(key))
        self.assertContains(edit, "2.000")
        self.assertContains(edit, "Entrega 1")
        second_review = self.client.post(url, payload)
        self.assertEqual(second_review.status_code, 200)
        self.assertContains(second_review, str(key))
        confirmed_payload = {**payload, "confirm": "1"}
        self.assertEqual(self.client.post(url, confirmed_payload).status_code, 302)
        self.assertEqual(self.client.post(url, confirmed_payload).status_code, 302)

        line.refresh_from_db()
        self.purchase.refresh_from_db()
        receipt = PurchaseReceipt.objects.get(purchase=self.purchase)
        receipt_line = PurchaseReceiptLine.objects.get(receipt=receipt)
        movement = StockMovement.objects.get(purchase_receipt=receipt)
        inventory = InventoryItem.objects.get(store=self.store, product=product)
        self.assertEqual(line.quantity_received, 2)
        self.assertEqual(self.purchase.status, PurchaseStatusChoices.RECEIVED)
        self.assertEqual(inventory.current_stock, 2)
        self.assertEqual(
            PurchaseReceipt.objects.filter(purchase=self.purchase).count(), 1
        )
        self.assertEqual(PurchaseReceiptLine.objects.filter(receipt=receipt).count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(purchase=self.purchase).count(), 1
        )
        self.assertEqual(movement.purchase, self.purchase)
        self.assertEqual(movement.purchase_line, line)
        self.assertEqual(movement.purchase_receipt_line, receipt_line)
        self.assertEqual(movement.movement_type, StockMovement.TYPE_PURCHASE_RECEIPT)

    def test_cancel_purchase_by_post(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("purchases:purchase_cancel", kwargs={"pk": self.purchase.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, PurchaseStatusChoices.CANCELLED)
