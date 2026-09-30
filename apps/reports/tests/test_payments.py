from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.cash_register.models import CashRegister, CashSession
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.reports.periods import ReportPeriod
from apps.reports.selectors import payment_summary, payments_by_method
from apps.sales.models import SaleReturnStatusChoices, SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_return,
    create_sales_business,
    create_sales_store,
    create_sales_user,
)

UTC = ZoneInfo("UTC")


class PaymentReportTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.register = CashRegister.objects.create(
            business=self.business, store=self.store, name="Caja", code="MAIN"
        )
        self.session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.register,
            opened_by=self.user,
        )
        self.sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("100.00"),
            cash_register=self.register,
            cash_session=self.session,
        )
        self.methods = {
            code: PaymentMethod.objects.create(
                business=self.business, name=name, code=code
            )
            for code, name in (
                ("cash", "Efectivo"),
                ("card", "Tarjeta"),
                ("bizum", "Bizum"),
                ("transfer", "Transferencia"),
            )
        }
        self.period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 3, tzinfo=UTC)
        )

    def _payment(
        self,
        *,
        code="cash",
        payment_type=PaymentTypeChoices.SALE_PAYMENT,
        status=PaymentStatusChoices.COMPLETED,
        amount="10.00",
        when=None,
    ):
        sale_return = None
        if payment_type == PaymentTypeChoices.REFUND:
            sale_return = create_sale_return(
                business=self.business,
                store=self.store,
                original_sale=self.sale,
                created_by=self.user,
                status=SaleReturnStatusChoices.DRAFT,
            )
        payment = Payment.objects.create(
            business=self.business,
            store=self.store,
            sale=self.sale,
            method=self.methods[code],
            cash_session=self.session,
            sale_return=sale_return,
            payment_type=payment_type,
            amount=Decimal(amount),
            status=status,
            processed_by=self.user,
            idempotency_key=uuid4(),
        )
        Payment.objects.filter(pk=payment.pk).update(
            created_at=when or datetime(2026, 9, 1, 10, tzinfo=UTC)
        )
        return payment

    def test_summary_completed_sale_payments_and_refunds_with_counts(self):
        self._payment(amount="30")
        self._payment(code="card", amount="20")
        self._payment(payment_type=PaymentTypeChoices.REFUND, amount="12")
        for status in (
            PaymentStatusChoices.PENDING,
            PaymentStatusChoices.FAILED,
            PaymentStatusChoices.CANCELLED,
        ):
            self._payment(status=status, amount="99")
        self.assertEqual(
            payment_summary(business=self.business, period=self.period),
            {
                "collected_amount": Decimal("50"),
                "refunded_amount": Decimal("12"),
                "payment_count": 2,
                "refund_count": 1,
                "net_amount": Decimal("38"),
            },
        )

    def test_by_method_uses_real_methods_orders_and_omits_unused(self):
        self._payment(code="transfer", amount="40")
        self._payment(code="cash", amount="20")
        self._payment(code="cash", payment_type=PaymentTypeChoices.REFUND, amount="5")
        self._payment(code="bizum", amount="10")
        rows = payments_by_method(business=self.business, period=self.period)
        self.assertEqual(
            [row["method_code"] for row in rows], ["bizum", "cash", "transfer"]
        )
        cash = rows[1]
        self.assertEqual(
            (cash["collected_amount"], cash["refunded_amount"], cash["net_amount"]),
            (Decimal("20"), Decimal("5"), Decimal("15")),
        )
        self.assertEqual((cash["payment_count"], cash["refund_count"]), (1, 1))
        self.assertNotIn("card", {row["method_code"] for row in rows})
        self.assertNotIn("other", {row["method_code"] for row in rows})

    def test_created_at_half_open_bounds(self):
        self._payment(amount="10", when=self.period.start)
        self._payment(amount="100", when=self.period.end)
        self._payment(
            payment_type=PaymentTypeChoices.REFUND,
            amount="3",
            when=datetime(2026, 9, 2, tzinfo=UTC),
        )
        result = payment_summary(business=self.business, period=self.period)
        self.assertEqual(result["collected_amount"], Decimal("10"))
        self.assertEqual(result["refunded_amount"], Decimal("3"))

    def test_store_filter_business_isolation_and_foreign_store_rejection(self):
        self._payment(amount="10")
        second_store = create_sales_store(business=self.business)
        second_register = CashRegister.objects.create(
            business=self.business, store=second_store, name="Caja 2", code="SECOND"
        )
        second_session = CashSession.objects.create(
            business=self.business,
            store=second_store,
            cash_register=second_register,
            opened_by=self.user,
        )
        second_sale = create_sale(
            business=self.business,
            store=second_store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("20"),
            cash_register=second_register,
            cash_session=second_session,
        )
        second_payment = Payment.objects.create(
            business=self.business,
            store=second_store,
            sale=second_sale,
            method=self.methods["cash"],
            cash_session=second_session,
            amount=Decimal("20"),
            status=PaymentStatusChoices.COMPLETED,
            processed_by=self.user,
            idempotency_key=uuid4(),
        )
        Payment.objects.filter(pk=second_payment.pk).update(
            created_at=datetime(2026, 9, 1, 10, tzinfo=UTC)
        )
        self.assertEqual(
            payment_summary(
                business=self.business, period=self.period, store=self.store
            )["collected_amount"],
            Decimal("10"),
        )
        other_business = create_sales_business()
        foreign_store = create_sales_store(business=other_business)
        with self.assertRaisesRegex(ValueError, "store must belong"):
            payment_summary(
                business=self.business, period=self.period, store=foreign_store
            )
