"""Tests for report calendar periods."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from django.utils import timezone

from apps.reports.periods import (
    ReportPeriod,
    report_period_for_day,
    report_period_from_dates,
)


class ReportPeriodTests(SimpleTestCase):
    def test_accepts_valid_aware_bounds(self):
        tz = ZoneInfo("UTC")
        start = datetime(2026, 9, 1, tzinfo=tz)
        end = datetime(2026, 9, 2, tzinfo=tz)

        period = ReportPeriod(start=start, end=end)

        self.assertEqual(period.start, start)
        self.assertEqual(period.end, end)

    def test_rejects_naive_start(self):
        with self.assertRaisesRegex(ValueError, "start must be timezone-aware"):
            ReportPeriod(
                start=datetime(2026, 9, 1),
                end=datetime(2026, 9, 2, tzinfo=ZoneInfo("UTC")),
            )

    def test_rejects_naive_end(self):
        with self.assertRaisesRegex(ValueError, "end must be timezone-aware"):
            ReportPeriod(
                start=datetime(2026, 9, 1, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 9, 2),
            )

    def test_rejects_equal_bounds(self):
        bound = datetime(2026, 9, 1, tzinfo=ZoneInfo("UTC"))

        with self.assertRaisesRegex(ValueError, "earlier than end"):
            ReportPeriod(start=bound, end=bound)

    def test_rejects_reversed_bounds(self):
        tz = ZoneInfo("UTC")

        with self.assertRaisesRegex(ValueError, "earlier than end"):
            ReportPeriod(
                start=datetime(2026, 9, 2, tzinfo=tz),
                end=datetime(2026, 9, 1, tzinfo=tz),
            )

    def test_inclusive_dates_become_half_open_local_bounds(self):
        tz = ZoneInfo("Europe/Madrid")

        period = report_period_from_dates(
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 15),
            tz=tz,
        )

        self.assertEqual(period.start, datetime(2026, 9, 1, tzinfo=tz))
        self.assertEqual(period.end, datetime(2026, 9, 16, tzinfo=tz))

    def test_for_day_uses_local_midnights(self):
        tz = ZoneInfo("Europe/Madrid")

        period = report_period_for_day(day=date(2026, 9, 15), tz=tz)

        self.assertEqual(period.start, datetime(2026, 9, 15, tzinfo=tz))
        self.assertEqual(period.end, datetime(2026, 9, 16, tzinfo=tz))

    def test_uses_active_timezone_by_default(self):
        tz = ZoneInfo("Atlantic/Canary")

        with timezone.override(tz):
            period = report_period_for_day(day=date(2026, 9, 15))

        self.assertEqual(period.start.tzinfo, tz)
        self.assertEqual(period.end.tzinfo, tz)

    def test_dst_day_is_a_local_calendar_day_not_24_utc_hours(self):
        madrid = ZoneInfo("Europe/Madrid")

        with timezone.override(madrid):
            period = report_period_for_day(day=date(2026, 3, 29))

        self.assertEqual(period.start, datetime(2026, 3, 29, tzinfo=madrid))
        self.assertEqual(period.end, datetime(2026, 3, 30, tzinfo=madrid))
        utc_elapsed = period.end.astimezone(ZoneInfo("UTC")) - period.start.astimezone(
            ZoneInfo("UTC")
        )
        self.assertEqual(utc_elapsed, timedelta(hours=23))
