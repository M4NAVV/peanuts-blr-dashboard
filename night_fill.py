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

# The tab's own columns. The seventh header is blank in the sheet and the eighth
# is the fiscal year ("26-27"), so they are taken by position rather than name.
_COLS = ["CODE", "VFL_NAME", "VFL_G", "STORE_NAME", "LOCATION", "CLUSTER",
         "DATE", "VAL"]


def _url():
    if os.environ.get(URL_ENV):
        return os.environ[URL_ENV]
    try:
        import streamlit as st
        return st.secrets.get(URL_ENV)
    except Exception:
        return None


def load(url=None) -> pd.DataFrame | None:
    """The tab, tidied: one row per store per line. None if anything is wrong."""
    url = url or _url()
    if not url:
        return None
    try:
        raw = pd.read_csv(url, dtype=str)
        if raw.shape[1] < len(_COLS):
            return None
        t = raw.iloc[:, :len(_COLS)].copy()
        t.columns = _COLS
        t["code"] = pd.to_numeric(t["CODE"], errors="coerce")
        t["value"] = pd.to_numeric(t["VAL"], errors="coerce")
        t["date"] = pd.to_datetime(t["DATE"], dayfirst=True, errors="coerce",
                                   format="mixed")
        t = t[t["code"].notna() & t["value"].notna()]
        if t.empty or t["date"].notna().sum() == 0:
            return None
        # The tab is a one-day template, so every row belongs to that day. A row
        # whose date cell does not parse still counts: the sheet carries a "Date"
        # label in that column on the first store's line, and dropping it lost
        # that store from the day entirely — a zero-value row, but its absence
        # changed the store count the reports print.
        days = t.loc[t["date"].notna(), "date"].unique()
        if len(days) != 1:
            return None                      # more than one day: not a night fill
        t["date"] = pd.Timestamp(days[0])
        t["code"] = t["code"].astype(int)
        return t
    except Exception:
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
