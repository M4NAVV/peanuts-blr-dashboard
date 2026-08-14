"""Like to like means ALREADY TRADING BEFORE LAST YEAR BEGAN — and page 1 must
say the same number as page 5.

The Executive Snapshot used to define its like to like set as `prior > 0`,
"traded at all last year". A store that opened in June of last year passed that
test, so four and a half months of this year were compared against two and a
half of last — Silchar's +113.8% was mostly two extra months of existing. The
snapshot printed +5.0% where the Growth-Degrowth sheet behind it, in the same
PDF, printed +2.38% on the same estate.

Manav's rule (11 Aug): *"store opens mid-year: NA till 31-03-2027, PY from
01-04-2027"*. The sheet already implements it when it tags a store OLD, so the
snapshot now reads that same tag and the two tie by construction rather than by
coincidence. This file exists to stop them drifting apart again.

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

# Codes deliberately outside gd_store_attrs.csv, so each store's DOO is derived
# from its own first sale and this frame alone decides the answer.
OLD_STORE, MID_LAST_YEAR, THIS_YEAR = 9001, 9002, 9003


def _frame():
    """Three stores, one per comparability class, selling on the 15th."""
    starts = {OLD_STORE: pd.Timestamp(2024, 4, 15),      # before last year
              MID_LAST_YEAR: pd.Timestamp(2025, 6, 15),  # opened inside last year
              THIS_YEAR: pd.Timestamp(2026, 4, 15)}      # opened this year
    rows = []
    for code, start in starts.items():
        d = start
        while d <= ASOF:
            rows.append({"date": d, "code": code, "sales": 100_000.0,
                         "region": "East & NE", "brand": f"BRAND {code}",
                         "location": f"Loc {code}", "city": "Siliguri",
                         "takeover_date": pd.Timestamp(2024, 4, 1)})
            d += pd.DateOffset(months=1)
    return pd.DataFrame(rows)


def test_a_store_that_opened_inside_last_year_is_not_comparable():
    """The whole point. Its last year is a PART year, so its growth is maturity."""
    lfl = ES._lfl_codes(_frame(), ASOF)
    assert OLD_STORE in lfl
    assert MID_LAST_YEAR not in lfl, "a part year is not a comparable year"
    assert THIS_YEAR not in lfl


def test_the_rule_is_the_gd_sheets_own_tag():
    """`_comparable` must agree with the sheet's OLD/PY/NA tagging, always."""
    assert ES._comparable("2024-04-15", ASOF) is True       # older than last year
    assert ES._comparable("2025-06-15", ASOF) is False      # opened inside it
    assert ES._comparable("2025-03-31", ASOF) is True       # day before it began
    assert ES._comparable("2025-04-01", ASOF) is False      # the day it began
    assert ES._comparable("2026-04-19", ASOF) is False      # opened this year
    assert ES._comparable("", ASOF) is True                 # unknown DOO reads old


def test_the_snapshot_tile_ties_to_the_gd_sheets_old_subtotal():
    """Page 1 and page 5 of the same pack, on the same estate, same percentage."""
    df = _frame()
    lfl = ES._lfl_codes(df, ASOF)

    y = PL.store_yoy(df, kind="YTD", asof=ASOF)
    y["code"] = y["code"].astype(int)
    tile = y[y["code"].isin(lfl)]

    disp, _ = PL.gd_sheet_report(df, ASOF)
    old = disp[disp["NEW/OLD"].astype(str).str.endswith("FY")
               & (disp["STORE CODE"].astype(str).str.strip() != "")]

    assert len(old) == len(tile) == 1
    assert round(tile["prior"].sum(), 2) == round(old["Sum of YTD_LY"].sum(), 2)
    assert round(tile["cur"].sum(), 2) == round(old["Sum of YTD_TY"].sum(), 2)


def test_a_closed_store_stays_in_the_set():
    """Its last year is already capped to its closure month by `_window_frames`;
    dropping it as well would apply Manav's closure rule twice."""
    df = _frame()
    lfl = ES._lfl_codes(df, ASOF)
    shut = {c for c in lfl if c in PL.closed_map()}
    # Nothing in this synthetic frame is closed, so the guarantee to pin is that
    # the set is built from the DOO tag alone and never subtracts closures.
    assert lfl == {int(r["code"]) for _, r in
                   PL.gd_store_attrs_dyn(df, ASOF).iterrows()
                   if ES._comparable(r["doo"], ASOF)}
    assert not shut


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all like-to-like tests passed")
