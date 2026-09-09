"""Google reviews against bills.

★ WHAT THESE PIN. The source workbook is hand-kept and three of its properties
were CHECKED against the POS rather than assumed — the date convention, the
store-name mapping, and whether its own bill column is good enough to divide
by. Get any of them wrong and every rate in the report is wrong while looking
entirely plausible.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reviews as RV


def _rv(rows):
    return pd.DataFrame(rows)


def _bills(rows):
    return pd.DataFrame(rows, columns=["store", "date", "bills"])


def test_every_mapped_name_points_at_a_distinct_store():
    # Two of their names collapsing onto one of ours would silently merge two
    # stores' reviews and halve the count of another.
    assert len(set(RV.STORE_MAP.values())) == len(RV.STORE_MAP)


def test_svr_is_siliguri_2_not_siliguri():
    # Decided by bill-series correlation, not by reading the name — the two
    # Siliguri stores are the pair most easily confused.
    assert RV.STORE_MAP["MANYAVAR SVR"] == "Siliguri 2"
    assert RV.STORE_MAP["MOHEY SILIGURI"] == "Siliguri"


def test_rate_uses_the_pos_bills_not_the_sheets_own_count():
    """Their hand count is 89% exact but Malda runs 3.5% high. The denominator
    should not be a hand count when an exact one exists."""
    rv = _rv([{"date": pd.Timestamp("2026-08-01"), "store": "Malda",
               "day_review": 5, "day_bill": 999}])          # their count is wrong
    bills = _bills([("Malda", pd.Timestamp("2026-08-01"), 20)])
    out = RV.build(rv, bills, pd.Timestamp("2026-08-01"))
    assert out["Day"].loc["Malda", "Bills"] == 20
    assert out["Day"].loc["Malda", "Rate %"] == pytest.approx(25.0)


def test_a_store_the_sheet_does_not_cover_is_absent_not_zero():
    """The workbook holds no Bengaluru store. A 0% there would read as 'nobody
    reviewed' rather than 'we do not measure this store'."""
    rv = _rv([{"date": pd.Timestamp("2026-08-01"), "store": "Malda",
               "day_review": 5, "day_bill": 20}])
    bills = _bills([("Malda", pd.Timestamp("2026-08-01"), 20),
                    ("Jayanagar", pd.Timestamp("2026-08-01"), 200)])
    out = RV.build(rv, bills, pd.Timestamp("2026-08-01"))
    assert "Jayanagar" not in out["Day"].index


def test_a_store_with_no_bills_shows_no_rate_rather_than_zero():
    rv = _rv([{"date": pd.Timestamp("2026-08-01"), "store": "Malda",
               "day_review": 0, "day_bill": 0}])
    bills = _bills([("Malda", pd.Timestamp("2026-08-01"), 0)])
    out = RV.build(rv, bills, pd.Timestamp("2026-08-01"))
    assert pd.isna(out["Day"].loc["Malda", "Rate %"])


def test_windows_accumulate_correctly():
    days = pd.date_range("2026-08-01", "2026-08-05", freq="D")
    rv = _rv([{"date": d, "store": "Malda", "day_review": 2, "day_bill": 10}
              for d in days])
    bills = _bills([("Malda", d, 10) for d in days])
    out = RV.build(rv, bills, pd.Timestamp("2026-08-05"))
    assert out["Day"].loc["Malda", "Reviews"] == 2        # the 5th alone
    assert out["MTD"].loc["Malda", "Reviews"] == 10       # 1st-5th
    assert out["MTD"].loc["Malda", "Rate %"] == pytest.approx(20.0)


def test_nothing_after_the_asof_date_leaks_in():
    days = pd.date_range("2026-08-01", "2026-08-10", freq="D")
    rv = _rv([{"date": d, "store": "Malda", "day_review": 1, "day_bill": 10}
              for d in days])
    bills = _bills([("Malda", d, 10) for d in days])
    out = RV.build(rv, bills, pd.Timestamp("2026-08-05"))
    assert out["MTD"].loc["Malda", "Reviews"] == 5


def test_the_year_window_is_the_fiscal_year():
    rv = _rv([{"date": pd.Timestamp("2026-03-31"), "store": "Malda",
               "day_review": 99, "day_bill": 10},
              {"date": pd.Timestamp("2026-04-01"), "store": "Malda",
               "day_review": 1, "day_bill": 10}])
    bills = _bills([("Malda", pd.Timestamp("2026-03-31"), 10),
                    ("Malda", pd.Timestamp("2026-04-01"), 10)])
    out = RV.build(rv, bills, pd.Timestamp("2026-04-02"))
    # last fiscal year's 99 must not land in this year's YTD
    assert out["YTD"].loc["Malda", "Reviews"] == 1
