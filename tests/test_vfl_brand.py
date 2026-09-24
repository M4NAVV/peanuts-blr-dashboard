"""The VFL brand contribution page — Manyavar, Mohey, Twamev by region.

Manav, 24 Sep 2026: *"just need the contribution of the three brands, for
east, south and one total column. day mtd and ytd."*

The rules are pinned on frames built inside the test, so CI verifies them with
no feed — see [[feedback-test-where-it-runs]]. The reconciliation against the
real G/D sheet needs the feed and skips without it.
"""
import pandas as pd
import pytest

import loader as L

DAY = pd.Timestamp("2026-09-23")


def _frame(rows):
    """A VFL-shaped frame: date, store, region, division, amount."""
    f = pd.DataFrame(rows, columns=["date", "store", "region", "division",
                                    "amount"])
    f["date"] = pd.to_datetime(f["date"])
    return f.rename(columns={"store": L.COL_STORE_LABEL,
                             "region": L.COL_REGION,
                             "division": L.COL_DIVISION,
                             "amount": L.COL_AMOUNT})


def _panels(f, asof=DAY):
    return {r: (rows, tot) for r, rows, tot in L.vfl_brand_report(f, asof=asof)}


def _basic():
    """One store a region, this year and last, across the three brands."""
    rows = []
    for d in (DAY, DAY - pd.DateOffset(years=1)):
        for region, store in (("East & NE", "Agartala"), ("South", "Jayanagar")):
            for div, amt in (("KURTA SET", 100), ("MOHEY-SAREE", 50),
                             ("TWAMEV-MEN", 30), ("TWAMEV-WOMEN", 20)):
                rows.append([d, store, region, div, amt])
    return _frame(rows)


# --------------------------------------------------------------------------- #
# What the three brands ARE
# --------------------------------------------------------------------------- #
def test_the_three_brands_are_the_workbooks_four_lines_folded():
    """★ Mebaz sits inside Mohey and Manthan inside Manyavar, exactly as on the
    VFL G/D sheet, and Twamev Men + Women are one brand because he named three.
    Reading `brand` instead would give Mebaz a line of its own and the two
    sheets would stop tying. See [[feedback-same-estate]]."""
    f = _frame([[DAY, "A", "South", d, 100] for d in
                ("KURTA SET", "MANTHAN", "MOHEY-SAREE", "MEBAZ",
                 "TWAMEV-MEN", "TWAMEV-WOMEN")])
    rows, total = _panels(f)["Total"]
    got = {r["brand"]: r["ytd"] for r in rows}
    assert got == {"Manyavar": 200.0, "Mohey": 200.0, "Twamev": 200.0}
    assert total["ytd"] == 600.0


def test_there_is_a_panel_for_each_region_and_one_for_the_estate():
    got = _panels(_basic())
    assert list(got) == ["East & NE", "South", "Total"]
    assert [r["brand"] for r in got["Total"][0]] == ["Manyavar", "Mohey",
                                                     "Twamev"]


# --------------------------------------------------------------------------- #
# The arithmetic that must never drift
# --------------------------------------------------------------------------- #
def test_the_regions_add_up_to_the_total_panel():
    got = _panels(_basic())
    for k in ("day", "mtd", "ytd"):
        assert (got["East & NE"][1][k] + got["South"][1][k]
                == pytest.approx(got["Total"][1][k])), k


def test_the_brands_add_up_to_their_own_panel_total():
    for region, (rows, total) in _panels(_basic()).items():
        for k in ("day", "mtd", "ytd"):
            assert sum(r[k] for r in rows) == pytest.approx(total[k]), (region, k)


def test_a_share_is_taken_against_its_own_panel_not_the_estate():
    """★ East's three brands add to 100% OF EAST. A share against the estate
    would be a different number meaning a different thing under the same
    header."""
    f = _frame(
        [[DAY, "A", "East & NE", "KURTA SET", 100]] +
        [[DAY, "B", "South", "KURTA SET", 300], [DAY, "B", "South", "MOHEY-SAREE", 100]])
    got = _panels(f)
    assert got["East & NE"][0][0]["mix"] == pytest.approx(100.0)
    assert [round(r["mix"], 1) for r in got["South"][0]] == [75.0, 25.0, 0.0]
    for region, (rows, _t) in got.items():
        assert sum(r["mix"] for r in rows) == pytest.approx(100.0), region


def test_a_totals_growth_is_recomputed_from_the_summed_pair():
    """Never averaged down the column — see
    [[feedback-aggregate-ratios-in-pairs]]."""
    ly = DAY - pd.DateOffset(years=1)
    f = _frame([[DAY, "A", "South", "KURTA SET", 200],
                [ly, "A", "South", "KURTA SET", 100],       # +100%
                [DAY, "A", "South", "MOHEY-SAREE", 110],
                [ly, "A", "South", "MOHEY-SAREE", 100]])    # +10%
    rows, total = _panels(f)["South"]
    assert round(rows[0]["gd_ytd"], 1) == 100.0
    assert round(rows[1]["gd_ytd"], 1) == 10.0
    # (310 - 200) / 200, not the mean of 100 and 10
    assert round(total["gd_ytd"], 1) == 55.0


def test_a_growth_against_a_negative_base_is_blank_not_minus_two_hundred():
    """★ A brand line whose last year was nothing but returns gives
    (9,999 − −9,999) / −9,999 = −200% — a red figure for a line that GREW."""
    ly = DAY - pd.DateOffset(years=1)
    f = _frame([[DAY, "A", "South", "TWAMEV-MEN", 9999],
                [ly, "A", "South", "TWAMEV-MEN", -9999],
                [DAY, "A", "South", "KURTA SET", 100],
                [ly, "A", "South", "KURTA SET", 100]])
    rows, _t = _panels(f)["South"]
    tw = next(r for r in rows if r["brand"] == "Twamev")
    assert pd.isna(tw["gd_ytd"]) and pd.isna(tw["gd_mtd"])


def test_a_brand_with_no_last_year_has_no_growth_to_state():
    f = _frame([[DAY, "A", "South", "MOHEY-SAREE", 500]])
    rows, _t = _panels(f)["South"]
    mohey = next(r for r in rows if r["brand"] == "Mohey")
    assert mohey["ytd"] == 500 and pd.isna(mohey["gd_ytd"])


def test_the_day_column_is_the_report_date_only():
    f = _frame([[DAY, "A", "South", "KURTA SET", 70],
                [DAY - pd.Timedelta(days=1), "A", "South", "KURTA SET", 900]])
    rows, total = _panels(f)["South"]
    assert rows[0]["day"] == 70 and total["day"] == 70
    assert total["mtd"] == 970            # the month still holds both


def test_a_day_carries_no_growth_because_the_feed_has_no_last_year_day():
    """★ The windows are last year's MONTH and last year's YEAR. A day-on-day
    growth would be invented, so the column does not exist rather than being
    printed blank."""
    rows, total = _panels(_basic())["Total"]
    for r in rows + [total]:
        assert "gd_day" not in r
    assert set(rows[0]) == {"brand", "day", "mtd", "ytd", "mix", "gd_mtd",
                            "gd_ytd"}


# --------------------------------------------------------------------------- #
# Against the real sheet it sits behind
# --------------------------------------------------------------------------- #
def test_the_page_totals_tie_to_the_gd_sheets_grand_total():
    """★ THE CHECK THAT MATTERS. Both come off the same feed by different
    routes; if they ever disagree, one of them is lying about the estate."""
    try:
        df = L.load_data()
    except Exception as e:                 # no sheet, no export: not a fault
        pytest.skip(f"live data unavailable: {type(e).__name__}")
    asof = L.as_of(df)
    total = {r: t for r, _rows, t in L.vfl_brand_report(df, asof=asof)}["Total"]
    gd, rt = L.vfl_gd_report(df, asof=asof, gen_date=asof)
    gd = gd.assign(__t=rt)
    grand = gd[gd["__t"] == "grand"].iloc[0]
    assert float(grand["Sum of YTD_TY"]) == pytest.approx(total["ytd"])
    assert float(grand["Sum of MTD_TY"]) == pytest.approx(total["mtd"])
    assert float(grand["Sum of DAY SALE FIGURE"]) == pytest.approx(total["day"])


# --------------------------------------------------------------------------- #
# Where it sits, and how it is drawn
# --------------------------------------------------------------------------- #
def _src():
    from pathlib import Path
    return Path("vfl_pdf.py").read_text()


def test_the_brand_page_is_the_last_page_of_the_report():
    """Manav, 24 Sep: *"the page should be the last page of this report."*
    The exec snapshots are PREPENDED, every sheet is appended in order, so the
    last `contents.append` is the last page."""
    src = _src()
    assert src.index('"VFL — Brand Contribution"') > \
        src.index('"VFL — Region × Gender Summary"')
    assert src.index('"VFL — Brand Contribution"') > \
        src.index('"VFL — Growth / Degrowth"')


def test_the_type_is_sized_to_fit_rather_than_set_and_hoped_for():
    """★ These figures only grow. This document's page width is the width of
    its widest sheet, so an overgrown panel grid would not clip — it would
    widen EVERY page and leave the sheets that matter floating in white."""
    src = _src()
    assert "_budget" in src and "for _fpx in" in src
    assert "if _grid.width <= _budget" in src


def test_every_column_on_the_page_is_declared_in_a_kind():
    """A column in no kind prints as `str(v)` — see
    [[feedback-declare-numeric-columns]]."""
    import re
    src = _src()
    spec = re.search(r"_BSPEC = \[(.+?)\]\n", src, re.S).group(1)
    kinds = re.findall(r'\("(\w+)", "(\w+)",', spec)
    assert {c for c, _k in kinds} == {"brand", "day", "mtd", "ytd", "mix",
                                      "gd_mtd", "gd_ytd"}
    for col, kind in kinds:
        assert kind in {"text", "money", "pct", "gd"}, (col, kind)
