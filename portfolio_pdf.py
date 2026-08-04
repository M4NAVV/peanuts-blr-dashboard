"""Portfolio-mode report PDF — the five workbook sheets compiled into one
shareable, print-clean file, in the dashboard's order:

    MW Data · GD Sheet · Brand-wise GD · Loc-wise GD · Average

Deliberately self-contained (its own Pillow rendering + page composition) so it
ships independently of the VFL report PDF. It reuses only the process-wide font
cache and render lock from ``imaging`` — no matplotlib (which crashed the deploy).

Design goals (in priority order): readability, then a CONSTANT thin frame with
identical margins on every page. Every page is rendered to the SAME width (the
widest sheet drives it); narrower sheets are centred inside the frame, so the
border is visually constant as you flip through. Page height follows content.

Everything is rendered at ``_S``× the logical pixel size (supersampling) and the
PDF is saved at a matching resolution, so the physical layout is unchanged but
the text is high-definition / crisp.
"""
from __future__ import annotations

import io
import re

from PIL import Image, ImageDraw

from imaging import _fonts, _LOCK
from portfolio_loader import (
    gd_sheet_report, brand_wise_gd_report, loc_wise_gd_report, average_report,
    mw_data, _MW_BLOCKS, _MW_STD, _MW_REG,
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
LINE = (231, 225, 214)               # hairline / gridlines
_ROW_BG = {                          # row-type → (background, bold?)
    "subtotal":   ((246, 217, 213), True),
    "grand":      ((205, 232, 207), True),
    "storetotal": ((251, 238, 230), True),
    "block":      ((214, 228, 245), True),
}
_ZEBRA = ((255, 255, 255), (250, 246, 239))

# --- supersampling: render at _S× pixels for crisp, high-definition text ---- #
_S = 2


def _px(n) -> int:
    return int(round(n * _S))


def _ft(size):
    """Fonts at the supersampled size (reg, bold)."""
    return _fonts(int(round(size * _S)))


# --- page geometry (logical px, scaled by _S at use) ----------------------- #
MARGIN = _px(42)     # white gap from page edge to the frame
FRAME = _px(2)       # frame thickness (constant, narrow)
PAD = _px(24)        # frame → content padding
HEADER_H = _px(76)   # section-header band height
FOOTER_H = _px(48)   # footer band height
PAD_X, PAD_Y = _px(16), _px(10)   # table cell padding
COL_CAP = _px(320)   # max data width before a column stops growing


def _fmt_in(x, dec=2) -> str:
    """Indian digit grouping (1,69,709.00), matching app.fmt_in."""
    if x is None:
        return "—"
    try:
        if x != x:                    # NaN
            return "—"
    except TypeError:
        return str(x)
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
# Rows of body per page. The maroon column header is repeated at the top of
# every page (see _render_chunk), so you never lose the column labels mid-report.
ROWS_PER_PAGE = 34


def _measure_table(df, *, money=(), pct=(), sign=(), money_dp=0,
                   font_px=21, header_px=19):
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
            try:
                return "—" if v != v else f"{float(v):,.2f}%"
            except (TypeError, ValueError):
                return "—" if v in (None, "") else str(v)
        if v is None or (isinstance(v, float) and v != v):
            return ""
        return str(v)

    txt = [[cell_text(c, df.iloc[i][c]) for c in cols] for i in range(len(df))]
    is_num = [c in money or c in pct for c in cols]

    # Column widths: data drives width (capped); header wraps to that width.
    col_w, hdr_lines = [], []
    for j, c in enumerate(cols):
        data_w = max((scratch.textlength(txt[i][j], font=reg)
                      for i in range(len(df))), default=0)
        target = min(max(data_w, _px(30)), COL_CAP)
        lines = _wrap(scratch, c, hbold, target)
        hw = max(scratch.textlength(ln, font=hbold) for ln in lines)
        hdr_lines.append(lines)
        col_w.append(int(max(target, hw)) + 2 * PAD_X)

    asc, desc = reg.getmetrics()
    row_h = asc + desc + 2 * PAD_Y
    hasc, hdesc = hbold.getmetrics()
    hline_h = hasc + hdesc + _px(2)
    head_h = max(len(l) for l in hdr_lines) * hline_h + 2 * PAD_Y

    return dict(cols=cols, txt=txt, is_num=is_num, col_w=col_w, hdr_lines=hdr_lines,
                head_h=head_h, row_h=row_h, hline_h=hline_h, W=sum(col_w),
                reg=reg, bold=bold, hbold=hbold, sign=sign)


def _render_chunk(m, row_types, rows):
    """Render the maroon column header + the given body `rows` (indices into the
    measured table) as one page-content image, so the header repeats per page."""
    W, head_h, row_h, hline_h = m["W"], m["head_h"], m["row_h"], m["hline_h"]
    cols, col_w, txt, is_num = m["cols"], m["col_w"], m["txt"], m["is_num"]
    reg, bold, hbold, sign = m["reg"], m["bold"], m["hbold"], m["sign"]
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    H = head_h + len(rows) * row_h
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # header (repeated on every page)
    d.rectangle([0, 0, W, head_h], fill=MAROON)
    x = 0
    for j in range(len(cols)):
        lines = m["hdr_lines"][j]
        ty = head_h - PAD_Y - len(lines) * hline_h + _px(2)
        for ln in lines:
            lw = scratch.textlength(ln, font=hbold)
            d.text((x + (col_w[j] - lw) / 2, ty), ln, font=hbold, fill=WHITE)
            ty += hline_h
        x += col_w[j]

    # body
    y = head_h
    for k, i in enumerate(rows):
        t = row_types[i] if row_types else "store"
        bg, is_bold = _ROW_BG.get(t, (_ZEBRA[k % 2], False))
        d.rectangle([0, y, W, y + row_h], fill=bg)
        x = 0
        for j, c in enumerate(cols):
            s = txt[i][j]
            f = bold if is_bold else reg
            color = DARK
            if c in sign and s not in ("", "—"):
                color = RED if s.lstrip().startswith("-") else GREEN
                f = bold
            tw = scratch.textlength(s, font=f)
            cx = x + col_w[j] - PAD_X - tw if is_num[j] else x + PAD_X
            d.text((cx, y + PAD_Y), s, font=f, fill=color)
            x += col_w[j]
        d.line([0, y + row_h, W, y + row_h], fill=LINE)
        y += row_h
    d.rectangle([0, 0, W - 1, H - 1], outline=LINE)
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


def _add_sheet(contents, section, disp, rt, *, money, pct, sign, money_dp):
    """Measure, paginate, and append one (possibly multi-page) sheet. The column
    header repeats on every page; continued pages are labelled 'k/total'."""
    m = _measure_table(disp, money=money, pct=pct, sign=sign, money_dp=money_dp)
    row_pages = _paginate(rt)
    n = len(row_pages)
    for k, rows in enumerate(row_pages):
        label = section if n == 1 else f"{section} — {k + 1}/{n}"
        contents.append((label, _render_chunk(m, rt, rows)))


# --------------------------------------------------------------------------- #
# MW Data grid → image (3 stacked blocks, FY groups side by side)
# --------------------------------------------------------------------------- #
def _mw_image(mw, *, font_px=19, header_px=17, gap=None, block_gap=None):
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
            cw, hlines = [], []
            for jc, (h, (k, typ)) in enumerate(zip(hdr, keys)):
                data_w = max([scratch.textlength(r[jc], font=reg) for r in body]
                             + [scratch.textlength(grow[jc], font=bold)], default=0)
                target = min(max(data_w, _px(30)), COL_CAP)
                lines = []
                for seg in str(h).split("\n"):
                    lines += _wrap(scratch, seg, hbold, target)
                hw = max(scratch.textlength(ln, font=hbold) for ln in lines)
                cw.append(int(max(target, hw)) + 2 * PAD_X)
                hlines.append(lines)
            specs.append(dict(fy=fy, keys=keys, body=body, grow=grow, cw=cw,
                              hlines=hlines, is_region=mw[fy]["type"] == "region"))

        title_h = hline_h + 2 * PAD_Y
        sub_h = max(max(len(l) for l in s["hlines"]) for s in specs) * hline_h + 2 * PAD_Y
        block_w = sum(sum(s["cw"]) for s in specs) + gap * (len(specs) - 1)
        block_h = title_h + sub_h + (12 + 1) * row_h
        img = Image.new("RGB", (block_w, block_h), WHITE)
        d = ImageDraw.Draw(img)

        x0 = 0
        for s in specs:
            gw = sum(s["cw"])
            # title band
            d.rectangle([x0, 0, x0 + gw, title_h], fill=MAROON)
            title = f"MONTHLY CONT SHEET FY {s['fy']}"
            tw = scratch.textlength(title, font=hbold)
            d.text((x0 + (gw - tw) / 2, (title_h - hline_h) / 2 + _px(1)), title,
                   font=hbold, fill=WHITE)
            # subheader (gold)
            d.rectangle([x0, title_h, x0 + gw, title_h + sub_h], fill=GOLD)
            x = x0
            for jc, lines in enumerate(s["hlines"]):
                ty = title_h + sub_h - PAD_Y - len(lines) * hline_h + _px(2)
                for ln in lines:
                    lw = scratch.textlength(ln, font=hbold)
                    d.text((x + (s["cw"][jc] - lw) / 2, ty), ln, font=hbold, fill=GOLD_TXT)
                    ty += hline_h
                x += s["cw"][jc]
            # body rows + grand
            y = title_h + sub_h
            for ri in range(13):
                is_grand = ri == 12
                cells = s["grow"] if is_grand else s["body"][ri]
                bg = (205, 232, 207) if is_grand else _ZEBRA[ri % 2]
                d.rectangle([x0, y, x0 + gw, y + row_h], fill=bg)
                x = x0
                for jc, (k, typ) in enumerate(s["keys"]):
                    val = cells[jc]
                    f = bold if is_grand else reg
                    if typ == "t":
                        d.text((x + PAD_X, y + PAD_Y), val, font=f, fill=DARK)
                    else:
                        tw = scratch.textlength(val, font=f)
                        d.text((x + s["cw"][jc] - PAD_X - tw, y + PAD_Y), val,
                               font=f, fill=DARK)
                    x += s["cw"][jc]
                d.line([x0, y + row_h, x0 + gw, y + row_h], fill=LINE)
                y += row_h
            d.rectangle([x0, 0, x0 + gw - 1, block_h - 1], outline=LINE)
            x0 += gw + gap
        return img

    blocks = [render_block(b) for b in _MW_BLOCKS]
    W = max(b.width for b in blocks)
    H = sum(b.height for b in blocks) + block_gap * (len(blocks) - 1)
    img = Image.new("RGB", (W, H), WHITE)
    y = 0
    for b in blocks:
        img.paste(b, (0, y))
        y += b.height + block_gap
    return img


# --------------------------------------------------------------------------- #
# Page composition — constant frame, uniform width
# --------------------------------------------------------------------------- #
def _compose(content, section, asof_label, page_no, total, page_w):
    """Place `content` onto a page of width `page_w`: constant maroon frame at a
    fixed inset, a section-header band, the content centred, and a footer."""
    reg, bold = _ft(21)
    tbig, _ = _ft(30)
    sml, smlb = _ft(18)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    page_h = MARGIN + FRAME + HEADER_H + content.height + PAD + FOOTER_H + FRAME + MARGIN
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
    right = "Peanuts Retail · Portfolio"
    rw = scratch.textlength(right, font=smlb)
    d.text((x1 - FRAME - PAD - rw, fy + _px(18)), right, font=smlb, fill=MAROON)
    return img


def _cover(page_w, asof, basis_label, scope_rows):
    reg, bold = _ft(26)
    big, _ = _ft(58)
    mid, _ = _ft(30)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_h = reg.getmetrics()[0] + reg.getmetrics()[1] + _px(22)
    # A proper page, not a wide banner: give it real height and centre the block.
    page_h = max(_px(880), MARGIN * 2 + _px(620))
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
    d.text((ix, y), "Peanuts Retail — Portfolio Report", font=big, fill=MAROON); y += _px(84)
    d.text((ix, y), "Whole portfolio · Growth / Degrowth pack", font=mid, fill=DARK); y += _px(54)
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
          "Sum of LY FULL SALES", "Sum of PROJECTED YTD"]
_PCT = ["Sum of GD_YTD_%", "Sum of GD_MTD_%"]
_AVG_MONEY = ["SBA", "CA", "Sum of YTD_LY", "Sum of YTD_TY", "Average of OPERATION",
              "Sum of AVG DAY SALE", "Sum of AVG MONTH SALE", "Sum of PSFPD"]


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


def build(pf, pf_all, asof, basis_label=""):
    """Compile the five portfolio sheets into one PDF (bytes), in dashboard
    order: MW Data, GD Sheet, Brand-wise GD, Loc-wise GD, Average.
    `pf` = filtered portfolio frame; `pf_all` = unfiltered (MW Data ignores
    filters, like the tab)."""
    import pandas as pd
    asof = pd.Timestamp(asof)
    asof_label = f"As of {asof:%d %b %Y}" + (f" · {basis_label}" if basis_label else "")

    with _LOCK:
        contents = []   # (section, content_image)

        # 1) MW Data (whole portfolio, unfiltered)
        contents.append(("MW Data — Monthly Contribution", _mw_image(mw_data(pf_all))))

        # 2) GD Sheet
        rep, rt = gd_sheet_report(pf, asof=asof)
        disp, money, pct = _prep_gd(rep)
        _add_sheet(contents, "GD Sheet — Growth / Degrowth", disp, rt,
                   money=money, pct=pct, sign=pct, money_dp=0)

        # 3) Brand-wise GD
        rep, rt = brand_wise_gd_report(pf, asof=asof)
        disp, money, pct = _prep_gd(rep)
        _add_sheet(contents, "Brand-wise Growth / Degrowth", disp, rt,
                   money=money, pct=pct, sign=pct, money_dp=0)

        # 4) Loc-wise GD
        rep, rt = loc_wise_gd_report(pf, asof=asof)
        disp, money, pct = _prep_gd(rep)
        _add_sheet(contents, "Location-wise Growth / Degrowth", disp, rt,
                   money=money, pct=pct, sign=pct, money_dp=0)

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

        # cover
        regions = ", ".join(sorted(pf["region"].dropna().unique())) if "region" in pf.columns else "—"
        cover_rows = [
            ("As of", f"{asof:%d %b %Y}"),
            ("Basis", basis_label or f"Live to {asof:%d %b %Y}"),
            ("Regions", regions or "—"),
            ("Sheets", "MW Data · GD Sheet · Brand-wise · Loc-wise · Average"),
            ("Generated", f"{pd.Timestamp.now(tz='Asia/Kolkata'):%d %b %Y, %H:%M} IST"),
        ]

        # uniform page width = widest content + frame + margins
        page_w = max(c.width for _, c in contents) + 2 * (MARGIN + FRAME + PAD)
        pages = [_cover(page_w, asof, basis_label, cover_rows)]
        total = len(contents) + 1
        for i, (section, content) in enumerate(contents, start=2):
            pages.append(_compose(content, section, asof_label, i, total, page_w))

        buf = io.BytesIO()
        pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:],
                      resolution=150.0 * _S)
        return buf.getvalue()
