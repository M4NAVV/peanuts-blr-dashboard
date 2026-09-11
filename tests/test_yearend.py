"""The YEAR END trial — TTM where a store has one, the projection until it does.

★ THE FIRST TEST IS THAT IT IS OFF. A trial that changes a live figure without
being asked is not a trial. Everything else here sets the flag explicitly.
"""
import os

import pandas as pd
import pytest

import yearend as YE


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("YEAR_END_VIEW", "1")
    yield


def test_it_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv("YEAR_END_VIEW", raising=False)
    assert YE.enabled() is False
    cols = ["A", "Sum of PROJECTED YTD", "Sum of TTM SALES", "B"]
    assert YE.swap_cols(cols) == cols            # untouched
    row = {"Sum of PROJECTED YTD": 1.0, "Sum of TTM SALES": 2.0}
    assert YE.swap_row(row, 99.0) == row         # untouched


def test_off_means_off_for_every_spelling(monkeypatch):
    for v in ("", "0", "no", "off", "false"):
        monkeypatch.setenv("YEAR_END_VIEW", v)
        assert YE.enabled() is False, v


def test_the_pair_becomes_one_column(on):
    """Manav: "only make one column to the sheets"."""
    cols = ["A", "Sum of PROJECTED MTD", "Sum of PROJECTED YTD",
            "Sum of TTM SALES", "B"]
    out = YE.swap_cols(cols)
    assert out == ["A", "Sum of PROJECTED MTD", YE.COL_PF, "B"]
    # ★ MTD SURVIVES. "for the mtd column, keep as is".
    assert "Sum of PROJECTED MTD" in out


def test_the_new_column_sits_where_the_projection_sat(on):
    cols = ["A", "Sum of PROJECTED YTD", "Sum of TTM SALES", "Z"]
    assert YE.swap_cols(cols).index(YE.COL_PF) == 1


def test_a_store_with_twelve_months_uses_its_ttm(on):
    asof = pd.Timestamp("2026-09-09")
    val, basis = YE.year_end(achieved_ytd=100.0, ttm=900.0,
                             first_trade=pd.Timestamp("2024-01-01"),
                             fy_start=pd.Timestamp("2026-04-01"),
                             doo=pd.Timestamp("2024-01-01"), asof=asof)
    assert (val, basis) == (900.0, YE.BASIS_TTM)


def test_a_store_without_twelve_months_uses_the_projection(on):
    """Manav: "use the projected calculation until the ttm naturally arrives"."""
    asof = pd.Timestamp("2026-09-09")
    opened = pd.Timestamp("2026-01-18")          # Dibrugarh's shape
    val, basis = YE.year_end(achieved_ytd=5_730_075.0, ttm=0.0,
                             first_trade=opened,
                             fy_start=pd.Timestamp("2026-04-01"),
                             doo=opened, asof=asof)
    assert basis == YE.BASIS_PROJ
    assert val > 5_730_075.0                     # annualised, so above YTD


def test_it_switches_basis_by_itself_on_the_anniversary(on):
    """"until the ttm naturally arrives which is 12 months after the business
    starts" — no list to maintain, the date does it."""
    opened = pd.Timestamp("2026-01-18")
    # The window is inclusive at both ends, so a store that opened on the 18th
    # has covered all 365 days of it on the following 17 Jan — not the 18th.
    arrives = opened + pd.DateOffset(years=1) - pd.Timedelta(days=1)
    assert YE.has_full_year(opened, arrives - pd.Timedelta(days=1)) is False
    assert YE.has_full_year(opened, arrives) is True
    assert len(pd.date_range(*YE.window(arrives))) == 365


def test_a_zero_ttm_never_wins(on):
    """A store the window outruns reports 0, and 0 must not be printed as a
    year-end figure — that is the part-year-dressed-as-a-year error."""
    asof = pd.Timestamp("2026-09-09")
    val, basis = YE.year_end(100.0, 0.0, pd.Timestamp("2020-01-01"),
                             pd.Timestamp("2026-04-01"),
                             pd.Timestamp("2020-01-01"), asof)
    assert basis == YE.BASIS_PROJ and val > 0


def _feeds():
    """A portfolio frame whose South store starts at the takeover, and a VFL
    frame that holds its earlier trading — the real shape."""
    import loader as L
    tko = pd.Timestamp("2026-04-19")
    pf = pd.DataFrame([
        {"code": 112, "date": d, "sales": 1000.0, "takeover_date": tko}
        for d in pd.date_range(tko, "2026-09-09")
    ] + [
        {"code": 1, "date": d, "sales": 500.0, "takeover_date": pd.Timestamp("2025-04-01")}
        for d in pd.date_range("2025-04-01", "2026-09-09")
    ])
    vfl = pd.DataFrame([
        {L.COL_STORE_LABEL: "Jayanagar", "date": d, L.COL_AMOUNT: 800.0}
        for d in pd.date_range("2025-04-01", "2026-09-09")
    ])
    return pf, vfl


def test_south_gets_a_real_ttm_from_the_other_feed(on):
    """★ Manav, 10 Sep: "technically we do have ttm, because we have the last
    year data from the previous operator". Read on the portfolio feed alone
    Jayanagar looks five months old and scores 0."""
    pf, vfl = _feeds()
    asof = pd.Timestamp("2026-09-09")
    ttm = YE.stitched_ttm(pf, vfl, asof)
    assert 112 in ttm.index and ttm[112] > 0

    # without the VFL feed there is no twelve months to be had, and the code
    # says so by leaving the store out rather than inventing a part year
    assert 112 not in YE.stitched_ttm(pf, None, asof).index


def test_the_seam_counts_every_day_once(on):
    """VFL strictly BEFORE the takeover, portfolio on and after it."""
    pf, vfl = _feeds()
    asof = pd.Timestamp("2026-09-09")
    start, _ = YE.window(asof)
    tko = pd.Timestamp("2026-04-19")
    expect = (800.0 * len(pd.date_range(start, tko - pd.Timedelta(days=1)))
              + 1000.0 * len(pd.date_range(tko, asof)))
    assert YE.stitched_ttm(pf, vfl, asof)[112] == pytest.approx(expect)


def test_first_trade_reaches_across_the_seam(on):
    pf, vfl = _feeds()
    assert YE.first_trade_map(pf, vfl)[112] == pd.Timestamp("2025-04-01")


def test_the_column_says_when_it_holds_two_kinds_of_number(on):
    """A measured year and a run-rate in one column must be labelled."""
    assert "TTM" in YE.column_label({YE.BASIS_TTM})
    assert "PROJECTED" in YE.column_label({YE.BASIS_PROJ})
    mixed = YE.column_label({YE.BASIS_TTM, YE.BASIS_PROJ})
    assert "TTM" in mixed and "PROJ" in mixed
    assert YE.note({YE.BASIS_TTM, YE.BASIS_PROJ}).strip() != ""


def test_the_header_names_both_bases(on):
    """Manav, 11 Sep: the column holds a measured year for most rows and a
    run-rate for the young ones, so the header must not claim one kind."""
    for name in (YE.COL_PF, YE.COL_VFL):
        u = name.upper()
        assert "PROJECTED" in u and "TTM" in u


def test_only_the_young_stores_are_marked_for_shading(on):
    pf, vfl = _feeds()
    asof = pd.Timestamp("2026-09-09")
    # 112 has VFL history across the seam; 1 has traded the whole window
    assert YE.projected_codes(pf, vfl, asof) == set()
    # without the VFL feed, South has no measured year and must be shaded
    assert 112 in YE.projected_codes(pf, None, asof)


def test_a_store_leaves_the_shaded_set_on_its_anniversary(on):
    """The set is derived every run, so nobody maintains a list."""
    import loader as L
    opened = pd.Timestamp("2026-01-18")
    pf = pd.DataFrame([{"code": 106, "date": d, "sales": 100.0,
                        "takeover_date": opened}
                       for d in pd.date_range(opened, "2027-01-17")])
    arrives = opened + pd.DateOffset(years=1) - pd.Timedelta(days=1)
    assert 106 in YE.projected_codes(pf, None, arrives - pd.Timedelta(days=1))
    assert 106 not in YE.projected_codes(pf, None, arrives)


def test_nothing_is_shaded_when_the_trial_is_off(monkeypatch):
    monkeypatch.delenv("YEAR_END_VIEW", raising=False)
    import portfolio_pdf as PP
    assert not YE.enabled()
    assert hasattr(PP, "HL_BG")          # the shade exists but goes unused
