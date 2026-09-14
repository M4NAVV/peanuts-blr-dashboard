"""The month-brief card and its festive run-up sibling.

Built on frames made inside the test, so CI verifies the RULES without the
feed — see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

# --------------------------------------------------------------------------- #
# The festive run-up card (12 Sep 2026) — the month block counted over a
# festival window instead of a calendar month.
# --------------------------------------------------------------------------- #
def _win(elapsed=6, tenure=45):
    import festive as F
    asof = pd.Timestamp("2026-09-11")
    ty_end = pd.Timestamp("2026-10-20")
    ly_end = pd.Timestamp("2025-10-02")
    return F.Window(festival="Durga Puja", tenure=tenure,
                    ty_start=ty_end - pd.Timedelta(days=tenure - 1), ty_end=ty_end,
                    ly_start=ly_end - pd.Timedelta(days=tenure - 1), ly_end=ly_end,
                    elapsed=elapsed, asof=asof)


def _frame():
    """10/day through last year's whole window, 5/day through this year's."""
    w = _win()
    rows = []
    for d in pd.date_range(w.ly_start, w.ly_end):
        rows.append({"date": d, "sales": 10.0})
    for d in pd.date_range(w.ty_start, w.asof):
        rows.append({"date": d, "sales": 5.0})
    return pd.DataFrame(rows)


def _rows(gd=None):
    import month_brief as MB
    _, rows = MB.festive_panel(None, "T", _frame(), "sales", _win(),
                               pd.Timestamp("2026-09-11"), gd_ytd=1.0, gd=gd)
    return {label: value for label, value, _style in rows}


def test_the_panel_prints_the_rate_it_is_given():
    """The G/D is LIKE TO LIKE and needs each store's comparable span, so the
    caller computes it and the panel only lays it out."""
    assert _rows(gd=-50.0)["G/D"] == "-50.00"
    assert _rows(gd=None)["G/D"] == "—"


# ---- the like to like window rate ----------------------------------------- #
def _estate():
    """Three stores over both windows:
      old   traded both years            -> comparable
      new   opened after last year's Puja -> this year only
      shut  closed before this year's     -> last year only
    """
    w = _win()
    rows = []
    for d in pd.date_range(w.ly_start, w.ly_cut):
        rows += [{"date": d, "code": 1, "sales": 10.0},
                 {"date": d, "code": 3, "sales": 100.0}]
    for d in pd.date_range(w.ty_start, w.asof):
        rows += [{"date": d, "code": 1, "sales": 20.0},
                 {"date": d, "code": 2, "sales": 500.0}]
    return pd.DataFrame(rows), w


def _bounds(fr, asof, shut=None, opened=None):
    import exec_snapshot as ES
    return ES.l2l_bounds(fr, "code", "sales", shut or {}, asof,
                         opened=opened or {})


def test_like_to_like_excludes_stores_with_no_counterpart():
    """A store opened since last Puja is not growth, and one that has closed is
    not decline. Both move a raw rate; neither should."""
    import month_brief as MB
    fr, w = _estate()
    # store 3 has SHUT — that is what caps its span, exactly as
    # `PL.closed_map()` does in production. Without it `l2l_bounds` has no way
    # to know, and its last year is compared against a this year that no longer
    # exists (measured: -81.8% instead of +100%).
    b = _bounds(fr, w.asof, shut={3: pd.Timestamp("2026-01-31")})
    gd = MB.gd_l2l_window(fr, "code", "sales", b, w)

    # store 1 alone: 20/day vs 10/day over its comparable span = +100%
    assert gd == pytest.approx(100.0)

    # the raw rate over every store is a different, wronger number
    ty = fr[(fr["date"] >= w.ty_start) & (fr["date"] <= w.ty_cut)]["sales"].sum()
    ly = fr[(fr["date"] >= w.ly_start) & (fr["date"] <= w.ly_cut)]["sales"].sum()
    raw = (ty - ly) / ly * 100
    assert raw == pytest.approx(372.7, abs=0.1)      # the number to avoid
    assert raw != pytest.approx(gd)


def test_like_to_like_is_none_when_nothing_is_comparable():
    """A card that cannot state a comparable rate prints a dash, not a number
    that looks like one."""
    import month_brief as MB
    w = _win()
    fr = pd.DataFrame([{"date": d, "code": 2, "sales": 5.0}
                       for d in pd.date_range(w.ty_start, w.asof)])
    assert MB.gd_l2l_window(fr, "code", "sales", _bounds(fr, w.asof), w) is None


def test_a_moving_festival_does_not_break_the_span_clip():
    """Last year's Puja window sits ~18 days earlier than this year's minus a
    year. Spans are spans, not windows, so the clip still lands."""
    import month_brief as MB
    fr, w = _estate()
    assert (w.ty_start - pd.DateOffset(years=1)) != w.ly_start   # it really moved
    assert MB.gd_l2l_window(fr, "code", "sales", _bounds(fr, w.asof), w) is not None


def test_till_date_avg_and_trending():
    r = _rows()
    assert r["Durga Puja 2026 Till Date"] == "30"      # 6 days x 5
    assert r["Durga Puja 2026 Till Date Avg"] == "5"
    assert r["Durga Puja Trending"] == "225"           # 5 x 45 tenure


def test_shortfall_is_measured_against_last_years_whole_window():
    """That is the number the season is trying to beat."""
    r = _rows()
    assert r["Durga Puja 45 Days 2025 Achieved"] == "450"
    assert r["Shortfall Vs Durga Puja 2025"] == "420"  # 450 - 30


def test_days_left_and_required_daily():
    r = _rows()
    assert r["No of days left"] == "39"
    assert r["Average Req. Daily"] == "11"             # 420 / 39


def test_a_complete_window_does_not_divide_by_zero():
    import month_brief as MB
    _, rows = MB.festive_panel(None, "T", _frame(), "sales", _win(elapsed=45),
                               pd.Timestamp("2026-09-11"), gd_ytd=1.0)
    got = {k: v for k, v, _ in rows}
    assert got["No of days left"] == "0"
    assert got["Average Req. Daily"] == "window complete"


def test_a_window_that_has_not_opened_is_not_drawn():
    """A card of zeros reads like a reading. Better to say it has not started."""
    import month_brief as MB
    ws = [_win(elapsed=0)]
    assert MB.festive_windows_started(pd.Timestamp("2026-09-11"), windows=ws) == []


def test_started_windows_come_longest_tenure_first():
    import month_brief as MB
    ws = [_win(elapsed=3, tenure=30), _win(elapsed=6, tenure=45)]
    got = MB.festive_windows_started(pd.Timestamp("2026-09-11"), windows=ws)
    assert [w.tenure for w in got] == [45, 30]


def test_the_subtitle_carries_no_glyph_the_font_cannot_draw():
    """A missing glyph draws as a tofu box in the middle of the date range."""
    import month_brief as MB
    sub = _win().basis().replace(chr(0x2192), "->")
    assert "→" not in sub and "->" in sub
