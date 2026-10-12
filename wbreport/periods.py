"""Date ranges for each report. All days are UTC days, the PostHog project's timezone (5:30 AM to 5:30 AM IST)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

DAY = dt.timedelta(days=1)


@dataclass(frozen=True)
class Period:
    start: dt.date  # first day
    end: dt.date    # the day after the last day (exclusive)

    @property
    def last(self) -> dt.date:
        return self.end - DAY

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def dates(self) -> list[dt.date]:
        return [self.start + DAY * i for i in range(self.days)]


class PeriodError(ValueError):
    pass


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def parse_date(text: str | None) -> dt.date | None:
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text.strip())
    except ValueError:
        raise PeriodError(f"'{text}' isn't a date. Use YYYY-MM-DD, for example 2026-10-08.") from None


def daily_day(today: dt.date, date: dt.date | None = None) -> dt.date:
    """The day to report on: yesterday by default."""
    day = date or today - DAY
    if day >= today:
        raise PeriodError(f"{day} isn't over yet in UTC. Pick {today - DAY} or earlier.")
    return day


def _clamp(cur: Period, today: dt.date) -> tuple[Period, bool]:
    """A period that hasn't finished becomes a preview that ends yesterday."""
    if cur.start >= today:
        raise PeriodError(f"The period starting {cur.start} has no complete days yet.")
    if cur.end > today:
        return Period(cur.start, today), True
    return cur, False


def week_periods(today: dt.date, date: dt.date | None = None) -> tuple[Period, Period, bool]:
    """The Monday-to-Sunday week containing `date` (default: the last complete week) and the week before.

    Returns (week, previous week, preview) where preview means the week isn't over yet.
    """
    anchor = date or today - DAY * (today.weekday() + 1)  # last Sunday
    start = anchor - DAY * anchor.weekday()
    cur, preview = _clamp(Period(start, start + DAY * 7), today)
    return cur, Period(start - DAY * 7, start), preview


def month_periods(today: dt.date, date: dt.date | None = None) -> tuple[Period, Period, bool]:
    """The calendar month containing `date` (default: the last complete month) and the month before."""
    anchor = date or today.replace(day=1) - DAY
    start = anchor.replace(day=1)
    end = (start + DAY * 32).replace(day=1)
    prev = Period((start - DAY).replace(day=1), start)
    cur, preview = _clamp(Period(start, end), today)
    return cur, prev, preview
