"""MW Data must survive the turn of the fiscal year.

The grid's years were a literal list ending at 2026-27, and each year's
treatment was chosen by name. On 1 April 2027 the new year would simply not
have appeared: no error, no gap, a whole year of trade rendering nowhere while
the previous one kept its current-year styling. That is the failure this file
exists to stop coming back.

Runs on a synthetic frame — no sheet, no network — so it can run anywhere:

    python tests/test_mw_rollover.py        (or: python -m pytest tests -q)
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_loader as PL          # noqa: E402


def _frame(first_fy=2025, last_fy=2027):
    """A day per month per region, every fiscal year in [first_fy, last_fy]."""
    rows = []
    for y in range(first_fy, last_fy + 1):
        for m in list(range(4, 13)) + list(range(1, 4)):
            year = y if m >= 4 else y + 1
            for region, amount in (("East & NE", 100_000.0), ("South", 60_000.0)):
                rows.append({"date": pd.Timestamp(year, m, 15), "region": region,
                             "sales": amount, "code": 1 if region == "South" else 2})
    return pd.DataFrame(rows)


def test_layout_keeps_the_workbook_shape():
    """Ten years, in rows of three, three and four, current year last on top."""
    blocks = PL.mw_blocks(pd.Timestamp(2026, 8, 14))
    assert blocks == [["2024-25", "2025-26", "2026-27"],
                      ["2023-24", "2022-23", "2021-22"],
                      ["2020-21", "2019-20", "2018-19", "2017-18"]], blocks


def test_the_new_year_appears_on_1_april():
    """The day the fiscal year turns, the new one is in the grid — and is the
    one drawn with the region split."""
    df = _frame()
    before = PL.mw_data(df, asof=pd.Timestamp(2027, 3, 31))
    after = PL.mw_data(df, asof=pd.Timestamp(2027, 4, 1))

    assert "2027-28" not in before
    assert "2027-28" in after, list(after)
    assert [fy for fy, v in before.items() if v["type"] == "region"] == ["2026-27"]
    assert [fy for fy, v in after.items() if v["type"] == "region"] == ["2027-28"]


def test_a_closed_year_keeps_its_figures_across_the_turn():
    """Rolling forward must not restate a year that has already ended."""
    df = _frame()
    before = PL.mw_data(df, asof=pd.Timestamp(2027, 3, 31))
    after = PL.mw_data(df, asof=pd.Timestamp(2027, 4, 1))
    assert round(before["2026-27"]["grand"]["total"], 2) == \
           round(after["2026-27"]["grand"]["total"], 2)
    # and it hands its region split back, becoming an ordinary prior year
    assert after["2026-27"]["type"] == "std"


def test_the_year_totals_what_the_feed_holds():
    """A live year is summed from the data, not from the committed snapshot."""
    df = _frame()
    mw = PL.mw_data(df, asof=pd.Timestamp(2026, 8, 14))
    expected = df[(df["date"] >= pd.Timestamp(2026, 4, 1))
                  & (df["date"] <= pd.Timestamp(2027, 3, 31))]["sales"].sum()
    assert round(mw["2026-27"]["grand"]["total"], 2) == round(expected, 2)


def test_years_before_the_feed_come_from_the_snapshot():
    """A year the feed cannot reach is static, and is never reported as zero
    while the snapshot has it."""
    df = _frame(first_fy=2025, last_fy=2026)
    mw = PL.mw_data(df, asof=pd.Timestamp(2026, 8, 14))
    assert mw["2024-25"]["type"] == "std"
    assert mw["2024-25"]["grand"]["total"] > 0


def test_the_layout_matches_the_grid_that_was_built():
    """The tab and the PDF read the layout off the result, so they cannot draw
    a different set of years from the one computed."""
    df = _frame()
    mw = PL.mw_data(df, asof=pd.Timestamp(2027, 4, 1))
    layout = PL.mw_layout(mw)
    assert [fy for row in layout for fy in row] == list(mw)
    assert layout[0][-1] == "2027-28"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                failed += 1
                print(f"  FAIL  {name}: {e}")
    print("all passed" if not failed else f"{failed} failed")
    sys.exit(1 if failed else 0)
