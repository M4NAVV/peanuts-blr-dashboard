"""A day nobody has filed is not a day of no sales.

Manav, 27 Sep 2026, with a screenshot of the South portfolio pack: *"south
sales werent recorded … just do a check and see if theres a gap."* There was no
gap in the data — he had built the pack before the eight Bengaluru figures were
typed. The gap was in what the page SAID about it.
"""
import pandas as pd
import pytest

import exec_snapshot as ES


def _frame(dates, codes=(107, 112), region="South"):
    rows = []
    for d in dates:
        for c in codes:
            rows.append({"date": pd.Timestamp(d), "code": c, "sales": 100000.0,
                         "region": region, "brand": "MANYAVAR & MOHEY",
                         "location": f"store {c}", "city": "BENGALURU",
                         "is_vfl": True, "takeover_date": pd.NaT,
                         "STORE NAME": "MANYAVAR & MOHEY",
                         "LOCATION": f"store {c}", "CITY": "BENGALURU",
                         "STORE CODE": c, "Total": "1,00,000.00"})
    f = pd.DataFrame(rows)
    f["date"] = pd.to_datetime(f["date"])
    f["month"] = f["date"].values.astype("datetime64[M]")
    f["month_label"] = f["date"].dt.strftime("%b %Y")
    fy = f["date"].dt.year.where(f["date"].dt.month >= 4,
                                 f["date"].dt.year - 1)
    f["fy"] = fy.astype(str) + "-" + (fy + 1).astype(str).str[-2:]
    return f


def _day_tile(pf, asof, region=None):
    m = ES.portfolio_metrics(pf, pd.Timestamp(asof), region=region)
    return [t for t in m["tiles"] if str(t["label"]).startswith("Day")][0]


ASOF = "2026-09-26"


def test_a_day_with_no_rows_says_it_is_not_filed():
    """★ The tile read `Rs 0.00 Cr · nothing trading · −100%` — a completed day
    that went to zero, for a day nobody had written in yet."""
    pf = _frame(["2026-09-24", "2026-09-25"])          # nothing on the 26th
    tile = _day_tile(pf, ASOF)
    assert tile["value"] == "not filed"
    assert "yet" in tile["sub"]


def test_it_never_prints_minus_one_hundred_for_a_day_nobody_filed():
    """★ −100% is a real statement about trade. Silence is not data."""
    pf = _frame(["2026-09-24", "2026-09-25"])
    tile = _day_tile(pf, ASOF)
    printed = [v for _k, v in tile["rows"]] + [tile["key"][1]]
    assert all(v == "—" for v in printed), printed


def test_it_never_prints_a_count_that_cannot_be_true():
    """★★ `Comparable 8 of 0` — eight comparable stores out of none open. An
    impossible sentence is worse than a blank, because a reader believes it."""
    pf = _frame(["2026-09-24", "2026-09-25"])
    tile = _day_tile(pf, ASOF)
    assert not any("of 0" in str(k) for k, _v in tile["rows"])


def test_a_filed_day_still_reports_normally():
    pf = _frame(["2026-09-25", ASOF])
    tile = _day_tile(pf, ASOF)
    assert tile["value"].startswith("Rs ")
    assert "2 stores trading" in tile["sub"]


def test_the_rule_holds_on_the_vfl_page_too():
    """Both pages carry the same tile; a fix to one is a fix to neither."""
    import inspect
    src = inspect.getsource(ES)
    assert src.count('"value": (f"Rs {_cr(day_all)} Cr" if _d_open '
                     'else "not filed")') == 2
