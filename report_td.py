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
import zipfile

import pandas as pd
from PIL import Image, ImageDraw

from imaging import _LOCK
import portfolio_pdf as PP
from portfolio_pdf import (_ft, _px, _fmt_in, _compose, save_pages,
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
FOOT_ROWS = [(_px(50), False), (_px(46), False), (_px(46), False),
             (_px(46), False), (_px(92), True), (_px(92), True), (_px(92), True)]
# Cells the workbook merges, as inclusive 0-based spans per footer row.
MERGES = {
    1: [(4, 6)], 2: [(4, 6)], 3: [(7, 10)],
    4: [(0, 1)], 5: [(0, 1)], 6: [(0, 1), (2, 3)],
}


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

    out, m = [], pd.Timestamp(fy, 4, 1)
    while m <= asof:
        out.append(_one_month(daily, m, asof, n_stores))
        m += pd.DateOffset(months=1)
    return out


def _one_month(daily, month_start, asof, n_stores) -> dict:
    ty_year, mth = month_start.year, month_start.month
    ndays = calendar.monthrange(ty_year, mth)[1]
    rows, ly_cum, ty_cum, elapsed, ly_at_elapsed = [], 0.0, 0.0, 0, 0.0
    for i in range(1, ndays + 1):
        ly_d = pd.Timestamp(ty_year - 1, mth, i)
        ty_d = pd.Timestamp(ty_year, mth, i)
        ly_v = float(daily.get(ly_d, 0.0))
        ty_v = float(daily.get(ty_d, 0.0)) if ty_d <= asof else None
        ly_cum += ly_v
        if ty_v is not None:
            ty_cum += ty_v
            elapsed, ly_at_elapsed = i, ly_cum
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


# ── Table rendering ─────────────────────────────────────────────────────────
def _cell(d, box, text, font, *, fill=None, ink=INK, align="c", bold_grid=False):
    x0, y0, x1, y1 = box
    if fill is not None:
        d.rectangle([x0, y0, x1, y1], fill=fill)
    d.rectangle([x0, y0, x1, y1], outline=GRID, width=2 if bold_grid else 1)
    if text in (None, ""):
        return
    text = str(text)
    tw = d.textlength(text, font=font)
    a, dsc = font.getmetrics()
    ty = y0 + max(0, ((y1 - y0) - (a + dsc)) // 2)
    tx = (x0 + PAD_X if align == "l" else
          x1 - PAD_X - tw if align == "r" else
          x0 + max(2, ((x1 - x0) - tw) / 2))
    d.text((tx, ty), text, font=font, fill=ink)


def _wrapped(d, box, text, font, fill, ink=INK):
    x0, y0, x1, y1 = box
    if fill is not None:
        d.rectangle([x0, y0, x1, y1], fill=fill)
    d.rectangle([x0, y0, x1, y1], outline=GRID, width=1)
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= (x1 - x0) - 2 * PAD_X or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    a, dsc = font.getmetrics()
    lh = a + dsc
    ty = y0 + max(2, ((y1 - y0) - lh * len(lines)) // 2)
    for ln in lines:
        tw = d.textlength(ln, font=font)
        d.text((x0 + max(2, ((x1 - x0) - tw) / 2), ty), ln, font=font, fill=ink)
        ty += lh


def render_south(sheet) -> Image.Image:
    reg, _ = _ft(FONT_PX)
    _, bold = _ft(FONT_PX)
    _, hbold = _ft(HDR_FONT_PX)

    widths = [int(round(u * PX_PER_UNIT)) for _, u, _ in SOUTH_COLS]
    xs = [0]
    for w in widths:
        xs.append(xs[-1] + w)
    total_w = xs[-1]
    height = HDR_H + len(sheet["rows"]) * ROW_H + sum(h for h, _ in FOOT_ROWS)

    img = Image.new("RGB", (total_w, height), WHITE)
    d = ImageDraw.Draw(img)

    mon, y2 = sheet["month"], sheet["ty_year"]
    subs = {"{MON}": mon, "{LY}": f"{y2 - 1}-{str(y2)[2:]}",
            "{TY}": f"{y2}-{str(y2 + 1)[2:]}", "{Y1}": str(y2 - 1), "{Y2}": str(y2)}
    for i, (h, _, _) in enumerate(SOUTH_COLS):
        for k, v in subs.items():
            h = h.replace(k, v)
        _wrapped(d, (xs[i], 0, xs[i + 1], HDR_H), h, hbold, HDR_BG)

    y = HDR_H
    aligns = [a for _, _, a in SOUTH_COLS]
    for r in sheet["rows"]:
        k = r["K"]
        vals = [r["DATE_LY"].strftime("%d-%m-%Y"), r["DAY_LY"],
                _money(r["C"]), _money(r["D"]), _money(r["E"]),
                r["DATE_TY"].strftime("%d-%m-%Y"), r["DAY_TY"],
                _money(r["H"]), _money(r["I"]), _money(r["J"]),
                "" if k is None else f"{k:,.0f}"]
        for i, v in enumerate(vals):
            # Red marks a DECLINE against last year, nothing else.
            ink = NEG_INK if (i == 10 and k is not None and k < 100) else INK
            _cell(d, (xs[i], y, xs[i + 1], y + ROW_H), v, reg,
                  ink=ink, align=aligns[i])
        y += ROW_H

    f, ndays = sheet["foot"], sheet["ndays"]
    blank = [""] * len(widths)
    row_i = 0

    def frow(cells, fills=None, inks=None, bolds=(), grid=False):
        nonlocal y, row_i
        h, wrap = FOOT_ROWS[row_i]
        spans = {}
        for a, b in MERGES.get(row_i, []):
            for c in range(a, b + 1):
                spans[c] = (a, b)
        i = 0
        while i < len(widths):
            a, b = spans.get(i, (i, i))
            box = (xs[a], y, xs[b + 1], y + h)
            fill = (fills or {}).get(a)
            ink = (inks or {}).get(a, INK)
            font = bold if a in bolds else reg
            if wrap and cells[a]:
                _wrapped(d, box, cells[a], font, fill, ink=ink)
            else:
                _cell(d, box, cells[a], font, fill=fill, ink=ink,
                      align=("r" if a in (2, 3, 4, 7, 8, 9, 10) else "c"),
                      bold_grid=grid)
            i = b + 1
        y += h
        row_i += 1

    # Grand total — the one row that earns the workbook's yellow.
    tot = list(blank)
    tot[2] = tot[4] = _money(f["ly_total"]); tot[7] = _money(f["ty_total"])
    frow(tot, fills={i: TOTAL_BG for i in range(len(widths))},
         bolds=set(range(len(widths))), grid=True)

    r = list(blank)
    r[0] = f"{y2 - 1}-{str(y2)[2:]}"; r[1] = str(sheet["n_stores"])
    r[2] = _money(f["ly_avg_per_day"])
    r[4] = f"AVG. PER DAY {mon} {y2}"; r[7] = _money(f["ty_avg_per_day"])
    frow(r, fills={4: HDR_BG}, bolds={2, 7})

    r = list(blank)
    r[0] = f"{y2}-{str(y2 + 1)[2:]}"; r[1] = str(sheet["n_stores"])
    r[2] = f"AVG. {mon} {y2 - 1}"
    r[4] = f"{ndays} DAYS TRENDING {mon} {y2}"; r[7] = _money(f["trending"])
    frow(r, fills={4: HDR_BG}, bolds={7})

    r = list(blank)
    r[0] = _money(f["ly_avg_per_store"]); r[2] = _money(f["projection"])
    r[3] = _money(f["ly_day_avg_till_yesterday"])
    r[7] = f"NO. OF DAYS REMAINING  {f['days_remaining']}"
    frow(r, fills={7: HDR_BG}, bolds={2})

    r = list(blank)
    r[0] = f"AVG. PER DAY PER STORE {mon} {y2 - 1}-{str(y2)[2:]}"
    r[2] = f"{mon} PROJECTIONS"; r[3] = f"{mon} {y2 - 1} DAY AVG. TILL YESTERDAY"
    r[7] = _money(f["ly_minus_ty"]); r[8] = _money(f["growth_10"])
    r[9] = _money(f["target_total"])
    frow(r, fills={0: HDR_BG, 2: HDR_BG, 3: HDR_BG}, bolds={7, 8, 9})

    r = list(blank)
    r[0] = _money(f["ty_avg_per_store"]); r[2] = str(sheet["n_stores"])
    r[7] = "LY-TY TILL DATE ACHVD."; r[8] = "10% GROWTH ON LY SALE"; r[9] = "TOTAL"
    frow(r, fills={7: HDR_BG, 8: HDR_BG, 9: HDR_BG})

    r = list(blank)
    r[0] = f"AVG. PER DAY PER STORE {mon} {y2}-{str(y2 + 1)[2:]}"
    r[2] = f"{mon} {y2 - 1} NO. OF STORE"
    frow(r, fills={0: HDR_BG, 2: HDR_BG})

    return img.crop((0, 0, total_w, y))


# ── Build ───────────────────────────────────────────────────────────────────
def build_south_ltol(vfl_df, asof, basis_label="") -> tuple[str, bytes]:
    """-> (filename, pdf bytes). One page per month, CURRENT MONTH FIRST.

    `south_months` returns fiscal order (April onward) because that is the
    natural order of the data; the report reverses it. Whoever opens this wants
    the month in progress, and burying it on the last page means paging past
    four closed months to reach the only one that can still be acted on.
    """
    asof = pd.Timestamp(asof)
    label = f"As of {asof:%d %b %Y}" + (f" · {basis_label}" if basis_label else "")
    with _LOCK:
        months = list(reversed(south_months(vfl_df, asof)))
        contents = [(f"South L-to-L · {m['month']} {m['ty_year']}", render_south(m))
                    for m in months]
        page_w = max(c.width for _, c in contents) + 2 * (PP.MARGIN + PP.FRAME + PP.PAD)
        page_h = max(c.height for _, c in contents) + (
            PP.MARGIN + PP.FRAME + PP.HEADER_H + PP.PAD + PP.FOOTER_H
            + PP.FRAME + PP.MARGIN)
        pages = [_compose(img, section, label, i, len(contents), page_w,
                          footer_right=FOOTER_RIGHT, page_h=page_h)
                 for i, (section, img) in enumerate(contents, start=1)]
        pdf = save_pages(pages)
    fy = asof.year if asof.month >= 4 else asof.year - 1
    name = (f"SOUTH STORE {asof:%b}".upper()
            + f" L TO L SHEET ({fy - 1}-{str(fy)[2:]} TO {fy}-{str(fy + 1)[2:]}).pdf")
    return name, pdf


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
