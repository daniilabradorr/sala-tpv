from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.customers.models import CustomerAccountEntry
from apps.customers.services import CustomerAccountService, CustomerService
from apps.customers.tests.factories import create_account, create_customer_user
from apps.users.tests.factories import create_business


class CustomerServiceTests(TestCase):
    def test_create_update_deactivate_reactivate(self):
        b = create_business(slug="svc")
        c = CustomerService.create_customer(
            business=b,
            data={"name": "Ana", "country_code": "ES", "customer_type": "individual"},
        )
        self.assertEqual(c.account.balance, Decimal("0.00"))
        c = CustomerService.update_customer(
            business=b, customer=c, data={"name": "B", "is_active": False}
        )
        self.assertEqual(c.name, "B")
        self.assertTrue(c.is_active)
        self.assertFalse(
            CustomerService.deactivate_customer(business=b, customer=c).is_active
        )
        self.assertFalse(
            CustomerService.deactivate_customer(business=b, customer=c).is_active
        )
        self.assertTrue(
            CustomerService.reactivate_customer(business=b, customer=c).is_active
        )
        self.assertTrue(
            CustomerService.reactivate_customer(business=b, customer=c).is_active
        )
        b.is_active = False
        b.save()
        with self.assertRaises(ValidationError):
            CustomerService.create_customer(business=b, data={"name": "X"})


class CustomerAccountServiceTests(TestCase):
    def test_account_operations_and_rollbacks(self):
        b = create_business(slug="acct")
        user = create_customer_user(business=b)
        account = create_account(business=b, credit_limit=Decimal("100.00"))
        CustomerAccountService.update_account_settings(
            business=b, account=account, credit_limit=Decimal("50.00"), is_blocked=True
        )
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("0.00"))
        self.assertTrue(account.is_blocked)
        self.assertFalse(CustomerAccountEntry.objects.exists())
        with self.assertRaises(ValidationError):
            CustomerAccountService.update_account_settings(
                business=b,
                account=account,
                credit_limit=Decimal("-1.00"),
                is_blocked=False,
            )
        account.is_blocked = False
        account.save()
        e = CustomerAccountService.create_charge(
            business=b, account=account, amount=Decimal("10.00"), user=user
        )
        self.assertEqual(e.amount, Decimal("10.00"))
        self.assertEqual(e.balance_after, Decimal("10.00"))
        CustomerAccountService.register_payment(
            business=b, account=account, amount=Decimal("15.00"), user=user
        )
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("-5.00"))
        CustomerAccountService.register_refund(
            business=b, account=account, amount=Decimal("1.00"), user=user
        )
        CustomerAccountService.create_adjustment(
            business=b, account=account, amount=Decimal("2.00"), user=user, notes="ok"
        )
        CustomerAccountService.create_adjustment(
            business=b, account=account, amount=Decimal("-1.00"), user=user, notes="ok"
        )
        with self.assertRaises(ValidationError):
            CustomerAccountService.create_adjustment(
                business=b,
                account=account,
                amount=Decimal("0.00"),
                user=user,
                notes="ok",
            )
        with self.assertRaises(ValidationError):
            CustomerAccountService.create_adjustment(
                business=b, account=account, amount=Decimal("1.00"), user=user, notes=""
            )
        other_b = create_business(name="Other", slug="otheracct")
        other_user = create_customer_user(business=other_b)
        with self.assertRaises(ValidationError):
            CustomerAccountService.register_payment(
                business=b, account=account, amount=Decimal("1.00"), user=other_user
            )
        with patch(
            "apps.customers.models.CustomerAccountEntry.save",
            side_effect=ValidationError("boom"),
        ):
            before = account.balance
            with self.assertRaises(ValidationError):
                CustomerAccountService.register_payment(
                    business=b, account=account, amount=Decimal("1.00"), user=user
                )
            account.refresh_from_db()
            self.assertEqual(account.balance, before)
