from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.cash_register.models import CashSession
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.reports.periods import ReportPeriod
from apps.reports.selectors import cash_session_summary, cash_sessions_summary
from apps.sales.tests.factories import create_sales_user


class CashReportTests(TestCase):
    def setUp(self):
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.register = create_cash_register(business=self.business, store=self.store)
        self.period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 9, 2, tzinfo=ZoneInfo("UTC")),
        )

    def _session(self, hour):
        return CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.register,
            opened_by=self.user,
            opened_at=datetime(2026, 9, 1, hour, tzinfo=ZoneInfo("UTC")),
            opening_amount=Decimal("20.00"),
            expected_cash_amount=Decimal("20.00"),
        )

    def test_open_session_preserves_not_counted_semantics(self):
        session = self._session(9)
        result = cash_session_summary(
            business=self.business, cash_session_id=session.pk
        )
        self.assertEqual(result["opening_amount"], Decimal("20.00"))
        self.assertEqual(result["net_physical_movement"], Decimal("0.00"))
        self.assertIsNone(result["counted_cash"])

    def test_sessions_summary_query_count_is_constant(self):
        self._session(9)
        with self.assertNumQueries(2):
            one = cash_sessions_summary(business=self.business, period=self.period)
        self._session(10)
        self._session(11)
        with self.assertNumQueries(2):
            many = cash_sessions_summary(business=self.business, period=self.period)
        self.assertEqual(len(one), 1)
        self.assertEqual(len(many), 3)
