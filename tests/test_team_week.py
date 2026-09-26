"""The team detail sheet reports a WEEK where it used to report a day.

Manav, 26 Sep 2026: *"these reports that we make, can we also have weekly data
in this. instead of the day data, make it week, gives more insight."* He chose
a rolling seven days over week-to-date when asked.

Frames are built here, so these run in CI with no feed —
see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import loader as L
import salespeople as SP

STORE = "Jayanagar"


def _feed(days, store=STORE):
    """`days` is {date: [(salesperson, bill, amount), …]}."""
    rows = []
    for d, sales in days.items():
        for who, bill, amt in sales:
            rows.append({"date": pd.Timestamp(d), L.COL_STORE_LABEL: store,
                         "SALESPERSON_NO": who, L.COL_SALESPERSON: who,
                         L.COL_BILL_UID: bill, L.COL_AMOUNT: float(amt),
                         "Bill Quantity": 1.0})
    f = pd.DataFrame(rows)
    f["date"] = pd.to_datetime(f["date"])
    return f


def _kpi(f, asof):
    return L.salesperson_kpis(f, asof=pd.Timestamp(asof))


# --------------------------------------------------------------------------- #
# What the week IS
# --------------------------------------------------------------------------- #
def test_the_week_is_seven_days_ending_on_the_last_settled_day():
    f = _feed({"2026-09-19": [("A", "b1", 100)],
               "2026-09-25": [("A", "b2", 100)]})
    k = _kpi(f, "2026-09-25")
    lo, hi = k.attrs["week"]
    assert (hi - lo).days == 6 and hi == k.attrs["day"]
    assert hi == pd.Timestamp("2026-09-25")


def test_it_is_a_rolling_week_not_monday_to_date():
    """★ THE CHOICE HE MADE. Week-to-date on a Tuesday is two days — barely
    more than the day column it replaced. 22 Sep 2026 is a Tuesday: a
    Monday-to-date week would start on the 21st and miss the weekend, which is
    most of a shop's month."""
    f = _feed({"2026-09-19": [("A", "b1", 500)],     # Saturday
               "2026-09-20": [("A", "b2", 700)],     # Sunday
               "2026-09-22": [("A", "b3", 100)]})    # Tuesday
    k = _kpi(f, "2026-09-22")
    assert k.attrs["week"][0] == pd.Timestamp("2026-09-16")
    assert float(k["w_sales"].iloc[0]) == 1300.0      # the weekend is in it


def test_the_week_ends_on_the_settled_day_not_the_feeds_newest_date():
    """★ The night fill carries takings with no bills. A week keyed to the
    feed's last date would end on a day nobody billed in.
    See [[feedback-provisional-day]]."""
    f = _feed({"2026-09-24": [("A", "b1", 400)]})
    fill = pd.DataFrame([{"date": pd.Timestamp("2026-09-25"),
                          L.COL_STORE_LABEL: STORE, "SALESPERSON_NO": None,
                          L.COL_SALESPERSON: "(PROVISIONAL)",
                          L.COL_BILL_UID: None, L.COL_AMOUNT: 90000.0,
                          "Bill Quantity": 1.0}])
    k = _kpi(pd.concat([f, fill], ignore_index=True), "2026-09-25")
    assert k.attrs["week"][1] == pd.Timestamp("2026-09-24")
    assert float(k["w_sales"].iloc[0]) == 400.0


def test_the_week_contains_the_day_and_sits_inside_the_month():
    f = _feed({"2026-09-01": [("A", "b0", 900)],
               "2026-09-20": [("A", "b1", 300)],
               "2026-09-25": [("A", "b2", 200)]})
    k = _kpi(f, "2026-09-25")
    d, w, m = (float(k[c].iloc[0]) for c in ("d_sales", "w_sales", "m_sales"))
    assert d == 200 and w == 500 and m == 1400
    assert d <= w <= m


def test_a_person_quiet_all_week_reads_zero_not_blank():
    f = _feed({"2026-09-02": [("A", "b1", 500)],
               "2026-09-25": [("B", "b2", 500)]})
    k = _kpi(f, "2026-09-25").set_index("ID")
    assert float(k.loc["A", "w_sales"]) == 0.0
    assert float(k.loc["A", "m_sales"]) == 500.0


# --------------------------------------------------------------------------- #
# What the SHEET does with it
# --------------------------------------------------------------------------- #
def test_the_first_block_of_the_detail_sheet_is_the_week():
    assert SP._PERIODS[0] == ("w", "WEEK")
    assert [t for _k, t in SP._PERIODS] == ["WEEK", "MTD", "YTD"]
    assert not any(c.startswith("DAY ") for c in SP._D_ORDER)
    for m in ("SALES", "UNITS", "ABV", "ABS", "SINGLE"):
        assert f"WEEK {m}" in SP._D_ORDER


def test_every_week_column_is_declared_in_a_bucket():
    """A column in none of money/pct/num/whole prints as a raw float,
    left-aligned. Four instances and counting —
    see [[feedback-declare-numeric-columns]]."""
    declared = set(SP._D_MONEY) | set(SP._D_PCT) | set(SP._D_NUM) | set(SP._D_WHOLE)
    identity = {"TOP", "SALESPERSON", "SELLING FOR"}
    missing = [c for c in SP._D_ORDER if c not in declared | identity]
    assert not missing, missing


def test_the_total_row_carries_every_week_measure():
    f = _feed({"2026-09-25": [("A", "b1", 1000), ("B", "b1", 1200),
                              ("A", "b2", 800)]})
    rows, types, meta = SP.store_table(L, f, pd.Timestamp("2026-09-25"), STORE)
    total = rows[types.index("subtotal")]
    for key, _label in SP._MEASURES:
        assert f"w_{key}" in total, key
    assert float(total["w_sales"]) == 3000.0
    # ★ two salespeople on one bill is ONE bill for the store
    assert float(total["w_abv"]) == pytest.approx(3000.0 / 2)


def test_the_sheet_names_the_weeks_own_dates():
    """★ "WEEK" alone could mean the calendar week, the last seven days, or
    whatever the reader has in mind. Printed as 19–25 Sep it means one thing."""
    import inspect
    src = inspect.getsource(SP.detailed_sheet)
    assert "_wk[0]:%d %b" in src and "_wk[1]:%d %b" in src
    assert "7 days to the" in src


def test_the_zero_in_red_rule_followed_the_column():
    """His 23 Sep rule was zero sales for the day, the month or the year. The
    day column is gone, so the rule is the week's — not a dangling reference to
    a column that no longer exists."""
    import inspect
    src = inspect.getsource(SP.detailed_sheet)
    assert '("WEEK SALES", "MTD SALES", "YTD SALES")' in src
    assert '"DAY SALES"' not in src


def test_the_star_and_the_pill_moved_with_the_block():
    assert SP._STAR_ON[0][0] == "w_sales"
    assert not any(c == "d_sales" for c, *_rest in SP._STAR_ON)
    import inspect
    assert '("Top this week", _who("w_sales"))' in \
        inspect.getsource(SP.detailed_sheet)


def test_the_pointer_sheet_still_reports_the_day():
    """★ HE CHANGED ONE REPORT. The pointer sheet's question is "who sold
    yesterday", and a week does not answer it."""
    assert "DAY SALES" in SP._ORDER and "DAY SALES" in SP._MONEY
    import inspect
    assert "d_sales" in inspect.getsource(SP.pointer_sheet)
