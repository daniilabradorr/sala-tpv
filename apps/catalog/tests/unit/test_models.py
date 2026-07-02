from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.catalog.models import Category, Tax, Product
from apps.catalog.tests.factories import create_category, create_tax, create_product
from apps.users.tests.factories import create_business


class CategoryModelTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )
        self.other_business = create_business(
            name="Negocio B",
            slug="negocio-b",
        )

    def test_category_str_returns_name(self):
        category = create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )

        self.assertEqual(str(category), "Bebidas")

    def test_category_generates_slug_when_empty(self):
        category = Category.objects.create(
            business=self.business,
            name="Bebidas Frías",
            slug="",
        )

        self.assertEqual(category.slug, "bebidas-frias")

    def test_category_generates_unique_slug_per_business(self):
        create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )

        category = Category.objects.create(
            business=self.business,
            name="Bebidas",
            slug="",
        )

        self.assertEqual(category.slug, "bebidas-2")

    def test_same_slug_is_allowed_in_different_business(self):
        create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )

        category = Category(
            business=self.other_business,
            name="Bebidas",
            slug="bebidas",
        )

        category.full_clean()

        self.assertEqual(category.slug, "bebidas")

    def test_category_cannot_be_parent_of_itself(self):
        category = create_category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )
        category.parent = category

        with self.assertRaises(ValidationError) as context:
            category.full_clean()

        self.assertIn("parent", context.exception.message_dict)

    def test_category_parent_must_belong_to_same_business(self):
        other_parent = create_category(
            business=self.other_business,
            name="Otra Categoría",
            slug="otra-categoria",
        )

        category = Category(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
            parent=other_parent,
        )

        with self.assertRaises(ValidationError) as context:
            category.full_clean()

        self.assertIn("parent", context.exception.message_dict)

    def test_category_defaults_are_correct(self):
        category = Category.objects.create(
            business=self.business,
            name="Bebidas",
            slug="bebidas",
        )

        self.assertTrue(category.is_active)
        self.assertEqual(category.sort_order, 0)


class TaxModelTests(TestCase):
    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )
        self.other_business = create_business(
            name="Negocio B",
            slug="negocio-b",
        )

    def test_tax_generates_code_when_empty(self):
        tax = Tax.objects.create(
            business=self.business,
            name="IVA 21%",
            code="",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
        )

        self.assertEqual(tax.code, "IVA_21")

    def test_tax_code_must_be_unique_per_business(self):
        create_tax(
            business=self.business,
            code="IVA_21",
        )

        duplicate = Tax(
            business=self.business,
            name="IVA 21 duplicado",
            code="IVA_21",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_same_tax_code_is_allowed_in_different_business(self):
        create_tax(
            business=self.business,
            code="IVA_21",
        )

        tax = Tax(
            business=self.other_business,
            name="IVA 21%",
            code="IVA_21",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
        )

        tax.full_clean()

        self.assertEqual(tax.code, "IVA_21")

    def test_only_one_default_tax_per_business(self):
        create_tax(
            business=self.business,
            code="IVA_21",
            is_default=True,
        )

        duplicate_default = Tax(
            business=self.business,
            name="IVA 10%",
            code="IVA_10",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("10.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
            is_default=True,
        )

        with self.assertRaises(ValidationError):
            duplicate_default.full_clean()

    def test_default_tax_is_allowed_in_different_business(self):
        create_tax(
            business=self.business,
            code="IVA_21",
            is_default=True,
        )

        tax = Tax(
            business=self.other_business,
            name="IVA 21%",
            code="IVA_21",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
            is_default=True,
        )

        tax.full_clean()

        self.assertTrue(tax.is_default)

    def test_tax_rejects_negative_rate(self):
        tax = Tax(
            business=self.business,
            name="IVA negativo",
            code="IVA_NEG",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("-1.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
        )

        with self.assertRaises(ValidationError) as context:
            tax.full_clean()

        self.assertIn("rate", context.exception.message_dict)

    def test_tax_sets_s1_when_not_exempt_and_calification_empty(self):
        tax = Tax(
            business=self.business,
            name="IVA 21%",
            code="IVA_21",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            calificacion_operacion=None,
            operacion_exenta=None,
        )

        tax.full_clean()

        self.assertEqual(tax.calificacion_operacion, "S1")

    def test_exempt_operation_must_have_zero_rate(self):
        tax = Tax(
            business=self.business,
            name="Exento incorrecto",
            code="EXENTO_BAD",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            operacion_exenta="E1",
        )

        with self.assertRaises(ValidationError) as context:
            tax.full_clean()

        self.assertIn("rate", context.exception.message_dict)

    def test_exempt_operation_with_zero_rate_is_valid_and_clears_calification(self):
        tax = Tax(
            business=self.business,
            name="Exento art 20",
            code="EXENTO_20",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("0.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
            operacion_exenta="E1",
        )

        tax.full_clean()

        self.assertIsNone(tax.calificacion_operacion)

    def test_non_subject_operation_must_have_zero_rate(self):
        tax = Tax(
            business=self.business,
            name="No sujeto incorrecto",
            code="NO_SUJETO_BAD",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            calificacion_operacion="N1",
        )

        with self.assertRaises(ValidationError) as context:
            tax.full_clean()

        self.assertIn("rate", context.exception.message_dict)

    def test_equivalence_surcharge_requires_rate(self):
        tax = Tax(
            business=self.business,
            name="Recargo sin porcentaje",
            code="RECARGO_BAD",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
            has_equivalence_surcharge=True,
            equivalence_surcharge_rate=None,
        )

        with self.assertRaises(ValidationError) as context:
            tax.full_clean()

        self.assertIn("equivalence_surcharge_rate", context.exception.message_dict)

    def test_equivalence_surcharge_rate_requires_flag(self):
        tax = Tax(
            business=self.business,
            name="Recargo mal informado",
            code="RECARGO_BAD",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
            has_equivalence_surcharge=False,
            equivalence_surcharge_rate=Decimal("5.20"),
        )

        with self.assertRaises(ValidationError) as context:
            tax.full_clean()

        self.assertIn("equivalence_surcharge_rate", context.exception.message_dict)

    def test_equivalence_surcharge_sets_regimen_18(self):
        tax = Tax(
            business=self.business,
            name="IVA 21 + Recargo",
            code="IVA_21_RE",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen="01",
            calificacion_operacion="S1",
            has_equivalence_surcharge=True,
            equivalence_surcharge_rate=Decimal("5.20"),
        )

        tax.full_clean()

        self.assertEqual(tax.clave_regimen, "18")


class ProductModelTests(TestCase):
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
        self.other_category = create_category(
            business=self.other_business,
            name="Otra Categoría",
            slug="otra-categoria",
        )

        self.tax = create_tax(
            business=self.business,
            code="IVA_21",
            is_default=True,
        )
        self.other_tax = create_tax(
            business=self.other_business,
            code="IVA_21",
        )

    def test_product_str_returns_name(self):
        product = create_product(
            business=self.business,
            category=self.category,
            tax=self.tax,
            name="Coca-Cola 500ml",
        )

        self.assertEqual(str(product), "Coca-Cola 500ml")

    def test_product_generates_sku_when_empty(self):
        product = Product.objects.create(
            business=self.business,
            category=self.category,
            tax=self.tax,
            name="Coca Cola 500ml",
            sku="",
            barcode="PRD000010",
            base_price=Decimal("2.00"),
        )

        self.assertTrue(product.sku)
        self.assertIn("COCA", product.sku)

    def test_physical_product_generates_barcode_when_empty(self):
        product = Product.objects.create(
            business=self.business,
            category=self.category,
            tax=self.tax,
            name="Producto sin barcode",
            sku="PROD_BAR",
            barcode="",
            base_price=Decimal("2.00"),
            is_service=False,
        )

        self.assertTrue(product.barcode)

    def test_service_does_not_track_stock_and_does_not_have_barcode(self):
        product = Product(
            business=self.business,
            category=self.category,
            tax=self.tax,
            name="Servicio de instalación",
            sku="SERV_INST",
            barcode="123456",
            base_price=Decimal("30.00"),
            track_stock=True,
            is_service=True,
        )

        product.full_clean()

        self.assertFalse(product.track_stock)
        self.assertIsNone(product.barcode)

    def test_product_rejects_negative_base_price(self):
        product = Product(
            business=self.business,
            category=self.category,
            tax=self.tax,
            name="Producto inválido",
            sku="BAD",
            barcode="BAD001",
            base_price=Decimal("-1.00"),
        )

        with self.assertRaises(ValidationError) as context:
            product.full_clean()

        self.assertIn("base_price", context.exception.message_dict)

    def test_product_rejects_negative_cost_price(self):
        product = Product(
            business=self.business,
            category=self.category,
            tax=self.tax,
            name="Producto inválido",
            sku="BAD",
            barcode="BAD001",
            base_price=Decimal("10.00"),
            cost_price=Decimal("-1.00"),
        )

        with self.assertRaises(ValidationError) as context:
            product.full_clean()

        self.assertIn("cost_price", context.exception.message_dict)

    def test_product_category_must_belong_to_same_business(self):
        product = Product(
            business=self.business,
            category=self.other_category,
            tax=self.tax,
            name="Producto inválido",
            sku="BAD",
            barcode="BAD001",
            base_price=Decimal("10.00"),
        )

        with self.assertRaises(ValidationError) as context:
            product.full_clean()

        self.assertIn("category", context.exception.message_dict)

    def test_product_tax_must_belong_to_same_business(self):
        product = Product(
            business=self.business,
            category=self.category,
            tax=self.other_tax,
            name="Producto inválido",
            sku="BAD",
            barcode="BAD001",
            base_price=Decimal("10.00"),
        )

        with self.assertRaises(ValidationError) as context:
            product.full_clean()

        self.assertIn("tax", context.exception.message_dict)

    def test_product_rejects_inactive_tax(self):
        inactive_tax = create_tax(
            business=self.business,
            name="IVA inactivo",
            code="IVA_INACTIVO",
            is_active=False,
        )

        product = Product(
            business=self.business,
            category=self.category,
            tax=inactive_tax,
            name="Producto inválido",
            sku="BAD",
            barcode="BAD001",
            base_price=Decimal("10.00"),
        )

        with self.assertRaises(ValidationError) as context:
            product.full_clean()

        self.assertIn("tax", context.exception.message_dict)

    def test_product_base_price_is_saved_without_tax(self):
        product = create_product(
            business=self.business,
            category=self.category,
            tax=self.tax,
            name="Producto",
            base_price=Decimal("10.00"),
        )

        self.assertEqual(product.base_price, Decimal("10.00"))
