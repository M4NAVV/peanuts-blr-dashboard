"""Category analysis VFL — how each product category is moving against last year.

★ Manav, 6 Oct 2026: *"another pdf, that is focused on VFL and categories, so on a
portfolio level, region level and then store level … like how kurtas are doing this
year, compared to last year"*. His rulings the same day:
  - the category is the DIVISION, with Twamev split into its own categories
    (Twamev is one division in the feed, holding kurtas, jodhpuris, sherwanis …);
  - periods MTD, YTD and one festive run-up, each against the same days last year;
  - measures: sales + G/D, price per piece, share of sales;
  - a store is NEW only if it has no last-year data. Every store with last year is
    compared, South included.

★ WHY NOT THE SECTION. Sections carry COLLECTION CODES (KURTA SET-09, -12, -14, O-S).
Stock moves from one code to the next between seasons — this year KURTA SET-14 halved
while -09 doubled — so a section-level comparison reports the catalogue changing, not
the customer. The division is the code-free category.

★ THE SAME WINDOWS AS EVERY OTHER REPORT. MTD and YTD come from `L.report_frames`
(South anchored to its 19 Apr takeover); the festive run-up from `festive.Window`
(`ty_start..ty_cut` against `ly_start..ly_cut`). So a category total here ties to the
brand and G/D pages for the same day. See [[feedback-same-estate]].
"""
import io
import re

import pandas as pd

import festive_admin as FADM
import loader as L

# --------------------------------------------------------------------------- categories
_LABEL = {
    "KURTA SET": "Kurta set", "KURTA ONLY": "Kurta only", "SHORT KURTA": "Short kurta",
    "INSIDE KURTA ONLY": "Inside kurta", "INDO WESTERN SET": "Indo-western",
    "SHERWANI SET": "Sherwani", "JODHPURI SUIT": "Jodhpuri suit", "JACKET": "Jacket",
    "JACKET SET": "Jacket set", "MANYAVAR ACCESSORIES": "Accessories", "CHILD": "Kidswear",
    "LOWERS": "Lowers", "SOUTH PANCHA VESHTI": "Pancha & veshti", "SUITS": "Suits",
    "DIWAS": "Diwas", "BLAZER": "Blazer", "SHIRTS": "Shirts", "MANTHAN": "Manthan",
    "MOHEY-SAREE": "Saree", "MOHEY-LEHENGA": "Lehenga", "MOHEY-STITCHED SUIT": "Stitched suit",
    "MOHEY-CROP TOP LEHENGA": "Crop top lehenga", "MOHEY ACCESSORIES": "Accessories",
    "MOHEY": "Mohey, other", "MEBAZ": "Mebaz",
}
# Twamev's sections, code-free. Anything not named here folds into one line, so a
# new or one-off section cannot quietly add a row that has no last year.
_TWAMEV = {
    "TWAM KURTA SET": "Kurta set", "TWAM JODHPURI SET": "Jodhpuri set",
    "TWAM SUIT SET": "Suit set", "TWAM INDO WESTERN SET": "Indo-western",
    "TWAM SHERWANI SET": "Sherwani", "TWAM JACKET SET": "Jacket set",
    "TWAM FOOTWEAR": "Footwear", "TWAM SAREE": "Saree", "TWAM LEHENGA": "Lehenga",
    "TWAM CROP TOP LEHENGA": "Crop top lehenga", "TWAM STITCHED SUIT": "Stitched suit",
}
_GROUP_OF = {"Manyavar": "Manyavar", "Manthan": "Manyavar", "Mohey": "Mohey",
             "Mebaz": "Mohey", "Twamev": "Twamev"}
GROUPS = ["Manyavar", "Mohey", "Twamev", "Other"]
_CODE = re.compile(r"[\s-]*(O-S|\d{2}|OTHERS)$")


def categorise(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `_grp` (Manyavar / Mohey / Twamev / Other) and `_cat` (the category)."""
    d = df.copy()
    div = d[L.COL_DIVISION].astype(str).str.strip().str.upper()
    sec = d[L.COL_SECTION].astype(str).str.strip().str.upper().str.replace(_CODE, "", regex=True)
    d["_grp"] = d[L.COL_BRAND].map(_GROUP_OF).fillna("Other")
    cat = div.map(_LABEL)
    tw = div.str.startswith("TWAMEV")
    cat = cat.mask(tw, sec.map(_TWAMEV).fillna("Accessories & other"))
    d["_grp"] = d["_grp"].mask(tw, "Twamev")
    d["_cat"] = cat.fillna("Other")
    d.loc[d["_cat"].eq("Other") & ~tw & d["_grp"].ne("Other"), "_grp"] = "Other"
    return d


# --------------------------------------------------------------------------- figures
def _sums(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["sales", "pcs"])
    return frame.groupby(["_grp", "_cat"]).agg(sales=(L.COL_AMOUNT, "sum"), pcs=("_units", "sum"))


def _gd(ty, ly):
    # ★ A NEGATIVE OR NIL BASE IS NOT A BASE (same rule as the brand page).
    return (ty / ly - 1) * 100 if ly and ly > 0 else None


def _ppc(sales, pcs):
    return sales / pcs if pcs and pcs > 0 else None


def windows(df: pd.DataFrame, asof, w):
    """{period: (this-year rows, last-year rows)} on the house windows."""
    ym, yp = L.report_frames(df, "YTD", asof=asof)
    mm, mp = L.report_frames(df, "MTD", asof=asof)
    out = {"MTD": (mm, mp), "YTD": (ym, yp)}
    if w is not None and w.started:
        dd = df["date"]
        out["FEST"] = (df[(dd >= w.ty_start) & (dd <= w.ty_cut)],
                       df[(dd >= w.ly_start) & (dd <= w.ly_cut)])
    return out


def table_rows(win: dict, stores):
    """Rows for one scope (a set of stores), grouped by brand, with subtotals.

    ★ RATIOS FROM SUMMED PAIRS: a subtotal's G/D, share and price per piece are taken
    from its own summed sales and pieces, never averaged down the column.
    See [[feedback-aggregate-ratios-in-pairs]]."""
    lab = L.COL_STORE_LABEL
    s = {k: (_sums(t[t[lab].isin(stores)]), _sums(l[l[lab].isin(stores)]))
         for k, (t, l) in win.items()}
    keys = set()
    for t, l in s.values():
        keys |= set(t.index) | set(l.index)
    ytd_t, ytd_l = s["YTD"]
    tot_ty = float(ytd_t["sales"].sum()) if len(ytd_t) else 0.0
    tot_ly = float(ytd_l["sales"].sum()) if len(ytd_l) else 0.0

    def line(name, idx):
        r = {"cat": name}
        for k, (t, l) in s.items():
            ts = float(t.loc[t.index.isin(idx), "sales"].sum()) if len(t) else 0.0
            ls = float(l.loc[l.index.isin(idx), "sales"].sum()) if len(l) else 0.0
            r[f"{k}_ty"], r[f"{k}_gd"] = ts, _gd(ts, ls)
            if k == "YTD":
                tp = float(t.loc[t.index.isin(idx), "pcs"].sum()) if len(t) else 0.0
                lp = float(l.loc[l.index.isin(idx), "pcs"].sum()) if len(l) else 0.0
                r["ppc_ty"], r["ppc_ly"] = _ppc(ts, tp), _ppc(ls, lp)
                r["ppc_gd"] = (_gd(r["ppc_ty"], r["ppc_ly"])
                               if r["ppc_ty"] is not None and r["ppc_ly"] is not None else None)
                sh_t = ts / tot_ty * 100 if tot_ty else None
                sh_l = ls / tot_ly * 100 if tot_ly > 0 else None
                r["share"] = sh_t
                # ★ IN %, NOT "PTS" (Manav, 6 Oct: "dont put anything in points,
                # percentage is fine"): the difference between this year's share
                # and last year's, written as a percentage.
                _d = round(sh_t - sh_l, 1) if sh_t is not None and sh_l is not None else None
                r["share_chg"] = ("" if _d is None else "0.0%" if _d == 0 else f"{_d:+.1f}%")
                r["_ly_ytd"] = ls
        return r

    rows = []
    for g in GROUPS:
        idx = sorted(k for k in keys if k[0] == g)
        if not idx:
            continue
        part = [dict(line(c, [(g, c)]), _label=(c if g == "Manyavar" else f"{g} {c.lower()}"))
                for _g, c in idx]
        part = [r for r in part if any(abs(r.get(f"{k}_ty", 0) or 0) > 0 for k in s) or r["_ly_ytd"]]
        part.sort(key=lambda r: -(r["YTD_ty"] or 0))
        if not part:
            continue
        # ★ THE BRAND'S TOTAL HEADS ITS GROUP (6 Oct): "Kurta set" is a Manyavar line
        # and a Twamev line, so the reader must know which group they are in BEFORE
        # the rows, not after them.
        if g != "Other":
            sub = line(g, idx)
            sub["_sub"] = True
            rows.append(sub)
        rows += part
    total = line("Total", sorted(keys))
    total["share_chg"] = ""                  # the whole is always 100%: nothing moved
    return rows, total, s


def movers(rows, min_share=1.0, n=3):
    """The categories that moved most on the year, among those that matter (share
    of at least `min_share`%). Computed from the same rows the table prints."""
    c = [r for r in rows if not r.get("_sub") and r.get("YTD_gd") is not None
         and (r.get("share") or 0) >= min_share]
    up = sorted([r for r in c if r["YTD_gd"] > 0], key=lambda r: -r["YTD_gd"])[:n]
    dn = sorted([r for r in c if r["YTD_gd"] < 0], key=lambda r: r["YTD_gd"])[:n]
    return up, dn


def _phrase(rs):
    return ", ".join(f"{r['_label']} {r['YTD_gd']:+.0f}%" for r in rs) or "none"


# --------------------------------------------------------------------------- drawing
def _spec(has_fest: bool):
    sp = [("cat", "text", "CATEGORY"),
          ("MTD_ty", "money", "MTD\nSALES"), ("MTD_gd", "gd", "MTD\nG/D"),
          ("YTD_ty", "money", "YTD\nSALES"), ("YTD_gd", "gd", "YTD\nG/D"),
          ("share", "pct", "SHARE\nYTD"), ("share_chg", "pct", "SHARE\nCHANGE"),
          ("ppc_ty", "money", "PRICE/PC\nYTD"), ("ppc_gd", "gd", "PRICE/PC\nG/D")]
    if has_fest:
        sp += [("FEST_ty", "money", "FESTIVE\nSALES"), ("FEST_gd", "gd", "FESTIVE\nG/D")]
    return sp


def _degrowth(r):
    v = r.get("YTD_gd")
    return isinstance(v, (int, float)) and v < 0


def build(df_in: pd.DataFrame, asof, w=None, basis_label=""):
    """-> (filename, pdf bytes). `df_in` = the full VFL frame (never the sidebar
    filters: the portfolio and region pages are totals). `w` = one festive Window
    already re-dated to `asof` (festive.at), or None for no festive columns."""
    import snapshots_a4 as A4
    import festive as F

    df = df_in
    note_prov = ""
    if "_provisional" in df.columns:
        prov = df["_provisional"].fillna(False).astype(bool)
        if prov.any():
            # ★ A PROVISIONAL DAY HAS TAKINGS, NOT PRODUCTS: it cannot be put in a
            # category, so it is left out and the page says so.
            # See [[feedback-provisional-day]].
            note_prov = (f" Last night's provisional takings "
                         f"({df.loc[prov, 'date'].max():%d %b}) carry no products and are not "
                         f"in this report.")
            df = df[~prov]
    asof = min(pd.Timestamp(asof).normalize(), df["date"].max().normalize())
    if w is not None:
        w = F.at(w, asof)
    df = categorise(df)
    win = windows(df, asof, w)
    has_fest = "FEST" in win

    lab = L.COL_STORE_LABEL
    master = L.load_store_master().set_index("tableau_name")
    ytd_ly = win["YTD"][1]
    has_ly = set(ytd_ly.loc[ytd_ly[L.COL_AMOUNT] > 0, lab].dropna().unique())
    # A store with no sale in 60 days is shut: held out of every page, and named.
    last_sale = df.groupby(lab)["date"].max()
    stores = sorted(s for s, d in last_sale.items() if d >= asof - pd.Timedelta(days=60))
    shut = sorted(s for s, d in last_sale.items() if d < asof - pd.Timedelta(days=60))
    shut_note = (" " + "; ".join(f"{s} left out: no sales since {last_sale[s]:%d %b %Y}"
                                 for s in shut) + "." if shut else "")
    region = {s: (master.loc[s, "region"] if s in master.index else "?") for s in stores}
    code = {s: pd.to_numeric(master.loc[s, "code"], errors="coerce") if s in master.index else 9999
            for s in stores}
    city = {s: (str(master.loc[s, "city"]).title() if s in master.index else "") for s in stores}
    new = [s for s in stores if s not in has_ly]
    l2l = [s for s in stores if s in has_ly]

    month_from = max(asof.replace(day=1), pd.Timestamp(asof.year, asof.month, 1))
    fy0 = pd.Timestamp(asof.year if asof.month >= 4 else asof.year - 1, 4, 1)
    def periods(reg=None):
        ytd = {None: f"YTD from {fy0:%d %b} (South from its 19 Apr takeover)",
               "South": "YTD from the 19 Apr takeover"}.get(reg, f"YTD from {fy0:%d %b}")
        return (f"MTD {month_from:%d %b} to {asof:%d %b}  ·  {ytd}"
                + (f"  ·  {w.festival} {w.tenure}: {w.basis().replace('→', 'to')}" if has_fest else "")
                + "  ·  each against the same days last year")

    _keep = (A4.MARGIN, A4.CONTENT_W, FADM.PP.PAD_Y)
    A4.MARGIN = A4.PRINT_MARGIN
    A4.CONTENT_W = A4.PAGE_W - 2 * A4.MARGIN
    try:
        W = A4.CONTENT_W
        spec = _spec(has_fest)
        pages = []

        def page(title, sub, scope, note):
            rows, total, _ = table_rows(win, scope)
            sh = A4._Sheet("Category analysis VFL", asof, "", bounded=False, footer=True)
            sh.put(A4._heading(W, title, sub), gap=14)
            up, dn = movers(rows)
            sh.put(A4._text_block(W, [(
                f"Growing most this year (categories with at least 1% of sales): {_phrase(up)}.  "
                f"Falling most: {_phrase(dn)}.", A4._ft(26)[1], A4.INK)]), gap=12)
            sh.put(A4._text_block(W, [(note + note_prov, A4._ft(21)[0], A4.SUB)]), gap=16)
            sh.put(FADM.table_image(rows, spec, W, font_px=21, total_row=total,
                                    neg_row=_degrowth, sub_row=lambda r: r.get("_sub", False),
                                    shade=[3, 4]), gap=18)
            sh.put(A4._text_block(W, [(
                "G/D is growth against the same days last year. SHARE is the category's part "
                "of this page's year-to-date sales; SHARE CHANGE is this year's share minus "
                "last year's (12.0% against 10.5% reads +1.5%). PRICE/PC is sales divided by pieces sold, so a rise "
                "with flat pieces is price, not volume. A row in red is down on the year. "
                "Subtotals and the total are worked from their own sums, not averaged.",
                A4._ft(19)[0], A4.SUB)]), gap=0)
            sh._footers()
            return sh.pages

        left = (f" {', '.join(new)} {'is' if len(new) == 1 else 'are'} left out of the group "
                f"pages: no last year to compare with." if new else "")
        pages += page("Categories · VFL portfolio", periods(), l2l,
                      f"{len(l2l)} stores, every one with last year's data.{left}{shut_note}")
        for reg in ("East & NE", "South"):
            sc = [s for s in l2l if region[s] == reg]
            if sc:
                pages += page(f"Categories · {'East & North-East' if reg == 'East & NE' else reg}",
                              periods(reg), sc, f"{len(sc)} stores, every one with last year's data."
                              + (f" {', '.join(s for s in new if region[s] == reg)} left out: "
                                 f"no last year." if any(region[s] == reg for s in new) else "")
                              + "".join(f" {s} left out: no sales since {last_sale[s]:%d %b %Y}."
                                        for s in shut if region.get(s, master.loc[s, "region"]
                                                                    if s in master.index else "") == reg))
        for reg in ("East & NE", "South"):
            for s in sorted([s for s in stores if region[s] == reg], key=lambda s: code[s]):
                pages += page(f"Categories · {s}", f"{city[s]}  ·  {reg}  ·  " + periods(reg), [s],
                              ("New this year: no last year, so no growth to state." if s in new
                               else "One store, against its own last year."))

        buf = io.BytesIO()
        pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:],
                      resolution=A4.PAGE_W * 72.0 / A4.PAGE_PT_W)
        out = buf.getvalue()
    finally:
        A4.MARGIN, A4.CONTENT_W, FADM.PP.PAD_Y = _keep
    return f"CATEGORY ANALYSIS VFL {asof:%d-%m-%Y}.pdf", out

