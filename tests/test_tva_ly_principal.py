"""Target vs achievement: last year + like-to-like GD%, and the parent-company page (Manav, 12 Nov 2026).
"Add LY MTD and GD% | LY YTD GD%" · "one more page … PARENT COMPANY WISE | LIKE SABHYATA/VFL/ABFRL" · principal from
the store master · South LY from the VFL feed's previous operator · GD% like to like."""
import pandas as pd

import report_td as R


def _rows():
    base = dict(mtd_target=100.0, ytd_target=1000.0, year_target=2000.0, mtd_bal=0.0, ytd_bal=0.0, ttm=0.0,
                region="East & NE", city="X", name="L", **{"from": pd.Timestamp("2026-04-01")})
    return [
        {**base, "code": 1, "brand": "MANYAVAR", "principal": "VFL", "mtd": 120.0, "ytd": 1100.0,
         "mtd_ty_l2l": 120.0, "mtd_ly": 100.0, "ytd_ty_l2l": 1100.0, "ytd_ly": 1000.0},
        {**base, "code": 2, "brand": "SABHYATA", "principal": "SAB", "mtd": 50.0, "ytd": 400.0,
         "mtd_ty_l2l": 50.0, "mtd_ly": 100.0, "ytd_ty_l2l": 400.0, "ytd_ly": 500.0},
        # a new store: no comparable last year — blank GD%, and it must NOT enter any total's pair
        {**base, "code": 3, "brand": "TURTLE", "principal": "TL", "mtd": 80.0, "ytd": 300.0,
         "mtd_ty_l2l": None, "mtd_ly": None, "ytd_ty_l2l": None, "ytd_ly": None},
    ]


def test_gd_is_from_the_pair_and_blank_without_last_year():
    r = _rows()
    assert R._tva_gd(r[0], "mtd") == "+20.0" and R._tva_gd(r[1], "ytd") == "-20.0"
    assert R._tva_gd(r[2], "mtd") == ""


def test_a_totals_gd_is_like_to_like_never_an_average_of_percentages():
    t = R._tva_total(_rows(), "G. TOTAL")
    assert t["mtd_ty_l2l"] == 170.0 and t["mtd_ly"] == 200.0          # the new store is out of the pair
    assert R._tva_gd(t, "mtd") == "-15.0"                              # (170-200)/200, not avg(+20, -50)
    assert t["mtd"] == 250.0                                           # but its sales are in ACHIEVED


def test_the_parent_page_renders_one_row_per_principal():
    sheet = {"rows": _rows(), "asof": pd.Timestamp("2026-11-11"), "principal_read": True}
    img = R.render_tva_principal(sheet)
    assert img.width > img.height                                      # a landscape table


def test_the_report_is_two_pages_store_sheet_then_parent_company():
    from pathlib import Path
    src = Path("report_td.py").read_text()
    assert "render_tva_principal(sheet, fill_w=main.width)" in src
    assert "render_target_vs_ach(sheet, by=\"principal\")" in src
    assert "own_heights=True" in src


def test_page_three_groups_stores_under_their_principal_with_a_total():
    """Manav, 12 Nov 2026: "the first page, but with brands as the subtotals. so, vfl and all under VFL"."""
    g = R._tva_group_principal(_rows())
    kinds = [(k, r.get("name") if k == "subtotal" else r["principal"]) for k, r in g]
    assert ("subtotal", "VFL TOTAL") in kinds and ("subtotal", "SAB TOTAL") in kinds
    first_total = next(i for i, (k, _) in enumerate(kinds) if k == "subtotal")
    assert all(p == kinds[first_total][1].replace(" TOTAL", "") for k, p in kinds[:first_total])
