"""A bill is a store, a day and a number — not a number.

`Bill No` is a per-store sequence, so `PM/00029/Apr-26` exists at twenty-two
stores at once. Counting distinct bill NUMBERS across stores merged bills that
had nothing to do with each other: the VFL year-to-date read 10,285 bills where
there were 24,899, and the average ticket doubled with it — Rs 28,306 against
Rs 11,692. That is where "bills collapsing, ticket way up" came from. Bills had
moved +4.6%, not -18.7%.

The DAY belongs in the key too. At the 19 April takeover the previous operator's
sequence and ours overlap, so CMH Road has a real PM/00001/Apr-26 on the 1st and
another on the 19th — 1,597 store-and-number pairs look like that, every one of
them around a takeover.

Runs on a synthetic frame — no sheet, no network:

    python tests/test_bill_identity.py        (or: python -m pytest tests -q)
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import loader as L                     # noqa: E402


def _clean(rows):
    """Through the real `clean`, so the key is built the way the app builds it.

    Dates are written MONTH-first, because the VFL export is: `loader._parse_dates`
    is the authority, and writing 01/04/2026 here would silently mean 4 January.
    """
    raw = pd.DataFrame(rows)
    return L.clean(raw)


def _row(store, date, bill, amount=1000.0, qty=1):
    """A raw export row — every column `clean` reads, so it runs for real."""
    return {"Sr No": 1, L.COL_STORE: f"Peanuts - {store}", L.COL_DATE: date,
            L.COL_BILL: bill, L.COL_AMOUNT: amount, L.COL_QTY: qty,
            L.COL_PROMO: 0.0, L.COL_DIVISION: "MANYAVAR", L.COL_SECTION: "S",
            L.COL_DEPARTMENT: "D", L.COL_SIZE: "M", L.COL_COLOR: "RED",
            L.COL_STYLE: "ST", L.COL_MOBILE: "", L.COL_MWC: "MEN",
            L.COL_SALESPERSON: "X"}


def test_the_same_number_at_two_stores_is_two_bills():
    """The defect, in one assertion."""
    df = _clean([_row("Agartala", "04/01/2026", "PM/00029/Apr-26"),
                 _row("Malda", "04/01/2026", "PM/00029/Apr-26")])
    assert df[L.COL_BILL].nunique() == 1, "one number..."
    assert df[L.COL_BILL_UID].nunique() == 2, "...but two bills"


def test_the_same_number_on_two_days_at_one_store_is_two_bills():
    """The takeover case: two operators, one sequence, one store."""
    df = _clean([_row("CMH Road", "04/01/2026", "PM/00001/Apr-26"),
                 _row("CMH Road", "04/19/2026", "PM/00001/Apr-26")])
    assert df[L.COL_BILL_UID].nunique() == 2


def test_one_bill_with_several_lines_stays_one_bill():
    """A bill is not a line: three garments on one bill is still one bill."""
    df = _clean([_row("Agartala", "04/01/2026", "PM/00007/Apr-26", 500.0),
                 _row("Agartala", "04/01/2026", "PM/00007/Apr-26", 700.0),
                 _row("Agartala", "04/01/2026", "PM/00007/Apr-26", 900.0)])
    assert df[L.COL_BILL_UID].nunique() == 1


def test_a_row_with_no_bill_number_is_not_a_bill():
    """The night fill appends takings with no bill numbers, because a night's
    takings have none. Built by concatenation the key would have become the
    countable string "store|date|nan" and invented a bill for every such row."""
    rows = [_row("Agartala", "04/01/2026", "PM/00007/Apr-26"),
            _row("Agartala", "04/02/2026", None)]
    df = _clean(rows)
    assert df[L.COL_BILL_UID].isna().sum() == 1
    assert df[L.COL_BILL_UID].nunique() == 1, "the null row must not count"


def test_per_store_counts_are_unchanged_by_the_fix():
    """Whatever this changes, it must not change a single store's own figures —
    within one store on one day the number was already unique."""
    rows = [_row("Agartala", "04/01/2026", f"PM/{i:05d}/Apr-26") for i in range(5)]
    df = _clean(rows)
    assert df[L.COL_BILL].nunique() == df[L.COL_BILL_UID].nunique() == 5


def test_the_window_metrics_count_bills_not_numbers():
    """The figure the executive tiles print."""
    rows = [_row(s, "04/01/2026", "PM/00029/Apr-26")
            for s in ("Agartala", "Malda", "Jorhat")]
    df = _clean(rows)
    m = L.window_yoy(df, pd.Timestamp(2026, 4, 1), pd.Timestamp(2026, 4, 30))
    assert m["cur"]["bills"] == 3, "three stores, three bills, one number"
    assert round(m["cur"]["atv"], 2) == 1000.0, "and the ticket is not tripled"


def test_store_summary_bills_add_up_to_the_whole():
    """Per-store bills summed must equal the estate's bills — arithmetic that
    could not hold while numbers were shared across stores."""
    rows = ([_row("Agartala", "04/01/2026", "PM/00001/Apr-26")]
            + [_row("Malda", "04/01/2026", "PM/00001/Apr-26")]
            + [_row("Malda", "04/02/2026", "PM/00002/Apr-26")])
    df = _clean(rows)
    assert L.store_summary(df)["bills"].sum() == df[L.COL_BILL_UID].nunique() == 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all bill-identity tests passed")
