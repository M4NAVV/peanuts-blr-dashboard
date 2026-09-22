"""The festive TTM column — the whole run-up, part actual, part last year's tail.

Manav, 21 Sep 2026: *"the days elapsed this year, plus the days yet to elapse
from last year for the 45 day window, or the 30 day window. this ttm is not 12
months, but only the duration which is being tracked in the reports."*

Frames are built inside the test so CI verifies the rules without the feed —
see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import festive as F


def _w(tenure=45, elapsed=16):
    """Durga Puja 2026 closes 20 Oct; last year's fell three weeks earlier."""
    ty_end = pd.Timestamp("2026-10-20")
    ly_end = pd.Timestamp("2025-10-02")
    return F.Window(festival="Durga Puja", tenure=tenure,
                    ty_start=ty_end - pd.Timedelta(days=tenure - 1), ty_end=ty_end,
                    ly_start=ly_end - pd.Timedelta(days=tenure - 1), ly_end=ly_end,
                    elapsed=elapsed,
                    asof=ty_end - pd.Timedelta(days=tenure - elapsed))


def _row(**kw):
    base = dict(new_old="OLD", store="A Store", location="Somewhere", parent="Manyavar",
                location_tl="Bengaluru", closed="", doo="", ly=0.0, ty=0.0,
                ly_full=0.0, day=0.0, projected=0.0)
    base.update(kw)
    base["ttm"] = kw.get("ttm", base["ty"] + base["ly_full"] - base["ly"])
    return base


# --------------------------------------------------------------------------- #
# The rule itself
# --------------------------------------------------------------------------- #
def test_ttm_is_this_year_so_far_plus_last_years_remaining_days():
    w = _w()
    assert F.ttm(ty=500.0, ly=300.0, ly_full=1000.0, closed=None, w=w) == 1200.0


def test_last_years_tail_is_measured_by_day_index_not_by_calendar_date():
    """The festival moves about three weeks a year, so the two windows do not
    sit on the same dates. `ly_full - ly` is days (elapsed+1)..tenure of LAST
    year's window because `ly` is truncated at `ly_cut`, not at this year's date."""
    w = _w(tenure=45, elapsed=16)
    assert w.ly_cut == w.ly_start + pd.Timedelta(days=15)
    assert (w.ly_end - w.ly_cut).days == 45 - 16
    # one unit a day last year: 16 days behind us, 29 still to come
    assert F.ttm(ty=0.0, ly=16.0, ly_full=45.0, closed=None, w=w) == 29.0


def test_last_year_truncated_can_never_exceed_last_year_whole():
    """If it could, the tail would go negative and TTM would understate."""
    for tenure in (30, 45):
        for elapsed in range(1, tenure + 1):
            w = _w(tenure=tenure, elapsed=elapsed)
            assert w.ly_cut <= w.ly_end


def test_a_closed_store_gets_no_tail():
    """Nothing is 'yet to elapse' for a shop that is not open. `projections.project`
    freezes a closed store the same way, so the two columns agree on the rule."""
    w = _w()
    shut = w.asof - pd.Timedelta(days=5)
    assert F.ttm(ty=500.0, ly=300.0, ly_full=1000.0, closed=shut, w=w) == 500.0


def test_a_store_closing_after_the_report_date_still_carries_its_tail():
    """`project` uses `closed <= asof`; TTM must not diverge from it."""
    w = _w()
    later = w.asof + pd.Timedelta(days=3)
    assert F.ttm(ty=500.0, ly=300.0, ly_full=1000.0, closed=later, w=w) == 1200.0


def test_a_new_store_keeps_its_own_figure_and_invents_no_tail():
    w = _w()
    assert F.ttm(ty=800.0, ly=0.0, ly_full=0.0, closed=None, w=w) == 800.0


def test_a_window_that_has_not_opened_has_no_ttm():
    """Same as `projected`, which is 0.0 before a window starts — a card of
    figures for a season that has not traded reads as a reading."""
    w = _w(elapsed=0)
    assert not w.started
    assert F.ttm(ty=0.0, ly=0.0, ly_full=1000.0, closed=None, w=w) == 0.0


# --------------------------------------------------------------------------- #
# The column, on the three sheets of the festive PDF
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("build", ["gd_report", "brand_report", "location_report"])
def test_every_sheet_carries_the_column_last(build):
    """TTM closes the sheet, with its own G/D immediately after it."""
    w = _w()
    f = pd.DataFrame([_row(ty=500.0, ly=300.0, ly_full=1000.0)])
    rep, _ = getattr(F, build)(f, w)
    assert list(rep.columns[-2:]) == ["Sum of TTM 45D", "Sum of GDTTM 45D"]


def test_the_header_names_its_own_window_so_it_cannot_read_as_twelve_months():
    """Plain 'TTM' already means the YEAR-END figure on the G/D sheets."""
    assert F.ttm_col(_w(tenure=45)) == "Sum of TTM 45D"
    assert F.ttm_col(_w(tenure=30)) == "Sum of TTM 30D"


def test_the_column_is_money_not_a_raw_float():
    """A column in none of the money/pct/num buckets prints left-aligned and
    unformatted. See [[feedback-declare-numeric-columns]]."""
    col = F.ttm_col(_w())
    assert col.startswith(F._TTM_PREFIX)
    assert col not in F._LEFT


def test_the_totals_add_up_at_every_level():
    """TTM is a sum, not a rate, so subtotal and Grand Total are plain adds —
    no numerator/denominator pairing to get wrong."""
    w = _w()
    f = pd.DataFrame([
        _row(store="One", ty=500.0, ly=300.0, ly_full=1000.0),
        _row(store="Two", ty=200.0, ly=100.0, ly_full=400.0),
        _row(store="Shut", ty=50.0, ly=80.0, ly_full=600.0, closed="01-09-2026", ttm=50.0),
    ])
    rep, types = F.gd_report(f, w)
    col = F.ttm_col(w)
    # rows come out sorted by store name, not in the order given
    rows = {s: v for s, v, t in zip(rep["STORE NAME"], rep[col], types) if t == "store"}
    grand = [v for v, t in zip(rep[col], types) if t == "grand"]
    assert rows == {"One": 1200.0, "Two": 500.0, "Shut": 50.0}
    assert grand == [sum(rows.values())]


def test_the_existing_columns_are_untouched():
    """Manav: keep everything as is, and add a column."""
    w = _w()
    f = pd.DataFrame([_row(ty=500.0, ly=300.0, ly_full=1000.0)])
    rep, _ = F.gd_report(f, w)
    assert list(rep.columns[:-2]) == F.GD_COLS


# --------------------------------------------------------------------------- #
# The admin pack — the festive report itself since 7 Sep
# --------------------------------------------------------------------------- #
def test_both_store_sheets_of_the_pack_carry_the_column():
    """Guards the wiring, not the arithmetic — the rule is tested above. The
    spec is built inside `build`, so this reads it the way
    `test_festive_admin` reads the portfolio path."""
    import inspect
    import festive_admin as FADM
    src = inspect.getsource(FADM.build)
    assert '("ttm", "money", f"TTM\\n{w.tenure}D")' in src
    assert '("ttm_gd", "gd", f"G/D\\nTTM {w.tenure}D")' in src
    # fed on every row and on the section total, not just declared
    assert '"ttm": r["ttm"]' in src
    assert '"ttm": frame["ttm"].sum()' in src
    assert '"ttm_gd": ttm_gd(r["ttm"], r["ly_full"], r["ty"])' in src
    # both sheets: the held-out one and the comparable one
    assert src.count("] + _ttm") == 2


def test_the_pack_reads_ttm_off_the_figures_both_feeds_build():
    """`build` takes either feed through `store_figures` or `vfl_figures`, so
    both must carry the column the pack now reads."""
    import inspect
    import festive as F
    for fn in (F.store_figures, F.vfl_figures):
        assert '"ttm"' in inspect.getsource(fn), fn.__name__


def test_the_page_one_card_is_summed_off_the_same_rows_as_the_store_sheet():
    """A card and a table on one pack describing the same set must not be able
    to disagree. Recomputing the card from `fig` would let the closed-store
    rule or the membership test move on one side only.
    See [[feedback-same-estate]]."""
    import inspect
    import festive_admin as FADM
    src = inspect.getsource(FADM.build)
    assert 'l2l_ttm = float(f.loc[f["l2l"], "ttm"].sum())' in src
    assert 'f"Full run-up, TTM {w.tenure}D"' in src
    # and it says "—" rather than a figure before the run-up opens
    assert 'if started else "—"' in src


# --------------------------------------------------------------------------- #
# The G/D on TTM — the whole run-up against last year's whole run-up
# --------------------------------------------------------------------------- #
def test_ttm_gd_is_measured_against_last_years_whole_window():
    import festive_admin as FADM
    assert FADM.ttm_gd(ttm=110.0, ly_full=100.0, ty=50.0) == pytest.approx(10.0)


def test_ttm_gd_carries_the_same_gain_as_todays_gd_over_a_bigger_base():
    """`ttm - ly_full` reduces exactly to `ty - ly`, so the two G/Ds differ
    only in what they divide by. TTM's must read closer to flat mid-window —
    that is arithmetic, not a bug, and the pack says so on its face."""
    import festive_admin as FADM
    w = _w(tenure=45, elapsed=16)
    ty, ly, ly_full = 500.0, 300.0, 1000.0
    t = F.ttm(ty, ly, ly_full, None, w)
    assert t - ly_full == ty - ly
    today = (ty - ly) / ly * 100
    whole = FADM.ttm_gd(t, ly_full, ty)
    assert whole == pytest.approx((t - ly_full) / ly_full * 100)
    assert abs(whole) < abs(today)


def test_a_store_with_no_last_year_says_new_rather_than_showing_a_blank():
    """A blank beside a -100% reads as a zero."""
    import festive_admin as FADM
    assert FADM.ttm_gd(ttm=800.0, ly_full=0.0, ty=800.0) == "new"
    assert FADM.ttm_gd(ttm=0.0, ly_full=0.0, ty=0.0) == ""


def test_a_closed_store_reads_its_loss_in_full():
    """It gets no tail, so against last year's whole run-up it is -100%."""
    import festive_admin as FADM
    assert FADM.ttm_gd(ttm=0.0, ly_full=964116.0, ty=0.0) == pytest.approx(-100.0)


def test_a_word_in_a_gd_cell_neither_crashes_nor_takes_the_growth_ink():
    """`gd` cells assumed a number before `new` could appear in one."""
    import festive_admin as FADM
    import inspect
    src = inspect.getsource(FADM.table_image)
    assert 'if isinstance(v, (int, float)) else str(v)' in src
    assert 'if isinstance(val, (int, float)) and not pd.isna(val):' in src


@pytest.mark.parametrize("build", ["gd_report", "brand_report", "location_report"])
def test_the_workbook_sheets_keep_their_own_percentage_convention(build):
    """`Sum of GDYTD` is this year as a PERCENTAGE of last year, 100 = flat —
    not a growth rate. Two columns headed G/D on one sheet must not mean two
    different things, so TTM's follows it."""
    w = _w()
    f = pd.DataFrame([_row(ty=500.0, ly=300.0, ly_full=1000.0)])
    rep, _ = getattr(F, build)(f, w)
    assert list(rep.columns[-2:]) == ["Sum of TTM 45D", "Sum of GDTTM 45D"]
    # 1200 of 1000 = 120.00, in the workbook's convention, not "+20.0%"
    assert rep["Sum of GDTTM 45D"].iloc[0] == "120.00"


def test_the_workbook_sheet_says_new_where_there_is_no_last_year():
    w = _w()
    f = pd.DataFrame([_row(ty=800.0, ly=0.0, ly_full=0.0)])
    rep, _ = F.gd_report(f, w)
    assert rep["Sum of GDTTM 45D"].iloc[0] == "new"


def test_the_page_one_card_shows_the_growth_beside_the_landing_figure():
    import inspect
    import festive_admin as FADM
    src = inspect.getsource(FADM.build)
    assert 'l2l_ttm_gd = ttm_gd(l2l_ttm, fig["ly_full"], fig["ty"])' in src
    assert 'f"   {l2l_ttm_gd:+,.1f}%"' in src
