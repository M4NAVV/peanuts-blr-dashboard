"""The team-detail sheet's TOTAL row.

Frames are built inside the test so CI verifies the rules without the feed —
see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import salespeople as SP


def _feed():
    """Two salespeople in one store, and one bill they WROTE TOGETHER."""
    import loader as L
    rows = []

    def line(d, who, code, bill, amt, units):
        return {"date": pd.Timestamp(d), L.COL_STORE_LABEL: "Jayanagar",
                L.COL_AMOUNT: amt, "net_amount": amt,
                # ★ Pieces come from the QUANTITY column via `unit_delta`
                # (a return takes one off), not from COL_UNITS.
                L.COL_QTY: units, L.COL_UNITS: units,
                L.COL_PROMO: 0.0, "mobile_clean": "m1",
                "bill_uid": f"Jayanagar-{bill}", "Bill No": bill,
                # ★ The KEY is SALESPERSON_NO; COL_SALESPERSON is the NAME.
                # Putting the code in the name column returns an empty frame.
                "SALESPERSON_NO": code, L.COL_SALESPERSON: who,
                L.COL_REGION: "South", L.COL_BRAND: "Manyavar",
                L.COL_DIVISION: "KURTA SET", L.COL_MWC: "MEN",
                L.COL_SECTION: "S1", L.COL_DEPARTMENT: "D1",
                L.COL_SIZE: "M", L.COL_COLOR_NAME: "TEAL",
                L.COL_COLOR: "327-Teal", L.COL_STYLE: "SDES503"}

    # ★ ONE bill, two salespeople, three pieces between them. This is the case
    # that separates a sum from a distinct count.
    rows.append(line("2026-09-22", "A", "23SVFL0001", "B1", 1000.0, 2))
    rows.append(line("2026-09-22", "B", "23SVFL0002", "B1", 500.0, 1))
    rows.append(line("2026-09-22", "A", "23SVFL0001", "B2", 700.0, 1))
    return pd.DataFrame(rows)


def _split(rows, types):
    people = [r for r, t in zip(rows, types) if t == "person"]
    total = [r for r, t in zip(rows, types) if t == "subtotal"][0]
    return people, total


def test_the_total_row_reports_the_pieces_it_used_to_report_as_zero():
    """★ The regression this test exists for: `{t}_units` was never set on the
    total, so `_detail_frame`'s `.get(..., 0.0)` printed 0 for the day, the
    month and the year on every team sheet ever generated."""
    import loader as L
    df = _feed()
    rows, types, _meta = SP.store_table(L, df, pd.Timestamp("2026-09-22"),
                                        "Jayanagar")
    people, total = _split(rows, types)
    for period in ("d", "m", "y"):
        assert float(total.get(f"{period}_units") or 0) == 4.0, period


def test_units_total_equals_the_sum_of_the_team():
    """Pieces are attributed line by line, so they add up."""
    import loader as L
    df = _feed()
    rows, types, _ = SP.store_table(L, df, pd.Timestamp("2026-09-22"), "Jayanagar")
    people, total = _split(rows, types)
    for period in ("d", "m", "y"):
        s = sum(float(r.get(f"{period}_units") or 0) for r in people)
        assert float(total[f"{period}_units"]) == pytest.approx(s)


def test_the_sales_total_still_adds_up():
    import loader as L
    df = _feed()
    rows, types, _ = SP.store_table(L, df, pd.Timestamp("2026-09-22"), "Jayanagar")
    people, total = _split(rows, types)
    assert float(total["d_sales"]) == pytest.approx(2200.0)


def test_a_shared_bill_is_one_bill_for_the_store():
    """★ Why units are summed and bills are NOT. Two people wrote bill B1
    between them; the store wrote two bills, not three."""
    import loader as L
    df = _feed()
    rows, types, _ = SP.store_table(L, df, pd.Timestamp("2026-09-22"), "Jayanagar")
    people, total = _split(rows, types)
    per_person = sum(float(r.get("d_bills") or 0) for r in people)
    assert per_person == 3.0                      # A twice, B once
    assert float(total["d_abv"]) == pytest.approx(2200.0 / 2)   # over TWO bills


def test_every_displayed_measure_is_present_on_the_total():
    """The bug was a missing key, not a wrong number. Nothing the sheet prints
    should fall through to a default."""
    import loader as L
    df = _feed()
    rows, types, _ = SP.store_table(L, df, pd.Timestamp("2026-09-22"), "Jayanagar")
    _people, total = _split(rows, types)
    for key, _label in SP._MEASURES:
        for period, _tag in SP._PERIODS:
            assert f"{period}_{key}" in total, f"{period}_{key} missing"
