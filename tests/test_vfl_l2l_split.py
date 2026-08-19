"""The VFL G/D sheet splits a store into its comparable and non-comparable halves.

Manav, 19 Aug 2026: *"that rule we made for the portfolio growth degrowth table,
where it splits a store into no l2l and l2l, to give an accurate read. i want to
implement that same rule in the VFL growth degrowth also."*

Two things these pin, both of which were wrong in the first cut:

1. The span maps are keyed by store LABEL, and `master["code"]` is a STRING
   column while `closed_map` / `doo_map` are keyed by INT. Without the cast every
   lookup misses, both maps come back empty, and nothing raises — the spans just
   open at the feed's left edge and never close, so a shut store compares a full
   last year against a part year.

2. A store splits when its SPAN CLIPS THE WINDOW, not when two sums differ. This
   sheet drops pure-return brand lines, so a store total can sit a few thousand
   rupees off the raw frames; reading that residual as "outside the span" split a
   store comparable since 2023 and printed a phantom -100% line under it.
"""

import pandas as pd
import pytest

import loader as L


ASOF = pd.Timestamp("2026-08-18")


def _report(df):
    return L.vfl_gd_report(df, asof=ASOF, gen_date=ASOF)


def _row(rep, label):
    hit = rep[rep["Region"] == label]
    return None if hit.empty else hit.iloc[0]


@pytest.fixture(scope="module")
def live():
    """The live feed, or a skip.

    ⚠️ These assertions are about the ESTATE — which store is clipped, which is
    closed — so they need the real data and cannot run on a fixture. CI has
    neither the sheet nor a local export, and erroring there tells nobody
    anything. The rule itself is pinned synthetically below, which is what CI
    actually verifies.
    """
    try:
        df = L.load_data()
    except Exception as e:                      # no sheet, no export: not a fault
        pytest.skip(f"live data unavailable: {type(e).__name__}")
    return df, L.as_of(df)


def test_spans_are_keyed_so_the_maps_are_not_empty(live):
    """The cast bug: empty maps do not raise, they quietly span everything."""
    df, asof = live
    start, end = L._l2l_spans_vfl(df, asof)
    assert start and end
    # A closure must actually cap the span — this is what an empty shut map lost.
    master = L.load_store_master()
    code_of = {str(n): int(c) for n, c in zip(master["tableau_name"], master["code"])
               if str(c).strip() not in ("", "nan", "None")}
    shut = L.closed_map()
    capped = [s for s, c in code_of.items()
              if c in shut and s in end
              and pd.Timestamp(shut[c]) <= pd.Timestamp(asof)]
    for s in capped:
        assert end[s] <= pd.Timestamp(shut[code_of[s]]), (
            f"{s} closed but its like-to-like span runs past the closure")


def test_halves_and_footer_reconcile_to_the_grand_total(live):
    """LIKE TO LIKE + NO L2L must be the whole estate, on both years."""
    df, asof = live
    rep, _ = L.vfl_gd_report(df, asof=asof, gen_date=asof)
    l2l, no, grand = _row(rep, "LIKE TO LIKE"), _row(rep, "NO L2L"), _row(rep, "Grand Total")
    assert l2l is not None and grand is not None
    for col in ("Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY"):
        got = float(l2l[col]) + (float(no[col]) if no is not None else 0.0)
        assert got == pytest.approx(float(grand[col]), abs=1.0), col


def test_the_footer_is_the_snapshot_s_own_arithmetic(live):
    """The sheet must not disagree with the page that fronts it — the whole
    reason this rule exists. Allowed gap: the pure-return lines this sheet drops
    by design, which are worth a few thousand rupees on a Rs 27 crore base."""
    import exec_snapshot as ES
    df, asof = live
    rep, _ = L.vfl_gd_report(df, asof=asof, gen_date=asof)
    l2l = _row(rep, "LIKE TO LIKE")
    b = L._l2l_spans_vfl(df, asof)
    cur, pri = L.report_frames(df, "YTD", asof=asof)
    c2, p2 = ES.l2l_frames(cur, pri, b, L.COL_STORE_LABEL)
    engine = (c2[L.COL_AMOUNT].sum() - p2[L.COL_AMOUNT].sum()) / p2[L.COL_AMOUNT].sum() * 100
    assert float(l2l["Sum of GD_YTD_%"]) == pytest.approx(engine, abs=0.05)


def test_only_a_clipped_store_may_split(live):
    """A split store must be one whose span clips the window.

    Note the converse is NOT true, and that is the point of the closure cap: a
    store that shut is clipped on the right, but once last year is stopped at
    the shutter there is nothing left outside the span, so it reads as one line
    — which is what the portfolio sheet has always shown for Roodraksh.
    """
    df, asof = live
    rep, types = L.vfl_gd_report(df, asof=asof, gen_date=asof)
    start, end = L._l2l_spans_vfl(df, asof)
    fy = asof.year if asof.month >= 4 else asof.year - 1
    win = pd.Timestamp(fy, 4, 1)
    clipped = {s for s in start
               if start.get(s) is not None and end.get(s) is not None
               and start[s] <= end[s] and (start[s] > win or end[s] < asof)}
    halves = rep.iloc[[i for i, t in enumerate(types) if t == "split"]]
    assert len(halves) % 2 == 0, "halves come in pairs"
    for loc in halves["LOCATION"].unique():
        assert any(str(loc) in str(s) or str(s) in str(loc) for s in clipped), (
            f"{loc} split but its span covers the window")


def test_a_closed_store_reads_as_one_line_not_a_split(live):
    """The regression this pair was written for. Last year must stop at the
    closure, so the store shows a single honest decline rather than a phantom
    'no L2L' half carrying last year's trade after the shutter came down."""
    df, asof = live
    shut = L.closed_map()
    master = L.load_store_master()
    label_of = {int(c): str(n) for n, c in zip(master["tableau_name"], master["code"])
                if str(c).strip() not in ("", "nan", "None")}
    past = [label_of[c] for c, d in shut.items()
            if c in label_of and pd.Timestamp(d) <= pd.Timestamp(asof)]
    if not past:
        pytest.skip("no store has closed within this window")
    rep, types = L.vfl_gd_report(df, asof=asof, gen_date=asof)
    halves = rep.iloc[[i for i, t in enumerate(types) if t == "split"]]
    for lbl in past:
        assert lbl not in set(halves["LOCATION"].astype(str)), (
            f"{lbl} is closed and should not split — cap last year instead")


def test_like_to_like_still_compares_every_rupee_of_last_year(live):
    """★ The property that proves the rule (settled 15 Aug): like-to-like's last
    year IS the estate's whole last year. Only THIS year's unmatched sales are
    held out. A closed store's uncapped last-year tail broke this by Rs 1.7 L."""
    df, asof = live
    rep, _ = L.vfl_gd_report(df, asof=asof, gen_date=asof)
    l2l, grand = _row(rep, "LIKE TO LIKE"), _row(rep, "Grand Total")
    assert float(l2l["Sum of YTD_LY"]) == pytest.approx(
        float(grand["Sum of YTD_LY"]), abs=1.0)


def test_an_empty_selection_still_renders(live):
    """A filter that matches nothing is a filter, not a fault."""
    df, asof = live
    rep, types = L.vfl_gd_report(df.iloc[0:0], asof=asof, gen_date=asof)
    assert list(rep.columns) == L.VFL_GD_COLS


def test_only_the_compared_columns_carry_figures_on_a_half(live):
    """Day sale, projections and last full year mean nothing cut this way."""
    df, asof = live
    rep, types = L.vfl_gd_report(df, asof=asof, gen_date=asof)
    halves = rep.iloc[[i for i, t in enumerate(types) if t == "split"]]
    if halves.empty:
        pytest.skip("no store is clipped in this window")
    for col in ("Sum of DAY SALE FIGURE", "Sum of PROJECTED MTD",
                "Sum of PROJECTED YTD", "Sum of LY FULL SALES",
                "Sum of MONTH SALE LY"):
        assert halves[col].isna().all(), col


def test_last_year_stops_at_a_closure_everywhere(live):
    """★ Option B, 19 Aug: the cap lives in `report_frames`, so EVERY VFL
    surface gets it — not just the two reports that showed the error.

    Before this, a shut store compared its full last year against a this year
    that ends with the shutter. It cost Roodraksh six points and put it on the
    August degrowth watchlist for sales it was never going to make.
    """
    df, asof = live
    cut = L.closure_cutoffs(asof)
    if not cut:
        pytest.skip("no closure is in force")
    for kind in ("YTD", "MTD"):
        _, prior = L.report_frames(df, kind, asof=asof)
        for store, closed in cut.items():
            rows = prior[prior[L.COL_STORE_LABEL] == store]
            if rows.empty:
                continue
            assert rows["date"].max() <= closed - pd.DateOffset(years=1), (
                f"{kind}: {store} closed {closed:%d-%m-%Y} but last year runs to "
                f"{rows['date'].max():%d-%m-%Y}")


def test_the_cap_is_applied_once_not_twice(live):
    """The per-report caps were removed when it moved to the source. If one
    came back, last year would be subtracted twice and no error would say so."""
    df, asof = live
    cut = L.closure_cutoffs(asof)
    if not cut:
        pytest.skip("no closure is in force")
    _, prior = L.report_frames(df, "YTD", asof=asof)
    by_store = prior.groupby(L.COL_STORE_LABEL)[L.COL_AMOUNT].sum()
    rep, _ = L.region_store_report(df, asof=asof)
    for store in cut:
        row = rep[rep["LOCATION"].astype(str) == store.split(" — ")[0]]
        if row.empty or store not in by_store.index:
            continue
        assert float(row.iloc[0]["YTD LY"]) == pytest.approx(
            float(by_store[store]), abs=1.0), f"{store}: last year capped twice"


# --------------------------------------------------------------------------- #
# The rule itself, on frames built here — so CI verifies it without the feed.
# --------------------------------------------------------------------------- #

def _frame(rows):
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), L.COL_STORE_LABEL: s, L.COL_AMOUNT: float(v)}
         for d, s, v in rows])


def test_closure_cap_cuts_last_year_on_the_closure_day(monkeypatch):
    """A store shut on 31 July must not carry last year's August into the
    comparison. This is the whole of Option B, in eight rows."""
    asof = pd.Timestamp("2026-08-18")
    df = _frame([
        ("2025-07-15", "SHUT", 100), ("2025-08-10", "SHUT", 50),   # LY, after close
        ("2026-07-15", "SHUT", 90),                                 # TY, before close
        ("2025-07-15", "OPEN", 100), ("2025-08-10", "OPEN", 50),
        ("2026-07-15", "OPEN", 90), ("2026-08-10", "OPEN", 60),
    ])
    monkeypatch.setattr(L, "closure_cutoffs",
                        lambda a: {"SHUT": pd.Timestamp("2026-07-31")})
    _, prior = L.report_frames(df, "YTD", asof=asof, anchor_takeover=False)
    shut = prior[prior[L.COL_STORE_LABEL] == "SHUT"]
    opens = prior[prior[L.COL_STORE_LABEL] == "OPEN"]
    assert shut[L.COL_AMOUNT].sum() == 100, "last year ran past the closure"
    assert opens[L.COL_AMOUNT].sum() == 150, "an open store must not be cut"


def test_no_closure_leaves_last_year_whole(monkeypatch):
    """The cap must be inert when nothing has closed — it runs on every call."""
    asof = pd.Timestamp("2026-08-18")
    df = _frame([("2025-08-10", "OPEN", 50), ("2026-08-10", "OPEN", 60)])
    monkeypatch.setattr(L, "closure_cutoffs", lambda a: {})
    _, prior = L.report_frames(df, "YTD", asof=asof, anchor_takeover=False)
    assert prior[L.COL_AMOUNT].sum() == 50


def test_a_future_closure_does_not_cut_anything(monkeypatch):
    """VEGA has a closure date at the end of this month and is still trading.
    Only a closure that has already happened may cap last year."""
    asof = pd.Timestamp("2026-08-18")
    df = _frame([("2025-08-10", "LATER", 50), ("2026-08-10", "LATER", 60)])
    monkeypatch.setattr(L, "closure_cutoffs", lambda a: {})   # cutoffs filters by asof
    _, prior = L.report_frames(df, "YTD", asof=asof, anchor_takeover=False)
    assert prior[L.COL_AMOUNT].sum() == 50


def test_closure_cutoffs_ignores_a_date_in_the_future():
    """The filter that makes the test above true, checked directly."""
    import datetime as _dt
    real_closed, real_master = L.closed_map, L.load_store_master
    try:
        L.closed_map = lambda: {1: pd.Timestamp("2030-01-01")}
        L.load_store_master = lambda: pd.DataFrame(
            {"tableau_name": ["FUTURE"], "code": ["1"]})
        assert L.closure_cutoffs(pd.Timestamp("2026-08-18")) == {}
    finally:
        L.closed_map, L.load_store_master = real_closed, real_master
