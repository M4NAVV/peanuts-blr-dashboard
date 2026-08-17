"""Like to like is a WINDOW PER STORE, applied to both years.

Manav's rule, 14 Aug 2026: *"L2L comparison is CONSIDERED only from the date the
store has data last year (eg Silchar L2L starts only from the date sales are
captured in LY). Similarly for closed stores L2L stops from the day it closes
this year. Same will apply to both the parts, VFL and overall."*

Two earlier definitions failed, and both failed the same way — by deciding whole
stores in or out:

  `prior > 0`  ("traded at all last year") let a store that opened last June be
  compared over 4.5 months of this year against 2.5 of last. Silchar's +113.8%
  was mostly two extra months of existing, and that one store moved the portfolio
  tile from +2.4% to +5.0%.

  "opened before last year began" then threw that store away whole, and with it
  the three months it genuinely COULD be compared over.

The window rule keeps the comparable part of every store and discards only the
part that has no counterpart — which is why last year's like to like total equals
last year's whole turnover, the property pinned below.

Runs on a synthetic frame — no sheet, no network:

    python tests/test_like_to_like.py       (or: python -m pytest tests -q)
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import exec_snapshot as ES              # noqa: E402
import portfolio_loader as PL           # noqa: E402

ASOF = pd.Timestamp(2026, 8, 14)        # FY 2026-27; last year began 1 Apr 2025

OLD, OPENED_MID_LAST_YEAR, OPENED_THIS_YEAR, SHUT = 9001, 9002, 9003, 9004
STARTS = {OLD: pd.Timestamp(2025, 4, 1),
          OPENED_MID_LAST_YEAR: pd.Timestamp(2025, 6, 1),
          OPENED_THIS_YEAR: pd.Timestamp(2026, 4, 1),
          SHUT: pd.Timestamp(2025, 4, 1)}
CLOSURE = pd.Timestamp(2026, 5, 31)     # SHUT stops trading at the end of May


def _frame():
    """Rs 1,000 a day per store, so every span has an exact expected value."""
    rows = []
    for code, start in STARTS.items():
        for d in pd.date_range(start, ASOF, freq="D"):
            if code == SHUT and d > CLOSURE:
                continue
            rows.append({"date": d, "code": code, "sales": 1_000.0,
                         "region": "East & NE", "brand": f"BRAND {code}",
                         "location": f"Loc {code}", "city": "Siliguri",
                         "takeover_date": pd.Timestamp(2024, 4, 1)})
    return pd.DataFrame(rows)


def _bounds(df):
    return ES.l2l_bounds(df, "code", "sales", {SHUT: CLOSURE}, ASOF)


def test_the_span_starts_where_last_years_data_starts():
    start, end = _bounds(_frame())
    assert start[OLD] == pd.Timestamp(2026, 4, 1)
    assert start[OPENED_MID_LAST_YEAR] == pd.Timestamp(2026, 6, 1), \
        "Silchar's span must open in June, not April"
    assert start[OPENED_THIS_YEAR] == pd.Timestamp(2027, 4, 1)      # beyond as-of


def test_the_span_stops_the_day_a_store_closes():
    start, end = _bounds(_frame())
    assert end[SHUT] == CLOSURE
    assert end[OLD] == ASOF


def test_a_store_with_no_overlap_at_all_falls_out():
    """Dibrugarh's case: its last year begins after this window ends."""
    df = _frame()
    t = ES.l2l_store_table(*PL._window_frames(df, "YTD", ASOF), _bounds(df),
                           PL.store_yoy(df, "YTD", ASOF), "code", "sales")
    assert OPENED_THIS_YEAR not in set(t["code"])
    assert {OLD, OPENED_MID_LAST_YEAR, SHUT} == set(t["code"])


def test_both_years_are_cut_to_the_same_span():
    """The whole point: 75 days this year against the SAME 75 days last year."""
    df = _frame()
    t = ES.l2l_store_table(*PL._window_frames(df, "YTD", ASOF), _bounds(df),
                           PL.store_yoy(df, "YTD", ASOF), "code", "sales")
    t = t.set_index("code")
    # Silchar: 1 Jun -> 14 Aug is 75 days, in each year, at Rs 1,000 a day.
    assert t.loc[OPENED_MID_LAST_YEAR, "cur"] == 75_000.0
    assert t.loc[OPENED_MID_LAST_YEAR, "prior"] == 75_000.0
    # The shut store: 1 Apr -> 31 May is 61 days, in each year.
    assert t.loc[SHUT, "cur"] == 61_000.0
    assert t.loc[SHUT, "prior"] == 61_000.0


def test_every_rupee_of_last_year_is_still_compared():
    """The property that makes this rule better than dropping whole stores: for a
    trading store, like to like's LAST YEAR is its WHOLE last year, to the rupee.
    Only THIS year's uncomparable part is held out.

    Stated over open stores on purpose. A shut store's last year is cut at its
    closure DAY here, while `_window_frames` caps it at the closure MONTH — the
    same date for every closure the estate has had (all three are month-ends),
    and the day is the rule Manav gave, so the tighter of the two wins.
    """
    df = _frame()
    y = PL.store_yoy(df, "YTD", ASOF).set_index("code")
    t = ES.l2l_store_table(*PL._window_frames(df, "YTD", ASOF), _bounds(df),
                           PL.store_yoy(df, "YTD", ASOF), "code", "sales")
    t = t.set_index("code")
    for code in (OLD, OPENED_MID_LAST_YEAR):
        assert round(t.loc[code, "prior"], 2) == round(y.loc[code, "prior"], 2)
    # ...while this year is NOT: Silchar's April and May have no counterpart.
    assert t.loc[OPENED_MID_LAST_YEAR, "cur"] < y.loc[OPENED_MID_LAST_YEAR, "cur"]


def test_a_month_a_store_cannot_be_compared_in_is_absent_from_both_bars():
    """Silchar sits out April and May and joins from June — on BOTH sides."""
    df = _frame()
    cur, pri = PL._window_frames(df, "YTD", ASOF)
    c, p = ES.l2l_frames(cur, pri, _bounds(df), "code")
    for fr, yr in ((c, 2026), (p, 2025)):
        apr = fr[(fr["code"] == OPENED_MID_LAST_YEAR)
                 & (fr["date"] < pd.Timestamp(yr, 6, 1))]
        assert apr.empty, f"nothing before June should survive in {yr}"

# --------------------------------------------------------------------------- #
# The span opens on the OPENING DATE, not the first sale (Manav, 17 Aug)
# --------------------------------------------------------------------------- #
def test_a_store_dark_at_the_start_of_last_year_is_not_clipped():
    """The whole reason the rule changed. Our stores shut all the time —
    renovations, mall works — and a store that existed but was closed is not a
    store that had not opened. Mani Square Colorplus, trading since 2017, was
    losing five weeks of comparison because it was dark last April."""
    df = _frame()
    dark = df[~((df["code"] == OLD)
                & (df["date"] >= pd.Timestamp(2025, 4, 1))
                & (df["date"] < pd.Timestamp(2025, 5, 7)))]
    opened = {OLD: pd.Timestamp(2017, 5, 1)}          # open since long before
    start, _ = ES.l2l_bounds(dark, "code", "sales", {}, ASOF, opened=opened)
    assert start[OLD] <= pd.Timestamp(2026, 4, 1), \
        "an old store must be comparable from the start of the window"


def test_a_store_that_opened_mid_last_year_still_clips():
    """Silchar's case, which is what the split exists for."""
    df = _frame()
    opened = {OPENED_MID_LAST_YEAR: pd.Timestamp(2025, 6, 1)}
    start, _ = ES.l2l_bounds(df, "code", "sales", {}, ASOF, opened=opened)
    assert start[OPENED_MID_LAST_YEAR] == pd.Timestamp(2026, 6, 1)


def test_an_opening_date_that_postdates_the_sales_is_a_takeover():
    """South's recorded date is 19 April 2026 — the day we took the stores over,
    not the day they opened — while the VFL feed holds the previous operator's
    trading from a year earlier. Read literally it would throw all eight out of
    like to like on the one feed that can compare them."""
    df = _frame()                                     # OLD sells from Apr 2025
    takeover = {OLD: pd.Timestamp(2026, 4, 19)}       # "opened" AFTER those sales
    start, _ = ES.l2l_bounds(df, "code", "sales", {}, ASOF, opened=takeover)
    assert start[OLD] <= pd.Timestamp(2026, 4, 1), \
        "the trading starts where the trading starts"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all like-to-like tests passed")
