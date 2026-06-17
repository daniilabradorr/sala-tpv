from django.test import TestCase

from apps.users.models import CustomUser, RoleChoices
from apps.users.tests.factories import create_business


class CustomUserManagerTests(TestCase):
    def setUp(self):
        self.business = create_business()

    def test_create_user_with_email_and_password(self):
        user = CustomUser.objects.create_user(
            email="USER@TEST.COM",
            password="testpass123",
            business=self.business,
            role=RoleChoices.CASHIER,
            first_name="Test",
            last_name="User",
            phone="600123123",
        )

        self.assertEqual(user.email, "USER@test.com")
        self.assertEqual(user.business, self.business)
        self.assertEqual(user.role, RoleChoices.CASHIER)
        self.assertTrue(user.check_password("testpass123"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_without_email_raises_error(self):
        with self.assertRaises(ValueError):
            CustomUser.objects.create_user(
                email="",
                password="testpass123",
                business=self.business,
                role=RoleChoices.CASHIER,
                first_name="Test",
                last_name="User",
                phone="600123123",
            )

    def test_create_superuser_sets_staff_and_superuser_true(self):
        superuser = CustomUser.objects.create_superuser(
            email="admin@test.com",
            password="adminpass123",
            role=RoleChoices.OWNER,
            first_name="Admin",
            last_name="User",
            phone="600123123",
        )

        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.is_active)
        self.assertTrue(superuser.check_password("adminpass123"))

    def test_create_superuser_without_staff_true_raises_error(self):
        with self.assertRaises(ValueError):
            CustomUser.objects.create_superuser(
                email="admin@test.com",
                password="adminpass123",
                role=RoleChoices.OWNER,
                first_name="Admin",
                last_name="User",
                phone="600123123",
                is_staff=False,
            )

    def test_create_superuser_without_superuser_true_raises_error(self):
        with self.assertRaises(ValueError):
            CustomUser.objects.create_superuser(
                email="admin@test.com",
                password="adminpass123",
                role=RoleChoices.OWNER,
                first_name="Admin",
                last_name="User",
                phone="600123123",
                is_superuser=False,
            )
