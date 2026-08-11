"""
REPORT T.D. — a separate reporting vertical.

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
Report T.D. page and a pack page are recognisably the same document family. Only
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
                           HDR_BG, TOTAL_BG, NEG_INK, GRID, INK, WHITE)

FOOTER_RIGHT = "Peanuts Retail · Report T.D."

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

PX_PER_UNIT = 22            # workbook width unit -> px
FONT_PX, HDR_FONT_PX = 30, 25
ROW_H = _px(46)
HDR_H = _px(126)
PAD_X = _px(12)

# Footer rows: (height, wraps?). The last three carry labels that wrap onto two
# lines; at 30px type two lines need ~80px, so they are given 92 rather than the
# workbook's own heights — 70 clipped "AVG. PER DAY PER STORE AUG 2026-27" in
# half, and a label cut off mid-phrase is worse than a slightly taller row.
FOOT_LABEL_H = _px(96)   # the wrapping label rows; two lines of 30px type
# Merged spans are now carried on the cells themselves (see render_south).


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


def _draw_grid(header, rows, *, title=None, hdr_h=None, landscape=True):
    """rows: list of (cells, height). Returns a cropped image."""
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    reg, _ = _ft(FONT_PX)
    _, bold = _ft(FONT_PX)
    _, hbold = _ft(HDR_FONT_PX)
    ncols = sum(c["span"] for c in rows[0][0]) if rows else len(header or [])
    widths = _measure(scratch, header, [r for r, _ in rows], reg, bold, hbold, ncols)
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
    if landscape:
        want = height * (PAGE_PT_W / 595.0)
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

    f, ndays, n = sheet["foot"], sheet["ndays"], sheet["n_stores"]
    blank = lambda: [cell() for _ in range(11)]

    c = blank()
    c[2] = cell(_money(f["ly_total"]), align="r", fill=TOTAL_BG, bold=True)
    c[4] = cell(_money(f["ly_total"]), align="r", fill=TOTAL_BG, bold=True)
    c[7] = cell(_money(f["ty_total"]), align="r", fill=TOTAL_BG, bold=True)
    for i in (0, 1, 3, 5, 6, 8, 9, 10):
        c[i] = cell(fill=TOTAL_BG)
    rows.append((c, ROW_H))

    c = blank()
    c[0] = cell(f"{y2 - 1}-{str(y2)[2:]}"); c[1] = cell(str(n))
    c[2] = cell(_money(f["ly_avg_per_day"]), align="r", bold=True)
    c[4] = cell(f"AVG. PER DAY {mon} {y2}", fill=HDR_BG, span=3)
    c[7] = cell(_money(f["ty_avg_per_day"]), align="r", bold=True)
    rows.append(([c[0], c[1], c[2], c[3], c[4], c[7], c[8], c[9], c[10]], ROW_H))

    c = blank()
    c[0] = cell(f"{y2}-{str(y2 + 1)[2:]}"); c[1] = cell(str(n))
    c[2] = cell(f"AVG. {mon} {y2 - 1}")
    c[4] = cell(f"{ndays} DAYS TRENDING {mon} {y2}", fill=HDR_BG, span=3)
    c[7] = cell(_money(f["trending"]), align="r", bold=True)
    rows.append(([c[0], c[1], c[2], c[3], c[4], c[7], c[8], c[9], c[10]], ROW_H))

    c = blank()
    c[0] = cell(_money(f["ly_avg_per_store"]), align="r")
    c[2] = cell(_money(f["projection"]), align="r", bold=True)
    c[3] = cell(_money(f["ly_day_avg_till_yesterday"]), align="r")
    c[7] = cell(f"NO. OF DAYS REMAINING  {f['days_remaining']}", fill=HDR_BG, span=4)
    rows.append(([c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]], ROW_H))

    c = blank()
    c[0] = cell(f"AVG. PER DAY PER STORE {mon} {y2 - 1}-{str(y2)[2:]}",
                fill=HDR_BG, span=2, wrap=True)
    c[2] = cell(f"{mon} PROJECTIONS", fill=HDR_BG, wrap=True)
    c[3] = cell(f"{mon} {y2 - 1} DAY AVG. TILL YESTERDAY", fill=HDR_BG, wrap=True)
    c[7] = cell(_money(f["ly_minus_ty"]), align="r", bold=True)
    c[8] = cell(_money(f["growth_10"]), align="r", bold=True)
    c[9] = cell(_money(f["target_total"]), align="r", bold=True)
    rows.append(([c[0], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10]],
                 FOOT_LABEL_H))

    c = blank()
    c[0] = cell(_money(f["ty_avg_per_store"]), align="r", span=2)
    c[2] = cell(str(n))
    c[7] = cell("LY-TY TILL DATE ACHVD.", fill=HDR_BG, wrap=True)
    c[8] = cell("10% GROWTH ON LY SALE", fill=HDR_BG, wrap=True)
    c[9] = cell("TOTAL", fill=HDR_BG)
    rows.append(([c[0], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10]],
                 FOOT_LABEL_H))

    c = blank()
    c[0] = cell(f"AVG. PER DAY PER STORE {mon} {y2}-{str(y2 + 1)[2:]}",
                fill=HDR_BG, span=2, wrap=True)
    c[2] = cell(f"{mon} {y2 - 1} NO. OF STORE", fill=HDR_BG, span=2, wrap=True)
    rows.append(([c[0], c[2], c[4], c[5], c[6], c[7], c[8], c[9], c[10]],
                 FOOT_LABEL_H))
    return _draw_grid(header, rows)


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
    with _LOCK:
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


def build_month_wise_south(vfl_df, asof, basis_label="") -> tuple[str, bytes]:
    L, master, vfl = _scopes()
    asof = pd.Timestamp(asof)
    tk = pd.to_datetime(master.set_index("region").loc["South", "takeover_date"]).min()
    with _LOCK:
        sheet = month_wise(vfl_df, asof, scope=vfl("South", tk),
                           carpet=_carpet_map(), store_col=L.COL_STORE_LABEL,
                           amount_col=L.COL_AMOUNT, code_col="_code")
        img = render_monthwise(
            sheet, "MOHEY MANYAVAR STORES — SOUTH · MONTH-WISE SALE DETAIL")
        pdf = _pdf_from([("South · Month-wise total sale", img)],
                        _label(asof, basis_label))
    fy = _fy(asof)
    return (f"SOUTH STORE {fy - 1}-{str(fy)[2:]} VS {fy}-{str(fy + 1)[2:]} "
            f"MONTH WISE TOTAL SALE REPORT.pdf"), pdf


def build_month_wise_east(pf_df, vfl_df, asof, basis_label="") -> tuple[str, bytes]:
    """Both sheets of the East workbook: OVERALL, then the VFL stores."""
    L, master, vfl = _scopes()
    asof = pd.Timestamp(asof)
    carpet = _carpet_map()

    def pf_scope(df):
        d = df[df["region"] == "East & NE"].copy()
        d["code"] = d["code"].astype(int)
        return d

    with _LOCK:
        all_sheet = month_wise(pf_df, asof, scope=pf_scope, carpet=carpet,
                               store_col="code", amount_col="sales", code_col="code")
        vfl_sheet = month_wise(vfl_df, asof, scope=vfl("East & NE"), carpet=carpet,
                               store_col=L.COL_STORE_LABEL,
                               amount_col=L.COL_AMOUNT, code_col="_code")
        contents = [
            ("East & NE · Overall",
             render_monthwise(all_sheet, "OVERALL STORES — MONTH-WISE SALE DETAIL")),
            ("East & NE · Mohey Manyavar stores",
             render_monthwise(vfl_sheet,
                              "MOHEY MANYAVAR STORES — MONTH-WISE SALE DETAIL")),
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
