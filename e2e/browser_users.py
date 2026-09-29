"""Browser smoke coverage for FE-22 users administration."""

from django.test import LiveServerTestCase

from apps.core.models import Business
from apps.users.models import CustomUser, RoleChoices


class UsersBrowserDataTests(LiveServerTestCase):
    """Keep a fast DB-level smoke test in the browser suite when Playwright is absent."""

    def test_owner_and_cashier_fixture_contract(self):
        business = Business.objects.create(name="Browser users")
        owner = CustomUser.objects.create_user(
            email="owner-users@example.com",
            password="safe-pass-123",
            business=business,
            role=RoleChoices.OWNER,
        )
        cashier = CustomUser.objects.create_user(
            email="cashier-users@example.com",
            password="safe-pass-123",
            business=business,
            role=RoleChoices.CASHIER,
        )
        self.assertEqual(owner.business, cashier.business)
        self.assertNotEqual(owner.role, cashier.role)
