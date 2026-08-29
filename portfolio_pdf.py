"""Portfolio-mode report PDF — the five workbook sheets compiled into one
shareable, print-clean file, in the dashboard's order:

    MW Data · GD Sheet · Brand-wise GD · Loc-wise GD · Average

Deliberately self-contained (its own Pillow rendering + page composition) so it
ships independently of the VFL report PDF. It reuses only the process-wide font
cache and render lock from ``imaging`` — no matplotlib (which crashed the deploy).

Design goals (in priority order): readability, then a CONSTANT thin frame with
identical margins on every page. Every page is rendered to the SAME width (the
widest sheet drives it); narrower sheets are centred inside the frame, so the
border is visually constant as you flip through. Pages share one height too, so
the document doesn't change size as you scroll.

Text is rasterised exactly once, at final size, and the page is never resampled
(see ``_S``) — resampling is what makes cells look soft. Margins are therefore
kept tight and the point size large, since on-page sharpness is a function of
how many pixels each glyph gets.
"""
from __future__ import annotations

import io
import math
import re

import pandas as pd
from PIL import Image, ImageDraw

from imaging import _fonts, _LOCK
from portfolio_loader import (
    gd_sheet_report, brand_wise_gd_report, loc_wise_gd_report, average_report,
    mw_data, mw_layout, _MW_STD, _MW_REG,
)

# --- palette (RGB) --------------------------------------------------------- #
MAROON = (122, 31, 43)
GOLD = (185, 150, 83)
GOLD_TXT = (58, 42, 18)
DARK = (31, 41, 55)
MUTED = (110, 96, 82)
RED = (192, 20, 60)
GREEN = (19, 122, 58)
WHITE = (255, 255, 255)
LINE = (231, 225, 214)               # hairline (frame furniture, not the table)

# --- table palette, lifted from the client's GROWTH DEGROWTH workbook print -- #
# Sampled directly off the reference PDF, so these are their exact Excel fills.
HDR_BG = (218, 238, 243)             # #DAEEF3 pale blue — column headers
TOTAL_BG = (255, 255, 0)             # #FFFF00 yellow  — total / subtotal rows
NEG_INK = (255, 0, 0)                # #FF0000 red — negative figures. Applied
                                     # to the TEXT, not as a cell fill: a solid
                                     # block fights the yellow total rows and
                                     # reads as alarm rather than pointing at
                                     # anything. The figures are the message.
NEG_BG = NEG_INK                     # retained for callers that name the colour
GRID = (99, 99, 99)                  # full gridline, every cell
INK = (0, 0, 0)                      # body text

# Row-type → (background, bold?). The workbook highlights every total tier the
# same yellow on the GD/Brand/Loc/Average sheets.
_ROW_BG = {
    "subtotal":   (TOTAL_BG, True),
    "grand":      (TOTAL_BG, True),
    "storetotal": (TOTAL_BG, True),
    "block":      (TOTAL_BG, True),
    # A store shown as its comparable and non-comparable halves. Tinted a step
    # under the header blue so the pair reads as detail belonging to the total
    # beneath them, rather than as two more stores.
    "split":      ((237, 246, 249), False),
    # LIKE TO LIKE / NO L2L — the sheet's own summary of itself, and the figure
    # page 1 prints. Header blue rather than a third yellow, so it does not read
    # as one more total in a column of them.
    "summary":    (HDR_BG, True),
}

# The VFL sheets in the same workbook use a graded tier palette instead of flat
# yellow. Pass this as `row_bg=` to render those the way their VFL pages look.
VFL_ROW_BG = {
    "storetotal": ((253, 233, 217), True),   # #FDE9D9 peach — MEN/WOMEN totals
    "subtotal":   ((149, 179, 215), True),   # #95B3D7 blue  — {code} totals
    "loctotal":   ((146, 208, 80), True),    # #92D050 green — location totals
    "block":      ((146, 208, 80), True),    # region totals
    "grand":      (TOTAL_BG, True),          # #FFFF00 yellow — grand
    # A store shown as its comparable and non-comparable halves, and the
    # sheet's LIKE TO LIKE / NO L2L footer. Same idea as the GD sheet's, in
    # this palette: a pale step under the store-total blue, then header blue.
    "split":      ((220, 230, 241), False),  # #DCE6F1
    "summary":    (HDR_BG, True),
}

_BODY_BG = (255, 255, 255)           # plain white body — no zebra banding

# --- output sizing --------------------------------------------------------- #
# The page is declared A4-landscape-wide whatever its pixel width: the save
# resolution is derived from the two, so more pixels means higher DPI rather
# than a bigger sheet of paper. Pages are NOT resampled (see _S) — that was the
# source of the blur — so the pixel width is whatever the widest sheet needs.
PAGE_PT_W = 842.0                    # A4 landscape width, points
MAX_PX_W = 6500                      # hard safety cap only. Deliberately far
                                     # above any real page: tripping it means
                                     # resampling, and resampling means blur.
                                     # If a sheet ever approaches it, cut
                                     # `font_px` — do NOT let it resample.
# Columns rendered bold in the body (the workbook bolds the store identity).
BOLD_COLS = {"STORE NAME MAIN", "STORE NAME", "STORE CODE", "PARENT",
             "MEN/WOMEN/KIDS", "Region", "Master Location"}
# Growth cells already carry a solid red fill when negative; bolding them too
# makes a dense page read as bands of black. Off by default.
BOLD_SIGN_CELLS = False

# --- conditional formatting ------------------------------------------------ #
# Value-driven text colouring, as (column, predicate, ink, row_types) handed to
# _add_sheet. `row_types` restricts which rows the rule sees; None means every
# row in that column, totals included. Each pack passes its own rules — these
# are NOT shared between the Portfolio and VFL reports.
DAY_SALE_COL = "Sum of DAY SALE FIGURE"

# Portfolio: one row is one store, so the rule is limited to data rows — the
# total rows are already colour-coded and aggregate differently.
DAY_SALE_FLOOR = 5000
PORTFOLIO_CELL_RULES = (
    (DAY_SALE_COL, lambda v: v < DAY_SALE_FLOOR, NEG_INK, {"store"}),
)

# VFL G/D: a higher bar, on the store-total row.
VFL_DAY_SALE_FLOOR = 50000
# Fires on the {code} Total row only — the store's whole day, not each
# brand-line and not the location/region rollups above it.
VFL_CELL_RULES = (
    (DAY_SALE_COL, lambda v: v < VFL_DAY_SALE_FLOOR, NEG_INK, {"subtotal"}),
)

# --- render scale ---------------------------------------------------------- #
# _S used to be 2 (supersample), with the finished page resampled DOWN to fit a
# pixel cap — a net scale of ~1.09 reached via two resampling passes. That second
# pass is what made cells look soft: downscaling throws away FreeType's hinting,
# so stems land between pixels and 1px gridlines smear to grey. We now render
# ONCE, at final size, and never resample. Sharpness comes from glyph pixel size,
# which we buy with tight margins and a larger point size instead.
_S = 1


def _px(n) -> int:
    return int(round(n * _S))


def _ft(size):
    """(regular, emphasis) fonts at `size`, scaled by the render scale."""
    return _fonts(int(round(size * _S)))


# --- page geometry (logical px, scaled by _S at use) ----------------------- #
MARGIN = _px(14)     # white gap from page edge to the frame (tight: the table
                     # earns the width, and width is what buys legible type)
FRAME = _px(2)       # frame thickness (constant, narrow)
PAD = _px(10)        # frame → content padding
HEADER_H = _px(76)   # section-header band height
FOOTER_H = _px(48)   # footer band height
# Cell padding. PAD_X is bought at the expense of legibility: with ~18 columns,
# every pixel of side padding costs 36px of page width, and page width is what
# apparent text size is measured against. Kept tight for that reason.
PAD_X, PAD_Y = _px(9), _px(10)
# Max data width before a column stops growing. Sized from the real strings:
# the widest Division is 439px and the widest Section 486px, so a 320px cap
# meant "MANYAVAR ACCESSORIES" spilled over the number beside it. Departments
# reach 836px and are still capped — those get clipped rather than dictating the
# page width.
COL_CAP = _px(520)


def _fmt_in(x, dec=2) -> str:
    """Indian digit grouping (1,69,709.00), matching app.fmt_in."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return "—"
    neg = float(x) < 0
    x = abs(float(x))
    s = f"{x:.{dec}f}"
    intpart, _, frac = s.partition(".")
    if len(intpart) > 3:
        head, tail = intpart[:-3], intpart[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        intpart = head + "," + tail
    out = intpart + ("." + frac if dec else "")
    return ("-" if neg else "") + out


def _wrap(draw, text, font, max_w):
    """Greedy word-wrap `text` to <= max_w px (never splits a single word)."""
    words = str(text).split()
    if not words:
        return [""]
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if not cur or draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


# --------------------------------------------------------------------------- #
# Generic report table → image
# --------------------------------------------------------------------------- #
# Rows of body per page. The pale-blue column header repeats at the top of every
# page (see _render_chunk), so you never lose the column labels mid-report. The
# count is tuned so a full page lands near A4-landscape proportions with the
# current typeface — a narrower face needs fewer rows to stay that shape.
ROWS_PER_PAGE = 35


def _measure_table(df, *, money=(), pct=(), sign=(), money_dp=0,
                   font_px=32, header_px=28):
    """Measure a report table ONCE — formatted cells, column widths, wrapped
    header layout — so every paginated chunk shares identical columns. Returns a
    dict consumed by `_render_chunk`."""
    reg, bold = _ft(font_px)
    hreg, hbold = _ft(header_px)
    cols = [str(c) for c in df.columns]
    money, pct, sign = set(money), set(pct), set(sign)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def cell_text(c, v):
        if c in money:
            return _fmt_in(v, money_dp)
        if c in pct:
            return "—" if pd.isna(v) else f"{float(v):,.2f}%"
        if isinstance(v, str):
            return v
        return "" if pd.isna(v) else str(v)

    txt = [[cell_text(c, df.iloc[i][c]) for c in cols] for i in range(len(df))]
    is_num = [c in money or c in pct for c in cols]

    # Column widths: data drives width (capped); header wraps to that width.
    # Measure in BOLD — total rows, identity columns and growth cells all render
    # bold, and bold is wider, so measuring in regular would clip them.
    col_w, hdr_lines = [], []
    for j, c in enumerate(cols):
        data_w = max((scratch.textlength(txt[i][j], font=bold)
                      for i in range(len(df))), default=0)
        target = min(max(data_w, _px(30)), COL_CAP)
        lines = _wrap(scratch, c, hbold, target)
        hw = max(scratch.textlength(ln, font=hbold) for ln in lines)
        hdr_lines.append(lines)
        col_w.append(int(math.ceil(max(target, hw))) + 2 * PAD_X)

    asc, desc = reg.getmetrics()
    row_h = asc + desc + 2 * PAD_Y
    hasc, hdesc = hbold.getmetrics()
    hline_h = hasc + hdesc + _px(2)
    head_h = max(len(l) for l in hdr_lines) * hline_h + 2 * PAD_Y

    raw = [[pd.to_numeric(df.iloc[i][c], errors="coerce") for c in cols]
           for i in range(len(df))]

    return dict(cols=cols, txt=txt, raw=raw, is_num=is_num, col_w=col_w,
                hdr_lines=hdr_lines, head_h=head_h, row_h=row_h, hline_h=hline_h,
                W=sum(col_w), reg=reg, bold=bold, hbold=hbold, sign=sign)


def _render_chunk(m, row_types, rows, row_bg=None, cell_rules=()):
    """Render the pale-blue column header + the given body `rows` (indices into
    the measured table) as one page-content image, so the header repeats per
    page. Styled to the client workbook: white ground, a full grid on every
    cell, yellow total rows, red-filled negatives. `row_bg` overrides the
    row-type palette (see VFL_ROW_BG)."""
    W, head_h, row_h, hline_h = m["W"], m["head_h"], m["row_h"], m["hline_h"]
    cols, col_w, txt, is_num = m["cols"], m["col_w"], m["txt"], m["is_num"]
    reg, bold, hbold, sign = m["reg"], m["bold"], m["hbold"], m["sign"]
    row_bg = _ROW_BG if row_bg is None else row_bg
    cell_rules = tuple(cell_rules)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    H = head_h + len(rows) * row_h
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # header (repeated on every page) — pale blue, dark bold text
    d.rectangle([0, 0, W, head_h], fill=HDR_BG)
    x = 0
    for j in range(len(cols)):
        lines = m["hdr_lines"][j]
        ty = head_h - PAD_Y - len(lines) * hline_h + _px(2)
        for ln in lines:
            lw = scratch.textlength(ln, font=hbold)
            d.text((x + (col_w[j] - lw) / 2, ty), ln, font=hbold, fill=INK)
            ty += hline_h
        x += col_w[j]

    # body
    y = head_h
    for i in rows:
        t = row_types[i] if row_types else "store"
        bg, is_bold = row_bg.get(t, (_BODY_BG, False))
        d.rectangle([0, y, W, y + row_h], fill=bg)
        x = 0
        for j, c in enumerate(cols):
            s = txt[i][j]
            f = bold if (is_bold or c in BOLD_COLS) else reg
            color = INK
            # Negative growth is filled red (workbook convention), not just
            # coloured — it has to read at a glance on a phone.
            # Conditional formatting and negative figures both colour the TEXT
            # rather than filling the cell — see NEG_INK.
            for rcol, test, ink, rtypes in cell_rules:
                if c != rcol or (rtypes is not None and t not in rtypes):
                    continue
                v = m["raw"][i][j]
                if v is not None and not pd.isna(v) and test(float(v)):
                    color, f = ink, bold
            if c in sign and s not in ("", "—"):
                if s.lstrip().startswith("-"):
                    color, f = NEG_INK, bold
                elif BOLD_SIGN_CELLS:
                    f = bold
            # Clip to the cell. A value wider than its column would otherwise
            # be drawn straight over the neighbouring figure, which reads as a
            # corrupted number rather than as truncated text.
            # 1px of slack: widths are rounded, and clipping a value that
            # actually fits turns a figure into a truncated one, which is far
            # worse than a slightly tight cell.
            avail = col_w[j] - 2 * PAD_X + 1
            if scratch.textlength(s, font=f) > avail:
                while s and scratch.textlength(s + "…", font=f) > avail:
                    s = s[:-1]
                s += "…"
            tw = scratch.textlength(s, font=f)
            cx = x + col_w[j] - PAD_X - tw if is_num[j] else x + PAD_X
            d.text((cx, y + PAD_Y), s, font=f, fill=color)
            x += col_w[j]
        y += row_h

    # full grid — every column boundary and row boundary, like the workbook
    gx = 0
    for j in range(len(cols)):
        gx += col_w[j]
        d.line([gx, 0, gx, H], fill=GRID, width=1)
    d.line([0, head_h, W, head_h], fill=GRID, width=1)
    for k in range(len(rows) + 1):
        gy = head_h + k * row_h
        d.line([0, gy, W, gy], fill=GRID, width=1)
    d.rectangle([0, 0, W - 1, H - 1], outline=GRID, width=1)
    return img


def _paginate(row_types, budget=ROWS_PER_PAGE):
    """Split row indices into pages of ~`budget` rows, keeping subtotal/total
    rows attached to their group (never orphaned at the top of a new page)."""
    n = len(row_types)
    pages, i = [], 0
    while i < n:
        pages.append(list(range(i, min(i + budget, n))))
        i += budget
    totals = {"subtotal", "block", "grand"}
    for p in range(1, len(pages)):
        while pages[p] and row_types[pages[p][0]] in totals:
            pages[p - 1].append(pages[p].pop(0))
    return [p for p in pages if p]


def _add_sheet(contents, section, disp, rt, *, money, pct, sign, money_dp,
               row_bg=None, cell_rules=()):
    """Measure, paginate, and append one (possibly multi-page) sheet. The column
    header repeats on every page; continued pages are labelled 'k/total'."""
    m = _measure_table(disp, money=money, pct=pct, sign=sign, money_dp=money_dp)
    row_pages = _paginate(rt)
    n = len(row_pages)
    for k, rows in enumerate(row_pages):
        label = section if n == 1 else f"{section} — {k + 1}/{n}"
        contents.append((label, _render_chunk(m, rt, rows, row_bg=row_bg,
                                              cell_rules=cell_rules)))


# --------------------------------------------------------------------------- #
# MW Data grid → image (3 stacked blocks, FY groups side by side)
# --------------------------------------------------------------------------- #
def _mw_image(mw, *, blocks=None, font_px=28, header_px=25, gap=None,
              block_gap=None):
    """Render MW Data as one image. `blocks` selects which rows of the grid's
    own layout to draw (default: all), so it can be split across pages — recent
    years get a page to themselves rather than being squeezed in with a decade
    of history."""
    gap = _px(30) if gap is None else gap
    block_gap = _px(34) if block_gap is None else block_gap
    reg, bold = _ft(font_px)
    hreg, hbold = _ft(header_px)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def fmt(v, typ):
        if v is None or v == "":
            return ""
        if typ == "t":
            return str(v)
        return _fmt_in(v, 0) if typ == "m" else f"{float(v):,.2f}%"

    def cols_for(fy):
        return _MW_REG if mw[fy]["type"] == "region" else _MW_STD

    asc, desc = reg.getmetrics()
    row_h = asc + desc + 2 * PAD_Y
    hasc, hdesc = hbold.getmetrics()
    hline_h = hasc + hdesc + _px(2)

    def render_block(fys):
        # per-FY column widths + wrapped subheaders
        specs = []
        for fy in fys:
            hdr, keys = cols_for(fy)
            months = mw[fy]["months"]
            grand = mw[fy]["grand"]
            gvals = ([("GRAND TOTAL", "t"), (grand["total"], "m"), (grand["ene"], "m"),
                      (grand["south"], "m"), ("", "p"), ("", "p"), ("", "p"),
                      (grand["ene_contrib"], "p"), (grand["south_contrib"], "p")]
                     if mw[fy]["type"] == "region" else
                     [("GRAND TOTAL", "t"), (grand["total"], "m"),
                      (grand["prpl"], "m"), (grand["mripl"], "m"), ("", "p")])
            body = [[fmt(m.get(k, ""), typ) for k, typ in keys] for m in months]
            grow = [fmt(v, typ) for v, typ in gvals]
            # ── H1 / H2, straight under GRAND TOTAL in the same table ────────
            # Manav, 27 Aug: the business leans into Q3-Q4, so the halves belong
            # on this sheet. Each FY block carries its OWN halves; nothing is
            # compared across years. A half still filling says so in its label —
            # a bare "H1" beside last year's finished H1 invites a comparison
            # that is not there.
            hrows = []
            for lo, hi, nm in ((0, 6, "H1  Apr-Sep"), (6, 12, "H2  Oct-Mar")):
                seg = months[lo:hi]
                tot = sum(x.get("total") or 0 for x in seg)
                live = sum(1 for x in seg if (x.get("total") or 0) > 0)
                lbl = nm if live in (0, hi - lo) else f"{nm}  ({live}/{hi - lo} mth)"
                pc = lambda a, b: (a / b * 100) if b else 0.0
                if mw[fy]["type"] == "region":
                    ene = sum(x.get("ene") or 0 for x in seg)
                    sth = sum(x.get("south") or 0 for x in seg)
                    hv = [(lbl, "t"), (tot, "m"), (ene, "m"), (sth, "m"),
                          (pc(tot, grand["total"]), "p"),
                          (pc(ene, grand["ene"]), "p"), (pc(sth, grand["south"]), "p"),
                          (pc(ene, tot), "p"), (pc(sth, tot), "p")]
                else:
                    hv = [(lbl, "t"), (tot, "m"),
                          (sum(x.get("prpl") or 0 for x in seg), "m"),
                          (sum(x.get("mripl") or 0 for x in seg), "m"),
                          (pc(tot, grand["total"]), "p")]
                hrows.append([fmt(v, typ) for v, typ in hv])
            # ── the VFL halves, under this block's own halves ───────────────
            # ★ ON EVERY YEAR WE HAVE A FIGURE FOR, not only the current one
            # (Manav, 29 Aug). A block whose year predates both the feed and
            # the history tab simply has no VFL rows — an unanswered year must
            # look unanswered, not look like nil.
            #
            # The row takes the SHAPE OF THE BLOCK IT SITS IN. On the current
            # year that is the nine region columns; on an older block it is the
            # five standard ones, where PRPL and MRIPL read "—" because VFL is
            # not divided that way in either source. Inventing a split to fill
            # a cell would be worse than an em dash.
            prior = mw[fy].get("vfl")
            prows = []
            if prior:
                pg = prior["grand"]
                pc = lambda a, b: (a / b * 100) if b else 0.0
                for lo, hi, nm in ((0, 6, "H1  Apr-Sep"), (6, 12, "H2  Oct-Mar")):
                    seg = prior["months"][lo:hi]
                    tot = sum(x["total"] for x in seg)
                    if mw[fy]["type"] == "region":
                        ene = sum(x["ene"] for x in seg)
                        sth = sum(x["south"] for x in seg)
                        pv = [(f"{nm}  {prior['label']}", "t"), (tot, "m"), (ene, "m"),
                              (sth, "m"), (pc(tot, pg["total"]), "p"),
                              (pc(ene, pg["ene"]), "p"), (pc(sth, pg["south"]), "p"),
                              (pc(ene, tot), "p"), (pc(sth, tot), "p")]
                    else:
                        pv = [(f"{nm}  {prior['label']}", "t"), (tot, "m"),
                              ("—", "t"), ("—", "t"), (pc(tot, pg["total"]), "p")]
                    prows.append([fmt(v, typ) for v, typ in pv])
            cw, hlines = [], []
            for jc, (h, (k, typ)) in enumerate(zip(hdr, keys)):
                data_w = max([scratch.textlength(r[jc], font=reg) for r in body]
                             + [scratch.textlength(grow[jc], font=bold)]
                             + [scratch.textlength(h[jc], font=bold) for h in hrows]
                             + [scratch.textlength(h[jc], font=bold) for h in prows],
                             default=0)
                # This grid is its own renderer with its own type scale, so it
                # keeps the module-level cap.
                target = min(max(data_w, _px(30)), COL_CAP)
                lines = []
                for seg in str(h).split("\n"):
                    lines += _wrap(scratch, seg, hbold, target)
                hw = max(scratch.textlength(ln, font=hbold) for ln in lines)
                cw.append(int(max(target, hw)) + 2 * PAD_X)
                hlines.append(lines)
            specs.append(dict(fy=fy, keys=keys, body=body, grow=grow, hrows=hrows,
                              prows=prows, cw=cw, hlines=hlines,
                              is_region=mw[fy]["type"] == "region"))

        title_h = hline_h + 2 * PAD_Y
        sub_h = max(max(len(l) for l in s["hlines"]) for s in specs) * hline_h + 2 * PAD_Y
        block_w = sum(sum(s["cw"]) for s in specs) + gap * (len(specs) - 1)
        nx = max(len(s['hrows']) + len(s['prows']) for s in specs)
        block_h = title_h + sub_h + (12 + 1 + nx) * row_h
        img = Image.new("RGB", (block_w, block_h), WHITE)
        d = ImageDraw.Draw(img)

        x0 = 0
        for s in specs:
            gw = sum(s["cw"])
            # title band (pale blue, dark bold — matches the workbook)
            d.rectangle([x0, 0, x0 + gw, title_h], fill=HDR_BG)
            title = f"MONTHLY CONT SHEET FY {s['fy']}"
            tw = scratch.textlength(title, font=hbold)
            d.text((x0 + (gw - tw) / 2, (title_h - hline_h) / 2 + _px(1)), title,
                   font=hbold, fill=INK)
            # subheader
            d.rectangle([x0, title_h, x0 + gw, title_h + sub_h], fill=HDR_BG)
            x = x0
            for jc, lines in enumerate(s["hlines"]):
                ty = title_h + sub_h - PAD_Y - len(lines) * hline_h + _px(2)
                for ln in lines:
                    lw = scratch.textlength(ln, font=hbold)
                    d.text((x + (s["cw"][jc] - lw) / 2, ty), ln, font=hbold, fill=INK)
                    ty += hline_h
                x += s["cw"][jc]
            # body rows + grand
            y = title_h + sub_h
            allx = s["hrows"] + s["prows"]
            for ri in range(13 + len(allx)):
                is_grand = ri == 12
                is_half = ri > 12
                # this year's halves in the header blue; last year's plain, so
                # the eye separates the two without a second colour
                is_prior = is_half and (ri - 13) >= len(s["hrows"])
                cells = (allx[ri - 13] if is_half
                         else s["grow"] if is_grand else s["body"][ri])
                bg = TOTAL_BG if is_grand else (
                    _BODY_BG if (is_prior or not is_half) else HDR_BG)
                d.rectangle([x0, y, x0 + gw, y + row_h], fill=bg)
                x = x0
                for jc, (k, typ) in enumerate(s["keys"]):
                    val = cells[jc]
                    f = bold if (is_grand or is_half) else reg
                    if typ == "t":
                        d.text((x + PAD_X, y + PAD_Y), val, font=f, fill=INK)
                    else:
                        tw = scratch.textlength(val, font=f)
                        d.text((x + s["cw"][jc] - PAD_X - tw, y + PAD_Y), val,
                               font=f, fill=INK)
                    x += s["cw"][jc]
                y += row_h
            # full grid on the block
            gy0 = title_h
            for ri in range(14 + len(allx)):
                gy = gy0 + sub_h + (ri - 1) * row_h if ri else gy0
                d.line([x0, gy, x0 + gw, gy], fill=GRID, width=1)
            gx = x0
            for jc in range(len(s["cw"])):
                gx += s["cw"][jc]
                d.line([gx, 0, gx, block_h], fill=GRID, width=1)
            d.rectangle([x0, 0, x0 + gw - 1, block_h - 1], outline=GRID, width=1)
            x0 += gw + gap
        return img

    rows = mw_layout(mw) if blocks is None else blocks
    imgs = [render_block(b) for b in rows]
    W = max(b.width for b in imgs)
    H = sum(b.height for b in imgs) + block_gap * (len(imgs) - 1)
    img = Image.new("RGB", (W, H), WHITE)
    y = 0
    for b in imgs:
        img.paste(b, (0, y))
        y += b.height + block_gap
    return img


# --------------------------------------------------------------------------- #
# Page composition — constant frame, uniform width
# --------------------------------------------------------------------------- #
def _compose(content, section, asof_label, page_no, total, page_w,
             footer_right="Peanuts Retail · Portfolio", page_h=None):
    """Place `content` onto a page of width `page_w`: constant maroon frame at a
    fixed inset, a section-header band, the content centred, and a footer.

    `page_h` forces a uniform page height across the document (short sheets are
    padded, so the PDF doesn't jump between page sizes as you scroll)."""
    reg, bold = _ft(21)
    tbig, _ = _ft(30)
    sml, smlb = _ft(18)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    natural_h = (MARGIN + FRAME + HEADER_H + content.height + PAD
                 + FOOTER_H + FRAME + MARGIN)
    page_h = natural_h if page_h is None else max(page_h, natural_h)
    img = Image.new("RGB", (page_w, page_h), WHITE)
    d = ImageDraw.Draw(img)

    x0, y0 = MARGIN, MARGIN
    x1, y1 = page_w - 1 - MARGIN, page_h - 1 - MARGIN
    for k in range(FRAME):
        d.rectangle([x0 + k, y0 + k, x1 - k, y1 - k], outline=MAROON)

    ix = x0 + FRAME + PAD                       # inner content-left
    iw = (x1 - x0) - 2 * (FRAME + PAD)           # inner content width

    # header band: maroon accent + section title (left) + as-of (right)
    hb_top = y0 + FRAME
    d.rectangle([x0 + FRAME, hb_top, x1 - FRAME, hb_top + _px(5)], fill=MAROON)
    ty = hb_top + _px(5) + _px(16)
    d.text((ix, ty), section, font=tbig, fill=MAROON)
    if asof_label:
        aw = scratch.textlength(asof_label, font=reg)
        d.text((x1 - FRAME - PAD - aw, ty + _px(8)), asof_label, font=reg, fill=MUTED)
    d.line([ix, hb_top + HEADER_H - _px(8), x1 - FRAME - PAD, hb_top + HEADER_H - _px(8)],
           fill=LINE, width=1)

    # content, centred within the inner width
    cx = ix + max(0, (iw - content.width) // 2)
    cy = hb_top + HEADER_H
    img.paste(content, (cx, cy))

    # footer
    fy = y1 - FRAME - FOOTER_H
    d.line([ix, fy + _px(8), x1 - FRAME - PAD, fy + _px(8)], fill=LINE, width=1)
    d.text((ix, fy + _px(18)), f"Page {page_no} of {total}", font=sml, fill=MUTED)
    right = footer_right
    rw = scratch.textlength(right, font=smlb)
    d.text((x1 - FRAME - PAD - rw, fy + _px(18)), right, font=smlb, fill=MAROON)
    return img


def _fit_mw(mw, blocks, max_w, max_h,
            sizes=(44, 42, 40, 38, 36, 34, 32, 30, 28, 26, 24, 22, 20, 19)):
    """Render an MW grid at the largest size that still fits the page box.

    MW is far less dense than the report tables, so a fixed size wasted most of
    the page. Fitting it to the box means the grid is always as legible as the
    space allows, and it can't silently overflow if a year is added.
    """
    img = None
    for f in sizes:
        img = _mw_image(mw, blocks=blocks, font_px=f, header_px=int(round(f * 0.9)))
        if img.width <= max_w and img.height <= max_h:
            return img
    return img


def save_pages(pages) -> bytes:
    """Save composed pages as one PDF at an A4-landscape page width.

    Pages are written at their native pixel size — no resampling — so glyphs
    keep the hinting FreeType gave them and hairline gridlines stay one crisp
    pixel. The declared page width is fixed, so extra pixels raise the DPI
    rather than growing the paper. Shared by both report builders, so the
    Portfolio and VFL packs come out at identical physical dimensions.
    """
    if pages[0].width > MAX_PX_W:        # safety net; normal pages never hit it
        k = MAX_PX_W / pages[0].width
        pages = [p.resize((max(1, round(p.width * k)), max(1, round(p.height * k))),
                          Image.LANCZOS) for p in pages]
    resolution = pages[0].width * 72.0 / PAGE_PT_W
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:],
                  resolution=resolution)
    return buf.getvalue()


def _cover(page_w, asof, basis_label, scope_rows,
           title="Peanuts Retail — Portfolio Report",
           subtitle="Whole portfolio · Growth / Degrowth pack",
           page_h=None):
    reg, bold = _ft(26)
    big, _ = _ft(58)
    mid, _ = _ft(30)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_h = reg.getmetrics()[0] + reg.getmetrics()[1] + _px(22)
    # A proper page, not a wide banner: give it real height and centre the block.
    page_h = page_h or max(_px(880), MARGIN * 2 + _px(620))
    img = Image.new("RGB", (page_w, page_h), WHITE)
    d = ImageDraw.Draw(img)
    x0, y0 = MARGIN, MARGIN
    x1, y1 = page_w - 1 - MARGIN, page_h - 1 - MARGIN
    for k in range(FRAME):
        d.rectangle([x0 + k, y0 + k, x1 - k, y1 - k], outline=MAROON)
    d.rectangle([x0 + FRAME, y0 + FRAME, x1 - FRAME, y0 + FRAME + _px(12)], fill=MAROON)

    block_h = _px(78) + _px(52) + _px(26) + len(scope_rows) * line_h
    ix = x0 + FRAME + PAD + _px(30)
    y = y0 + FRAME + max(_px(70), (page_h - 2 * (MARGIN + FRAME) - block_h) // 2)
    d.text((ix, y), title, font=big, fill=MAROON); y += _px(84)
    d.text((ix, y), subtitle, font=mid, fill=DARK); y += _px(54)
    d.line([ix, y, x1 - FRAME - PAD - _px(30), y], fill=LINE, width=1); y += _px(28)
    lw = max((scratch.textlength(l, font=bold) for l, _ in scope_rows), default=0)
    for label, value in scope_rows:
        d.text((ix, y), label, font=bold, fill=MAROON)
        d.text((ix + lw + _px(44), y), str(value), font=reg, fill=DARK)
        y += line_h
    return img


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #
_MONEY = ["Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY",
          "Sum of DAY SALE FIGURE", "Sum of MONTH SALE LY", "Sum of PROJECTED MTD",
          "Sum of LY FULL SALES", "Sum of PROJECTED YTD", "Sum of TTM SALES"]
_PCT = ["Sum of GD_YTD_%", "Sum of GD_MTD_%"]
_AVG_MONEY = ["SBA", "CA", "Sum of YTD_LY", "Sum of YTD_TY", "Average of OPERATION",
              "Sum of AVG DAY SALE", "Sum of AVG MONTH SALE", "Sum of PSFPD",
              "Sum of TTM SALES"]


def _prep_gd(df, money=_MONEY):
    disp = df.copy()
    for c in _PCT:
        if c in disp.columns:
            disp[c] = _to_num(disp[c]) * 100
    return disp, [c for c in money if c in disp.columns], \
        [c for c in _PCT if c in disp.columns]


def _to_num(s):
    import pandas as pd
    return pd.to_numeric(s, errors="coerce")


def build(pf, pf_all, asof, basis_label="", vfl_df=None):
    """Compile the five portfolio sheets into one PDF (bytes), in dashboard
    order: MW Data, GD Sheet, Brand-wise GD, Loc-wise GD, Average.
    `pf` = filtered portfolio frame; `pf_all` = unfiltered (MW Data ignores
    filters, like the tab). `vfl_df` supplies last year for any region the
    portfolio feed does not cover — South, whose history predates the takeover."""
    import pandas as pd
    asof = pd.Timestamp(asof)
    asof_label = f"As of {asof:%d %b %Y}" + (f" · {basis_label}" if basis_label else "")

    with _LOCK:
        contents = []   # (section, content_image)
        # MW Data is built last (it is sized to the page box the report tables
        # establish) and inserted at the front, keeping the dashboard order.

        # 2) GD Sheet
        rep, rt = gd_sheet_report(pf, asof=asof)
        disp, money, pct = _prep_gd(rep)
        _add_sheet(contents, "GD Sheet — Growth / Degrowth", disp, rt,
                   money=money, pct=pct, sign=pct, money_dp=0,
                   cell_rules=PORTFOLIO_CELL_RULES)

        # 3) Brand-wise GD
        rep, rt = brand_wise_gd_report(pf, asof=asof)
        disp, money, pct = _prep_gd(rep)
        _add_sheet(contents, "Brand-wise Growth / Degrowth", disp, rt,
                   money=money, pct=pct, sign=pct, money_dp=0,
                   cell_rules=PORTFOLIO_CELL_RULES)

        # 4) Loc-wise GD
        rep, rt = loc_wise_gd_report(pf, asof=asof)
        disp, money, pct = _prep_gd(rep)
        _add_sheet(contents, "Location-wise Growth / Degrowth", disp, rt,
                   money=money, pct=pct, sign=pct, money_dp=0,
                   cell_rules=PORTFOLIO_CELL_RULES)

        # 5) Average (store productivity)
        rep, rt = average_report(pf, asof=asof)
        disp = rep.copy()
        if "Sum of GD_YTD_%" in disp.columns:
            disp["Sum of GD_YTD_%"] = _to_num(disp["Sum of GD_YTD_%"]) * 100
        for c in _AVG_MONEY:
            if c in disp.columns:
                disp[c] = _to_num(disp[c])
        _add_sheet(contents, "Average — Store Productivity", disp, rt,
                   money=[c for c in _AVG_MONEY if c in disp.columns],
                   pct=["Sum of GD_YTD_%"], sign=["Sum of GD_YTD_%"], money_dp=2)

        # MW Data (whole portfolio, unfiltered), across two pages. Page one puts
        # the CURRENT year on its own row with the two prior years beneath it —
        # the current year is what gets read, and giving it a full row lets the
        # whole grid render far larger. Older years follow on a history page.
        tbl_w = max(c.width for _, c in contents)
        tbl_h = max(c.height for _, c in contents)
        _mw = mw_data(pf_all, asof, vfl_df=vfl_df)
        _layout = mw_layout(_mw)
        # ★ PAGE ONE IS LAST YEAR AND THIS YEAR, NOTHING ELSE (Manav, 28 Aug).
        # The current block now carries four half-year rows and the VFL slice
        # beneath it; sharing the page with 2024-25 squeezed all three. Every
        # earlier year moves to the history page, which takes them three to a
        # row.
        _recent, _rest = _layout[0], _layout[1:]
        _cur = [_recent[-1]]
        _prior = [_recent[-2]] if len(_recent) > 1 else []
        _spill = _recent[:-2]                       # 2024-25 and anything older
        _flat = _spill + [fy for row in _rest for fy in row]
        # ★ FOUR TO A ROW on the history page — two rows instead of three, so
        # each block gets more of the page and the type comes up with it.
        _older = [_flat[i:i + 4] for i in range(0, len(_flat), 4)]
        # ★ SIDE BY SIDE on page one. Stacked, two blocks used half the width
        # and were sized down to fit the height they did not need. One row of
        # two spends the page on legibility instead. Last year on the left, so
        # it reads left to right in time.
        _first = [_prior + _cur] if _prior else [_cur]
        mw_pages = [(f"MW Data — Monthly Contribution · "
                     f"{(_prior or _cur)[0]} – {_cur[-1]}",
                     _fit_mw(_mw, _first, tbl_w, tbl_h))]
        if _flat:
            mw_pages.append((f"MW Data — Monthly Contribution · earlier years "
                             f"({_flat[-1]} – {_flat[0]})",
                             _fit_mw(_mw, _older, tbl_w, tbl_h)))
        contents = mw_pages + contents

        # 1) Executive Snapshot — replaces the cover. Built last because it is
        # sized to the box the tables establish, then put at the front so it is
        # the first thing opened.
        #
        # One page for the whole estate, then one per region. Each is computed on
        # its OWN scope rather than sliced from a national figure, so a region's
        # like to like set, trajectory and concentration are its own.
        import exec_snapshot as ES
        snaps = [(None, "Executive Snapshot")]
        for r in ES.regions_of(pf_all):
            snaps.append((r, f"Executive Snapshot · {r}"))
        snap_pages = []
        for r, sec in snaps:
            src = pf_all
            # A region the portfolio feed has no last year for (South, taken over
            # 19 Apr 2026) is built from the VFL feed instead, which keeps the
            # previous operator's history. Without it that page has no
            # trajectory, no movers and no growth at all.
            if r and vfl_df is not None and not ES.has_prior_year(pf_all, asof, r):
                src = ES.portfolio_frame_from_vfl(vfl_df, region=r)
            snap_pages.append((sec, ES.content(
                ES.portfolio_metrics(src, asof, basis_label, region=r),
                tbl_w, tbl_h)))
        contents = snap_pages + contents

        # uniform page width = widest content + frame + margins; uniform height
        # = tallest page, so the document doesn't change size as you scroll.
        page_w = max(c.width for _, c in contents) + 2 * (MARGIN + FRAME + PAD)
        page_h = max(c.height for _, c in contents) + (
            MARGIN + FRAME + HEADER_H + PAD + FOOTER_H + FRAME + MARGIN)
        pages = []
        total = len(contents)
        for i, (section, content) in enumerate(contents, start=1):
            pages.append(_compose(content, section, asof_label, i, total, page_w,
                                  page_h=page_h))

        return save_pages(pages)
