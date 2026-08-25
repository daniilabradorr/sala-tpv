from decimal import Decimal
import uuid

from django.db import transaction
from django.test import TestCase

from apps.cash_register.models import CashSession
from apps.cash_register.services import register_payment_cash_movement
from apps.cash_register.selectors import (
    get_cash_session_counts,
    get_cash_session_movements,
    get_cash_session_payment_summary,
    get_open_cash_session,
)
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.sales.models import SaleReturnStatusChoices, SaleStatusChoices
from apps.sales.tests.factories import create_sale, create_sale_return
from apps.users.tests.factories import create_user


class CashRegisterSelectorsTests(TestCase):
    def setUp(self):
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business)
        self.user = create_user(business=self.business, email="selector@test.com")
        register = create_cash_register(business=self.business, store=self.store)
        self.session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
            opening_amount=Decimal("10"),
            expected_cash_amount=Decimal("10"),
        )

    def test_read_selectors_are_session_scoped(self):
        self.assertEqual(
            get_open_cash_session(
                business=self.business,
                store=self.store,
                cash_register=self.session.cash_register,
            ),
            self.session,
        )
        self.assertFalse(
            get_cash_session_movements(
                business=self.business, store=self.store, cash_session=self.session
            ).exists()
        )
        self.assertFalse(
            get_cash_session_counts(
                business=self.business, store=self.store, cash_session=self.session
            ).exists()
        )

    def test_payment_summary_includes_non_cash_without_changing_expected(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("50"),
        )
        card = PaymentMethod.objects.create(
            business=self.business, name="Tarjeta", code="card"
        )
        Payment.objects.create(
            business=self.business,
            store=self.store,
            sale=sale,
            method=card,
            cash_session=self.session,
            amount=Decimal("50"),
            status=PaymentStatusChoices.COMPLETED,
            processed_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        summary = get_cash_session_payment_summary(
            business=self.business, store=self.store, cash_session=self.session
        )
        self.assertEqual(summary[0]["payments"], Decimal("50"))
        self.assertEqual(summary[0]["net"], Decimal("50"))
        self.session.refresh_from_db()
        self.assertEqual(self.session.expected_cash_amount, Decimal("10"))

    def test_complete_payment_summary_and_physical_expected(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("1000"),
        )
        methods = {
            code: PaymentMethod.objects.create(
                business=self.business, name=code.title(), code=code
            )
            for code in ("cash", "card", "bizum", "transfer")
        }

        def payment(code, amount, payment_type=PaymentTypeChoices.SALE_PAYMENT):
            returned = None
            if payment_type == PaymentTypeChoices.REFUND:
                returned = create_sale_return(
                    business=self.business,
                    store=self.store,
                    original_sale=sale,
                    created_by=self.user,
                    status=SaleReturnStatusChoices.COMPLETED,
                    total_amount=amount,
                )
            return Payment.objects.create(
                business=self.business,
                store=self.store,
                sale=sale,
                method=methods[code],
                cash_session=self.session,
                sale_return=returned,
                payment_type=payment_type,
                amount=amount,
                status=PaymentStatusChoices.COMPLETED,
                processed_by=self.user,
                idempotency_key=uuid.uuid4(),
            )

        cash_sale = payment("cash", Decimal("200"))
        cash_refund = payment("cash", Decimal("20"), PaymentTypeChoices.REFUND)
        payment("card", Decimal("500"))
        payment("card", Decimal("50"), PaymentTypeChoices.REFUND)
        payment("bizum", Decimal("80"))
        payment("transfer", Decimal("40"))
        with transaction.atomic():
            register_payment_cash_movement(payment=cash_sale)
            register_payment_cash_movement(payment=cash_refund)

        summary = {
            row["method__code"]: row
            for row in get_cash_session_payment_summary(
                business=self.business, store=self.store, cash_session=self.session
            )
        }
        self.assertEqual(
            {
                code: (row["payments"], row["refunds"], row["net"])
                for code, row in summary.items()
            },
            {
                "cash": (Decimal("200"), Decimal("20"), Decimal("180")),
                "card": (Decimal("500"), Decimal("50"), Decimal("450")),
                "bizum": (Decimal("80"), Decimal("0"), Decimal("80")),
                "transfer": (Decimal("40"), Decimal("0"), Decimal("40")),
            },
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.expected_cash_amount, Decimal("190.00"))
