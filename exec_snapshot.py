"""
Executive Snapshot — the opening page of both report packs.

Replaces the cover. The cover carried a title and four stamp lines; this carries
the same stamp plus everything an owner would otherwise have to assemble by
reading five sheets: where the business stands, which way it is moving, which
doors moved the money, and which need attention today.

Rendered as *content* and handed to ``portfolio_pdf._compose``, so it inherits
the pack's frame, header band, footer and page numbering rather than
re-implementing them — a snapshot and the sheets behind it are one document.

Five bands, top to bottom:

  1. six tiles      — YTD, MTD, day, projected year, breadth, estate
  2. trajectory     — the last five months, this year against last
  3. a four-column body — region/concentration, mix, gained, declined

One page per scope: the whole estate, then each region. Same format throughout,
each page computed on its own scope rather than sliced from a national figure.
The movers columns list EVERY store that moved, not a top-n — a manager looking
for their own store should find it.

★ THE LIKE TO LIKE RULE (Manav, 9 Aug). The portfolio headline is computed two
ways and both are printed. Total growth reads +114% because the eight South
stores have no last year at all; like to like — stores trading in BOTH years and
still open — reads +4.9%, and the month reads -7.3% against a total of +128%. A
page that printed only the first number would be a misread waiting to happen, and
the gap between the two is itself the finding. VFL needs no such split: it keeps
South's pre-takeover history, so every store is already comparable.

★ ONE LIKE TO LIKE SET, DEFINED ONCE. An early draft mixed a 44-store set (from
the YTD window) with a 41-store set (from the MTD window) and printed -7.3% and
-10.1% for the same month — closed stores' last-year sales were leaking into one
of them. `_lfl_codes` is now the single definition every figure on the page uses.

★ PART MONTHS ARE MARKED. August is eight days here. An unmarked short bar beside
four full months reads as a collapse, so the current month is hatched and its day
count printed on the axis.
"""

from __future__ import annotations

import pandas as pd
from PIL import Image, ImageDraw

import portfolio_pdf as PP
from portfolio_pdf import _ft, _px, GRID, HDR_BG, INK, NEG_INK, WHITE, MAROON

# Bar fills. The pale one is the workbook's own header blue; the deep one is a
# darker step of the same hue, chosen because a pale-on-white fill prints washed
# out. Validated rather than eyeballed: DE 43 apart under both protanopia and
# tritanopia, and every bar carries a grid border and a printed value so the
# pair never has to be told apart by colour alone.
BAR_TY = (47, 102, 144)          # #2F6690
BAR_LY = HDR_BG                  # #DAEEF3
MUTED_INK = (68, 68, 68)
FAINT_INK = (85, 85, 85)

# Day-sale floors. The attention band that used them was removed from the
# snapshot on Manav's instruction (11 Aug); the floors stay because the tile
# still reports how many stores fall under one.
PORTFOLIO_DAY_FLOOR = 10_000
VFL_DAY_FLOOR = 50_000

MOVERS_N = 6
TRAJ_MONTHS = 5


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def _cr(v) -> str:
    return f"{v / 1e7:,.2f}"


def _rupee_move(v) -> str:
    """Movement in the unit that keeps it readable: crore past a crore, else lakh."""
    if abs(v) >= 1e7:
        return f"{v / 1e7:+,.2f} Cr"
    return f"{v / 1e5:+,.1f} L"


def _pct(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{v:+,.1f}%"


def _rs(v) -> str:
    return f"Rs {v:,.0f}"


def _growth(cur, pri):
    return ((cur / pri - 1) * 100) if pri else None


# --------------------------------------------------------------------------- #
# Metrics — portfolio
# --------------------------------------------------------------------------- #
def regions_of(df, vfl=False) -> list:
    """Regions present in the frame, in the packs' display order.

    Derived from the data rather than hardcoded, so a third region appears as a
    third page on its own without anyone remembering to add it.
    """
    if vfl:
        import loader as L
        m = L.load_store_master()
        reg = dict(zip(m["tableau_name"], m["region"]))
        present = set(df[L.COL_STORE_LABEL].map(reg).dropna())
    else:
        present = set(df["region"].dropna())
    order = ["East & NE", "South"]
    return ([r for r in order if r in present]
            + sorted(present - set(order)))


def portfolio_frame_from_vfl(vfl_df, region=None):
    """The VFL frame reshaped into the portfolio schema.

    ★ Why this exists (Manav, 11 Aug): "even for south, if we look at the VFL
    sheet, we will get all of last years data, if you look at portfolio sheet,
    you will get nothing." South was taken over on 19 April 2026, so the
    portfolio feed starts there and its last year is simply absent — a South page
    built from it has no trajectory, no movers and no growth. The VFL feed keeps
    the previous operator's history, and all eight South stores are VFL stores,
    so it can supply the whole comparison.

    Returns one row per store-day, with the identity columns the portfolio
    reports expect, so the page format is unchanged.
    """
    import loader as L
    import portfolio_loader as PL
    m = L.load_store_master()
    code = dict(zip(m["tableau_name"], m["code"]))
    d = pd.DataFrame({
        "date": vfl_df["date"],
        "code": pd.to_numeric(vfl_df[L.COL_STORE_LABEL].map(code), errors="coerce"),
        "sales": vfl_df[L.COL_AMOUNT],
    })
    d = d[d["code"].notna() & d["date"].notna()]
    d["code"] = d["code"].astype(int)
    d = d.groupby(["date", "code"], as_index=False)["sales"].sum()
    pm = PL.store_master().dropna(subset=["code"]).copy()
    pm["code"] = pm["code"].astype(int)
    pm = pm.set_index("code")
    for col in ("region", "city", "location", "brand", "takeover_date", "is_vfl"):
        d[col] = d["code"].map(pm[col])
    # The rest of the portfolio schema, so every report helper works unchanged.
    # takeover_date is carried through deliberately: the windows stay
    # takeover-anchored, so South compares 19 April onward in BOTH years, exactly
    # as the VFL pack and the L-to-L sheets do.
    d["date"] = pd.to_datetime(d["date"])
    d["month"] = d["date"].dt.to_period("M").dt.to_timestamp()
    d["month_label"] = d["date"].dt.strftime("%b %Y")
    fy_start = d["date"].dt.year.where(d["date"].dt.month >= 4,
                                       d["date"].dt.year - 1)
    d["fy"] = "FY" + ((fy_start + 1) % 100).astype(int).astype(str).str.zfill(2)
    if region:
        d = d[d["region"] == region]
    return d.reset_index(drop=True)


def has_prior_year(pf, asof, region) -> bool:
    """Does this region have ANY last-year sales in the frame given?"""
    fy = asof.year if asof.month >= 4 else asof.year - 1
    d = pf[pf["region"] == region]
    prev = d[(d["date"] >= pd.Timestamp(fy - 1, 4, 1))
             & (d["date"] < pd.Timestamp(fy, 4, 1))]
    return float(prev["sales"].sum()) > 0


def _closed_codes(pf, asof) -> set:
    import portfolio_loader as PL
    attrs = PL.gd_store_attrs_dyn(pf, asof).set_index("code")
    out = set()
    for c in attrs.index:
        v = str(attrs.loc[c, "closed"]).strip()
        if v and v.lower() != "nan":
            out.add(int(c))
    return out


def _lfl_codes(pf, asof) -> set:
    """Stores trading in BOTH years and still open — the one like to like set.

    Both halves matter. Without 'both years' the new South stores make every
    growth rate meaningless; without 'still open' a shut store's last year is
    counted against a current year it was never going to trade.
    """
    import portfolio_loader as PL
    y = PL.store_yoy(pf, kind="YTD", asof=asof)
    return set(y[y["prior"] > 0]["code"]) - _closed_codes(pf, asof)


def _monthly(cur, pri, asof, value_col, month_col="date", n=TRAJ_MONTHS):
    """Last `n` months of the fiscal year to date, this year against last.

    Both frames are the report's own windows, so the months line up: the prior
    frame is the same calendar span a year earlier, already takeover-anchored and
    closure-capped by whichever loader produced it.
    """
    def by_month(fr):
        if fr.empty:
            return {}
        k = fr[month_col].dt.strftime("%b")
        return fr.groupby(k)[value_col].sum().to_dict()

    ty, ly = by_month(cur), by_month(pri)
    fy_start = pd.Timestamp(asof.year if asof.month >= 4 else asof.year - 1, 4, 1)
    months, m = [], fy_start
    while m <= asof:
        months.append(m.strftime("%b"))
        m += pd.DateOffset(months=1)
    months = months[-n:]
    return {
        "months": months,
        "ty": [float(ty.get(k, 0.0)) for k in months],
        "ly": [float(ly.get(k, 0.0)) for k in months],
        "part_days": int(asof.day),
    }


def portfolio_metrics(pf, asof, basis_label="", region=None) -> dict:
    """Everything the portfolio snapshot prints, computed on one basis.

    `region` scopes the whole page — the frame is filtered first, so every
    figure below (like to like set, trajectory, movers, concentration) is that
    region's own rather than a slice of a national number.
    """
    import portfolio_loader as PL
    asof = pd.Timestamp(asof)
    if region:
        pf = pf[pf["region"] == region]
    closed = _closed_codes(pf, asof)
    lfl = _lfl_codes(pf, asof)

    y = PL.store_yoy(pf, kind="YTD", asof=asof)
    m = PL.store_yoy(pf, kind="MTD", asof=asof)
    yl, ml = y[y["code"].isin(lfl)], m[m["code"].isin(lfl)]

    ytd_all, ytd_ly = y["cur"].sum(), y["prior"].sum()
    mtd_all, mtd_ly = m["cur"].sum(), m["prior"].sum()
    ytd_l, ytd_ll = yl["cur"].sum(), yl["prior"].sum()
    mtd_l, mtd_ll = ml["cur"].sum(), ml["prior"].sum()

    # Day: the whole estate for the headline figure, like to like for the rate.
    # Same WEEKDAY is the honest comparison — a single date a year ago lands on a
    # different day of the week and its year-on-year is mostly noise.
    day_all = pf[pf["date"] == asof]["sales"].sum()
    dl = pf[pf["code"].isin(lfl)]
    d_ty = dl[dl["date"] == asof]["sales"].sum()
    d_date = dl[dl["date"] == asof - pd.DateOffset(years=1)]["sales"].sum()
    d_wday = dl[dl["date"] == asof - pd.Timedelta(days=364)]["sales"].sum()

    mets = PL._gd_store_metrics(pf, asof)
    proj = sum(v["proj_ytd"] for v in mets.values())
    ly_full = sum(v["ly_full"] for v in mets.values())

    # South has NO last year in the portfolio feed, so its like to like set is
    # empty and a like to like trajectory would be five zero bars — a page that
    # looks broken rather than one that says "no comparison exists". Fall back to
    # every store: the current-year shape is real and worth seeing, and the
    # absent last-year bars state the situation themselves.
    cur, pri = PL._window_frames(pf, "YTD", asof)
    _tset = lfl if lfl else set(y["code"])
    traj = _monthly(cur[cur["code"].isin(_tset)], pri[pri["code"].isin(_tset)],
                    asof, "sales")
    traj_note = ("Like to like, Rs crore by month" if lfl
                 else "Overall, Rs crore by month — no last year to compare")

    tot = y["cur"].sum()
    top5 = y.nlargest(5, "cur")
    top1 = top5.iloc[0] if len(top5) else None

    # On the overall page this splits by region. On a region page that would be a
    # single row repeating the total underneath it, so it splits by CITY instead
    # — same columns, same shape, but it says something.
    # Region page splits by city; a one-city region (South is all Bengaluru)
    # would repeat its own total, so it splits by store location instead.
    split = "region"
    if region:
        split = "city" if y["city"].nunique() > 1 else "location"
    reg_y = y.groupby(split)[["cur", "prior"]].sum()
    reg_m = m.groupby(split)[["cur", "prior"]].sum()
    region_rows = []
    for r in reg_y.sort_values("cur", ascending=False).index:
        yc, yp = reg_y.loc[r, "cur"], reg_y.loc[r, "prior"]
        mc, mp = reg_m.loc[r, "cur"] if r in reg_m.index else 0, \
            reg_m.loc[r, "prior"] if r in reg_m.index else 0
        region_rows.append([str(r).title(), _cr(yc), _pct(_growth(yc, yp)),
                            _cr(mc), _pct(_growth(mc, mp))])
    region_rows.append(["Total", _cr(ytd_all), _pct(_growth(ytd_all, ytd_ly)),
                        _cr(mtd_all), _pct(_growth(mtd_all, mtd_ly))])

    # EVERY brand, biggest gain to biggest decline — not the three best and
    # three worst. A brand missing from the list is indistinguishable from a
    # brand that did nothing, and the middle is where most of the estate sits.
    if not len(yl):
        brand_rows = [["No last-year comparison", "—", "—"]]
    else:
        b = yl.groupby("brand")[["cur", "prior"]].sum()
        b["move"] = b["cur"] - b["prior"]
        b = b.sort_values("move", ascending=False)
        brand_rows = [[str(i).title(), _rupee_move(r["move"]),
                       _pct(_growth(r["cur"], r["prior"]))]
                      for i, r in b.iterrows()]

    def mover_rows(frame, best):
        """EVERY store that moved that way, not a top-n. A manager looking for
        their own store should find it; a list of five answers only about five."""
        f = frame[frame["shortfall"] > 0].sort_values("shortfall", ascending=False) \
            if best else \
            frame[frame["shortfall"] < 0].sort_values("shortfall")
        if not len(f):
            # South has no last year in the portfolio feed, so "gained" and
            # "declined" are undefined there. Say so — two blank columns read as
            # a broken report rather than as an absent comparison.
            return [["No last-year comparison", "—", "—"]]
        return [[f"{str(r['location'])[:16]}  {int(r['code'])}",
                 _rupee_move(r["shortfall"]), _pct(r["growth"])]
                for _, r in f.iterrows()]

    day_by = pf[pf["date"] == asof].groupby(["code", "location"])["sales"].sum()
    low = [(str(loc)[:15], int(c), float(v))
           for (c, loc), v in day_by.items()
           if int(c) not in closed and v < PORTFOLIO_DAY_FLOOR]
    low.sort(key=lambda t: t[2])
    n_open = len(set(int(c) for c in y["code"]) - closed)
    # A closed store still appears in the day frame at zero; counting it as
    # having "filed" produced 53 of 50.
    n_filed = len({int(c) for c, _ in day_by.index} - closed)

    return {
        "title": "Executive Snapshot",
        "subtitle": "Whole Portfolio" + (f"  ·  {region}" if region else ""),
        "region": region,
        "stamp": [
            f"As of {asof:%d %b %Y}",
            basis_label or f"Live to {asof:%d %b %Y}",
            f"{len(y)} trading  |  {len(closed)} closed  |  {n_open} open",
            f"Like to like = {len(lfl)} stores trading both years",
        ],
        "tiles": [
            {"label": "Year to date", "value": f"Rs {_cr(ytd_all)} Cr",
             "sub": f"LY Rs {_cr(ytd_ly)} Cr",
             "rows": [("Overall", _pct(_growth(ytd_all, ytd_ly)))],
             "key": ("Like to like", _pct(_growth(ytd_l, ytd_ll)))},
            {"label": "Month to date", "value": f"Rs {_cr(mtd_all)} Cr",
             "sub": f"LY Rs {_cr(mtd_ly)} Cr",
             "rows": [("Overall", _pct(_growth(mtd_all, mtd_ly)))],
             "key": ("Like to like", _pct(_growth(mtd_l, mtd_ll)))},
            {"label": f"Day {asof:%d %b}", "value": f"Rs {_cr(day_all)} Cr",
             "sub": f"Like to like Rs {_cr(d_ty)} Cr",
             "rows": [("vs same date", _pct(_growth(d_ty, d_date)))],
             "key": ("vs same weekday", _pct(_growth(d_ty, d_wday)))},
            {"label": "Projected year", "value": f"Rs {_cr(proj)} Cr",
             "sub": f"last full year Rs {_cr(ly_full)} Cr",
             "rows": [("Run-rate", "x365 op-days")],
             "key": ("Implied", _pct(_growth(proj, ly_full)))},
            {"label": "Breadth  LTL",
             "value": (f"{int((ml['shortfall'] > 0).sum())} up  "
                       f"{int((ml['shortfall'] < 0).sum())} dn") if len(ml) else "—",
             "sub": (f"this month, of {len(ml)}" if len(ml)
                     else "no comparable stores"),
             "rows": [("Year to date",
                       f"{int((yl['shortfall'] > 0).sum())} up" if len(yl) else "—")],
             "key": ("", f"{int((yl['shortfall'] < 0).sum())} down" if len(yl) else "")},
            {"label": "Estate", "value": f"{n_open} open",
             "sub": f"{len(closed)} closed, excluded",
             "rows": [("Filed today", f"{n_filed} of {n_open}")],
             "key": (f"Under {_rs(PORTFOLIO_DAY_FLOOR)}", str(len(low)))},
        ],
        "traj": {**traj, "note": traj_note},
        "tables": [
            {"title": {"region": "Region", "city": "Cities",
                       "location": "Stores"}[split], "sub": "overall",
             "cols": [{"region": "Region", "city": "City",
                       "location": "Store"}[split], "YTD", "G/D", "MTD", "G/D"],
             "rows": region_rows, "total_last": True},
            {"title": "Brands", "sub": "like to like",
             "cols": ["Brand", "Moved", "G/D"], "rows": brand_rows},
            {"title": "Gained", "sub": "by rupees",
             "cols": ["Store", "Moved", "G/D"], "rows": mover_rows(yl, True)},
            {"title": "Declined", "sub": "by rupees",
             "cols": ["Store", "Moved", "G/D"], "rows": mover_rows(yl, False)},
        ],
        "concentration": {
            "share": (top5["cur"].sum() / tot * 100) if tot else 0,
            "top10": (y.nlargest(10, "cur")["cur"].sum() / tot * 100) if tot else 0,
            "top1_name": str(top1["location"]) if top1 is not None else "—",
            "top1_share": (top1["cur"] / tot * 100) if (top1 is not None and tot) else 0,
        },
    }


# --------------------------------------------------------------------------- #
# Metrics — VFL
# --------------------------------------------------------------------------- #
def vfl_metrics(df, asof, gen_date=None, basis_label="", region=None) -> dict:
    """VFL snapshot, on the pack's TAKEOVER-ANCHORED basis (Manav, 9 Aug).

    Every other sheet in the VFL pack anchors each store's window to its takeover
    date, so the snapshot does too — a summary page disagreeing with the sheets
    behind it is worse than a slightly smaller headline. On the plain fiscal
    Apr-1 basis the same YTD reads Rs 31.61 Cr / +8.2% instead of Rs 27.40 Cr /
    +8.4%; the difference is South's pre-takeover April.

    VFL needs no like to like split: it retains South's pre-takeover history, so
    all 22 stores already compare against a real last year.
    """
    import loader as L
    asof = pd.Timestamp(asof)
    gen_date = asof if gen_date is None else pd.Timestamp(gen_date)
    if region:
        # Scope the whole page, so every figure below is this region's own.
        _m = L.load_store_master()
        _reg = dict(zip(_m["tableau_name"], _m["region"]))
        df = df[df[L.COL_STORE_LABEL].map(_reg) == region]

    ytd = L.window_yoy_takeover(df, "YTD", asof=asof)
    mtd = L.window_yoy_takeover(df, "MTD", asof=asof)
    y_ty, y_ly = ytd["cur"]["sales"], ytd["prior"]["sales"]
    m_ty, m_ly = mtd["cur"]["sales"], mtd["prior"]["sales"]

    cur, pri = L.report_frames(df, "YTD", asof=asof)
    amt = L.COL_AMOUNT
    traj = _monthly(cur, pri, asof, amt)

    g_ty = cur.groupby(L.COL_MWC)[amt].sum()
    g_ly = pri.groupby(L.COL_MWC)[amt].sum()
    g_tot = g_ty.sum()
    gender_rows = []
    for seg in ["MEN", "WOMEN", "CHILD"]:
        if seg not in g_ty.index:
            continue
        v = float(g_ty[seg])
        gender_rows.append([seg.title(), _cr(v), f"{v / g_tot * 100:,.1f}%",
                            _pct(_growth(v, float(g_ly.get(seg, 0))))])
    gender_rows.append(["Total", _cr(g_tot), "100.0%",
                        _pct(_growth(g_tot, float(g_ly.sum())))])

    bl = L.brand_line_vfl(cur)
    bl_ly = L.brand_line_vfl(pri)
    t_ty = cur.assign(_b=bl).groupby("_b")[amt].sum()
    t_ly = pri.assign(_b=bl_ly).groupby("_b")[amt].sum()
    line_rows = [[str(i).title(), _cr(float(v)),
                  _pct(_growth(float(v), float(t_ly.get(i, 0))))]
                 for i, v in t_ty.sort_values(ascending=False).items()]

    sy = L.store_yoy(df, kind="YTD", asof=asof).copy()
    sy["shortfall"] = sy["cur"] - sy["prior"]

    def mover_rows(best):
        """EVERY store that moved that way, not a top-n."""
        f = sy[sy["shortfall"] > 0].sort_values("shortfall", ascending=False) \
            if best else sy[sy["shortfall"] < 0].sort_values("shortfall")
        if not len(f):
            return [["No last-year comparison", "—", "—"]]
        return [[str(r["store"])[:18], _rupee_move(r["shortfall"]), _pct(r["growth"])]
                for _, r in f.iterrows()]

    tot = sy["cur"].sum()
    top5 = sy.nlargest(5, "cur")
    top1 = top5.iloc[0] if len(top5) else None

    # A closed store sits at zero every day and would otherwise head the
    # attention list forever — Roodraksh (shut 31-Jul) did exactly that. The
    # frames are keyed by store label, the closure map by code, so map across.
    master = L.load_store_master()[["tableau_name", "code"]]
    shut = L.closed_map()
    closed_labels = {
        str(n) for n, c in zip(master["tableau_name"], master["code"])
        if pd.notna(c) and int(c) in shut
        and pd.to_datetime(shut[int(c)]) <= asof
    }
    day_by = cur[cur["date"] == asof].groupby(L.COL_STORE_LABEL)[amt].sum()
    low = sorted([(str(s)[:15], None, float(v)) for s, v in day_by.items()
                  if str(s) not in closed_labels and v < VFL_DAY_FLOOR],
                 key=lambda t: t[2])
    n_open = int(sy[~sy["store"].astype(str).isin(closed_labels)]["cur"].gt(0).sum())

    return {
        "title": "Executive Snapshot",
        "subtitle": "VFL  ·  Manyavar & Mohey" + (f"  ·  {region}" if region else ""),
        "region": region,
        "stamp": [
            f"As of {asof:%d %b %Y}",
            basis_label or f"Live to {asof:%d %b %Y}",
            f"{len(sy)} stores  |  {n_open} trading",
            "Takeover-anchored — all stores comparable",
        ],
        "tiles": [
            {"label": "Year to date", "value": f"Rs {_cr(y_ty)} Cr",
             "sub": f"LY Rs {_cr(y_ly)} Cr", "rows": [],
             "key": ("Growth", _pct(_growth(y_ty, y_ly)))},
            {"label": "Month to date", "value": f"Rs {_cr(m_ty)} Cr",
             "sub": f"LY Rs {_cr(m_ly)} Cr", "rows": [],
             "key": ("Growth", _pct(_growth(m_ty, m_ly)))},
            {"label": f"Day {asof:%d %b}",
             "value": f"Rs {_cr(cur[cur['date'] == asof][amt].sum())} Cr",
             "sub": "same date last year", "rows": [],
             "key": ("Growth", _pct(_growth(
                 cur[cur["date"] == asof][amt].sum(),
                 pri[pri["date"] == asof - pd.DateOffset(years=1)][amt].sum())))},
            {"label": "How  ·  bills & basket", "value": "Fewer, bigger",
             "sub": "", "small_value": True,
             "rows": [("Bills", _pct(ytd["growth"]["bills"])),
                      ("Units", _pct(ytd["growth"]["units"]))],
             "key": ("Ticket", _pct(ytd["growth"]["atv"]))},
            {"label": "Breadth",
             "value": f"{int((sy['shortfall'] > 0).sum())} up  "
                      f"{int((sy['shortfall'] < 0).sum())} dn",
             "sub": f"year to date, of {len(sy)}", "rows": [],
             "key": ("Total still", _pct(_growth(y_ty, y_ly)))},
            {"label": "Concentration",
             "value": f"{(top5['cur'].sum() / tot * 100) if tot else 0:,.1f}%",
             "sub": "top 5 stores", "rows": [],
             "key": (str(top1["store"])[:14] if top1 is not None else "—",
                     f"{(top1['cur'] / tot * 100) if (top1 is not None and tot) else 0:,.1f}%")},
        ],
        "traj": {**traj, "note": "Rs crore by month"},
        "tables": [
            {"title": "Men / Women / Kids", "sub": "year to date",
             "cols": ["Segment", "YTD", "Mix", "G/D"], "rows": gender_rows,
             "total_last": True},
            {"title": "Brand lines", "sub": "year to date",
             "cols": ["Line", "YTD", "G/D"], "rows": line_rows},
            {"title": "Gained", "sub": "by rupees",
             "cols": ["Store", "Moved", "G/D"], "rows": mover_rows(True)},
            {"title": "Declined", "sub": "by rupees",
             "cols": ["Store", "Moved", "G/D"], "rows": mover_rows(False)},
        ],
        "concentration": None,
    }


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
# Uniform scale for the whole page. The pack forces one page height across the
# document (set by the 35-row GD sheet), which leaves the snapshot's natural
# layout filling only about half of it. Rather than waste that, the page is
# rendered LARGER — every dimension and font size multiplied by `_K` — so it
# fills the box it is given. Scaling the drawing, not the finished bitmap, keeps
# the engine's rasterise-once-never-resample rule intact: bigger text here is
# genuinely bigger, not an upscaled image. Rendering is serialised under the
# engine's `_LOCK`, so a module-level factor is safe.
_K = 1.0


def _p(n) -> int:
    return _px(int(round(n * _K)))


def _f(size):
    return _ft(max(8, int(round(size * _K))))


def _neg(text: str) -> bool:
    return str(text).strip().startswith("-")


def _ink(text) -> tuple:
    return NEG_INK if _neg(text) else INK


def _cell(d, box, text, font, fill=None, align="l", pad=None, color=None):
    x0, y0, x1, y1 = box
    if fill is not None:
        d.rectangle([x0, y0, x1, y1], fill=fill)
    d.rectangle([x0, y0, x1, y1], outline=GRID, width=1)
    if text == "":
        return
    pad = _p(6) if pad is None else pad
    w = d.textlength(str(text), font=font)
    a, dsc = font.getmetrics()
    ty = y0 + max(0, ((y1 - y0) - (a + dsc)) // 2)
    tx = x0 + pad if align == "l" else x1 - pad - w
    d.text((tx, ty), str(text), font=font, fill=color or _ink(text))


def _tiles(d, x, y, w, h, tiles):
    n = len(tiles)
    gap = _p(10)
    tw = (w - gap * (n - 1)) / n
    lab, labb = _f(19)
    _, big = _f(37)
    sml, smlb = _f(18)
    hh = _p(30)
    for i, t in enumerate(tiles):
        x0 = int(round(x + i * (tw + gap)))
        x1 = int(round(x0 + tw))
        d.rectangle([x0, y, x1, y + h], outline=GRID, width=2)
        d.rectangle([x0, y, x1, y + hh], fill=HDR_BG)
        d.rectangle([x0, y, x1, y + hh], outline=GRID, width=2)
        d.text((x0 + _p(7), y + _p(6)), t["label"].upper(), font=labb, fill=INK)
        vy = y + hh + _p(8)
        vfont = smlb if t.get("small_value") else big
        d.text((x0 + _p(7), vy), t["value"], font=vfont, fill=INK)
        vy += _p(26) if t.get("small_value") else _p(44)
        if t.get("sub"):
            d.text((x0 + _p(7), vy), t["sub"], font=sml, fill=MUTED_INK)
            vy += _p(24)
        rows = list(t.get("rows", []))
        key = t.get("key")
        for k, v in rows:
            d.text((x0 + _p(7), vy), k, font=sml, fill=MUTED_INK)
            vw = d.textlength(str(v), font=sml)
            d.text((x1 - _p(7) - vw, vy), str(v), font=sml, fill=_ink(v))
            vy += _p(22)
        if key:
            d.line([x0 + _p(7), vy + _p(2), x1 - _p(7), vy + _p(2)],
                   fill=(150, 150, 150), width=1)
            vy += _p(7)
            d.text((x0 + _p(7), vy), key[0], font=smlb, fill=INK)
            vw = d.textlength(str(key[1]), font=smlb)
            d.text((x1 - _p(7) - vw, vy), str(key[1]), font=smlb, fill=_ink(key[1]))


def _trajectory(d, x, y, w, h, tr):
    """Grouped bars, this year against last, with growth called out per month.

    The current month is a PART month and is hatched with its day count on the
    axis: unmarked, a short final bar beside four full ones reads as a collapse
    rather than as a month that is only a third over.
    """
    sml, smlb = _f(18)
    lab, labb = _f(19)
    d.rectangle([x, y, x + w, y + h], outline=GRID, width=2)

    d.text((x + _p(9), y + _p(7)), tr.get("note", ""), font=sml, fill=MUTED_INK)
    lx = x + w - _p(9)
    for text, col in (("Last year", BAR_LY), ("This year", BAR_TY)):
        tw = d.textlength(text, font=sml)
        d.text((lx - tw, y + _p(7)), text, font=sml, fill=MUTED_INK)
        sq = _p(13)
        d.rectangle([lx - tw - _p(8) - sq, y + _p(8),
                     lx - tw - _p(8), y + _p(8) + sq], fill=col, outline=GRID)
        lx -= tw + sq + _p(24)

    # Fixed rows, so nothing can collide: growth % gets its own band, and the
    # plot top is held far enough below it to clear a full-height bar's value
    # label. An earlier version anchored both to the same y and April printed
    # "4.7*1.6%" — the tallest bar's value ran straight through its growth label.
    gd_y = y + _p(38)
    axis_h = _p(30)
    base = y + h - axis_h
    plot_top = y + _p(64)
    plot_h = base - plot_top - _p(22)
    n = len(tr["months"])
    if n == 0:
        return
    peak = max(list(tr["ty"]) + list(tr["ly"]) + [1.0])
    gw = w / n
    for i, mon in enumerate(tr["months"]):
        cx = x + i * gw + gw / 2
        ty_v, ly_v = tr["ty"][i], tr["ly"][i]
        gd = _growth(ty_v, ly_v)
        part = (i == n - 1)
        bw = min(_p(64), gw * 0.22)
        for j, (val, col) in enumerate(((ty_v, BAR_TY), (ly_v, BAR_LY))):
            bh = max(1, int(round(plot_h * (val / peak))))
            bx0 = cx + (j - 1) * (bw + _p(4)) + _p(2)
            bx1 = bx0 + bw
            d.rectangle([bx0, base - bh, bx1, base], fill=col, outline=GRID, width=1)
            if part:                       # hatch the incomplete month
                step = _p(7)
                yy = base - bh
                while yy < base:
                    d.line([bx0 + 1, min(yy + step, base), min(bx0 + step, bx1 - 1), yy],
                           fill=WHITE, width=1)
                    yy += step
            vs = f"{val / 1e7:,.2f}"
            vw = d.textlength(vs, font=sml)
            d.text((bx0 + (bw - vw) / 2, base - bh - _p(20)), vs, font=sml,
                   fill=FAINT_INK)
        gs = _pct(gd)
        gw_ = d.textlength(gs, font=smlb)
        d.text((cx - gw_ / 2, gd_y), gs, font=smlb, fill=_ink(gs))
        ms = mon if not part else f"{mon}  ({tr['part_days']} days)"
        mw = d.textlength(ms, font=labb if not part else lab)
        d.text((cx - mw / 2, base + _p(6)), ms,
               font=labb if not part else lab, fill=INK if not part else MUTED_INK)
    d.line([x + _p(4), base, x + w - _p(4), base], fill=GRID, width=2)


def _table(d, x, y, w, tbl, row_h, head_h):
    sml, smlb = _f(18)
    lab, labb = _f(19)
    d.text((x, y), tbl["title"].upper(), font=labb, fill=INK)
    tw = d.textlength(tbl["title"].upper(), font=labb)
    if tbl.get("sub"):
        d.text((x + tw + _p(8), y + _p(2)), tbl["sub"], font=sml, fill=FAINT_INK)
    y += _p(24)

    cols = tbl["cols"]
    ncol = len(cols)
    first = w * (0.40 if ncol <= 3 else 0.30)
    rest = (w - first) / (ncol - 1)
    xs = [x] + [x + first + i * rest for i in range(ncol)]
    for i, c in enumerate(cols):
        _cell(d, (xs[i], y, xs[i + 1], y + head_h), c, smlb, fill=HDR_BG,
              align="l" if i == 0 else "r", color=INK)
    y += head_h
    total_last = tbl.get("total_last")
    rows = tbl["rows"]
    for r_i, row in enumerate(rows):
        is_total = total_last and r_i == len(rows) - 1
        for i, v in enumerate(row):
            _cell(d, (xs[i], y, xs[i + 1], y + row_h), v,
                  smlb if is_total else sml,
                  fill=PP.TOTAL_BG if is_total else WHITE,
                  align="l" if i == 0 else "r")
        y += row_h
    return y


def _concentration(d, x, y, w, conc):
    sml, smlb = _f(18)
    lab, labb = _f(19)
    _, big = _f(30)
    h = _p(136)
    d.rectangle([x, y, x + w, y + h], outline=GRID, width=2)
    d.text((x + _p(8), y + _p(8)), "CONCENTRATION", font=labb, fill=INK)
    d.text((x + _p(8), y + _p(30)), f"{conc['share']:,.1f}%", font=big, fill=INK)
    d.text((x + _p(8), y + _p(68)),
           f"of turnover, top 5   top 10 = {conc['top10']:,.1f}%",
           font=sml, fill=MUTED_INK)
    d.text((x + _p(8), y + _p(90)),
           f"{conc['top1_name'][:20]} alone {conc['top1_share']:,.1f}%",
           font=smlb, fill=INK)
    bx0, bx1 = x + _p(8), x + w - _p(8)
    by = y + _p(114)
    bh = _p(12)
    s1 = conc["top1_share"] / 100.0
    s5 = conc["share"] / 100.0
    d.rectangle([bx0, by, bx1, by + bh], fill=BAR_LY)
    d.rectangle([bx0, by, bx0 + (bx1 - bx0) * s5, by + bh], fill=(127, 166, 196))
    d.rectangle([bx0, by, bx0 + (bx1 - bx0) * s1, by + bh], fill=BAR_TY)
    d.rectangle([bx0, by, bx1, by + bh], outline=GRID, width=1)
    return h


def _plan(m):
    """Band heights at the current scale, and the total they need."""
    row_h, head_h = _p(34), _p(32)
    gap = _p(16)
    tiles_h, traj_h = _p(178), _p(360)
    strip_h = max(_p(44), _p(21) * len(m["stamp"]))
    body_rows = max(len(t["rows"]) for t in m["tables"])
    body_h = _p(26) + head_h + body_rows * row_h
    if m.get("concentration"):
        # Concentration is drawn BELOW the first table, so the band has to hold
        # both — not whichever is taller. Taking the max worked only while that
        # table was three region rows; at nine store rows the box fell off the
        # page entirely.
        first_rows = len(m["tables"][0]["rows"])
        body_h = max(body_h,
                     _p(26) + head_h + first_rows * row_h + _p(12) + _p(136))
    total = strip_h + _p(8) + gap + tiles_h + gap + traj_h + gap + body_h
    return dict(row_h=row_h, head_h=head_h, gap=gap, tiles_h=tiles_h,
                traj_h=traj_h, strip_h=strip_h, body_h=body_h, total=total)


def content(m, width, max_height=None) -> Image.Image:
    """Render the snapshot at `width`, scaled to fill `max_height` if given.

    The pack forces one page height on every page (the 35-row GD sheet sets it),
    so at natural size the snapshot filled barely half the page. It is therefore
    drawn at a uniform scale factor chosen to fill the box — which makes the type
    larger rather than merely stretching a bitmap. Capped at 1.75x so a very tall
    pack can't inflate it into a poster.
    """
    global _K
    width = int(width)
    _K = 1.0
    plan = _plan(m)
    if max_height:
        _K = max(1.0, min(1.75, float(max_height) / plan["total"]))
        plan = _plan(m)

    row_h, head_h, gap = plan["row_h"], plan["head_h"], plan["gap"]
    tiles_h, traj_h = plan["tiles_h"], plan["traj_h"]
    strip_h, body_h = plan["strip_h"], plan["body_h"]
    height = min(plan["total"], int(max_height)) if max_height else plan["total"]

    img = Image.new("RGB", (width, int(height)), WHITE)
    d = ImageDraw.Draw(img)
    sml, smlb = _f(18)
    _, hdr = _f(26)

    x, w, y = 0, width, 0

    # identity strip — the cover's title and stamp, folded in
    d.text((x, y), m["subtitle"].upper(), font=hdr, fill=MAROON)
    sy = y
    for line in m["stamp"]:
        lw = d.textlength(line, font=sml)
        d.text((x + w - lw, sy), line, font=sml, fill=MUTED_INK)
        sy += _p(21)
    y = strip_h + _p(8)
    d.line([x, y, x + w, y], fill=GRID, width=2)
    y += gap

    _tiles(d, x, y, w, tiles_h, m["tiles"])
    y += tiles_h + gap

    _trajectory(d, x, y, w, traj_h, m["traj"])
    y += traj_h + gap

    ncol = len(m["tables"])
    cgap = _p(14)
    cw = (w - cgap * (ncol - 1)) / ncol
    for i, t in enumerate(m["tables"]):
        cx = int(round(x + i * (cw + cgap)))
        end = _table(d, cx, y, int(cw), t, row_h, head_h)
        if i == 0 and m.get("concentration"):
            _concentration(d, cx, end + _p(12), int(cw), m["concentration"])
    return img
