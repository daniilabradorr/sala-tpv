import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connections
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from apps.customers.models import (
    CustomerAccount,
    CustomerAccountEntry,
    EntryTypeChoices,
)
from apps.customers.services import CustomerAccountService
from apps.payments.forms import PaymentCreateForm
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.payments.selectors import get_sale_payment_summary
from apps.payments.services import (
    cancel_payment,
    register_refund,
    register_sale_payment,
)
from apps.sales.models import (
    PaymentStatusChoices as SalePaymentStatus,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sale,
    create_sale_return,
    create_sales_business,
    create_sales_customer,
    create_sales_store,
    create_sales_user,
)


class PaymentsTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.other_business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business, pin="1234")
        create_pos_settings(business=self.business)
        self.card = PaymentMethod.objects.create(
            business=self.business, name="Tarjeta", code="card"
        )
        self.cash = PaymentMethod.objects.create(
            business=self.business, name="Efectivo", code="cash"
        )
        self.sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("100"),
        )

    def pay(self, amount, method=None, key=None):
        return register_sale_payment(
            business=self.business,
            sale_id=self.sale.pk,
            method_id=(method or self.card).pk,
            amount=amount,
            user=self.user,
            idempotency_key=key or uuid.uuid4(),
        )

    def test_method_enforces_cash_register_flag_and_business_code_unique(self):
        self.assertFalse(self.card.affects_cash_register)
        self.assertTrue(self.cash.affects_cash_register)
        for code in ("bizum", "transfer"):
            method = PaymentMethod.objects.create(
                business=self.business, name=code, code=code, affects_cash_register=True
            )
            self.assertFalse(method.affects_cash_register)
        with self.assertRaises(ValidationError):
            PaymentMethod.objects.create(
                business=self.business, name="Otra", code="card"
            )

    def test_form_is_business_scoped_validates_amount_and_has_hidden_uuid(self):
        foreign = PaymentMethod.objects.create(
            business=self.other_business, name="B", code="card"
        )
        form = PaymentCreateForm(business=self.business)
        self.assertNotIn(foreign, form.fields["method"].queryset)
        self.assertEqual(form.fields["idempotency_key"].widget.input_type, "hidden")
        invalid = PaymentCreateForm(
            {"method": self.card.pk, "amount": "0", "idempotency_key": uuid.uuid4()},
            business=self.business,
        )
        self.assertFalse(invalid.is_valid())

    def test_full_partial_and_same_method_payments(self):
        self.pay("40")
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, Decimal("60"))
        self.assertEqual(self.sale.payment_status, SalePaymentStatus.PARTIAL)
        self.pay("30")
        self.pay("30")
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, Decimal("0"))
        self.assertEqual(self.sale.payment_status, SalePaymentStatus.PAID)

    def test_overpayment_and_non_completed_sale_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.pay("101")
        self.sale.status = SaleStatusChoices.OPEN
        self.sale.completed_at = None
        self.sale.save()
        with self.assertRaises(ValidationError):
            self.pay("10")

    def test_split_setting_blocks_only_a_different_method(self):
        settings = self.business.pos_settings
        settings.allow_split_payments = False
        settings.save()
        self.pay("40")
        with self.assertRaises(ValidationError):
            self.pay("60", self.cash)
        self.pay("60", self.card)

    def test_idempotency_returns_same_payment_and_rejects_changed_payload(self):
        key = uuid.uuid4()
        first = self.pay("40", key=key)
        second = self.pay("40", key=key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Payment.objects.filter(idempotency_key=key).count(), 1)
        with self.assertRaises(ValidationError):
            self.pay("20", key=key)

    def test_other_business_method_and_sale_are_rejected(self):
        foreign = PaymentMethod.objects.create(
            business=self.other_business, name="B", code="card"
        )
        with self.assertRaises(ValidationError):
            self.pay("10", foreign)
        with self.assertRaises(ValidationError):
            register_sale_payment(
                business=self.other_business,
                sale_id=self.sale.pk,
                method_id=foreign.pk,
                amount=10,
                user=self.user,
                idempotency_key=uuid.uuid4(),
            )

    def test_pending_failed_cancelled_do_not_count_in_summary(self):
        for status in (
            PaymentStatusChoices.PENDING,
            PaymentStatusChoices.FAILED,
            PaymentStatusChoices.CANCELLED,
        ):
            Payment.objects.create(
                business=self.business,
                store=self.store,
                sale=self.sale,
                method=self.card,
                amount=Decimal("50"),
                status=status,
                processed_by=self.user,
                idempotency_key=uuid.uuid4(),
            )
        self.assertEqual(
            get_sale_payment_summary(business=self.business, sale_id=self.sale.pk)[
                "paid_total"
            ],
            0,
        )

    def test_refund_limits_idempotency_and_does_not_reopen_pending(self):
        self.pay("100")
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("100"),
        )
        key = uuid.uuid4()
        refund = register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.card.pk,
            amount=100,
            user=self.user,
            idempotency_key=key,
        )
        same = register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.card.pk,
            amount=100,
            user=self.user,
            idempotency_key=key,
        )
        self.assertEqual(refund.pk, same.pk)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, 0)
        self.assertEqual(self.sale.payment_status, SalePaymentStatus.REFUNDED)
        with self.assertRaises(ValidationError):
            register_refund(
                business=self.business,
                sale_return_id=returned.pk,
                method_id=self.card.pk,
                amount=1,
                user=self.user,
                idempotency_key=uuid.uuid4(),
            )

    def test_refund_requires_completed_return_refundable_method_and_real_money(self):
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            total_amount=Decimal("10"),
        )
        with self.assertRaises(ValidationError):
            register_refund(
                business=self.business,
                sale_return_id=returned.pk,
                method_id=self.card.pk,
                amount=10,
                user=self.user,
                idempotency_key=uuid.uuid4(),
            )
        returned.status = SaleReturnStatusChoices.COMPLETED
        returned.completed_at = self.sale.completed_at
        returned.save()
        self.card.allows_refund = False
        self.card.save()
        with self.assertRaises(ValidationError):
            register_refund(
                business=self.business,
                sale_return_id=returned.pk,
                method_id=self.card.pk,
                amount=10,
                user=self.user,
                idempotency_key=uuid.uuid4(),
            )

    def test_cancel_pending_is_idempotent_and_completed_is_terminal(self):
        pending = Payment.objects.create(
            business=self.business,
            store=self.store,
            sale=self.sale,
            method=self.card,
            amount=1,
            processed_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        self.assertEqual(
            cancel_payment(
                business=self.business, payment_id=pending.pk, user=self.user
            ).status,
            PaymentStatusChoices.CANCELLED,
        )
        cancel_payment(business=self.business, payment_id=pending.pk, user=self.user)
        completed = self.pay("10")
        with self.assertRaises(ValidationError):
            cancel_payment(
                business=self.business, payment_id=completed.pk, user=self.user
            )

    def test_explicit_customer_debt_is_linked_once_to_payment(self):
        customer = create_sales_customer(business=self.business)
        account = CustomerAccount.objects.create(
            business=self.business, customer=customer, credit_limit=Decimal("200")
        )
        self.sale.customer = customer
        self.sale.save()
        CustomerAccountService.create_charge(
            business=self.business,
            account=account,
            amount=100,
            user=self.user,
            sale=self.sale,
        )
        key = uuid.uuid4()
        payment = self.pay("100", key=key)
        self.pay("100", key=key)
        entry = CustomerAccountEntry.objects.get(entry_type=EntryTypeChoices.PAYMENT)
        self.assertEqual(entry.payment, payment)
        self.assertEqual(entry.sale, self.sale)
        account.refresh_from_db()
        self.assertEqual(account.balance, 0)


class PaymentModelTests(TestCase):
    def test_refund_requires_return_and_amount_positive(self):
        self.assertIn(PaymentTypeChoices.REFUND, PaymentTypeChoices.values)
        self.assertNotIn("refunded", PaymentStatusChoices.values)


class PaymentConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_concurrent_payments_cannot_overpay(self):
        business = create_sales_business()
        store = create_sales_store(business=business)
        user = create_sales_user(business=business)
        create_pos_settings(business=business)
        method = PaymentMethod.objects.create(
            business=business, name="Tarjeta", code="card"
        )
        sale = create_sale(
            business=business,
            store=store,
            opened_by=user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("100"),
        )

        def register(key):
            connections.close_all()
            try:
                register_sale_payment(
                    business=business,
                    sale_id=sale.pk,
                    method_id=method.pk,
                    amount=70,
                    user=user,
                    idempotency_key=key,
                )
                return True
            except ValidationError:
                return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(register, (uuid.uuid4(), uuid.uuid4())))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(
            Payment.objects.filter(
                sale=sale, status=PaymentStatusChoices.COMPLETED
            ).aggregate(total=Sum("amount"))["total"],
            Decimal("70"),
        )
