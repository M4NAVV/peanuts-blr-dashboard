"""Standalone VFL report PDF — the two workbook sheets (VFL Growth/Degrowth and
VFL Gender Contribution %) compiled into one shareable file.

Reuses the shared ``portfolio_pdf`` engine (constant thin frame, uniform page
width, per-page repeated column headers via pagination, 2x-supersampled crisp
text) so the VFL PDF looks identical in style to the portfolio one.
"""
from __future__ import annotations

import io

import pandas as pd

from imaging import _LOCK
import loader as L
import portfolio_pdf as PP

_FOOTER = "Peanuts Retail · VFL"


def build(df, asof, gen_date=None, basis_label=""):
    """Compile the VFL G/D + VFL Gender sheets into one PDF (bytes). `df` is the
    (already filtered) VFL frame; `asof` sets the sum windows (month-end matches
    the workbook), `gen_date` the projection day-count anchor (the live date)."""
    asof = pd.Timestamp(asof)
    gen_date = asof if gen_date is None else pd.Timestamp(gen_date)
    asof_label = f"As of {asof:%d %b %Y}" + (f" · {basis_label}" if basis_label else "")

    with _LOCK:
        contents = []   # (section, content_image), each may span multiple pages

        # 1) VFL — Growth / Degrowth (18-col brand-line sheet, paginated)
        gd, gd_rt = L.vfl_gd_report(df, asof=asof, gen_date=gen_date)
        # Day sales under 50k are flagged red on this sheet only — the two
        # gender sheets carry no day-sale column.
        PP._add_sheet(contents, "VFL — Growth / Degrowth", gd, gd_rt,
                      money=L.VFL_GD_MONEY, pct=L.VFL_GD_PCT, sign=L.VFL_GD_PCT,
                      money_dp=0, row_bg=PP.VFL_ROW_BG,
                      cell_rules=PP.VFL_CELL_RULES)

        # 2) VFL — Gender Contribution % (main table + Region × Gender summary)
        gmain, gm_rt, gsum, gs_rt = L.vfl_gender_report(df, asof=asof)
        PP._add_sheet(contents, "VFL — Gender Contribution %", gmain, gm_rt,
                      money=L.VFL_GENDER_MONEY, pct=L.VFL_GENDER_PCT, sign=[],
                      money_dp=0, row_bg=PP.VFL_ROW_BG)
        PP._add_sheet(contents, "VFL — Region × Gender Summary", gsum, gs_rt,
                      money=L.VFL_GENDER_MONEY, pct=L.VFL_GENDER_PCT, sign=[],
                      money_dp=0, row_bg=PP.VFL_ROW_BG)

        # Executive Snapshot — replaces the cover. Sized to the box the sheets
        # establish, then placed first.
        import exec_snapshot as ES
        tbl_w = max(c.width for _, c in contents)
        tbl_h = max(c.height for _, c in contents)
        # Whole estate first, then one page per region, each on its own scope.
        snaps = [(None, "Executive Snapshot")]
        for r in ES.regions_of(df, vfl=True):
            snaps.append((r, f"Executive Snapshot · {r}"))
        contents = [(sec, ES.content(
            ES.vfl_metrics(df, asof, gen_date, basis_label, region=r),
            tbl_w, tbl_h)) for r, sec in snaps] + contents

        page_w = max(c.width for _, c in contents) + 2 * (PP.MARGIN + PP.FRAME + PP.PAD)
        page_h = max(c.height for _, c in contents) + (
            PP.MARGIN + PP.FRAME + PP.HEADER_H + PP.PAD + PP.FOOTER_H
            + PP.FRAME + PP.MARGIN)
        pages = []
        total = len(contents)
        for i, (section, content) in enumerate(contents, start=1):
            pages.append(PP._compose(content, section, asof_label, i, total, page_w,
                                     footer_right=_FOOTER, page_h=page_h))

        return PP.save_pages(pages)
