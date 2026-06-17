from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.users.models import CustomUser, RoleChoices, UserStoreAccess
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_user,
    create_store_access,
)


class CustomUserModelTests(TestCase):
    def setUp(self):
        self.business = create_business()

    def test_create_user_with_business_and_role(self):
        user = create_user(
            business=self.business,
            email="cashier@test.com",
            role=RoleChoices.CASHIER,
        )

        self.assertEqual(user.email, "cashier@test.com")
        self.assertEqual(user.business, self.business)
        self.assertEqual(user.role, RoleChoices.CASHIER)
        self.assertTrue(user.is_active)

    def test_str_returns_full_name_when_user_has_name(self):
        user = create_user(
            business=self.business,
            email="daniel@test.com",
            first_name="Daniel",
            last_name="Labrador",
        )

        self.assertEqual(str(user), "Daniel Labrador")

    def test_str_returns_email_when_user_has_no_name(self):
        user = create_user(
            business=self.business,
            email="noname@test.com",
            first_name="",
            last_name="",
        )

        self.assertEqual(str(user), "noname@test.com")

    def test_phone_must_contain_only_digits(self):
        user = CustomUser(
            business=self.business,
            email="badphone@test.com",
            role=RoleChoices.CASHIER,
            phone="600ABC123",
        )

        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_normal_user_requires_business(self):
        user = CustomUser(
            email="nobusiness@test.com",
            role=RoleChoices.CASHIER,
            phone="600123123",
        )

        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_set_pin_saves_hash_not_plain_pin(self):
        user = create_user(
            business=self.business,
            email="pin@test.com",
        )

        user.set_pin("1234")
        user.save()

        self.assertNotEqual(user.pin_hash, "1234")
        self.assertTrue(user.check_pin("1234"))

    def test_check_pin_returns_false_with_wrong_pin(self):
        user = create_user(
            business=self.business,
            email="wrongpin@test.com",
        )

        user.set_pin("1234")
        user.save()

        self.assertFalse(user.check_pin("9999"))

    def test_check_pin_returns_false_if_user_has_no_pin(self):
        user = create_user(
            business=self.business,
            email="nopin@test.com",
        )

        self.assertFalse(user.check_pin("1234"))

    def test_pin_must_contain_only_digits(self):
        user = create_user(
            business=self.business,
            email="pinletters@test.com",
        )

        with self.assertRaises(ValidationError):
            user.set_pin("12AB")

    def test_pin_must_have_between_4_and_6_digits(self):
        user = create_user(
            business=self.business,
            email="pinlength@test.com",
        )

        with self.assertRaises(ValidationError):
            user.set_pin("123")

        with self.assertRaises(ValidationError):
            user.set_pin("1234567")


class UserStoreAccessModelTests(TestCase):
    def setUp(self):
        self.business = create_business()
        self.store = create_store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )
        self.user = create_user(
            business=self.business,
            email="cashier@test.com",
            role=RoleChoices.CASHIER,
        )

    def test_create_user_store_access(self):
        access = create_store_access(
            business=self.business,
            user=self.user,
            store=self.store,
            can_sell=True,
            can_open_cash=True,
            can_close_cash=False,
        )

        self.assertEqual(access.business, self.business)
        self.assertEqual(access.user, self.user)
        self.assertEqual(access.store, self.store)
        self.assertTrue(access.can_sell)
        self.assertTrue(access.can_open_cash)
        self.assertFalse(access.can_close_cash)
        self.assertTrue(access.is_active)

    def test_str_returns_user_and_store(self):
        access = create_store_access(
            business=self.business,
            user=self.user,
            store=self.store,
        )

        self.assertIn(str(self.user), str(access))
        self.assertIn(str(self.store), str(access))

    def test_user_must_belong_to_same_business(self):
        other_business = create_business(
            name="Otro negocio",
            slug="otro-negocio",
        )
        other_user = create_user(
            business=other_business,
            email="other@test.com",
        )

        access = UserStoreAccess(
            business=self.business,
            user=other_user,
            store=self.store,
        )

        with self.assertRaises(ValidationError):
            access.full_clean()

    def test_store_must_belong_to_same_business(self):
        other_business = create_business(
            name="Otro negocio",
            slug="otro-negocio",
        )
        other_store = create_store(
            business=other_business,
            name="Otra tienda",
            code="OTRA",
        )

        access = UserStoreAccess(
            business=self.business,
            user=self.user,
            store=other_store,
        )

        with self.assertRaises(ValidationError):
            access.full_clean()

    def test_cannot_duplicate_user_store_access(self):
        create_store_access(
            business=self.business,
            user=self.user,
            store=self.store,
        )

        duplicated_access = UserStoreAccess(
            business=self.business,
            user=self.user,
            store=self.store,
        )

        with self.assertRaises(ValidationError):
            duplicated_access.full_clean()
