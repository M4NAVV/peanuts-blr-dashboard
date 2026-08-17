"""A selection whose stores have all closed must render, not raise.

The Portfolio page took a raw traceback from six ordinary sidebar choices — the
city ASANSOL, the brand LONGHORNS, the stores Forum Mall, Galaxy Mall and Nh31A.
Each selects stores that shut before this fiscal year, so the frame arrives with
a full year of history and NO sales in the current one. `pf.empty` is therefore
False and the guard passes, then:

  * `gd_store_attrs_dyn` built a DataFrame from an empty row list — no columns —
    and read `out["doo"]`                                    KeyError: 'doo'
  * `_window_frames` mapped a column of codes through an empty datetime Series
                             TypeError: Cannot cast DatetimeArray to dtype float64

Every closure adds another such selection once its fiscal year passes, so this
was going to keep happening. The same emptiness arrives on the first day of a
new fiscal year, before any store has sold anything.

Runs on a synthetic frame — no sheet, no network:

    python tests/test_closed_store_selection.py   (or: python -m pytest tests -q)
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_loader as PL          # noqa: E402

ASOF = pd.Timestamp(2026, 8, 14)       # FY 2026-27
SHUT, OPEN = 9101, 9102


def _frame():
    """One store that stopped selling last October, one still trading."""
    rows = []
    for code, last in ((SHUT, pd.Timestamp(2025, 10, 31)), (OPEN, ASOF)):
        for d in pd.date_range("2025-04-01", ASOF, freq="D"):
            rows.append({"date": d, "code": code,
                         # the sheet keeps ZERO rows for a shut store, which is
                         # exactly why the frame is not empty
                         "sales": 1_000.0 if d <= last else 0.0,
                         "region": "East & NE", "brand": "BRAND",
                         "location": f"Loc {code}", "city": "Siliguri",
                         "takeover_date": pd.Timestamp(2024, 4, 1)})
    return pd.DataFrame(rows)


def _closed_only():
    """What the sidebar hands over when the selection is a shut store."""
    df = _frame()
    return df[df["code"] == SHUT]


def test_the_selection_is_not_empty_which_is_the_whole_problem():
    df = _closed_only()
    assert not df.empty, "the guard upstream passes precisely because rows exist"
    assert df["sales"].sum() > 0, "it has last year's sales, just none this year"
    assert PL.active_codes(df, ASOF) == set(), "and nothing active this year"


def test_store_attributes_come_back_with_their_columns():
    a = PL.gd_store_attrs_dyn(_closed_only(), ASOF)
    assert a.empty
    for col in ("code", "doo", "closed", "new_old", "region"):
        assert col in a.columns, f"{col} must exist even with no rows"


def test_window_frames_returns_an_empty_pair():
    cur, pri = PL._window_frames(_closed_only(), "YTD", ASOF)
    assert cur.empty and pri.empty
    assert list(cur.columns) == list(_closed_only().columns)


def test_every_portfolio_entry_point_survives_the_selection():
    df = _closed_only()
    for name, fn in (
        ("store_yoy YTD", lambda: PL.store_yoy(df, "YTD", ASOF)),
        ("store_yoy MTD", lambda: PL.store_yoy(df, "MTD", ASOF)),
        ("exec_yoy", lambda: PL.exec_yoy(df, ASOF)),
        ("region_yoy", lambda: PL.region_yoy(df, "YTD", ASOF)),
        ("_gd_store_metrics", lambda: PL._gd_store_metrics(df, ASOF)),
        ("gd_sheet_report", lambda: PL.gd_sheet_report(df, ASOF)),
        ("brand_wise_gd_report", lambda: PL.brand_wise_gd_report(df, ASOF)),
        ("loc_wise_gd_report", lambda: PL.loc_wise_gd_report(df, ASOF)),
        ("average_report", lambda: PL.average_report(df, ASOF)),
    ):
        try:
            fn()
        except Exception as e:                      # pragma: no cover - the point
            raise AssertionError(f"{name} raised {type(e).__name__}: {e}") from e


def test_the_reports_come_back_empty_so_a_tab_can_say_so():
    """Each report's `if rep.empty` branch is what puts a message on screen."""
    df = _closed_only()
    for fn, cols in ((PL.gd_sheet_report, PL.GD_SHEET_COLS),
                     (PL.brand_wise_gd_report, PL.BRAND_GD_COLS),
                     (PL.loc_wise_gd_report, PL.LOC_GD_COLS),
                     (PL.average_report, PL.AVG_COLS)):
        rep, types = fn(df, ASOF)
        assert rep.empty and types == []
        assert list(rep.columns) == list(cols)


def test_a_new_fiscal_year_with_no_sales_yet_behaves_the_same():
    """1 April, before the first store has sold anything."""
    df = _frame()
    nye = pd.Timestamp(2027, 4, 1)
    assert PL.active_codes(df, nye) == set()
    PL.gd_sheet_report(df, nye)
    PL.store_yoy(df, "YTD", nye)
    PL.exec_yoy(df, nye)


def test_a_normal_selection_is_untouched():
    """The guards must not change a frame that has trading stores."""
    df = _frame()
    rep, types = PL.gd_sheet_report(df, ASOF)
    assert not rep.empty and "grand" in types
    y = PL.store_yoy(df, "YTD", ASOF)
    assert set(y["code"]) == {OPEN}, "the shut store drops out, as it always did"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all closed-selection tests passed")
