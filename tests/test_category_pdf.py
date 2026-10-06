"""Category analysis VFL — the category rules and the arithmetic, on made-up rows (no live data)."""
import pandas as pd

import category_pdf as C
import loader as L


def _rows(rows):
    """rows: (store, division, section, brand, sales, pieces)"""
    return pd.DataFrame(rows, columns=[L.COL_STORE_LABEL, L.COL_DIVISION, L.COL_SECTION,
                                       L.COL_BRAND, L.COL_AMOUNT, "_units"])


def test_collection_codes_never_split_a_category():
    d = C.categorise(_rows([
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 100, 1),
        ("A", "KURTA SET", "KURTA SET-14", "Manyavar", 100, 1),
        ("A", "KURTA SET", "KURTA SET O-S", "Manyavar", 100, 1)]))
    assert d["_cat"].unique().tolist() == ["Kurta set"]


def test_twamev_is_split_into_its_own_categories():
    d = C.categorise(_rows([
        ("A", "TWAMEV-MEN", "TWAM KURTA SET", "Twamev", 1, 1),
        ("A", "TWAMEV-MEN", "TWAM JODHPURI SET", "Twamev", 1, 1),
        ("A", "TWAMEV-WOMEN", "TWAM SAREE", "Twamev", 1, 1),
        ("A", "TWAMEV-MEN", "TWAM MALA", "Twamev", 1, 1)]))
    assert list(zip(d["_grp"], d["_cat"])) == [
        ("Twamev", "Kurta set"), ("Twamev", "Jodhpuri set"), ("Twamev", "Saree"),
        ("Twamev", "Accessories & other")]


def test_sub_brands_sit_under_their_parent_and_unknowns_under_other():
    d = C.categorise(_rows([
        ("A", "MEBAZ", "X", "Mebaz", 1, 1), ("A", "MANTHAN", "X", "Manthan", 1, 1),
        ("A", "OUTPUT ITEM", "X", "Other", 1, 1), ("A", "SOMETHING NEW", "X", "Manyavar", 1, 1)]))
    assert list(zip(d["_grp"], d["_cat"])) == [
        ("Mohey", "Mebaz"), ("Manyavar", "Manthan"), ("Other", "Other"), ("Other", "Other")]


def _win():
    ty = C.categorise(_rows([
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 300, 3),
        ("A", "SHERWANI SET", "SHERWANI O-S", "Manyavar", 100, 1),
        ("A", "MOHEY-SAREE", "SAREE-09", "Mohey", 100, 4)]))
    ly = C.categorise(_rows([
        ("A", "KURTA SET", "KURTA SET-14", "Manyavar", 200, 4),
        ("A", "SHERWANI SET", "SHERWANI O-S", "Manyavar", 200, 2),
        ("A", "MOHEY-SAREE", "SAREE-14", "Mohey", -50, 1)]))
    return {"MTD": (ty, ly), "YTD": (ty, ly)}


def test_brand_heading_comes_before_its_categories():
    rows, _t, _ = C.table_rows(_win(), ["A"])
    assert [r["cat"] for r in rows] == ["Manyavar", "Kurta set", "Sherwani", "Mohey", "Saree"]
    assert rows[0]["_sub"] and rows[3]["_sub"]


def test_a_subtotal_growth_is_worked_from_its_summed_pair():
    rows, total, _ = C.table_rows(_win(), ["A"])
    mv = rows[0]
    assert mv["YTD_ty"] == 400 and abs(mv["YTD_gd"] - 0.0) < 1e-9          # 400 against 400
    assert abs(rows[1]["YTD_gd"] - 50.0) < 1e-9                             # kurta 300 v 200
    assert abs(total["YTD_gd"] - (500 / 350 - 1) * 100) < 1e-9


def test_a_negative_last_year_gives_no_growth_rather_a_wrong_one():
    rows, _t, _ = C.table_rows(_win(), ["A"])
    assert rows[4]["YTD_gd"] is None                                        # saree LY was returns only


def test_price_per_piece_and_share():
    rows, total, _ = C.table_rows(_win(), ["A"])
    kurta = rows[1]
    assert kurta["ppc_ty"] == 100 and kurta["ppc_ly"] == 50 and abs(kurta["ppc_gd"] - 100) < 1e-9
    assert abs(sum(r["share"] for r in rows if not r.get("_sub")) - 100) < 1e-9
    assert total["share_chg"] is None


def test_movers_ignore_subtotals():
    rows, _t, _ = C.table_rows(_win(), ["A"])
    up, dn = C.movers(rows)
    assert [r["cat"] for r in up] == ["Kurta set"] and [r["cat"] for r in dn] == ["Sherwani"]
