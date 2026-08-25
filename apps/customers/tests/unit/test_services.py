import uuid
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)

from apps.sales.models import SaleReturnStatusChoices

from apps.sales.tests.factories import (
    create_sale,
    create_sale_return,
    create_sales_store,
)
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.cash_register.models import CashRegister, CashSession
from apps.customers.models import (
    Customer,
    CustomerAccount,
    CustomerAccountEntry,
    EntryTypeChoices,
)
from apps.customers.services import (
    CustomerAccountService,
    CustomerService,
    _to_decimal,
    _validate_business,
    _validate_user_business,
)
from apps.customers.tests.factories import create_account, create_customer_user
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_user


class ServiceHelperTests(TestCase):
    def setUp(self):
        self.business = create_business(slug="svc-helpers")

    def test_to_decimal_int(self):
        self.assertEqual(_to_decimal(2), Decimal("2"))

    def test_to_decimal_str_decimal(self):
        self.assertEqual(_to_decimal("2.50"), Decimal("2.50"))

    def test_to_decimal_decimal(self):
        self.assertEqual(_to_decimal(Decimal("2.50")), Decimal("2.50"))

    def test_to_decimal_abc(self):
        with self.assertRaises(ValidationError):
            _to_decimal("abc")

    def test_to_decimal_empty(self):
        with self.assertRaises(ValidationError):
            _to_decimal("")

    def test_to_decimal_none(self):
        with self.assertRaises(ValidationError):
            _to_decimal(None)

    def test_to_decimal_nan(self):
        with self.assertRaises(ValidationError):
            _to_decimal("NaN")

    def test_to_decimal_infinity(self):
        with self.assertRaises(ValidationError):
            _to_decimal("Infinity")

    def test_to_decimal_negative_infinity(self):
        with self.assertRaises(ValidationError):
            _to_decimal("-Infinity")

    def test_validate_business_none(self):
        with self.assertRaises(ValidationError):
            _validate_business(None)

    def test_validate_business_inactive(self):
        self.business.is_active = False
        self.business.save()
        with self.assertRaises(ValidationError):
            _validate_business(self.business)

    def test_validate_user_none(self):
        _validate_user_business(user=None, business=self.business)

    def test_validate_superuser_without_business(self):
        user = create_user(
            business=None,
            email="svcsuper@test.com",
            role=RoleChoices.OWNER,
            is_superuser=True,
            is_staff=True,
        )
        _validate_user_business(user=user, business=self.business)

    def test_validate_normal_same_business(self):
        _validate_user_business(
            user=create_customer_user(business=self.business), business=self.business
        )

    def test_validate_normal_other_business(self):
        user = create_customer_user(
            business=create_business(name="Other", slug="svc-other")
        )
        with self.assertRaises(ValidationError):
            _validate_user_business(user=user, business=self.business)

    def test_validate_normal_without_business(self):
        user = create_user(
            business=None,
            email="svcnobiz@test.com",
            role=RoleChoices.CASHIER,
            is_superuser=True,
        )
        user.is_superuser = False
        with self.assertRaises(ValidationError):
            _validate_user_business(user=user, business=self.business)


class CustomerServiceTests(TestCase):
    def setUp(self):
        self.business = create_business(slug="svc-customer")

    def test_create_customer_success_and_defaults(self):
        customer, account = CustomerService.create_customer(
            business=self.business,
            customer_data={"name": "Ana", "customer_type": "person"},
        )
        self.assertEqual(customer.business, self.business)
        self.assertEqual(account.customer, customer)
        self.assertEqual(account.balance, Decimal("0.00"))
        self.assertEqual(account.credit_limit, Decimal("0.00"))
        self.assertFalse(account.is_blocked)

    def test_create_generates_exactly_one_account(self):
        customer, _ = CustomerService.create_customer(
            business=self.business, customer_data={"name": "Ana"}
        )
        self.assertEqual(CustomerAccount.objects.filter(customer=customer).count(), 1)

    def test_create_filters_non_editable_fields(self):
        customer, account = CustomerService.create_customer(
            business=self.business,
            customer_data={"name": "Ana", "is_active": False},
            credit_limit="1.00",
            is_blocked=True,
        )
        self.assertTrue(customer.is_active)
        self.assertTrue(account.is_blocked)

    def test_rollback_if_customer_save_fails(self):
        with patch(
            "apps.customers.models.Customer.save", side_effect=ValidationError("boom")
        ):
            with self.assertRaises(ValidationError):
                CustomerService.create_customer(
                    business=self.business, customer_data={"name": "Ana"}
                )
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(CustomerAccount.objects.count(), 0)

    def test_rollback_if_account_save_fails(self):
        with patch(
            "apps.customers.models.CustomerAccount.save",
            side_effect=ValidationError("boom"),
        ):
            with self.assertRaises(ValidationError):
                CustomerService.create_customer(
                    business=self.business, customer_data={"name": "Ana"}
                )
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(CustomerAccount.objects.count(), 0)

    def test_update_customer_success_and_ignores_business(self):
        customer, _ = CustomerService.create_customer(
            business=self.business, customer_data={"name": "Ana"}
        )
        updated = CustomerService.update_customer(
            business=self.business,
            customer=customer,
            customer_data={"name": "Eva", "business": create_business(slug="ignored")},
        )
        self.assertEqual(updated.name, "Eva")
        self.assertEqual(updated.business, self.business)

    def test_update_other_business_rejected(self):
        other = create_business(name="Other", slug="svc-update-other")
        customer, _ = CustomerService.create_customer(
            business=other, customer_data={"name": "Ana"}
        )
        with self.assertRaises(ValidationError):
            CustomerService.update_customer(
                business=self.business, customer=customer, customer_data={"name": "Eva"}
            )

    def test_deactivate_and_double_deactivate(self):
        customer, _ = CustomerService.create_customer(
            business=self.business, customer_data={"name": "Ana"}
        )
        self.assertFalse(
            CustomerService.deactivate_customer(
                business=self.business, customer=customer
            ).is_active
        )
        self.assertFalse(
            CustomerService.deactivate_customer(
                business=self.business, customer=customer
            ).is_active
        )

    def test_reactivate_and_double_reactivate(self):
        customer, _ = CustomerService.create_customer(
            business=self.business, customer_data={"name": "Ana"}
        )
        CustomerService.deactivate_customer(business=self.business, customer=customer)
        self.assertTrue(
            CustomerService.reactivate_customer(
                business=self.business, customer=customer
            ).is_active
        )
        self.assertTrue(
            CustomerService.reactivate_customer(
                business=self.business, customer=customer
            ).is_active
        )

    def test_inactive_business_rejected(self):
        self.business.is_active = False
        self.business.save()
        with self.assertRaises(ValidationError):
            CustomerService.create_customer(
                business=self.business, customer_data={"name": "Ana"}
            )


class CustomerAccountServiceTests(TestCase):
    def setUp(self):
        self.business = create_business(slug="svc-account")
        self.user = create_customer_user(business=self.business)
        self.account = create_account(
            business=self.business,
            balance=Decimal("0.00"),
            credit_limit=Decimal("100.00"),
        )

    def _sale(self, *, business=None, customer=None):
        business = business or self.business
        user = self.user
        if business != self.business:
            user = create_customer_user(business=business)
        return create_sale(
            business=business,
            store=create_sales_store(business=business),
            opened_by=user,
            customer=customer,
        )

    def _cash_session(self, *, store):
        cash_register = CashRegister.objects.create(
            business=self.business,
            store=store,
            name=f"Caja {uuid.uuid4().hex[:8]}",
            code=f"CAJA-{uuid.uuid4().hex[:8].upper()}",
        )
        return CashSession.objects.create(
            business=self.business,
            store=store,
            cash_register=cash_register,
            opened_by=self.user,
        )

    def test_update_account_settings_success_zero_positive_and_no_entries(self):
        CustomerAccountService.update_account_settings(
            business=self.business,
            account=self.account,
            credit_limit="0.00",
            is_blocked=True,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertTrue(self.account.is_blocked)
        self.assertEqual(CustomerAccountEntry.objects.count(), 0)
        CustomerAccountService.update_account_settings(
            business=self.business,
            account=self.account,
            credit_limit="50.00",
            is_blocked=False,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.credit_limit, Decimal("50.00"))
        self.assertFalse(self.account.is_blocked)

    def test_update_account_settings_invalids(self):
        other = create_account(
            business=create_business(name="Other", slug="svc-account-other")
        )
        for value in ["-1.00", "abc"]:
            with self.assertRaises(ValidationError):
                CustomerAccountService.update_account_settings(
                    business=self.business,
                    account=self.account,
                    credit_limit=value,
                    is_blocked=False,
                )
        with self.assertRaises(ValidationError):
            CustomerAccountService.update_account_settings(
                business=self.business,
                account=other,
                credit_limit="1.00",
                is_blocked=False,
            )

    def test_create_charge_valid_exact_limit_and_notes(self):
        locked, entry = CustomerAccountService.create_charge(
            business=self.business,
            account=self.account,
            amount="100.00",
            user=self.user,
            notes=" ok ",
        )
        self.assertEqual(locked.balance, Decimal("100.00"))
        self.assertEqual(entry.entry_type, EntryTypeChoices.CHARGE)
        self.assertEqual(entry.balance_after, locked.balance)
        self.assertEqual(entry.notes, "ok")
        self.assertEqual(CustomerAccountEntry.objects.count(), 1)

    def test_create_charge_accepts_optional_matching_sale(self):
        sale = self._sale(customer=self.account.customer)
        _, entry = CustomerAccountService.create_charge(
            business=self.business,
            account=self.account,
            amount="10.00",
            user=self.user,
            sale=sale,
        )
        self.assertEqual(entry.sale, sale)

    def test_create_charge_without_sale_remains_supported(self):
        _, entry = CustomerAccountService.create_charge(
            business=self.business,
            account=self.account,
            amount="10.00",
            user=self.user,
        )
        self.assertIsNone(entry.sale)

    def test_create_charge_rejects_cross_business_and_customer_sales(self):
        other_business = create_business(name="Other", slug="svc-sale-other")
        with self.assertRaises(ValidationError):
            CustomerAccountService.create_charge(
                business=self.business,
                account=self.account,
                amount="10.00",
                user=self.user,
                sale=self._sale(business=other_business),
            )
        other_account = create_account(business=self.business)
        with self.assertRaises(ValidationError):
            CustomerAccountService.create_charge(
                business=self.business,
                account=self.account,
                amount="10.00",
                user=self.user,
                sale=self._sale(customer=other_account.customer),
            )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(CustomerAccountEntry.objects.count(), 0)

    def test_create_charge_rejections(self):
        for amount in ["0.00", "-1.00", "abc"]:
            with self.assertRaises(ValidationError):
                CustomerAccountService.create_charge(
                    business=self.business,
                    account=self.account,
                    amount=amount,
                    user=self.user,
                )
        with self.assertRaises(ValidationError):
            CustomerAccountService.create_charge(
                business=self.business,
                account=self.account,
                amount="100.01",
                user=self.user,
            )
        self.account.is_blocked = True
        self.account.save()
        with self.assertRaises(ValidationError):
            CustomerAccountService.create_charge(
                business=self.business,
                account=self.account,
                amount="1.00",
                user=self.user,
            )
        self.account.is_blocked = False
        self.account.customer.is_active = False
        self.account.customer.save()
        with self.assertRaises(ValidationError):
            CustomerAccountService.create_charge(
                business=self.business,
                account=self.account,
                amount="1.00",
                user=self.user,
            )

    def test_payment_partial_exact_overpay_blocked_inactive(self):
        CustomerAccountService.create_charge(
            business=self.business, account=self.account, amount="50.00", user=self.user
        )
        CustomerAccountService.register_payment(
            business=self.business, account=self.account, amount="10.00", user=self.user
        )
        CustomerAccountService.register_payment(
            business=self.business, account=self.account, amount="40.00", user=self.user
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.account.is_blocked = True
        self.account.customer.is_active = False
        self.account.save()
        self.account.customer.save()
        _, entry = CustomerAccountService.register_payment(
            business=self.business, account=self.account, amount="5.00", user=self.user
        )
        self.account.refresh_from_db()
        self.assertEqual(entry.amount, Decimal("-5.00"))
        self.assertEqual(self.account.balance, Decimal("-5.00"))

    def test_payment_invalids(self):
        for amount in ["0.00", "-1.00", "abc"]:
            with self.assertRaises(ValidationError):
                CustomerAccountService.register_payment(
                    business=self.business,
                    account=self.account,
                    amount=amount,
                    user=self.user,
                )

    def test_refund_valid_and_allowed_when_blocked_inactive(self):
        self.account.is_blocked = True
        self.account.customer.is_active = False
        self.account.save()
        self.account.customer.save()
        _, entry = CustomerAccountService.register_refund(
            business=self.business, account=self.account, amount="3.00", user=self.user
        )
        self.account.refresh_from_db()
        self.assertEqual(entry.amount, Decimal("-3.00"))
        self.assertEqual(self.account.balance, Decimal("-3.00"))

    def test_refund_invalids(self):
        for amount in ["0.00", "-1.00"]:
            with self.assertRaises(ValidationError):
                CustomerAccountService.register_refund(
                    business=self.business,
                    account=self.account,
                    amount=amount,
                    user=self.user,
                )

    def test_adjustment_variants(self):
        CustomerAccountService.create_adjustment(
            business=self.business,
            account=self.account,
            amount_delta="5.00",
            user=self.user,
            notes="plus",
        )
        CustomerAccountService.create_adjustment(
            business=self.business,
            account=self.account,
            amount_delta="-2.00",
            user=self.user,
            notes="minus",
        )

        self.account.refresh_from_db()
        self.account.is_blocked = True
        self.account.save(update_fields=["is_blocked", "updated_at"])

        customer = self.account.customer
        customer.is_active = False
        customer.save(update_fields=["is_active", "updated_at"])

        CustomerAccountService.create_adjustment(
            business=self.business,
            account=self.account,
            amount_delta="1.00",
            user=self.user,
            notes="inactive ok",
        )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("4.00"))

    def test_adjustment_invalids(self):
        for kwargs in [
            {"amount_delta": "0.00", "notes": "zero"},
            {"amount_delta": "1.00", "notes": ""},
            {"amount_delta": "1.00", "notes": "   "},
        ]:
            with self.assertRaises(ValidationError):
                CustomerAccountService.create_adjustment(
                    business=self.business,
                    account=self.account,
                    user=self.user,
                    **kwargs,
                )

    def test_other_business_user_rejected(self):
        other_user = create_customer_user(
            business=create_business(name="Other", slug="svc-user-other")
        )
        with self.assertRaises(ValidationError):
            CustomerAccountService.create_charge(
                business=self.business,
                account=self.account,
                amount="1.00",
                user=other_user,
            )

    def test_entry_save_rollback_restores_balance(self):
        before_balance = self.account.balance
        before_updated_at = self.account.updated_at
        with patch(
            "apps.customers.models.CustomerAccountEntry.save",
            side_effect=ValidationError("boom"),
        ):
            with self.assertRaises(ValidationError):
                CustomerAccountService.create_charge(
                    business=self.business,
                    account=self.account,
                    amount="1.00",
                    user=self.user,
                )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, before_balance)
        self.assertEqual(CustomerAccountEntry.objects.count(), 0)
        self.assertEqual(self.account.updated_at, before_updated_at)

    def test_select_for_update_is_used(self):
        with patch(
            "apps.customers.models.CustomerAccount.objects.select_for_update",
            wraps=CustomerAccount.objects.select_for_update,
        ) as spy:
            CustomerAccountService.create_charge(
                business=self.business,
                account=self.account,
                amount="1.00",
                user=self.user,
            )
        self.assertTrue(spy.called)

    def test_register_refund_with_payment_is_idempotent(self):
        store = create_sales_store(
            business=self.business,
        )

        sale = create_sale(
            business=self.business,
            store=store,
            opened_by=self.user,
            customer=self.account.customer,
            total_amount=Decimal("10.00"),
        )

        sale_return = create_sale_return(
            business=self.business,
            store=store,
            original_sale=sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("3.00"),
        )

        method = PaymentMethod.objects.create(
            business=self.business,
            name="Tarjeta",
            code="card",
        )
        session = self._cash_session(store=store)

        refund_payment = Payment.objects.create(
            business=self.business,
            store=store,
            sale=sale,
            method=method,
            sale_return=sale_return,
            payment_type=PaymentTypeChoices.REFUND,
            amount=Decimal("3.00"),
            status=PaymentStatusChoices.COMPLETED,
            processed_by=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session=session,
        )

        account_1, entry_1 = CustomerAccountService.register_refund(
            business=self.business,
            account=self.account,
            amount=Decimal("3.00"),
            user=self.user,
            sale=sale,
            payment=refund_payment,
            notes="Refund test",
        )

        account_2, entry_2 = CustomerAccountService.register_refund(
            business=self.business,
            account=self.account,
            amount=Decimal("3.00"),
            user=self.user,
            sale=sale,
            payment=refund_payment,
            notes="Refund test",
        )

        self.assertEqual(entry_1.pk, entry_2.pk)
        self.assertEqual(account_1.pk, account_2.pk)

        self.assertEqual(
            CustomerAccountEntry.objects.filter(payment=refund_payment).count(),
            1,
        )

        self.account.refresh_from_db()

        self.assertEqual(
            self.account.balance,
            Decimal("-3.00"),
        )

    def test_register_refund_rejects_same_payment_with_different_amount(self):
        store = create_sales_store(
            business=self.business,
        )

        sale = create_sale(
            business=self.business,
            store=store,
            opened_by=self.user,
            customer=self.account.customer,
            total_amount=Decimal("10.00"),
        )

        sale_return = create_sale_return(
            business=self.business,
            store=store,
            original_sale=sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("3.00"),
        )

        method = PaymentMethod.objects.create(
            business=self.business,
            name="Tarjeta",
            code="card",
        )
        session = self._cash_session(store=store)

        refund_payment = Payment.objects.create(
            business=self.business,
            store=store,
            sale=sale,
            method=method,
            sale_return=sale_return,
            payment_type=PaymentTypeChoices.REFUND,
            amount=Decimal("3.00"),
            status=PaymentStatusChoices.COMPLETED,
            processed_by=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session=session,
        )

        CustomerAccountService.register_refund(
            business=self.business,
            account=self.account,
            amount=Decimal("3.00"),
            user=self.user,
            sale=sale,
            payment=refund_payment,
        )

        with self.assertRaises(ValidationError):
            CustomerAccountService.register_refund(
                business=self.business,
                account=self.account,
                amount=Decimal("2.00"),
                user=self.user,
                sale=sale,
                payment=refund_payment,
            )
