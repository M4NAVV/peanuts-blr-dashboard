"""Bills are the distinct bill numbers, and they tie to the POS exactly.

★ WHAT THIS FILE IS REALLY FOR. On 30 Aug an audit of Orion Mall's 1-29 August
against the GINESYS POS showed sales agreeing to Rs 78 and the bill count 21
short — 430 against 451. Twenty-two bills in that window carried a return line
as well as sale lines, and 430 + 22 = 452. One away. A rule counting an
exchange as two memos was written, tested, and shipped that morning.

⚠ THE 21 WERE NOT EXCHANGES. THE DAY WAS NOT FINISHED. The feed's 29 August was
still filling; the POS report had been printed on the 30th against a settled
day. When the feed completed, the same window gave exactly 451 distinct bills
and the new rule was counting the exchanges twice — Orion's ABV Rs 8,073
against the POS's Rs 8,467, the same error it was written to fix, inverted.

So these tests now pin the plain count, and the reconciliation runs on a window
that ENDS BEFORE THE FEED'S LAST DAY — because the last day is the one that can
still change, and a shortfall in it will always find a plausible explanation
among whatever happens to be nearby.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import loader as L                                          # noqa: E402


def _f(rows):
    """rows: [(bill, amount)]"""
    return pd.DataFrame({L.COL_BILL_UID: [r[0] for r in rows],
                         L.COL_AMOUNT: [r[1] for r in rows]})


def test_a_plain_sale_is_one_bill():
    assert L.bill_count(_f([("A", 100), ("A", 200)])) == 1


def test_an_exchange_is_still_one_bill():
    """★ THE REVERT. Sale lines and a return line on one bill number are one
    bill — the POS counts it that way too, once its day has settled."""
    assert L.bill_count(_f([("A", 1500), ("A", 4499), ("A", -4999)])) == 1


def test_a_return_only_bill_is_one_bill():
    assert L.bill_count(_f([("A", -999)])) == 1


def test_bills_are_counted_once_each():
    assert L.bill_count(_f([("A", 100), ("B", 200), ("B", -50), ("C", -10)])) == 3


def test_an_empty_frame_counts_nothing():
    assert L.bill_count(_f([])) == 0
    assert L.bill_count(pd.DataFrame()) == 0


def test_every_bill_count_in_the_pack_uses_this_one_definition():
    """Five places counted bills. If a new one appears and does its own
    `nunique`, the sheet and the till can drift apart again."""
    import re
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "loader.py"), encoding="utf-8").read()
    body = src.split("def bill_count", 1)[1].split("\ndef ", 1)[1]
    stray = re.findall(r"\[COL_BILL_UID\]\.nunique\(\)", body)
    assert not stray, f"{len(stray)} bill count(s) bypass bill_count()"
    # ★ AND THE GROUPBY SPELLING, which the line above never saw. Seven
    # aggregations counted bills as `(COL_BILL_UID, "nunique")` inside a
    # named-agg — the same definition, written a second way, and invisible to a
    # test that claimed every bill count went through one place.
    agg = re.findall(r'\(COL_BILL_UID,\s*"nunique"\)', body)
    assert not agg, (f"{len(agg)} groupby bill count(s) spell it out instead of "
                     f"using BILLS_AGG")


def test_orion_august_ties_to_the_pos_exactly():
    """The real reconciliation, on a SETTLED window.

    GINESYS, 1-29 Aug 2026: net sales 38,18,420 · 451 memos · ABV Rs 8,467.
    """
    try:
        df = L.load_data()
    except Exception as e:
        import pytest
        pytest.skip(f"needs live data: {e}")
    end = pd.Timestamp(2026, 8, 29)
    if df["date"].max() <= end:
        import pytest
        pytest.skip("the window's last day is still the feed's last day — "
                    "it can still change, so there is nothing to reconcile against")
    d = df[(df[L.COL_STORE_LABEL] == "Orion Mall")
           & (df["date"] >= pd.Timestamp(2026, 8, 1)) & (df["date"] <= end)]
    if d.empty:
        import pytest
        pytest.skip("Orion's August is not in this feed")
    bills = L.bill_count(d)
    assert bills == 451, f"{bills} bills against the POS's 451"
    abv = float(d[L.COL_AMOUNT].sum()) / bills
    assert abs(abv - 8467) < 5, f"ABV {abv:,.0f} against the POS's 8,467"


# --------------------------------------------------------------------------- #
#  The driver sheet must see growth as well as loss                            #
# --------------------------------------------------------------------------- #
# ★ Manav, 30 Aug, asking whether the driver sheets cover all the segments.
# They did not, and the cap was not the reason. `top_products` sorts
# most-negative-first and truncates with `head`, so it has always meant "the N
# WORST", never "the N biggest movers". A sheet that prints one table of losses
# is served correctly by that. The driver sheet prints a falling table AND a
# growing table, and the second could only ever show growth that survived a
# worst-first cut — 48% of it reached the page, while the losses beside it were
# listed in full. Jayanagar hid Rs 36.1 lakh of growth in one month.

def _movers(rows):
    """A frame shaped like the drivers input: one store, one brand, N divisions."""
    out = []
    for i, (ty, ly) in enumerate(rows):
        out.append({L.COL_STORE_LABEL: "S", L.COL_BRAND: "B",
                    L.COL_DIVISION: f"D{i}", L.COL_AMOUNT: float(ty),
                    "date": pd.Timestamp(2026, 8, 10)})
        out.append({L.COL_STORE_LABEL: "S", L.COL_BRAND: "B",
                    L.COL_DIVISION: f"D{i}", L.COL_AMOUNT: float(ly),
                    "date": pd.Timestamp(2025, 8, 10)})
    return pd.DataFrame(out)


def _divisions(df, **kw):
    d, t = L.degrowth_drivers(df, asof=pd.Timestamp(2026, 8, 20), kind="MTD",
                              only_declining=False, stores_only=["S"],
                              products_under="every", level="division", **kw)
    if d.empty:
        return []
    r = d.iloc[[i for i, x in enumerate(t) if x == "store"]]
    return list(zip(r[L.COL_DIVISION], r["Shortfall"]))


def test_worst_first_is_still_what_every_other_caller_gets():
    """Off by default — the Degrowth tab and the WhatsApp image want the worst."""
    df = _movers([(0, 500), (0, 400), (0, 300), (900, 0), (800, 0)])
    got = _divisions(df, top_products=2)
    assert [n for n, _ in got] == ["D0", "D1"]          # the two worst
    assert all(v < 0 for _, v in got)


def test_both_ways_takes_the_worst_and_the_best():
    """★ THE FIX. Two losses and two gains, not four losses."""
    df = _movers([(0, 500), (0, 400), (0, 300), (900, 0), (800, 0)])
    got = _divisions(df, top_products=2, both_ways=True)
    names = [n for n, _ in got]
    assert "D0" in names and "D1" in names               # the worst two
    assert "D3" in names and "D4" in names               # the best two
    assert sum(1 for _, v in got if v > 0) == 2


def test_growth_is_not_hidden_when_a_brand_is_mostly_falling():
    """The shape that caused it: many small losses, one large gain."""
    df = _movers([(0, 100), (0, 90), (0, 80), (0, 70), (0, 60), (5000, 0)])
    plain = _divisions(df, top_products=3)
    both = _divisions(df, top_products=3, both_ways=True)
    assert not any(v > 0 for _, v in plain), "the gain used to be invisible"
    assert any(v > 0 for _, v in both), "the gain must reach the growing table"


def test_nothing_is_dropped_when_the_brand_is_smaller_than_the_cap():
    df = _movers([(0, 100), (200, 0)])
    assert len(_divisions(df, top_products=10, both_ways=True)) == 2


def test_a_division_is_never_listed_twice():
    """head and tail overlap once the cap exceeds half the rows."""
    df = _movers([(0, 100), (0, 90), (300, 0)])
    got = _divisions(df, top_products=2, both_ways=True)
    assert len(got) == len({n for n, _ in got}) == 3


# --------------------------------------------------------------------------- #
#  Salesperson KPIs — the quarter, the depth measures, and the rank move       #
# --------------------------------------------------------------------------- #
def _sp_frame():
    """A two-month, three-person store built by hand, so the expected answers
    are arithmetic rather than whatever the live feed happens to hold."""
    import loader as L
    rows = []

    def bill(day, who, sid, amt, uid, qty=1):
        rows.append({"date": pd.Timestamp(day), L.COL_AMOUNT: amt,
                     L.COL_QTY: qty, L.COL_BILL_UID: uid,
                     "SALESPERSON_NO": sid, L.COL_SALESPERSON: who,
                     L.COL_STORE_LABEL: "Test Store"})

    # August: A ahead of B on the first three days, C nowhere
    bill("2026-08-01", "A", "1", 300, "b1")
    bill("2026-08-02", "A", "1", 300, "b2")
    bill("2026-08-02", "B", "2", 100, "b3")
    bill("2026-08-20", "B", "2", 5000, "b4")     # after the 3rd — must NOT count
    bill("2026-08-21", "C", "3", 9000, "b5")     # ditto
    # September, three days: B ahead of A, C still nothing
    bill("2026-09-01", "B", "2", 900, "b6")
    bill("2026-09-02", "B", "2", 900, "b7")
    bill("2026-09-03", "A", "1", 400, "b8")
    return pd.DataFrame(rows)


def test_the_quarter_is_the_fiscal_one_not_the_calendar_one():
    import loader as L
    k = L.salesperson_kpis(_sp_frame(), asof=pd.Timestamp("2026-09-03"))
    lo, hi = k.attrs["quarter"]
    assert (lo.month, lo.day) == (7, 1), "Jul-Sep, not Jul-Sep of a calendar Q3"
    assert hi == pd.Timestamp("2026-09-03")


def test_the_move_compares_the_same_number_of_days():
    """★ THE BUG THIS PINS. Ranking three days of September against the WHOLE
    of August made B (who took Rs 5,000 on the 20th) look established and
    everyone else look like risers. Cut to 1-3 Aug, A led August and B leads
    September, so B has climbed one and A has fallen one."""
    import loader as L
    k = L.salesperson_kpis(_sp_frame(), asof=pd.Timestamp("2026-09-03"))
    lo, hi = k.attrs["prev_month"]
    assert (lo, hi) == (pd.Timestamp("2026-08-01"), pd.Timestamp("2026-08-03"))
    by = k.set_index("Salesperson")
    assert by.loc["B", "m_move"] == 1
    assert by.loc["A", "m_move"] == -1


def test_somebody_who_did_not_sell_last_month_has_not_moved():
    """A rank they never held is not a rank they climbed from."""
    import loader as L
    k = L.salesperson_kpis(_sp_frame(), asof=pd.Timestamp("2026-09-03"))
    assert pd.isna(k.set_index("Salesperson").loc["C", "m_move"])


def test_days_sold_counts_days_not_bills():
    import loader as L
    k = L.salesperson_kpis(_sp_frame(), asof=pd.Timestamp("2026-09-03"))
    by = k.set_index("Salesperson")
    assert by.loc["B", "m_days"] == 2          # 1 and 2 Sep
    assert by.loc["A", "m_days"] == 1          # 3 Sep only
    assert by.loc["B", "m_perday"] == 900


def test_share_is_of_the_frame_it_was_given():
    import loader as L
    k = L.salesperson_kpis(_sp_frame(), asof=pd.Timestamp("2026-09-03"))
    assert round(k["m_share"].sum(), 6) == 100.0
    by = k.set_index("Salesperson")
    assert round(by.loc["B", "m_share"], 2) == round(1800 / 2200 * 100, 2)


def test_a_whole_number_column_prints_without_decimals():
    """★ A rank and a day count came out as '1.00' beside '1.91' pieces per
    bill — three kinds of number claiming the same precision."""
    import portfolio_pdf as PP
    d = pd.DataFrame({"#": [1.0, 2.0], "ABS": [1.9142, 2.0]})
    m = PP._measure_table(d, whole=["#"], num=["ABS"], font_px=20, header_px=18)
    assert m["txt"][0][0] == "1"
    assert m["txt"][0][1] == "1.91"


def test_every_salesperson_column_is_declared():
    """The undeclared-column warning, turned into a failure for this report."""
    import warnings
    import salespeople as SP
    rows = [{"rank": 1, "who": "A", "id": "1", "share": 10.0, "days": 2.0,
             "perday": 100.0, "move": 1.0, "last": pd.Timestamp("2026-09-03"),
             **{f"{t}_{m}": 1.0 for t in "dmqy"
                for m in ("sales", "abv", "abs", "single")}}]
    for frame, money, pct, num, whole in (
            (SP._frame(rows), SP._MONEY, SP._PCT, SP._NUM, SP._WHOLE),
            (SP._grid_frame(rows), SP._G_MONEY, SP._G_PCT, SP._G_NUM, SP._G_WHOLE)):
        import portfolio_pdf as PP
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            PP._measure_table(frame, money=money, pct=pct, num=num, whole=whole,
                              font_px=20, header_px=18)


# --------------------------------------------------------------------------- #
#  An even exchange is not a sale                                              #
# --------------------------------------------------------------------------- #
def _exchange_frame():
    """One bill per case, built by hand so the right answer is arithmetic."""
    import loader as L
    rows = []

    def line(uid, amt, qty):
        rows.append({"date": pd.Timestamp("2026-09-08"), L.COL_AMOUNT: amt,
                     L.COL_QTY: qty, L.COL_BILL_UID: uid,
                     L.COL_STORE_LABEL: "T"})

    line("b1", 5000, 1)                      # a plain sale
    line("b2", -6999, None); line("b2", 6999, 1)      # an even swap
    line("b3", -4499, None); line("b3", 4999, 1)      # an upgrade: really sold
    # ★ THE CASE A BILL-LEVEL RULE GETS WRONG: this bill nets +500, so "does it
    # net to zero" keeps all three pieces. Only one of them was sold.
    line("b4", -4499, None); line("b4", 4999, 1)
    line("b4", -1899, None); line("b4", 1899, 1)
    line("b4", -2624, None); line("b4", 2624, 1)
    return pd.DataFrame(rows)


def test_an_even_swap_is_not_a_piece_sold():
    """Manav, 9 Sep: the driver sheet read ABS 1.94 where he made it 1.89, and
    ASP was out by Rs 240. One exchange explained both."""
    import loader as L
    d = _exchange_frame()
    b2 = d[d[L.COL_BILL_UID] == "b2"]
    assert b2[L.COL_QTY].sum() == 1          # the raw column says one piece
    assert L.sold_units(b2) == 0             # nothing was sold


def test_an_upgrade_is_a_piece_sold():
    import loader as L
    d = _exchange_frame()
    assert L.sold_units(d[d[L.COL_BILL_UID] == "b3"]) == 1


def test_the_pairing_is_line_by_line_not_bill_by_bill():
    """b4 nets +500, so a bill-level test keeps all three pieces. Two of them
    were swapped for an identical amount and only one was sold."""
    import loader as L
    d = _exchange_frame()
    b4 = d[d[L.COL_BILL_UID] == "b4"]
    assert round(b4[L.COL_AMOUNT].sum()) == 500      # not zero
    assert b4[L.COL_QTY].sum() == 3
    assert L.sold_units(b4) == 1


def test_abs_and_asp_move_the_way_the_swap_implies():
    """A swapped piece carries no money, so counting it lifts ABS and drags
    ASP down — which is exactly the pair of errors he spotted."""
    import loader as L
    d = _exchange_frame()
    bills = L.bill_count(d)
    sale = d[L.COL_AMOUNT].sum()
    raw, sold = d[L.COL_QTY].sum(), L.sold_units(d)
    assert sold < raw
    assert sold / bills < raw / bills          # ABS falls
    assert sale / sold > sale / raw            # ASP rises


def test_a_pure_return_needs_no_special_handling():
    """Every negative line in this feed carries a blank quantity, so a return
    with no replacement already contributes nothing."""
    import loader as L
    d = pd.DataFrame([{"date": pd.Timestamp("2026-09-08"),
                       L.COL_AMOUNT: -2999, L.COL_QTY: None,
                       L.COL_BILL_UID: "r1", L.COL_STORE_LABEL: "T"}])
    assert L.sold_units(d) == 0
    assert not L.swapped_lines(d).any()       # nothing to cancel
