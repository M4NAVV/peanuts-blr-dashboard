"""Target vs achievement — the month as bars, one per store (Manav, 13 Nov 2026).

"in new pages after all the current info, can u add bars like this for every store … city wise" — his choices:
MTD only, every store. Then: "revert to previous iteration, thats better … we want the city, then we want our
stores … siliguri, then manyavar, sevok road … and then after this graph data, we want another graph data, which is
brand wise, so, all the vfl stores like this" — two sets of pages: CITY-WISE (store = brand · location), then
PARENT COMPANY-WISE (VFL, RAL, SAB … as on page 2; store = city · location). No avg-per-day plot (his call).

★ EACH BAR IS SCALED TO ITS OWN MONTH TARGET (B = the same x for every store). Drawn in rupees, a 4 Cr store would
dwarf a 4 L one; scaled, every store reads the same way, the slab ticks line up in columns, and TODAY'S PACE is one
vertical line down the whole page — left of it is behind, right of it is ahead.

The four slabs come from the `Target Slabs` tab (slabs.py): C · B · A · SUPER A — for Nov 2026 it covers 48 of the 49
stores, every brand (C = 90% of B, A = 110%, SUPER A ≈ 143%). A store missing from the tab shows the B tick alone. A
store with no month target prints "no month target" instead of a bar — never a zero.

Colour (the same rule as page 1's red rows): green at or ahead of today's pace, red under 90% of it, amber between.
"""
from __future__ import annotations

import calendar

import pandas as pd
from PIL import Image, ImageDraw

import slabs as SL
from snapshots_a4 import _ft, _cr_l

INK, SOFT, FAINT = (22, 25, 30), (85, 91, 102), (150, 156, 166)
TRACK, RULE = (236, 236, 236), (214, 218, 224)
GREEN, AMBER, RED = (46, 125, 50), (214, 146, 40), (178, 34, 34)
HEAD_BG = (226, 239, 246)
SLAB_ORDER = ("C", "B", "A", "SUPER A")


def _pace(asof) -> tuple[float, int, int]:
    asof = pd.Timestamp(asof)
    days = calendar.monthrange(asof.year, asof.month)[1]
    return asof.day / days, asof.day, days


def _stores(sheet) -> list[dict]:
    asof = sheet["asof"]
    out = []
    for r in sheet["rows"]:
        b = r.get("mtd_target")
        s = SL.for_store(r["code"], asof) if b else {}
        # the bar measures against the TARGET SHEET's month target (what page 1 prints); the slab tab's other
        # slabs are drawn in proportion to its own B
        ratios = ({k: s[k] / s["B"] for k in SLAB_ORDER if s.get(k)} if s.get("B") else {"B": 1.0})
        out.append({"code": r["code"], "city": r["city"], "region": r["region"], "name": r["name"],
                    "brand": (r.get("brand") or "").title(), "principal": r.get("principal") or "(not in master)",
                    "sold": float(r["mtd"] or 0), "B": float(b) if b else None, "ratios": ratios, "slabs": bool(s)})
    return out


def _behind_first(st):
    st.sort(key=lambda x: (x["B"] is None, (x["sold"] / x["B"]) if x["B"] else 9))
    return st


def _brand_loc(x):
    return f"{x['brand']}  ·  {x['name']}" if x["brand"] else x["name"]


def _city_loc(x):
    c = x["city"].title()
    return c if x["name"].strip().lower() == c.lower() else f"{c}  ·  {x['name']}"   # "Agartala", not "Agartala · Agartala"


def groups_by_city(sheet) -> list[dict]:
    """City headers; each store labelled BRAND · LOCATION (Manav: "siliguri, then manyavar, sevok road")."""
    by = {}
    for x in _stores(sheet):
        by.setdefault((x["region"], x["city"]), []).append(x)
    out = [{"title": city, "tag": reg.upper(), "rows": _behind_first(st), "label": _brand_loc}
           for (reg, city), st in by.items()]
    out.sort(key=lambda g: (g["tag"], -sum(x["B"] or 0 for x in g["rows"])))
    return out


def groups_by_principal(sheet) -> list[dict]:
    """Parent-company headers, as on page 2 (store master PRINCIPAL), biggest first; stores labelled CITY · LOCATION."""
    by = {}
    for x in _stores(sheet):
        by.setdefault(x["principal"], []).append(x)
    out = []
    for p, st in by.items():
        brands = ", ".join(sorted({x["brand"] for x in st if x["brand"]}))
        out.append({"title": p, "tag": brands, "rows": _behind_first(st), "label": _city_loc})
    out.sort(key=lambda g: -sum(x["B"] or 0 for x in g["rows"]))
    return out


def _tone(share, pace):
    if share >= pace:
        return GREEN
    return RED if share < pace * 0.9 else AMBER


def render_pages(sheet, width: int, page_h: int, by: str = "city") -> list[Image.Image]:
    """The bar pages, each `width` × `page_h` (landscape). `by` = "city" | "principal"."""
    asof = pd.Timestamp(sheet["asof"])
    pace, day, days = _pace(asof)
    groups = groups_by_city(sheet) if by == "city" else groups_by_principal(sheet)
    what = "CITY-WISE" if by == "city" else "PARENT COMPANY-WISE"
    top = max([1.25] + [max(x["ratios"].values()) for g in groups for x in g["rows"] if x["B"]]) * 1.04

    fs = max(20, width // 120)
    reg, bold = _ft(fs)
    small, small_b = _ft(int(fs * .82))
    big, big_b = _ft(int(fs * 1.25))
    row_h = int(fs * 2.55)
    city_h = int(fs * 2.2)
    head_h = int(fs * 5.2)
    lab_w = int(width * 0.24)
    fig_w = int(width * 0.17)
    bx0, bx1 = lab_w + 16, width - fig_w - 16
    X = lambda ratio: bx0 + (bx1 - bx0) * min(max(ratio / top, 0), 1)

    def page_header(d, n, total):
        d.text((0, 0), f"TARGET vs ACHIEVEMENT  ·  MTD BARS, {what}  ·  {asof:%d %b %Y}"
                       + (f"  ·  page {n} of {total}" if total > 1 else ""), font=big_b, fill=INK)
        d.text((0, int(fs * 1.7)),
               f"Each bar is the store's month so far against its OWN month target (B), so every store reads on one scale. "
               f"Ticks: the slabs C · B · A · SUPER A (B alone if a store has none). The dashed line is today's pace: "
               f"day {day} of {days} = {pace * 100:.0f}% of B.", font=small, fill=SOFT)
        lx = 0
        for col, txt in ((GREEN, "at or ahead of pace"), (AMBER, "within 10% of pace"), (RED, "behind pace")):
            d.rectangle([lx, int(fs * 3.35), lx + fs, int(fs * 3.35) + int(fs * .7)], fill=col)
            d.text((lx + fs + 8, int(fs * 3.2)), txt, font=small, fill=SOFT)
            lx += fs + 20 + int(d.textlength(txt, font=small)) + 30

    def draw_bar(d, y, sold, B, ratios, label_l, label_sub, bold_row=False, fill_bg=None):
        if fill_bg:
            d.rectangle([0, y, width, y + row_h], fill=fill_bg)
        d.text((8, y + int(row_h * .04)), label_l, font=bold if bold_row else reg, fill=INK)
        if label_sub:
            d.text((8, y + int(row_h * .54)), label_sub, font=small, fill=SOFT)
        yb, hb = y + int(row_h * .26), int(row_h * .48)
        if not B:
            d.text((bx0, yb + 2), "no month target", font=small, fill=FAINT)
            return
        share = sold / B
        d.rectangle([bx0, yb, bx1, yb + hb], fill=TRACK)
        col = _tone(share, pace)
        xe = X(share)
        d.rectangle([bx0, yb, xe, yb + hb], fill=col)
        if share > top:                                   # ran off the scale: say so rather than clip silently
            d.polygon([(bx1 - 2, yb), (bx1 + 12, yb + hb // 2), (bx1 - 2, yb + hb)], fill=col)
        txt = _cr_l(sold)
        tw = d.textlength(txt, font=small_b)
        if xe - bx0 > tw + 16:
            d.text((bx0 + 8, yb + (hb - int(fs * .82)) // 2 - 2), txt, font=small_b, fill=(255, 255, 255))
        else:
            d.text((xe + 8, yb + (hb - int(fs * .82)) // 2 - 2), txt, font=small_b, fill=INK)
        for k in SLAB_ORDER:
            r = ratios.get(k)
            if not r:
                continue
            x = X(r)
            w = 4 if k == "B" else 2
            d.rectangle([x - w // 2, yb - 5, x + w // 2, yb + hb + 5], fill=INK)
        left = days - day
        need = B - sold
        d.text((bx1 + 24, y + int(row_h * .12)), f"{share * 100:,.1f}% of B", font=bold if bold_row else small_b,
               fill=col if col != AMBER else INK)
        d.text((bx1 + 24, y + int(row_h * .52)),
               ("B reached" if need <= 0 else f"needs {_cr_l(need / left)}/day" if left > 0 else f"short {_cr_l(need)}"),
               font=small, fill=SOFT)

    # blocks per group, then pages — a group stays whole unless it alone is taller than a page
    blocks = [(g, city_h + row_h * (len(g["rows"]) + (1 if len(g["rows"]) > 1 else 0)) + int(fs * .6)) for g in groups]
    body_h = page_h - head_h - int(fs * 2.4)
    pages, cur, used = [], [], 0
    for b in blocks:
        if cur and used + b[1] > body_h:
            pages.append(cur)
            cur, used = [], 0
        cur.append(b)
        used += b[1]
    if cur:
        pages.append(cur)
    # ★ balance (Manav, 13 Nov 2026: "half filled looks empty"): same page count, groups spread evenly
    if len(pages) > 1:
        n, total = len(pages), sum(b[1] for b in blocks)
        cap = max(body_h, max(sum(b[1] for b in pg) for pg in pages))
        best = None
        for k in range(60, 126, 2):
            share = total / n * k / 100
            bal, cur, used = [], [], 0
            for b in blocks:
                if cur and (used + b[1] > cap or (used >= share and len(bal) < n - 1)):
                    bal.append(cur)
                    cur, used = [], 0
                cur.append(b)
                used += b[1]
            bal.append(cur)
            if len(bal) != n:
                continue
            fills = [sum(b[1] for b in pg) for pg in bal]
            if best is None or max(fills) - min(fills) < best[0]:
                best = (max(fills) - min(fills), bal)
        if best:
            pages = best[1]

    out = []
    for n, blks in enumerate(pages, start=1):
        need_h = head_h + sum(b[1] for b in blks) + int(fs * 2.4)
        img = Image.new("RGB", (width, max(page_h, need_h)), (255, 255, 255))
        d = ImageDraw.Draw(img)
        page_header(d, n, len(pages))
        yl = head_h - int(fs * 1.2)
        for k in SLAB_ORDER:
            ratio = next((x["ratios"][k] for g, _ in blks for x in g["rows"] if k in x["ratios"]), None)
            if ratio:
                lab = f"{k} {ratio * 100:.0f}%"
                tw = d.textlength(lab, font=small_b if k == "B" else small)
                xl = X(ratio) - tw - 6 if k == "C" else X(ratio) + 6 if k == "A" else X(ratio) - tw / 2
                d.text((xl, yl), lab, font=small_b if k == "B" else small, fill=INK)
        y = head_h
        y_first = y
        for g, h in blks:
            st = g["rows"]
            d.rectangle([0, y, width, y + city_h - 6], fill=HEAD_BG)
            d.text((8, y + int(city_h * .16)),
                   f"{g['title']}  ·  {g['tag']}  ·  {len(st)} store{'s' if len(st) > 1 else ''}", font=bold, fill=INK)
            y += city_h
            for x in st:
                draw_bar(d, y, x["sold"], x["B"], x["ratios"], g["label"](x),
                         f"B {_cr_l(x['B'])}" if x["B"] else "")
                d.line([(0, y + row_h - 1), (width, y + row_h - 1)], fill=RULE)
                y += row_h
            if len(st) > 1:
                with_t = [x for x in st if x["B"]]
                b_c = sum(x["B"] for x in with_t)
                sold_c = sum(x["sold"] for x in with_t)
                # slab ticks on the total only when every store in it has slabs (a sum of slabs is then fair)
                allslab = all(x["slabs"] for x in with_t)
                rat = ({k: sum(x["ratios"][k] * x["B"] for x in with_t) / b_c for k in SLAB_ORDER}
                       if (allslab and b_c) else {"B": 1.0})
                draw_bar(d, y, sold_c, b_c or None, rat, f"{g['title']} TOTAL", f"B {_cr_l(b_c)}" if b_c else "",
                         bold_row=True, fill_bg=(246, 247, 249))
                y += row_h
            y += int(fs * .6)
        # today's pace: one dashed line down the page
        xp = X(pace)
        for yy in range(y_first, y - int(fs * .6), 10):
            d.line([(xp, yy), (xp, yy + 5)], fill=RED, width=2)
        lab = f"today's pace {pace * 100:.0f}%"
        tw = d.textlength(lab, font=small_b)
        d.text((xp - tw / 2, y - int(fs * .3)), lab, font=small_b, fill=RED)
        out.append(img)
    return out
