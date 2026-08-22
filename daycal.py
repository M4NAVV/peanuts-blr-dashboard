"""Last year's month, day by day, as a calendar.

★ WHY THIS EXISTS. Manav, 22 Aug: *"a tab where i can see the last year month
sales for everyday, like a heatmap … i will be selecting the store i want to
see, and then i will be able to view the entire sales data for last year for
the month we are in."*

The point is to know what is COMING. Halfway through a month, the useful
question is not "how are we doing" — the dashboard answers that everywhere —
but "what did the rest of this month look like last year". A calendar shows it
in the shape a manager already thinks in: which Saturdays were big, where the
dead run was, whether the month ends with a rush.

★ WHY A CALENDAR AND NOT A LINE. Sales here are dominated by day of week —
weekends run about twice a weekday across the estate. On a line chart that
sawtooth drowns everything else. Laid out as a calendar, the weekend column IS
a column, so what is left to see is the part that is not the weekly cycle.
"""

from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def month_window(asof, years_back: int = 1):
    """The same calendar month, `years_back` years earlier: (start, end)."""
    asof = pd.Timestamp(asof)
    y, m = asof.year - years_back, asof.month
    start = pd.Timestamp(y, m, 1)
    end = pd.Timestamp(y, m, calendar.monthrange(y, m)[1])
    return start, end


def daily_series(df, date_col, value_col, start, end, store_col=None, store=None):
    """One row per calendar day in the window, zero-filled.

    ★ ZERO-FILLED ON PURPOSE. A day with no rows is a day the store took
    nothing — a holiday, a closure — and that is exactly what a reader needs to
    see. Left absent it would silently vanish from the grid and the month would
    look like it had 27 days.
    """
    d = df
    if store_col and store and store != "All stores":
        d = d[d[store_col] == store]
    d = d[(d[date_col] >= start) & (d[date_col] <= end)]
    s = d.groupby(d[date_col].dt.normalize())[value_col].sum()
    idx = pd.date_range(start, end, freq="D")
    return s.reindex(idx, fill_value=0.0)


def to_grid(series):
    """Lay a daily series out as weeks x weekdays, the way a wall calendar reads.

    Returns (values, labels) — values for the colour, labels for the text, both
    indexed by week-of-month with Mon..Sun columns. Cells outside the month are
    NaN / blank rather than zero, so an empty corner cannot be read as a day
    that took nothing.
    """
    if series.empty:
        return pd.DataFrame(), pd.DataFrame()
    f = pd.DataFrame({"date": series.index, "val": series.values})
    f["dow"] = f.date.dt.weekday                       # Mon=0
    first = f.date.iloc[0]
    f["week"] = ((f.date - first).dt.days + first.weekday()) // 7

    vals = pd.DataFrame(np.nan, index=sorted(f.week.unique()), columns=WEEKDAYS)
    labs = pd.DataFrame("", index=sorted(f.week.unique()), columns=WEEKDAYS)
    for r in f.itertuples():
        vals.loc[r.week, WEEKDAYS[r.dow]] = r.val
        labs.loc[r.week, WEEKDAYS[r.dow]] = f"{r.date.day}\n{_short(r.val)}"
    vals.index = [f"Week {i+1}" for i in range(len(vals))]
    labs.index = vals.index
    return vals, labs


def _short(v) -> str:
    """Money at a glance. A calendar cell has no room for digit grouping."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if v == 0:
        return "—"
    a = abs(v)
    if a >= 1e7:
        return f"{v/1e7:,.2f} Cr"
    if a >= 1e5:
        return f"{v/1e5:,.2f} L"
    if a >= 1e3:
        return f"{v/1e3:,.0f} K"
    return f"{v:,.0f}"


def summary(series, same_days: int | None = None) -> dict:
    """Totals for the month, and for a like-for-like slice of it.

    `same_days` compares only the first N days, because a part-month measured
    against a whole one is the commonest way to make this year look broken.
    """
    s = series
    out = {
        "total": float(s.sum()),
        "days": int((s > 0).sum()),
        "best_day": s.idxmax() if len(s) and s.max() > 0 else None,
        "best_val": float(s.max()) if len(s) else 0.0,
        "worst_open": None, "worst_val": None,
        "weekend": float(s[s.index.weekday >= 5].sum()),
        "weekday": float(s[s.index.weekday < 5].sum()),
    }
    open_days = s[s > 0]
    if len(open_days):
        out["worst_open"] = open_days.idxmin()
        out["worst_val"] = float(open_days.min())
    if same_days:
        out["same_days_total"] = float(s.iloc[:same_days].sum())
        out["same_days"] = same_days
    return out


# --------------------------------------------------------------------------- #
#  Rendering — an actual calendar, in the house's inline-HTML idiom
# --------------------------------------------------------------------------- #
MAROON = "#7A1F2B"
INK = "#2B2B2B"
MUTED = "#8A8A8A"
LINE = "#ECE4D6"
GREEN = "#137A3A"
RED = "#C0143C"


def _tint(t: float) -> str:
    """White through to the house maroon. `t` in [0,1].

    Sequential, not diverging: there is no meaningful midpoint in a day's
    takings, only more and less.
    """
    t = 0.0 if t is None or (isinstance(t, float) and np.isnan(t)) else max(0.0, min(1.0, t))
    r = int(255 + (122 - 255) * t)
    g = int(255 + (31 - 255) * t)
    b = int(255 + (43 - 255) * t)
    return f"rgb({r},{g},{b})"


def _ink_on(t: float) -> str:
    """Text has to stay readable as the cell darkens."""
    return "#FFFFFF" if (t or 0) > 0.55 else INK


def calendar_html(series, compare=None, upto=None, cap_pct: float = 0.95) -> str:
    """The month as a wall calendar.

    series   the month being shown, one value per calendar day
    compare  optional same-length series to show as a delta chip
    upto     day-of-month already traded this year; days after it are the ones
             still to come, and are ringed because they are the reason to look
    cap_pct  the colour scale is capped here so one huge day does not flatten
             every other cell to the same pale wash
    """
    if series.empty:
        return "<p>No data.</p>"

    hi = float(np.nanpercentile(series.values, cap_pct * 100)) or 1.0
    first = series.index[0]
    pad = first.weekday()                       # blanks before the 1st

    head = "".join(
        f'<div style="padding:6px 0;text-align:center;font-size:.72rem;'
        f'letter-spacing:.06em;color:{MUTED};font-weight:600;'
        f'background:{"#FAF6EF" if i >= 5 else "transparent"}">{d}</div>'
        for i, d in enumerate(WEEKDAYS))

    cells = ['<div style="border:1px solid transparent"></div>'] * pad
    for day, val in series.items():
        t = min(float(val) / hi, 1.0) if hi else 0.0
        ink = _ink_on(t)
        future = upto is not None and day.day > upto
        ring = f"2px solid {MAROON}" if future else f"1px solid {LINE}"

        chip = ""
        if compare is not None and day in compare.index and not future:
            was = float(compare.loc[day])
            if was > 0:
                pct = (float(val) / was - 1) * 100
                col = GREEN if pct >= 0 else RED
                chip = (f'<div style="font-size:.62rem;font-weight:700;color:{col};'
                        f'margin-top:1px">{pct:+.0f}%</div>')

        body = ("—" if val == 0 else _short(val))
        cells.append(
            f'<div style="border:{ring};border-radius:6px;padding:7px 6px 6px;'
            f'background:{_tint(t)};min-height:64px;display:flex;'
            f'flex-direction:column;justify-content:space-between">'
            f'<div style="font-size:.66rem;color:{ink};opacity:.75;'
            f'font-weight:600">{day.day}</div>'
            f'<div style="font-size:.92rem;font-weight:700;color:{ink};'
            f'font-variant-numeric:tabular-nums;line-height:1.1">{body}</div>'
            f'{chip}</div>')

    return (
        f'<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;'
        f'margin:4px 0 2px">{head}</div>'
        f'<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px">'
        f'{"".join(cells)}</div>')


def stat_row(items) -> str:
    """`items` = [(label, value, sub or None), …] — the house metric card."""
    out = []
    for label, value, sub in items:
        tail = (f'<div style="font-size:.7rem;color:{MUTED};margin-top:2px">{sub}</div>'
                if sub else "")
        out.append(
            f'<div style="border-left:2px solid {LINE};padding:2px 0 2px 10px">'
            f'<div style="font-size:.68rem;color:{MUTED};text-transform:uppercase;'
            f'letter-spacing:.07em">{label}</div>'
            f'<div style="font-size:1.35rem;font-weight:700;color:{INK};'
            f'font-variant-numeric:tabular-nums;line-height:1.2">{value}</div>'
            f'{tail}</div>')
    return (f'<div style="display:grid;grid-template-columns:repeat({len(out)},1fr);'
            f'gap:14px;margin:10px 0 14px">{"".join(out)}</div>')
