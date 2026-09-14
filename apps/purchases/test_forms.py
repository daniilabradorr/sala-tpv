from decimal import Decimal
from uuid import uuid4

from django.test import TestCase

from apps.catalog.models import Product
from apps.core.models import Business
from apps.purchases.forms import (
    PurchaseCreateForm,
    PurchaseLineCreateForm,
    PurchaseLineUpdateForm,
    PurchaseReceiptForm,
    PurchaseUpdateForm,
    SupplierForm,
)
from apps.purchases.models import Purchase, PurchaseLine, Supplier
from apps.stores.models import Store
from apps.users.models import RoleChoices, UserStoreAccess
from apps.users.tests.factories import create_user


class PurchaseFormTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="A", slug=f"a-{uuid4().hex}")
        self.other = Business.objects.create(name="B", slug=f"b-{uuid4().hex}")
        self.store = Store.objects.create(business=self.business, name="A", code="A1")
        self.other_store = Store.objects.create(
            business=self.other, name="B", code="B1"
        )
        self.supplier = Supplier.objects.create(
            business=self.business, name="Proveedor"
        )
        self.other_supplier = Supplier.objects.create(business=self.other, name="Ajeno")
        self.inactive_store = Store.objects.create(
            business=self.business, name="Inactiva", code="OFF", is_active=False
        )
        self.inactive_supplier = Supplier.objects.create(
            business=self.business, name="Inactivo", is_active=False
        )
        self.owner = create_user(
            business=self.business,
            role=RoleChoices.OWNER,
            email="forms-owner@test.com",
        )
        self.manager = create_user(
            business=self.business,
            role=RoleChoices.MANAGER,
            email="forms-manager@test.com",
        )
        UserStoreAccess.objects.create(
            business=self.business, user=self.manager, store=self.store
        )
        self.product = Product.objects.create(
            business=self.business,
            name="Servicio",
            sku=f"S-{uuid4().hex[:6]}",
            barcode=f"9{uuid4().int % 10**12:012d}",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
            track_stock=False,
        )
        self.inactive_product = Product.objects.create(
            business=self.business,
            name="Inactivo",
            sku=f"I-{uuid4().hex[:6]}",
            barcode=f"8{uuid4().int % 10**12:012d}",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
            is_active=False,
        )
        self.other_product = Product.objects.create(
            business=self.other,
            name="Ajeno",
            sku=f"O-{uuid4().hex[:6]}",
            barcode=f"7{uuid4().int % 10**12:012d}",
            base_price=1,
            cost_price=1,
            unit=Product.UNIT_UNIDAD,
        )

    def test_supplier_form_is_valid(self):
        self.assertTrue(
            SupplierForm({"name": "Proveedor", "email": "p@example.com"}).is_valid()
        )

    def test_purchase_create_choices_are_business_and_access_scoped(self):
        form = PurchaseCreateForm(business=self.business, user=self.manager)
        self.assertQuerySetEqual(form.fields["store"].queryset, [self.store])
        self.assertNotIn(self.other_store, form.fields["store"].queryset)
        self.assertNotIn(self.inactive_store, form.fields["store"].queryset)
        self.assertNotIn(self.other_supplier, form.fields["supplier"].queryset)
        self.assertNotIn(self.inactive_supplier, form.fields["supplier"].queryset)

    def test_purchase_update_can_keep_inactive_current_relations(self):
        purchase = Purchase.objects.create(
            business=self.business,
            store=self.store,
            supplier=self.supplier,
            created_by=self.owner,
        )
        Store.objects.filter(pk=self.store.pk).update(is_default=False, is_active=False)
        Supplier.objects.filter(pk=self.supplier.pk).update(is_active=False)
        form = PurchaseUpdateForm(
            business=self.business, user=self.owner, purchase=purchase
        )
        self.assertIn(self.store, form.fields["store"].queryset)
        self.assertIn(self.supplier, form.fields["supplier"].queryset)

    def test_purchase_line_create_includes_active_non_stock_product(self):
        form = PurchaseLineCreateForm(business=self.business)
        self.assertIn(self.product, form.fields["product"].queryset)
        self.assertNotIn(self.inactive_product, form.fields["product"].queryset)
        self.assertNotIn(self.other_product, form.fields["product"].queryset)
        self.assertNotIn("product", PurchaseLineUpdateForm().fields)

    def test_receipt_form_supports_multiple_lines_and_requires_quantity(self):
        lines = [
            PurchaseLine(
                pk=1, product_name="A", quantity_ordered=2, quantity_received=0
            ),
            PurchaseLine(
                pk=2, product_name="B", quantity_ordered=3, quantity_received=1
            ),
        ]
        empty = PurchaseReceiptForm(
            {"idempotency_key": str(uuid4())}, purchase_lines=lines
        )
        self.assertFalse(empty.is_valid())
        valid = PurchaseReceiptForm(
            {
                "idempotency_key": str(uuid4()),
                "line_1": "1.000",
                "line_2": "2.000",
            },
            purchase_lines=lines,
        )
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(
            [entry["quantity_received"] for entry in valid.receipt_lines()],
            [Decimal("1.000"), Decimal("2.000")],
        )

    def test_receipt_form_generates_uuid_and_rejects_non_positive_values(self):
        lines = [
            PurchaseLine(
                pk=1,
                product_name="A",
                quantity_ordered=1,
                quantity_received=1,
            )
        ]
        unbound = PurchaseReceiptForm(purchase_lines=lines)
        self.assertIsNotNone(unbound.initial["idempotency_key"])
        for value in ("0", "-1"):
            bound = PurchaseReceiptForm(
                {"idempotency_key": str(uuid4()), "line_1": value},
                purchase_lines=lines,
            )
            self.assertFalse(bound.is_valid())
            self.assertIn("line_1", bound.fields)
