"""Non-destructive, idempotent demo data provisioning for an existing business."""

from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Category, Product
from apps.catalog.services import (
    BusinessDefaultTaxResolutionError,
    resolve_business_default_tax,
)
from apps.customers.models import Customer, CustomerAccount, CustomerTypeChoices
from apps.customers.services import CustomerService
from apps.inventory.models import InventoryItem
from apps.inventory.services import create_initial_stock, create_inventory_item
from apps.stores.models import Store


class DemoSeedError(Exception):
    """Base class for expected demo seed failures."""


class DemoSeedConflictError(DemoSeedError):
    """Raised when a deterministic demo key belongs to incompatible data."""


class DemoSeedPrerequisiteError(DemoSeedError):
    """Raised when onboarding infrastructure required by the seed is missing."""


@dataclass
class SeedCounts:
    created: int = 0
    reused: int = 0


@dataclass
class DemoSeedResult:
    business: object
    store: Store
    categories: list[Category] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    inventory_items: list[InventoryItem] = field(default_factory=list)
    customers: list[Customer] = field(default_factory=list)
    category_counts: SeedCounts = field(default_factory=SeedCounts)
    product_counts: SeedCounts = field(default_factory=SeedCounts)
    inventory_counts: SeedCounts = field(default_factory=SeedCounts)
    customer_counts: SeedCounts = field(default_factory=SeedCounts)
    initial_stocks_created: int = 0


class DemoBusinessSeeder:
    """Add the fixed shop demo dataset without changing onboarding infrastructure."""

    CATEGORIES = (
        {"slug": "demo-bebidas", "name": "Bebidas", "sort_order": 10},
        {"slug": "demo-alimentacion", "name": "Alimentación", "sort_order": 20},
        {"slug": "demo-servicios", "name": "Servicios", "sort_order": 30},
    )
    PRODUCTS = (
        {
            "sku": "DEMO-AGUA-500",
            "name": "Agua mineral 500 ml",
            "barcode": "DEMO000001",
            "category_slug": "demo-bebidas",
            "base_price": Decimal("0.90"),
            "cost_price": Decimal("0.35"),
            "unit": Product.UNIT_UNIDAD,
            "track_stock": True,
            "is_service": False,
            "sort_order": 10,
            "stock": Decimal("48.000"),
            "minimum_stock": Decimal("12.000"),
            "location": "A1",
        },
        {
            "sku": "DEMO-REFRESCO-COLA",
            "name": "Refresco cola 330 ml",
            "barcode": "DEMO000002",
            "category_slug": "demo-bebidas",
            "base_price": Decimal("1.50"),
            "cost_price": Decimal("0.55"),
            "unit": Product.UNIT_UNIDAD,
            "track_stock": True,
            "is_service": False,
            "sort_order": 20,
            "stock": Decimal("36.000"),
            "minimum_stock": Decimal("8.000"),
            "location": "A2",
        },
        {
            "sku": "DEMO-PATATAS",
            "name": "Patatas chips",
            "barcode": "DEMO000003",
            "category_slug": "demo-alimentacion",
            "base_price": Decimal("1.80"),
            "cost_price": Decimal("0.70"),
            "unit": Product.UNIT_UNIDAD,
            "track_stock": True,
            "is_service": False,
            "sort_order": 30,
            "stock": Decimal("24.000"),
            "minimum_stock": Decimal("6.000"),
            "location": "B1",
        },
        {
            "sku": "DEMO-CHOCOLATE",
            "name": "Barrita de chocolate",
            "barcode": "DEMO000004",
            "category_slug": "demo-alimentacion",
            "base_price": Decimal("1.20"),
            "cost_price": Decimal("0.45"),
            "unit": Product.UNIT_UNIDAD,
            "track_stock": True,
            "is_service": False,
            "sort_order": 40,
            "stock": Decimal("30.000"),
            "minimum_stock": Decimal("8.000"),
            "location": "B2",
        },
        {
            "sku": "DEMO-BOLSA",
            "name": "Bolsa reutilizable",
            "barcode": "DEMO000005",
            "category_slug": "demo-alimentacion",
            "base_price": Decimal("0.50"),
            "cost_price": Decimal("0.15"),
            "unit": Product.UNIT_UNIDAD,
            "track_stock": True,
            "is_service": False,
            "sort_order": 50,
            "stock": Decimal("50.000"),
            "minimum_stock": Decimal("10.000"),
            "location": "B3",
        },
        {
            "sku": "DEMO-ENVOLTORIO",
            "name": "Envoltorio para regalo",
            "barcode": None,
            "category_slug": "demo-servicios",
            "base_price": Decimal("2.00"),
            "cost_price": None,
            "unit": Product.UNIT_SERVICIO,
            "track_stock": False,
            "is_service": True,
            "sort_order": 60,
            "stock": None,
            "minimum_stock": None,
            "location": None,
        },
    )
    CUSTOMERS = (
        {
            "lookup": {
                "name": "Cliente Mostrador DEMO",
                "email": "demo.mostrador@example.com",
            },
            "data": {
                "customer_type": CustomerTypeChoices.PERSON,
                "name": "Cliente Mostrador DEMO",
                "legal_name": "",
                "tax_identifier": "",
                "country_code": "ES",
                "email": "demo.mostrador@example.com",
                "phone": "",
                "address_line_1": "",
                "postal_code": "",
                "city": "",
                "province": "",
            },
            "credit_limit": Decimal("0.00"),
            "is_blocked": False,
        },
        {
            "lookup": {"tax_identifier": "B12345678"},
            "data": {
                "customer_type": CustomerTypeChoices.COMPANY,
                "name": "Empresa Demo Netxodo SL",
                "legal_name": "Empresa Demo Netxodo SL",
                "tax_identifier": "B12345678",
                "country_code": "ES",
                "email": "demo.empresa@example.com",
                "phone": "923000000",
                "address_line_1": "Calle Demo 1",
                "postal_code": "37001",
                "city": "Salamanca",
                "province": "Salamanca",
            },
            "credit_limit": Decimal("500.00"),
            "is_blocked": False,
        },
    )

    @classmethod
    @transaction.atomic
    def seed(cls, *, business):
        if business is None or not getattr(business, "pk", None):
            raise DemoSeedPrerequisiteError(
                "El Business debe existir antes de cargar la demo."
            )
        if not business.is_active:
            raise DemoSeedPrerequisiteError("El Business está inactivo.")

        stores = Store.objects.filter(
            business=business, is_default=True, is_active=True
        )
        if stores.count() != 1:
            raise DemoSeedPrerequisiteError(
                "Debe existir exactamente una Store predeterminada activa para el Business."
            )
        store = stores.get()
        try:
            resolve_business_default_tax(business=business)
        except BusinessDefaultTaxResolutionError as exc:
            raise DemoSeedPrerequisiteError(str(exc)) from exc

        result = DemoSeedResult(business=business, store=store)
        categories = {}
        for definition in cls.CATEGORIES:
            category, created = cls._category(business, definition)
            categories[definition["slug"]] = category
            result.categories.append(category)
            cls._count(result.category_counts, created)

        for definition in cls.PRODUCTS:
            product, created = cls._product(business, categories, definition)
            result.products.append(product)
            cls._count(result.product_counts, created)
            if product.track_stock:
                item, item_created = cls._inventory(
                    business, store, product, definition
                )
                result.inventory_items.append(item)
                cls._count(result.inventory_counts, item_created)
                if item_created:
                    try:
                        create_initial_stock(
                            inventory_item=item,
                            quantity=definition["stock"],
                            unit_cost=product.cost_price,
                            reason="Stock inicial demo",
                            notes="Generado por seed_demo_business",
                            user=None,
                        )
                    except (IntegrityError, ValidationError) as exc:
                        raise DemoSeedConflictError(
                            f"No se pudo crear el stock inicial demo de '{product.sku}': {exc}"
                        ) from exc
                    result.initial_stocks_created += 1

        for definition in cls.CUSTOMERS:
            customer, created = cls._customer(business, definition)
            result.customers.append(customer)
            cls._count(result.customer_counts, created)
        return result

    @staticmethod
    def _count(counts, created):
        if created:
            counts.created += 1
        else:
            counts.reused += 1

    @classmethod
    def _category(cls, business, definition):
        matches = list(
            Category.objects.filter(business=business, slug=definition["slug"])
        )
        if matches:
            category = matches[0]
            cls._assert_matches(
                category, definition, ("name", "slug", "sort_order"), "categoría"
            )
            cls._assert_matches(
                category,
                {"parent_id": None, "is_active": True},
                ("parent_id", "is_active"),
                "categoría",
            )
            return category, False
        try:
            with transaction.atomic():
                category = Category(
                    business=business, parent=None, is_active=True, **definition
                )
                category.save()
        except (IntegrityError, ValidationError) as exc:
            raise DemoSeedConflictError(
                f"No se pudo crear la categoría demo '{definition['slug']}': {exc}"
            ) from exc
        return category, True

    @classmethod
    def _product(cls, business, categories, definition):
        matches = list(Product.objects.filter(business=business, sku=definition["sku"]))
        expected = {
            key: definition[key]
            for key in (
                "name",
                "sku",
                "barcode",
                "base_price",
                "cost_price",
                "unit",
                "track_stock",
                "is_service",
                "sort_order",
            )
        }
        expected.update(
            category_id=categories[definition["category_slug"]].pk,
            tax_id=None,
            is_active=True,
        )
        if matches:
            product = matches[0]
            cls._assert_matches(product, expected, tuple(expected), "producto")
            return product, False
        fields = {
            key: value for key, value in expected.items() if not key.endswith("_id")
        }
        fields["category"] = categories[definition["category_slug"]]
        fields["tax"] = None
        try:
            with transaction.atomic():
                product = Product(business=business, **fields)
                product.save()
        except (IntegrityError, ValidationError) as exc:
            raise DemoSeedConflictError(
                f"No se pudo crear el producto demo '{definition['sku']}': {exc}"
            ) from exc
        return product, True

    @classmethod
    def _inventory(cls, business, store, product, definition):
        matches = list(
            InventoryItem.objects.filter(
                business=business, store=store, product=product
            )
        )
        if matches:
            item = matches[0]
            expected = {
                "minimum_stock": definition["minimum_stock"],
                "maximum_stock": None,
                "location": definition["location"],
                "is_active": True,
            }
            cls._assert_matches(item, expected, tuple(expected), "ficha de inventario")
            return item, False
        try:
            with transaction.atomic():
                item = create_inventory_item(
                    business=business,
                    store=store,
                    product=product,
                    minimum_stock=definition["minimum_stock"],
                    maximum_stock=None,
                    location=definition["location"],
                )
        except (IntegrityError, ValidationError) as exc:
            raise DemoSeedConflictError(
                f"No se pudo crear el inventario demo de '{product.sku}': {exc}"
            ) from exc
        return item, True

    @classmethod
    def _customer(cls, business, definition):
        matches = list(
            Customer.objects.filter(business=business, **definition["lookup"])
        )
        if len(matches) > 1:
            raise DemoSeedConflictError(
                f"Hay múltiples clientes demo para {definition['lookup']}."
            )
        if matches:
            customer = matches[0]
            cls._assert_matches(
                customer, definition["data"], tuple(definition["data"]), "cliente"
            )
            try:
                account = customer.account
            except CustomerAccount.DoesNotExist as exc:
                raise DemoSeedConflictError(
                    f"El cliente demo '{customer.name}' no tiene CustomerAccount."
                ) from exc
            expected = {
                "business_id": business.pk,
                "credit_limit": definition["credit_limit"],
                "is_blocked": definition["is_blocked"],
            }
            cls._assert_matches(account, expected, tuple(expected), "cuenta de cliente")
            return customer, False
        try:
            with transaction.atomic():
                customer, _account = CustomerService.create_customer(
                    business=business,
                    customer_data=definition["data"],
                    credit_limit=definition["credit_limit"],
                    is_blocked=definition["is_blocked"],
                )
        except (IntegrityError, ValidationError) as exc:
            raise DemoSeedConflictError(
                f"No se pudo crear el cliente demo '{definition['data']['name']}': {exc}"
            ) from exc
        return customer, True

    @staticmethod
    def _assert_matches(instance, expected, fields, kind):
        conflicts = [
            field for field in fields if getattr(instance, field) != expected[field]
        ]
        if conflicts:
            key = (
                getattr(instance, "sku", None)
                or getattr(instance, "slug", None)
                or getattr(instance, "name", str(instance.pk))
            )
            raise DemoSeedConflictError(
                f"El/la {kind} demo '{key}' tiene configuración incompatible: {', '.join(conflicts)}."
            )
