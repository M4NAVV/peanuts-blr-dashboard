"""Alterations & parking in the Excel Builder.

Manav, 10 Nov 2026: *"i want to pull the alterations and parking in the excel
builder too."* A third source for the same pivot engine: the stores' own books
(tailoring.load), one row per booked job. Pinned on frames built here, so CI
checks it with no Drive.
"""
import pandas as pd
import pytest

import pivotx as P
import pivot_ui as PU
import pivot_pane as PP


def _books():
    rows = [
        # store, kind, date, billed, due, due_paid, total, cash, card_upi, done_by
        (107, "alter",   "2026-09-19", 4000, 0, 0, 4000, 0, 4000, ""),
        (107, "alter",   "2026-10-02", 2000, 1000, 0, 1000, 1000, 0, "InHouse"),
        (107, "parking", "2026-10-02", 100, 0, 0, 100, 100, 0, None),
        (112, "alter",   "2026-10-05", 3000, 0, 0, 3000, 0, 3000, "Com Street"),
        (112, "alter",   "2026-10-06", 1500, 0, 0, 1500, 0, 1500, "suhail"),
        (92,  "parking", "2026-11-01", 50, 0, 0, 50, 50, 0, "in house"),
    ]
    f = pd.DataFrame(rows, columns=["store_code", "kind", "date", "billed", "due", "due_paid", "total",
                                    "cash", "card_upi", "done_by"])
    f["date"] = pd.to_datetime(f["date"])
    f["bill_no"], f["source_id"] = "1", "x"
    return f


def test_the_engine_totals_are_the_books_own_sums():
    base = P._aggregate(P.prepare(_books(), "tailoring"), [], "tailoring",
                        {"total", "billed", "jobs", "cash", "card_upi", "stores", "days"})
    b = _books()
    assert base.loc[0, "total"] == b["total"].sum()
    assert base.loc[0, "billed"] == b["billed"].sum()
    assert base.loc[0, "jobs"] == len(b)
    assert base.loc[0, "stores"] == 3


def test_outstanding_is_billed_less_collected():
    M = P.measures("tailoring")
    base = P._aggregate(P.prepare(_books(), "tailoring"), [], "tailoring", {"billed", "total"})
    assert float(M["Outstanding (₹)"].fn(base)[0]) == 1000.0      # the one part-paid job


def test_a_ratio_is_not_offered_as_a_share_of_total():
    assert "% of grand total" not in P.show_as_for("tailoring", "Avg per job (₹)")
    assert "% of grand total" in P.show_as_for("tailoring", "Collected (₹)")


def test_book_and_done_by_read_in_one_spelling_each():
    w = P.prepare(_books(), "tailoring")
    assert set(w["_book"]) == {"Alterations", "Parking"}
    assert set(w["_done_by"]) == {"(not recorded)", "In-house", "Commercial Street", "Suhail"}


def test_every_preset_builds_and_every_field_has_labels():
    w = P.prepare(_books(), "tailoring")
    for f in P.field_names("tailoring"):
        lab, _o = P.labels(w, "tailoring", f)
        assert len(lab) == len(w) and lab.notna().all(), f
    for name, p in PU.PRESETS["tailoring"].items():
        ui = PP.from_preset("tailoring", p)
        g = P.build(w, "tailoring", PP.to_spec(ui, "tailoring", pd.Timestamp("2026-11-09")), prepared=True)
        assert "rows" in g or g.get("empty"), name
    assert PU.DEFAULT["tailoring"] in PU.PRESETS["tailoring"]


def test_the_sales_pivots_are_untouched():
    assert "Collected (₹)" not in P.measures("vfl") and "Collected (₹)" not in P.measures("portfolio")
    assert "Book" not in P.field_names("vfl")


def test_the_vfl_builder_offers_the_books_as_a_second_source():
    from pathlib import Path
    src = Path("app.py").read_text()
    assert 'feed="tailoring", key="vfl_tlpx"' in src
    assert '["Sales", "Alterations & parking"]' in src
    assert 'feed="tailoring", key="pf_tlpx"' in src
