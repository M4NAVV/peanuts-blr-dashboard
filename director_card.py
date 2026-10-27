"""The directors' morning card — yesterday, the month and the year on one tall card (27 Oct 2026).

Manav, 27 Oct 2026: "design me a director card, which also goes to the director every morning through whatsapp. this
card doesnt need to follow any size or dimension, but it needs to be very comphrehensive and give a good level of detail
of everything that happened yesterday, and how we are doing at a portfolio level and all that."

One card, read top to bottom:
  1  YESTERDAY      sale · vs the same day last year (like to like) · vs the store's own last 7 days · day target
                    bills · average bill · pieces per bill · conversion (footfall where it was counted)
  2  THE MONTH      month to date · like-to-like growth · achieved against target, coloured against PACE · needed per day
  3  THE YEAR       year to date · like-to-like growth · year target · the estate
  4  REGIONS        East & NE, South, OVERALL — yesterday, month, year, side by side
  5  THE MONTH LINE the month day by day, cumulative, this year against last (like to like) and the target's even pace
  6  EVERY STORE    region › city › store — yesterday, vs its 7 days, day target, month, achieved, needed per day
  7  BRANDS         every brand: yesterday, month, share
  8  NOTES          stores that sold nothing, stores with no figure, what is not counted and why

★ THE SAME DEFINITIONS AS THE REST OF THE DASHBOARD. Month and year growth are the MONTH CARD's (month_brief), region by
region: East & NE like to like off the portfolio sheet, South off the VFL bill feed with its year from the 19 Apr 2026
takeover — the portfolio sheet holds no South last year, so the executive snapshot's "overall" growth is East's alone
and must not be printed as the whole. OVERALL adds the two regions' rupees (this year ÷ last year), never their rates.
The estate and throughput come from exec_snapshot.portfolio_metrics.
Closed stores (storemaster CLOSURE DATE on or before the day) are out of every figure. Ratios are paired over the same
rows (feedback: aggregate ratios in pairs): average bill = sale ÷ bills over stores that recorded bills; conversion =
bills ÷ footfall over stores that counted footfall; a growth against nothing is blank, never 100 %.
★ YESTERDAY'S LAST YEAR is the same calendar date, as the night report reads it: East & NE store by store off the
portfolio (a store without that date last year is left out of the pair), South off the VFL feed (stores that billed on
both dates).

    python3 -c "import director_card as D; D.write()"      → out/director-card-<date>.png (and .html)
"""
from __future__ import annotations

import calendar
import datetime as dt
import html
import pathlib

import pandas as pd

import afternoon_sale as AS
import month_brief as MB
import exec_snapshot as ES
import portfolio_loader as PL

HERE = pathlib.Path(__file__).resolve().parent
GREEN, AMBER, IVORY, STONE, INK, QUIET, RULE, SIND = AS.GREEN, AS.AMBER, AS.IVORY, AS.STONE, AS.INK, AS.QUIET, AS.RULE, "#b3261e"
GOOD, WARN, BAD = "#1d7a3e", "#b7791f", SIND


def esc(s) -> str:
    return html.escape(str(s))


def inr(v) -> str:
    return AS.inr(v)


def cr(v) -> str:
    if v is None:
        return "—"
    return f"₹{v / 1e7:,.2f} Cr" if abs(v) >= 1e7 else f"₹{v / 1e5:,.2f} L"


def pct(v, dp=1, sign=True) -> str:
    if v is None:
        return "—"
    return f"{v:+.{dp}f}%" if sign else f"{v:.{dp}f}%"


def gd(a, b):
    """★ A growth against nothing is blank, never 100 %."""
    return (a - b) / b * 100 if (a is not None and b) else None


def tone(v) -> str:
    return "" if v is None else ("up" if v >= 0 else "dn")


def pace_tone(ach, pace) -> str:
    """Achieved % coloured against the month's PACE, never against 100 (house rule)."""
    if ach is None:
        return ""
    return "up" if ach >= pace else ("mid" if ach >= pace * .9 else "dn")


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════
def data(pf: pd.DataFrame, df: pd.DataFrame | None = None, asof=None) -> dict:
    """`df` is the VFL bill feed (loader.load_data()) — South's last year lives only there."""
    asof = pd.Timestamp(asof or pf["date"].max()).normalize()
    closed = {c for c, d in PL.closed_map().items() if pd.notna(d) and pd.Timestamp(d) <= asof}
    live = pf[~pf["code"].isin(closed)].copy()
    for c in ("BILL", "QTY", "FOOTFALL", "Day Target"):
        live[c] = pd.to_numeric(live[c].astype(str).str.replace(",", ""), errors="coerce")
    m0, dim = asof.replace(day=1), calendar.monthrange(asof.year, asof.month)[1]
    days_done, days_left = asof.day, dim - asof.day
    pace = days_done / dim * 100
    ly = asof - pd.DateOffset(years=1)

    stores = live[live["date"] <= asof].groupby("code").agg(name=("brand", "last"), loc=("location", "last"), city=("city", "last"),
                                                            region=("region", "last"), vfl=("is_vfl", "last")).reset_index()
    day = live[live["date"] == asof].set_index("code")
    lyd = live[live["date"] == ly].set_index("code")["sales"]
    wk = live[(live["date"] >= asof - pd.Timedelta(days=7)) & (live["date"] < asof)].groupby("code")["sales"].mean()
    mtd = live[(live["date"] >= m0) & (live["date"] <= asof)].groupby("code")["sales"].sum()
    try:
        import targets as T
        tg = T.for_month(asof)
    except Exception:
        tg = {}

    rows = []
    for _, s in stores.iterrows():
        c = int(s["code"])
        if c not in day.index and c not in mtd.index:
            continue
        d = day.loc[c] if c in day.index else None
        sale = float(d["sales"]) if d is not None else None
        t = tg.get(c, {}).get("mtd")
        m = float(mtd.get(c, 0.0))
        rows.append(dict(
            code=c, name=f"{str(s['name']).title()} · {str(s['loc']).title()}", city=str(s["city"]).title(), region=s["region"], vfl=bool(s["vfl"]),
            sale=sale, ly=float(lyd[c]) if c in lyd.index and lyd[c] > 0 else None, wk=float(wk[c]) if c in wk.index else None,
            bills=float(d["BILL"]) if d is not None and pd.notna(d["BILL"]) else None,
            qty=float(d["QTY"]) if d is not None and pd.notna(d["QTY"]) else None,
            foot=float(d["FOOTFALL"]) if d is not None and pd.notna(d["FOOTFALL"]) and d["FOOTFALL"] > 0 else None,
            dt=float(d["Day Target"]) if d is not None and pd.notna(d["Day Target"]) and d["Day Target"] > 0 else None,
            mtd=m, target=t, ach=m / t * 100 if t else None,
            need=max(0.0, (t - m) / days_left) if (t and days_left) else None))

    def roll(rs, label):
        sale = sum(r["sale"] or 0 for r in rs)
        pair = [r for r in rs if r["ly"] and r["sale"] is not None]
        bp = [r for r in rs if r["bills"] and r["sale"]]
        fp = [r for r in rs if r["foot"] and r["bills"] is not None]
        tp = [r for r in rs if r["dt"] and r["sale"] is not None]
        mp = [r for r in rs if r["target"]]
        mt = sum(r["target"] for r in mp)
        mm = sum(r["mtd"] for r in mp)
        wp = [r for r in rs if r["wk"] and r["sale"] is not None]
        return dict(label=label, sale=sale, n=len(rs), live=sum(1 for r in rs if r["sale"]),
                    ltl=gd(sum(r["sale"] for r in pair), sum(r["ly"] for r in pair)), ltl_n=len(pair),
                    vs_wk=gd(sum(r["sale"] for r in wp), sum(r["wk"] for r in wp)),
                    bills=sum(r["bills"] for r in bp), abv=(sum(r["sale"] for r in bp) / sum(r["bills"] for r in bp)) if bp else None,
                    ppb=(sum(r["qty"] or 0 for r in bp) / sum(r["bills"] for r in bp)) if bp else None,
                    conv=(sum(r["bills"] for r in fp) / sum(r["foot"] for r in fp) * 100) if fp else None, conv_n=len(fp),
                    dt_ach=(sum(r["sale"] for r in tp) / sum(r["dt"] for r in tp) * 100) if tp else None, dt_n=len(tp),
                    mtd=sum(r["mtd"] for r in rs), mtd_t=mm, target=mt or None, ach=(mm / mt * 100) if mt else None,
                    need=max(0.0, (mt - mm) / days_left) if (mt and days_left) else None,
                    proj=(mm / days_done * dim) if mt else None)

    regions = [roll([r for r in rows if r["region"] == g], g) for g in ("East & NE", "South")]
    total = roll(rows, "OVERALL")
    ex = {None: ES.portfolio_metrics(pf, asof)}

    # ★ growth, region by region in rupees (the month card's definitions), then OVERALL from the summed rupees
    import loader as L
    pairs = {"East & NE": MB.east_pairs(PL, pf, asof)}
    day = {"East & NE": (sum(r["sale"] for r in rows if r["region"] == "East & NE" and r["ly"] and r["sale"] is not None),
                         sum(r["ly"] for r in rows if r["region"] == "East & NE" and r["ly"] and r["sale"] is not None))}
    if df is not None:
        pairs["South"] = MB.south_pairs(L, df, asof)
        sf = df[df[L.COL_REGION] == "South"]
        a_ = sf[sf["date"] == asof].groupby(L.COL_STORE_LABEL)[L.COL_AMOUNT].sum()
        b_ = sf[sf["date"] == ly].groupby(L.COL_STORE_LABEL)[L.COL_AMOUNT].sum()
        both = [k for k in a_.index if k in b_.index and b_[k] > 0]
        day["South"] = (float(a_[both].sum()), float(b_[both].sum()))
    for r in regions:
        g = r["label"]
        r["ltl"] = gd(*day[g]) if g in day else None
        r["ltl_m"] = gd(*pairs[g]["MTD"]) if g in pairs else None
        r["ltl_y"] = gd(*pairs[g]["YTD"]) if g in pairs else None
    have = [g for g in ("East & NE", "South") if g in pairs]
    add = lambda k: (sum(pairs[g][k][0] for g in have), sum(pairs[g][k][1] for g in have))
    total["ltl"] = gd(sum(day[g][0] for g in day), sum(day[g][1] for g in day))
    total["ltl_m"] = gd(*add("MTD")) if len(have) == 2 else None
    total["ltl_y"] = gd(*add("YTD")) if len(have) == 2 else None
    # ★ the year's rupees INCLUDE stores that have since closed — what they sold this year was sold (ties to the
    # executive snapshot's ₹ year to date); only the day and month views leave closed stores out
    yr = pf[(pf["date"] >= PL._fy_start(asof)) & (pf["date"] <= asof)]
    total["ytd"] = float(yr["sales"].sum())
    for r in regions:
        r["ytd"] = float(yr[yr["region"] == r["label"]]["sales"].sum())

    # ★ the month line — ONE estate on every line: the stores that carry a month target (sales, target and the rate)
    tcodes = {r["code"] for r in rows if r["target"]}
    mon = live[(live["date"] >= m0) & (live["date"] <= asof) & live["code"].isin(tcodes)].groupby("date")["sales"].sum()
    line, run = [], 0.0
    for k in range(1, dim + 1):
        dte = m0 + pd.Timedelta(days=k - 1)
        d_ = float(mon.get(dte, 0.0)) if dte <= asof else None
        run += d_ or 0.0
        line.append(dict(day=k, sale=d_, ty=run if dte <= asof else None, tg=(total["target"] or 0) * k / dim,
                         pr=(total["mtd_t"] / days_done * k) if (k >= days_done and total.get("mtd_t")) else None))

    brands = (live[(live["date"] >= m0) & (live["date"] <= asof)].assign(
        b=lambda x: x["brand"].str.upper().replace({"MANYAVAR": "MANYAVAR & MOHEY", "MOHEY": "MANYAVAR & MOHEY"}))
        .groupby("b").apply(lambda x: pd.Series({"day": x[x["date"] == asof]["sales"].sum(), "mtd": x["sales"].sum()}), include_groups=False)
        .sort_values("mtd", ascending=False))
    no_sale = [r for r in rows if r["sale"] == 0]
    no_row = [r for r in rows if r["sale"] is None]
    return dict(asof=asof, pace=pace, days_done=days_done, dim=dim, days_left=days_left, rows=rows, regions=regions, total=total,
                ex=ex, south_feed=df is not None, line=line, brands=brands, no_sale=no_sale, no_row=no_row,
                provisional=pf.attrs.get("provisional_date"))


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════
CSS = AS.CSS + f"""
.page{{width:1240px}} .card{{border-radius:26px}}
.hd .ttl{{font-size:50px}}
.band{{padding:26px 44px 8px}} .band h2{{margin:0 0 4px;font-size:15px;letter-spacing:.18em;text-transform:uppercase;color:{QUIET};font-weight:800}}
.band h3{{margin:0 0 16px;font-size:30px;font-weight:800;letter-spacing:-.01em}}
.tiles.t4{{grid-template-columns:repeat(4,1fr);border:1px solid {RULE};border-radius:16px;overflow:hidden;margin-bottom:14px}}
.tile .v{{font-size:34px}} .tile .s{{font-size:16px;color:{QUIET};margin-top:6px;line-height:1.35}}
.up{{color:{GOOD}!important}} .dn{{color:{BAD}!important}} .mid{{color:{WARN}!important}}
.pill{{display:inline-block;padding:3px 10px;border-radius:99px;font-weight:800;font-size:15px}}
.pill.up{{background:#e3f1e7}} .pill.dn{{background:#f8e1df}} .pill.mid{{background:#fbefd9}}
table.wide td,table.wide th{{font-size:17px;padding:9px 10px}} table.wide th{{font-size:12px}}
table.wide td.s{{color:{QUIET};font-size:14px}}
.pacebar{{position:relative;height:12px;border-radius:6px;background:{STONE};margin-top:10px}}
.pacebar i{{position:absolute;left:0;top:0;bottom:0;border-radius:6px;background:{GREEN}}}
.pacebar b{{position:absolute;top:-6px;bottom:-6px;width:3px;background:{INK}}}
.legend{{display:flex;gap:22px;font-size:15px;color:{QUIET};margin:6px 0 4px}} .legend i{{display:inline-block;width:22px;height:4px;vertical-align:middle;margin-right:6px}}
.notes{{padding:4px 44px 0;font-size:16px;color:{QUIET};line-height:1.5}} .notes b{{color:{INK}}}
tr.grand td.up,tr.grand td.dn,tr.grand td.mid{{color:#fff!important}}
.page{{padding:0}} .card{{border-radius:0}}
"""


def tile(k, v, s="", cls="") -> str:
    return f"<div class=tile><div class=k>{esc(k)}</div><div class='v {cls}'>{v}</div>{f'<div class=s>{s}</div>' if s else ''}</div>"


def chart(line, w=1150, h=360) -> str:
    """The month as inline SVG: each day's sale as a bar, the running total (green) against the target's even pace
    (amber, dashed) and where today's daily rate lands by month end (green, dotted). Attributes are QUOTED: an unquoted
    `stroke-width=4/>` leaves the path open in HTML and swallows every shape after it (the first cut lost its line)."""
    top = max([p["tg"] for p in line] + [p["ty"] or 0 for p in line] + [p["pr"] or 0 for p in line]) or 1
    dmax = max([p["sale"] or 0 for p in line]) or 1
    L0, R0, B0, T0 = 70, 30, 44, 20
    X = lambda d: L0 + (d - 1) / (len(line) - 1) * (w - L0 - R0)
    Y = lambda v: h - B0 - v / top * (h - B0 - T0)
    pts = lambda key: [(X(p["day"]), Y(p[key])) for p in line if p[key] is not None]
    path = lambda ps: " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(ps))
    bw = (w - L0 - R0) / len(line) * .56
    bars = "".join(f'<rect x="{X(p["day"]) - bw / 2:.1f}" y="{h - B0 - p["sale"] / dmax * (h - B0 - T0) * .32:.1f}" width="{bw:.1f}" '
                   f'height="{p["sale"] / dmax * (h - B0 - T0) * .32:.1f}" rx="3" fill="#cfe0d4"/>' for p in line if p["sale"])
    grid = "".join(f'<line x1="{L0}" x2="{w - R0}" y1="{Y(top * f):.1f}" y2="{Y(top * f):.1f}" stroke="{RULE}"/>'
                   f'<text x="{L0 - 10}" y="{Y(top * f) + 5:.1f}" font-size="14" text-anchor="end" fill="{QUIET}">{top * f / 1e7:.1f} Cr</text>'
                   for f in (0, .25, .5, .75, 1))
    ticks = "".join(f'<text x="{X(d):.1f}" y="{h - 16}" font-size="14" text-anchor="middle" fill="{QUIET}">{d}</text>'
                    for d in sorted({1, 5, 10, 15, 20, 25, len(line)}))
    last = [p for p in line if p["ty"] is not None][-1]
    end = line[-1]
    lab = lambda x, y, t, c, anchor="end": f'<text x="{x:.1f}" y="{y:.1f}" font-size="16" font-weight="800" text-anchor="{anchor}" fill="{c}">{t}</text>'
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="Hanken Grotesk">{grid}{bars}{ticks}'
            f'<path d="{path(pts("tg"))}" fill="none" stroke="{AMBER}" stroke-width="3" stroke-dasharray="10 8"/>'
            f'<path d="{path(pts("pr"))}" fill="none" stroke="{GREEN}" stroke-width="3" stroke-dasharray="2 7" stroke-linecap="round"/>'
            f'<path d="{path(pts("ty"))}" fill="none" stroke="{GREEN}" stroke-width="5" stroke-linejoin="round"/>'
            f'<circle cx="{X(last["day"]):.1f}" cy="{Y(last["ty"]):.1f}" r="7" fill="{GREEN}"/>'
            + lab(X(last["day"]) + 4, Y(last["ty"]) + 34, "so far " + cr(last["ty"]), GREEN, "middle")
            + "</svg>")


def page(D: dict) -> str:
    a, T, R, ex = D["asof"], D["total"], D["regions"], D["ex"]
    exm = ex[None]
    tiles_ex = {t["label"]: t for t in exm["tiles"]}
    est = tiles_ex.get("Estate", {})
    rs = lambda t: str(t).replace("Rs ", "₹")
    split = lambda k: " · ".join(f"{'East' if r['label'].startswith('East') else r['label']} {pct(r[k])}" for r in R)

    y1 = "".join([
        tile("Sale yesterday", cr(T["sale"]), f"{T['live']} of {T['n']} stores sold", "hi"),
        tile("vs same day last year", pct(T["ltl"]), f"like to like · {split('ltl')}", tone(T["ltl"])),
        tile("vs last 7 days", pct(T["vs_wk"]), "each store against its own daily average", tone(T["vs_wk"])),
        tile("Day target", pct(T["dt_ach"], 0, False), f"achieved · {T['dt_n']} stores with a day target", pace_tone(T["dt_ach"], 100))])
    y2 = "".join([
        tile("Bills", f"{T['bills']:,.0f}", "stores that recorded bills"),
        tile("Average bill", inr(T["abv"]), "sale ÷ bills, same stores"),
        tile("Pieces per bill", f"{T['ppb']:.2f}" if T["ppb"] else "—", "pieces ÷ bills"),
        tile("Conversion", pct(T["conv"], 1, False), f"bills ÷ footfall · {T['conv_n']} stores counted footfall")])
    pace = D["pace"]
    bar = f"<div class=pacebar><i style='width:{min(100, T['ach'] or 0):.1f}%'></i><b style='left:{pace:.1f}%'></b></div>"
    m1 = "".join([
        tile("Month to date", cr(T["mtd"]), f"day {D['days_done']} of {D['dim']}", "hi"),
        tile("Growth, like to like", pct(T["ltl_m"]), split("ltl_m"), tone(T["ltl_m"])),
        tile("Target achieved", pct(T["ach"], 1, False), f"pace today {pace:.0f}% · target {cr(T['target'])}{bar}", pace_tone(T["ach"], pace)),
        tile("Needed per day", cr(T["need"]) if T["need"] else "done", f"for the {D['days_left']} days left · at today's rate the month closes {cr(T['proj'])}")])
    yt = "".join([
        tile("Year to date", cr(T["ytd"]), "since 1 April · South since the 19 Apr takeover · includes stores since closed", "hi"),
        tile("Growth, like to like", pct(T["ltl_y"]), split("ltl_y"), tone(T["ltl_y"])),
        tile("Estate", esc(est.get("value", "—")), esc(est.get("sub", ""))),
        tile("Throughput / sq ft", esc(rs((est.get("key") or ["", "—"])[1])), esc(" · ".join(est.get("rows", [[]])[0]) if est.get("rows") else ""))])

    def regrow(r, cls=""):
        return (f"<tr class='{cls}'><td>{esc(r['label'])}</td><td class=r>{inr(r['sale'])}</td><td class='r {tone(r['ltl'])}'>{pct(r['ltl'])}</td>"
                f"<td class=r>{inr(r['mtd'])}</td><td class='r {tone(r['ltl_m'])}'>{pct(r['ltl_m'])}</td><td class='r {pace_tone(r['ach'], pace)}'>{pct(r['ach'], 1, False)}</td>"
                f"<td class=r>{inr(r['need']) if r['need'] else '—'}</td><td class=r>{cr(r['ytd'])}</td><td class='r {tone(r['ltl_y'])}'>{pct(r['ltl_y'])}</td></tr>")
    reg = (f"<table class=wide><tr><th>Region</th><th class=r>Yesterday</th><th class=r>vs LY day</th><th class=r>Month to date</th><th class=r>LTL</th>"
           f"<th class=r>Achieved</th><th class=r>Needed / day</th><th class=r>Year to date</th><th class=r>LTL</th></tr>"
           + "".join(regrow(r) for r in R) + regrow(T, "grand") + "</table>")

    # every store: region › city › store
    srows = ""
    for g in ("East & NE", "South"):
        rs = [r for r in D["rows"] if r["region"] == g]
        srows += f"<tr class=band><td colspan=8>{esc(g.upper())}</td></tr>"
        for city in sorted({r["city"] for r in rs}):
            cs = sorted([r for r in rs if r["city"] == city], key=lambda r: -(r["mtd"] or 0))
            for r in cs:
                vs = gd(r["sale"], r["wk"])
                da = r["sale"] / r["dt"] * 100 if (r["dt"] and r["sale"] is not None) else None
                zero = " zero" if not r["sale"] else ""
                srows += (f"<tr class='{zero}'><td>{esc(r['name'])} <span class=s>{r['code']}</span></td><td class=s>{esc(city)}</td>"
                          f"<td class=r>{inr(r['sale']) if r['sale'] is not None else '—'}</td><td class='r {tone(vs)}'>{pct(vs, 0)}</td>"
                          f"<td class='r {pace_tone(da, 100)}'>{pct(da, 0, False)}</td><td class=r>{inr(r['mtd'])}</td>"
                          f"<td class='r'><span class='pill {pace_tone(r['ach'], pace)}'>{pct(r['ach'], 0, False)}</span></td>"
                          f"<td class=r>{inr(r['need']) if r['need'] else ('done' if r['target'] else '—')}</td></tr>")
            if len(cs) > 1:
                srows += (f"<tr class=sub><td colspan=2>{esc(city)} total</td><td class=r>{inr(sum(r['sale'] or 0 for r in cs))}</td><td></td><td></td>"
                          f"<td class=r>{inr(sum(r['mtd'] for r in cs))}</td><td></td><td></td></tr>")
    stores = (f"<table class=wide><tr><th>Store</th><th>City</th><th class=r>Yesterday</th><th class=r>vs 7 days</th><th class=r>Day target</th>"
              f"<th class=r>Month to date</th><th class=r>Achieved</th><th class=r>Needed / day</th></tr>{srows}</table>")

    bt_rows = "".join(f"<tr><td>{esc(b.title())}</td><td class=r>{inr(v['day'])}</td><td class=r>{inr(v['mtd'])}</td>"
                      f"<td class=r>{v['mtd'] / T['mtd'] * 100:.1f}%</td></tr>" for b, v in D["brands"].iterrows())
    brands = f"<table class=wide><tr><th>Brand</th><th class=r>Yesterday</th><th class=r>Month to date</th><th class=r>Share of month</th></tr>{bt_rows}</table>"

    notes = []
    if D["no_sale"]:
        notes.append("<b>Sold nothing yesterday:</b> " + ", ".join(f"{esc(r['name'])} ({r['code']})" for r in D["no_sale"]))
    if D["no_row"]:
        notes.append("<b>No figure for yesterday</b> (shown —, not counted): " + ", ".join(f"{esc(r['name'])} ({r['code']})" for r in D["no_row"]))
    if D["provisional"] is not None:
        notes.append(f"<b>Provisional:</b> {pd.Timestamp(D['provisional']):%d %b} is from the night fill; bills may still change.")
    if not D["south_feed"]:
        notes.append("<b>South's growth is missing:</b> the VFL bill feed did not load, and the portfolio sheet holds no South last year.")
    notes.append(f"Closed stores are out of every figure. Growth is like to like: East &amp; NE store by store over the span each has "
                 f"both years; South off the bill feed, its year from the 19 Apr takeover; OVERALL adds the rupees. Last year's day is the "
                 f"same calendar date, so a festival that moved shows here. Achieved is coloured against the month's pace ({pace:.0f}% today): "
                 f"green on or ahead, amber within 10%, red behind.")
    return f"""<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body><div class=page><div class=card>
<div class=hd><div><div class=kick>Directors' morning card</div><div class=ttl>{a:%A, %d %B %Y}</div></div>
<div class=dt><div class=l>Yesterday's figures</div><div class=v>{a:%d.%m.%Y}</div></div></div>
<div class=band><h2>1 · Yesterday</h2><h3>What the stores did</h3><div class='tiles t4'>{y1}</div><div class='tiles t4'>{y2}</div></div>
<div class=band><h2>2 · The month</h2><h3>{a:%B} so far</h3><div class='tiles t4'>{m1}</div></div>
<div class=band><h2>3 · The year</h2><h3>FY {a.year if a.month >= 4 else a.year - 1}–{(a.year + 1 if a.month >= 4 else a.year) % 100:02d} so far</h3><div class='tiles t4'>{yt}</div></div>
<div class=band><h2>4 · Regions</h2><h3>East &amp; NE and South</h3>{reg}</div>
<div class=band><h2>5 · The month, day by day</h2><h3>Running total against the target</h3>
<div class=legend><span><i style='background:{GREEN}'></i>sale so far</span><span><i style='background:#cfe0d4;height:12px'></i>each day's sale (own scale, tallest {cr(max(p['sale'] or 0 for p in D['line']))})</span><span><i style='background:{AMBER}'></i>target, at an even pace · <b>{cr(D['line'][-1]['tg'])}</b></span><span><i style='border-top:3px dotted {GREEN};height:0'></i>today's rate, to month end · <b>{cr(D['line'][-1]['pr'])}</b></span></div>
{chart(D['line'])}<div class=notes style='padding:0'>Stores that carry a {a:%B} target ({sum(1 for r in D['rows'] if r['target'])} of {len(D['rows'])}).</div></div>
<div class=band><h2>6 · Every store</h2><h3>Region › city › store, biggest month first</h3>{stores}</div>
<div class=band><h2>7 · Brands</h2><h3>Every brand, the month</h3>{brands}</div>
<div class=notes>{'<br>'.join(notes)}</div>
<div class=ft><div class=n>Peanuts Retail · from the portfolio sheet and the Targets tab, as of {a:%d %b %Y}</div><img src="{AS._logo()}"></div></div></div></body></html>"""


def build(pf, df=None, asof=None) -> tuple[str, bytes]:
    """(file name, PDF bytes) — what the WhatsApp sender's `director_card` extra sends (27 Oct 2026: Manav, "dont add it
    to directors morning send, but make it like an extras option, so i can send it to people who need it").

    ★ A PDF, NOT THE PNG: the sender posts a .png through the image template, and WhatsApp recompresses a picture to a
    couple of thousand pixels on its long side — this card is ~5,600 css px tall, so its tables would arrive unreadable.
    A PDF goes as a document, untouched: ONE page exactly the card's size, text kept as text, sharp at any zoom; the
    chat shows its top (the day) as the preview."""
    import subprocess, tempfile
    from PIL import Image
    D = data(pf, df, asof)
    h = page(D)
    with tempfile.TemporaryDirectory() as tmp:
        tall = Image.open(_render_tall(h, pathlib.Path(tmp) / "card.png")).height // 2     # css px: the PNG is drawn at ×2
        src, pdf = pathlib.Path(tmp) / "p.html", pathlib.Path(tmp) / "card.pdf"
        src.write_text(h.replace("</style>", f"@page{{size:1240px {tall + 2}px;margin:0}}html,body{{background:#fff}}</style>", 1),
                       encoding="utf-8")
        subprocess.run([AS._chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={tmp}/profile",
                        "--no-pdf-header-footer", "--virtual-time-budget=8000", f"--print-to-pdf={pdf}", src.as_uri()],
                       check=True, capture_output=True, timeout=180)
        return f"director_card_{D['asof']:%Y%m%d}.pdf", pdf.read_bytes()


def write(out_dir=None, asof=None) -> pathlib.Path:
    import loader as L
    pf = PL.load_portfolio()
    try:
        df = L.load_data()
    except Exception:
        df = None                                 # the card says South's growth is missing rather than print East's as all
    D = data(pf, df, asof)
    out = pathlib.Path(out_dir or HERE / "out_director"); out.mkdir(exist_ok=True)
    h = page(D)
    (out / f"director-card-{D['asof']:%Y-%m-%d}.html").write_text(h, encoding="utf-8")
    png = out / f"director-card-{D['asof']:%Y-%m-%d}.png"
    _render_tall(h, png)
    return png


def _render_tall(html_text: str, out: pathlib.Path) -> pathlib.Path:
    """Chrome at 1312 css px wide, tall enough for the whole card, ×2; the empty stone below is trimmed."""
    import shutil, subprocess, tempfile
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        src, shot = pathlib.Path(tmp) / "p.html", pathlib.Path(tmp) / "p.png"
        src.write_text(html_text, encoding="utf-8")
        subprocess.run([AS._chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", f"--user-data-dir={tmp}/profile",
                        "--force-device-scale-factor=2", "--window-size=1240,9000", "--virtual-time-budget=8000",
                        f"--screenshot={shot}", src.as_uri()], check=True, capture_output=True, timeout=180)
        im = Image.open(shot).convert("RGB"); bg = im.getpixel((5, im.height - 5)); px = im.load(); bottom = im.height - 1
        while bottom > 0 and all(px[x, bottom] == bg for x in range(0, im.width, 9)):
            bottom -= 1
        im.crop((0, 0, im.width, min(im.height, bottom + 72))).save(out, optimize=True)
    return out


if __name__ == "__main__":
    print(write())
