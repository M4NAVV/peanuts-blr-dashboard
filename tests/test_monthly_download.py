"""Store-wise monthly sales, downloaded off the day-calendar tab.

Frames are built inside the test so CI verifies the rules without the feed —
see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import daycal


def _feed(start="2026-04-01", end="2026-09-22"):
    rows = []
    for d in pd.date_range(start, end):
        rows += [{"date": d, "brand": "MANYAVAR", "location": "City Centre",
                  "code": 56, "sales": 100.0},
                 {"date": d, "brand": "TURTLE", "location": "City Centre",
                  "code": 98, "sales": 40.0}]
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# A location is not a store
# --------------------------------------------------------------------------- #
def test_two_brands_in_one_mall_are_two_stores():
    """`City Centre` is a Siliguri mall holding eleven brands. Keyed on
    location alone, eleven shops would add into one line."""
    df = _feed()
    ident = daycal.store_identity(df, ("brand", "location"))
    assert set(ident) == {"MANYAVAR — City Centre", "TURTLE — City Centre"}
    assert df["location"].nunique() == 1


def test_a_single_column_identity_still_works():
    df = _feed()
    assert set(daycal.store_identity(df, "location")) == {"City Centre"}


# --------------------------------------------------------------------------- #
# Which stores are live
# --------------------------------------------------------------------------- #
def test_a_label_with_several_codes_is_live_if_any_of_them_is():
    """Rajarhat CC2 read as SHUT because a plain dict kept its last code: 99
    closed in Aug 2025 while 90 has traded every day since."""
    live, shut = daycal.live_labels(
        ["Rajarhat Cc2"], {"Rajarhat Cc2": [90, 99]},
        {99: pd.Timestamp("2025-08-31")}, "2026-09-22")
    assert live == ["Rajarhat Cc2"] and shut == []


def test_a_label_whose_every_code_has_closed_is_shut():
    live, shut = daycal.live_labels(
        ["Gone"], {"Gone": [1, 2]},
        {1: pd.Timestamp("2026-07-31"), 2: pd.Timestamp("2026-08-31")},
        "2026-09-22")
    assert shut == ["Gone"] and live == []


def test_a_closure_still_in_the_future_is_not_a_closure_yet():
    live, _ = daycal.live_labels(["Later"], {"Later": 3},
                                 {3: pd.Timestamp("2026-12-31")}, "2026-09-22")
    assert live == ["Later"]


def test_a_store_the_master_does_not_know_is_kept_not_dropped():
    """Dropping it would quietly answer a different question.
    See [[feedback-silent-failure-must-speak]]."""
    live, shut = daycal.live_labels(["Mystery"], {}, {1: pd.Timestamp("2020-01-01")},
                                    "2026-09-22")
    assert live == ["Mystery"] and shut == []


# --------------------------------------------------------------------------- #
# The grid
# --------------------------------------------------------------------------- #
def _matrix(df, **kw):
    work = df[["date", "sales"]].copy()
    work["Store"] = daycal.store_identity(df, ("brand", "location"))
    return daycal.monthly_matrix(work, "date", "sales", "Store", **kw)


def test_the_grid_totals_every_rupee_the_feed_holds():
    """A download that quietly drops rows is worse than no download."""
    df = _feed()
    out, _ = _matrix(df, fy=2026)
    assert out.iloc[-1]["Store"] == "TOTAL"
    assert out.iloc[-1]["Total"] == pytest.approx(df["sales"].sum())


def test_months_run_in_the_order_they_happened():
    out, _ = _matrix(_feed(), fy=2026)
    assert list(out.columns)[1:4] == ["Apr 2026", "May 2026", "Jun 2026"]
    assert list(out.columns)[-1] == "Total"


def test_a_part_traded_month_says_so_in_its_own_header():
    """A part month unlabelled beside a whole one invites a comparison that is
    not one. See [[feedback-provisional-day]]."""
    out, note = _matrix(_feed(end="2026-09-22"), fy=2026)
    assert "Sep 2026 (1–22)" in out.columns
    assert "September 2026 is part-traded" in note
    # a month that ran to its end is not labelled
    assert "Aug 2026" in out.columns


def test_a_whole_final_month_is_not_called_part_traded():
    out, note = _matrix(_feed(end="2026-08-31"), fy=2026)
    assert "Aug 2026" in out.columns
    assert "part-traded" not in note


def test_a_chosen_store_with_no_rows_still_gets_a_row_of_zeros():
    """The user asked about that store and is owed an answer about it."""
    df = _feed()
    work = df[["date", "sales"]].copy()
    work["Store"] = daycal.store_identity(df, ("brand", "location"))
    out, _ = daycal.monthly_matrix(work, "date", "sales", "Store",
                                   stores=["MANYAVAR — City Centre", "Ghost"],
                                   fy=2026)
    assert "Ghost" in list(out["Store"])
    assert out[out["Store"] == "Ghost"]["Total"].iloc[0] == 0.0


def test_the_fiscal_year_filter_excludes_the_year_before():
    df = pd.concat([_feed("2025-04-01", "2025-06-30"), _feed()])
    out, _ = _matrix(df, fy=2026)
    assert all("2025" not in c for c in out.columns if c not in ("Store", "Total"))
    assert out.iloc[-1]["Total"] == pytest.approx(
        df[df["date"] >= pd.Timestamp(2026, 4, 1)]["sales"].sum())


def test_fiscal_helpers_name_the_year_by_its_opening_april():
    assert daycal.fiscal_year_of("2027-02-14") == 2026
    assert daycal.fiscal_year_of("2026-04-01") == 2026
    assert daycal.fiscal_label(2026) == "2026-27"
