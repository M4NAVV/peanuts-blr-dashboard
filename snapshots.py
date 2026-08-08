"""Report → PNG, for the morning WhatsApp send.

Each snapshot is self-contained: a title saying what it is and as of when, the
summary cards, then the table. Someone reading it in a group chat has no
sidebar and no context, so anything they need to interpret the numbers has to
be inside the image.

Rendering reuses the report-PDF engine rather than a second implementation, so
a snapshot, its dashboard tab and its printed page are the same table in the
same palette. Crucially it also inherits that engine's rule: text is rasterised
ONCE at final size and the image is never resampled. Downscaling is what makes
a table look soft, and these are read by pinch-zooming on a phone, where
softness is exactly what hurts.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

import portfolio_pdf as PP

# Same fills as the tables, so the cards belong to the sheet rather than
# sitting on top of it.
CARD_BG = (255, 255, 255)
CARD_EDGE = PP.GRID
TITLE_INK = (0, 0, 0)
SUB_INK = (90, 90, 90)

PAD = 26                 # outer margin
CARD_GAP = 16
CARD_PAD_X, CARD_PAD_Y = 22, 18


def _cards_image(cards, width, label_px=22, value_px=44):
    """`cards` = [(label, value_text), …] laid out in one row across `width`."""
    if not cards:
        return None
    lab_f, _ = PP._ft(label_px)
    _, val_f = PP._ft(value_px)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    n = len(cards)
    cw = (width - CARD_GAP * (n - 1)) // n
    lab_h = lab_f.getmetrics()[0] + lab_f.getmetrics()[1]
    val_h = val_f.getmetrics()[0] + val_f.getmetrics()[1]
    ch = CARD_PAD_Y * 2 + lab_h + 8 + val_h

    img = Image.new("RGB", (width, ch), (255, 255, 255))
    d = ImageDraw.Draw(img)
    x = 0
    for label, value in cards:
        d.rectangle([x, 0, x + cw - 1, ch - 1], fill=CARD_BG, outline=CARD_EDGE,
                    width=1)
        d.text((x + CARD_PAD_X, CARD_PAD_Y), str(label), font=lab_f, fill=SUB_INK)
        # Negative headline figures pick up the same red the tables use.
        col = PP.NEG_INK if str(value).lstrip("₹ ").startswith("-") else TITLE_INK
        d.text((x + CARD_PAD_X, CARD_PAD_Y + lab_h + 8), str(value), font=val_f,
               fill=col)
        x += cw + CARD_GAP
    return img


def render(df, *, title, subtitle="", cards=(), money=(), pct=(), sign=(),
           row_types=None, row_bg=None, cell_rules=(), money_dp=0,
           font_px=32, header_px=28) -> bytes:
    """One report → PNG bytes."""
    m = PP._measure_table(df, money=money, pct=pct, sign=sign, money_dp=money_dp,
                          font_px=font_px, header_px=header_px)
    table = PP._render_chunk(m, row_types or ["store"] * len(df),
                             list(range(len(df))), row_bg=row_bg,
                             cell_rules=cell_rules)

    title_f, title_b = PP._ft(40)
    sub_f, _ = PP._ft(24)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    inner = max(table.width, 900)
    cards_img = _cards_image(cards, inner) if cards else None

    th = title_b.getmetrics()[0] + title_b.getmetrics()[1]
    sh = (sub_f.getmetrics()[0] + sub_f.getmetrics()[1] + 8) if subtitle else 0
    ch = (cards_img.height + 22) if cards_img is not None else 0
    H = PAD + th + 10 + sh + ch + table.height + PAD
    W = inner + PAD * 2

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    y = PAD
    d.text((PAD, y), title, font=title_b, fill=TITLE_INK)
    y += th + 10
    if subtitle:
        d.text((PAD, y), subtitle, font=sub_f, fill=SUB_INK)
        y += sh
    if cards_img is not None:
        img.paste(cards_img, (PAD, y))
        y += cards_img.height + 22
    img.paste(table, (PAD + (inner - table.width) // 2, y))

    buf = io.BytesIO()
    # No resampling anywhere in this path — see the module docstring.
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# The morning set
# --------------------------------------------------------------------------- #
# Filenames are date-first so a folder sorts chronologically, and carry the
# store code before the name so a manager's files group together.
def _slug(text):
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def store_wise(L, df, asof):
    """Store-wise MTD / YTD, year on year — both periods in one table."""
    rep, rtypes = L.region_store_report(df, asof=asof)
    money = [c for c in ("MTD LY", "MTD TY", "GD MTD Value", "Day Sales",
                         "YTD LY", "YTD TY", "GD YTD Value") if c in rep.columns]
    pct = [c for c in ("GD MTD %", "GD YTD %") if c in rep.columns]
    png = render(rep, title="VFL — Store-wise MTD / YTD, year on year",
                 subtitle=f"As of {asof:%d %b %Y} · all stores, unfiltered",
                 money=money, pct=pct,
                 sign=pct + [c for c in ("GD MTD Value", "GD YTD Value")
                             if c in rep.columns],
                 row_types=rtypes)
    return f"{asof:%Y-%m-%d}_vfl_store-wise-mtd-ytd.png", png


def degrowth_region(L, df, asof, kind, region):
    """The degrowth watchlist for one region and one period."""
    dg = L.degrowth_report(df, asof=asof, kind=kind)
    dg = dg[dg["region"] == region]
    if dg.empty:
        return None
    tot, ly = dg["shortfall"].sum(), dg["prior"].sum()
    disp = dg.copy()
    disp.insert(0, "DATE", f"{asof:%d-%m-%Y}")
    disp = disp.rename(columns={
        "region": "Region", "code": "STORE CODE", "location": "LOCATION",
        "prior": f"{kind} LY", "cur": f"{kind} TY",
        "shortfall": "Shortfall", "growth": "Degrowth %"})
    disp["STORE CODE"] = disp["STORE CODE"].astype(int)
    png = render(
        disp, title=f"VFL — Degrowth watchlist · {region} · {kind}",
        subtitle=f"Stores where {kind} this year < last year · "
                 f"as of {asof:%d %b %Y} · unfiltered",
        cards=[("Stores degrowing", f"{len(dg)}"),
               ("Total shortfall", f"₹{tot / 1e5:,.2f} L"),
               ("Degrowth %", f"{tot / ly * 100:,.2f}%" if ly else "—")],
        money=[f"{kind} LY", f"{kind} TY", "Shortfall"], pct=["Degrowth %"],
        sign=["Shortfall", "Degrowth %"])
    return f"{asof:%Y-%m-%d}_vfl_degrowth_{_slug(region)}_{kind}.png", png


def drivers_store(L, df, asof, kind, store, code=None):
    """One store's full brand-and-product breakdown — sent to that manager.

    Every store gets one, not just the declining, so a good month reads as a
    good month rather than the manager receiving nothing.
    """
    drv, types = L.degrowth_drivers(
        df, asof=asof, kind=kind, only_declining=False, stores_only=[store],
        products_under="every", top_products=6, level="division")
    if drv.empty:
        return None
    tot = float(drv.loc[[t == "block" for t in types], "Shortfall"].sum())
    ly = float(drv.loc[[t == "block" for t in types], f"{kind} LY"].sum())
    png = render(
        drv, title=f"{store} — {kind} performance drivers",
        subtitle=f"Where the movement comes from, by brand and product · "
                 f"as of {asof:%d %b %Y}",
        cards=[("Movement", f"₹{tot / 1e5:,.2f} L"),
               (f"{kind} vs last year", f"{tot / ly * 100:,.2f}%" if ly else "—"),
               ("Lines shown", f"{sum(1 for t in types if t == 'store')}")],
        money=L.drivers_money(kind), pct=L.DRIVERS_PCT,
        sign=["Shortfall"] + L.DRIVERS_PCT, row_types=types)
    tag = f"{code}_" if code is not None else ""
    return f"{asof:%Y-%m-%d}_{tag}{_slug(store)}_drivers_{kind}.png", png
