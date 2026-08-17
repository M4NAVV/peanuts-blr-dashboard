"""VFL WOMEN'S DISCOUNT REPORT — how discounted merchandise is performing.

Manav, 17 Aug: a summary page mapping both quantity and value, store-wise and
day-wise sheets after it, Mohey & Manyavar stores only, brand-wise fresh and
discount sales with each one's contribution to total women's sales.

WOMEN'S ONLY, AND WHY THAT IS THE WHOLE REPORT
Menswear carries no promotions at all — `Promotion Amount` has never been
written against a MANYAVAR line (nought of 227,803) nor a TWAMEV MEN one. It is
only ever populated for MOHEY and TWAMEV-WOMEN. So a discount report on the men's
lines could only ever print zero, and this one covers the two brands that can
actually answer the question.

★★ WHAT THIS REPORT DOES NOT CLAIM, AND WHY. It does not show a discount DEPTH —
no "30% off" anywhere — because the feed cannot support one. There is no MRP
column, and since June every promotional line carries a `Promotion Amount`
exactly equal to its `Bill Amount`: 965 rows in June, 1,025 in July, 549 in
August, all at a ratio of 1.00. Earlier months held ratios of 1.5 and 1.86 (an
item at 12,999 sold for 7,000) which did carry depth, but that stopped. So the
field is read as a FLAG — this line was sold under a promotion — which is
exactly how Manav's own Mohey Jayanagar sheet reads it, and that sheet
reconciles to the unit.

What the data DOES support, and what this reports:
  * how much of women's trade is discounted, in value AND units
  * what it is doing to the achieved price — discounted pieces sell at Rs 5,119
    against Rs 8,523 fresh, which is the finding depth would have told us
  * which brand, which store, which day
"""

from __future__ import annotations

import pandas as pd

from report_td import (_LOCK, _draw_grid, _money, _pdf_from, _px, _stack,
                       cell, HDR_BG, ROW_H, TOTAL_BG, NEG_INK, INK)

# The two women's brand lines, in the order they are reported.
BRANDS = ("MOHEY", "TWAMEV-WOMEN")
BRAND_LABEL = {"MOHEY": "MOHEY", "TWAMEV-WOMEN": "TWAMEV WOMEN"}

# ★ BRAND MARKING. Each brand owns a colour across its columns, so a reader
# finds Mohey's numbers without reading a heading. Rose for Mohey and sand for
# Twamev sit either side of the pack's pale blue, which is kept for the totals —
# the palette stays the workbook's, only the assignment is new.
BRAND_BG = {"MOHEY": (245, 225, 231), "TWAMEV-WOMEN": (242, 233, 216)}
BRAND_INK = {"MOHEY": (122, 31, 43), "TWAMEV-WOMEN": (107, 84, 36)}
TOTAL_TINT = HDR_BG
GREY = (120, 120, 120)


# --------------------------------------------------------------------------- #
# The numbers
# --------------------------------------------------------------------------- #
def womens(vdf: pd.DataFrame) -> pd.DataFrame:
    """Every women's line, typed, with the promotion read as a flag."""
    import loader as L
    d = vdf.copy()
    d["_line"] = L.brand_line_vfl(d).astype(str).str.upper()
    d = d[d["_line"].isin(BRANDS)].copy()
    d["_val"] = pd.to_numeric(d[L.COL_AMOUNT], errors="coerce").fillna(0.0)
    d["_qty"] = pd.to_numeric(d[L.COL_QTY], errors="coerce").fillna(0.0)
    d["_disc"] = pd.to_numeric(d[L.COL_PROMO], errors="coerce").fillna(0) > 0
    return d


def mohey_stores(asof=None) -> dict:
    """{store label: (code, region)} for the Mohey & Manyavar stores only.

    Read from the curated store attributes rather than from whoever happens to
    have sold a Mohey saree this month: the report is about a defined estate,
    and a store that sold none is a finding, not an absence.
    """
    import loader as L
    import portfolio_loader as PL
    attrs = PL.gd_store_attrs()
    codes = {int(r["code"]): str(r["region"]) for _, r in attrs.iterrows()
             if "MOHEY" in str(r["store_name_main"]).upper()}
    m = L.load_store_master()
    out = {}
    for name, code, region in zip(m["tableau_name"], m["code"], m["region"]):
        if pd.notna(code) and int(code) in codes:
            out[str(name)] = (int(code), str(region))
    return out


def _cut(part) -> dict:
    """Fresh and discount, value and quantity, for one slice."""
    d, f = part[part["_disc"]], part[~part["_disc"]]
    return {
        "disc_val": float(d["_val"].sum()), "disc_qty": float(d["_qty"].sum()),
        "fresh_val": float(f["_val"].sum()), "fresh_qty": float(f["_qty"].sum()),
        "val": float(part["_val"].sum()), "qty": float(part["_qty"].sum()),
    }


def brand_rows(w: pd.DataFrame) -> list:
    """One row per women's brand, plus the total they contribute to."""
    total = _cut(w)
    rows = []
    for b in BRANDS:
        r = _cut(w[w["_line"] == b])
        r["brand"] = b
        rows.append(r)
    total["brand"] = "TOTAL"
    rows.append(total)
    return rows


def ever_recorded(vdf: pd.DataFrame) -> dict:
    """{store: has a promotion EVER reached us from it}.

    ★ Asked of the whole feed, not the month. Four of these stores have never
    sent a Promotion Amount in any month — Fairfield across 4,938 Mohey lines —
    so their 0.0% is not a zero, it is a silence. Agartala and Malda DO record
    them and simply ran none in August, which is a real zero and reads as one.
    """
    import loader as L
    p = pd.to_numeric(vdf[L.COL_PROMO], errors="coerce").fillna(0) > 0
    return {str(k): bool(v) for k, v in
            p.groupby(vdf[L.COL_STORE_LABEL].astype(str)).any().items()}


def store_rows(w: pd.DataFrame, stores: dict, records: dict | None = None) -> list:
    """One row per Mohey store, brand by brand, biggest women's trade first."""
    import loader as L
    records = records or {}
    rows = []
    for label, (code, region) in stores.items():
        part = w[w[L.COL_STORE_LABEL].astype(str) == label]
        r = {"store": label, "code": code, "region": region,
             "traded": bool(len(part)),
             "records": records.get(label, True), **_cut(part)}
        for b in BRANDS:
            r[b] = _cut(part[part["_line"] == b])
        rows.append(r)
    rows.sort(key=lambda r: -r["val"])
    return rows


def day_rows(w: pd.DataFrame, label: str, asof) -> list:
    """A day per row for one store, every day of the month present or not."""
    import loader as L
    asof = pd.Timestamp(asof)
    part = w[w[L.COL_STORE_LABEL].astype(str) == label]
    days = pd.date_range(asof.replace(day=1),
                         asof.replace(day=1) + pd.offsets.MonthEnd(0), freq="D")
    out = []
    for day in days:
        one = part[part["date"] == day]
        r = {"date": day, "future": day > asof, **_cut(one)}
        for b in BRANDS:
            r[b] = _cut(one[one["_line"] == b])
        out.append(r)
    return out


# --------------------------------------------------------------------------- #
# The look
# --------------------------------------------------------------------------- #
def _pc(part, whole):
    return f"{part / whole * 100:,.1f}%" if whole else "—"


def _band_and_head(first_label, tail_labels, per_brand=("Fresh Sale", "Qty",
                                                        "Disc. Sale", "Qty")):
    """Two header rows: a brand band, then the columns under it.

    `_draw_grid` styles a plain header uniformly, so the header is built as grid
    rows instead — which is what lets each brand carry its own colour across the
    columns that belong to it.
    """
    band = [cell(first_label, align="l", fill=TOTAL_TINT, bold=True)]
    head = [cell("", fill=TOTAL_TINT)]
    aligns = ["l"]
    for b in BRANDS:
        band.append(cell(BRAND_LABEL[b], align="c", fill=BRAND_BG[b], bold=True,
                         span=len(per_brand), ink=BRAND_INK[b]))
        for c in per_brand:
            head.append(cell(c, align="c", fill=BRAND_BG[b], bold=True,
                             ink=BRAND_INK[b], wrap=True))
            aligns.append("r")
    band.append(cell("TOTAL WOMEN'S", align="c", fill=TOTAL_TINT, bold=True,
                     span=len(tail_labels)))
    for c in tail_labels:
        head.append(cell(c, align="c", fill=TOTAL_TINT, bold=True, wrap=True))
        aligns.append("r")
    return band, head, aligns


def _brand_cells(r, key, fill=None):
    """The four figures a brand contributes, in its own colour when banded."""
    out = []
    for b in BRANDS:
        v = r[b] if key is None else r[key][b]
        tint = fill if fill is not None else None
        for k in ("fresh_val", "fresh_qty", "disc_val", "disc_qty"):
            out.append(cell(_money(v[k]), align="r", fill=tint))
    return out


def render_summary(brands, stores, asof, title, period_note="") -> "Image":
    """Page one, as two tables: what each brand contributes, then every store.

    Two grids rather than one, because `_draw_grid` measures a single column
    structure and these two do not share one — nine columns against thirteen.
    Stacked, they read as a summary box above its detail.
    """
    total = next(b for b in brands if b["brand"] == "TOTAL")

    # ---- what each brand contributes to total women's trade ----------------
    head = [cell("BRAND", align="l", fill=TOTAL_TINT, bold=True)]
    for lbl in ("Fresh Sale", "Fresh Qty", "Disc. Sale", "Disc. Qty",
                "Total Sale", "Total Qty",
                "Fresh % of women's", "Disc. % of women's"):
        head.append(cell(lbl, align="c", fill=TOTAL_TINT, bold=True, wrap=True))
    top = [(head, int(ROW_H * 1.7))]
    for r in brands:
        is_tot = r["brand"] == "TOTAL"
        fill = TOTAL_BG if is_tot else BRAND_BG[r["brand"]]
        ink = INK if is_tot else BRAND_INK[r["brand"]]
        lbl = "TOTAL WOMEN'S" if is_tot else BRAND_LABEL[r["brand"]]
        vals = [lbl, _money(r["fresh_val"]), _money(r["fresh_qty"]),
                _money(r["disc_val"]), _money(r["disc_qty"]),
                _money(r["val"]), _money(r["qty"]),
                _pc(r["fresh_val"], total["val"]), _pc(r["disc_val"], total["val"])]
        top.append(([cell(v, align="l" if i == 0 else "r", fill=fill,
                          bold=True, ink=ink) for i, v in enumerate(vals)],
                    ROW_H))
    a = _draw_grid([], top, landscape=False,
                   # The title is clipped to this table's width, and this table is
                   # the narrow one — so it carries the report's name only. What
                   # the columns mean is written on the columns.
                   title=title)

    # ---- and the same question of every store ------------------------------
    band2, head2, _ = _band_and_head(
        "STORE", ("Total Sale", "Total Qty", "Fresh %", "Disc. %"))
    grid = [(band2, ROW_H), (head2, int(ROW_H * 1.7))]
    for r in stores:
        if not r["traded"]:
            grid.append(([cell(r["store"], align="l", ink=GREY)]
                         + [cell("", ink=GREY) for _ in range(8)]
                         + [cell("no women's sale this month", align="r",
                                 span=4, ink=GREY)], ROW_H))
            continue
        cells = [cell(r["store"], align="l")]
        cells += _brand_cells(r, None)
        cells += [cell(_money(r["val"]), align="r"),
                  cell(_money(r["qty"]), align="r")]
        if r["records"]:
            cells += [cell(_pc(r["fresh_val"], r["val"]), align="r"),
                      cell(_pc(r["disc_val"], r["val"]), align="r",
                           ink=NEG_INK if r["val"] and r["disc_val"] / r["val"] > .3
                           else INK)]
        else:
            # Never a promotion from this store, in any month — so its discount
            # cannot be told apart from zero, and 0.0% would say it could.
            cells += [cell("", align="r"),
                      cell("not recorded", align="r", ink=GREY)]
        grid.append((cells, ROW_H))

    t = {k: sum(s[k] for s in stores) for k in
         ("fresh_val", "fresh_qty", "disc_val", "disc_qty", "val", "qty")}
    tot_cells = [cell("TOTAL", align="l", fill=TOTAL_BG, bold=True)]
    for b in BRANDS:
        for k in ("fresh_val", "fresh_qty", "disc_val", "disc_qty"):
            tot_cells.append(cell(_money(sum(s[b][k] for s in stores)),
                                  align="r", fill=TOTAL_BG, bold=True))
    tot_cells += [cell(_money(t["val"]), align="r", fill=TOTAL_BG, bold=True),
                  cell(_money(t["qty"]), align="r", fill=TOTAL_BG, bold=True),
                  cell(_pc(t["fresh_val"], t["val"]), align="r", fill=TOTAL_BG,
                       bold=True),
                  cell(_pc(t["disc_val"], t["val"]), align="r", fill=TOTAL_BG,
                       bold=True)]
    grid.append((tot_cells, ROW_H))
    if period_note:
        grid.append(([cell(period_note, align="l", span=13, ink=GREY)],
                     int(ROW_H * 1.4)))
    silent = [r["store"] for r in stores if r["traded"] and not r["records"]]
    if silent:
        grid.append(([cell(
            "\"Not recorded\" — no Promotion Amount has ever reached us from "
            "these stores, in any month, so their discount cannot be told apart "
            "from nil: " + ", ".join(silent),
            align="l", span=13, ink=GREY)], int(ROW_H * 1.4)))
    b_img = _draw_grid([], grid, landscape=False,
                       title="STORE BY STORE  ·  Mohey & Manyavar stores")
    return _stack([a, b_img], _px(34))


def render_store_days(rows, store, asof) -> "Image":
    """A store's month, day by day, brand by brand."""
    band, head, _ = _band_and_head(
        "DATE", ("Total Sale", "Total Qty", "Disc. %"))
    grid = [(band, ROW_H), (head, int(ROW_H * 1.7))]
    for r in rows:
        if r["future"]:
            grid.append(([cell(f"{r['date']:%d-%m-%Y}", align="l")]
                         + [cell("") for _ in range(11)], ROW_H))
            continue
        cells = [cell(f"{r['date']:%d-%m-%Y}", align="l")]
        cells += _brand_cells(r, None)
        cells += [cell(_money(r["val"]), align="r"),
                  cell(_money(r["qty"]), align="r"),
                  cell(_pc(r["disc_val"], r["val"]), align="r")]
        grid.append((cells, ROW_H))

    t = {k: sum(r[k] for r in rows) for k in
         ("fresh_val", "fresh_qty", "disc_val", "disc_qty", "val", "qty")}
    cells = [cell("TOTAL", align="l", fill=TOTAL_BG, bold=True)]
    for b in BRANDS:
        for k in ("fresh_val", "fresh_qty", "disc_val", "disc_qty"):
            cells.append(cell(_money(sum(r[b][k] for r in rows)), align="r",
                              fill=TOTAL_BG, bold=True))
    cells += [cell(_money(t["val"]), align="r", fill=TOTAL_BG, bold=True),
              cell(_money(t["qty"]), align="r", fill=TOTAL_BG, bold=True),
              cell(_pc(t["disc_val"], t["val"]), align="r", fill=TOTAL_BG,
                   bold=True)]
    grid.append((cells, ROW_H))
    return _draw_grid([], grid, title=f"{store.upper()} — WOMEN'S DISCOUNT  ·  "
                                      f"{asof:%b %Y}")


# --------------------------------------------------------------------------- #
def _south_note(y, asof) -> str:
    """What the 1 April start folds in for South, in its own words."""
    import loader as L
    tk = pd.Timestamp(asof.year if asof.month >= 4 else asof.year - 1, 4, 19)
    stores = mohey_stores(asof)
    south = [k for k, (c, r) in stores.items() if r == "South"]
    pre = y[y[L.COL_STORE_LABEL].astype(str).isin(south) & (y["date"] < tk)]
    if pre.empty:
        return ""
    return (f"The year runs from 1 April for every store. South was taken over "
            f"on {tk:%d %b %Y}, so its first {tk.day - 1} days here — "
            f"Rs {pre['_val'].sum():,.0f} of women's sale — are the previous "
            f"operator's trading, not ours.")


def _fy_start(asof) -> pd.Timestamp:
    asof = pd.Timestamp(asof)
    return pd.Timestamp(asof.year if asof.month >= 4 else asof.year - 1, 4, 1)


def build_pdf(vdf, asof, basis_label="") -> tuple[str, bytes]:
    """The year to date, then the month, then a page per Mohey store."""
    asof = pd.Timestamp(asof)
    allw = womens(vdf)
    stores = mohey_stores(asof)
    records = ever_recorded(vdf)

    # ---- page one: the year, from 1 April -----------------------------------
    # ★ SOUTH IS INCLUDED FROM THE 1st, WHICH MEANS THE PREVIOUS OPERATOR.
    # We took those five stores over on 19 April; the feed keeps their earlier
    # trading, so a flat 1 April start folds in Rs 74.8 L of women's sale that
    # was not ours — 11.9% of South's year. Every other VFL report anchors South
    # at the takeover instead. Manav asked for 1 April, so 1 April it is, and the
    # page says so rather than leaving the reader to find out.
    fy0 = _fy_start(asof)
    y = allw[(allw["date"] >= fy0) & (allw["date"] <= asof)]
    yrows = store_rows(y, stores, records)
    sheets = [("Year to date",
               render_summary(brand_rows(y), yrows, asof,
                              f"VFL WOMEN'S DISCOUNT — YEAR TO DATE  ·  "
                              f"{fy0:%d %b} to {asof:%d %b %Y}",
                              period_note=_south_note(y, asof)))]

    # ---- then the month, and the stores day by day --------------------------
    w = allw[(allw["date"] >= asof.replace(day=1)) & (allw["date"] <= asof)]
    srows = store_rows(w, stores, records)
    sheets.append(("Summary — the month",
                   render_summary(brand_rows(w), srows, asof,
                                  f"VFL WOMEN'S DISCOUNT — {asof:%B %Y}")))
    for r in srows:
        if not r["traded"]:
            continue
        sheets.append((r["store"],
                       render_store_days(day_rows(w, r["store"], asof),
                                         r["store"], asof)))
    with _LOCK:
        pdf = _pdf_from(sheets, f"As of {asof:%d %b %Y}"
                        + (f" · {basis_label}" if basis_label else ""))
    return (f"VFL WOMENS DISCOUNT REPORT {asof:%b %Y}.pdf".upper(), pdf)
