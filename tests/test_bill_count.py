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
