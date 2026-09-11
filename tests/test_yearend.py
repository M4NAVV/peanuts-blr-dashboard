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


# ── the sweep ───────────────────────────────────────────────────────────────
# ★★ THREE TIMES NOW a rule was fixed in one place and left in the others: the
# pieces rule (2 of 14 call sites), the year-end column (1 of 3 row builders),
# and then the pace table Manav found himself — "im sure there will be other
# instances like these, do a thorough sweep". These tests fail if ANY rendered
# surface still offers a year projection when the trial is on.

_PAIR = ("Sum of PROJECTED YTD", "Sum of TTM SALES",
         "Projected YTD", "TTM Sales")


def _no_pair(df, where):
    left = [c for c in df.columns if c in _PAIR]
    assert not left, f"{where} still carries {left}"
    assert any(c in (YE.COL_PF, YE.COL_VFL) for c in df.columns), \
        f"{where} has no year-end column"
    # ★ MTD IS NOT TOUCHED.
    assert any("PROJECTED MTD" in c.upper() or "Projected MTD" in c
               for c in df.columns), f"{where} lost its MTD projection"


def test_every_portfolio_gd_report_is_swept(on):
    import portfolio_loader as PL
    pf = PL.load_portfolio()
    for name, fn in (("gd_sheet", PL.gd_sheet_report),
                     ("brand_wise", PL.brand_wise_gd_report),
                     ("loc_wise", PL.loc_wise_gd_report)):
        _no_pair(fn(pf)[0], name)


def test_every_vfl_gd_report_is_swept(on):
    import loader as L
    v = L.load_data()
    for name, fn in (("brand_wise_gd", L.brand_wise_gd),
                     ("gender_wise_gd", L.gender_wise_gd)):
        _no_pair(fn(v), name)
    out = L.vfl_gd_report(v)
    _no_pair(out[0] if isinstance(out, tuple) else out, "vfl_gd_report")


def test_the_target_sheet_and_its_pace_table_are_swept(on):
    """★ The one Manav found: "the top table of the targets vs achievement
    still has a projected column"."""
    import pandas as pd
    import portfolio_loader as PL
    import report_td as RTD
    pf = PL.load_portfolio()
    sheet = RTD.target_vs_ach(pf, PL.as_of(pf))

    heads = [h for h, _ in RTD._tva_cols()]
    assert "TTM SALES" not in heads and "YEAR END" in heads

    exec_heads = [h for h, _ in RTD._tva_exec_cols()]
    assert "PROJECTED" not in exec_heads, "the pace table still says PROJECTED"
    assert any("TTM" in h for h in exec_heads)

    # the YEAR row is the measured year; the MONTH row is still a run-rate
    rows = RTD.tva_exec_rows(sheet)
    per = {}
    cur = None
    for kind, r in rows:
        if kind == "head":
            cur = r["label"]
        else:
            per.setdefault(cur, {})[r["label"]] = r["projected"]
    ytd = per["YEAR TO DATE"]
    assert ytd["OVERALL"] > 0
    # a scope is the sum of its stores' year-end figures, so the regions add up
    regions = sum(v for k, v in ytd.items() if k != "OVERALL")
    assert abs(regions - ytd["OVERALL"]) < 1.0


def test_a_festival_window_is_left_alone(on):
    """★ NOT EVERY PROJECTION IS A YEAR-END ONE. Festive projects a 45-day
    window to its own tenure; a trailing twelve months answers nothing there,
    so `festive.py` keeps its projection and must not be swept."""
    import festive
    src = open(festive.__file__, encoding="utf-8").read()
    assert "PROJ.project(" in src
    assert "yearend" not in src


def test_the_two_grand_totals_reconcile_exactly(on):
    """★★ Manav, 11 Sep: "yes, reconcile these".

    The GD sheet's grand total read Rs 138.35 Cr and the target sheet's
    Rs 136.16 Cr, with nothing on either page explaining the Rs 2.19 Cr. Both
    were right: the GD sheet carries stores that shut during the year, because
    their sales happened; the target sheet drops them, because a closed store
    has no ongoing target. The difference IS those stores, to the rupee, and
    the target sheet now says which estate it covers.
    """
    import portfolio_loader as PL
    import report_td as RTD

    pf = PL.load_portfolio()
    asof = PL.as_of(pf)
    mets = PL._gd_store_metrics(pf, asof)
    sheet = RTD.target_vs_ach(pf, asof)

    gd = sum(v.get("year_end", 0.0) for v in mets.values())
    tva = sum(r.get("ttm") or 0.0 for r in sheet["rows"])
    closed = sheet["closed_out"]
    gone = sum(mets[c].get("year_end", 0.0) for c in closed if c in mets)

    assert closed, "no store closed in-year; this fixture no longer bites"
    assert abs((gd - gone) - tva) < 1.0, (
        f"GD {gd:,.0f} - closed {gone:,.0f} != target sheet {tva:,.0f}")


def test_only_in_year_closures_are_reported(on):
    """Ten of the fourteen dropped codes shut in an EARLIER year and carry no
    sales in this one. Counting those would overstate what the reader is
    missing, so the note names only the in-year ones."""
    import pandas as pd
    import portfolio_loader as PL
    import report_td as RTD
    import loader as L

    pf = PL.load_portfolio()
    asof = PL.as_of(pf)
    fy0 = pd.Timestamp(asof.year if asof.month >= 4 else asof.year - 1, 4, 1)
    shut = L.closed_map()
    for c in RTD.target_vs_ach(pf, asof)["closed_out"]:
        assert fy0 <= pd.to_datetime(shut[c]) <= asof


def test_the_target_sheet_declares_its_estate(on):
    """A grand total that will not say what it covers cannot be reconciled."""
    src = open("report_td.py", encoding="utf-8").read()
    assert "trading stores only" in src
