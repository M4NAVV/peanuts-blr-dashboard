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
ways and both are printed. Total growth reads +115% because the eight South
stores have no last year at all; like to like reads +1.7%, and the month +0.1%
against a total of +138%. A page that printed only the first number would be a
misread waiting to happen, and the gap between the two is itself the finding.

★★ LIKE TO LIKE IS A WINDOW PER STORE, NOT A LIST OF STORES (Manav, 14 Aug).
His rule, verbatim: *"L2L comparison is CONSIDERED only from the date the store
has data last year (eg Silchar L2L starts only from the date sales are captured
in LY). Similarly for closed stores L2L stops from the day it closes this year.
Same will apply to both the parts, VFL and overall."*

  So a store is not in or out — it contributes the SPAN over which it has both
  years, and the same span is applied to each. Silchar, which opened on 1 June
  last year, counts from June in both years instead of counting wholly (which
  compared 4.5 months against 2.5 and read +113.8%) or not at all. Roodraksh,
  shut on 31 July, counts to 31 July in both. `l2l_bounds` computes the spans,
  `l2l_frames` cuts a pair of window frames to them, `l2l_store_table` sums per
  store; the tiles, the trajectory, breadth, brands and movers all read those.

  ★ THE PROPERTY THAT MAKES IT THE RIGHT RULE: every rupee of LAST year is still
  compared — like to like's last-year total comes out at the whole estate's
  last-year turnover to the rupee. Only THIS year's sales with no counterpart are
  held out. Both earlier definitions threw away real last-year trade.

  ⚠ IT THEREFORE NO LONGER EQUALS THE GD SHEET'S OLD SUBTOTAL, and should not.
  That sheet classifies each store NEW or OLD and totals whole stores; this asks
  a different and better question. The two sat at +1.7% and +2.5% the day this
  shipped. The stamp says which is which.

★ ONE DEFINITION, BOTH FEEDS. An early draft mixed a 44-store set (from the YTD
window) with a 41-store set (from the MTD window) and printed -7.3% and -10.1%
for the same month. Portfolio and VFL now call the same three functions, keyed by
code and by store label respectively — and because the spans are read from the
DATA, neither needs a DOO column, which is what lets South be comparable on the
VFL feed (where its previous operator's history lives) and not on the portfolio
feed (where it does not) with no special case for either.

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
# The growth strip above the bars: the workbook's header blue, thinned so it
# reads as a band without competing with the bars drawn in the same hue.
BAND_BG = (241, 248, 251)
BAND_RULE = (214, 228, 235)
CITY_LAB = (130, 130, 130)

# Day-sale floors. The attention band that used them was removed from the
# snapshot on Manav's instruction (11 Aug); the floors stay because the tile
# still reports how many stores fall under one.
PORTFOLIO_DAY_FLOOR = 10_000
VFL_DAY_FLOOR = 50_000

MOVERS_N = 6
TRAJ_MONTHS = 5

# Brands that are one brand seen from the store master's point of view. Manav,
# 13 Aug: "some stores are Manyavar only and some are Manyavar and Mohey — from
# the brand perspective they should be combined, because same brand." The
# master's value describes what a STORE carries, which is a format, not a
# separate brand; ten stores were filed under MANYAVAR and twelve under
# MANYAVAR & MOHEY, so the table showed one brand twice and neither row was the
# brand's real movement.
#
# Applied where the Brands table is built, and nowhere else: a store's own brand
# attribute stays exactly as the master states it, so filters, the Brand-wise GD
# sheet (which groups by parent company) and every other report are untouched.
BRAND_FOLD = {
    "MANYAVAR": "MANYAVAR & MOHEY",
    "MOHEY": "MANYAVAR & MOHEY",
}


def _brand_fold(s) -> str:
    return BRAND_FOLD.get(str(s).strip().upper(), s)


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
    """Stores on THIS page shut on or before as-of, from the STORE MASTER.

    The master is the authority (13 Aug) and `closed_map` is what the report
    windows themselves read. This function used to read the `closed` column of
    the committed attributes file instead — which knew 3 closures where the
    master knew 13 — so page 1 could call a store open while the windows behind
    it treated it as closed. Two sources for one fact is how they drift.

    Scoped to the stores this page is about: read off the master alone, a region
    page counts closures in another region, which is how South once printed
    "8 stores | 1 closed" for a store shut in East.
    """
    import portfolio_loader as PL
    here = set(int(c) for c in PL.active_codes(pf, asof))
    shut = PL.closed_map()
    return {c for c in here
            if c in shut and pd.to_datetime(shut[c]) <= pd.Timestamp(asof)}


def l2l_bounds(raw, key, amt, shut, asof, opened=None):
    """Each store's LIKE TO LIKE span, in THIS year's dates. (Manav, 14 Aug.)

    His rule, verbatim: *"L2L comparison is CONSIDERED only from the date the
    store has data last year (eg Silchar L2L starts only from the date sales are
    captured in LY). Similarly for closed stores L2L stops from the day it closes
    this year. Same will apply to both the parts, VFL and overall."*

    So like to like is not a list of stores, it is a WINDOW PER STORE, and the
    same window is applied to both years. A store that opened last June counts
    from June in both; a store that shut in July counts up to July in both.
    Nothing is thrown away wholesale — Silchar contributes the three months it
    can be compared over instead of contributing all of them or none.

    ★ THE PROPERTY THIS BUYS, AND IT IS THE POINT: EVERY RUPEE OF LAST YEAR IS
    STILL COMPARED. Last year's like to like total comes out at the whole
    estate's last-year turnover to the rupee (Rs 17.61 Cr today); only THIS
    year's sales that have no counterpart are held out. The old rule dropped
    both sides of a store and lost real last-year trade with it.

    `start` is the store's first ACTUAL SALE mapped forward a year — "the date
    sales are captured", his words, not the date a row appears. The difference is
    one store today: Mani Square Colorplus is in the sheet from 1 Apr 2025 but at
    zero for 36 days, first selling on 7 May. It is an old store, yet it has no
    last-year April to compare this April against, and counting one is exactly
    the distortion this rule exists to stop. Switch to first ROW here if that is
    ever the wrong call.

    Mapping forward a year also makes this self-correcting on either feed: a
    store trading since 2012 has its first sale at the feed's own left edge, so
    `start` lands on or before the window and clips nothing. South clips to
    nothing in the portfolio feed (first sale = the takeover) and to the full
    window in the VFL feed (which keeps the previous operator's history) —
    without either loader knowing which feed it is.
    """
    first = raw[raw[amt] > 0].groupby(key)["date"].min()
    asof = pd.Timestamp(asof)
    start, end = {}, {}
    for k, f in first.items():
        if pd.isna(f):
            continue
        # ★★ THE SPAN OPENS ON THE STORE'S OPENING DATE (Manav, 17 Aug), when one
        # is known. It used to open on the store's first SALE, which conflated
        # two different things: a store that did not exist yet, and a store that
        # existed and was shut. Ours shut all the time — renovations, mall works,
        # a strike — and clipping an established store for it read as if it had
        # opened late. Mani Square Colorplus, trading since 2017, lost five weeks
        # of comparison because it was dark last April; Cosmos Mall lost two days
        # for a bank holiday. On opening dates only a genuinely new store clips,
        # which is the systematic answer.
        #
        # ★ A DATE CANNOT BE AN OPENING IF WE HAVE THE STORE'S SALES FROM BEFORE
        # IT. South's recorded date is 19 April 2026 — the day we took the stores
        # over, not the day they opened — and the VFL feed carries the previous
        # operator's trading for them going back a year. Read literally it would
        # throw all eight South stores out of like to like, on a feed that holds
        # exactly the history they are supposed to be compared against. So an
        # opening date that post-dates the store's own sales is a takeover, and
        # the trading starts where the trading starts. The portfolio feed has no
        # pre-takeover South rows, so there the date stands and South is
        # correctly not comparable — one rule, right on both feeds.
        o = pd.to_datetime((opened or {}).get(k), errors="coerce")
        if pd.notna(o) and pd.Timestamp(f) < o:
            o = pd.NaT
        base = o if pd.notna(o) else pd.Timestamp(f)
        start[k] = base + pd.DateOffset(years=1)
        cl = pd.to_datetime(shut.get(k), errors="coerce")
        end[k] = min(asof, cl) if pd.notna(cl) else asof
    return start, end


def l2l_frames(cur, pri, bounds, key):
    """(current, prior) restricted to each store's like to like span.

    The prior frame is shifted by exactly a year, so both sides cover the same
    calendar span for that store and the comparison is symmetric by
    construction rather than by two separate filters agreeing.
    """
    start, end = bounds
    yr = pd.DateOffset(years=1)

    def cut(fr, shift):
        if fr.empty:
            return fr
        s = fr[key].map(start)
        e = fr[key].map(end)
        if shift:
            s, e = s - yr, e - yr
        return fr[s.notna() & (fr["date"] >= s) & (fr["date"] <= e)]

    return cut(cur, False), cut(pri, True)


def l2l_store_table(cur, pri, bounds, ident, key, amt):
    """Per-store like to like TY/LY, carrying `ident`'s identity columns.

    Stores with no comparable span at all (Dibrugarh: its last year begins after
    this window ends) fall out here, which is how "no last year" states itself
    rather than arriving as a zero.
    """
    c, p = l2l_frames(cur, pri, bounds, key)
    ty = c.groupby(key)[amt].sum().rename("cur")
    ly = p.groupby(key)[amt].sum().rename("prior")
    t = pd.concat([ty, ly], axis=1).fillna(0.0).reset_index()
    t = t[t["prior"] > 0]                       # nothing to be like to like with
    keep = [c for c in ident.columns if c not in ("cur", "prior",
                                                  "growth", "shortfall")]
    out = ident[keep].merge(t, on=key, how="inner")
    out["shortfall"] = out["cur"] - out["prior"]
    out["growth"] = out.apply(
        lambda r: ((r["cur"] - r["prior"]) / r["prior"] * 100)
        if r["prior"] else None, axis=1)
    return out


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

    y = PL.store_yoy(pf, kind="YTD", asof=asof)
    m = PL.store_yoy(pf, kind="MTD", asof=asof)

    # LIKE TO LIKE = each store over the span it has BOTH years (see `l2l_bounds`
    # for Manav's rule). The windows come off the report's own frames, so the
    # anchoring and closure handling below them is untouched.
    # Opening dates, so page 1 and the GD sheet compare over the same spans.
    bounds = l2l_bounds(pf, "code", "sales", PL.closed_map(), asof,
                        opened=PL.opened_map(pf, asof))
    ycur, ypri = PL._window_frames(pf, "YTD", asof)
    mcur, mpri = PL._window_frames(pf, "MTD", asof)
    yl = l2l_store_table(ycur, ypri, bounds, y, "code", "sales")
    ml = l2l_store_table(mcur, mpri, bounds, m, "code", "sales")
    lfl = set(int(c) for c in yl["code"])

    ytd_all, ytd_ly = y["cur"].sum(), y["prior"].sum()
    mtd_all, mtd_ly = m["cur"].sum(), m["prior"].sum()
    ytd_l, ytd_ll = yl["cur"].sum(), yl["prior"].sum()
    mtd_l, mtd_ll = ml["cur"].sum(), ml["prior"].sum()

    # Day: the whole estate for the headline figure, like to like for the rate.
    # Same WEEKDAY is the honest comparison — a single date a year ago lands on a
    # different day of the week and its year-on-year is mostly noise.
    #
    # A store counts on the day only if TODAY falls inside its own like to like
    # span — which is the same rule as everywhere else on this page, asked of one
    # date. It drops a store shut in July (its span ended there, and it would
    # otherwise put a live 15-Aug LAST year against a guaranteed zero today) and
    # it keeps Silchar, whose span opened in June and covers today on both sides.
    _b_start, _b_end = bounds
    _day_set = {c for c in lfl
                if _b_start.get(c) is not None and _b_start[c] <= asof <= _b_end[c]}
    day_all = pf[pf["date"] == asof]["sales"].sum()
    dl = pf[pf["code"].isin(_day_set)]
    d_ty = dl[dl["date"] == asof]["sales"].sum()
    d_date = dl[dl["date"] == asof - pd.DateOffset(years=1)]["sales"].sum()
    d_wday = dl[dl["date"] == asof - pd.Timedelta(days=364)]["sales"].sum()

    mets = PL._gd_store_metrics(pf, asof)
    proj = sum(v["proj_ytd"] for v in mets.values())
    ly_full = sum(v["ly_full"] for v in mets.values())

    # Floor space actually being traded from, and what it earns. Carpet comes
    # from the store master; closed stores are excluded from both sides, so the
    # area and the sales that divide by it describe the same estate.
    # Throughput is annualised — the projected year over the area — because a
    # part-year figure understates it and is not comparable with the month-wise
    # report's own throughput, which annualises the same way.
    import master_lookup
    carpet_map = master_lookup.carpet()
    open_codes = set(int(c) for c in y["code"]) - closed
    # ★ A STORE WITH NO CARPET FIGURE LEAVES BOTH SIDES OF THE RATIO, not just
    # the bottom. `carpet_map.get(c, 0)` gave it zero floor space while its
    # sales stayed in the numerator, so throughput rose and the page said
    # nothing. Every open store has a figure today, so this moves no number —
    # it bites the day a store opens before the master's CARPET cell is filled,
    # which is the normal order of events.
    measured = {c for c in open_codes if (carpet_map.get(c) or 0) > 0}
    area = float(sum(carpet_map[c] for c in measured))
    proj_open = sum(v["proj_ytd"] for c, v in mets.items()
                    if int(c) in measured)
    throughput = (proj_open / area) if area else None
    unmeasured = len(open_codes) - len(measured)

    # South has NO last year in the portfolio feed, so its like to like set is
    # empty and a like to like trajectory would be five zero bars — a page that
    # looks broken rather than one that says "no comparison exists". Fall back to
    # every store: the current-year shape is real and worth seeing, and the
    # absent last-year bars state the situation themselves.
    # Each bar is built from the same per-store spans, so a store joins the
    # months it is comparable in and sits out the ones it is not: Silchar is
    # absent from April and May and present from June, on both sides of the bar.
    if lfl:
        _c, _p = l2l_frames(ycur, ypri, bounds, "code")
        traj_note = "Like to like, Rs crore by month"
    else:
        _c, _p = ycur, ypri
        traj_note = "Overall, Rs crore by month — no last year to compare"
    traj = _monthly(_c, _p, asof, "sales")

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
        b = yl.assign(brand=yl["brand"].map(_brand_fold)) \
              .groupby("brand")[["cur", "prior"]].sum()
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
            f"Like to like = {len(lfl)} stores, each over its comparable span",
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
             # A store still waiting on its CARPET cell is named here rather
             # than silently lifting the rate it is left out of.
             "rows": [("Carpet area",
                       (f"{area:,.0f} sq ft" if area else "—")
                       + (f"  ·  {unmeasured} unmeasured" if unmeasured else ""))],
             "key": ("Throughput / sq ft",
                     f"Rs {throughput:,.0f}" if throughput else "—")},
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
    # Trajectory built LIKE TO LIKE, matching the portfolio page and the tiles
    # above it. It used to count every store: Dibrugarh and Silchar have sales
    # this year and none last, so East read +7.4% in April where comparable
    # stores were at -7.5%, and May +5.3% against -8.5% — a sign flip in both.
    # The spans are attached further down (`vb`), so this is filled in there —
    # together with the city line, Manav's own market movement printed under
    # ours so the page answers whether we are beating the city or losing share.
    # ★ That comparison is the reason the band HAD to move onto like to like:
    # a benchmark for the market is not something to hold our new stores up
    # against. South is unaffected either way (all 8 comparable), so no city
    # figure already published changes.
    traj = None

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
    sm = L.store_yoy(df, kind="MTD", asof=asof).copy()
    sm["shortfall"] = sm["cur"] - sm["prior"]

    def mover_rows(frame, best):
        """EVERY store that moved that way, not a top-n.

        Reads the LIKE TO LIKE table, matching the portfolio page and Manav's
        decision of 10 Aug ("movers by rupees, new stores excluded"). Off the
        whole frame this column had Dibrugarh at +51.6 L against no last year at
        all, and Silchar at +113.8% for months it had no counterpart for.
        """
        f = frame[frame["shortfall"] > 0].sort_values("shortfall", ascending=False) \
            if best else frame[frame["shortfall"] < 0].sort_values("shortfall")
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
    code_of = {str(n): int(c) for n, c in zip(master["tableau_name"], master["code"])
               if pd.notna(c)}
    # Scoped to the stores THIS page is about. Read off the master alone, a
    # region page counted the whole estate's closures — South printed "8 stores
    # | 1 closed | 8 trading" for a store shut in East.
    _here = set(sy["store"].astype(str))
    closed_labels = {
        s for s, c in code_of.items()
        if s in _here and c in shut and pd.to_datetime(shut[c]) <= asof
    }
    day_by = cur[cur["date"] == asof].groupby(L.COL_STORE_LABEL)[amt].sum()
    low = sorted([(str(s)[:15], None, float(v)) for s, v in day_by.items()
                  if str(s) not in closed_labels and v < VFL_DAY_FLOOR],
                 key=lambda t: t[2])
    n_open = int(sy[~sy["store"].astype(str).isin(closed_labels)]["cur"].gt(0).sum())

    # ---- the six tiles the portfolio pack prints, on the VFL feed ------------
    # Manav, 13 Aug: the same tile row on both packs. Same definitions, so a
    # figure means the same thing whichever pack it is read in — which is the
    # whole point of replicating them rather than approximating them.
    #
    # LIKE TO LIKE, on Manav's rule and the portfolio page's exact machinery —
    # `l2l_bounds` / `l2l_store_table`, keyed by store label instead of code
    # ("same will apply to both the parts, VFL and overall"). Each store counts
    # over the span it has both years: Silchar from June, Roodraksh up to 31
    # July, Dibrugarh not at all (its last year begins after this window ends).
    #
    # ★ THE CLOSURE CAP MATTERS MORE HERE THAN IT DOES THERE. `loader.report_frames`
    # has no closure handling at all, so before this Roodraksh's last year ran to
    # as-of against a this-year that stopped on 31 July — a decline it did not
    # have. The rule's "stops from the day it closes" now supplies that cap on
    # this feed, symmetrically, which is why a shut store can finally stay in.
    #
    # ★ AND IT NEEDS NO DOO COLUMN, WHICH IS WHAT MAKES IT WORK ON BOTH FEEDS.
    # The curated `doo` for the eight South stores is 2026-04-19 — our TAKEOVER
    # date, not an opening — while this feed carries the previous operator's full
    # history for them, the whole reason South's last year points here. Reading
    # that attribute threw all eight out. Reading the data keeps them, because
    # their first sale here is the feed's own left edge.
    shut_by_label = {s: shut[c] for s, c in code_of.items()
                     if c in shut and s in _here}
    # Opening dates here too, so both feeds compare on the same rule. South's
    # recorded date is a takeover and `l2l_bounds` sees through it — see there.
    _doo = L.doo_map()
    opened_by_label = {s: _doo[c] for s, c in code_of.items()
                       if c in _doo and s in _here}
    vb = l2l_bounds(df, L.COL_STORE_LABEL, amt, shut_by_label, asof,
                    opened=opened_by_label)
    vy_cur, vy_pri = L.report_frames(df, "YTD", asof=asof)
    vm_cur, vm_pri = L.report_frames(df, "MTD", asof=asof)
    _key = L.COL_STORE_LABEL
    yl = l2l_store_table(vy_cur, vy_pri, vb, sy, _key, amt)
    ml = l2l_store_table(vm_cur, vm_pri, vb, sm, _key, amt)
    lfl = set(yl[_key].astype(str))

    # The trajectory promised above, now that the spans exist.
    if len(yl):
        _c, _p = l2l_frames(cur, pri, vb, _key)
        traj_note = "Like to like, Rs crore by month"
    else:
        _c, _p = cur, pri
        traj_note = "Overall, Rs crore by month — no last year to compare"
    traj = _monthly(_c, _p, asof, amt)
    try:
        import city_growth
        traj["city"] = city_growth.for_months(region, traj["months"], asof)
    except Exception:
        traj["city"] = [None] * len(traj["months"])

    # Day figures come off the WHOLE frame, not the year-to-date windows: the
    # same weekday a year ago (asof - 364) falls one day outside the prior
    # window, so reading it there returns zero and the comparison prints +inf.
    # A store counts today only if today falls inside its own span, exactly as
    # on the portfolio page.
    _vb_start, _vb_end = vb
    _day_set = {s for s in lfl
                if s in _vb_start and _vb_start[s] <= asof <= _vb_end[s]}
    dl = df[df[L.COL_STORE_LABEL].astype(str).isin(_day_set)]
    day_all = float(cur[cur["date"] == asof][amt].sum())
    d_ty = float(dl[dl["date"] == asof][amt].sum())
    d_date = float(dl[dl["date"] == asof - pd.DateOffset(years=1)][amt].sum())
    d_wday = float(dl[dl["date"] == asof - pd.Timedelta(days=364)][amt].sum())

    # Projected year on the SHARED rule (projections.py) with the same last-full-
    # year definition the portfolio pack uses — achieved / days actually traded
    # x 365, frozen for a closed store, against the whole of the prior fiscal
    # year. Projected off `gen_date`, like the GD sheet on page 2, so the tile
    # and the sheet behind it agree.
    import projections as PROJ
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    fy_start = pd.Timestamp(fy_year, 4, 1)
    doo_by_code, tk_by_label = L.doo_map(), L.takeover_map()
    ly_full_by = df[(df["date"] >= pd.Timestamp(fy_year - 1, 4, 1))
                    & (df["date"] <= pd.Timestamp(fy_year, 3, 31))] \
        .groupby(L.COL_STORE_LABEL)[amt].sum()
    # Trailing twelve months, on the same rolling 365-day window the GD sheets
    # and the target pack print — as-of back a year plus a day, so the window is
    # 365 days inclusive and the anniversary is not counted twice. A store whose
    # history does not reach the window's left edge contributes 0 rather than a
    # part year, exactly as it does on the sheets (see `_extra_gd_windows`);
    # here that is Dibrugarh, which opens 23 Jan 2026.
    ttm_start = asof - pd.DateOffset(years=1) + pd.Timedelta(days=1)
    _first = df.groupby(L.COL_STORE_LABEL)["date"].min()
    _short = set(_first[_first > ttm_start].index)
    ttm_by = df[(df["date"] >= ttm_start) & (df["date"] <= asof)
                & ~df[L.COL_STORE_LABEL].isin(_short)] \
        .groupby(L.COL_STORE_LABEL)[amt].sum()
    proj = proj_open = proj_open_all = ly_full = ttm = 0.0
    import master_lookup as _ML
    carpet_by_code = _ML.carpet()
    for _, r in sy.iterrows():
        s = str(r["store"])
        c = code_of.get(s)
        opened = pd.to_datetime(doo_by_code.get(c), errors="coerce") if c else pd.NaT
        if pd.isna(opened):
            opened = pd.to_datetime(tk_by_label.get(s), errors="coerce")
        if pd.isna(opened):
            opened = fy_start
        cl = pd.to_datetime(shut.get(c), errors="coerce") if c else pd.NaT
        p = PROJ.project_ytd(float(r["cur"]), fy_start, opened, gen_date,
                             None if pd.isna(cl) else cl)
        proj += p
        ly_full += float(ly_full_by.get(s, 0.0))
        ttm += float(ttm_by.get(s, 0.0))
        if s not in closed_labels:
            proj_open_all += p
            if (carpet_by_code.get(c) or 0) > 0:      # see the portfolio site
                proj_open += p

    # Floor space being traded from, and what it earns. Closed stores are out of
    # both the area and the sales that divide by it, so the two describe the
    # same estate; throughput is annualised for the same reason it is on the
    # portfolio page — a part year understates it.
    import master_lookup
    carpet_map = master_lookup.carpet()
    open_codes = {code_of[s] for s in sy["store"].astype(str)
                  if s in code_of and s not in closed_labels}
    measured = {c for c in open_codes if (carpet_map.get(c) or 0) > 0}
    area = float(sum(carpet_map[c] for c in measured))
    throughput = (proj_open / area) if area else None
    unmeasured = len(open_codes) - len(measured)

    return {
        "title": "Executive Snapshot",
        "subtitle": "VFL  ·  Manyavar & Mohey" + (f"  ·  {region}" if region else ""),
        "region": region,
        "stamp": [
            f"As of {asof:%d %b %Y}",
            basis_label or f"Live to {asof:%d %b %Y}",
            f"{len(sy)} stores  |  {len(closed_labels)} closed  |  {n_open} trading",
            f"Like to like = {len(lfl)} stores, each over its comparable span",
        ],
        # The portfolio pack's six, definition for definition — see the block
        # above. Bills & basket loses its tile and is not replaced (Manav,
        # 13 Aug: "the displaced tile is not needed"); concentration keeps its
        # figures in the box under the first table, where the portfolio page
        # puts them.
        "tiles": [
            {"label": "Year to date", "value": f"Rs {_cr(y_ty)} Cr",
             "sub": f"LY Rs {_cr(y_ly)} Cr",
             "rows": [("Overall", _pct(_growth(y_ty, y_ly)))],
             "key": ("Like to like",
                     _pct(_growth(yl["cur"].sum(), yl["prior"].sum())))},
            {"label": "Month to date", "value": f"Rs {_cr(m_ty)} Cr",
             "sub": f"LY Rs {_cr(m_ly)} Cr",
             "rows": [("Overall", _pct(_growth(m_ty, m_ly)))],
             "key": ("Like to like",
                     _pct(_growth(ml["cur"].sum(), ml["prior"].sum())))},
            {"label": f"Day {asof:%d %b}", "value": f"Rs {_cr(day_all)} Cr",
             "sub": f"Like to like Rs {_cr(d_ty)} Cr",
             "rows": [("vs same date", _pct(_growth(d_ty, d_date)))],
             "key": ("vs same weekday", _pct(_growth(d_ty, d_wday)))},
            {"label": "Projected year", "value": f"Rs {_cr(proj)} Cr",
             "sub": f"last full year Rs {_cr(ly_full)} Cr",
             "rows": [("Run-rate", "x365 op-days"),
                      ("TTM", f"Rs {_cr(ttm)} Cr")],
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
             "sub": f"{len(closed_labels)} closed, excluded",
             # A store still waiting on its CARPET cell is named here rather
             # than silently lifting the rate it is left out of.
             "rows": [("Carpet area",
                       (f"{area:,.0f} sq ft" if area else "—")
                       + (f"  ·  {unmeasured} unmeasured" if unmeasured else ""))],
             "key": ("Throughput / sq ft",
                     f"Rs {throughput:,.0f}" if throughput else "—")},
        ],
        "traj": {**traj, "note": traj_note},
        "tables": [
            {"title": "Men / Women / Kids", "sub": "year to date",
             "cols": ["Segment", "YTD", "Mix", "G/D"], "rows": gender_rows,
             "total_last": True},
            {"title": "Brand lines", "sub": "year to date",
             "cols": ["Line", "YTD", "G/D"], "rows": line_rows},
            {"title": "Gained", "sub": "by rupees",
             "cols": ["Store", "Moved", "G/D"], "rows": mover_rows(yl, True)},
            {"title": "Declined", "sub": "by rupees",
             "cols": ["Store", "Moved", "G/D"], "rows": mover_rows(yl, False)},
        ],
        # Concentration lost its tile to the portfolio's six and keeps its
        # figures in the box under the first table — the same box, in the same
        # place, that the portfolio page has always drawn.
        "concentration": {
            "share": (top5["cur"].sum() / tot * 100) if tot else 0.0,
            "top10": (sy.nlargest(10, "cur")["cur"].sum() / tot * 100) if tot else 0.0,
            "top1_name": str(top1["store"]) if top1 is not None else "—",
            "top1_share": (top1["cur"] / tot * 100) if (top1 is not None and tot) else 0.0,
        },
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


def _lh(font) -> int:
    """A line's real height for this font — ascender plus descender.

    Line spacing used to be a set of fixed step sizes (44 after the big value,
    24 after the sub, 22 a row) chosen when the page drew at natural size. They
    do not survive `_K`: the type scales up to 1.75x and the steps scale with it,
    but a font's ascender and descender do not grow at the same rate as a number
    someone picked by eye. At 1.664x the gap between "9 up 11 dn" and the line
    under it had closed to nothing and the p descended into it. Stepping by what
    the font actually measures cannot drift that way.
    """
    a, d = font.getmetrics()
    return a + d


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


def _fit(d, text, fonts, avail):
    """The first of `fonts` that fits `text` into `avail`, else the smallest."""
    for f in fonts:
        if d.textlength(str(text), font=f) <= avail:
            return f
    return fonts[-1]


def _kv(d, x0, x1, y, k, v, font, small, pad):
    """A label left, its figure right — stepped down a size if they would meet.

    "Throughput / sq ft" against "Rs 9,429" is the tightest pair in the row, and
    it clears only because of how wide the page happens to be. A tile is not
    guaranteed any particular width, so the row checks rather than assumes.
    """
    vw = d.textlength(str(v), font=font)
    if d.textlength(str(k), font=font) + vw > (x1 - x0) - pad * 2 - _p(8):
        font = small
        vw = d.textlength(str(v), font=font)
    d.text((x0 + pad, y), str(k), font=font, fill=MUTED_INK)
    d.text((x1 - pad - vw, y), str(v), font=font, fill=_ink(v))
    return _lh(font)


def _tiles(d, x, y, w, h, tiles):
    n = len(tiles)
    gap = _p(10)
    tw = (w - gap * (n - 1)) / n
    lab, labb = _f(19)
    _, big = _f(37)
    sml, smlb = _f(18)
    tiny, tinyb = _f(16)
    hh = _lh(labb) + _p(9)        # the label's own height, not a guessed 30
    for i, t in enumerate(tiles):
        x0 = int(round(x + i * (tw + gap)))
        x1 = int(round(x0 + tw))
        d.rectangle([x0, y, x1, y + h], outline=GRID, width=2)
        d.rectangle([x0, y, x1, y + hh], fill=HDR_BG)
        d.rectangle([x0, y, x1, y + hh], outline=GRID, width=2)
        d.text((x0 + _p(7), y + _p(5)), t["label"].upper(), font=labb, fill=INK)
        vy = y + hh + _p(6)
        # The headline and its sub line step down rather than run into the tile
        # beside them — a tile is only ever as wide as the page divided six ways.
        avail = (x1 - x0) - _p(14)
        vfont = (smlb if t.get("small_value")
                 else _fit(d, t["value"], [big, _f(30)[1], _f(24)[1]], avail))
        d.text((x0 + _p(7), vy), t["value"], font=vfont, fill=INK)
        vy += _lh(vfont) + _p(3)
        if t.get("sub"):
            sfont = _fit(d, t["sub"], [sml, tiny, _f(14)[0]], avail)
            d.text((x0 + _p(7), vy), t["sub"], font=sfont, fill=MUTED_INK)
            vy += _lh(sml) + _p(3)
        rows = list(t.get("rows", []))
        key = t.get("key")
        for k, v in rows:
            vy += _kv(d, x0, x1, vy, k, v, sml, tiny, _p(7)) + _p(3)
        if key:
            d.line([x0 + _p(7), vy + _p(2), x1 - _p(7), vy + _p(2)],
                   fill=(150, 150, 150), width=1)
            vy += _p(6)
            kw_ = d.textlength(str(key[1]), font=smlb)
            kf = smlb if (d.textlength(str(key[0]), font=smlb) + kw_
                          <= (x1 - x0) - _p(14) - _p(8)) else tinyb
            kw_ = d.textlength(str(key[1]), font=kf)
            d.text((x0 + _p(7), vy), key[0], font=kf, fill=INK)
            d.text((x1 - _p(7) - kw_, vy), str(key[1]), font=kf, fill=_ink(key[1]))


def _bar_value(d, bx0, bw, top, base, text, font, small, on_dark):
    """Print a bar's value INSIDE the bar, or just above it when it cannot fit.

    Manav, 13 Aug: the figure belongs in the bar, not on top of it. Inside, it
    reads as part of the bar and the plot gets back the band that floating
    labels used to reserve. It only works while the label actually fits, so the
    label steps down one size, and a bar still too short to hold it keeps its
    figure just above — a number half outside its own bar is worse than a
    number above it.
    """
    vw = d.textlength(text, font=font)
    if vw > bw - _p(8):
        font = small
        vw = d.textlength(text, font=font)
    asc, dsc = font.getmetrics()
    lh = asc + dsc
    tx = bx0 + (bw - vw) / 2
    if base - top >= lh + _p(9) and vw <= bw - _p(4):
        d.text((tx, top + _p(5)), text, font=font,
               fill=WHITE if on_dark else INK)
    else:
        d.text((tx, top - lh - _p(3)), text, font=font, fill=FAINT_INK)


def _trajectory(d, x, y, w, h, tr):
    """Grouped bars, this year against last, with growth called out per month.

    The current month is a PART month and is hatched with its day count on the
    axis: unmarked, a short final bar beside four full ones reads as a collapse
    rather than as a month that is only a third over.
    """
    sml, smlb = _f(18)
    lab, labb = _f(19)
    tiny, tinyb = _f(16)
    _, gfont = _f(21)
    d.rectangle([x, y, x + w, y + h], outline=GRID, width=2)

    # Title row, set like the tables below it — a bold uppercase name with its
    # basis as a muted qualifier beside it ("REGION overall", "GAINED by
    # rupees") — so the boxes on the page read as one family, not three
    # treatments. The basis is the note the metrics already carry.
    d.text((x + _p(9), y + _p(7)), "TRAJECTORY", font=labb, fill=INK)
    ttw = d.textlength("TRAJECTORY", font=labb)
    d.text((x + _p(9) + ttw + _p(8), y + _p(9)), str(tr.get("note", "")),
           font=sml, fill=FAINT_INK)
    lx = x + w - _p(9)
    for text, col in (("Last year", BAR_LY), ("This year", BAR_TY)):
        tw = d.textlength(text, font=sml)
        d.text((lx - tw, y + _p(8)), text, font=sml, fill=MUTED_INK)
        sq = _p(14)
        d.rectangle([lx - tw - _p(9) - sq, y + _p(9),
                     lx - tw - _p(9), y + _p(9) + sq], fill=col, outline=GRID)
        lx -= tw + sq + _p(26)
    hdr_b = y + _p(34)
    d.line([x + _p(2), hdr_b, x + w - _p(2), hdr_b], fill=GRID, width=1)

    # Fixed rows, so nothing can collide: the growth figures get their own band,
    # ruled and tinted so they read as a strip belonging to the months below
    # rather than as numbers floating over the plot. An earlier version anchored
    # growth and a bar's value to the same y and April printed "4.7*1.6%".
    has_city = any(v is not None for v in (tr.get("city") or []))
    gd_y = hdr_b + _p(6)
    band_b = gd_y + (_p(52) if has_city else _p(28))
    # Room for the month name UNDER the axis, measured rather than assumed — at
    # 30 the names crossed the box's own bottom border.
    axis_h = _p(6) + _lh(labb) + _p(6)
    base = y + h - axis_h
    # Values now sit inside their bars, so the plot no longer has to reserve a
    # band above the tallest one — it starts just under the growth strip and
    # keeps the full height for the bars.
    plot_top = band_b + _p(10)
    plot_h = base - plot_top
    n = len(tr["months"])
    if n == 0:
        return
    d.rectangle([x + _p(2), hdr_b + 1, x + w - _p(2), band_b], fill=BAND_BG)
    peak = max(list(tr["ty"]) + list(tr["ly"]) + [1.0])
    gw = w / n
    for i in range(1, n):                  # month dividers, inside the strip
        dx = int(round(x + i * gw))
        d.line([dx, hdr_b + 1, dx, band_b], fill=BAND_RULE, width=1)
    d.line([x + _p(2), band_b, x + w - _p(2), band_b], fill=GRID, width=1)
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
            _bar_value(d, bx0, bw, base - bh, base, f"{val / 1e7:,.2f}",
                       smlb, tinyb, on_dark=(j == 0))
        gs = _pct(gd)
        gw_ = d.textlength(gs, font=gfont)
        d.text((cx - gw_ / 2, gd_y), gs, font=gfont, fill=_ink(gs))
        # The city's growth for the same month, where it exists. Set in two
        # tones — a light label, a firmer figure — and kept muted, so ours stays
        # the figure being read and this is the context beneath it.
        city = (tr.get("city") or [None] * n)[i]
        if city is not None:
            # An explicit gap, not a trailing space: the space's advance left
            # the y of "City" touching the sign of the figure beside it.
            cl, cv = "City", f"{city:+,.1f}%"
            clw = d.textlength(cl, font=tiny) + _p(6)
            cvw = d.textlength(cv, font=tinyb)
            c0 = cx - (clw + cvw) / 2
            cy = gd_y + _p(28)
            d.text((c0, cy), cl, font=tiny, fill=CITY_LAB)
            d.text((c0 + clw, cy), cv, font=tinyb, fill=FAINT_INK)
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
    h = _p(BOX_H)
    d.rectangle([x, y, x + w, y + h], outline=GRID, width=2)
    d.text((x + _p(8), y + _p(8)), "CONCENTRATION", font=labb, fill=INK)
    vy = y + _p(30)
    d.text((x + _p(8), vy), f"{conc['share']:,.1f}%", font=big, fill=INK)
    vy += _lh(big) + _p(3)
    d.text((x + _p(8), vy),
           f"of turnover, top 5   top 10 = {conc['top10']:,.1f}%",
           font=sml, fill=MUTED_INK)
    vy += _lh(sml) + _p(3)
    d.text((x + _p(8), vy),
           f"{conc['top1_name'][:20]} alone {conc['top1_share']:,.1f}%",
           font=smlb, fill=INK)
    # The share bar hangs from the BOTTOM of the box rather than following the
    # text, so the box fills its height whatever the text above it needs — and
    # sits level with the bills & basket box beside it.
    bx0, bx1 = x + _p(8), x + w - _p(8)
    bh = _p(14)
    by = y + h - _p(10) - bh
    s1 = conc["top1_share"] / 100.0
    s5 = conc["share"] / 100.0
    d.rectangle([bx0, by, bx1, by + bh], fill=BAR_LY)
    d.rectangle([bx0, by, bx0 + (bx1 - bx0) * s5, by + bh], fill=(127, 166, 196))
    d.rectangle([bx0, by, bx0 + (bx1 - bx0) * s1, by + bh], fill=BAR_TY)
    d.rectangle([bx0, by, bx1, by + bh], outline=GRID, width=1)
    return h


# Height of the under-table box. Sized for the concentration box's own content
# now that every line steps by what its font measures, with its share bar hung
# from the bottom edge.
BOX_H = 148


def _boxes_of(m) -> dict:
    """Which under-table box sits under which column."""
    return {0: ("conc", m["concentration"])} if m.get("concentration") else {}


def _plan(m):
    """Band heights at the current scale, and the total they need."""
    row_h, head_h = _p(34), _p(32)
    gap = _p(16)
    # The tile band holds label strip + value + sub + a row + the ruled key, each
    # now stepping by its font's real height; 178 was sized for the old fixed
    # steps and the key row would sit on the frame.
    _tile_rows = max([len(t.get("rows", ())) for t in m.get("tiles", [])] or [1])
    tiles_h = _p(192) + _p(21) * max(0, _tile_rows - 1)
    traj_h = _p(360)
    strip_h = max(_p(44), _p(21) * len(m["stamp"]))
    body_rows = max(len(t["rows"]) for t in m["tables"])
    body_h = _p(26) + head_h + body_rows * row_h
    # A box is drawn BELOW its table, so the band has to hold both — not
    # whichever is taller. Taking the max worked only while the first table was
    # three region rows; at nine store rows the box fell off the page entirely.
    for i in _boxes_of(m):
        if i < len(m["tables"]):
            body_h = max(body_h,
                         _p(26) + head_h + len(m["tables"][i]["rows"]) * row_h
                         + _p(12) + _p(BOX_H))
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
    boxes = _boxes_of(m)
    for i, t in enumerate(m["tables"]):
        cx = int(round(x + i * (cw + cgap)))
        end = _table(d, cx, y, int(cw), t, row_h, head_h)
        kind, spec = boxes.get(i, (None, None))
        if kind == "conc":
            _concentration(d, cx, end + _p(12), int(cw), spec)
    return img
