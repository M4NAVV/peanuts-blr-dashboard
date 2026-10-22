"""Weekday vs weekend — every store's Monday-to-Friday and Saturday-Sunday.

★ WHY THIS EXISTS. Manav, 22 Oct: *"Monday to Friday each store sales
contribution, Saturday and Sunday contribution. Need to understand how much
each store does in the five days and the 2 days of weekend."* All stores, not
just VFL — so it reads the portfolio sheet, one `Total` per store per day.

★ TWO DIFFERENT QUESTIONS, BOTH ANSWERED.
  * SPLIT — of this store's own takings, what part came Mon-Fri and what part
    Sat-Sun. The weekend is 2 of 7 days, so 28.6% is what an even week would
    give; anything above it is weekend-led.
  * PER DAY — what an average weekday takes against an average weekend day.
    The split alone cannot say this: a store at 45% weekend sells about twice
    as much on a Saturday as on a Tuesday, and the ratio column says so in one
    number.

★ FULL WEEKS BY DEFAULT. A window that ends on a Wednesday holds three extra
weekdays and no extra weekend, which moves the split by several points without
anything having changed in the shop. The default periods therefore end on the
last complete Sunday. The averages are per CALENDAR day of each kind, so they
stay fair in any window; only the split needs whole weeks.

★ DAYS ARE THE STORE'S OWN. A store counts the weekdays and weekend days from
its first to its last sale inside the window — one that opened or shut midway
is not averaged over days it did not exist. A total counts calendar days from
its earliest member's first sale to its latest member's last, never the sum of
its stores' days (five stores do not give a city five days in a day — the same
rule as `report_td._avg_day`).

★ THE SHEET PRINTS MON-THU vs FRI-SUN ONLY (Manav, 22 Oct: *"only want
monday to thursday and fri, sat, sun, not the mon to fri and sat sun"*). It
was first built as Mon-Fri / Sat-Sun, then both side by side; he chose the
4+3 cut. Fri-Sun is 3 of 7 days, so 42.9% is what an even week would put
there. The Mon-Fri / Sat-Sun figures are still computed (`wd`/`we`, `ratio`)
so the old cut is one column list away, but nothing prints them. The
Fri-Sun ÷ Mon-Thu ratio is likewise computed but not printed (his call, same
day: "not needed").

★ THE LONG VIEW IS THE LAST 12 MONTHS, NOT THE YEAR TO DATE (Manav, 22 Oct).
The Fri-Sun share swings with the season — East & NE ran 39% in Oct 2025
(Puja and Diwali on weekdays) and 59% in Aug 2026 — and a year to date holds
whichever months the year has reached: in October it is summer weddings and
Puja, with no Diwali, winter weddings or Bihu, so it read 54.5% Fri-Sun where
the full year read 52.1%. A full year holds every season once, whenever the
report is opened, so it is the store's normal week and the fair baseline for
the 4-week page. "FY to date" stays on the tab only.

★ TTM IS 365 DAYS TO THE LATEST DAY — NOT WHOLE WEEKS (Manav, 22 Oct: *"to
yesterday, across the dash. thats what TTM means for us"*). It was first built
as 52 full weeks to the last Sunday, for the reason under FULL WEEKS above, and
read "20 Oct – 18 Oct". Every other TTM on the dashboard (GD sheets, price
brackets, executive snapshot, year end) is `asof - 1 year + 1 day` to `asof`,
and this one now is too. The cost is small and known: a part-week at the end
and one weekday counted 53 times — about 0.3% of the year each. The 4- and
13-week views keep their whole weeks.

★ SOUTH'S YEAR STARTS ON 19 APRIL 2026, its takeover. The loader already drops
everything before a store's takeover, and each store counts days from its own
first sale, so South's year to date is 19 April onwards without any rule here.
What this module adds is SAYING it: `late_starts` names every region whose
first sale is after the window opens, and the page prints it beside the
dates — otherwise "1 Apr – 21 Oct" sits above figures that do not cover it.

⚠️ A festival on a weekday is still a weekday. Puja and Diwali fall mostly on
weekdays in October-November, so a window holding them reads more weekday-led
than an ordinary month. The report says so rather than moving the days.
"""

from __future__ import annotations

import pandas as pd

import portfolio_loader as PL

EVEN_WEEKEND = 2 / 7 * 100           # the share an evenly-spread week would give
EVEN_FRI_SUN = 3 / 7 * 100

PERIODS = ["Last 4 weeks", "Last 13 weeks", "Last 12 months", "FY to date"]


def last_sunday(asof) -> pd.Timestamp:
    """The last complete Sunday on or before `asof`."""
    asof = pd.Timestamp(asof).normalize()
    return asof - pd.Timedelta(days=(asof.dayofweek + 1) % 7)


def window(period: str, asof) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(start, end) for one of `PERIODS`. Week windows run Monday to Sunday."""
    asof = pd.Timestamp(asof).normalize()
    if period == "FY to date":
        return PL._fy_start(asof), asof
    if period == "Last 12 months":          # the dashboard's TTM — see above
        return asof - pd.DateOffset(years=1) + pd.Timedelta(days=1), asof
    weeks = {"Last 4 weeks": 4, "Last 13 weeks": 13}[period]
    end = last_sunday(asof)
    return end - pd.Timedelta(days=7 * weeks - 1), end


def _days(start, end) -> tuple[int, int, int]:
    """(weekdays, weekend days, Fridays) from `start` to `end` inclusive."""
    if pd.isna(start) or pd.isna(end) or end < start:
        return 0, 0, 0
    dow = pd.date_range(start, end, freq="D").dayofweek
    we = int((dow >= 5).sum())
    return len(dow) - we, we, int((dow == 4).sum())


def by_store(pf: pd.DataFrame, start, end) -> pd.DataFrame:
    """One row per store that sold anything in the window."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    d = pf[(pf["date"] >= start) & (pf["date"] <= end)]
    if d.empty:
        return pd.DataFrame()
    dow = d["date"].dt.dayofweek
    d = d.assign(part=dow.map(lambda x: "we" if x >= 5 else
                              "fri" if x == 4 else "mt"))
    keys = ["code", "region", "city", "location", "brand"]
    money = (d.groupby(keys + ["part"], dropna=False)["sales"].sum()
             .unstack("part").reindex(columns=["mt", "fri", "we"]).fillna(0.0))
    # Mon-Fri and Sat-Sun as before; Friday kept apart for the 4+3 cut.
    money["wd"] = money["mt"] + money["fri"]
    sold = d[d["sales"] > 0].groupby("code")["date"].agg(["min", "max"])
    out = money.reset_index()
    out = out[out["code"].isin(sold.index)]       # traded in the window
    out["from"] = out["code"].map(sold["min"])
    out["to"] = out["code"].map(sold["max"])
    return out.reset_index(drop=True)


def measures(wd, we, start, end, estate_wd=None, estate_we=None,
             fri=0.0, estate_mt=None, estate_fs=None) -> dict:
    """Every figure the report prints, for one store or one total. `fri` is
    the Friday part of `wd`, for the Mon-Thu / Fri-Sun cut."""
    wdn, wen, frin = _days(start, end)
    tot = wd + we
    avg_wd = wd / wdn if wdn else None
    avg_we = we / wen if wen else None
    mt, fs = wd - fri, we + fri
    mtn, fsn = wdn - frin, wen + frin
    avg_mt = mt / mtn if mtn else None
    avg_fs = fs / fsn if fsn else None
    return {
        "mt": mt, "fs": fs, "mt_days": mtn, "fs_days": fsn,
        "mt_pct": mt / tot * 100 if tot else None,
        "fs_pct": fs / tot * 100 if tot else None,
        "avg_mt": avg_mt, "avg_fs": avg_fs,
        "ratio_fs": (avg_fs / avg_mt) if (avg_mt and avg_fs is not None)
        else None,
        "wd": wd, "we": we, "total": tot,
        "wd_pct": wd / tot * 100 if tot else None,
        "we_pct": we / tot * 100 if tot else None,
        "wd_days": wdn, "we_days": wen,
        "avg_wd": avg_wd, "avg_we": avg_we,
        "ratio": (avg_we / avg_wd) if (avg_wd and avg_we is not None) else None,
        "mt_share": mt / estate_mt * 100 if estate_mt else None,
        "fs_share": fs / estate_fs * 100 if estate_fs else None,
        "wd_share": wd / estate_wd * 100 if estate_wd else None,
        "we_share": we / estate_we * 100 if estate_we else None,
    }


def report(pf: pd.DataFrame, start, end) -> list[tuple[str, dict]]:
    """Rows in print order: stores by city, a city total where a city has more
    than one store, a total per region, then OVERALL. Each is (kind, row)."""
    s = by_store(pf, start, end)
    if s.empty:
        return []
    est_wd, est_we = s["wd"].sum(), s["we"].sum()
    est = {"estate_mt": s["mt"].sum(), "estate_fs": s["fri"].sum() + est_we}

    def tot(part, label, city=""):
        r = measures(part["wd"].sum(), part["we"].sum(),
                     part["from"].min(), part["to"].max(), est_wd, est_we,
                     fri=part["fri"].sum(), **est)
        return {"name": label, "city": city, "brand": "", "stores": len(part),
                "from": part["from"].min(),
                **r}

    out = []
    order = [r for r in PL.REGION_ORDER if r in set(s["region"])] + sorted(
        set(s["region"]) - set(PL.REGION_ORDER))
    for reg in order:
        rs = s[s["region"] == reg]
        cities = rs.groupby("city")["wd"].sum().add(
            rs.groupby("city")["we"].sum())
        for city in cities.sort_values(ascending=False).index:
            cs = rs[rs["city"] == city]
            cs = cs.assign(_t=cs["wd"] + cs["we"]).sort_values(
                "_t", ascending=False)
            for _, x in cs.iterrows():
                out.append(("store", {
                    "name": x["location"], "city": city, "brand": x["brand"],
                    "code": int(x["code"]), "region": reg, "stores": 1,
                    "from": x["from"],
                    **measures(x["wd"], x["we"], x["from"], x["to"],
                               est_wd, est_we, fri=x["fri"], **est)}))
            # A region of one city would print the same total twice.
            if len(cs) > 1 and len(cities) > 1:
                out.append(("citytotal", tot(cs, f"{city} TOTAL", city)))
        out.append(("subtotal", {**tot(rs, f"{reg.upper()} TOTAL"),
                                 "region": reg}))
    out.append(("grand", tot(s, "OVERALL")))
    return out


def late_starts(rows, start) -> str:
    """"South from 19 Apr 2026" for each region that starts after the window
    does, or "" — see the module note."""
    start = pd.Timestamp(start)
    late = [f"{r['region']} from {r['from']:%d %b %Y}" for k, r in rows
            if k == "subtotal" and pd.Timestamp(r["from"]) > start]
    return ", ".join(late)


# --------------------------------------------------------------------------- #
# PDF — the house desk-report page, via report_td's grid
# --------------------------------------------------------------------------- #
COLS = [
    ("CITY", "l"), ("STORE", "l"), ("BRAND", "l"),
    ("MON–THU SALE", "r"), ("FRI–SUN SALE", "r"), ("TOTAL SALE", "r"),
    ("MON–THU %", "r"), ("FRI–SUN %", "r"),
    ("AVG MON–THU DAY", "r"), ("AVG FRI–SUN DAY", "r"),
    ("SHARE OF ALL MON–THU %", "r"), ("SHARE OF ALL FRI–SUN %", "r"),
]


def _pct(v):
    return "" if v is None else f"{v:,.1f}"


def render(rows, title):
    import report_td as RTD
    header = [h for h, _ in COLS]
    aligns = [a for _, a in COLS]
    grid = []
    for kind, r in rows:
        if kind == "store":
            head = [r["city"], r["name"], r["brand"]]
        elif kind == "citytotal":
            head = [r["city"], (f"{r['name']}  ·  {r['stores']} stores", 2)]
        else:
            head = [(f"{r['name']}  ·  {r['stores']} stores", 3)]
        vals = head + [
            RTD._money(r["mt"]), RTD._money(r["fs"]), RTD._money(r["total"]),
            _pct(r["mt_pct"]), _pct(r["fs_pct"]),
            RTD._money(r["avg_mt"]), RTD._money(r["avg_fs"]),
            _pct(r["mt_share"]), _pct(r["fs_share"])]
        fill = {"citytotal": RTD.LOC_BG, "subtotal": RTD.HDR_BG,
                "grand": RTD.TOTAL_BG}.get(kind)
        grid.append((RTD._cells(vals, aligns, fill, kind != "store"),
                     RTD.ROW_H))
    return RTD._draw_grid(header, grid, landscape=False, title=title)


def build_pdf(pf: pd.DataFrame, asof, basis_label="") -> tuple[str, bytes]:
    """Two pages: the last four full weeks, then the last 12 months (TTM)."""
    import report_td as RTD
    from imaging import _LOCK
    asof = pd.Timestamp(asof).normalize()
    contents = []
    with _LOCK, RTD.desk():
        for period in ("Last 4 weeks", "Last 12 months"):
            start, end = window(period, asof)
            rows = report(pf, start, end)
            if not rows:
                continue
            wdn, wen, frin = _days(start, end)
            title = (f"MON–THU vs FRI–SUN  ·  {period.upper()}  ·  "
                     f"{start:%d %b %Y} – {end:%d %b %Y}  ·  {wdn - frin} "
                     f"Mon–Thu days, {wen + frin} Fri–Sun days  ·  an even "
                     f"week puts {EVEN_FRI_SUN:.1f}% on Fri–Sun")
            if late_starts(rows, start):
                title += f"  ·  {late_starts(rows, start)}"
            contents.append((f"Weekday vs weekend · {period}",
                             render(rows, title)))
        if not contents:
            raise ValueError("no store sold anything in either window")
        pdf = RTD._pdf_from(contents, RTD._label(asof, basis_label))
    return (f"WEEKDAY VS WEEKEND {asof:%d-%m-%Y}.pdf", pdf)


# --------------------------------------------------------------------------- #
# Manager snaps — one image per region, percentages only
# --------------------------------------------------------------------------- #
# ★ Manav, 22 Oct: *"2 snaps, one for the east, and one for the south. only the
# TTM data. no real sales figures, only percentages … we need to send this in
# manager groups."* So: no rupee figure anywhere, not even a per-day average,
# and the share columns are of the REGION, not the company — a manager in
# Bengaluru is placing his store among the South stores, and a share of the
# whole company would hand the East's size to the South group and vice versa.
# Phone type (report_td's default, not `desk()`), as the night SMS uses: these
# are read on WhatsApp.
SNAP_COLS = [
    ("CITY", "l"), ("STORE", "l"), ("BRAND", "l"),
    ("MON–THU %", "r"), ("FRI–SUN %", "r"),
]


def snap_rows(pf: pd.DataFrame, region: str, start, end, asof=None):
    """Every store in the region RANKED by Mon-Thu %, highest first, then the
    region total (Manav, 22 Oct: *"remove the share of columns, and sort it
    from Mon-Thu % highest to lowest"*). A ranking has no place for city totals
    between its rows, so they are left out; the city is a column.

    Stores shut by `asof` (the master's closure date) are left out before
    anything is summed: a managers' group has no use for Nh31A or Galaxy Mall,
    and a region total that still counted them would not be the sum of the
    rows shown."""
    d = pf[pf["region"] == region]
    if asof is not None:
        shut = {c for c, when in PL.closed_map().items()
                if pd.Timestamp(when) <= pd.Timestamp(asof)}
        d = d[~d["code"].isin(shut)]
    rows = report(d, start, end)
    if not rows:
        return []
    stores = sorted((x for x in rows if x[0] == "store"),
                    key=lambda x: -(x[1]["mt_pct"] or 0))
    return stores + [x for x in rows if x[0] == "subtotal"]


def snap_png(pf: pd.DataFrame, region: str, asof,
             vfl: bool = False) -> tuple[str, bytes]:
    """One region, the last 12 months, as a PNG for the managers' group.

    `vfl=True` keeps the Manyavar / Mohey stores only (Manav, 22 Oct: *"for
    east, make 2. give me VFL separately, and one like u did right now"*). The
    total is then the VFL total, and is labelled so."""
    import io
    import report_td as RTD
    import portfolio_pdf as PP
    from imaging import _LOCK
    asof = pd.Timestamp(asof).normalize()
    start, end = window("Last 12 months", asof)
    tag = region.upper() + (" VFL" if vfl else "")
    rows = snap_rows(pf[pf["is_vfl"]] if vfl else pf, region, start, end,
                     asof=asof)
    if not rows:
        raise ValueError(f"no {tag} store sold anything in the window")
    rows = [(k, {**r, "name": f"{tag} TOTAL"} if k == "subtotal" else r)
            for k, r in rows]
    header = [h for h, _ in SNAP_COLS]
    aligns = [a for _, a in SNAP_COLS]
    grid = []
    for kind, r in rows:
        if kind == "store":
            head = [r["city"], r["name"], r["brand"]]
        elif kind == "citytotal":
            head = [r["city"], (f"{r['name']}  ·  {r['stores']} stores", 2)]
        else:
            head = [(f"{r['name']}  ·  {r['stores']} stores", 3)]
        vals = head + [_pct(r["mt_pct"]), _pct(r["fs_pct"])]
        fill = {"citytotal": RTD.LOC_BG, "subtotal": RTD.TOTAL_BG}.get(kind)
        grid.append((RTD._cells(vals, aligns, fill, kind != "store"),
                     RTD.ROW_H))
    late = late_starts(rows, start)
    note = (f"Mon–Thu is 4 days of the week and Fri–Sun is 3, so an even week "
            f"would put {EVEN_FRI_SUN:.1f}% on Fri–Sun — above that, the store "
            f"leans on its Friday-to-Sunday. Stores are ranked by Mon–Thu %, "
            f"highest first. Stores that have shut are not shown.")
    if late:
        note += f" {late}, its takeover, so less than 12 months."
    grid.append(([RTD.cell(note, align="l", wrap=True, span=len(SNAP_COLS))],
                 RTD.ROW_H))
    with _LOCK:
        img = RTD._draw_grid(
            header, grid, landscape=False,
            title=f"{tag}  ·  LAST 12 MONTHS  ·  "
                  f"{start:%d %b %Y} – {end:%d %b %Y}")
        page_w = img.width + 2 * (PP.MARGIN + PP.FRAME + PP.PAD)
        page = PP._compose(img, f"{region}{' VFL' if vfl else ''} · "
                                f"Mon–Thu vs Fri–Sun",
                           f"Last 12 months to {end:%d %b %Y}", 1, 1, page_w,
                           footer_right="Peanuts Retail")
    buf = io.BytesIO()
    page.save(buf, format="PNG", optimize=True)
    return (f"{tag} MON-THU vs FRI-SUN {end:%d-%m-%Y}.png", buf.getvalue())
