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


def _pc(v) -> str:
    return "—" if v != v else f"{v:+.1f}%"


def _brand_reading(panels) -> str:
    """The page in two sentences, built from the same rows it sits under."""
    by = {r: (rows, total) for r, rows, total in panels}
    rows, total = by.get("Total", panels[-1][1:])
    share = ", ".join(f"{r['brand']} {r['mix']:.1f}%" for r in rows)
    out = (f"Of the year so far, {share}. The estate is {_pc(total['gd_ytd'])} "
           f"on last year and {_pc(total['gd_mtd'])} on the month.")
    regions = [(r, t) for r, _rw, t in panels if r != "Total"]
    if len(regions) == 2:
        (r1, t1), (r2, t2) = sorted(regions, key=lambda x: -(x[1]["gd_mtd"]
                                                             if x[1]["gd_mtd"] == x[1]["gd_mtd"]
                                                             else -999))
        out += (f" The month is being carried by {r1} at "
                f"{_pc(t1['gd_mtd'])}, against {r2} at {_pc(t2['gd_mtd'])}.")
    return out


def _beside(images, gap=None):
    """Panels across the page, top-aligned — the landscape sheet's own shape.

    Three region panels stacked would leave two thirds of a landscape page
    white and force the eye to travel down to compare regions that belong side
    by side. Across, the same brand sits on the same line in all three.
    """
    from PIL import Image
    gap = PP._px(80) if gap is None else gap
    w = sum(i.width for i in images) + gap * (len(images) - 1)
    h = max(i.height for i in images)
    out = Image.new("RGB", (w, h), (255, 255, 255))
    x = 0
    for i in images:
        out.paste(i, (x, 0))
        x += i.width + gap
    return out


def _stack(images, gap=None):
    """Several tables as one content image, centred on each other.

    A short table on this engine gets a page of its own; three of them would be
    three near-empty pages. Stacked, they are one page that can be read without
    turning it, which is the whole point of a summary sheet.
    """
    from PIL import Image
    gap = PP._px(46) if gap is None else gap
    w = max(i.width for i in images)
    h = sum(i.height for i in images) + gap * (len(images) - 1)
    out = Image.new("RGB", (w, h), (255, 255, 255))
    y = 0
    for i in images:
        out.paste(i, ((w - i.width) // 2, y))
        y += i.height + gap
    return out


def build(df, asof, gen_date=None, basis_label=""):
    """Compile the VFL G/D + VFL Gender sheets into one PDF (bytes). `df` is the
    (already filtered) VFL frame; `asof` sets the sum windows (month-end matches
    the workbook), `gen_date` the projection day-count anchor (the live date)."""
    asof = pd.Timestamp(asof)
    gen_date = asof if gen_date is None else pd.Timestamp(gen_date)
    asof_label = f"As of {asof:%d %b %Y}" + (f" · {basis_label}" if basis_label else "")

    import yearend as _YE
    _shut = _YE.closed_codes(asof) if _YE.enabled() else set()

    def _dim(disp):
        """Year-end cells of CLOSED stores, greyed. Same rule and same source
        as the portfolio PDF (`yearend.closed_codes`), so the two files can
        never disagree about which stores are dead."""
        if not _shut or _YE.COL_PF not in disp.columns \
                or "STORE CODE" not in disp.columns:
            return frozenset()
        codes = pd.to_numeric(disp["STORE CODE"], errors="coerce")
        return frozenset((i, _YE.COL_PF)
                         for i, c in enumerate(codes)
                         if pd.notna(c) and int(c) in _shut)

    with _LOCK:
        contents = []   # (section, content_image), each may span multiple pages

        # 1) VFL — Growth / Degrowth (18-col brand-line sheet, paginated)
        gd, gd_rt = L.vfl_gd_report(df, asof=asof, gen_date=gen_date)
        # Day sales under 50k are flagged red on this sheet only — the two
        # gender sheets carry no day-sale column.
        # ★ THE MONEY LIST MUST BE RESOLVED, NOT THE MODULE CONSTANT (12 Sep).
        # `vfl_gd_cols()` swaps PROJECTED YTD + TTM SALES for the single
        # "Sum of YEAR END PROJECTED/TTM" column, so the frame arriving here
        # carries a column name that `VFL_GD_MONEY` has never heard of. Passing
        # the raw constant left it in no bucket, and an undeclared numeric
        # column prints as `str(v)` — `1106344252.8109756`, left-aligned,
        # beside neighbours reading `1,07,25,02,127`. `app.py` already calls
        # `vfl_gd_money()` for the on-screen table, which is why the screen was
        # right and only the PDF was wrong.
        PP._add_sheet(contents, "VFL — Growth / Degrowth", gd, gd_rt,
                      money=L.vfl_gd_money(), pct=L.VFL_GD_PCT, sign=L.VFL_GD_PCT,
                      money_dp=0, row_bg=PP.VFL_ROW_BG,
                      cell_rules=PP.VFL_CELL_RULES, dim_cells=_dim(gd))

        # 2) VFL — Gender Contribution % (main table + Region × Gender summary)
        gmain, gm_rt, gsum, gs_rt = L.vfl_gender_report(df, asof=asof)
        PP._add_sheet(contents, "VFL — Gender Contribution %", gmain, gm_rt,
                      money=L.VFL_GENDER_MONEY, pct=L.VFL_GENDER_PCT, sign=[],
                      money_dp=0, row_bg=PP.VFL_ROW_BG)
        PP._add_sheet(contents, "VFL — Region × Gender Summary", gsum, gs_rt,
                      money=L.VFL_GENDER_MONEY, pct=L.VFL_GENDER_PCT, sign=[],
                      money_dp=0, row_bg=PP.VFL_ROW_BG)

        # 4) VFL — Brand Contribution, the LAST page (Manav, 24 Sep: *"the
        # page should be the last page of this report"*). One panel per
        # region, one line per brand. Manav, 24 Sep, on the first draft of this page: *"this report
        # is a difficult read, visually cluttered."*
        #
        # ★ IT IS NOT DRAWN IN THE WORKBOOK STYLE, DELIBERATELY. The sheets
        # around it are the client's own spreadsheet reproduced — a full grid on
        # every cell, ten columns of eight-digit rupees, a header read three
        # times over. That is right for a sheet somebody reconciles line by
        # line and wrong for a summary of nine numbers, where the grid is most
        # of the ink on the page. This page uses the pack style instead:
        # banded rows, no grid, money in crores, and the region as a heading
        # rather than as a prefix repeated on every column.
        import festive_admin as FADM
        import snapshots_a4 as A4

        _BSPEC = [("brand", "text", "BRAND"), ("day", "money", "DAY"),
                  ("mtd", "money", "MTD"), ("ytd", "money", "YTD"),
                  ("mix", "pct", "SHARE"), ("gd_mtd", "gd", "G/D\nMTD"),
                  ("gd_ytd", "gd", "G/D\nYTD")]
        _bpanels = L.vfl_brand_report(df, asof=asof, gen_date=gen_date)

        def _draw_panels(font_px):
            # ★ NATURAL WIDTH, NOT A WIDTH I GUESSED. Handing the table a box
            # narrower than its own text made it claw the difference back out
            # of the one text column, and `Manyavar` printed over the figure
            # beside it. `fill=False` lets the data size the table.
            out = []
            for _region, _rows, _total in _bpanels:
                t = FADM.table_image(_rows, _BSPEC, PP._px(4000),
                                     font_px=font_px, total_row=_total,
                                     fill=False)
                out.append(_stack([A4._caption(t.width, _region, ""), t],
                                  gap=PP._px(16)))
            return _beside(out, gap=PP._px(90))

        # ★★ THE TYPE IS SIZED TO FIT, NOT SET AND HOPED FOR (Manav, 24 Sep:
        # *"its stretched side to side, might overflow by end of year"*). These
        # figures only grow — a 39 Cr year becomes a 60 Cr one, `100.0%` in the
        # share column, and every panel widens with them. The page width of
        # this whole document is the width of its widest sheet, so a panel grid
        # that outgrew the G/D sheet would not clip: it would quietly widen
        # EVERY page and leave the sheets that matter floating in white. So the
        # grid is drawn at the largest size that still sits inside a margin,
        # and it will simply step down a point as the year fills up.
        # ~5% of clear page either side: enough to read as a margin, not so
        # much that the type has to shrink to buy it.
        _budget = int(max(c.width for _, c in contents) * 0.90)
        for _fpx in (46, 42, 38, 34, 30, 26):
            _grid = _draw_panels(_fpx)
            if _grid.width <= _budget:
                break
        # ★ ONE LINE OF READING, not a second table. The panels say what the
        # numbers are; this says what they mean, which is the thing a summary
        # page is for — and it is computed from the same frames, so it cannot
        # describe a figure that is not above it.
        _say = A4._text_block(_grid.width, [(_brand_reading(_bpanels),
                                            A4._ft(30)[0], A4.SUB)])
        contents.append(("VFL — Brand Contribution",
                         _stack([_grid, _say], gap=PP._px(44))))

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
