"""
Projected MTD / YTD — ONE definition, shared by every report.

The rule (Manav's, 9 Aug 2026):

    Projected YTD = YTD achieved  / operational days in the year  x 365
    Projected MTD = MTD achieved  / operational days in the month x days in that month

"Operational days" = the days the store has actually been open in the period,
counted inclusively from the later of the period start and its opening date
(DOO) through the as-of date. A store that opened mid-year is therefore rated on
the days it has traded, not on the whole period.

★ THE MONTH MULTIPLIER IS THE REAL CALENDAR MONTH, NOT A CONSTANT (Manav,
10 Aug). A flat 30 understated every 31-day month by 3.3% and overstated
February by 7%, and the error moved with the calendar, so the same run-rate
projected differently depending on which month you asked in. The year multiplier
stays a flat 365; if a leap year ever needs handling it belongs here too.

This module exists because this rule previously lived in FOUR copies (two in
portfolio_loader, two in loader) which drifted apart — the VFL sheet annualised
South over a 347-day window while the portfolio pack used 365, so the same store
projected two different numbers depending on which tab you opened. Any new
report needing a projection must call `project()` rather than re-deriving it.
"""

from __future__ import annotations

import calendar

# The year multiplier is flat; the month multiplier is not — see the docstring.
YEAR_DAYS = 365.0


def month_days(asof) -> float:
    """Days in the calendar month `asof` falls in: 31, 30 or 28/29."""
    return float(calendar.monthrange(asof.year, asof.month)[1])


def operational_days(start, asof) -> int:
    """Days open across [start, asof], inclusive. Never below 1, so a store on
    its very first day projects off one day rather than dividing by zero."""
    return max((asof - start).days + 1, 1)


def project(achieved: float, start, asof, closed=None,
            period_days: float = YEAR_DAYS) -> float:
    """`achieved / operational days x period_days`.

    A CLOSED store is NOT annualised: its period is over, so the projection is
    frozen at what it actually took (Manav's call, 7 Aug — Planet Fashion was
    otherwise projecting 972,668 against 338,435 actually taken, ~2.9x).

    `start`   period start, already clamped to the store's DOO by the caller
    `asof`    the as-of / generation date
    `closed`  closure date or None
    """
    if closed is not None and closed <= asof:
        return achieved
    return achieved * period_days / operational_days(start, asof)


def project_ytd(achieved: float, fy_start, doo, asof, closed=None) -> float:
    """Projected YTD: run-rate since the later of FY-start and opening x 365."""
    return project(achieved, max(fy_start, doo), asof, closed, YEAR_DAYS)


def project_mtd(achieved: float, asof, doo=None, closed=None) -> float:
    """Projected MTD: run-rate since the later of the 1st and opening, scaled to
    the length of the month actually being projected."""
    month_start = asof.replace(day=1)
    start = month_start if doo is None else max(month_start, doo)
    return project(achieved, start, asof, closed, month_days(asof))
