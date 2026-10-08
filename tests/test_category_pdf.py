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


def test_a_category_is_what_the_customer_buys_whoever_the_brand():
    """★ Manav, 6 Oct: saree is a category, Mohey or Twamev."""
    d = C.categorise(_rows([
        ("A", "MOHEY-SAREE", "SAREE-09", "Mohey", 1, 1),
        ("A", "TWAMEV-WOMEN", "TWAM SAREE", "Twamev", 1, 1),
        ("A", "KURTA SET", "KURTA SET-14", "Manyavar", 1, 1),
        ("A", "TWAMEV-MEN", "TWAM KURTA SET", "Twamev", 1, 1),
        ("A", "DIWAS", "KURTA SET-DIWAS", "Manyavar", 1, 1),
        ("A", "MANTHAN", "KURTA SET-MTHN", "Manthan", 1, 1),
        ("A", "JODHPURI SUIT", "JODHPURI SUIT SET", "Manyavar", 1, 1),
        ("A", "TWAMEV-MEN", "TWAM JODHPURI SET", "Twamev", 1, 1)]))
    assert list(zip(d["_grp"], d["_cat"])) == [
        ("Womenswear", "Saree"), ("Womenswear", "Saree"),
        ("Menswear", "Kurta set"), ("Menswear", "Kurta set"), ("Menswear", "Kurta set"),
        ("Menswear", "Kurta set"), ("Menswear", "Jodhpuri"), ("Menswear", "Jodhpuri")]


def test_accessories_are_split_into_what_they_are_and_kids_go_to_kidswear():
    d = C.categorise(_rows([
        ("A", "MANYAVAR ACCESSORIES", "JOOTI", "Manyavar", 1, 1),
        ("A", "TWAMEV-MEN", "TWAM FOOTWEAR", "Twamev", 1, 1),
        ("A", "MANYAVAR ACCESSORIES", "SAFA", "Manyavar", 1, 1),
        ("A", "MANYAVAR ACCESSORIES", "SOCKS", "Manyavar", 1, 1),
        ("A", "MANYAVAR ACCESSORIES", "JOOTI CHILD", "Manyavar", 1, 1),
        ("A", "LOWERS", "CHILD DHOTI", "Manyavar", 1, 1),
        ("A", "CHILD", "CHILD KURTA SET-09", "Manyavar", 1, 1),
        ("A", "TWAMEV-MEN", "TWAM MALA", "Twamev", 1, 1)]))
    assert list(zip(d["_grp"], d["_cat"])) == [
        ("Menswear", "Footwear"), ("Menswear", "Footwear"), ("Menswear", "Safa & bandanna"),
        ("Menswear", "Men's accessories"), ("Kidswear", "Other kidswear"),
        ("Kidswear", "Other kidswear"), ("Kidswear", "Kids kurta set"),
        ("Menswear", "Men's accessories")]


def test_unknown_divisions_go_to_other():
    d = C.categorise(_rows([("A", "OUTPUT ITEM", "X", "Other", 1, 1),
                            ("A", "SOMETHING NEW", "X", "Manyavar", 1, 1)]))
    assert list(zip(d["_grp"], d["_cat"])) == [("Other", "Other"), ("Other", "Other")]


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


def test_group_label_on_top_and_its_total_at_the_bottom():
    rows, _t, _ = C.table_rows(_win(), ["A"])
    assert [r["cat"] for r in rows] == ["MENSWEAR", "Kurta set", "Sherwani", "Menswear total",
                                        "WOMENSWEAR", "Saree", "Womenswear total"]
    assert rows[0]["_head"] and rows[3]["_sub"] and rows[4]["_head"] and rows[6]["_sub"]


def test_a_subtotal_growth_is_worked_from_its_summed_pair():
    rows, total, _ = C.table_rows(_win(), ["A"])
    mv = rows[3]
    assert mv["YTD_ty"] == 400 and abs(mv["YTD_gd"] - 0.0) < 1e-9          # 400 against 400
    assert abs(rows[1]["YTD_gd"] - 50.0) < 1e-9                             # kurta 300 v 200
    assert abs(total["YTD_gd"] - (500 / 350 - 1) * 100) < 0.05             # rounded to 0.1


def test_a_negative_last_year_gives_no_growth_rather_a_wrong_one():
    rows, _t, _ = C.table_rows(_win(), ["A"])
    assert rows[5]["YTD_gd"] is None                                        # saree LY was returns only


def test_price_per_piece_and_share():
    rows, total, _ = C.table_rows(_win(), ["A"])
    kurta = rows[1]
    assert kurta["ppc_ty"] == 100 and kurta["ppc_ly"] == 50 and abs(kurta["ppc_gd"] - 100) < 1e-9
    assert abs(sum(r["share"] for r in rows if not r.get("_sub") and not r.get("_head")) - 100) < 1e-9
    assert total["share_chg"] is None


def test_movers_ignore_subtotals():
    rows, _t, _ = C.table_rows(_win(), ["A"])
    up, dn = C.movers(rows)
    assert [r["cat"] for r in up] == ["Kurta set"] and [r["cat"] for r in dn] == ["Sherwani"]


# --- the brand-wise report (kept as its own report, 6 Oct) ---------------------------
def test_by_brand_twamev_is_split_into_its_own_categories():
    d = C.categorise_by_brand(_rows([
        ("A", "TWAMEV-MEN", "TWAM KURTA SET", "Twamev", 1, 1),
        ("A", "TWAMEV-WOMEN", "TWAM SAREE", "Twamev", 1, 1),
        ("A", "TWAMEV-MEN", "TWAM MALA", "Twamev", 1, 1),
        ("A", "MOHEY-SAREE", "SAREE-09", "Mohey", 1, 1)]))
    assert list(zip(d["_grp"], d["_cat"])) == [
        ("Twamev", "Kurta set"), ("Twamev", "Saree"), ("Twamev", "Accessories & other"),
        ("Mohey", "Saree")]


def test_by_brand_sub_brands_sit_under_their_parent():
    d = C.categorise_by_brand(_rows([("A", "MEBAZ", "X", "Mebaz", 1, 1),
                                     ("A", "MANTHAN", "X", "Manthan", 1, 1)]))
    assert list(zip(d["_grp"], d["_cat"])) == [("Mohey", "Mebaz"), ("Manyavar", "Manthan")]


def test_by_brand_groups_follow_the_brand_order():
    ty = C.categorise_by_brand(_rows([("A", "MOHEY-SAREE", "SAREE-09", "Mohey", 50, 1),
                                      ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 100, 1)]))
    rows, _t, _ = C.table_rows({"MTD": (ty, ty), "YTD": (ty, ty)}, ["A"], C.BRAND_GROUPS)
    assert [r["cat"] for r in rows] == ["MANYAVAR", "Kurta set", "Manyavar total",
                                        "MOHEY", "Saree", "Mohey total"]
    assert rows[4]["_label"] == "Mohey saree"


# --------------------------------------------------------------------------- price brackets
def test_price_brackets_by_selling_price_per_piece():
    """★ Manav, 9 Oct: brackets on the bill's selling price, ₹5,000 steps from ₹1,000 to ₹50,000."""
    d = C.categorise_by_price(_rows([
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 999, 1),
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 1000, 1),
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 5000, 1),
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 5001, 1),
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 20000, 2),      # two pieces at 10,000
        ("A", "MOHEY-LEHENGA", "LEHENGA-09", "Mohey", 50001, 1),
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", -5001, -1)]))   # a return, at its own price
    assert d["_cat"].tolist() == ["Under ₹1,000", "₹1,000–5,000", "₹1,000–5,000", "₹5,001–10,000",
                                  "₹5,001–10,000", "Above ₹50,000", "₹5,001–10,000"]
    assert d["_grp"].tolist()[5] == "Womenswear"
    assert len(C.BRACKETS) == 12


def test_price_rows_overall_first_in_price_order_and_tie_to_the_total():
    d = C.categorise_by_price(_rows([
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 30000, 1),
        ("A", "KURTA SET", "KURTA SET-09", "Manyavar", 2000, 1),
        ("A", "MOHEY-SAREE", "SAREE-09", "Mohey", 3000, 1)]))
    win = {"MTD": (d, d.iloc[0:0]), "YTD": (d, d.assign(**{L.COL_AMOUNT: d[L.COL_AMOUNT] / 2}))}
    rows, total, _ = C.table_rows(win, ["A"], C.GROUPS, C.BRACKETS)
    assert rows[0]["cat"] == "OVERALL"
    ov = [r for r in rows if r.get("_ov")]
    assert [r["cat"] for r in ov] == ["₹1,000–5,000", "₹25,001–30,000"]   # price order, not size
    assert ov[0]["YTD_ty"] == 5000 and ov[0]["YTD_ly"] == 2500 and ov[0]["YTD_gda"] == 2500
    assert sum(r["YTD_ty"] for r in ov) == total["YTD_ty"]
    # the store page: sections only
    rows2, _, _ = C.table_rows(win, ["A"], C.GROUPS, C.BRACKETS, overall=False)
    assert not any(r.get("_ov") for r in rows2) and rows2[0]["cat"] == "MENSWEAR"
    # the movers line names the section when there is no OVERALL block
    assert all(r["_label"].startswith(("Menswear", "Womenswear")) for r in rows2
               if not r.get("_head") and not r.get("_sub"))
