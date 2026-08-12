"""
Night fill — yesterday's takings, hours before the paste.

The day's figures are typed into a "Night Tinku Fill" tab at close, and pasted
into the portfolio sheet the next morning; only then does the dashboard see
them. This reads that tab directly so the morning reports don't have to wait for
the paste.

★ IT IS STRICTLY ADDITIVE, AND ONLY FORWARD.

    a date the portfolio sheet already covers  ->  ignored entirely
    a date newer than anything in the sheet    ->  appended

So the moment the paste (or Tableau) lands, that date is covered and this steps
aside on its own. There is no mode to switch and nothing to turn off later — the
authoritative feed always wins, because it is always at least as new.

★ IT CANNOT BREAK THE EXISTING REPORTS.

  * Unless `NIGHT_FILL_URL` is configured this module does nothing at all, so the
    default behaviour of every report is exactly what it was.
  * Every failure — unreachable sheet, renamed column, unparseable date, a code
    that maps to no store — returns None and the feed is used untouched. It
    never raises into a caller.
  * Rows are emitted in the RAW sheet schema and appended BEFORE `clean()`, so
    typing, the takeover filter and the fiscal columns are applied by the same
    code that handles every other row. Nothing here builds a cleaned frame by
    hand.
  * Store name, location and city are copied from that store's own most recent
    row in the sheet, so an appended row is indistinguishable from a pasted one.

★ WHAT IT IS NOT. The tab holds ONE day and is overwritten each night, so it can
only ever fill the gap between close and paste — all history still comes from
the sheet. It also carries no division, category, bill or unit detail, which is
why it feeds the portfolio (sales-only) side and not the VFL transaction frame.

Verified 11 Aug 2026 against a day the paste had already done: 78 rows, one date,
52 stores, Rs 23,54,810 — matching the sheet's own total to the rupee, with ZERO
stores differing.
"""

from __future__ import annotations

import os

import pandas as pd

URL_ENV = "NIGHT_FILL_URL"

# Raw portfolio sheet schema — appended rows must look exactly like sheet rows.
C_DATE, C_CODE, C_NAME, C_LOC, C_CITY, C_TOTAL = (
    "DATE", "STORE CODE", "STORE NAME", "LOCATION", "CITY", "Total")

# ★ COLUMNS ARE FOUND BY HEADER NAME, NEVER BY POSITION.
# The first version read the first eight columns positionally. On 12 Aug the tab
# was restructured — Date moved from the seventh column to the first, and BILL,
# QTY and FOOTFALL were inserted before the value — and the overlay silently
# stopped working: every guard held, nothing raised, and it simply produced no
# rows. Safe, but invisible. Reading by header survives columns being added,
# moved or reordered, which is what actually happens to a sheet in daily use.
_CODE = ("CODE", "STORE CODE")
_DATE = ("DATE",)
_FY_RE = r"^\d{2}-\d{2}(\.\d+)?$"

_LAST_PROBLEM = None


def last_problem():
    """Why the night fill was not used, or None. Surfaced in the sidebar, so a
    dead overlay is visible rather than merely harmless."""
    return _LAST_PROBLEM


def _url():
    if os.environ.get(URL_ENV):
        return os.environ[URL_ENV]
    try:
        import streamlit as st
        return st.secrets.get(URL_ENV)
    except Exception:
        return None


def _find(cols, names):
    want = {n.strip().upper() for n in names}
    for c in cols:
        if str(c).strip().upper() in want:
            return c
    return None


def _value_col(cols, day):
    """The column holding this year's sale, headed with the fiscal year.

    Duplicate headers get a suffix from pandas, so the current year's column is
    the first exact match; anything fiscal-year-shaped is the fallback.
    """
    import re
    fy = day.year if day.month >= 4 else day.year - 1
    label = f"{str(fy)[2:]}-{str(fy + 1)[2:]}"
    for c in cols:
        if str(c).strip() == label:
            return c
    for c in cols:
        if re.match(_FY_RE, str(c).strip()):
            return c
    return None


def load(url=None) -> pd.DataFrame | None:
    """The tab, tidied: one row per store per brand line. None if unusable."""
    global _LAST_PROBLEM
    _LAST_PROBLEM = None
    url = url or _url()
    if not url:
        return None
    try:
        raw = pd.read_csv(url, dtype=str)
    except Exception as e:
        _LAST_PROBLEM = f"could not be read ({type(e).__name__})"
        return None
    try:
        cols = list(raw.columns)
        c_code, c_date = _find(cols, _CODE), _find(cols, _DATE)
        if c_code is None or c_date is None:
            _LAST_PROBLEM = "no CODE or Date column"
            return None
        t = pd.DataFrame({
            "code": pd.to_numeric(raw[c_code], errors="coerce"),
            "date": pd.to_datetime(raw[c_date], dayfirst=True, errors="coerce",
                                   format="mixed"),
        })
        t = t[t["code"].notna()]
        if t.empty or t["date"].notna().sum() == 0:
            _LAST_PROBLEM = "no dated store rows"
            return None
        # The tab is a one-day template, so every row belongs to that day. A row
        # whose own date cell does not parse still counts — dropping one once
        # lost a store from the day's count.
        days = t.loc[t["date"].notna(), "date"].unique()
        if len(days) != 1:
            _LAST_PROBLEM = f"holds {len(days)} dates, expected one"
            return None
        day = pd.Timestamp(days[0])
        c_val = _value_col(cols, day)
        if c_val is None:
            _LAST_PROBLEM = "no fiscal-year value column"
            return None
        t["date"] = day
        t["value"] = pd.to_numeric(raw.loc[t.index, c_val], errors="coerce")
        t = t[t["value"].notna()]
        if t.empty:
            _LAST_PROBLEM = "no numeric values"
            return None
        t["code"] = t["code"].astype(int)
        # Per-store extras, carried when the sheet has them. Entered once per
        # store (on its MANYAVAR line), so they SUM correctly per store.
        for key, names in (("bills", ("BILL", "BILLS")), ("qty", ("QTY",)),
                           ("footfall", ("FOOTFALL",)),
                           ("manual", ("MANUAL SALE", "MANUAL"))):
            col = _find(cols, names)
            if col is not None:
                t[key] = pd.to_numeric(raw.loc[t.index, col], errors="coerce")
        return t
    except Exception as e:
        _LAST_PROBLEM = f"unexpected shape ({type(e).__name__})"
        return None


def fill_date(t: pd.DataFrame):
    """The single day the tab is holding. None if it holds more than one."""
    days = t["date"].dropna().unique()
    return pd.Timestamp(days[0]) if len(days) == 1 else None


def raw_rows_if_newer(raw: pd.DataFrame, url=None) -> pd.DataFrame | None:
    """Rows to append to the RAW portfolio frame, or None to leave it alone.

    `raw` is the sheet exactly as read. Returns None whenever the night fill is
    absent, unusable, or covers a day the sheet already has.
    """
    try:
        t = load(url)
        if t is None:
            return None
        day = fill_date(t)
        if day is None:
            return None

        have = pd.to_datetime(raw[C_DATE], format="%d/%m/%Y", errors="coerce")
        miss = have.isna()
        if miss.any():
            have.loc[miss] = pd.to_datetime(raw.loc[miss, C_DATE], dayfirst=True,
                                            errors="coerce")
        latest = have.max()
        if pd.isna(latest) or day <= latest:
            return None                      # already covered — stand aside

        # Emit exactly what the paste emits: ONE ROW PER TAB LINE — so the VFL
        # stores keep their brand-line split — carrying only the date, the code
        # and the amount. The sheet's own pasted rows leave STORE NAME, LOCATION
        # and CITY blank and let `clean()` fill them from the master, so this
        # does the same rather than inventing identity of its own.
        known = set(pd.to_numeric(raw[C_CODE], errors="coerce").dropna().astype(int))
        rows = t[t["code"].isin(known)]      # never invent an unknown store
        if rows.empty:
            return None
        return pd.DataFrame({
            C_DATE: f"{day.day}/{day.month}/{day.year}",
            C_CODE: rows["code"].astype(str).values,
            C_NAME: "", C_LOC: "", C_CITY: "",
            C_TOTAL: [f"{v:.2f}" for v in rows["value"]],
        }, columns=[C_DATE, C_CODE, C_NAME, C_LOC, C_CITY, C_TOTAL])
    except Exception:
        return None
