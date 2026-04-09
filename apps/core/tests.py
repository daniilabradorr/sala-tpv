from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.isolation import validate_same_business
from apps.core.models import Business


class BusinessModelTests(TestCase):
    def test_slug_is_generated_from_name(self):
        business = Business.objects.create(name="Sala Centro")

        self.assertEqual(business.slug, "sala-centro")

    def test_slug_must_be_unique(self):
        Business.objects.create(name="Sala Centro", slug="sala-centro")
        duplicate = Business(name="Otra Sala", slug="sala-centro")

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_active_and_inactive_scopes(self):
        active = Business.objects.create(name="Sala Centro", slug="sala-centro")
        inactive = Business.objects.create(
            name="Sala Norte",
            slug="sala-norte",
            is_active=False,
        )

        self.assertQuerySetEqual(
            Business.objects.active().order_by("id"),
            [active.id],
            transform=lambda obj: obj.id,
        )
        self.assertQuerySetEqual(
            Business.objects.inactive().order_by("id"),
            [inactive.id],
            transform=lambda obj: obj.id,
        )


class BusinessIsolationTests(TestCase):
    def test_validate_same_business_accepts_same_business(self):
        instance = SimpleNamespace(
            business_id=1,
            customer=SimpleNamespace(business_id=1),
            cash_register=SimpleNamespace(business_id=1),
        )

        validate_same_business(instance, "customer", "cash_register")

    def test_validate_same_business_rejects_cross_business_relations(self):
        instance = SimpleNamespace(
            business_id=1,
            customer=SimpleNamespace(business_id=2),
        )

        with self.assertRaises(ValidationError) as exc:
            validate_same_business(instance, "customer")

        self.assertIn("customer", exc.exception.message_dict)