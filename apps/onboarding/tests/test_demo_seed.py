from decimal import Decimal

from django.test import TestCase

from apps.catalog.models import Category, Product, Tax
from apps.customers.models import Customer, CustomerAccount
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import decrease_stock
from apps.onboarding.demo_seed import (
    DemoBusinessSeeder,
    DemoSeedConflictError,
    DemoSeedPrerequisiteError,
)
from apps.onboarding.services import OnboardingService
from apps.stores.models import Store


def provision_business(*, suffix=""):
    return OnboardingService.create_business(
        legal_name=f"Demo Retail {suffix} SL",
        trade_name=f"Demo {suffix}",
        tax_identifier=f"B8765432{suffix or '1'}",
        phone="923111111",
        email=f"demo{suffix}@business.example.com",
        address_line_1="Calle Principal 1",
        postal_code="37001",
        city="Salamanca",
        province="Salamanca",
        country_code="ES",
        store_name="Tienda principal",
        owner_first_name="Demo",
        owner_last_name="Owner",
        owner_email=f"owner{suffix}@example.com",
        owner_phone="600000000",
        owner_password="safe-demo-test-password",
        owner_pin="1234",
    )


class DemoBusinessSeederTests(TestCase):
    def setUp(self):
        self.onboarding = provision_business()
        self.business = self.onboarding.business

    def test_first_run_creates_complete_dataset_through_domain_services(self):
        result = DemoBusinessSeeder.seed(business=self.business)

        self.assertEqual(result.category_counts.created, 3)
        self.assertEqual(result.product_counts.created, 6)
        self.assertEqual(result.inventory_counts.created, 5)
        self.assertEqual(result.initial_stocks_created, 5)
        self.assertEqual(result.customer_counts.created, 2)
        self.assertEqual(
            Category.objects.filter(
                business=self.business, slug__startswith="demo-"
            ).count(),
            3,
        )
        self.assertEqual(
            Product.objects.filter(
                business=self.business, sku__startswith="DEMO-"
            ).count(),
            6,
        )
        self.assertEqual(
            InventoryItem.objects.filter(
                business=self.business, product__sku__startswith="DEMO-"
            ).count(),
            5,
        )
        self.assertEqual(
            StockMovement.objects.filter(
                business=self.business, movement_type=StockMovement.TYPE_INITIAL
            ).count(),
            5,
        )
        self.assertEqual(
            CustomerAccount.objects.filter(
                business=self.business, customer__in=result.customers
            ).count(),
            2,
        )

        water = Product.objects.get(business=self.business, sku="DEMO-AGUA-500")
        service = Product.objects.get(business=self.business, sku="DEMO-ENVOLTORIO")
        self.assertEqual(water.base_price, Decimal("0.90"))
        self.assertTrue(water.track_stock)
        self.assertFalse(water.is_service)
        self.assertIsNone(water.tax)
        self.assertFalse(service.track_stock)
        self.assertTrue(service.is_service)
        self.assertIsNone(service.barcode)
        self.assertFalse(InventoryItem.objects.filter(product=service).exists())

        item = InventoryItem.objects.get(product=water, store=self.onboarding.store)
        movement = item.movements.get(movement_type=StockMovement.TYPE_INITIAL)
        self.assertEqual(item.current_stock, Decimal("48.000"))
        self.assertEqual(movement.stock_before, Decimal("0.000"))
        self.assertEqual(movement.stock_after, Decimal("48.000"))

        counter = Customer.objects.get(
            business=self.business, email="demo.mostrador@example.com"
        )
        company = Customer.objects.get(
            business=self.business, tax_identifier="B12345678"
        )
        self.assertFalse(counter.has_complete_fiscal_identity)
        self.assertTrue(company.has_complete_fiscal_identity)
        self.assertEqual(company.account.credit_limit, Decimal("500.00"))

    def test_second_run_reuses_everything_and_does_not_reset_stock(self):
        first = DemoBusinessSeeder.seed(business=self.business)
        water_item = next(
            item
            for item in first.inventory_items
            if item.product.sku == "DEMO-AGUA-500"
        )
        decrease_stock(
            inventory_item=water_item,
            quantity=Decimal("5.000"),
            movement_type=StockMovement.TYPE_LOSS,
            reason="Merma de prueba",
        )

        second = DemoBusinessSeeder.seed(business=self.business)

        water_item.refresh_from_db()
        self.assertEqual(second.category_counts.reused, 3)
        self.assertEqual(second.product_counts.reused, 6)
        self.assertEqual(second.inventory_counts.reused, 5)
        self.assertEqual(second.customer_counts.reused, 2)
        self.assertEqual(second.initial_stocks_created, 0)
        self.assertEqual(water_item.current_stock, Decimal("43.000"))
        self.assertEqual(
            water_item.movements.filter(
                movement_type=StockMovement.TYPE_INITIAL
            ).count(),
            1,
        )

    def test_missing_default_store_is_rejected_without_repair(self):
        # Deliberately bypass Store.save() to simulate inconsistent legacy data.
        Store.objects.filter(pk=self.onboarding.store.pk).update(is_default=False)

        with self.assertRaises(DemoSeedPrerequisiteError):
            DemoBusinessSeeder.seed(business=self.business)

        self.assertEqual(Category.objects.filter(business=self.business).count(), 0)

    def test_missing_default_tax_is_rejected_without_repair(self):
        Tax.objects.filter(business=self.business).update(is_active=False)

        with self.assertRaises(DemoSeedPrerequisiteError):
            DemoBusinessSeeder.seed(business=self.business)

        self.assertEqual(Category.objects.filter(business=self.business).count(), 0)

    def test_late_product_conflict_rolls_back_new_demo_records(self):
        Product.objects.create(
            business=self.business,
            name="Conflicto",
            sku="DEMO-BOLSA",
            barcode=None,
            base_price=Decimal("1.00"),
            is_service=True,
            track_stock=False,
        )
        with self.assertRaises(DemoSeedConflictError):
            DemoBusinessSeeder.seed(business=self.business)

        self.assertEqual(
            Category.objects.filter(
                business=self.business, slug__startswith="demo-"
            ).count(),
            0,
        )
        self.assertEqual(
            Product.objects.filter(
                business=self.business, sku__startswith="DEMO-"
            ).count(),
            1,
        )

    def test_uses_only_default_store_and_isolates_other_business(self):
        secondary = Store.objects.create(
            business=self.business, name="Secundaria", code="SEC-01"
        )
        other = provision_business(suffix="2")

        DemoBusinessSeeder.seed(business=self.business)

        self.assertEqual(
            InventoryItem.objects.filter(
                business=self.business, store=secondary
            ).count(),
            0,
        )
        self.assertEqual(
            InventoryItem.objects.filter(
                business=self.business, store=self.onboarding.store
            ).count(),
            5,
        )
        self.assertEqual(Category.objects.filter(business=other.business).count(), 0)
        self.assertEqual(Product.objects.filter(business=other.business).count(), 0)
        self.assertEqual(Customer.objects.filter(business=other.business).count(), 0)
