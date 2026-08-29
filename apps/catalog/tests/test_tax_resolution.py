from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.catalog.services import ProductTaxResolutionError, resolve_product_tax
from apps.catalog.tests.factories import create_product, create_tax
from apps.users.tests.factories import create_business


class ProductTaxResolutionTests(TestCase):
    def setUp(self):
        self.business = create_business()

    def test_active_product_tax_wins_over_default(self):
        default = create_tax(business=self.business, is_default=True)
        specific = create_tax(
            business=self.business, name="IVA 10", code="IVA_10", rate=10
        )
        product = create_product(business=self.business, tax=specific)
        self.assertEqual(resolve_product_tax(product), specific)
        self.assertNotEqual(resolve_product_tax(product), default)

    def test_product_without_tax_uses_active_business_default(self):
        default = create_tax(business=self.business, is_default=True)
        product = create_product(business=self.business)
        self.assertEqual(resolve_product_tax(product), default)

    def test_inactive_specific_tax_is_an_error(self):
        tax = create_tax(business=self.business, is_active=False)
        product = create_product(business=self.business, tax=tax)
        with self.assertRaises(ProductTaxResolutionError):
            resolve_product_tax(product)

    def test_missing_or_inactive_default_is_an_error(self):
        product = create_product(business=self.business)
        with self.assertRaises(ProductTaxResolutionError):
            resolve_product_tax(product)
        create_tax(business=self.business, is_default=True, is_active=False)
        with self.assertRaises(ProductTaxResolutionError):
            resolve_product_tax(product)

    def test_other_business_default_is_never_used(self):
        create_tax(business=create_business(), is_default=True)
        product = create_product(business=self.business)
        with self.assertRaises(ProductTaxResolutionError):
            resolve_product_tax(product)

    def test_one_default_per_business_and_defaults_for_two_businesses(self):
        create_tax(business=self.business, is_default=True)
        with self.assertRaises(ValidationError):
            create_tax(
                business=self.business,
                name="IVA 10",
                code="IVA_10",
                rate=10,
                is_default=True,
            )
        other = create_business()
        self.assertTrue(create_tax(business=other, is_default=True).is_default)

    def test_deprecated_profile_rate_cannot_change_resolved_tax(self):
        default = create_tax(
            business=self.business,
            name="IVA 10",
            code="IVA_10",
            rate=Decimal("10.00"),
            is_default=True,
        )
        self.business.profile.default_tax_rate = Decimal("21.00")
        self.business.profile.save()
        product = create_product(business=self.business)
        self.assertEqual(resolve_product_tax(product), default)
        self.assertEqual(self.business.pos_settings.resolve_tax_rate(), default.rate)
