"""Weekday vs weekend (Manav, 22 Oct) — see `weekend.py`."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import weekend as W  # noqa: E402


def _frame(rows):
    """rows: (code, city, region, date, sales)."""
    df = pd.DataFrame(rows, columns=["code", "city", "region", "date", "sales"])
    df["date"] = pd.to_datetime(df["date"])
    df["location"] = "Store " + df["code"].astype(str)
    df["brand"] = "MANYAVAR"
    return df


def _week(code, city, region, monday, wd, we):
    """One Mon–Sun week: `wd` on each weekday, `we` on each weekend day."""
    m = pd.Timestamp(monday)
    return [(code, city, region, m + pd.Timedelta(days=i),
             wd if i < 5 else we) for i in range(7)]


def test_window_ends_on_the_last_complete_sunday():
    # 22 Oct 2026 is a Thursday; the last Sunday is the 18th.
    s, e = W.window("Last 4 weeks", "2026-10-22")
    assert e == pd.Timestamp("2026-10-18") and e.dayofweek == 6
    assert s == pd.Timestamp("2026-09-21") and s.dayofweek == 0
    # On a Sunday, that Sunday is complete.
    assert W.window("Last 4 weeks", "2026-10-18")[1] == pd.Timestamp("2026-10-18")
    assert W.window("FY to date", "2026-10-22") == (
        pd.Timestamp("2026-04-01"), pd.Timestamp("2026-10-22"))


def test_split_averages_and_ratio():
    df = _frame(_week(1, "KOLKATA", "East & NE", "2026-10-12", 100, 250))
    rows = W.report(df, "2026-10-12", "2026-10-18")
    s = rows[0][1]
    assert (s["wd"], s["we"]) == (500, 500)
    assert s["wd_pct"] == pytest.approx(50) and s["we_pct"] == pytest.approx(50)
    assert (s["avg_wd"], s["avg_we"]) == (100, 250)
    assert s["ratio"] == pytest.approx(2.5)


def test_a_store_is_averaged_over_its_own_days_only():
    # Store 2 opens on the Thursday: 2 weekdays and the weekend, not 5.
    rows = _week(1, "KOLKATA", "East & NE", "2026-10-12", 100, 200)
    rows += [r for r in _week(2, "KOLKATA", "East & NE", "2026-10-12", 100, 200)
             if r[3] >= pd.Timestamp("2026-10-15")]
    out = dict((r["code"], r) for k, r in W.report(
        _frame(rows), "2026-10-12", "2026-10-18") if k == "store")
    assert out[2]["wd_days"] == 2 and out[2]["avg_wd"] == 100
    # …while a total counts calendar days, not the sum of its stores' days.
    city = [r for k, r in W.report(_frame(rows), "2026-10-12", "2026-10-18")
            if k == "grand"][0]
    assert city["wd_days"] == 5 and city["avg_wd"] == (500 + 200) / 5


def test_totals_add_up_and_shares_sum_to_100():
    rows = (_week(1, "KOLKATA", "East & NE", "2026-10-12", 100, 300)
            + _week(2, "SILIGURI", "East & NE", "2026-10-12", 50, 60)
            + _week(3, "BENGALURU", "South", "2026-10-12", 80, 400))
    rep = W.report(_frame(rows), "2026-10-12", "2026-10-18")
    stores = [r for k, r in rep if k == "store"]
    g = rep[-1][1]
    assert rep[-1][0] == "grand" and g["name"] == "OVERALL"
    assert g["total"] == sum(r["total"] for r in stores)
    assert sum(r["wd_share"] for r in stores) == pytest.approx(100)
    assert sum(r["we_share"] for r in stores) == pytest.approx(100)
    kinds = [k for k, _ in rep]
    assert kinds.count("subtotal") == 2          # one per region
    assert "citytotal" not in kinds              # one store per city


def test_a_store_that_sold_nothing_is_left_out():
    rows = (_week(1, "KOLKATA", "East & NE", "2026-10-12", 100, 300)
            + _week(2, "KOLKATA", "East & NE", "2026-10-12", 0, 0))
    rep = W.report(_frame(rows), "2026-10-12", "2026-10-18")
    assert [r["code"] for k, r in rep if k == "store"] == [1]


def test_empty_window_returns_nothing():
    df = _frame(_week(1, "KOLKATA", "East & NE", "2026-10-12", 100, 300))
    assert W.report(df, "2025-01-01", "2025-01-31") == []
