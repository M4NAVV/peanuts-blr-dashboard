"""The pivot table (pivotx) — the rules that must hold whatever the layout.

Frames are built inside the test so CI checks the rules without the feed — see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import pivotx as P
from tests.test_pivot import _pf, _vfl


def _vfl2():
    """Two stores, two regions, two financial years (Apr-May 2025 and Apr-May 2026)."""
    a = _vfl()
    b = a.copy()
    b["date"] = b["date"] - pd.DateOffset(years=1)
    b["bill_uid"] = "ly-" + b["bill_uid"]
    b["Bill Amount"] = b["Bill Amount"] * 0.8
    out = pd.concat([a, b], ignore_index=True)
    out.loc[out["store"] == "Jayanagar", "region"] = "South"
    out["SALESPERSON_NO"] = "C1"
    out["Name (Dm Salesperson)"] = "ASHIS DAS"
    return out


def _build(**kw):
    return P.build(_vfl2(), "vfl", P.Spec(**kw))


def _row(g, kind, key=()):
    return next(r for r in g["rows"] if r["kind"] == kind and r["key"] == key)


def test_totals_are_rederived_not_summed():
    g = _build(rows=["Region", "Store"], values=[("Sales (₹)", "Value"), ("ATV / avg bill value (₹)", "Value")])
    grand = _row(g, "grand")
    items = [r for r in g["rows"] if r["kind"] == "item"]
    assert grand["values"][0] == pytest.approx(sum(r["values"][0] for r in items))
    # ATV of the whole = all sales / all bills — not the mean of the two store ATVs
    w = _vfl2()
    assert grand["values"][1] == pytest.approx(w["Bill Amount"].sum() / w["bill_uid"].nunique())
    assert grand["values"][1] != pytest.approx(sum(r["values"][1] for r in items) / len(items))


def test_subtotal_rows_under_each_group():
    g = _build(rows=["Region", "Store"], values=[("Sales (₹)", "Value")])
    kinds = [r["kind"] for r in g["rows"]]
    assert kinds.count("subtotal") == 2 and kinds[-1] == "grand"
    g2 = _build(rows=["Region", "Store"], values=[("Sales (₹)", "Value")], subtotals=False)
    assert "subtotal" not in [r["kind"] for r in g2["rows"]]


def test_change_vs_previous_column_is_year_on_year():
    g = _build(rows=["Store"], cols=["Financial Year"], values=[("Sales (₹)", "% change vs previous column")],
               grand_cols=False)
    assert g["heads"] == [["FY26", "FY27"]]
    grand = _row(g, "grand")
    assert grand["values"][0] is None                       # FY26 has nothing before it
    assert grand["values"][1] == pytest.approx(0.25)        # last year was 80% of this year


def test_percent_of_column_total_adds_to_one():
    g = _build(rows=["Store"], cols=["Financial Year"], values=[("Sales (₹)", "% of column total")])
    items = [r for r in g["rows"] if r["kind"] == "item"]
    assert sum(r["values"][0] for r in items) == pytest.approx(1.0)


def test_ratios_cannot_be_a_share_of_a_total():
    assert "% of grand total" not in P.show_as_for("vfl", "ATV / avg bill value (₹)")
    assert "% of grand total" in P.show_as_for("vfl", "Sales (₹)")


def test_filters_include_and_exclude():
    inc = _build(rows=["Store"], values=[("Sales (₹)", "Value")],
                 filters={"Region": {"mode": "include", "items": ["South"]}})
    exc = _build(rows=["Store"], values=[("Sales (₹)", "Value")],
                 filters={"Region": {"mode": "exclude", "items": ["South"]}})
    assert [r["key"] for r in inc["rows"] if r["kind"] == "item"] == [("Jayanagar",)]
    assert [r["key"] for r in exc["rows"] if r["kind"] == "item"] == [("Agartala",)]


def test_same_dates_both_years():
    per = P.periods(pd.Timestamp("2026-05-15"))["FY to date · this year and last"]
    assert [str(pd.Timestamp(a).date()) for a, _b in per] == ["2026-04-01", "2025-04-01"]
    assert [str(pd.Timestamp(b).date()) for _a, b in per] == ["2026-05-15", "2025-05-15"]


def test_financial_calendar_fields():
    d = pd.Series(pd.to_datetime(["2026-03-31", "2026-04-01", "2026-10-13"]))
    assert P._time(d, "Financial Year")[0].tolist() == ["FY26", "FY27", "FY27"]
    assert P._time(d, "FY Quarter")[0].tolist() == ["FY26 Q4", "FY27 Q1", "FY27 Q3"]
    assert P._time(d, "FY Half")[0].tolist() == ["FY26 H2", "FY27 H1", "FY27 H2"]


def test_top_n_keeps_totals_whole():
    g = _build(rows=["Store"], values=[("Sales (₹)", "Value")], top=1, sort_by="Sales (₹)")
    items = [r for r in g["rows"] if r["kind"] == "item"]
    assert len(items) == 1 and g["hidden_items"] == 1
    assert _row(g, "grand")["values"][0] > items[0]["values"][0]


def test_no_customer_mobile_anywhere():
    for feed in ("vfl", "portfolio"):
        assert not any("mobile" in f.lower() or "customer" in f.lower() for f in P.field_names(feed))
    src = P.source_rows(_vfl2(), "vfl", P.Spec(rows=["Store"], values=[("Sales (₹)", "Value")]))
    assert not any("mobile" in c.lower() for c in src.columns)


def test_layout_survives_the_address_bar():
    s = P.Spec(rows=["Region"], cols=["Financial Year"], values=[("Sales (₹)", "Value")],
               filters={"Store": {"mode": "exclude", "items": ["Agartala"]}}, top=3, layout="Compact")
    back = P.Spec.from_param(s.to_param())
    assert back.rows == s.rows and back.values == s.values and back.filters == s.filters and back.top == 3


def test_workbook_builds_both_feeds():
    g = _build(rows=["Region", "Store"], cols=["Financial Year"], values=[("Sales (₹)", "Value"), ("Bills", "Value")])
    assert P.to_excel(g, title="t", about={"a": "b"})[:2] == b"PK"
    pg = P.build(_pf(), "portfolio", P.Spec(rows=["Brand"], cols=["Month"], values=[("Sales (₹)", "Value")]))
    assert P.to_excel(pg, title="t", about={})[:2] == b"PK"
    assert "<table" in P.to_html(pg)


def test_indian_grouping():
    assert P.fmt(12345678, "money") == "1,23,45,678"
    assert P.fmt(0.123, "pctchg") == "+12.3%"
