"""Calendar-period primitives shared by report selectors."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from django.utils import timezone


@dataclass(frozen=True, slots=True)
class ReportPeriod:
    """A timezone-aware half-open interval: ``[start, end)``."""

    start: datetime
    end: datetime

    def __post_init__(self):
        if timezone.is_naive(self.start):
            raise ValueError("ReportPeriod start must be timezone-aware.")
        if timezone.is_naive(self.end):
            raise ValueError("ReportPeriod end must be timezone-aware.")
        if self.start >= self.end:
            raise ValueError("ReportPeriod start must be earlier than end.")


def _local_midnight(day: date, tz: tzinfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def report_period_from_dates(
    *, date_from: date, date_to: date, tz: tzinfo | None = None
) -> ReportPeriod:
    """Convert inclusive business dates to local half-open datetime bounds."""

    if date_from > date_to:
        raise ValueError("date_from must be on or before date_to.")

    effective_tz = tz or timezone.get_current_timezone()
    return ReportPeriod(
        start=_local_midnight(date_from, effective_tz),
        end=_local_midnight(date_to + timedelta(days=1), effective_tz),
    )


def report_period_for_day(
    *, day: date | None = None, tz: tzinfo | None = None
) -> ReportPeriod:
    """Return the local calendar-day interval for ``day`` (or today)."""

    effective_tz = tz or timezone.get_current_timezone()
    effective_day = (
        day if day is not None else timezone.localdate(timezone=effective_tz)
    )
    return report_period_from_dates(
        date_from=effective_day,
        date_to=effective_day,
        tz=effective_tz,
    )
