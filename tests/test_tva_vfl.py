"""The VFL snapshot (16 Oct 2026): Manyavar / Mohey / Twamev stores only, same arithmetic as the estate block."""
import pandas as pd
import report_td as RTD


def _row(region, brand, mtd, tgt):
    return {"region": region, "brand": brand, "mtd": mtd, "mtd_target": tgt, "ytd": mtd * 5,
            "year_target": tgt * 12, "from": "2026-04-01", "ttm": None}


def test_only_vfl_brands_count_and_regions_split():
    rows = [_row("East & NE", "MANYAVAR & MOHEY", 100, 200), _row("East & NE", "TURTLE", 50, 100),
            _row("South", "MANYAVAR", 30, 60), _row("East & NE", "Twamev", 10, 20)]
    sheet = {"rows": rows, "asof": pd.Timestamp("2026-10-15"), "fy_start": pd.Timestamp("2026-04-01")}
    mtd = [r for k, r in RTD.tva_exec_rows(sheet, RTD.is_vfl)][:4]
    assert [r["label"] for r in mtd] == ["MONTH TO DATE", "OVERALL", "EAST & NE", "SOUTH"]
    assert mtd[1]["ach"] == 140 and mtd[1]["target"] == 280        # Turtle left out
    assert mtd[2]["ach"] == 110 and mtd[3]["ach"] == 30
    assert RTD.tva_exec_rows(sheet)[1][1]["ach"] == 190              # the estate block is unchanged
