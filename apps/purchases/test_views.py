from uuid import uuid4

from django.test import TestCase
from django.urls import reverse

from apps.business_config.models import POSSettings
from apps.catalog.models import Product
from apps.core.models import Business
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

    def test_cashier_is_forbidden(self):
        self.client.force_login(self.cashier)
        self.assertEqual(
            self.client.get(reverse("purchases:purchase_list")).status_code, 403
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
            ("purchase_order", {"pk": self.purchase.pk}),
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
        payload = {"idempotency_key": str(key), f"line_{line.pk}": "2.000"}
        self.client.force_login(self.owner)
        url = reverse("purchases:purchase_receive", kwargs={"pk": self.purchase.pk})
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)

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
