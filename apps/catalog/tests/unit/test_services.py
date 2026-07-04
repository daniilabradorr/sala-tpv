from decimal import Decimal

from django.test import TestCase

from apps.catalog.models import Product
from apps.catalog.services import (
    ProductTaxResolutionError,
    resolve_product_tax,
)
from apps.catalog.tests.factories import (
    create_category,
    create_product,
    create_tax,
)
from apps.users.tests.factories import create_business


class ResolveProductTaxServiceTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )
        self.other_business = create_business(
            name="Negocio B",
            slug="negocio-b",
        )

        self.category = create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )

    def test_returns_product_specific_tax_when_it_is_active(self):
        """
        Si el producto tiene un impuesto específico activo,
        la función debe devolver ese impuesto.
        """
        product_tax = create_tax(
            business=self.business,
            name="IVA 10%",
            code="IVA_10",
            rate=Decimal("10.00"),
            is_default=False,
            is_active=True,
        )

        default_tax = create_tax(
            business=self.business,
            name="IVA 21%",
            code="IVA_21",
            rate=Decimal("21.00"),
            is_default=True,
            is_active=True,
        )

        product = create_product(
            business=self.business,
            category=self.category,
            tax=product_tax,
            name="Café",
            sku="CAFE",
            barcode="PRD000001",
            base_price=Decimal("1.50"),
        )

        resolved_tax = resolve_product_tax(product)

        self.assertEqual(resolved_tax, product_tax)
        self.assertNotEqual(resolved_tax, default_tax)

    def test_raises_error_when_product_specific_tax_is_inactive(self):
        """
        Si el producto tiene un impuesto específico pero está inactivo,
        la función debe lanzar error.

        No debe usar el impuesto por defecto silenciosamente.
        """
        product_tax = create_tax(
            business=self.business,
            name="IVA 10%",
            code="IVA_10",
            rate=Decimal("10.00"),
            is_default=False,
            is_active=True,
        )

        create_tax(
            business=self.business,
            name="IVA 21%",
            code="IVA_21",
            rate=Decimal("21.00"),
            is_default=True,
            is_active=True,
        )

        product = create_product(
            business=self.business,
            category=self.category,
            tax=product_tax,
            name="Café",
            sku="CAFE",
            barcode="PRD000002",
            base_price=Decimal("1.50"),
        )

        product_tax.is_active = False
        product_tax.save(update_fields=["is_active"])

        with self.assertRaises(ProductTaxResolutionError) as context:
            resolve_product_tax(product)

        self.assertIn("está inactivo", str(context.exception))

    def test_returns_default_tax_when_product_has_no_specific_tax(self):
        """
        Si el producto no tiene tax específico,
        debe usar el impuesto por defecto activo del mismo business.
        """
        default_tax = create_tax(
            business=self.business,
            name="IVA 21%",
            code="IVA_21",
            rate=Decimal("21.00"),
            is_default=True,
            is_active=True,
        )

        product = create_product(
            business=self.business,
            category=self.category,
            tax=None,
            name="Agua",
            sku="AGUA",
            barcode="PRD000003",
            base_price=Decimal("1.00"),
        )

        resolved_tax = resolve_product_tax(product)

        self.assertEqual(resolved_tax, default_tax)

    def test_raises_error_when_product_has_no_tax_and_business_has_no_default_tax(self):
        """
        Si el producto no tiene tax específico y el negocio no tiene
        impuesto por defecto activo, la función debe lanzar error.
        """
        product = create_product(
            business=self.business,
            category=self.category,
            tax=None,
            name="Agua",
            sku="AGUA",
            barcode="PRD000004",
            base_price=Decimal("1.00"),
        )

        with self.assertRaises(ProductTaxResolutionError) as context:
            resolve_product_tax(product)

        self.assertIn(
            "No existe un impuesto por defecto activo",
            str(context.exception),
        )

    def test_does_not_use_default_tax_from_other_business(self):
        """
        La función debe respetar el multi-business.

        Si existe un impuesto por defecto en otro negocio,
        no debe usarlo para este producto.
        """
        create_tax(
            business=self.other_business,
            name="IVA 21% Otro Negocio",
            code="IVA_21",
            rate=Decimal("21.00"),
            is_default=True,
            is_active=True,
        )

        product = create_product(
            business=self.business,
            category=self.category,
            tax=None,
            name="Agua",
            sku="AGUA",
            barcode="PRD000005",
            base_price=Decimal("1.00"),
        )

        with self.assertRaises(ProductTaxResolutionError):
            resolve_product_tax(product)

    def test_raises_error_when_product_has_no_business(self):
        """
        Si el producto no tiene business asociado,
        no se puede resolver el impuesto.
        """
        product = Product(
            name="Producto sin negocio",
            sku="SIN_NEGOCIO",
            barcode="PRD000006",
            base_price=Decimal("1.00"),
        )

        with self.assertRaises(ProductTaxResolutionError) as context:
            resolve_product_tax(product)

        self.assertIn(
            "no tiene negocio asociado",
            str(context.exception),
        )
