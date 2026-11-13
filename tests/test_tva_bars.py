"""TvA MTD bar pages (Manav, 13 Nov 2026) — grouping, labels and pages, on made-up rows (no live data)."""
import pandas as pd

import tva_bars as TB


def _sheet():
    rows = [
        dict(code=1, city="SILIGURI", region="East & NE", name="Sevok Road", brand="MANYAVAR", principal="VFL",
             mtd=50_000.0, mtd_target=400_000.0),
        dict(code=2, city="SILIGURI", region="East & NE", name="City Centre", brand="TURTLE", principal="TL",
             mtd=10_000.0, mtd_target=600_000.0),
        dict(code=3, city="AGARTALA", region="East & NE", name="Agartala", brand="MANYAVAR", principal="VFL",
             mtd=100_000.0, mtd_target=300_000.0),
        dict(code=4, city="GUWAHATI", region="East & NE", name="New Store", brand="SABHYATA", principal="SAB",
             mtd=0.0, mtd_target=None),
    ]
    return {"asof": pd.Timestamp("2026-11-12"), "rows": rows}


def test_city_groups_label_brand_then_location_and_put_the_furthest_behind_first(monkeypatch):
    monkeypatch.setattr(TB.SL, "for_store", lambda c, a: {"C": 360_000, "B": 400_000, "A": 440_000, "SUPER A": 572_000} if c == 1 else {})
    g = {x["title"]: x for x in TB.groups_by_city(_sheet())}
    sil = g["SILIGURI"]["rows"]
    assert [r["code"] for r in sil] == [2, 1]                       # 1.7% of B before 12.5%
    assert g["SILIGURI"]["label"](sil[1]) == "Manyavar  ·  Sevok Road"
    assert sil[1]["ratios"]["SUPER A"] == 572_000 / 400_000 and sil[0]["ratios"] == {"B": 1.0}


def test_parent_company_groups_label_city_then_location_without_repeating_the_city(monkeypatch):
    monkeypatch.setattr(TB.SL, "for_store", lambda c, a: {})
    g = {x["title"]: x for x in TB.groups_by_principal(_sheet())}
    assert list(g)[0] == "VFL"                                       # biggest target first
    lab = {r["code"]: g["VFL"]["label"](r) for r in g["VFL"]["rows"]}
    assert lab == {1: "Siliguri  ·  Sevok Road", 3: "Agartala"}


def test_pages_render_for_both_groupings_and_a_store_without_a_target_does_not_break(monkeypatch):
    monkeypatch.setattr(TB.SL, "for_store", lambda c, a: {})
    for by in ("city", "principal"):
        pages = TB.render_pages(_sheet(), 2400, 1500, by=by)
        assert pages and all(p.size[0] == 2400 and p.size[1] >= 1500 for p in pages)
