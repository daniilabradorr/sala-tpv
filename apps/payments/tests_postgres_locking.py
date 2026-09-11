"""PostgreSQL regression tests for nullable joins in payment row locks."""

import uuid
from decimal import Decimal

from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.cash_register.models import CashRegister, CashSession
from apps.customers.models import CustomerAccount, CustomerAccountEntry
from apps.payments.models import Payment, PaymentMethod, PaymentStatusChoices
from apps.payments.services import (
    register_refund,
    register_sale_on_account,
    register_sale_payment,
)
from apps.sales.models import SaleReturnStatusChoices, SaleStatusChoices
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sale,
    create_sale_return,
    create_sales_business,
    create_sales_customer,
    create_sales_store,
    create_sales_user,
)


@skipUnlessDBFeature("has_select_for_update")
class PaymentPostgreSQLLockingTests(TransactionTestCase):
    """Execute real payment services against PostgreSQL row locks."""

    reset_sequences = True

    def setUp(self):
        self.business = create_sales_business(name="Payments PostgreSQL")
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business, pin="1234")
        create_pos_settings(
            business=self.business,
            require_open_cash_register=True,
            require_pin_for_sensitive_actions=True,
        )
        self.method = PaymentMethod.objects.create(
            business=self.business,
            name="Tarjeta",
            code="card",
        )
        register = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja PostgreSQL",
            code="PG-PAY-01",
        )
        self.session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )

    def create_completed_sale(self, *, customer=None):
        return create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            customer=customer,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("100.00"),
            cash_register=None,
            cash_session=None,
        )

    def pay(self, sale, amount=Decimal("100.00")):
        return register_sale_payment(
            business=self.business,
            sale_id=sale.pk,
            method_id=self.method.pk,
            amount=amount,
            user=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session_id=self.session.pk,
        )

    def test_register_sale_payment_locks_sale_with_nullable_cash_session(self):
        sale = self.create_completed_sale()

        payment = self.pay(sale)

        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())

    def test_register_refund_locks_sale_with_nullable_cash_session(self):
        sale = self.create_completed_sale()
        self.pay(sale)
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("20.00"),
        )

        refund = register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.method.pk,
            amount=Decimal("20.00"),
            user=self.user,
            pin="1234",
            idempotency_key=uuid.uuid4(),
            cash_session_id=self.session.pk,
        )

        self.assertEqual(refund.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(refund.sale_return_id, returned.pk)

    def test_register_sale_on_account_locks_nullable_customer_relation(self):
        customer = create_sales_customer(business=self.business)
        CustomerAccount.objects.create(
            business=self.business,
            customer=customer,
            credit_limit=Decimal("200.00"),
        )
        sale = self.create_completed_sale(customer=customer)

        charge = register_sale_on_account(
            business=self.business,
            sale_id=sale.pk,
            user=self.user,
        )

        self.assertEqual(charge.sale_id, sale.pk)
        self.assertTrue(CustomerAccountEntry.objects.filter(pk=charge.pk).exists())
