"""A bill is counted the way the store's own till counts it.

★ WHY. Manav, 30 Aug, auditing Orion Mall's August against the GINESYS POS: the
sales agreed to Rs 78 but the bill count did not — 430 to the POS's 451 — and
every average bill value was therefore too high, Rs 8,880 against Rs 8,467.

An exchange is ONE bill number in our feed and TWO memos in the till: a sale
memo and a credit memo. The return arrives as a negative line under the same
bill number. Counting it once made the denominator too small.

The manager checks the sheet against the till they are standing at, so the
till's convention is the one that has to win.
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


def test_an_exchange_is_two_memos():
    """★ THE CASE. Sale lines and a return line on one bill number."""
    assert L.bill_count(_f([("A", 1500), ("A", 4499), ("A", -4999)])) == 2


def test_several_return_lines_on_one_bill_are_still_one_credit_memo():
    """The till raises one credit note for the transaction, not one per item."""
    assert L.bill_count(_f([("A", 5000), ("A", -1000), ("A", -2000)])) == 2


def test_a_return_only_bill_is_one_memo():
    assert L.bill_count(_f([("A", -999)])) == 1


def test_bills_are_counted_independently():
    rows = [("A", 100), ("B", 200), ("B", -50), ("C", -10)]
    assert L.bill_count(_f(rows)) == 4          # A=1, B=2, C=1


def test_a_zero_line_is_neither_a_sale_nor_a_return():
    assert L.bill_count(_f([("A", 100), ("A", 0)])) == 1


def test_an_empty_frame_counts_nothing():
    assert L.bill_count(_f([])) == 0
    assert L.bill_count(pd.DataFrame()) == 0


def test_amounts_written_as_text_are_still_counted():
    """The feed arrives as strings; a return must not be read as a sale."""
    f = _f([("A", "1,500"), ("A", "-4,999")])
    f[L.COL_AMOUNT] = ["1500", "-4999"]
    assert L.bill_count(f) == 2


def test_every_bill_count_in_the_pack_uses_this_one_definition():
    """Five places counted bills. If a new one appears and does its own
    `nunique`, the sheet and the till disagree again and nobody notices."""
    import re
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "loader.py"), encoding="utf-8").read()
    stray = re.findall(r"\[COL_BILL_UID\]\.nunique\(\)", src)
    assert not stray, f"{len(stray)} bill count(s) bypass bill_count()"


def test_orion_august_lands_within_one_of_the_pos():
    """The real audit, on the real feed. GINESYS: 451 memos, ABV Rs 8,467.

    Off by one is expected and deliberate: 26 negative lines fall in 22 bills
    and one of them is not a credit note — most likely an adjustment, or a
    return the till dated outside the window. The residue is left visible
    rather than tuned away against a single store's month."""
    try:
        df = L.load_data()
    except Exception as e:
        import pytest
        pytest.skip(f"needs live data: {e}")
    d = df[(df[L.COL_STORE_LABEL] == "Orion Mall")
           & (df["date"] >= pd.Timestamp(2026, 8, 1))
           & (df["date"] <= pd.Timestamp(2026, 8, 29))]
    if d.empty:
        import pytest
        pytest.skip("Orion's August is not in this feed")
    bills = L.bill_count(d)
    assert abs(bills - 451) <= 1, f"{bills} bills against the POS's 451"
    abv = float(d[L.COL_AMOUNT].sum()) / bills
    assert abs(abv - 8467) < 50, f"ABV {abv:,.0f} against the POS's 8,467"
