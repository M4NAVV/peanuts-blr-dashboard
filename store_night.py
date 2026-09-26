"""The store's night report — one page a store, the way the stores keep it.

Manav, 26 Sep 2026, with a photograph of Grand Kamraj's own workbook: *"every
night something like this is made … from this data that we get from the forms
every night, a report like this needs to be made by us, and then will be
forwarded to admin."*

His sheet holds about sixty cells across three colours. Everything on it is
here, in a shape that can be read: the FIGURES, then the GROWTH, then the
BRAND SPLIT, each as its own table.

★★ ONE KIND OF NUMBER PER COLUMN — which is why this is three tables and not
one. Rupees, counts, ratios and percentages cannot share a column: a column is
formatted once, for every row in it. Laying the measures ACROSS and the periods
DOWN is what makes each column internally consistent, and it is also how a
reader compares a day with a month without moving their eyes twice.
See [[feedback-declare-numeric-columns]].

★★ THE YEAR RUNS FROM THE TAKEOVER, NOT FROM 1 APRIL (Manav, 26 Sep: *"the ytd
rule will be from 19th april, which is our takeover date"*). The store master
already carries 19-04-2026 for all eight Bengaluru stores and the dashboard is
already anchored that way, which is why this reproduces his own YTD to ₹753 on
a ₹12.3 crore figure. A plain 1-April year would read ₹14.01 crore and every
growth on the page would be wrong.

★ CONVERSION IS PAIRED DAY FOR DAY. Footfall is counted by hand and is missing
on some days, so bills are taken over the days footfall was ALSO counted. A
month of bills over a fortnight of footfall is the error that once printed a
380% conversion. The page says how many days were counted.
See [[feedback-aggregate-ratios-in-pairs]].
"""
from __future__ import annotations

import pandas as pd

import loader as L

BRANDS = (("MANYAVAR", "Manyavar"), ("MOHEY", "Mohey"), ("TWAMEV", "Twamev"))
_FOLD = {"MANYAVAR": "MANYAVAR", "MOHEY": "MOHEY",
         "TWAMEV MEN": "TWAMEV", "TWAMEV-WOMEN": "TWAMEV"}

# measure -> (label, kind). One kind per column, by construction.
FIGURE_SPEC = [("period", "text", "PERIOD"),
               ("sales", "rupee", "SALES"),
               ("manyavar", "rupee", "MANYAVAR"),
               ("mohey", "rupee", "MOHEY"),
               ("twamev", "rupee", "TWAMEV"),
               ("bills", "int", "BILLS"),
               ("qty", "int", "QTY"),
               ("footfall", "int", "FOOTFALL"),
               ("abv", "rupee", "ABV"),
               ("abs", "num", "ABS"),
               ("asp", "rupee", "ASP"),
               ("conv", "pct", "CONV %")]
GROWTH_SPEC = [("period", "text", "GROWTH ON LAST YEAR")] + [
    (k, "gd", h) for k, _t, h in FIGURE_SPEC[1:]]
# ★ SHARE AND PIECES TOGETHER. His own sheet carries brand quantities beside
# the contribution percentages, and the two answer different questions: what a
# brand is worth, and how much of it walked out of the door.
SHARE_SPEC = ([("period", "text", "BRAND SPLIT")]
              + [(k, "pct", f"{h}\n% OF SALE") for k, _t, h in FIGURE_SPEC[2:5]]
              + [(f"{k}_qty", "int", f"{h}\nPIECES")
                 for k, _t, h in FIGURE_SPEC[2:5]])


def windows(asof, takeover=None) -> list:
    """[(label, start, end)] — the day, the month, and the year from takeover."""
    asof = pd.Timestamp(asof).normalize()
    fy = asof.year if asof.month >= 4 else asof.year - 1
    year_start = pd.Timestamp(fy, 4, 1)
    if takeover is not None and pd.notna(takeover):
        t = pd.Timestamp(takeover).normalize()
        if t > year_start:
            year_start = t
    return [("Day", asof, asof),
            ("Month", asof.replace(day=1), asof),
            ("Year", year_start, asof)]


def _rate(top, bottom):
    return float(top) / float(bottom) if bottom else None


def measure(bills_df, foot: dict, lo, hi) -> dict:
    """Every figure on the page, for one window of one store."""
    x = bills_df[(bills_df["date"] >= lo) & (bills_df["date"] <= hi)]
    sales = float(x[L.COL_AMOUNT].sum())
    qty = float(L.unit_delta(x).sum()) if len(x) else 0.0
    bills = float(L.bill_count(x)) if len(x) else 0.0
    out = {"sales": sales, "qty": qty, "bills": bills}
    for key, _label in BRANDS:
        b = x[x["_b"] == key] if len(x) else x
        out[key.lower()] = float(b[L.COL_AMOUNT].sum()) if len(b) else 0.0
        out[f"{key.lower()}_qty"] = (float(L.unit_delta(b).sum())
                                     if len(b) else 0.0)

    # ★ Footfall is counted by hand, so the window is only the days it exists,
    # and BILLS FOR CONVERSION are taken over those same days.
    days = [d for d in foot if lo <= d <= hi]
    out["footfall"] = float(sum(foot[d] for d in days)) if days else None
    out["_foot_days"] = len(days)
    out["_span_days"] = int((hi - lo).days) + 1
    if days and len(x):
        paired = x[x["date"].isin(days)]
        pb = float(L.bill_count(paired))
        out["conv"] = _rate(pb, out["footfall"])
        out["conv"] = out["conv"] * 100 if out["conv"] is not None else None
    else:
        out["conv"] = None

    out["abv"] = _rate(sales, bills)
    out["abs"] = _rate(qty, bills)
    out["asp"] = _rate(sales, qty)
    return out


def growth(ty: dict, ly: dict) -> dict:
    """★ A GROWTH AGAINST NOTHING IS NOT A GROWTH. Blank, never 100%."""
    out = {}
    for k in ("sales", "manyavar", "mohey", "twamev", "bills", "qty",
              "footfall", "abv", "abs", "asp", "conv"):
        a, b = ty.get(k), ly.get(k)
        out[k] = ((a - b) / b * 100) if (a is not None and b) else None
    return out


def share(m: dict) -> dict:
    s = m.get("sales") or 0
    out = {}
    for k, _l in BRANDS:
        out[k.lower()] = m[k.lower()] / s * 100 if s else None
        out[f"{k.lower()}_qty"] = m.get(f"{k.lower()}_qty")
    return out


def figures(df, pf, store_label, asof, code=None) -> dict:
    """Everything the page needs: rows for each table, plus the context line."""
    import snapshots as SN
    asof = pd.Timestamp(asof).normalize()
    d = df[df[L.COL_STORE_LABEL] == store_label].copy()
    d["_b"] = L.brand_line_vfl(d).map(_FOLD)

    master = L.load_store_master()
    row = master[master["tableau_name"] == store_label]
    code = int(row["code"].iloc[0]) if len(row) and code is None else code
    takeover = row["takeover_date"].iloc[0] if len(row) else None
    area = pd.to_numeric(row["ca"], errors="coerce").iloc[0] if len(row) else None

    ff = SN.footfall_map(pf) if pf is not None else {}
    foot = {pd.Timestamp(dt).normalize(): v
            for (c, dt), v in ff.items() if code is not None and int(c) == code}

    ly = pd.DateOffset(years=1)
    figs, grows, shares, notes = [], [], [], []
    for label, lo, hi in windows(asof, takeover):
        ty = measure(d, foot, lo, hi)
        pri = measure(d, foot, lo - ly, hi - ly)
        figs.append({"period": f"{label}  ·  this year", **ty})
        figs.append({"period": f"{label}  ·  last year", **pri})
        grows.append({"period": label, **growth(ty, pri)})
        shares.append({"period": label, **share(ty)})
        if ty["_foot_days"] < ty["_span_days"]:
            notes.append(f"{label.lower()}: footfall counted on "
                         f"{ty['_foot_days']} of {ty['_span_days']} days")
    full = measure(d, foot, pd.Timestamp(asof.year - 1, 4, 1),
                   pd.Timestamp(asof.year, 3, 31)) if asof.month >= 4 else None
    return {"rows": figs, "growth": grows, "share": shares, "last_full": full,
            "code": code, "takeover": takeover, "area": area,
            "foot_notes": notes,
            "day": figs[0], "month": figs[2], "year": figs[4]}


# --------------------------------------------------------------------------- #
#  The page — his own sheet's shape
# --------------------------------------------------------------------------- #
# Manav, 26 Sep: *"stick to a similar format of the image i gave you, we will
# work on making it better afterwards."* So this is his workbook: three columns
# of label-and-value, colour-banded by period, with the averages and the
# conversion grid on the right. The figures are ours and the arrangement is
# his — which is the right way round for a report somebody already reads every
# night.
BAND = {
    "title": ((255, 242, 0), (0, 0, 0), True),
    "day": ((0, 176, 240), (0, 0, 0), True),
    "mtd": ((252, 213, 180), (0, 0, 0), False),
    "mtdh": ((247, 150, 70), (0, 0, 0), True),
    "ytd": ((216, 228, 188), (0, 0, 0), False),
    "ytdh": ((146, 208, 80), (0, 0, 0), True),
    "sub": ((220, 230, 241), (0, 0, 0), False),
    "plain": ((255, 255, 255), (0, 0, 0), False),
    "red": ((255, 255, 255), (192, 0, 0), False),
}


def _pairs(width, rows, font_px=26):
    """A column of `(label, value, band)` — his sheet's basic unit."""
    from PIL import Image, ImageDraw
    import portfolio_pdf as PP
    reg, bold = PP._ft(font_px)
    pad = PP._px(10)
    rh = int((reg.getmetrics()[0] + reg.getmetrics()[1]) + pad * 2)
    img = Image.new("RGB", (width, rh * len(rows)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    lw = int(width * 0.56)
    for i, (label, value, band) in enumerate(rows):
        fill, ink, strong = BAND.get(band, BAND["plain"])
        y = i * rh
        d.rectangle([0, y, width, y + rh], fill=fill, outline=(170, 170, 170))
        d.line([(lw, y), (lw, y + rh)], fill=(170, 170, 170))
        f = bold if strong else reg
        d.text((pad, y + pad), str(label), font=f, fill=ink)
        if value != "":
            t = str(value)
            d.text((width - pad - d.textlength(t, font=f), y + pad), t,
                   font=f, fill=ink)
    return img


def _r(v, dp=0):
    import portfolio_pdf as PP
    return "—" if v is None else PP._fmt_in(v, dp)


def _p(v, dp=0):
    return "—" if v is None else f"{v:,.{dp}f}%"


def month_target(code, asof):
    """September's target for this store, from the `Targets New` tab.

    ★ THE TARGET EXISTS EVEN THOUGH HIS SHEET LEAVES THE CELL BLANK — 2.50 Cr
    for Grand Kamraj this September, off the same tab the dashboard reads. A
    row that is always empty teaches a reader to stop looking at it.
    """
    try:
        import targets as T
        t = T.load()
    except Exception:
        return None
    if t is None:
        return None
    asof = pd.Timestamp(asof)
    col = asof.strftime("%b")
    row = t[t["code"].astype(str) == str(int(code))]
    if not len(row) or col not in t.columns:
        return None
    v = pd.to_numeric(row[col], errors="coerce").dropna()
    return float(v.iloc[0]) if len(v) else None


def day_target(pf, code, asof):
    """The night fill's own Day Target for this store, if one was typed."""
    if pf is None or "Day Target" not in getattr(pf, "columns", []):
        return None
    x = pf[(pf["code"] == code) & (pf["date"] == pd.Timestamp(asof).normalize())]
    if not len(x):
        return None
    v = pd.to_numeric(x["Day Target"].astype(str).str.replace(",", ""),
                      errors="coerce").dropna()
    return float(v.iloc[0]) if len(v) else None


def build(df, pf, store_label, asof, code=None) -> tuple:
    """(filename, pdf bytes, page count) — one store, one night, his layout."""
    import festive_admin as FADM
    import portfolio_pdf as PP
    import snapshots_a4 as A4

    asof = pd.Timestamp(asof).normalize()
    f = figures(df, pf, store_label, asof, code)
    code = f["code"]
    rows = f["rows"]
    day, day_ly = rows[0], rows[1]
    mtd, mtd_ly = rows[2], rows[3]
    ytd, ytd_ly = rows[4], rows[5]
    g_day, g_mtd, g_ytd = f["growth"]
    s_mtd, s_ytd = f["share"][1], f["share"][2]
    lf = f.get("last_full") or {}
    tgt = day_target(pf, code, asof)
    mtgt = month_target(code, asof)

    _keep = (A4.MARGIN, A4.CONTENT_W, PP.PAD_Y)
    A4.MARGIN = A4.PRINT_MARGIN
    A4.CONTENT_W = A4.PAGE_W - 2 * A4.MARGIN
    try:
        W = A4.CONTENT_W
        gap = PP._px(26)
        cw = (W - 2 * gap) // 3

        left = [(f"PEANUTS RETAIL — {store_label.upper()}", "", "title"),
                ("Date", f"{asof:%d-%m-%Y}", "plain"),
                ("Month Target", _r(mtgt), "plain"),
                ("MTD Achieved", _p(mtd["sales"] / mtgt * 100)
                 if mtgt else "—", "plain"),
                ("Day Target", _r(tgt), "plain"),
                ("Day Achieved", _p(day["sales"] / tgt * 100)
                 if tgt else "—", "plain"),
                ("DAY SALE", _r(day["sales"]), "day"),
                ("MANYAVAR DAY SALE", _r(day["manyavar"]), "day"),
                ("MOHEY DAY SALE", _r(day["mohey"]), "day"),
                ("TWAMEV DAY SALE", _r(day["twamev"]), "day"),
                ("ABS  (Average Basket Size)", _r(day["abs"], 2), "day"),
                ("ABV  (Average Bill Value)", _r(day["abv"]), "day"),
                ("ASP  (Average Selling Price)", _r(day["asp"]), "day"),
                ("TY MTD SALE", _r(mtd["sales"]), "mtdh"),
                ("LY MTD SALE", _r(mtd_ly["sales"]), "mtd"),
                ("MTD GROWTH", _p(g_mtd["sales"]), "mtdh"),
                ("TY MANYAVAR MTD", _r(mtd["manyavar"]), "mtd"),
                ("LY MANYAVAR MTD", _r(mtd_ly["manyavar"]), "mtd"),
                ("MANYAVAR GROWTH", _p(g_mtd["manyavar"]), "mtdh"),
                ("TY MOHEY MTD", _r(mtd["mohey"]), "mtd"),
                ("LY MOHEY MTD", _r(mtd_ly["mohey"]), "mtd"),
                ("MOHEY GROWTH", _p(g_mtd["mohey"]), "mtdh"),
                ("TY TWAMEV MTD", _r(mtd["twamev"]), "mtd"),
                ("LY TWAMEV MTD", _r(mtd_ly["twamev"]), "mtd"),
                ("TWAMEV GROWTH", _p(g_mtd["twamev"]), "mtdh"),
                ("TY MTD ABS", _r(mtd["abs"], 2), "mtd"),
                ("LY MTD ABS", _r(mtd_ly["abs"], 2), "mtd"),
                ("TY MTD ABV", _r(mtd["abv"]), "mtd"),
                ("LY MTD ABV", _r(mtd_ly["abv"]), "mtd"),
                ("TY MTD ASP", _r(mtd["asp"]), "mtd"),
                ("LY MTD ASP", _r(mtd_ly["asp"]), "mtd")]

        ty = pd.Timestamp(f["takeover"]) if pd.notna(f["takeover"]) else None
        mid = [("CA IN SQFT", _r(f["area"]), "title"),
               ("SALES PER SQ FT  (day)",
                _r(day["sales"] / f["area"]) if f["area"] else "—", "plain"),
               (f"TY YTD  (from {ty:%d-%m-%Y})" if ty is not None else "TY YTD",
                _r(ytd["sales"]), "ytdh"),
               ("LY YTD", _r(ytd_ly["sales"]), "ytd"),
               ("YTD GROWTH", _p(g_ytd["sales"]), "ytdh"),
               ("TY MANYAVAR YTD", _r(ytd["manyavar"]), "ytd"),
               ("LY MANYAVAR YTD", _r(ytd_ly["manyavar"]), "ytd"),
               ("MANYAVAR GROWTH", _p(g_ytd["manyavar"]), "ytdh"),
               ("TY MOHEY YTD", _r(ytd["mohey"]), "ytd"),
               ("LY MOHEY YTD", _r(ytd_ly["mohey"]), "ytd"),
               ("MOHEY GROWTH", _p(g_ytd["mohey"]), "ytdh"),
               ("TY TWAMEV YTD", _r(ytd["twamev"]), "ytd"),
               ("LY TWAMEV YTD", _r(ytd_ly["twamev"]), "ytd"),
               ("TWAMEV GROWTH", _p(g_ytd["twamev"]), "ytdh"),
               ("TY QTY SOLD", _r(ytd["qty"]), "ytd"),
               ("LY QTY SOLD", _r(ytd_ly["qty"]), "ytd"),
               ("TY ABS", _r(ytd["abs"], 2), "ytd"),
               ("LY ABS", _r(ytd_ly["abs"], 2), "ytd"),
               ("TY ABV", _r(ytd["abv"]), "ytd"),
               ("LY ABV", _r(ytd_ly["abv"]), "ytd"),
               ("TY ASP", _r(ytd["asp"]), "ytd"),
               ("LY ASP", _r(ytd_ly["asp"]), "ytd"),
               ("BRAND CONTRIBUTION %", "", "title"),
               ("MANYAVAR (MTD)", _p(s_mtd["manyavar"], 2), "mtd"),
               ("MOHEY (MTD)", _p(s_mtd["mohey"], 2), "mtd"),
               ("TWAMEV (MTD)", _p(s_mtd["twamev"], 2), "mtd"),
               ("MANYAVAR (YTD)", _p(s_ytd["manyavar"], 2), "ytd"),
               ("MOHEY (YTD)", _p(s_ytd["mohey"], 2), "ytd")]
        mid.append(("TWAMEV (YTD)", _p(s_ytd["twamev"], 2), "ytd"))

        right = [("BRAND QUANTITIES", "", "title"),
                 ("MANYAVAR MTD QTY", _r(mtd["manyavar_qty"]), "mtd"),
                 ("MOHEY MTD QTY", _r(mtd["mohey_qty"]), "mtd"),
                 ("TWAMEV MTD QTY", _r(mtd["twamev_qty"]), "mtd"),
                 ("MANYAVAR YTD QTY", _r(ytd["manyavar_qty"]), "ytd"),
                 ("MOHEY YTD QTY", _r(ytd["mohey_qty"]), "ytd"),
                 ("TWAMEV YTD QTY", _r(ytd["twamev_qty"]), "ytd"),
                 ("LAST FULL YEAR  (Apr 25 – Mar 26)", "", "title"),
                 ("MANYAVAR", _r(lf.get("manyavar")), "plain"),
                 ("MOHEY", _r(lf.get("mohey")), "plain"),
                 ("TWAMEV", _r(lf.get("twamev")), "plain"),
                 ("TOTAL SALE", _r(lf.get("sales")), "title")]

        sheet = A4._Sheet(store_label, asof, "", bounded=False, footer=True)
        sheet.put(_pairs(W, [(f"PEANUTS RETAIL — {store_label.upper()}  ·  "
                              f"NIGHT REPORT  ·  {asof:%d-%m-%Y}", "",
                              "title")], font_px=30), gap=14)
        cols = [_pairs(cw, left[1:]), _pairs(cw, mid), _pairs(cw, right)]
        sheet.put(_beside(cols, gap), gap=20)

        # The averages and the conversion grid, as his sheet lays them out.
        def per_day(m):
            # ★ EACH AVERAGE OVER ITS OWN DENOMINATOR. Bills and pieces are
            # counted every day; footfall is not, so it is divided by the days
            # it was actually counted on. One shared denominator would quietly
            # understate footfall by the days nobody wrote it down.
            n = max(1, m["_span_days"])
            return {"days": n, "bills": m["bills"] / n, "qty": m["qty"] / n,
                    "foot": (m["footfall"] / m["_foot_days"]
                             if m["_foot_days"] else None),
                    "fdays": m["_foot_days"]}
        avg_rows = [{"w": "Day", **per_day(day)}, {"w": "MTD", **per_day(mtd)},
                    {"w": "YTD", **per_day(ytd)}]
        AVG = [("w", "text", "AVERAGE PER DAY"), ("days", "int", "DAYS"),
               ("bills", "num1", "BILLS"), ("qty", "num1", "PIECES"),
               ("foot", "num1", "FOOTFALL"),
               ("fdays", "int", "DAYS\nCOUNTED")]
        conv_rows = []
        for label, a, b in (("Day", day, day_ly), ("MTD", mtd, mtd_ly),
                            ("YTD", ytd, ytd_ly)):
            conv_rows.append({"w": label, "bills": a["bills"], "qty": a["qty"],
                              "foot": a["footfall"], "conv": a["conv"],
                              "lbills": b["bills"], "lqty": b["qty"],
                              "lfoot": b["footfall"], "lconv": b["conv"]})
        CONV = [("w", "text", "STORE CONVERSION"),
                ("bills", "int", "BILL"), ("qty", "int", "QTY"),
                ("foot", "int", "FOOT\nFALL"), ("conv", "pct", "CONV %"),
                ("lbills", "int", "LY\nBILL"), ("lqty", "int", "LY\nQTY"),
                ("lfoot", "int", "LY\nFOOT"), ("lconv", "pct", "LY\nCONV %")]
        two = _beside([FADM.table_image(avg_rows, AVG, int(cw * 1.15),
                                        font_px=25, fill=False),
                       FADM.table_image(conv_rows, CONV, int(cw * 1.7),
                                        font_px=25, fill=False)], gap)
        sheet.put(two, gap=16)

        said = []
        if f["foot_notes"]:
            said.append("Footfall is counted by hand, so conversion is taken "
                        "over the days it was counted and the bills of those "
                        "same days — " + "; ".join(f["foot_notes"]) + ".")
        if ytd_ly.get("footfall") is None:
            said.append("Last year has no footfall on record, so no "
                        "conversion can be compared to it.")
        if said:
            sheet.put(A4._text_block(
                W, [(" ".join(said), A4._ft(21)[0], A4.SUB)]), gap=10)
        sheet._footers()
        out = sheet.pdf()
        pages = len(sheet.pages)
    finally:
        A4.MARGIN, A4.CONTENT_W, PP.PAD_Y = _keep
    import snapshots as SN
    return (f"{asof:%Y-%m-%d}_{code}_{SN._slug(store_label)}_night.pdf",
            out, pages)


def _beside(images, gap):
    """Panels across the page, top-aligned — his sheet's three columns."""
    from PIL import Image
    w = sum(i.width for i in images) + gap * (len(images) - 1)
    h = max(i.height for i in images)
    out = Image.new("RGB", (w, h), (255, 255, 255))
    x = 0
    for i in images:
        out.paste(i, (x, 0))
        x += i.width + gap
    return out
