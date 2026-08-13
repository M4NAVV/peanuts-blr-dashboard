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
# The tab's own gid, so the URL can be derived from the workbook the portfolio
# feed already names — the same approach targets.py and city_growth.py take.
# A configured URL that has lost its gid serves the workbook's FIRST tab (the
# VFL transaction data) instead, which is how a correct-looking secret produced
# "no CODE or Date column"; the derived URL is tried as a fallback for exactly
# that case, so a mangled secret self-corrects.
_GID = "1754360378"
_PORTFOLIO_ENV = "PORTFOLIO_CSV_URL"

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


def _secret(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        return st.secrets.get(name)
    except Exception:
        return None


def _derived():
    """The tab's export URL, built from the workbook the portfolio feed names."""
    import re
    base = _secret(_PORTFOLIO_ENV)
    if not base:
        return None
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", str(base))
    return (f"https://docs.google.com/spreadsheets/d/{m.group(1)}"
            f"/export?format=csv&gid={_GID}") if m else None


def _urls():
    """Every URL worth trying, best first, without duplicates."""
    out = []
    for u in (_secret(URL_ENV), _derived()):
        if u and u not in out:
            out.append(u)
    return out


def _url():
    us = _urls()
    return us[0] if us else None


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
    """The tab, tidied: one row per store per brand line. None if unusable.

    Each candidate URL is tried in turn, so a secret that has lost its gid — and
    therefore serves the wrong tab — is rescued by the derived one.
    """
    global _LAST_PROBLEM
    if url is None:
        for candidate in _urls():
            got = _load_one(candidate)
            if got is not None:
                return got
        if not _urls():
            _LAST_PROBLEM = f"${URL_ENV} is not set and no workbook to derive it from"
        return None
    return _load_one(url)


def _load_one(url) -> pd.DataFrame | None:
    global _LAST_PROBLEM
    _LAST_PROBLEM = None
    if not url:
        # Say so. An unconfigured overlay used to return None with no reason,
        # so the sidebar printed nothing and a missing secret looked exactly
        # like a working one — the invisible failure this whole module is meant
        # to avoid, left in the one path that never got tested.
        _LAST_PROBLEM = f"${URL_ENV} is not set"
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
            # Name what WAS found: the usual cause is a URL without its gid,
            # which serves the workbook's first tab instead of this one.
            _LAST_PROBLEM = ("no CODE or Date column — found "
                             + ", ".join(str(c) for c in cols[:4]) + "…")
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
        # The brand line this row is for (MANYAVAR / MOHEY / TWAMEV …). The tab
        # splits VFL stores by line, and the night SMS reports that split.
        c_gender = _find(cols, ("VFL G", "MEN/WOMEN/CHILD"))
        t["gender"] = (raw.loc[t.index, c_gender].astype(str).str.strip().str.upper()
                       if c_gender is not None else "")
        c_line = _find(cols, ("STORE NAME",))
        t["line"] = (raw.loc[t.index, c_line].astype(str).str.strip().str.upper()
                     if c_line is not None else "")
        # Per-store extras, carried when the sheet has them. Entered once per
        # store (on its MANYAVAR line), so they SUM correctly per store.
        for key, names in (("bills", ("BILL", "BILLS")), ("qty", ("QTY",)),
                           ("footfall", ("FOOTFALL",)),
                           ("manual", ("MANUAL SALE", "MANUAL")),
                           # The day target moves daily, so it belongs beside
                           # the day's figures rather than in the targets tab.
                           ("day_target", ("DAY TARGET", "TODAY TARGET"))):
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


# ── VFL side ────────────────────────────────────────────────────────────────
# ★ WHAT CAN AND CANNOT BE CARRIED ACROSS.
#
# The portfolio sheet is already ONE ROW PER STORE PER DAY, so a night-fill row
# appended to it is the same kind of thing the paste would add. The VFL frame is
# TRANSACTIONAL — one row per line item, carrying division, section, department,
# category, salesperson and a bill number — and the night fill has none of that.
# So what is appended here is honest about its own coarseness:
#
#   sales, brand line and gender  -> faithful. Division is set to the brand line
#       the tab states, which is exactly what `brand_line_vfl` reads, so the VFL
#       G/D and gender reports are correct for the day.
#   units                         -> faithful, from the tab's QTY.
#   section / department / category / salesperson -> literally "(PROVISIONAL)",
#       so a finer breakdown SHOWS the day as provisional instead of quietly
#       filing it under a real division it was never measured against.
#   BILLS                         -> cannot be represented. A bill count is a
#       count of distinct bill numbers, and inventing 32 bill numbers to make
#       one store's count come out right would be fabricating transactions.
#       Bill No is left null, so provisional rows contribute no bills, and
#       `_PROVISIONAL_COL` marks them so bill-derived figures (bills, average
#       bill value) can exclude the day and stay internally consistent rather
#       than dividing today's sales by yesterday's bills.
_PROVISIONAL_COL = "_provisional"

# The tab's brand-line spelling -> the Division spelling `brand_line_vfl` reads.
_LINE_TO_DIVISION = {
    "MANYAVAR": "MANYAVAR", "MOHEY": "MOHEY",
    "TWAMEV MEN": "TWAMEV-MEN", "TWAMEV-MEN": "TWAMEV-MEN",
    "TWAMEV WOMEN": "TWAMEV-WOMEN", "TWAMEV-WOMEN": "TWAMEV-WOMEN",
}


def vfl_rows_if_newer(raw: pd.DataFrame, url=None) -> pd.DataFrame | None:
    """Rows to append to the RAW VFL frame, or None to leave it alone.

    Same forward-only rule as the portfolio side: a day the VFL sheet already
    covers is ignored, so Tableau always wins the moment it lands.
    """
    try:
        import loader as L
        t = load(url)
        if t is None:
            return None
        day = fill_date(t)
        if day is None:
            return None

        have = L._parse_dates(raw[L.COL_DATE])
        latest = have.max()
        if pd.isna(latest) or day <= latest:
            return None                      # already covered — stand aside

        # Only stores the VFL feed knows; the tab also carries 31 non-VFL ones.
        m = L.load_store_master()
        label = {int(c): n for c, n in zip(
            pd.to_numeric(m["code"], errors="coerce"), m["tableau_name"])
            if pd.notna(c)}
        t = t[t["code"].isin(label)]
        if t.empty:
            return None

        line = t["line"].astype(str).str.strip().str.upper()
        out = pd.DataFrame({
            L.COL_STORE: t["code"].map(label),
            # ⚠️ THE VFL SHEET IS MONTH-FIRST (%m/%d/%Y), unlike the portfolio
            # sheet, which is day-first. Writing the portfolio's format here
            # turned 12 August into 8 December — silently, because both are
            # valid dates. Match `loader._parse_dates` exactly.
            L.COL_DATE: day.strftime("%m/%d/%Y"),
            L.COL_AMOUNT: t["value"].astype(float),
            L.COL_QTY: (t["qty"] if "qty" in t.columns else pd.NA),
            L.COL_DIVISION: line.map(_LINE_TO_DIVISION).fillna("MANYAVAR"),
            L.COL_MWC: t.get("gender", pd.Series("", index=t.index)),
            L.COL_BILL: pd.NA,               # a bill count cannot be invented
        })
        for c in (L.COL_SECTION, L.COL_DEPARTMENT, L.COL_STYLE, L.COL_COLOR,
                  L.COL_SALESPERSON):
            out[c] = "(PROVISIONAL)"
        out[L.COL_PROMO] = 0
        out[_PROVISIONAL_COL] = True
        return out
    except Exception:
        return None
