"""Synthetic, deterministic commercial objects; never read production data."""

from decimal import Decimal
from hashlib import sha256

from django.utils import timezone

from apps.billing.models import BillingSeries
from apps.business_config.services import create_business_configuration
from apps.cash_register.models import CashRegister, CashSession
from apps.catalog.models import Category, Product
from apps.inventory.models import InventoryItem
from apps.payments.models import PaymentMethod
from apps.sales.models import Sale, SaleLine
from apps.sales.services import calculate_sale_line_amounts
from apps.sales.tests.factories import (
    create_sale,
    create_sales_business,
    create_sales_customer,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


class Dataset:
    """Setup is deliberately outside every measured interval.

    Bulk inserts are only fixture setup. Line snapshots use the existing amount
    calculator, with real Product/Tax/Inventory relations and consistent totals.
    """

    def __init__(self, catalog_size=250, label="baseline"):
        self.business = create_sales_business(name="TPV Baseline", slug=label)
        self.store = create_sales_store(
            business=self.business, name="Baseline", code="BASE"
        )
        self.user = create_sales_user(
            business=self.business, email=f"{label}@example.test"
        )
        _, self.settings = create_business_configuration(
            business=self.business,
            legal_name="Baseline ficticio SL",
            tax_identifier="TEST-" + sha256(label.encode()).hexdigest()[:10],
            phone="600000000",
            email="fixture@example.test",
            address_line_1="Dirección ficticia 1",
            postal_code="28001",
            city="Madrid",
            province="Madrid",
        )
        self.settings.require_pin_for_sensitive_actions = False
        self.settings.save()
        self.taxes = [
            create_sales_tax(business=self.business, code="IVA21", rate=Decimal("21")),
            create_sales_tax(
                business=self.business,
                code="IVA10",
                rate=Decimal("10"),
                is_default=False,
            ),
        ]
        self.categories = [
            Category.objects.create(
                business=self.business, name=f"Categoría {i}", slug=f"category-{i}"
            )
            for i in range(3)
        ]
        self.customers = [
            create_sales_customer(
                business=self.business,
                name=f"Cliente ficticio {i}",
                legal_name=f"Cliente ficticio {i}",
                tax_identifier=f"TEST-CUSTOMER-{i}",
            )
            for i in range(2)
        ]
        self.register = CashRegister.objects.create(
            business=self.business, store=self.store, name="Baseline", code="BASE"
        )
        self.session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.register,
            opened_by=self.user,
        )
        self.methods = [
            PaymentMethod.objects.create(business=self.business, name=name, code=code)
            for name, code in (("Efectivo", "cash"), ("Tarjeta", "card"))
        ]
        for kind in ("F1", "F2"):
            BillingSeries.objects.create(
                business=self.business,
                store=self.store,
                name=f"Baseline {kind}",
                document_type=kind,
                prefix=f"BASE-{kind}",
                year=timezone.localdate().year,
            )
        self.products = []
        self.grow_catalog(catalog_size)

    def grow_catalog(self, size):
        products = Product.objects.bulk_create(
            [
                Product(
                    business=self.business,
                    category=self.categories[i % 3],
                    tax=self.taxes[i % 2] if i % 3 else None,
                    name=f"Producto {i:04d}",
                    sku=f"BASE-{i:04d}",
                    barcode=f"900000{i:07d}",
                    base_price=Decimal("10.00"),
                    cost_price=Decimal("4.00"),
                    track_stock=True,
                    is_active=True,
                )
                for i in range(len(self.products), size)
            ]
        )
        InventoryItem.objects.bulk_create(
            [
                InventoryItem(
                    business=self.business,
                    store=self.store,
                    product=product,
                    current_stock=Decimal("1000"),
                )
                for product in products
            ]
        )
        self.products.extend(products)

    def sale(self, line_count=0, *, quantity="1", customer=None, document="ticket"):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            cash_register=self.register,
            cash_session=self.session,
            customer=customer,
            document_type_requested=document,
        )
        lines = []
        subtotal = taxes = Decimal("0.00")
        for product in self.products[:line_count]:
            tax = product.tax or self.taxes[0]
            amounts = calculate_sale_line_amounts(
                quantity=Decimal(quantity),
                unit_base_price=product.base_price,
                discount_amount=Decimal("0"),
                tax_rate=tax.rate,
            )
            subtotal += amounts["quantity"] * amounts["unit_base_price"]
            taxes += amounts["tax_amount"]
            lines.append(
                SaleLine(
                    business=self.business,
                    sale=sale,
                    product=product,
                    product_name=product.name,
                    sku=product.sku,
                    category_source_id=product.category_id,
                    category_name=product.category.name,
                    category_slug=product.category.slug,
                    unit=product.unit,
                    tax_type=tax.tax_type,
                    clave_regimen=tax.clave_regimen,
                    calificacion_operacion=tax.calificacion_operacion,
                    **{
                        key: amounts[key]
                        for key in (
                            "quantity",
                            "unit_base_price",
                            "discount_amount",
                            "tax_rate",
                            "tax_amount",
                            "line_total",
                        )
                    },
                )
            )
        SaleLine.objects.bulk_create(lines)
        Sale.objects.filter(pk=sale.pk).update(
            subtotal_amount=subtotal,
            tax_amount=taxes,
            total_amount=subtotal + taxes,
            pending_amount=subtotal + taxes,
        )
        sale.refresh_from_db()
        return sale, lines
