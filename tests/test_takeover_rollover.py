"""A takeover starts a store's year ONCE — the year after, it counts from 1 April.

Found 19 Oct 2026, the third 1-April-2027 bomb of its kind (after MW Data and the
NEW/OLD order). The anchor was the takeover's month and day in EVERY year, so
from FY27-28 South's year would have begun on 19 April 2027: 18 days of our own
trading dropped every year, and South blank in every YTD and rolling report from
1 to 18 April. Self-contained inputs, so CI runs it without the feed.
"""

import pandas as pd

import category_pdf as C
import loader as L

SOUTH, EAST = "Jayanagar", "Siliguri"


def _feed(monkeypatch):
    monkeypatch.setattr(L, "takeover_map", lambda: {SOUTH: pd.Timestamp("2026-04-19"),
                                                    EAST: pd.Timestamp("2025-04-01")})
    monkeypatch.setattr(L, "closure_cutoffs", lambda asof: {})
    days = pd.date_range("2025-04-01", "2027-08-31")
    return pd.concat([pd.DataFrame({L.COL_STORE_LABEL: s, "date": days, L.COL_AMOUNT: 1.0})
                      for s in (SOUTH, EAST)], ignore_index=True)


def _starts(cur, pri, store):
    c, p = cur[cur[L.COL_STORE_LABEL] == store]["date"], pri[pri[L.COL_STORE_LABEL] == store]["date"]
    return (c.min(), p.min())


def test_the_takeover_year_still_starts_at_the_takeover(monkeypatch):
    df = _feed(monkeypatch)
    cur, pri = L.report_frames(df, "YTD", asof="2026-10-19")
    assert _starts(cur, pri, SOUTH) == (pd.Timestamp("2026-04-19"), pd.Timestamp("2025-04-19"))
    assert _starts(cur, pri, EAST) == (pd.Timestamp("2026-04-01"), pd.Timestamp("2025-04-01"))


def test_the_year_after_counts_from_1_april(monkeypatch):
    df = _feed(monkeypatch)
    for kind in ("YTD", "MTD"):
        cur, pri = L.report_frames(df, kind, asof="2027-04-25")
        assert _starts(cur, pri, SOUTH) == (pd.Timestamp("2027-04-01"), pd.Timestamp("2026-04-01")), kind


def test_south_is_not_blank_in_the_first_days_of_the_next_year(monkeypatch):
    df = _feed(monkeypatch)
    cur, _ = L.report_frames(df, "YTD", asof="2027-04-05")
    assert (cur[L.COL_STORE_LABEL] == SOUTH).sum() == 5
    cur, _ = C.rolling_frames(df, pd.Timestamp("2027-04-05"), 30)
    assert (cur[L.COL_STORE_LABEL] == SOUTH).sum() == 30


def test_only_takeovers_inside_the_year_are_named(monkeypatch):
    _feed(monkeypatch)
    assert set(L.takeovers_in_fy(2026)) == {SOUTH}
    assert L.takeovers_in_fy(2027) == {}
    assert L.takeovers_in_fy(2025) == {}          # East's 1 April IS the year start


def test_a_rolling_window_runs_across_the_year_end(monkeypatch):
    """Anchored to the fiscal year, every rolling window stopped at 1 April."""
    df = _feed(monkeypatch)
    for store in (SOUTH, EAST):
        cur, pri = C.rolling_frames(df, pd.Timestamp("2027-04-05"), 30)
        assert (cur[L.COL_STORE_LABEL] == store).sum() == 30, store
    # …but still never before the takeover itself
    cur, _ = C.rolling_frames(df, pd.Timestamp("2026-05-01"), 30)
    assert cur[cur[L.COL_STORE_LABEL] == SOUTH]["date"].min() == pd.Timestamp("2026-04-19")
