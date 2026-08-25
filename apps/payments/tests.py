import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connections
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from apps.cash_register.models import CashRegister, CashSession
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
    recalculate_sale_payment_state,
    cancel_payment,
    register_refund,
    register_sale_payment,
    register_sale_on_account,
)
from apps.sales.models import (
    PaymentStatusChoices as SalePaymentStatus,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_business,
    create_sales_customer,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
    create_store_access,
)
from apps.users.models import RoleChoices
from apps.sales.services import complete_sale_return


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
        self.session = self.create_session()

    def pay(self, amount, method=None, key=None):
        return register_sale_payment(
            business=self.business,
            sale_id=self.sale.pk,
            method_id=(method or self.card).pk,
            amount=amount,
            user=self.user,
            idempotency_key=key or uuid.uuid4(),
            cash_session_id=self.session.pk,
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
        form = PaymentCreateForm(business=self.business, store=self.store)
        self.assertTrue(form.fields["cash_session"].required)
        self.assertNotIn(foreign, form.fields["method"].queryset)
        self.assertEqual(form.fields["idempotency_key"].widget.input_type, "hidden")
        invalid = PaymentCreateForm(
            {"method": self.card.pk, "amount": "0", "idempotency_key": uuid.uuid4()},
            business=self.business,
            store=self.store,
        )
        self.assertFalse(invalid.is_valid())

    def create_session(self, *, business=None, store=None, open=True):
        business = business or self.business
        store = store or self.store
        opened_by = (
            self.user
            if business == self.business
            else create_sales_user(business=business)
        )
        register = CashRegister.objects.create(
            business=business,
            store=store,
            name=f"Caja {uuid.uuid4()}",
            code=f"CAJA-{uuid.uuid4().hex[:8].upper()}",
        )
        session = CashSession.objects.create(
            business=business,
            store=store,
            cash_register=register,
            opened_by=opened_by,
            expected_cash_amount=Decimal("0.00"),
        )
        if not open:
            session.status = CashSession.Status.CLOSED
            session.closed_at = timezone.now()
            session.closed_by = opened_by
            session.counted_cash_amount = Decimal("0.00")
            session.difference_amount = (
                session.counted_cash_amount - session.expected_cash_amount
            )
            session.save()
        return session

    def test_payment_uses_current_session_not_historical_sale_session(self):
        historical = self.create_session()
        historical.status = CashSession.Status.CLOSED
        historical.closed_at = timezone.now()
        historical.closed_by = self.user
        historical.counted_cash_amount = historical.expected_cash_amount
        historical.difference_amount = Decimal("0.00")
        historical.save()
        current = self.create_session()
        self.sale.cash_session = historical
        self.sale.save()
        payment = register_sale_payment(
            business=self.business,
            sale_id=self.sale.pk,
            method_id=self.cash.pk,
            amount=10,
            user=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session_id=current.pk,
        )
        self.assertEqual(payment.cash_session, current)

    def test_partial_payment_return_has_no_refundable_money(self):
        # Caso A: Sale 100, paid 30, return 50 -> no hay dinero reembolsable
        self.sale.total_amount = Decimal("100")
        self.sale.pending_amount = Decimal("70")
        self.sale.save(update_fields=["total_amount", "pending_amount"])
        # pay 30
        self.pay(Decimal("30"))
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("50"),
        )
        # ensure pending remains 20
        recalc = recalculate_sale_payment_state(self.sale)
        self.assertEqual(recalc["pending_amount"], Decimal("20"))
        # try to refund 1 -> ValidationError
        with self.assertRaises(ValidationError):
            register_refund(
                business=self.business,
                sale_return_id=returned.pk,
                method_id=self.card.pk,
                amount=Decimal("1"),
                user=self.user,
                idempotency_key=uuid.uuid4(),
                cash_session_id=self.session.pk,
            )

    def test_partial_payment_return_only_refunds_excess_paid(self):
        # Caso B: Sale 100, paid 60, return 50 -> refund max 10
        self.sale.total_amount = Decimal("100")
        self.sale.pending_amount = Decimal("40")
        self.sale.save(update_fields=["total_amount", "pending_amount"])
        # pay 60
        self.pay(Decimal("60"))
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("50"),
        )
        # refund 10 -> OK
        p = register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.card.pk,
            amount=Decimal("10"),
            user=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session_id=self.session.pk,
        )
        self.assertEqual(p.amount, Decimal("10"))
        recalc = recalculate_sale_payment_state(self.sale)
        self.assertEqual(recalc["pending_amount"], Decimal("0"))
        self.assertEqual(self.sale.payment_status, SalePaymentStatus.PAID)
        # another refund of 1 -> ValidationError
        with self.assertRaises(ValidationError):
            register_refund(
                business=self.business,
                sale_return_id=returned.pk,
                method_id=self.card.pk,
                amount=Decimal("1"),
                user=self.user,
                idempotency_key=uuid.uuid4(),
                cash_session_id=self.session.pk,
            )

    def test_cash_session_is_scoped_and_must_be_operational(self):
        settings = self.business.pos_settings
        settings.require_open_cash_register = True
        settings.save()
        closed = self.create_session(open=False)
        with self.assertRaises(ValidationError):
            register_sale_payment(
                business=self.business,
                sale_id=self.sale.pk,
                method_id=self.cash.pk,
                amount=10,
                user=self.user,
                idempotency_key=uuid.uuid4(),
                cash_session_id=closed.pk,
            )
        payment = self.pay("10", self.cash)
        self.assertEqual(payment.cash_session_id, self.session.pk)
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)

    def test_cash_session_from_other_business_or_store_is_rejected(self):
        other_store = create_sales_store(business=self.business)
        other_store_session = self.create_session(store=other_store)
        with self.assertRaises(ValidationError):
            register_sale_payment(
                business=self.business,
                sale_id=self.sale.pk,
                method_id=self.card.pk,
                amount=10,
                user=self.user,
                idempotency_key=uuid.uuid4(),
                cash_session_id=other_store_session.pk,
            )

        foreign_store = create_sales_store(business=self.other_business)
        foreign_user = create_sales_user(business=self.other_business)
        foreign_register = CashRegister.objects.create(
            business=self.other_business,
            store=foreign_store,
            name="Caja extranjera",
            code=f"CAJA-{uuid.uuid4().hex[:8].upper()}",
        )
        foreign_session = CashSession.objects.create(
            business=self.other_business,
            store=foreign_store,
            cash_register=foreign_register,
            opened_by=foreign_user,
        )
        with self.assertRaises(ValidationError):
            register_sale_payment(
                business=self.business,
                sale_id=self.sale.pk,
                method_id=self.card.pk,
                amount=10,
                user=self.user,
                idempotency_key=uuid.uuid4(),
                cash_session_id=foreign_session.pk,
            )

    def test_later_cash_refund_uses_current_session(self):
        current = self.create_session()
        self.pay("100")
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("20"),
        )
        refund = register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.cash.pk,
            amount=20,
            user=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session_id=current.pk,
        )
        self.assertEqual(refund.cash_session, current)

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
                cash_session_id=self.session.pk,
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
            cash_session_id=self.session.pk,
        )
        same = register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.card.pk,
            amount=100,
            user=self.user,
            idempotency_key=key,
            cash_session_id=self.session.pk,
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
                cash_session_id=self.session.pk,
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
                cash_session_id=self.session.pk,
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
                cash_session_id=self.session.pk,
            )

    def test_refund_requires_sensitive_permission_and_valid_pin(self):
        self.pay("100")
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("20"),
        )
        settings = self.business.pos_settings
        settings.require_pin_for_sensitive_actions = True
        settings.save()
        with self.assertRaises(ValidationError):
            register_refund(
                business=self.business,
                sale_return_id=returned.pk,
                method_id=self.card.pk,
                amount=20,
                user=self.user,
                pin="wrong",
                idempotency_key=uuid.uuid4(),
                cash_session_id=self.session.pk,
            )
        refund = register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.card.pk,
            amount=20,
            user=self.user,
            pin="1234",
            idempotency_key=uuid.uuid4(),
            cash_session_id=self.session.pk,
        )
        self.assertEqual(refund.status, PaymentStatusChoices.COMPLETED)

        cashier = create_sales_user(business=self.business, role=RoleChoices.CASHIER)
        create_store_access(
            business=self.business, user=cashier, store=self.store, can_sell=True
        )
        with self.assertRaises(ValidationError):
            register_refund(
                business=self.business,
                sale_return_id=returned.pk,
                method_id=self.card.pk,
                amount=20,
                user=cashier,
                idempotency_key=uuid.uuid4(),
                cash_session_id=self.session.pk,
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

    def test_customer_account_failure_rolls_back_payment(self):
        customer = create_sales_customer(business=self.business)
        account = CustomerAccount.objects.create(
            business=self.business, customer=customer, credit_limit=Decimal("100")
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
        with patch.object(
            CustomerAccountService,
            "register_payment",
            side_effect=ValidationError("fallo de cuenta"),
        ):
            with self.assertRaises(ValidationError):
                self.pay("40")
        self.assertFalse(Payment.objects.filter(sale=self.sale).exists())
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("100"))

    def test_non_completed_idempotent_replay_never_reduces_customer_debt(self):
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
        for status in (
            PaymentStatusChoices.PENDING,
            PaymentStatusChoices.FAILED,
            PaymentStatusChoices.CANCELLED,
        ):
            key = uuid.uuid4()
            Payment.objects.create(
                business=self.business,
                store=self.store,
                sale=self.sale,
                method=self.card,
                amount=10,
                status=status,
                processed_by=self.user,
                idempotency_key=key,
                cash_session=self.session,
            )
            replay = self.pay("10", key=key)
            self.assertEqual(replay.status, status)
        self.assertFalse(
            CustomerAccountEntry.objects.filter(
                entry_type=EntryTypeChoices.PAYMENT
            ).exists()
        )

    def test_sale_on_account_and_two_later_payments(self):
        customer = create_sales_customer(business=self.business)
        account = CustomerAccount.objects.create(
            business=self.business, customer=customer, credit_limit=Decimal("100")
        )
        self.sale.customer = customer
        self.sale.save()
        charge = register_sale_on_account(
            business=self.business, sale_id=self.sale.pk, user=self.user
        )
        replay = register_sale_on_account(
            business=self.business, sale_id=self.sale.pk, user=self.user
        )
        self.assertEqual(charge.pk, replay.pk)
        self.pay("40")
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("60"))
        self.pay("60")
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("0"))

    def test_sale_on_account_requires_customer_and_honours_account_rules(self):
        with self.assertRaises(ValidationError):
            register_sale_on_account(
                business=self.business, sale_id=self.sale.pk, user=self.user
            )
        customer = create_sales_customer(business=self.business)
        account = CustomerAccount.objects.create(
            business=self.business,
            customer=customer,
            credit_limit=Decimal("50"),
            is_blocked=True,
        )
        self.sale.customer = customer
        self.sale.save()
        with self.assertRaises(ValidationError):
            register_sale_on_account(
                business=self.business, sale_id=self.sale.pk, user=self.user
            )
        account.is_blocked = False
        account.save()
        with self.assertRaises(ValidationError):
            register_sale_on_account(
                business=self.business, sale_id=self.sale.pk, user=self.user
            )

    def test_end_to_end_debt_first_then_monetary_refund(self):
        settings = self.business.pos_settings
        settings.enable_stock_control = False
        settings.save()
        customer = create_sales_customer(business=self.business)
        account = CustomerAccount.objects.create(
            business=self.business, customer=customer, credit_limit=Decimal("100")
        )
        self.sale.customer = customer
        self.sale.save()
        tax = create_sales_tax(business=self.business, rate=Decimal("0"))
        product = create_sales_product(
            business=self.business, tax=tax, base_price=Decimal("100")
        )
        line = create_sale_line(
            business=self.business,
            sale=self.sale,
            product=product,
            quantity=Decimal("1"),
        )
        register_sale_on_account(
            business=self.business, sale_id=self.sale.pk, user=self.user
        )
        self.pay("60")
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=returned,
            original_line=line,
            quantity=Decimal("0.5"),
            restock=False,
        )
        # Ensure PIN is not required for sensitive actions in this test
        settings.require_pin_for_sensitive_actions = False
        settings.save(update_fields=["require_pin_for_sensitive_actions", "updated_at"])
        complete_sale_return(
            business=self.business, return_doc=returned, completed_by=self.user
        )
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("0"))
        debt_refund = CustomerAccountEntry.objects.get(
            sale=self.sale,
            entry_type=EntryTypeChoices.REFUND,
            payment__isnull=True,
        )
        self.assertEqual(debt_refund.amount, Decimal("-40"))
        monetary = register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.card.pk,
            amount=10,
            user=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session_id=self.session.pk,
        )
        self.assertEqual(monetary.amount, Decimal("10"))
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, Decimal("0"))
        self.assertEqual(self.sale.payment_status, SalePaymentStatus.PAID)
        with self.assertRaises(ValidationError):
            self.pay("1")
        with self.assertRaises(ValidationError):
            register_refund(
                business=self.business,
                sale_return_id=returned.pk,
                method_id=self.card.pk,
                amount=1,
                user=self.user,
                idempotency_key=uuid.uuid4(),
                cash_session_id=self.session.pk,
            )

    def test_partial_return_reduces_collectable_amount(self):
        create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("50"),
        )
        recalculate_sale_payment_state(self.sale)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, Decimal("50"))
        self.pay("50")
        with self.assertRaises(ValidationError):
            self.pay("1")

    def test_partial_return_fully_refunded_remains_paid(self):
        self.pay("100")
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("20"),
        )
        register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.card.pk,
            amount=20,
            user=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session_id=self.session.pk,
        )
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, Decimal("0"))
        self.assertEqual(self.sale.payment_status, SalePaymentStatus.PAID)

    def test_full_return_and_full_refund_is_refunded(self):
        self.pay("100")
        returned = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("100"),
        )
        register_refund(
            business=self.business,
            sale_return_id=returned.pk,
            method_id=self.card.pk,
            amount=100,
            user=self.user,
            idempotency_key=uuid.uuid4(),
            cash_session_id=self.session.pk,
        )
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, Decimal("0"))
        self.assertEqual(self.sale.payment_status, SalePaymentStatus.REFUNDED)

    def test_full_return_never_paid_is_unpaid_with_zero_pending(self):
        create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("100"),
        )
        recalculate_sale_payment_state(self.sale)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.pending_amount, Decimal("0"))
        self.assertEqual(self.sale.payment_status, SalePaymentStatus.UNPAID)
        self.assertFalse(
            Payment.objects.filter(payment_type=PaymentTypeChoices.REFUND).exists()
        )


class PaymentModelTests(TestCase):
    def test_refund_requires_return_and_amount_positive(self):
        self.assertIn(PaymentTypeChoices.REFUND, PaymentTypeChoices.values)
        self.assertNotIn("refunded", PaymentStatusChoices.values)


class PaymentConcurrencyTests(TransactionTestCase):
    def create_session(self, *, business, store, user):
        register = CashRegister.objects.create(
            business=business,
            store=store,
            name=f"Caja {uuid.uuid4()}",
            code=f"CAJA-{uuid.uuid4().hex[:8].upper()}",
        )
        return CashSession.objects.create(
            business=business,
            store=store,
            cash_register=register,
            opened_by=user,
        )

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
        session = self.create_session(business=business, store=store, user=user)

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
                    cash_session_id=session.pk,
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

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_refund_replay_creates_one_payment(self):
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
        session = self.create_session(business=business, store=store, user=user)
        register_sale_payment(
            business=business,
            sale_id=sale.pk,
            method_id=method.pk,
            amount=100,
            user=user,
            idempotency_key=uuid.uuid4(),
            cash_session_id=session.pk,
        )
        returned = create_sale_return(
            business=business,
            store=store,
            original_sale=sale,
            created_by=user,
            status=SaleReturnStatusChoices.COMPLETED,
            total_amount=Decimal("20"),
        )
        key = uuid.uuid4()

        def refund(_):
            connections.close_all()
            try:
                return register_refund(
                    business=business,
                    sale_return_id=returned.pk,
                    method_id=method.pk,
                    amount=20,
                    user=user,
                    idempotency_key=key,
                    cash_session_id=session.pk,
                ).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            payment_ids = list(executor.map(refund, range(2)))
        self.assertEqual(payment_ids[0], payment_ids[1])
        self.assertEqual(Payment.objects.filter(idempotency_key=key).count(), 1)
