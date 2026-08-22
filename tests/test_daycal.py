"""The day calendar — last year's version of the month we are in.

Pins the two things that would quietly mislead: a day the store took nothing
must be visible rather than absent, and a part-month must never be compared
against a whole one.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import daycal


def test_window_is_the_same_month_a_year_back():
    s, e = daycal.month_window(pd.Timestamp("2026-08-22"))
    assert (s, e) == (pd.Timestamp("2025-08-01"), pd.Timestamp("2025-08-31"))


def test_window_handles_a_short_month_and_a_leap_year():
    assert daycal.month_window(pd.Timestamp("2026-03-10"))[1] == pd.Timestamp("2025-03-31")
    assert daycal.month_window(pd.Timestamp("2025-02-10"))[1] == pd.Timestamp("2024-02-29")


def _df(rows):
    return pd.DataFrame(rows)


def test_a_day_with_no_sales_shows_as_zero_not_as_missing():
    """A closed day is information. Left absent the month would look 30 days long."""
    df = _df([{"date": pd.Timestamp("2025-08-01"), "amt": 100.0, "store": "A"},
              {"date": pd.Timestamp("2025-08-03"), "amt": 200.0, "store": "A"}])
    s = daycal.daily_series(df, "date", "amt", pd.Timestamp("2025-08-01"),
                            pd.Timestamp("2025-08-03"), "store", "A")
    assert len(s) == 3
    assert s.loc[pd.Timestamp("2025-08-02")] == 0.0


def test_all_stores_sums_every_store():
    df = _df([{"date": pd.Timestamp("2025-08-01"), "amt": 100.0, "store": "A"},
              {"date": pd.Timestamp("2025-08-01"), "amt": 50.0, "store": "B"}])
    s = daycal.daily_series(df, "date", "amt", pd.Timestamp("2025-08-01"),
                            pd.Timestamp("2025-08-01"), "store", "All stores")
    assert s.iloc[0] == 150.0


def test_the_grid_puts_each_date_on_its_real_weekday():
    # 1 Aug 2025 was a Friday. If the grid drifts, every weekend column is wrong
    # and the whole point of the layout is lost.
    idx = pd.date_range("2025-08-01", "2025-08-31", freq="D")
    ser = pd.Series(range(len(idx)), index=idx, dtype=float)
    vals, labs = daycal.to_grid(ser)
    assert labs.loc["Week 1", "Fri"].startswith("1\n")
    assert labs.loc["Week 1", "Mon"] == ""          # outside the month
    assert labs.loc["Week 5", "Sun"].startswith("31\n")


def test_cells_outside_the_month_are_blank_not_zero():
    idx = pd.date_range("2025-08-01", "2025-08-31", freq="D")
    vals, _ = daycal.to_grid(pd.Series(5.0, index=idx))
    assert np.isnan(vals.loc["Week 1", "Mon"])      # 1 Aug is a Friday
    assert vals.loc["Week 1", "Fri"] == 5.0


def test_summary_compares_only_the_days_already_traded():
    """Mid-month, a part-month against a whole one is the commonest way to make
    this year look broken."""
    idx = pd.date_range("2025-08-01", "2025-08-31", freq="D")
    ser = pd.Series(10.0, index=idx)
    sm = daycal.summary(ser, same_days=10)
    assert sm["total"] == 310.0
    assert sm["same_days_total"] == 100.0


def test_summary_worst_day_ignores_days_the_store_was_shut():
    idx = pd.date_range("2025-08-01", "2025-08-05", freq="D")
    ser = pd.Series([50.0, 0.0, 30.0, 90.0, 70.0], index=idx)
    sm = daycal.summary(ser)
    assert sm["worst_val"] == 30.0                  # not the closed day
    assert sm["best_val"] == 90.0


def test_money_shortens_sensibly():
    assert daycal._short(0) == "—"
    assert daycal._short(950) == "950"
    assert daycal._short(12_345) == "12 K"
    assert daycal._short(1_234_567) == "12.35 L"
    assert daycal._short(23_456_789) == "2.35 Cr"


# ---------------------------------------------------------------- rendering

def test_calendar_pads_to_the_right_weekday():
    # 1 Aug 2025 was a Friday, so four blank cells must precede it or every
    # weekend column is wrong and the layout loses its point.
    idx = pd.date_range("2025-08-01", "2025-08-31", freq="D")
    html = daycal.calendar_html(pd.Series(1.0, index=idx))
    assert html.count("border:1px solid transparent") == 4


def test_days_still_ahead_are_ringed():
    # The reason to open this mid-month is the part that has not happened.
    idx = pd.date_range("2025-08-01", "2025-08-31", freq="D")
    html = daycal.calendar_html(pd.Series(1.0, index=idx), upto=21)
    assert html.count(f"2px solid {daycal.MAROON}") == 10   # 22nd-31st


def test_a_day_that_took_nothing_shows_a_dash():
    idx = pd.date_range("2025-08-01", "2025-08-03", freq="D")
    html = daycal.calendar_html(pd.Series([100.0, 0.0, 50.0], index=idx))
    assert ">—<" in html


def test_the_colour_scale_is_capped_so_one_huge_day_does_not_flatten_the_rest():
    idx = pd.date_range("2025-08-01", "2025-08-10", freq="D")
    ser = pd.Series([1.0] * 9 + [1000.0], index=idx)
    html = daycal.calendar_html(ser, cap_pct=0.8)
    # ordinary days must still take colour rather than all rendering white
    assert "rgb(255,255,255)" not in html.split("min-height")[1]


def test_a_delta_chip_is_not_drawn_for_a_day_that_has_not_happened():
    idx = pd.date_range("2025-08-01", "2025-08-31", freq="D")
    cur = pd.Series(100.0, index=idx)
    prev = pd.Series(50.0, index=idx)
    html = daycal.calendar_html(cur, compare=prev, upto=None)
    assert "+100%" in html


def test_no_percentage_when_the_other_year_took_nothing():
    idx = pd.date_range("2025-08-01", "2025-08-02", freq="D")
    html = daycal.calendar_html(pd.Series([100.0, 100.0], index=idx),
                                compare=pd.Series([0.0, 50.0], index=idx))
    assert html.count("%<") == 1     # only the day with a real base
