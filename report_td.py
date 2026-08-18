"""
REPORT TD — a separate reporting vertical.

Reproduces Manav's operational workbooks (the "L TO L" sheets, month-wise
totals, night SMS formats) as proper reports. Separate from the Portfolio and
VFL packs: its own module, its own tab, its own content. Nothing in those packs
imports from here, so a change on one side cannot move the other.

★ WHAT "MATCH THE EXCEL" MEANS HERE

The STRUCTURE is the Excel's, exactly: the same eleven columns in the same
order, the same footer block with the same merged spans and labels, the same
day-by-day rows.

The PRESENTATION is the house design system, because the Excel's own formatting
does not survive print. Its raw appearance — a pure #FFFF00 fill behind every
heading, every figure in red, a hard black grid, no margins — is a spreadsheet
on screen, not a page. Rendered literally it came out as a bitmap jammed against
the paper edge with nothing to say what it was.

So it follows the same rules as every other report we ship:

  * `HDR_BG` #DAEEF3 headers, `TOTAL_BG` #FFFF00 for total rows only, `GRID`
    #636363 hairlines, white body;
  * **red is TEXT and only marks a decline** — an index under 100 — never a fill.
    A page where every number is red says nothing about any of them;
  * Indian digit grouping, as the packs use. The source sheet prints 47353086
    with no separators, which is unreadable at a glance;
  * a real page: constant frame, section band naming the month, as-of stamp,
    footer and page numbers, uniform page size, A4 landscape;
  * rasterised once at final size and never resampled.

Page furniture comes from `portfolio_pdf._compose` — shared deliberately, so a
Report TD page and a pack page are recognisably the same document family. Only
the table inside it is this module's own.

★ WHERE THE FIGURES DIVERGE FROM THE WORKBOOK, DELIBERATELY

  * the South August tab divides its monthly average by 30 on a 31-day month,
    and the label above still reads "AVG. JUL 2025" — a July leftover;
  * its last two cumulative rows are off by one (`I31 = I30 + C32`), so the
    30-August figure already contains the 31st and the final cell adds the whole
    month a second time (92,349,676 against a true 47,353,086).

Both are computed correctly here, so those cells will disagree with the old
sheet. That is the point, but it looks like an error until you know.
"""

from __future__ import annotations

import calendar
import io
import math
import zipfile

import pandas as pd
from PIL import Image, ImageDraw

from imaging import _LOCK
import portfolio_pdf as PP
from portfolio_pdf import (_ft, _px, _fmt_in, _compose, save_pages, PAGE_PT_W,
                           HDR_BG, TOTAL_BG, NEG_INK, GRID, GREEN, INK, WHITE)

FOOTER_RIGHT = "Peanuts Retail · Report TD"

# Column widths in the source workbook's own units, so the proportions are its
# proportions; only the scale is ours.
SOUTH_COLS = [
    ("DATE", 11.3, "c"), ("DAY", 8.9, "c"),
    ("GRAND TOTAL SALE PRPL {LY}", 14.4, "r"),
    ("GRAND TOTAL SALE PRPL CUMULATIVE {LY}", 15.3, "r"),
    ("PRPL STORE TOTAL SALE {LY}", 14.4, "r"),
    ("DATE", 11.3, "c"), ("DAY", 8.9, "c"),
    ("PRPL STORE TOTAL SALE {TY}", 14.3, "r"),
    ("PRPL TOTAL {MON} {Y1}", 12.3, "r"),
    ("PRPL TOTAL {MON} {Y2}", 12.0, "r"),
    ("GROTH / D GROTH", 12.3, "r"),
]

# ★ HOW MANY PIXELS THIS VERTICAL DRAWS WITH (14 Aug).
# `save_pages` writes a page at its NATIVE pixel size and derives the DPI from
# the pixel width — more pixels on the same 842pt paper means a higher DPI, not
# a bigger sheet. The pack's sheets come out ~3,800px wide and print at 327 ppi;
# Report TD's narrower tables were landing at 2,532px and 217 ppi, two thirds of
# the resolution, which is why its type looked soft beside a GD sheet.
# Everything below is multiplied by this, so the layout is untouched and only
# the pixel density changes.
SCALE = 1.5

PX_PER_UNIT = int(22 * SCALE)   # workbook width unit -> px
FONT_PX, HDR_FONT_PX = int(30 * SCALE), int(25 * SCALE)
ROW_H = _px(int(46 * SCALE))
HDR_H = _px(int(126 * SCALE))
PAD_X = _px(int(12 * SCALE))

# Footer rows: (height, wraps?). The last three carry labels that wrap onto two
# lines; at 30px type two lines need ~80px, so they are given 92 rather than the
# workbook's own heights — 70 clipped "AVG. PER DAY PER STORE AUG 2026-27" in
# half, and a label cut off mid-phrase is worse than a slightly taller row.
FOOT_LABEL_H = _px(int(96 * SCALE))   # the wrapping label rows; two lines of 30px type
# Merged spans are now carried on the cells themselves (see render_south).


# ★ TWO TYPE SIZES, BECAUSE THESE REPORTS ARE READ IN TWO PLACES (Manav,
# 14 Aug). The night SMS goes to a WhatsApp group and is read on a phone, where
# the pack's 7pt would be unreadable. The L-to-L and month-wise sheets are desk
# reports, read beside a GD sheet, and at 10pt they looked enlarged next to one.
# Only the TYPE changes; the rows, padding and grid keep their scale, so a desk
# sheet gets the pack's density without losing the pixels that make it sharp.
import contextlib


@contextlib.contextmanager
def _type(font_px, hdr_px):
    global FONT_PX, HDR_FONT_PX
    was = FONT_PX, HDR_FONT_PX
    FONT_PX, HDR_FONT_PX = font_px, hdr_px
    try:
        yield
    finally:
        FONT_PX, HDR_FONT_PX = was


DESK_FONT, DESK_HDR = 31, 27       # tuned to land on the pack's ~7pt — see below
# ★ A FLOOR ON THE TABLE'S WIDTH, for the same reason the night SMS needed one.
# The grid widens a table until it is landscape-shaped, and that widening is a
# function of HEIGHT — so a SHORT sheet never widens at all. Month-wise is 17
# rows, so it came out 2,163px and printed at 12pt and 185 ppi while the L-to-L
# beside it printed at 7pt. A floor gives every desk sheet the pack's width
# whatever its height, which fixes the type size and the resolution together.
MIN_TABLE_W = 0                    # only the desk reports set one
DESK_MIN_W = 3800


# The rows come down with the type. Left at the phone size they were a quarter
# taller than the pack's for type the same size, which reads as airy rather than
# dense — the other half of what made a Report TD page look unlike a GD sheet.
DESK_ROW_F = 0.78


@contextlib.contextmanager
def desk():
    """The density of a pack sheet, for the reports read at a desk."""
    global MIN_TABLE_W, ROW_H, HDR_H, FOOT_LABEL_H
    was = MIN_TABLE_W, ROW_H, HDR_H, FOOT_LABEL_H
    MIN_TABLE_W = _px(DESK_MIN_W)
    ROW_H = int(ROW_H * DESK_ROW_F)
    HDR_H = int(HDR_H * DESK_ROW_F)
    FOOT_LABEL_H = int(FOOT_LABEL_H * DESK_ROW_F)
    try:
        with _type(DESK_FONT, DESK_HDR):
            yield
    finally:
        MIN_TABLE_W, ROW_H, HDR_H, FOOT_LABEL_H = was


def _money(v) -> str:
    return "" if v is None or pd.isna(v) else _fmt_in(float(v), dec=0)


# ── Data ────────────────────────────────────────────────────────────────────
def south_months(df, asof, region="South") -> list[dict]:
    """One dict per month of the fiscal year to date, in the sheet's shape.

    `df` is the VFL frame: South's last year is the previous operator's history,
    which only that feed retains — the portfolio feed has no South LY at all.
    """
    import loader as L
    asof = pd.Timestamp(asof)
    master = L.load_store_master()
    reg = dict(zip(master["tableau_name"], master["region"]))
    d = df.copy()
    d["_r"] = d[L.COL_STORE_LABEL].map(reg)
    d = d[d["_r"] == region]
    daily = d.groupby("date")[L.COL_AMOUNT].sum()
    fy = asof.year if asof.month >= 4 else asof.year - 1
    n_stores = int(d[d["date"] >= pd.Timestamp(fy, 4, 1)][L.COL_STORE_LABEL].nunique())

    # ★ TAKEOVER-ANCHORED, like every other report here. South was taken over on
    # 19 April, so its April is the 19th to the 30th — in BOTH years, so the two
    # sides compare like with like — and every per-day figure divides by those 12
    # days, not by 30. The workbook does the same: its April tab carries 12 rows
    # and divides by 12. Running April from the 1st pulled in the previous
    # operator's first eighteen days and tripled the month.
    tk = pd.to_datetime(
        L.load_store_master().set_index("region")
        .loc[region, "takeover_date"]).min() if region else None

    out, m = [], pd.Timestamp(fy, 4, 1)
    while m <= asof:
        month_end = m + pd.offsets.MonthEnd(0)
        if tk is not None and tk > month_end:
            m += pd.DateOffset(months=1)
            continue                       # wholly before the takeover
        start_day = tk.day if (tk is not None and tk.year == m.year
                               and tk.month == m.month) else 1
        out.append(_one_month(daily, m, asof, n_stores, start_day))
        m += pd.DateOffset(months=1)
    return out


def _one_month(daily, month_start, asof, n_stores, start_day=1) -> dict:
    ty_year, mth = month_start.year, month_start.month
    last_day = calendar.monthrange(ty_year, mth)[1]
    ndays = last_day - start_day + 1        # the window, not the calendar month
    rows, ly_cum, ty_cum, elapsed, ly_at_elapsed = [], 0.0, 0.0, 0, 0.0
    for i in range(start_day, last_day + 1):
        ly_d = pd.Timestamp(ty_year - 1, mth, i)
        ty_d = pd.Timestamp(ty_year, mth, i)
        ly_v = float(daily.get(ly_d, 0.0))
        ty_v = float(daily.get(ty_d, 0.0)) if ty_d <= asof else None
        ly_cum += ly_v
        if ty_v is not None:
            ty_cum += ty_v
            # Days INTO the window, not the day of the month — April starts on
            # the 19th, so its 12th filled day is the 30th.
            elapsed, ly_at_elapsed = i - start_day + 1, ly_cum
        rows.append({"DATE_LY": ly_d, "DAY_LY": ly_d.strftime("%a").upper(),
                     "C": ly_v, "D": ly_cum, "E": ly_v,
                     "DATE_TY": ty_d, "DAY_TY": ty_d.strftime("%a").upper(),
                     "H": ty_v, "I": ly_cum, "J": ty_cum,
                     "K": (ty_cum * 100 / ly_cum) if ly_cum else None})

    elapsed = max(elapsed, 1)
    ty_avg = ty_cum / elapsed
    growth10 = ly_cum * 0.10
    return {
        "month": month_start.strftime("%b").upper(), "ty_year": ty_year,
        "ndays": ndays, "elapsed": elapsed, "rows": rows, "n_stores": n_stores,
        "foot": {
            "ly_total": ly_cum, "ty_total": ty_cum,
            "ly_avg_per_day": ly_cum / ndays, "ty_avg_per_day": ty_avg,
            "trending": ty_avg * ndays, "days_remaining": max(ndays - elapsed, 0),
            "ly_avg_per_store": (ly_at_elapsed / elapsed / n_stores) if n_stores else 0,
            "ly_day_avg_till_yesterday": ly_at_elapsed / elapsed,
            "ty_avg_per_store": (ty_avg / n_stores) if n_stores else 0,
            "projection": ly_cum + growth10, "ly_minus_ty": ly_cum - ty_cum,
            "growth_10": growth10, "target_total": (ly_cum - ty_cum) + growth10,
        },
    }


# ── Measured grid ───────────────────────────────────────────────────────────
# Columns are sized from the strings they will actually contain, measured with
# the font each cell is drawn in. Guessing widths is what made the total rows
# bleed: those figures render BOLD, which is wider than the regular text the
# columns had been eyeballed against, so "1,78,38,533" ran into the cell beside
# it. Widths round UP with a pixel of slack, and any cell that still cannot fit
# is clipped with an ellipsis rather than allowed to overprint its neighbour.

def cell(text="", *, align="c", fill=None, ink=INK, bold=False, span=1, wrap=False):
    return {"text": "" if text is None else str(text), "align": align,
            "fill": fill, "ink": ink, "bold": bold, "span": span, "wrap": wrap}


def _tw(d, s, font) -> float:
    return d.textlength(str(s), font=font)


def _fit(d, text, font, avail):
    """`text`, shortened with an ellipsis if it cannot fit `avail` px."""
    if _tw(d, text, font) <= avail:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if _tw(d, text[:mid] + ell, font) <= avail:
            lo = mid + 1
        else:
            hi = mid
    return (text[:max(lo - 1, 0)] + ell) if lo > 1 else ell


def _wrap_lines(d, text, font, avail):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if _tw(d, t, font) <= avail or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def measure_for(header, rows, ncols, cap=None):
    """Column widths for a set of rows, so several grids can share them."""
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    reg, _ = _ft(FONT_PX)
    _, bold = _ft(FONT_PX)
    _, hbold = _ft(HDR_FONT_PX)
    w = _measure(scratch, header, rows, reg, bold, hbold, ncols)
    if cap:
        w = [min(x, c) if c else x for x, c in zip(w, cap)]
    return w


def _measure(d, header, rows, reg, bold, hbold, ncols):
    w = [0.0] * ncols
    for i, h in enumerate(header or []):
        # A header wraps, so it only has to be as wide as its longest WORD.
        for word in (str(h).split() or [""]):
            w[i] = max(w[i], _tw(d, word, hbold))
    spanning = []
    for cells in rows:
        i = 0
        for c in cells:
            f = bold if c["bold"] else reg
            if c["span"] == 1:
                if not c["wrap"]:
                    w[i] = max(w[i], _tw(d, c["text"], f))
                else:
                    for word in (c["text"].split() or [""]):
                        w[i] = max(w[i], _tw(d, word, f))
            else:
                spanning.append((i, c, f))
            i += c["span"]
    w = [math.ceil(x) + 2 * PAD_X + 1 for x in w]
    # A merged label must still fit across the columns it spans.
    for i, c, f in spanning:
        if c["wrap"]:
            continue
        need = math.ceil(_tw(d, c["text"], f)) + 2 * PAD_X + 1
        have = sum(w[i:i + c["span"]])
        if need > have:
            extra = need - have
            per = extra // c["span"]
            for k in range(i, i + c["span"]):
                w[k] += per
            w[i] += extra - per * c["span"]
    return w


def _draw_grid(header, rows, *, title=None, hdr_h=None, landscape=True,
               widths=None):
    """rows: list of (cells, height). Returns a cropped image.

    `widths` pins the column widths instead of measuring them off these rows,
    so two tables of the same shape come out the SAME WIDTH — East & NE ran
    wider than South simply because its store names are longer, and two tables
    on one page that do not line up read as two documents.
    """
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    reg, _ = _ft(FONT_PX)
    _, bold = _ft(FONT_PX)
    _, hbold = _ft(HDR_FONT_PX)
    ncols = sum(c["span"] for c in rows[0][0]) if rows else len(header or [])
    widths = (list(widths) if widths is not None else
              _measure(scratch, header, [r for r, _ in rows], reg, bold, hbold, ncols))
    xs = [0]
    for w in widths:
        xs.append(xs[-1] + w)
    total_w = xs[-1]

    # Heights follow the wrapped text, never a guessed constant. "CARPET AREA
    # SQFT 2025-26" wraps to four lines in a narrow column and spilled out of a
    # fixed header band; a row that cannot hold its own label is the same defect
    # as a cell that cannot hold its number.
    def _needed(text, font, width, wrap):
        if not text or not wrap:
            return 0
        a, dsc = font.getmetrics()
        n = len(_wrap_lines(scratch, text, font, width - 2 * PAD_X))
        return n * (a + dsc) + _px(10)

    hdr_h = hdr_h or HDR_H
    if header:
        hdr_h = max(hdr_h, max(_needed(h, hbold, widths[i], True)
                               for i, h in enumerate(header)))
    sized = []
    for cells, h in rows:
        need, i = h, 0
        for c in cells:
            w = sum(widths[i:i + c["span"]])
            need = max(need, _needed(c["text"],
                                     bold if c["bold"] else reg, w, c["wrap"]))
            i += c["span"]
        sized.append((cells, need))
    rows = sized

    title_h = _px(64) if title else 0
    height = title_h + (hdr_h if header else 0) + sum(h for _, h in rows) + 4

    # Measuring gives each column the MINIMUM width its text needs, which is what
    # stops the bleeding — but on a 31-row daily sheet that leaves a narrow, tall
    # table, and the page came out portrait. The workbook prints A4 landscape and
    # so does every pack we ship, so the surplus is handed back to the columns in
    # proportion: same type size, more room around it.
    if landscape or MIN_TABLE_W:
        want = max(height * (PAGE_PT_W / 595.0) if landscape else 0, MIN_TABLE_W)
        if total_w < want:
            k = want / total_w
            widths = [int(round(w * k)) for w in widths]
            xs = [0]
            for w in widths:
                xs.append(xs[-1] + w)
            total_w = xs[-1]
    img = Image.new("RGB", (total_w, height), WHITE)
    d = ImageDraw.Draw(img)

    y = 0
    if title:
        _paint(d, (0, y, total_w, y + title_h),
               cell(title, align="l", fill=HDR_BG, bold=True), reg, bold, hbold)
        y += title_h
    if header:
        for i, h in enumerate(header):
            _paint(d, (xs[i], y, xs[i + 1], y + hdr_h),
                   cell(h, fill=HDR_BG, bold=True, wrap=True), reg, bold, hbold,
                   header=True)
        y += hdr_h
    for cells, h in rows:
        i = 0
        for c in cells:
            _paint(d, (xs[i], y, xs[i + c["span"]], y + h), c, reg, bold, hbold)
            i += c["span"]
        y += h
    return img.crop((0, 0, total_w, y))


def _paint(d, box, c, reg, bold, hbold, header=False):
    x0, y0, x1, y1 = box
    if c["fill"] is not None:
        d.rectangle([x0, y0, x1, y1], fill=c["fill"])
    d.rectangle([x0, y0, x1, y1], outline=GRID, width=1)
    if not c["text"]:
        return
    font = hbold if header else (bold if c["bold"] else reg)
    avail = (x1 - x0) - 2 * PAD_X
    a, dsc = font.getmetrics()
    lh = a + dsc
    lines = _wrap_lines(d, c["text"], font, avail) if (c["wrap"] or header) \
        else [_fit(d, c["text"], font, avail)]
    ty = y0 + max(1, ((y1 - y0) - lh * len(lines)) // 2)
    for ln in lines:
        tw = _tw(d, ln, font)
        tx = (x0 + PAD_X if c["align"] == "l" else
              x1 - PAD_X - tw if c["align"] == "r" else
              x0 + max(1, ((x1 - x0) - tw) / 2))
        d.text((tx, ty), ln, font=font, fill=c["ink"])
        ty += lh


# ── The month's summary, under both L-to-L sheets ───────────────────────────
# ★ REDONE 14 Aug. This used to be the workbook's own footer reproduced cell for
# cell: labels in one row, their figures in the row above or below, spread over
# the eleven columns the DAY table needs, with blanks between. Every number was
# right and almost none could be read — "AVG. PER DAY PER STORE AUG 2025-26" sat
# beneath a figure belonging to the line before it.
#
# Same figures, none added or dropped. Two things changed: the ones that
# summarise a COLUMN (average per day, the trend) stay in the day grid where
# they line up under the column they describe, and everything else becomes
# label→value pairs, two to a row, under headings that say what the block is
# for — where the month stands, where it lands, what is left to beat last year.
def _foot_grid(sections, total_w, highlight=()):
    """`sections` is [(heading, [(label, value), …]), …]. Values already
    formatted; `highlight` names the labels whose figure gets the total fill."""
    rows = []
    for heading, pairs in sections:
        rows.append(([cell(heading, align="l", fill=HDR_BG, bold=True, span=4)],
                     ROW_H))
        for i in range(0, len(pairs), 2):
            chunk = list(pairs[i:i + 2])
            if len(chunk) == 1:
                chunk.append(("", ""))
            out = []
            for lbl, val in chunk:
                hit = lbl in highlight
                out.append(cell(lbl, align="l", bold=hit))
                out.append(cell(val, align="r", bold=bool(val),
                                fill=TOTAL_BG if hit else None))
            rows.append((out, ROW_H))
    # The labels earn the width; the figures need only enough to sit right.
    w = [int(total_w * x) for x in (0.32, 0.18, 0.32, 0.18)]
    w[-1] += total_w - sum(w)
    return _draw_grid([], rows, widths=w, landscape=False)


# ── South L-to-L ────────────────────────────────────────────────────────────
def render_south(sheet) -> Image.Image:
    mon, y2 = sheet["month"], sheet["ty_year"]
    subs = {"{MON}": mon, "{LY}": f"{y2 - 1}-{str(y2)[2:]}",
            "{TY}": f"{y2}-{str(y2 + 1)[2:]}", "{Y1}": str(y2 - 1), "{Y2}": str(y2)}
    header = []
    for h, _, _ in SOUTH_COLS:
        for k, v in subs.items():
            h = h.replace(k, v)
        header.append(h)
    aligns = [a for _, _, a in SOUTH_COLS]

    rows = []
    for r in sheet["rows"]:
        k = r["K"]
        vals = [r["DATE_LY"].strftime("%d-%m-%Y"), r["DAY_LY"],
                _money(r["C"]), _money(r["D"]), _money(r["E"]),
                r["DATE_TY"].strftime("%d-%m-%Y"), r["DAY_TY"],
                _money(r["H"]), _money(r["I"]), _money(r["J"]),
                "" if k is None else f"{k:,.0f}"]
        cells = [cell(v, align=aligns[i]) for i, v in enumerate(vals)]
        # Red marks a DECLINE against last year, nothing else.
        if k is not None and k < 100:
            cells[10] = cell(vals[10], align="r", ink=NEG_INK)
        rows.append((cells, ROW_H))

    # Column summaries stay in the day grid, under the columns they describe.
    f = sheet["foot"]
    ly_lbl, ty_lbl = f"{y2 - 1}-{str(y2)[2:]}", f"{y2}-{str(y2 + 1)[2:]}"
    blank = lambda: [cell() for _ in range(11)]

    c = blank()
    for i in range(11):
        c[i] = cell(fill=TOTAL_BG)
    c[0] = cell("TOTAL", fill=TOTAL_BG, bold=True)
    c[2] = cell(_money(f["ly_total"]), align="r", fill=TOTAL_BG, bold=True)
    c[4] = cell(_money(f["ly_total"]), align="r", fill=TOTAL_BG, bold=True)
    c[7] = cell(_money(f["ty_total"]), align="r", fill=TOTAL_BG, bold=True)
    rows.append((c, ROW_H))

    c = blank()
    c[0] = cell("AVG. PER DAY", fill=HDR_BG, bold=True, span=2)
    c[2] = cell(_money(f["ly_avg_per_day"]), align="r", bold=True)
    c[7] = cell(_money(f["ty_avg_per_day"]), align="r", bold=True)
    rows.append(([c[0], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10]],
                 ROW_H))

    c = blank()
    c[0] = cell(f"{sheet['ndays']} DAYS TRENDING", fill=HDR_BG, bold=True, span=2)
    c[7] = cell(_money(f["trending"]), align="r", bold=True)
    rows.append(([c[0], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10]],
                 ROW_H))

    day = _draw_grid(header, rows)
    n, el = sheet["n_stores"], sheet["elapsed"]
    sections = [
        ("WHERE THE MONTH STANDS", [
            (f"AVG. PER DAY PER STORE {ly_lbl}", _money(f["ly_avg_per_store"])),
            (f"AVG. PER DAY PER STORE {ty_lbl}", _money(f["ty_avg_per_store"])),
            (f"NO. OF STORES {mon} {y2 - 1}", str(n)),
            (f"NO. OF STORES {mon} {y2}", str(n)),
        ]),
        (f"WHERE {mon} {y2} LANDS", [
            (f"{mon} PROJECTIONS", _money(f["projection"])),
            ("NO. OF DAYS REMAINING", str(f["days_remaining"])),
            (f"{mon} {y2 - 1} DAY AVG. TILL YESTERDAY",
             _money(f["ly_day_avg_till_yesterday"])),
            (f"DAYS COUNTED SO FAR", str(el)),
        ]),
        (f"TO FINISH ABOVE {mon} {y2 - 1}", [
            ("LY-TY TILL DATE ACHVD.", _money(f["ly_minus_ty"])),
            ("10% GROWTH ON LY SALE", _money(f["growth_10"])),
            ("TOTAL", _money(f["target_total"])),
        ]),
    ]
    foot = _foot_grid(sections, day.width, highlight={"TOTAL"})
    return _stack([day, foot], _px(22))


# ── Month-wise total sale ───────────────────────────────────────────────────
def render_monthwise(sheet, title) -> Image.Image:
    fy = sheet["fy"]
    ly_lbl, ty_lbl = f"{fy - 1}-{str(fy)[2:]}", f"{fy}-{str(fy + 1)[2:]}"
    header = [h.replace("{LY}", ly_lbl).replace("{TY}", ty_lbl)
              for h, _, _ in MW_COLS]
    aligns = [a for _, _, a in MW_COLS]

    def diff(a, b):
        if a is None or b is None:
            return "", INK
        v = a - b
        return (_money(v) if abs(v) >= 1 else "0"), (NEG_INK if v < 0 else INK)

    rows = []

    def line(vals, inks=None, fill=None, boldrow=False):
        cs = [cell(v, align=aligns[i], fill=fill, bold=boldrow,
                   ink=(inks or {}).get(i, INK)) for i, v in enumerate(vals)]
        rows.append((cs, ROW_H))

    def emit(r):
        ds, di = diff(r["ty_sale"], r["ly_sale"])
        dn = "" if r["ty_n"] is None else str(r["ty_n"] - r["ly_n"])
        dni = NEG_INK if (r["ty_n"] is not None and r["ty_n"] < r["ly_n"]) else INK
        da, dai = diff(r["ty_avg"], r["ly_avg"])
        line([r["month"], _money(r["ly_sale"]), _money(r["ty_sale"]), ds,
              str(r["ly_n"]), "" if r["ty_n"] is None else str(r["ty_n"]), dn,
              _money(r["ly_avg"]), _money(r["ty_avg"]), da,
              _money(r["ly_carpet"]), _money(r["ty_carpet"])],
             inks={3: di, 6: dni, 9: dai})

    def subtotal(group):
        ls = sum(r["ly_sale"] for r in group)
        ts = sum(r["ty_sale"] or 0 for r in group)
        ds, di = diff(ts, ls)
        line(["", _money(ls), _money(ts), ds, "", "", "", "", "", "", "", ""],
             inks={3: di}, fill=TOTAL_BG, boldrow=True)
        return ls, ts

    done = [r for r in sheet["rows"] if r["done"]]
    rest = [r for r in sheet["rows"] if not r["done"]]
    for r in done:
        emit(r)
    a_ls, a_ts = subtotal(done) if done else (0, 0)
    for r in rest:
        emit(r)
    b_ls, b_ts = subtotal(rest) if rest else (0, 0)

    ly_ca = sum(r["ly_carpet"] or 0 for r in sheet["rows"]) / 12
    ty_ca = sum(r["ty_carpet"] or 0 for r in sheet["rows"]) / 12
    line(["", "", "", "", "", "", "", "", "", "", _money(ly_ca), _money(ty_ca)])

    g_ls, g_ts = a_ls + b_ls, a_ts + b_ts
    ds, di = diff(g_ts, g_ls)
    line(["G. TOTAL", _money(g_ls), _money(g_ts), ds, "", "", "", "", "", "",
          _money(g_ls / ly_ca) if ly_ca else "",
          _money(g_ts / ty_ca) if ty_ca else ""],
         inks={3: di}, fill=TOTAL_BG, boldrow=True)

    rows.append(([cell("THROUGH PUT = sale ÷ average carpet sqft", align="r",
                       span=10),
                  cell("THROUGH PUT", fill=HDR_BG, bold=True, span=2)], ROW_H))
    return _draw_grid(header, rows, title=title)


# ── Build ───────────────────────────────────────────────────────────────────
def _carpet_map():
    import master_lookup
    return master_lookup.carpet()


def _pdf_from(contents, label):
    page_w = max(c.width for _, c in contents) + 2 * (PP.MARGIN + PP.FRAME + PP.PAD)
    page_h = max(c.height for _, c in contents) + (
        PP.MARGIN + PP.FRAME + PP.HEADER_H + PP.PAD + PP.FOOTER_H
        + PP.FRAME + PP.MARGIN)
    pages = [_compose(img, sec, label, i, len(contents), page_w,
                      footer_right=FOOTER_RIGHT, page_h=page_h)
             for i, (sec, img) in enumerate(contents, start=1)]
    return save_pages(pages)


def _label(asof, basis):
    return f"As of {asof:%d %b %Y}" + (f" · {basis}" if basis else "")


def _fy(asof):
    return asof.year if asof.month >= 4 else asof.year - 1


def build_south_ltol(vfl_df, asof, basis_label="") -> tuple[str, bytes]:
    """One page per month, CURRENT MONTH FIRST.

    `south_months` returns fiscal order because that is the order of the data;
    the report reverses it. Whoever opens this wants the month in progress, and
    burying it last means paging past four closed months to reach it.
    """
    asof = pd.Timestamp(asof)
    with _LOCK, desk():
        months = list(reversed(south_months(vfl_df, asof)))
        contents = [(f"South L-to-L · {m['month']} {m['ty_year']}", render_south(m))
                    for m in months]
        pdf = _pdf_from(contents, _label(asof, basis_label))
    fy = _fy(asof)
    return (f"SOUTH STORE {asof:%b}".upper()
            + f" L TO L SHEET ({fy - 1}-{str(fy)[2:]} TO {fy}-{str(fy + 1)[2:]}).pdf",
            pdf)


def _scopes():
    import loader as L
    master = L.load_store_master()
    reg = dict(zip(master["tableau_name"], master["region"]))
    code = dict(zip(master["tableau_name"], master["code"]))

    def vfl(region, takeover=None):
        def _s(df):
            d = df.copy()
            d["_r"] = d[L.COL_STORE_LABEL].map(reg)
            d["_code"] = pd.to_numeric(d[L.COL_STORE_LABEL].map(code),
                                       errors="coerce")
            d = d[d["_r"] == region]
            if takeover is not None:
                d.attrs["takeover"] = takeover
            return d
        return _s
    return L, master, vfl


def build_month_wise(pf_df, vfl_df, asof, basis_label="") -> tuple[str, bytes]:
    """Both regions' month-wise sale detail in ONE file (Manav, 14 Aug).

    East & NE overall, then its Mohey Manyavar stores, then South — the same
    order the night SMS reads in, larger half first. They were two PDFs that
    were always sent together and always compared against each other, and
    nobody wanting the estate should have to open two files to add up a month.
    """
    L, master, vfl = _scopes()
    asof = pd.Timestamp(asof)
    carpet = _carpet_map()
    tk = pd.to_datetime(master.set_index("region").loc["South", "takeover_date"]).min()

    def pf_scope(df):
        d = df[df["region"] == "East & NE"].copy()
        d["code"] = d["code"].astype(int)
        return d

    with _LOCK, desk():
        east_all = month_wise(pf_df, asof, scope=pf_scope, carpet=carpet,
                              store_col="code", amount_col="sales", code_col="code")
        east_vfl = month_wise(vfl_df, asof, scope=vfl("East & NE"), carpet=carpet,
                              store_col=L.COL_STORE_LABEL,
                              amount_col=L.COL_AMOUNT, code_col="_code")
        south = month_wise(vfl_df, asof, scope=vfl("South", tk), carpet=carpet,
                           store_col=L.COL_STORE_LABEL,
                           amount_col=L.COL_AMOUNT, code_col="_code")
        contents = [
            ("East & NE · Overall",
             render_monthwise(east_all, "OVERALL STORES — MONTH-WISE SALE DETAIL")),
            ("East & NE · Mohey Manyavar stores",
             render_monthwise(east_vfl,
                              "MOHEY MANYAVAR STORES — MONTH-WISE SALE DETAIL")),
            ("South · Mohey Manyavar stores",
             render_monthwise(south,
                              "MOHEY MANYAVAR STORES — SOUTH · MONTH-WISE SALE DETAIL")),
        ]
        pdf = _pdf_from(contents, _label(asof, basis_label))
    fy = _fy(asof)
    return (f"{fy - 1}-{str(fy)[2:]} VS {fy}-{str(fy + 1)[2:]} "
            f"MONTH WISE TOTAL SALE REPORT.pdf"), pdf



def bundle(reports: list[tuple[str, bytes]]) -> tuple[str, bytes, str]:
    """One report downloads as itself; several download as a ZIP."""
    if len(reports) == 1:
        name, data = reports[0]
        return name, data, "application/pdf"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in reports:
            z.writestr(name, data)
    return "REPORT_TD.zip", buf.getvalue(), "application/zip"


# ── Month-wise data ─────────────────────────────────────────────────────────
MW_COLS = [
    ("MONTH", 0, "l"),
    ("SALE {LY}", 0, "r"), ("SALE {TY}", 0, "r"), ("DIFF", 0, "r"),
    ("NO. OF STORE {LY}", 0, "c"), ("NO. OF STORE {TY}", 0, "c"), ("DIFF", 0, "c"),
    ("STORE AVG. SALE {LY}", 0, "r"), ("STORE AVG. SALE {TY}", 0, "r"),
    ("DIFF", 0, "r"),
    ("CARPET AREA SQFT {LY}", 0, "r"), ("CARPET AREA SQFT {TY}", 0, "r"),
]
_MONTHS = [(4, "APRIL"), (5, "MAY"), (6, "JUNE"), (7, "JULY"), (8, "AUGUST"),
           (9, "SEPTEMBER"), (10, "OCTOBER"), (11, "NOVEMBER"), (12, "DECEMBER"),
           (1, "JANUARY"), (2, "FEBRUARY"), (3, "MARCH")]


def month_wise(df, asof, *, scope, carpet=None, store_col=None, amount_col=None,
               code_col=None):
    """The month-wise total-sale table for one scope.

    Counts are stores that actually SOLD in the month, which is how the
    workbook's own figures come out on the South and VFL sheets.
    """
    asof = pd.Timestamp(asof)
    fy = _fy(asof)
    d = scope(df)
    tk = d.attrs.get("takeover")
    rows = []
    for mth, name in _MONTHS:
        ty_year = fy if mth >= 4 else fy + 1
        t0 = pd.Timestamp(ty_year, mth, 1); t1 = t0 + pd.offsets.MonthEnd(0)
        l0 = pd.Timestamp(ty_year - 1, mth, 1); l1 = l0 + pd.offsets.MonthEnd(0)
        if tk is not None and tk.year == t0.year and tk.month == t0.month:
            # Takeover-anchored, both years, so the sides compare like with like.
            t0 = max(t0, tk)
            l0 = max(l0, tk - pd.DateOffset(years=1))
        ly = d[(d["date"] >= l0) & (d["date"] <= l1)]
        ty = d[(d["date"] >= t0) & (d["date"] <= t1)]
        ly_sale = float(ly[amount_col].sum())
        ty_sale = float(ty[amount_col].sum()) if t0 <= asof else None
        ly_n = int(ly[ly[amount_col] > 0][store_col].nunique())
        ty_n = int(ty[ty[amount_col] > 0][store_col].nunique()) if ty_sale is not None else None

        def _carpet(frame):
            if not carpet:
                return None
            ids = frame[frame[amount_col] > 0][code_col or store_col].unique()
            return float(sum(carpet.get(int(i), 0) or 0 for i in ids
                             if pd.notna(i)))
        done = ty_sale is not None and t1 <= asof
        rows.append({
            "month": name, "ly_sale": ly_sale, "ty_sale": ty_sale,
            "ly_n": ly_n, "ty_n": ty_n,
            "ly_avg": (ly_sale / ly_n) if ly_n else None,
            "ty_avg": (ty_sale / ty_n) if (ty_n and ty_sale is not None) else None,
            "ly_carpet": _carpet(ly),
            # Only COMPLETED months contribute carpet on the current-year side,
            # as the workbook does: the month in progress has not earned a full
            # month of floor space, and counting it drags the 12-month average
            # down and the throughput with it.
            # The month in progress DOES contribute carpet area — its floor
            # space exists. The two source sheets disagree here: the East
            # workbook fills August's carpet (56,380) while the South one leaves
            # it blank. Generalising from South put a zero in East's August and
            # threw its carpet average and throughput out, so this follows East,
            # which makes that sheet tie exactly. South's blank is an unfilled
            # cell in a live file; until it is filled, its own average and
            # throughput will differ from ours.
            "ty_carpet": _carpet(ty) if ty_sale is not None else None,
            "done": done, "current": t0 <= asof <= t1,
        })
    return {"rows": rows, "fy": fy}


# ═══════════════════════════════════════════════════════════════════════════
# EAST & NE — L TO L SHEET (18 columns)
# ═══════════════════════════════════════════════════════════════════════════
# ★ THE LIKE-TO-LIKE RULES (Manav, 11-12 Aug). All three come from him:
#
#   1. A store that CLOSES leaves last year from the month AFTER its closure
#      month — the closure date is the last month still counted.
#   2. NEW/OLD is decided ONCE A YEAR against 1 April of the PREVIOUS year: a
#      store open before it traded all of last year and is comparable; a store
#      opened on or after it is NEW for the whole fiscal year and joins on the
#      next 1 April. "NA till 31-03-2027, PY from 01-04-2027."
#   3. A store that goes quiet stays IN until a closure date is given.
#
# ★ Rule 2 is an ANNUAL classification, and that is the point. Deciding it
# monthly — "did this store trade in the same month last year?" — lets a store
# switch sides mid-year, so May's index and June's index are computed on
# different populations and the movement between them is part trading and part
# bookkeeping. It also compares against an opening month: Silchar opened
# 01-06-2025 and took Rs 17.0 L that June, then settled to 12.2 and 8.4 — so a
# perfectly ordinary June 2026 of Rs 12.1 L reads as index 71, a 29% "decline"
# that never happened.
#
# ⚠️ THIS DELIBERATELY DIVERGES FROM THE EXISTING WORKBOOK, which decides monthly:
#   * APR — it counts 104 West Point as new; the master says it opened
#     01-12-2024, so under rule 2 it is comparable. Index 84 -> 82.
#   * JUN/JUL — it treats Silchar as comparable once it has a same-month last
#     year; under rule 2 it stays new all year. Index 103 -> 108 and 97 -> 100.
#   * AUG — it drops store 102 from the 8th; 102 has no closure date and Manav
#     said not to drop it until 31-08-2026, so it stays.
#   * 13-JUL — the workbook's new-store cell reads 37,831 against an actual
#     37,891: transposed digits.
EAST_COLS = [
    ("DATE", "c"), ("DAY", "c"),
    ("GRAND TOTAL SALE PRPL {LY}", "r"),
    ("GRAND TOTAL SALE PRPL CUMULATIVE {LY}", "r"),
    ("PRPL STORE TOTAL SALE {LY}", "r"),
    ("DATE", "c"), ("DAY", "c"),
    ("PRPL STORE TOTAL SALE {TY}", "r"),
    ("STORE 58 PLANET MALL TOTAL SALE {TY}", "r"),
    ("NEW STORE {TY}", "r"),
    ("WITHOUT STORE 58 AND NEW STORE SALE", "r"),
    ("PRPL TOTAL {MON} {Y1}", "r"), ("PRPL TOTAL {MON} {Y2}", "r"),
    ("GROTH / D GROTH", "r"),
    ("STORE 58 {MON} {Y1}", "r"),
    ("WITHOUT STORE 58 AND NEW STORE TOTAL {MON} {Y1}", "r"),
    ("WITHOUT STORE 58 AND NEW STORE TOTAL {MON} {Y2}", "r"),
    ("WITHOUT STORE 58 AND NEW STORE GROTH / D GROTH", "r"),
]

CARVE_OUT_CODE = 58          # shown on its own; it has no like-to-like partner
# New-store contribution assumed for the rest of the month, in the projection
# block. Manav types this into the workbook (200000 x days remaining); it is not
# derived from anything, so it is a parameter here rather than a computed value.
NEW_STORE_DAILY_TARGET = 200_000


def _east_sets(codes_this_fy, opened, closed, fy, month):
    """(new, comparable) for one month, under the three rules above."""
    bench = pd.Timestamp(fy - 1, 4, 1)          # 1 April of the PREVIOUS year
    new = {c for c in codes_this_fy
           if c in opened and pd.notna(opened[c]) and opened[c] >= bench}

    def gone(c):
        d = closed.get(c)
        if d is None or pd.isna(d):
            return False
        # Compare on the fiscal timeline so Jan-Mar sort after Apr-Dec.
        f = lambda y, m: (y - fy) * 12 + m
        return f(month.year, month.month) > f(d.year, d.month)

    comparable = {c for c in codes_this_fy if c not in new and not gone(c)}
    return new, comparable


def east_months(pf_df, asof, region="East & NE") -> list[dict]:
    """One dict per month of the fiscal year to date, in the sheet's shape."""
    import master_lookup
    asof = pd.Timestamp(asof)
    fy = _fy(asof)
    d = pf_df[pf_df["region"] == region].copy()
    d["code"] = pd.to_numeric(d["code"], errors="coerce").astype("Int64")
    d = d[d["code"].notna()]
    d["code"] = d["code"].astype(int)

    opened, closed = master_lookup.opened(), master_lookup.closed()
    if not opened:
        raise RuntimeError(
            "no opening dates available — the store master is unreachable and "
            "store_attrs.csv is missing. Refusing to build: without them every "
            "store would silently count as comparable.")

    this_fy = set(d[(d["date"] >= pd.Timestamp(fy, 4, 1)) & (d["sales"] > 0)]["code"])
    daily = d.groupby(["date", "code"])["sales"].sum()
    by_day = d.groupby("date")["sales"].sum()

    def traded(y, m, codes=None):
        a = pd.Timestamp(y, m, 1); b = a + pd.offsets.MonthEnd(0)
        f = d[(d["date"] >= a) & (d["date"] <= b) & (d["sales"] > 0)]
        if codes is not None:
            f = f[f["code"].isin(codes)]
        return int(f["code"].nunique())

    def sales(day, codes=None):
        if codes is None:
            return float(by_day.get(day, 0.0))
        if day not in daily.index.get_level_values(0):
            return 0.0
        s = daily.loc[day]
        return float(s[s.index.isin(codes)].sum())

    out, m = [], pd.Timestamp(fy, 4, 1)
    while m <= asof:
        out.append(_east_month(m, asof, fy, this_fy, opened, closed, sales, traded))
        m += pd.DateOffset(months=1)
    return out


def _east_month(month_start, asof, fy, this_fy, opened, closed, sales,
                traded) -> dict:
    new, comparable = _east_sets(this_fy, opened, closed, fy, month_start)
    y2, mth = month_start.year, month_start.month
    ndays = calendar.monthrange(y2, mth)[1]
    rows = []
    ly_cum = ty_cum = k_cum = o_cum = 0.0
    elapsed = 0
    for i in range(1, ndays + 1):
        ly_d = pd.Timestamp(y2 - 1, mth, i)
        ty_d = pd.Timestamp(y2, mth, i)
        e = sales(ly_d, comparable)                 # comparable LY
        o = sales(ly_d, {CARVE_OUT_CODE})           # store 58 LY
        ly_cum += e
        o_cum += o
        live = ty_d <= asof
        h = sales(ty_d) if live else None           # every store, this year
        i_ = sales(ty_d, {CARVE_OUT_CODE}) if live else None
        j = sales(ty_d, new) if live else None
        k = (h - i_ - j) if live else None
        if live:
            ty_cum += h
            k_cum += k
            elapsed = i
        rows.append({
            "DATE_LY": ly_d, "DAY_LY": ly_d.strftime("%a").upper(),
            "C": e, "D": ly_cum, "E": e,
            "DATE_TY": ty_d, "DAY_TY": ty_d.strftime("%a").upper(),
            "H": h, "I": i_, "J": j, "K": k,
            "L": ly_cum, "M": ty_cum,
            "N": (ty_cum * 100 / ly_cum) if ly_cum else None,
            "O": o,
            "P": ly_cum - o_cum,
            "Q": k_cum,
            "R": (k_cum * 100 / (ly_cum - o_cum)) if (ly_cum - o_cum) else None,
        })

    elapsed = max(elapsed, 1)
    remaining = max(ndays - elapsed, 0)
    ly_total = ly_cum
    ty_total = ty_cum
    i_total = sum(r["I"] or 0 for r in rows)
    j_total = sum(r["J"] or 0 for r in rows)
    k_total = k_cum
    ly_at = next((r["L"] for r in reversed(rows) if r["H"] is not None), 0.0)
    growth10 = ly_total * 0.10
    new_target = NEW_STORE_DAILY_TARGET * remaining
    shortfall = ly_total - ty_total
    return {
        "month": month_start.strftime("%b").upper(), "ty_year": y2, "fy": fy,
        "ndays": ndays, "elapsed": elapsed, "rows": rows,
        # Counts for THAT MONTH, not for the year — the labels beneath them say
        # "AUG 2025 NO. OF STORE", and a year-wide count under a month's label
        # would be a different number from the one the reader expects.
        "n_comparable": len(comparable), "n_trading": len(this_fy),
        "n_ly_month": traded(y2 - 1, mth, comparable),
        "n_ty_month": traded(y2, mth),
        "new_codes": sorted(new),
        "foot": {
            "ly_total": ly_total, "ty_total": ty_total,
            "i_total": i_total, "j_total": j_total, "k_total": k_total,
            "o_total": o_cum,
            "ly_avg_per_day": ly_total / ndays,
            "ty_avg_per_day": ty_total / elapsed,
            "i_avg": i_total / elapsed, "j_avg": j_total / elapsed,
            "k_avg": k_total / elapsed,
            "trending": ty_total / elapsed * ndays,
            "i_trend": i_total / elapsed * ndays,
            "j_trend": j_total / elapsed * ndays,
            "k_trend": k_total / elapsed * ndays,
            "days_remaining": remaining,
            "ly_day_avg_till_yesterday": ly_at / elapsed,
            "ly_avg_per_store": (ly_at / elapsed / len(comparable)) if comparable else 0,
            "ty_avg_per_store": (ty_total / elapsed / len(this_fy)) if this_fy else 0,
            "shortfall": shortfall, "growth_10": growth10,
            "target_total": shortfall + growth10,
            "new_target": new_target,
            "grand_target": shortfall + growth10 + new_target,
            "avg_req_daily": ((shortfall + growth10 + new_target) / remaining)
                             if remaining else 0,
            "projection": ly_total + growth10 + new_target,
        },
    }


def _row(spec, n):
    """A grid row from {column index: cell}, gaps filled, spans respected."""
    out, i = [], 0
    while i < n:
        c = spec.get(i)
        if c is None:
            out.append(cell()); i += 1
        else:
            out.append(c); i += c["span"]
    return out


def render_east(sheet) -> Image.Image:
    mon, y2, fy = sheet["month"], sheet["ty_year"], sheet["fy"]
    subs = {"{MON}": mon, "{LY}": f"{fy - 1}-{str(fy)[2:]}",
            "{TY}": f"{fy}-{str(fy + 1)[2:]}", "{Y1}": str(y2 - 1), "{Y2}": str(y2)}
    header = []
    for h, _ in EAST_COLS:
        for k, v in subs.items():
            h = h.replace(k, v)
        header.append(h)
    aligns = [a for _, a in EAST_COLS]
    n = len(EAST_COLS)

    rows = []
    for r in sheet["rows"]:
        pct = lambda v: "" if v is None else f"{v:,.0f}"
        vals = [r["DATE_LY"].strftime("%d-%m-%Y"), r["DAY_LY"],
                _money(r["C"]), _money(r["D"]), _money(r["E"]),
                r["DATE_TY"].strftime("%d-%m-%Y"), r["DAY_TY"],
                _money(r["H"]), _money(r["I"]), _money(r["J"]), _money(r["K"]),
                _money(r["L"]), _money(r["M"]), pct(r["N"]),
                _money(r["O"]), _money(r["P"]), _money(r["Q"]), pct(r["R"])]
        cs = [cell(v, align=aligns[i]) for i, v in enumerate(vals)]
        # Red marks a decline against last year — an index under 100 — nothing else.
        for idx, key in ((13, "N"), (17, "R")):
            if r[key] is not None and r[key] < 100:
                cs[idx] = cell(vals[idx], align="r", ink=NEG_INK)
        rows.append((cs, ROW_H))

    f = sheet["foot"]
    ncmp, ntr = sheet["n_ly_month"], sheet["n_ty_month"]
    nd, el = sheet["ndays"], sheet["elapsed"]
    Y = lambda a, b: f"{a}-{str(b)[2:]}"

    rows.append((_row({i: cell(v, align="r", fill=TOTAL_BG, bold=True)
                       for i, v in ((2, _money(f["ly_total"])),
                                    (4, _money(f["ly_total"])),
                                    (7, _money(f["ty_total"])),
                                    (8, _money(f["i_total"])),
                                    (9, _money(f["j_total"])),
                                    (10, _money(f["k_total"])),
                                    (14, _money(f["o_total"])))}
                      | {0: cell("TOTAL", fill=TOTAL_BG, bold=True)}
                      | {i: cell(fill=TOTAL_BG) for i in
                         (1, 3, 5, 6, 11, 12, 13, 15, 16, 17)}, n), ROW_H))

    # These two summarise COLUMNS, so they stay under the columns they describe.
    rows.append((_row({0: cell("AVG. PER DAY", fill=HDR_BG, bold=True, span=2),
                       2: cell(_money(f["ly_avg_per_day"]), align="r", bold=True),
                       7: cell(_money(f["ty_avg_per_day"]), align="r", bold=True),
                       8: cell(_money(f["i_avg"]), align="r"),
                       9: cell(_money(f["j_avg"]), align="r"),
                       10: cell(_money(f["k_avg"]), align="r")}, n), ROW_H))

    rows.append((_row({0: cell(f"{nd} DAYS TRENDING", fill=HDR_BG, bold=True,
                               span=2),
                       7: cell(_money(f["trending"]), align="r", bold=True),
                       8: cell(_money(f["i_trend"]), align="r"),
                       9: cell(_money(f["j_trend"]), align="r"),
                       10: cell(_money(f["k_trend"]), align="r")}, n), ROW_H))

    day = _draw_grid(header, rows)
    sections = [
        ("WHERE THE MONTH STANDS", [
            (f"AVG. PER DAY PER STORE {Y(fy - 1, fy)}",
             _money(f["ly_avg_per_store"])),
            (f"AVG. PER DAY PER STORE {Y(fy, fy + 1)}",
             _money(f["ty_avg_per_store"])),
            (f"NO. OF STORES {mon} {y2 - 1}", str(ncmp)),
            (f"NO. OF STORES {mon} {y2}", str(ntr)),
        ]),
        (f"WHERE {mon} {y2} LANDS", [
            (f"{mon} PROJECTIONS", _money(f["projection"])),
            ("NO. OF DAYS REMAINING", str(f["days_remaining"])),
            (f"{mon} {y2 - 1} DAY AVG. TILL YESTERDAY",
             _money(f["ly_day_avg_till_yesterday"])),
            ("DAYS COUNTED SO FAR", str(el)),
        ]),
        (f"TO FINISH ABOVE {mon} {y2 - 1}", [
            ("LY-TY TILL DATE ACHVD.", _money(f["shortfall"])),
            ("10% GROWTH ON LY SALE", _money(f["growth_10"])),
            ("TOTAL", _money(f["target_total"])),
            (f"NEW STORE @ {NEW_STORE_DAILY_TARGET:,}/DAY",
             _money(f["new_target"])),
            ("TOTAL WITH NEW STORE", _money(f["grand_target"])),
            ("AVG. REQ DAILY", _money(f["avg_req_daily"])),
        ]),
    ]
    foot = _foot_grid(sections, day.width,
                      highlight={"TOTAL", "TOTAL WITH NEW STORE"})
    return _stack([day, foot], _px(22))


def build_east_ltol(pf_df, asof, basis_label="") -> tuple[str, bytes]:
    """East & NE L-to-L, current month first."""
    asof = pd.Timestamp(asof)
    with _LOCK, desk():
        months = list(reversed(east_months(pf_df, asof)))
        contents = [(f"East & NE L-to-L · {m['month']} {m['ty_year']}",
                     render_east(m)) for m in months]
        pdf = _pdf_from(contents, _label(asof, basis_label))
    fy = _fy(asof)
    return (f"{asof:%b}".upper()
            + f" L TO L SHEET ({fy - 1}-{str(fy)[2:]} TO {fy}-{str(fy + 1)[2:]}).pdf",
            pdf)


# ═══════════════════════════════════════════════════════════════════════════
# SOUTH — NIGHT SALE SMS
# ═══════════════════════════════════════════════════════════════════════════
# The report that goes out at close, so every figure for the day comes from the
# night fill — the only source that exists at that hour. Month- and year-to-date
# come from the portfolio history, which the night-fill overlay has already
# brought up to the same day.
#
# ★ WHERE THE TARGETS COME FROM. Year and month come from the Targets tab, which
# holds a year target and twelve month columns per store; the day target comes
# from the NIGHT FILL, because it is the one that moves daily and so belongs
# beside the day's figures. Verified against the 09-Aug SMS: both the year and
# the August column match all eight South stores exactly.
#
# Any target still missing renders as an EMPTY cell, and the achievement
# percentage that divides by it is left empty too rather than shown as zero or
# infinite. A store with no target is a store nobody has set one for, which is
# not the same as a store asked for nothing.
#
# MANUAL SALE is read from the night fill when the tab has that column; DAY
# ACHIEVED is system sale plus manual, so it equals system sale until then.
#
# ★ BILL, QTY and FOOTFALL sit in the KPI table, not this one (Manav, 13 Aug).
# The top table is money — targets, sale and achievement. The three counts are
# what the KPIs are computed FROM (ABS = qty/bills, ABV = sale/bills,
# ASP = sale/qty, CONVERSION = bills/footfall), so they belong beside them,
# where a reader can check the ratio against its own inputs.
# ★ ONE REPORT FOR THE WHOLE ESTATE (Manav, 14 Aug). South and East used to be
# two files; they are now one, every store in every city, grouped BY CITY with a
# subtotal per city — so the city figures are read off the same table as the
# stores rather than a second sheet repeating them.
#
# The brand-line split stays. Only the 8 VFL stores fill it, but they fill it
# with real money (Grand Kamraj alone splits Manyavar 2.38 L / Mohey 1.59 L /
# Twamev 42k), and BRAND now names the format for all 50, which is what the
# other 42 need.
#
# ★ DAY ACHIVED MOVED TO THE KPI TABLE, to the right of CONVERSION (Manav,
# 14 Aug), so the money table ends on what was sold and the KPI table ends on
# what that came to.
def _sms_cols(mode="all"):
    head = {"all": [("CITY", "l"), ("LOCATION", "l"), ("BRAND", "l")],
            "vfl": [("STORE NAME", "l")],
            "mixed": [("STORE NAME", "l"), ("BRAND", "l")],
            "city": [("CITY", "l")]}[mode]
    money = [("MTD TARGET", "r"), ("MTD ACHIVED", "r"), ("MTD ACHIVED %", "r"),
             ("YTD TARGET", "r"), ("YTD ACHIVED", "r"),
             ("YTD ACHIVED %", "r"), ("DAY TARGET", "r"),
             ("TOTAL SYSTEM SALE", "r")]
    split = [("MANYAVAR SYSTEM SALE", "r"), ("MOHEY SYSTEM SALE", "r"),
             ("TWAMEV SYSTEM SALE", "r")] if mode in ("vfl", "all") else []
    return head + money + split + [("MANUAL SALE", "r")]


SMS_COLS = _sms_cols("all")
# DAY ACHIVED closes the KPI row: bills, units and footfall, the four rates they
# make, and then the day's takings the rates describe.
KPI_COLS = [("BILL", "r"), ("QTY", "r"), ("FOOTFALL", "r"),
            ("ABS", "r"), ("ABV", "r"), ("ASP", "r"), ("CONVERSION", "r"),
            ("DAY ACHIVED", "r")]


def _ordinal(n: int) -> str:
    """1ST, 2ND, 3RD, 19TH — the header said "01TH APR" for East, because the
    suffix was a literal TH that South's 19th never contradicted."""
    if 11 <= n % 100 <= 13:
        return f"{n:02d}TH"
    return f"{n:02d}" + {1: "ST", 2: "ND", 3: "RD"}.get(n % 10, "TH")


def _line_bucket(name: str) -> str:
    n = str(name).upper()
    if n.startswith("TWAMEV"):
        return "twamev"
    if n.startswith("MOHEY"):
        return "mohey"
    if n.startswith("MANYAVAR"):
        return "manyavar"
    return "other"


def south_night_sms(pf_df, region=None, targets=None) -> dict:
    """The night SMS, as of the night fill's own day.

    `region=None` (the default since 14 Aug) reports the WHOLE estate in one
    sheet, grouped by city. Passing a region still scopes it, which is what the
    tests and any one-region call want, but the report Manav sends is the merged
    one — South and East were two files saying the same things about different
    halves of the same night.
    """
    import night_fill
    import portfolio_loader as PL
    import loader as L
    import targets as TG
    t = night_fill.load()
    if t is None:
        raise RuntimeError(
            f"the night fill is not available ({night_fill.last_problem() or 'not configured'}) "
            "— it is the only source for the day's figures at this hour.")
    day = pd.Timestamp(t["date"].iloc[0])
    if targets is None:
        targets = TG.for_month(day)          # year + month; day comes below

    master = PL.store_master().dropna(subset=["code"]).copy()
    master["code"] = master["code"].astype(int)
    south = master if region is None else master[master["region"] == region]
    # A closed store is not a store that took nothing tonight. East carries
    # three; South none, which is why this never showed before.
    shut = L.closed_map()
    south = south[~south["code"].map(
        lambda c: c in shut and pd.to_datetime(shut[c]) <= day)]
    codes = sorted(south["code"])
    loc = dict(zip(south["code"], south["location"]))
    region_of = dict(zip(south["code"], south["region"]))
    brand_of = dict(zip(south["code"], south.get("brand", pd.Series(dtype=str))))
    city_of = dict(zip(south["code"], south["city"]))
    fy = day.year if day.month >= 4 else day.year - 1
    fy_start = pd.Timestamp(fy, 4, 1)
    mtd_from = day.replace(day=1)
    # ★ EACH STORE KEEPS ITS OWN YEAR START. One anchor for the region worked
    # while the report was one region: South ran from its 19 April takeover,
    # East from 1 April. Merged, the earliest takeover would have restated
    # South's year from 1 April and quietly added a fortnight it did not trade
    # under us. Takeover-anchored is what every other figure in this pack is.
    tk_of = {int(c): pd.to_datetime(t_, errors="coerce")
             for c, t_ in zip(south["code"], south["takeover_date"])}
    ytd_from_of = {c: (max(fy_start, tk) if pd.notna(tk) else fy_start)
                   for c, tk in tk_of.items()}
    anchors = sorted({d for d in ytd_from_of.values()})

    p = pf_df if region is None else pf_df[pf_df["region"] == region]
    p = p.copy()
    p["code"] = pd.to_numeric(p["code"], errors="coerce").astype("Int64")
    mtd = (p[(p["date"] >= mtd_from) & (p["date"] <= day)]
           .groupby("code")["sales"].sum())
    _ytd_rows = p[(p["date"] <= day)]
    _from = _ytd_rows["code"].map(lambda c: ytd_from_of.get(int(c), fy_start)
                                  if pd.notna(c) else fy_start)
    ytd = _ytd_rows[_ytd_rows["date"] >= _from].groupby("code")["sales"].sum()
    ytd_from = min(anchors) if anchors else fy_start

    t = t[t["code"].isin(codes)].copy()
    t["bucket"] = t["line"].map(_line_bucket)
    def g(c, b):
        """A brand line's share of the store's night, or None for a store that
        has no brand lines. The tab splits VFL stores by line and gives every
        other store a single row, so a Turtle or Colorplus store has no Mohey to
        report — and a zero there would say it sold none, not that the question
        does not apply."""
        mine = t[t["code"] == c]
        if not mine["bucket"].isin(("manyavar", "mohey", "twamev")).any():
            return None
        return float(mine[mine["bucket"] == b]["value"].sum())

    def col(c, k):
        """A per-store extra, or None when nothing was typed for it.

        `min_count=1` is the whole point: summing an empty column returns 0.0,
        and a store nobody entered a footfall for then reports "0 footfall"
        rather than a blank. East is typed unevenly today — bills on 39 rows,
        footfall on 23 — so sixteen stores would have claimed nobody walked in.
        """
        if k not in t.columns:
            return None
        v = t[t["code"] == c][k].sum(min_count=1)
        return None if pd.isna(v) else float(v)

    # ★ THE CITY COMES FROM THE NIGHT FILL — Manav's own column, kept beside the
    # figures, so the report follows his naming without a map of ours. A store
    # with no row tonight still has to land in the right group, so it borrows
    # what its neighbours use: same location first, then same city. Falling
    # straight back to the master's city printed a second "KOLKATA" beside his
    # "KOLKATTA". `cluster` (his mall/state grouping) stands behind CITY for a
    # tab that has not been given the column yet.
    cluster_of = {}
    for c in codes:
        mine_ = t[t["code"] == c]
        got = [str(x).strip() for x in mine_.get("city", pd.Series(dtype=str)).tolist()
               if str(x).strip()]
        if not got:
            got = [str(x).strip() for x in mine_.get("cluster", pd.Series(dtype=str)).tolist()
                   if str(x).strip()]
        if got:
            cluster_of[c] = got[0].upper()
    by_loc, by_city = {}, {}
    for c, cl in cluster_of.items():
        by_loc.setdefault(str(loc.get(c, "")).upper(), cl)
        by_city.setdefault(str(city_of.get(c, "")).upper(), cl)

    def _cluster(c):
        return (cluster_of.get(c)
                or by_loc.get(str(loc.get(c, "")).upper())
                or by_city.get(str(city_of.get(c, "")).upper())
                or str(city_of.get(c, "") or "").upper() or "UNMAPPED")

    rows = []
    for c in codes:
        tgt = (targets or {}).get(c, {})
        mine = t[t["code"] == c]
        # A store the night fill has no row for did not file; its day is BLANK,
        # not zero. Ten open East stores are in that position tonight, and a
        # zero would read as "sold nothing" — the same silence-is-not-data
        # mistake that once hid a store's whole month.
        sysS = float(mine["value"].sum()) if len(mine) else None
        man = col(c, "manual")
        # The day target is the night fill's, unless a caller passed one.
        day_t = tgt.get("day")
        if day_t is None:
            day_t = col(c, "day_target")
        if day_t is not None and not (day_t > 0):
            day_t = None                     # zero means unset, not zero-target
        m_ach, y_ach = float(mtd.get(c, 0.0)), float(ytd.get(c, 0.0))
        rows.append({
            "code": c, "name": str(loc.get(c, c)).upper(),
            "brand": str(brand_of.get(c, "") or "").upper(),
            "region": str(region_of.get(c, "") or ""),
            "city": _cluster(c),
            "mtd_target": tgt.get("mtd"), "mtd": m_ach,
            "ytd_target": tgt.get("ytd"), "ytd": y_ach,
            "day_target": day_t,
            "system": sysS, "manyavar": g(c, "manyavar"), "mohey": g(c, "mohey"),
            "twamev": g(c, "twamev"), "manual": man,
            "achieved": None if (sysS is None and man is None)
                        else (sysS or 0.0) + (man or 0.0),
            "bills": col(c, "bills"), "qty": col(c, "qty"),
            "footfall": col(c, "footfall"),
        })
    # The whole estate gets the merged shape — a CITY column in front, BRAND for
    # every store, and the VFL brand-line split kept for the eight that fill it.
    # A single region keeps the shape it had, which is what the tests exercise.
    vfl = bool(south["is_vfl"].all()) if "is_vfl" in south.columns else False
    mode = "all" if region is None else ("vfl" if vfl else "mixed")
    return {"day": day, "region": region or "Peanuts Retail", "rows": rows,
            "ytd_from": ytd_from, "has_targets": bool(targets),
            "mode": mode,
            "filed": sum(1 for r in rows if r["system"] is not None)}


def _kpi_agg(rows):
    """Ratios over the stores that have BOTH sides typed, and only those.

    ★ A ratio cannot be aggregated by summing its parts independently. Footfall
    is typed for some East stores and not others, so Siliguri divided all 21
    stores' bills by the footfall of the four that had one and reported a 380%
    conversion. Each ratio now takes its numerator and denominator from the same
    stores; where nothing pairs up, it stays blank rather than inventing a
    number out of mismatched halves.
    """
    def pair(num_k, den_k):
        n = d = 0.0
        seen = False
        for r in rows:
            a, b = r.get(num_k), r.get(den_k)
            if a is not None and b:
                n += a
                d += b
                seen = True
        return (n, d) if seen else (None, None)

    return {"abs": pair("qty", "bills"), "abv": pair("system", "bills"),
            "asp": pair("system", "qty"), "conv": pair("bills", "footfall")}


def _city_rows(rows):
    """Store rows folded into Manav's clusters, biggest day first."""
    keys = ("mtd", "ytd", "system", "manyavar", "mohey", "twamev", "manual",
            "achieved", "bills", "qty", "footfall", "mtd_target", "ytd_target",
            "day_target")
    out = {}
    for r in rows:
        city = r["city"]
        d = out.setdefault(city, {"name": city, "stores": 0})
        d["stores"] += 1
        for k in keys:
            v = r[k]
            if v is not None:
                d[k] = (d.get(k) or 0.0) + v
    for city, d in out.items():
        for k in keys:
            d.setdefault(k, None)
        d["_kpi"] = _kpi_agg([r for r in rows if r["city"] == city])
    return sorted(out.values(), key=lambda d: -(d["ytd"] or 0))


def _sms_totals(rows):
    keys = ("mtd", "ytd", "system", "manyavar", "mohey", "twamev", "manual",
            "achieved", "bills", "qty", "footfall", "mtd_target", "ytd_target",
            "day_target")
    out = {}
    for k in keys:
        vals = [r[k] for r in rows if r[k] is not None]
        out[k] = sum(vals) if vals else None
    # The grand total is an aggregate like any city row, so its ratios come
    # from the stores that have both sides, not from these summed columns.
    out["_kpi"] = _kpi_agg(rows)
    return out


# ★ THE ROW'S INK CARRIES THE VERDICT (Manav, 14 Aug). Green for a store that
# made its day, red for one that took less than its region's floor — the whole
# line, not a fill, so the tables keep their white ground and the colour reads
# as a judgement on the store rather than a highlight on the paper.
#
# The floors are his: Rs 10,000 a day in East & NE, Rs 50,000 in South, where a
# single store is worth several of the smaller ones.
DAY_FLOOR = {"East & NE": 10_000, "South": 50_000}
# A location total sits between a store and its city, so it is shaded one step
# lighter than the city's band rather than competing with it.
LOC_BG = (237, 246, 249)


def _cells(values, aligns, fill, bold, ink=INK):
    """Row cells, where a value may be `(text, span)` to merge columns."""
    out, i = [], 0
    for v in values:
        text, span = v if isinstance(v, tuple) else (v, 1)
        out.append(cell(text, align=aligns[min(i, len(aligns) - 1)], fill=fill,
                        bold=bold, span=span, ink=ink))
        i += span
    return out


def _made_target(r) -> bool:
    """Beat a target that exists. A store nobody set one for is never green:
    that is not the same as missing it."""
    t, a = r.get("day_target"), r.get("achieved")
    return bool(t) and a is not None and a >= t


def _below_floor(r) -> bool:
    """Took less than its region asks of a store in a day.

    A store with NO figure is not below the floor — it has not filed, which is
    a different thing, and red would accuse it of a bad night it may not have
    had.
    """
    a = r.get("achieved")
    floor = DAY_FLOOR.get(str(r.get("region", "")))
    return floor is not None and a is not None and a < floor


def _row_ink(r):
    """Red beats green: a store can make a small target and still have taken
    less than the floor, and the floor is the more urgent fact."""
    if _below_floor(r):
        return NEG_INK
    if _made_target(r):
        return GREEN
    return INK


def _by_city(rows):
    """Store rows arranged city by city, each city closing with its subtotal.

    Cities lead with the biggest day, which is how the city sheet ordered them
    before it was folded into this one; a store with no day figure still sits
    under its city, because the month and the year to date are its own.
    """
    order = {}
    for c in _city_rows(rows):
        order[c["name"]] = c
    out = []
    # A subtotal that repeats the single row above it is noise, so each level
    # earns its row: a location totals only when it holds more than one store
    # (City Centre carries ten brands, Malda carries one), and a city totals
    # only when it holds more than one store. A region of one city — South is
    # all Bengaluru — leaves the city total to the grand total below it.
    one_city = len(order) == 1
    for city, agg in order.items():
        members = [r for r in rows if r["city"] == city]
        locs = {}
        for r in members:
            locs.setdefault(str(r["name"]), []).append(r)
        for loc in sorted(locs, key=lambda l: -sum(x["system"] or 0 for x in locs[l])):
            part = sorted(locs[loc], key=lambda r: -(r["system"] or 0))
            out.extend(("store", r) for r in part)
            if len(part) > 1:
                lt = _sms_totals(part)
                lt["_kpi"] = _kpi_agg(part)
                out.append(("loctotal", {**lt, "name": f"{loc} TOTAL",
                                         "city": city, "brand": ""}))
        # ★ EVERY CITY CLOSES WITH ITS OWN TOTAL, even a city of one store
        # (Manav, 14 Aug: "agartala and shilchar are their own locations, no
        # relation to gangtok"). Suppressing the single-store totals left
        # Agartala and Silchar as bare rows above Gangtok's, and the GANGTOK
        # TOTAL beneath them read as if it closed all three. A row that repeats
        # the one above it is a small price for a boundary that cannot be
        # misread. A region of ONE city still leaves it to the grand total.
        if not one_city:
            out.append(("subtotal", {**agg, "name": f"{city} TOTAL"}))
    return out


# The regions stay apart (Manav, 14 Aug): "north and east will be a separate
# table and south will be a separate table". East & NE leads because it is the
# larger half; each region carries its own grand total, and there is no combined
# row — the point of splitting them is that they are not added up here.
_REGION_ORDER = ("East & NE", "South")


def _regions_in(rows):
    seen = [r["region"] for r in rows if r.get("region")]
    ordered = [x for x in _REGION_ORDER if x in seen]
    return ordered + sorted({x for x in seen if x not in _REGION_ORDER})


def render_night_sms(sheet, by="store") -> Image.Image:
    """The night's sheets: ONE money table and ONE KPI table for the whole
    estate, running city by city with a subtotal under every city, each region
    closing with its own total, and the grand total closing all of them."""
    day = sheet["day"]
    mode = "city" if by == "city" else sheet.get("mode", "all")
    cols = _sms_cols(mode)
    tk = f"{_ordinal(sheet['ytd_from'].day)} {sheet['ytd_from']:%b}".upper()
    header = [h.replace("{TK}", tk) for h, _ in cols]
    aligns = [a for _, a in cols]
    regions = _regions_in(sheet["rows"]) or [sheet["region"]]

    def pct(a, b):
        return f"{a / b * 100:,.1f}" if (a and b) else ""

    def line(r, kind):
        """A row of the money table. `DAY ACHIVED` is not here any more — it
        closes the KPI table instead (Manav, 14 Aug)."""
        if mode == "all":
            if kind == "grand":                 # the totals row carries no name
                head = [("G. TOTAL", 3)]
            elif kind in ("subtotal", "regiontotal"):
                head = [(r["name"], 3)]
            elif kind == "loctotal":
                # The label spans LOCATION and BRAND — a location total has no
                # brand of its own, and "CITY CENTRE TOTAL" needs the room.
                head = [r["city"], (r["name"], 2)]
            else:
                # The city repeats on every row rather than printing once per
                # group: Manav's standing preference on these sheets, and it
                # survives a reader copying rows out of the middle.
                head = [r["city"], r["name"], r.get("brand", "")]
        elif mode == "mixed":
            head = ["G. TOTAL", ""] if kind == "grand" else [r["name"], r.get("brand", "")]
        else:
            head = ["G. TOTAL"] if kind == "grand" else [r["name"]]
        split = ([_money(r["manyavar"]), _money(r["mohey"]), _money(r["twamev"])]
                 if mode in ("vfl", "all") else [])
        return head + [
            _money(r["mtd_target"]), _money(r["mtd"]),
            pct(r["mtd"], r["mtd_target"]), _money(r["ytd_target"]),
            _money(r["ytd"]), pct(r["ytd"], r["ytd_target"]),
            _money(r["day_target"]), _money(r["system"])] + split + [
            _money(r["manual"])]

    def kpis(r):
        """The three counts, the four rates they make, then the day's takings.

        An aggregate row carries `_kpi`: its rates computed store by store
        rather than off its own summed columns — see `_kpi_agg`.
        """
        b, q, f_, s_ = r["bills"], r["qty"], r["footfall"], r["system"]
        counts = [_money(b), _money(q), _money(f_)]
        k = r.get("_kpi")
        if k:
            def rat(key, mult=1.0, dp=2):
                n, d = k[key]
                return f"{n / d * mult:,.{dp}f}" if (n is not None and d) else ""
            rates = [rat("abs"), rat("abv", dp=0), rat("asp", dp=0),
                     rat("conv", 100.0, 1)]
        else:
            rates = [
                f"{q / b:,.2f}" if (q is not None and b) else "",
                f"{s_ / b:,.0f}" if (s_ is not None and b) else "",
                f"{s_ / q:,.0f}" if (s_ is not None and q) else "",
                f"{b / f_ * 100:,.1f}" if (b is not None and f_) else ""]
        return counts + rates + [_money(r["achieved"])]

    # ★ ONE MONEY TABLE AND ONE KPI TABLE FOR THE WHOLE ESTATE (Manav, 16 Aug).
    # East & NE and South ran as two money tables and two KPI tables; each region
    # now closes with its OWN TOTAL inside a single table, and the grand total
    # closes all of them. A region total is a total like the grand one and takes
    # the same yellow — the workbook does the same at every level of the
    # Growth-Degrowth sheet — with the label saying which region it closes.
    def _region_total(rs, name):
        return {**_sms_totals(rs), "name": f"{name.upper()} TOTAL",
                "city": "", "brand": ""}

    def money_rows(by_region):
        """Every region's cells in one grid, so widths are measured across the
        whole table before any of it is drawn."""
        grid = []
        for n, rs in by_region.items():
            for kind, r in _by_city(rs):
                fill = (HDR_BG if kind == "subtotal"
                        else LOC_BG if kind == "loctotal" else None)
                grid.append((_cells(line(r, kind), aligns, fill,
                                    kind in ("subtotal", "loctotal"),
                                    ink=_row_ink(r) if kind == "store" else INK),
                             ROW_H))
            if _show_region_totals:
                grid.append((_cells(line(_region_total(rs, n), "regiontotal"),
                                    aligns, TOTAL_BG, True), ROW_H))
        T = _sms_totals([r for rs in by_region.values() for r in rs])
        grid.append((_cells(line(T, "grand"), aligns, TOTAL_BG, True), ROW_H))
        return grid

    def kpi_rows(by_region):
        """The same shape, plus BRAND after the location (Manav, 14 Aug)."""
        rows = [r for rs in by_region.values() for r in rs]
        if not any(r["bills"] or r["qty"] or r["footfall"] for r in rows):
            return None

        def kpi_line(r, head, fill, bold, ink=INK):
            return (_cells(head, ["l"] * 3, fill, bold, ink=ink)
                    + [cell(v, align="r", fill=fill, bold=bold, ink=ink)
                       for v in kpis(r)], ROW_H)

        kg = []
        for n, rs in by_region.items():
            for kind, r in _by_city(rs):
                fill = (HDR_BG if kind == "subtotal"
                        else LOC_BG if kind == "loctotal" else None)
                head = ([(r["name"], 3)] if kind == "subtotal"
                        else [r["city"], (r["name"], 2)] if kind == "loctotal"
                        else [r["city"], r["name"], r.get("brand", "")])
                kg.append(kpi_line(r, head, fill, kind in ("subtotal", "loctotal"),
                                   ink=INK if kind != "store" else _row_ink(r)))
            if _show_region_totals:
                RT = _region_total(rs, n)
                kg.append(kpi_line(RT, [(RT["name"], 3)], TOTAL_BG, True))
        T = _sms_totals(rows)
        kg.append(kpi_line(T, [("G. TOTAL", 3)], TOTAL_BG, True))
        return kg

    by_region = {n: [r for r in sheet["rows"] if r.get("region") == n]
                 for n in regions}
    if len(regions) == 1 and not by_region.get(regions[0]):
        by_region = {regions[0]: sheet["rows"]}
    by_region = {n: rs for n, rs in by_region.items() if rs}
    # A region total under a report of ONE region would repeat the grand total
    # below it — the same noise `_by_city` avoids for a single-city region.
    _show_region_totals = len(by_region) > 1

    kh = ["CITY", "LOCATION", "BRAND"] + [h for h, _ in KPI_COLS]
    m_grid = money_rows(by_region)
    k_grid = kpi_rows(by_region)

    # ★ ONE WIDTH FOR EVERY TABLE (Manav, 14 Aug), measured across BOTH regions
    # so they line up down the page and the wider one no longer runs off it.
    # No caps: with the landscape stretch off (below), every column already
    # gets the MINIMUM width its longest value needs and no more, which is the
    # narrow shape Manav asked for. Capping on top of that only clipped
    # "BENGALURU" and "COMMERCIAL STREET" into ellipses.
    m_w = measure_for(header, [r for r, _ in m_grid], len(header))
    k_w = measure_for(kh, [r for r, _ in (k_grid or [])], len(kh))
    # The KPI table carries four fewer columns, so its minimum width is narrower
    # than the money table's. Widen it to match rather than leaving the page with
    # two right edges — every table then starts and ends on the same lines.
    if sum(k_w) < sum(m_w):
        k = sum(m_w) / sum(k_w)
        k_w = [int(round(x * k)) for x in k_w]

    # ★ `landscape=False` matters here. The grid normally hands surplus width
    # back to the columns until the table is landscape-shaped, and that surplus
    # is a function of HEIGHT — so East & NE's 60 rows stretched it half again
    # as wide as South's 8, which is exactly the mismatch Manav saw. Pinned
    # widths with the stretch off give every table the same, narrower shape.
    scope = " · ".join(n.upper() for n in by_region) if not _show_region_totals \
        else "ALL REGIONS"
    parts = [_draw_grid(header, m_grid, widths=m_w, landscape=False,
                        title=f"{scope} — ALL STORE TOTAL SMS  ·  "
                              f"{day:%d %b %Y}")]
    if k_grid:
        parts.append(_draw_grid(kh, k_grid, widths=k_w, landscape=False,
                                title=f"{scope} — DAILY KPI REPORT"))
    else:
        parts.append(_draw_grid(
            [],
            [([cell("No bill, quantity or footfall typed in the night fill — "
                    "this table fills itself the day those three columns are "
                    "entered, as the target columns did.", align="l")], ROW_H)],
            title=f"{scope} — DAILY KPI REPORT"))
    return _stack(parts, _px(30))



def _stack(images, gap):
    """Two tables on one page, left-aligned, with a gap between them."""
    w = max(i.width for i in images)
    h = sum(i.height for i in images) + gap * (len(images) - 1)
    out = Image.new("RGB", (w, h), WHITE)
    y = 0
    for im in images:
        out.paste(im, (0, y))
        y += im.height + gap
    return out


def build_night_sms(pf_df, region=None, targets=None,
                    basis_label="") -> tuple[str, bytes]:
    """One comprehensive PDF: every store, in every city, in one sheet.

    South and East were two files until 14 Aug. They asked the same questions of
    the same night, and anyone wanting the estate had to add two grand totals
    together. Now the money table runs city by city with a subtotal under each
    and the KPI table repeats that shape — so a city figure is read off the same
    page as the stores that make it, and there is no separate city sheet to keep
    in step.
    """
    with _LOCK:
        sheet = south_night_sms(pf_df, region=region, targets=targets)
        day = sheet["day"]
        contents = [(f"{sheet['region']} · Night sale SMS · {day:%d %b %Y}",
                     render_night_sms(sheet))]
        pdf = _pdf_from(contents,
                        f"As of {day:%d %b %Y}"
                        + (f" · {basis_label}" if basis_label else ""))
    tag = "NIGHT SALE SMS" if region is None else f"{region.upper()} NIGHT SALE SMS"
    return (f"{tag} {day:%d-%m-%Y}.pdf", pdf)


# --------------------------------------------------------------------------- #
# TARGET vs ACHIEVEMENT — the night SMS's shape, at MTD and YTD
# --------------------------------------------------------------------------- #
# Manav, 18 Aug: "replicate same report on MTD and YTD level from 01-04-2026 …
# this becomes a target vs ach report to us. and for south, u can do it from
# 19th april, which is the takeover."
#
# ★ THE YEAR ANCHORS ITSELF, from two directions that agree. The achievement
# side runs from each store's own takeover — 1 April for East & NE, 19 April for
# South — exactly as the night SMS does. The target side needs no special case
# at all: the Targets tab has no April figure for seven of the eight South
# stores, because their year began after it. Summing April onward therefore
# gives South a year that starts in May of its own accord.
TVA_COLS = [
    ("CITY", "l"), ("LOCATION", "l"), ("BRAND", "l"),
    ("MTD TARGET", "r"), ("MTD ACHIVED", "r"), ("MTD ACHIVED %", "r"),
    ("MTD BALANCE", "r"),
    ("YTD TARGET", "r"), ("YTD ACHIVED", "r"), ("YTD ACHIVED %", "r"),
    ("YTD BALANCE", "r"),
    ("YEAR TARGET", "r"), ("YEAR ACHIVED %", "r"),
]
_TVA_VALUES = ("mtd_target", "mtd", "mtd_bal", "ytd_target", "ytd", "ytd_bal",
               "year_target")


def _tva_months(asof):
    """The fiscal months elapsed, April first — how a year-to-date target is
    built. A full-year figure would have every store reading 20-something per
    cent in August and looking behind when it is not."""
    order = ("Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
             "Jan", "Feb", "Mar")
    return list(order[:((asof.month - 4) % 12) + 1])


def target_vs_ach(pf_df, asof=None, targets_df=None) -> dict:
    """Rows for the target-vs-achievement sheet, one per store."""
    import portfolio_loader as PL
    import loader as L
    import targets as TG

    asof = PL.as_of(pf_df) if asof is None else pd.Timestamp(asof)
    t = TG.load() if targets_df is None else targets_df
    months = _tva_months(asof)

    master = PL.store_master().dropna(subset=["code"]).copy()
    master["code"] = master["code"].astype(int)
    shut = L.closed_map()
    master = master[~master["code"].map(
        lambda c: c in shut and pd.to_datetime(shut[c]) <= asof)]

    fy = asof.year if asof.month >= 4 else asof.year - 1
    fy_start = pd.Timestamp(fy, 4, 1)
    tk_of = {int(c): pd.to_datetime(x, errors="coerce")
             for c, x in zip(master["code"], master["takeover_date"])}
    start_of = {c: (max(fy_start, tk) if pd.notna(tk) else fy_start)
                for c, tk in tk_of.items()}

    p = pf_df.copy()
    p["code"] = pd.to_numeric(p["code"], errors="coerce").astype("Int64")
    mtd = (p[(p["date"] >= asof.replace(day=1)) & (p["date"] <= asof)]
           .groupby("code")["sales"].sum())
    upto = p[p["date"] <= asof]
    frm = upto["code"].map(lambda c: start_of.get(int(c), fy_start)
                           if pd.notna(c) else fy_start)
    ytd = upto[upto["date"] >= frm].groupby("code")["sales"].sum()

    tgt = {} if t is None else t.set_index("code").to_dict("index")
    rows = []
    for _, m in master.iterrows():
        c = int(m["code"])
        g = tgt.get(c, {})
        mt = g.get(months[-1])
        yt = sum(v for k in months
                 if (v := g.get(k)) is not None and pd.notna(v))
        yr = g.get("year")
        a_m, a_y = float(mtd.get(c, 0.0)), float(ytd.get(c, 0.0))
        rows.append({
            "code": c, "city": str(m["city"]).upper(),
            "name": str(m["location"]), "brand": str(m.get("brand", "") or ""),
            "region": str(m["region"]), "from": start_of.get(c, fy_start),
            "mtd": a_m, "ytd": a_y,
            "mtd_target": float(mt) if mt is not None and pd.notna(mt) else None,
            "ytd_target": float(yt) if yt else None,
            "year_target": float(yr) if yr is not None and pd.notna(yr) else None,
        })
    for r in rows:
        r["mtd_bal"] = (r["mtd_target"] - r["mtd"]) if r["mtd_target"] else None
        r["ytd_bal"] = (r["ytd_target"] - r["ytd"]) if r["ytd_target"] else None
    return {"rows": rows, "asof": asof, "months": months,
            "fy_start": fy_start}


def _tva_total(part, label, city="", brand=""):
    """Sum a set of stores into one row. Used for every tier, so a region total
    cannot quietly become the last city's — which is exactly what it was."""
    d = {"name": label, "city": city, "brand": brand,
         "from": min(r["from"] for r in part)}
    for k in _TVA_VALUES:
        vals = [r[k] for r in part if r.get(k) is not None]
        d[k] = sum(vals) if vals else None
    d["mtd"] = sum(r["mtd"] for r in part)
    d["ytd"] = sum(r["ytd"] for r in part)
    return d


def _tva_group(rows):
    """City, then location, then store — the night SMS's own shape."""
    def tot(part, label, city="", brand=""):
        d = {"name": label, "city": city, "brand": brand,
             "from": min(r["from"] for r in part)}
        for k in _TVA_VALUES:
            vals = [r[k] for r in part if r.get(k) is not None]
            d[k] = sum(vals) if vals else None
        d["mtd"] = sum(r["mtd"] for r in part)
        d["ytd"] = sum(r["ytd"] for r in part)
        return d

    out = []
    cities = {}
    for r in rows:
        cities.setdefault(r["city"], []).append(r)
    for city in sorted(cities, key=lambda c: -sum(x["ytd"] for x in cities[c])):
        members = cities[city]
        locs = {}
        for r in members:
            locs.setdefault(r["name"], []).append(r)
        for loc in sorted(locs, key=lambda l: -sum(x["ytd"] for x in locs[l])):
            part = sorted(locs[loc], key=lambda r: -r["ytd"])
            out.extend(("store", r) for r in part)
            if len(part) > 1:
                out.append(("loctotal", tot(part, f"{loc} TOTAL", city)))
        out.append(("subtotal", tot(members, f"{city} TOTAL")))
    return out


def _tva_pace(r, asof, kind):
    """How far through the period we are — what "on target" means today."""
    if kind == "MTD":
        return asof.day / calendar.monthrange(asof.year, asof.month)[1]
    fy_end = pd.Timestamp(asof.year + (1 if asof.month >= 4 else 0), 3, 31)
    span = (fy_end - r["from"]).days + 1
    return ((asof - r["from"]).days + 1) / span if span > 0 else 1.0


def render_target_vs_ach(sheet, region=None) -> "Image":
    """One money table: every store against its month and its year."""
    asof = sheet["asof"]
    rows = [r for r in sheet["rows"]
            if region is None or r["region"] == region]
    header = [h for h, _ in TVA_COLS]
    aligns = [a for _, a in TVA_COLS]

    def pct(a, b):
        return f"{a / b * 100:,.1f}" if (a is not None and b) else ""

    def line(r, kind):
        if kind == "store":
            head = [r["city"], r["name"], r.get("brand", "")]
        elif kind == "loctotal":
            head = [r["city"], (r["name"], 2)]
        else:
            head = [(r["name"], 3)]
        return head + [
            _money(r["mtd_target"]), _money(r["mtd"]),
            pct(r["mtd"], r["mtd_target"]), _money(r["mtd_bal"]),
            _money(r["ytd_target"]), _money(r["ytd"]),
            pct(r["ytd"], r["ytd_target"]), _money(r["ytd_bal"]),
            _money(r["year_target"]), pct(r["ytd"], r["year_target"])]

    def ink_for(r, kind):
        """Green once the target is met, red when behind where the calendar is.

        A store at 60% of its month on the 17th is not behind — it is exactly
        where it should be. Colouring anything under 100% red would paint the
        whole sheet red every day but the last, and be ignored by the second
        morning.
        """
        if kind not in ("store",) or not r.get("mtd_target"):
            return INK
        share = r["mtd"] / r["mtd_target"] if r["mtd_target"] else 0
        if share >= 1:
            return GREEN
        return NEG_INK if share < _tva_pace(r, asof, "MTD") * 0.9 else INK

    grid = []
    for kind, r in _tva_group(rows):
        fill = (HDR_BG if kind == "subtotal"
                else LOC_BG if kind == "loctotal" else None)
        grid.append((_cells(line(r, kind), aligns, fill,
                            kind in ("subtotal", "loctotal"),
                            ink=ink_for(r, kind)), ROW_H))
    if region is None:
        for reg in sorted({r["region"] for r in rows}):
            part = [r for r in rows if r["region"] == reg]
            if part:
                grid.append((_cells(line(_tva_total(part, f"{reg.upper()} TOTAL"),
                                         "subtotal"), aligns, TOTAL_BG, True),
                             ROW_H))
    grid.append((_cells(line(_tva_total(rows, "G. TOTAL"), "subtotal"),
                        aligns, TOTAL_BG, True), ROW_H))

    m = sheet["months"]
    return _draw_grid(header, grid, landscape=False,
                      title=f"TARGET vs ACHIEVEMENT  ·  {asof:%d %b %Y}  ·  "
                            f"year to date covers {m[0]}–{m[-1]}")


def build_target_vs_ach(pf_df, asof=None, basis_label="") -> tuple[str, bytes]:
    """The whole estate, one page, against month and year."""
    sheet = target_vs_ach(pf_df, asof)
    asof = sheet["asof"]
    with _LOCK, desk():
        img = render_target_vs_ach(sheet)
        pdf = _pdf_from([("Target vs achievement", img)],
                        f"As of {asof:%d %b %Y}"
                        + (f" · {basis_label}" if basis_label else ""))
    return (f"TARGET VS ACHIEVEMENT {asof:%d-%m-%Y}.pdf", pdf)
