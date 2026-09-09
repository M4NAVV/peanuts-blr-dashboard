"""Google reviews per store per day, and what share of bills they represent.

The source is the team's own workbook — "MANYAVAR ALL STORE GOOGLE REVIEW
REPORT" — which stacks one block per day down each monthly tab: a date, a
header row, then one row per store.

★ THREE THINGS ABOUT THAT SHEET THAT WERE CHECKED, NOT ASSUMED.

1. **The column says PREVIOUS DAY; the figures are for the DAY ON THE BLOCK.**
   Read literally, every review would be attributed to the wrong date. Settled
   by correlating their bill column against our own POS bill counts under both
   readings, per store: same-day wins 14 of 14, median correlation 0.976
   against 0.608. The label is loose; the data is not.

2. **Their store names are not ours**, and the mapping was decided the same way
   — by which bill series actually matches — rather than by reading names.
   "MANYAVAR SVR" is Siliguri 2, not Siliguri.

3. **Their manual bill counts are good but not authoritative.** 89% of
   store-days match the POS exactly and the total is 0.30% light, but Malda
   runs 3.5% high and Roodraksh Mall 3.4% low. So reviews come from this sheet
   and BILLS COME FROM THE POS — the denominator should not be a hand count
   when an exact one exists.

★ AND WHAT IT DOES NOT COVER: fourteen stores, all East & NE. None of the eight
Bengaluru stores appear, so any estate-wide review rate computed from it is an
East & NE figure wearing an estate label. The report says so on its face.
"""

from __future__ import annotations

import io
import os
import re

import pandas as pd

URL_ENV = "REVIEWS_URL"

# The pack's own print quality — see feedback on pixels per page. Every other
# report in the same download lands near here.
TARGET_PPI = 327.0

# ★ ONE WASH PER PERIOD, pale enough that the figures stay the content.
_BAND = {"Day": (238, 245, 251),      # blue
         "MTD": (238, 248, 241),      # green
         "QTD": (252, 247, 236),      # amber
         "YTD": (245, 241, 250)}      # violet
_SNAPSHOT = os.path.join(os.path.dirname(__file__), "reviews_snapshot.csv")

# Their name -> ours. Every one of these was confirmed by bill-series
# correlation (0.906 to 0.992), not by eye.
STORE_MAP = {
    "MANYAVAR AGARTALA": "Agartala",
    "MANYAVAR CC GHY": "City Centre GHY",
    "MANYAVAR CC2": "CC2 Rajarhat",
    "MANYAVAR CITY CENTRE": "City Centre SIL",
    "MANYAVAR JORHAT": "Jorhat",
    "MANYAVAR MALDA": "Malda",
    "MANYAVAR MNSQ": "Mani Square",
    "MANYAVAR RM GHY": "Roodraksh Mall",
    "MANYAVAR SVR": "Siliguri 2",
    "MANYAVAR VEGA MALL": "VEGA Circle Mall",
    "MOHEY SILIGURI": "Siliguri",
    "MOHEY MANYAVAR DIBRUGARH": "Dibrugarh",
    "MOHEY MANYAVAR FAIRFIELD": "Fairfield",
    "MOHEY MANYAVAR SILCHAR": "Silchar",
}

# The block's columns, in order, after the store name.
_FIELDS = ["day_bill", "day_review", "day_pct", "mtd_bill", "mtd_review",
           "mtd_pct", "q_bill", "q_review", "q_pct", "ytd_bill", "ytd_review",
           "ytd_pct"]

_PROBLEM = None


def last_problem():
    return _PROBLEM


def parse_workbook(path) -> pd.DataFrame:
    """One row per store per day: date, store, reviews (and their bill count).

    Their bill column is kept only so the two can be reconciled; the reports
    use the POS.
    """
    rows = []
    xl = pd.ExcelFile(path)
    for tab in xl.sheet_names:
        if "rule" in tab.lower():          # the incentive-rules tabs
            continue
        raw = pd.read_excel(path, sheet_name=tab, header=None)
        day = None
        for _, r in raw.iterrows():
            a = r.iloc[0]
            if not isinstance(a, str) and hasattr(a, "year"):
                day = pd.Timestamp(a)
                continue
            name = str(a).strip().upper()
            if (not name or name == "NAN" or name in ("STORE NAME", "TOTAL")
                    or "INCENTIVE" in name or day is None):
                continue
            ours = STORE_MAP.get(name)
            if ours is None:
                continue                   # anything not a mapped store
            rec = {"date": day, "store": ours, "their_name": name}
            for i, f in enumerate(_FIELDS, start=1):
                rec[f] = r.iloc[i] if i < len(r) else None
            rows.append(rec)
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    for f in _FIELDS:
        d[f] = pd.to_numeric(d[f], errors="coerce")
    # A store repeated within a day (the sheet is hand-kept) keeps the last.
    return (d.dropna(subset=["day_review"])
             .drop_duplicates(["date", "store"], keep="last")
             .sort_values(["date", "store"]).reset_index(drop=True))


# ★★ NO MACHINE'S HOME DIRECTORY IN THE CODE (6 Sep 2026). The manual workbook
# used to be named as `/Users/manavbansal/Downloads/...` in two places in
# `app.py` and one in the resolver. On the Space that path does not exist, so
# the fallback could never fire there — and the one time it mattered it would
# have failed for a reason nobody could see from the logs. The workbook is now
# looked for where a deployment can actually put it: an explicit env var, then
# the project's own folder, then the local Downloads as a DEVELOPER
# convenience — last, and only if it happens to be there.
_MANUAL_ENV = "REVIEWS_WORKBOOK"
_MANUAL_NAMES = ("Google review.xlsx", "Manyavar Google Review Sheet.xlsx")


def manual_paths() -> list[str]:
    """Where the hand-kept workbook might be, best first."""
    out = []
    named = os.environ.get(_MANUAL_ENV)
    if not named:
        try:
            import streamlit as st
            named = st.secrets.get(_MANUAL_ENV)
        except Exception:
            named = None
    if named:
        out.append(named)
    here = os.path.dirname(os.path.abspath(__file__))
    for n in _MANUAL_NAMES:
        out.append(os.path.join(here, n))
    home = os.path.expanduser("~/Downloads")
    if os.path.isdir(home):
        out += [os.path.join(home, n) for n in _MANUAL_NAMES]
    return out


def load(paths=None) -> pd.DataFrame | None:
    """Reviews from wherever they can be had, best source first.

    Order: an explicit REVIEWS_URL, then any workbook the caller names, then
    the committed snapshot. A snapshot that is merely stale is far better than
    a page that cannot answer at all — but the caller is told which it got, so
    the report can say how old its figures are.
    """
    global _PROBLEM
    _PROBLEM = None

    url = os.environ.get(URL_ENV)
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get(URL_ENV)
        except Exception:
            url = None
    if url:
        try:
            return parse_workbook(url)
        except Exception as e:            # noqa: BLE001 - fall through, and say so
            _PROBLEM = f"could not read {URL_ENV}: {type(e).__name__}"

    for p in (paths or []):
        try:
            if os.path.exists(p):
                return parse_workbook(p)
        except Exception as e:            # noqa: BLE001
            _PROBLEM = f"could not read {os.path.basename(p)}: {type(e).__name__}"

    if os.path.exists(_SNAPSHOT):
        d = pd.read_csv(_SNAPSHOT, parse_dates=["date"])
        if not _PROBLEM:
            _PROBLEM = "reading the committed snapshot, not a live sheet"
        return d
    _PROBLEM = "no review source configured"
    return None


def save_snapshot(d: pd.DataFrame, path=None) -> str:
    path = path or _SNAPSHOT
    d.to_csv(path, index=False)
    return path


def load_best(manual_paths=None) -> tuple:
    """Reviews from the automated reading if it can answer, else the workbook.

    ★ THE AUTOMATED COUNT IS DERIVED FROM A DIFFERENCE, so it needs at least two
    readings before it can report a single day. Until then the hand-kept
    workbook is the only source that can, and swapping to a source that says
    "0 reviews everywhere" because it has one reading would be worse than
    useless — it would look like a collapse.

    Returns (frame, source_label) so the report can print which it used.
    """
    try:
        import google_reviews as G
        auto = G.daily_reviews()
        if auto is not None and not auto.empty:
            days = auto["date"].nunique()
            d = auto.rename(columns={"reviews": "day_review"})[
                ["date", "store", "day_review", "removed", "days_covered"]]
            return d, (f"read automatically from Google, {days} day(s) of "
                       f"counts so far")
    except Exception:                     # noqa: BLE001 - fall through and say so
        pass

    d = load(manual_paths if manual_paths is not None else globals()
             ["manual_paths"]())
    if d is None or d.empty:
        return None, "no source available"
    return d, "the team's hand-kept review workbook"


# --------------------------------------------------------------------------- #
#  The report
# --------------------------------------------------------------------------- #
def settled_day(reviews: pd.DataFrame, bills: pd.DataFrame, asof=None):
    """The newest day that has BOTH a review reading and bills.

    ★ THE REPORT MUST NOT END ON A DAY IT DID NOT READ. The collector missed
    4 September — the Mac was asleep at 07:30 — so that day had bills, no
    reading, and the whole Day block printed as zeros and dashes: three empty
    columns that read as "nobody reviewed" rather than "we did not look". The
    last day both halves cover is 3 September, and that is where the report
    ends. Same discipline as [[feedback-settled-window]].
    """
    r = set(pd.to_datetime(reviews["date"]).dt.normalize())
    b = set(pd.to_datetime(bills["date"]).dt.normalize())
    both = sorted(r & b)
    if not both:
        return None
    return both[-1] if asof is None else min(both[-1], pd.Timestamp(asof))


def build(reviews: pd.DataFrame, bills: pd.DataFrame, asof) -> dict:
    """Day / month / quarter / year, per store, reviews against POS bills.

    `bills` is (store, date, bills) from the POS — the denominator is never the
    sheet's own hand count.
    """
    asof = pd.Timestamp(asof)
    r = reviews[reviews["date"] <= asof]
    b = bills[bills["date"] <= asof]

    fy = asof.year if asof.month >= 4 else asof.year - 1
    windows = {
        "Day": (asof, asof),
        "MTD": (asof.replace(day=1), asof),
        "QTD": (pd.Timestamp(fy if (asof.month - 4) % 12 < 12 else fy, 4, 1)
                + pd.DateOffset(months=3 * (((asof.month - 4) % 12) // 3)), asof),
        "YTD": (pd.Timestamp(fy, 4, 1), asof),
    }

    out = {}
    for name, (s, e) in windows.items():
        rw = r[(r.date >= s) & (r.date <= e)]
        bw = b[(b.date >= s) & (b.date <= e)]

        # ★★ THE TWO HALVES MUST COVER THE SAME DAYS. This is the single most
        # dangerous thing in this report and it nearly shipped.
        #
        # The automated source derives a day's reviews from the CHANGE in a
        # store's running Google total, so it can only speak for days it
        # actually read — collection began on 23 August. The POS has every day
        # since 1 April. Divided naively, the year read
        #
        #     169 reviews (10 days) / 22,908 bills (157 days) = 0.74%
        #
        # against 9.63% for the month, and NOTHING on the page said the two
        # numbers described different spans. A missed morning did it in
        # miniature: no reading on 4 Sep, so the day printed 0.00% — "nobody
        # reviewed today" when the truth was "we did not look".
        #
        # So bills are counted ONLY on the days that store has a reading, per
        # store, and the number of days behind each figure is carried out with
        # it. A rate over ten measured days is a real rate; the same numerator
        # over a hundred and fifty-seven is an artefact.
        # See [[feedback-aggregate-ratios-in-pairs]] and [[feedback-same-estate]].
        # ★★ A READING COVERS THE DAYS SINCE THE LAST ONE, NOT JUST ITS OWN.
        # The collector missed 24-25 Aug and 4 Sep, so the 26 Aug reading holds
        # THREE days of reviews and the 5 Sep reading holds two — 86 of the 206
        # collected. Paired against one day of bills, those dates read far too
        # high and the skipped days read zero. The span is expanded here so the
        # numerator and the denominator cover the same calendar either way.
        # This is the same fault as the year-vs-ten-days one, one gap wide.
        if "days_covered" in rw.columns:
            spans = []
            for st_, dt, n in zip(rw["store"], rw["date"],
                                  rw["days_covered"].fillna(1)):
                for k in range(int(n)):
                    spans.append((st_, pd.Timestamp(dt) - pd.Timedelta(days=k)))
            seen = pd.DataFrame(spans, columns=["store", "date"]).drop_duplicates()
            seen = seen[(seen["date"] >= s) & (seen["date"] <= e)]
        else:
            seen = rw[rw["day_review"].notna()][["store", "date"]].drop_duplicates()
        paired = bw.merge(seen, on=["store", "date"], how="inner")

        rr = rw.groupby("store")["day_review"].sum()
        rm = (rw.groupby("store")["removed"].sum() if "removed" in rw.columns
              else rr * 0)
        bb = paired.groupby("store")["bills"].sum()
        days = paired.groupby("store")["date"].nunique()
        traded = bw.groupby("store")["date"].nunique()

        t = pd.DataFrame({"Reviews": rr, "Removed": rm, "Bills": bb,
                          "Days": days, "Traded": traded})
        # Only stores this sheet actually covers; the rest have no numerator and
        # a 0% would read as "nobody reviewed" rather than "not measured".
        t = t[t.index.isin(reviews["store"].unique())]
        _n = ["Reviews", "Removed", "Bills", "Days", "Traded"]
        t[_n] = t[_n].fillna(0)
        # ★ NO MEASURED DAY, NO RATE. Blank, never zero — see above.
        t["Rate %"] = (t.Reviews / t.Bills.replace(0, pd.NA) * 100).where(
            t["Days"] > 0)
        out[name] = t.sort_values("Rate %", ascending=False, na_position="last")

    out["_windows"] = {k: v for k, v in windows.items()}
    out["_asof"] = asof
    # what each period could actually be measured over, for the page to say
    # ★ AN EMPTY WINDOW HAS NO MAXIMUM, AND `int(nan)` RAISES. A window with no
    # measured store — a fiscal year that has just turned, a store with no
    # reading yet — took the whole report down with a ValueError instead of
    # printing "0 days". Caught by the year-boundary test, which is the only
    # place an empty window occurs in the suite.
    def _days(col, k):
        v = out[k][col].max() if len(out[k]) else 0
        return 0 if v is None or pd.isna(v) else int(v)

    out["_cover"] = {k: {"measured": _days("Days", k),
                         "traded": _days("Traded", k)} for k in windows}
    return out


# --------------------------------------------------------------------------- #
#  PDF report
# --------------------------------------------------------------------------- #
def store_display(vdf) -> dict:
    """store label -> "MANYAVAR & MOHEY · Jayanagar", from the VFL feed.

    Manav, 9 Sep: *"for the names of the stores, can u pull them from the VFL
    sheet we have made. right now, i think u are doing more location names."*

    ★ THE VFL SHEET'S OWN `SHORT_NAME` IS ALSO A LOCATION NAME. It reads
    "Peanuts - Agartala", "Peanuts-CMH Road", "Peanuts Retail-Fairfield" — the
    same place with a prefix, and that prefix is spelled FOUR ways across the
    sheet. Every store is Peanuts, so the column would repeat it twenty times
    and distinguish nothing while eating width.

    The one name in the feed that carries information the location does not is
    `store_format` — MANYAVAR or MANYAVAR & MOHEY — which is exactly what the
    GD sheet and the festive store pages print as STORE NAME. So a store is
    named the way it already is everywhere else in the pack, and the two
    Kamraj Road shops stop looking like a duplicate.

    ★ THE KEY IS UNCHANGED. Only the label shown is; the figures are still
    joined on the store label, so a rename cannot silently drop a store.
    """
    import loader as L
    if vdf is None or "store_format" not in getattr(vdf, "columns", []):
        return {}
    fmt = (vdf.dropna(subset=["store_format"])
           .groupby(L.COL_STORE_LABEL)["store_format"]
           .agg(lambda x: x.value_counts().index[0]))
    return {st: f"{f} · {st}" for st, f in fmt.items()}


def wide_table(report: dict, names: dict | None = None) -> tuple:
    """One row per store, all four windows across — his own layout.

    ★ ALSO WHY THE PAGE IS SHARP. The pack renders text ONCE at final size and
    never resamples, so a page's dpi is decided by how many pixels the drawing
    lays down across a fixed 842pt sheet. Four narrow tables on four pages came
    out at 73 ppi against the pack's ~327; the same figures in ONE WIDE table
    fill the sheet and print at the pack's own quality. Layout and legibility
    happen to want the same thing here.
    """
    rows, order = {}, []
    for period in ("Day", "MTD", "QTD", "YTD"):
        t = report.get(period)
        if t is None:
            continue
        for store, r in t.iterrows():
            rows.setdefault(store, {"STORE": (names or {}).get(store, store)})
            rows[store][f"{period} BILLS"] = r["Bills"]
            rows[store][f"{period} GAINED"] = r["Reviews"]
            rows[store][f"{period} %"] = r["Rate %"]
            if store not in order:
                order.append(store)

    cols = ["STORE"]
    for period in ("Day", "MTD", "QTD", "YTD"):
        cols += [f"{period} BILLS", f"{period} GAINED", f"{period} %"]

    ytd = report.get("YTD")
    if ytd is not None and not ytd.empty:
        order = [s for s in ytd.sort_values("Rate %", ascending=False).index
                 if s in rows]
    disp = pd.DataFrame([rows[s] for s in order]).reindex(columns=cols)

    totals = {"STORE": "TOTAL"}
    for period in ("Day", "MTD", "QTD", "YTD"):
        t = report.get(period)
        if t is None or t.empty:
            continue
        b, v = t["Bills"].sum(), t["Reviews"].sum()
        totals[f"{period} BILLS"] = b
        totals[f"{period} GAINED"] = v
        totals[f"{period} %"] = (v / b * 100) if b else None
    disp = pd.concat([disp, pd.DataFrame([totals])], ignore_index=True)
    rt = ["data"] * (len(disp) - 1) + ["total"]
    pct = [c for c in disp.columns if c.endswith("%")]
    return disp, rt, pct


# --------------------------------------------------------------------------- #
#  The leaderboard — the block this report is actually read for               #
# --------------------------------------------------------------------------- #
def _bars(t, width, title, sub, names=None):
    """Stores ranked by review rate, as bars.

    ★★ THIS REPORT IS READ ON A PHONE (Manav, 5 Sep). Thirteen columns across a
    landscape sheet is a desk layout — on a handset it arrives as a grey grid
    nobody zooms into. A bar carries the ONE comparison that matters (who is
    asking for reviews and who is not) at a glance and at a size a thumb-scroll
    can read, and the exact figures still sit beside it.

    ★ THE BAR IS SCALED TO THE BEST STORE, NOT TO 100%. A review rate is not a
    percentage of anything bounded — a customer can review without buying, and
    the top store here is at 55% while most are under 15%. Against a 100% axis
    every bar would be a stub and the page would say nothing.
    """
    from PIL import Image, ImageDraw
    import portfolio_pdf as PP

    rows = [((names or {}).get(str(i), str(i)), float(r["Rate %"]),
             float(r["Reviews"]), float(r["Bills"]),
             float(r.get("Removed", 0) or 0))
            for i, r in t.iterrows() if pd.notna(r["Rate %"])]
    if not rows:
        return None
    rows.sort(key=lambda x: x[1], reverse=True)
    top = max(r[1] for r in rows) or 1.0

    # ★ SIZED FOR A HANDSET, NOT A DESK. The pack's ~7pt is right beside a GD
    # sheet and unreadable in a WhatsApp thread; the night SMS already makes
    # this distinction and this report is forwarded the same way.
    ttl_f, ttl_b = PP._ft(50)
    sub_f, _ = PP._ft(30)
    name_f, name_b = PP._ft(40)
    val_f, val_b = PP._ft(42)
    small_f, _ = PP._ft(28)

    name_w = int(width * 0.31)
    val_w = int(width * 0.15)
    cnt_w = int(width * 0.21)
    bar_w = width - name_w - val_w - cnt_w - PP._px(24)

    def _hh(f):
        a, b = f.getmetrics()
        return a + b

    th, sh = _hh(ttl_b), _hh(sub_f)
    row_h = int(_hh(name_b) * 1.95)
    head = th + 6 + sh + PP._px(16)
    img = Image.new("RGB", (width, head + row_h * len(rows)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((0, 0), title, font=ttl_b, fill=PP.INK)
    d.text((0, th + 6), sub, font=sub_f, fill=(90, 90, 90))

    y = head
    for name, rate, rev, bills, gone in rows:
        cy = y + (row_h - _hh(name_b)) // 2
        d.text((0, cy), name, font=name_b, fill=PP.INK)
        # the bar
        bx = name_w
        bh = int(row_h * 0.52)
        by = y + (row_h - bh) // 2
        d.rectangle([bx, by, bx + bar_w, by + bh], fill=(240, 240, 240))
        w = int(bar_w * (rate / top))
        if w > 0:
            d.rectangle([bx, by, bx + w, by + bh], fill=PP.HDR_BG,
                        outline=PP.GRID)
        # the figure, then what it is made of
        vx = name_w + bar_w + PP._px(12)
        txt = f"{rate:,.1f}%"
        d.text((vx + val_w - d.textlength(txt, font=val_b), cy), txt,
               font=val_b, fill=PP.INK)
        made = f"{rev:,.0f} of {bills:,.0f} bills"
        d.text((vx + val_w + PP._px(12), cy + PP._px(2)), made, font=small_f,
               fill=(90, 90, 90))
        # ★ A STORE LOSING REVIEWS SAYS SO, IN RED, ON THE SAME LINE. This is
        # the figure the report used to throw away, and it is the one a manager
        # can act on — reviews being taken down is a different problem from
        # reviews never being asked for, and the fix is not the same.
        if gone:
            gt = f"-{gone:,.0f} removed"
            d.text((vx + val_w + PP._px(12),
                    cy + PP._px(2) + int(_hh(small_f) * 1.05)), gt,
                   font=small_f, fill=PP.NEG_INK)
        y += row_h
    return img


def build_pdf(report: dict, coverage: dict, asof, basis_label="",
              names: dict | None = None) -> bytes:
    """The review report, built for a phone.

    ★ IT USED TO BE A COVER PAGE AND ONE WIDE GRID. The cover carried six lines
    on an otherwise empty sheet and the grid was thirteen columns of four-digit
    numbers — a desk layout for a report that gets forwarded into a WhatsApp
    group. Now: the leaderboard first, the rates beside it, every exact figure
    on a second page for anyone who wants to check, and the caveats as a block
    at the foot of page one rather than a page of their own.
    """
    import snapshots_a4 as A4
    import portfolio_pdf as PP

    asof = pd.Timestamp(asof)
    cov = report.get("_cover") or {}
    win = report.get("_windows") or {}

    _keep = (A4.MARGIN, A4.CONTENT_W, PP.PAD_Y)
    A4.MARGIN = A4.PRINT_MARGIN
    A4.CONTENT_W = A4.PAGE_W - 2 * A4.MARGIN
    try:
        usable = A4.PAGE_H - 2 * A4.MARGIN
        W = A4.CONTENT_W

        title = A4._heading(
            W, "Google reviews",
            f"Peanuts Retail  ·  as of {asof:%d %b %Y}  ·  "
            f"{coverage.get('measured', 0)} of {coverage.get('total', 0)} stores "
            f"measured  ·  the movement in each store's public Google rating "
            f"count")

        # ---- the four figures worth a card ------------------------------
        import snapshots as SN
        mt, qt = report.get("MTD"), report.get("QTD")
        m_rev = float(mt["Reviews"].sum()) if mt is not None else 0
        m_bil = float(mt["Bills"].sum()) if mt is not None else 0
        q_rev = float(qt["Reviews"].sum()) if qt is not None else 0
        q_bil = float(qt["Bills"].sum()) if qt is not None else 0
        best = (qt[qt["Rate %"].notna()].sort_values("Rate %", ascending=False)
                if qt is not None else None)
        worst = best.iloc[-1] if best is not None and len(best) else None
        q_gone = float(qt["Removed"].sum()) if qt is not None else 0
        cards = SN._cards_image([
            ("Ratings gained this month", f"{m_rev:,.0f}"),
            ("This month's rate", f"{m_bil and m_rev / m_bil * 100 or 0:,.1f}%"),
            ("Removed by Google", f"-{q_gone:,.0f}" if q_gone else "0"),
            ("Best store", (best.index[0] if best is not None and len(best)
                            else "—")),
        ], W, label_px=30, value_px=54)

        # ---- the leaderboard --------------------------------------------
        qlo, qhi = win.get("QTD", (asof, asof))
        c = cov.get("QTD", {})
        bars = _bars(qt, W, "Who is being reviewed",
                     f"{qlo:%d %b} to {qhi:%d %b %Y}  ·  "
                     f"{c.get('measured', 0)} days actually read  ·  "
                     f"bar scaled to the best store, not to 100%",
                     names=names)

        # ---- the caveats, at the foot rather than on a page of their own --
        days = " · ".join(
            f"{k} {cov[k]['measured']} of {cov[k]['traded']} days"
            for k in ("Day", "MTD", "QTD", "YTD") if k in cov)
        note = A4._note_section(W, "What this is, and what it is not", [
            f"Days actually read — {days}. Every rate is ratings over the bills "
            f"of THE SAME DAYS; a period with no reading is blank, never 0%.",
            "THIS COUNTS THE MOVEMENT IN A STORE'S PUBLIC GOOGLE RATING "
            "COUNT, not a list of reviews. Google's public interface gives no "
            "way to list reviews by date — it returns five, and not the most "
            "recent five — so a day's figure is the change in the running "
            "total. A rating left and one removed on the same day cancel out.",
            "Removals are now shown in red beside the store. They used to be "
            "counted as zero, which is why a store could look quiet when its "
            "reviews were being taken down as fast as they arrived.",
            "A rate over 100% on one day is not an error. A rating is not tied "
            "to that day's bill — somebody can rate a week after buying, or "
            "without buying at all. One store-day is only a handful of bills, "
            "so read the month and the quarter, not the day.",
            "The quarter and the year are identical until 1 October: counting "
            "began on 23 August, which is inside this quarter.",
            "To count actual reviews with their dates, this needs OWNER "
            "access to the listings through the Google Business Profile API. "
            "Until then every figure here is net public movement.",
        ])

        sheet = A4._Sheet("Google reviews", asof, "", bounded=False, footer=True)
        sheet.put(title, gap=22)
        if cards is not None:
            sheet.put(cards, gap=20)
        if bars is not None:
            sheet.put(bars, gap=26)
        sheet.put(note, gap=18)

        # ---- page two: every figure ---------------------------------------
        two = None
        disp, rt, pct = wide_table(report, names)
        if len(disp) > 1:
            counts = [c2 for c2 in disp.columns
                      if c2.endswith("BILLS") or c2.endswith("GAINED")]
            g_title = A4._heading(
                W, "Every figure",
                "bills, reviews and the rate on each of the day, the month, "
                "the quarter and the year")
            g_fixed = g_title.height + 22 + 22
            best_fit = None
            for pad in (14, 12, 10, 8, 6, 5, 4, 3, 2):
                PP.PAD_Y = PP._px(pad)
                lo, hi, here = A4.FONT_MIN, A4.FONT_MAX, None
                while lo <= hi:
                    mid = (lo + hi) // 2
                    m = A4._measure(disp, counts, pct, pct, mid)
                    h = m["head_h"] + m["row_h"] * len(disp)
                    if m["W"] <= W and g_fixed + h <= usable:
                        here, lo = (mid, m), mid + 1
                    else:
                        hi = mid - 1
                if here and (best_fit is None or here[0] > best_fit[0]):
                    best_fit = (here[0], pad, here[1])
            if best_fit is None:
                PP.PAD_Y = PP._px(2)
                best_fit = (A4.FONT_MIN, 2,
                            A4._measure(disp, counts, pct, pct, A4.FONT_MIN))
            PP.PAD_Y = PP._px(best_fit[1])
            two = A4._Sheet("Google reviews", asof, "", bounded=False,
                            footer=True)
            two.put(g_title, gap=22)
            # ★ A WASH PER PERIOD. Twelve number columns in one flat run is
            # where an eye loses which window it is reading — the same reason
            # the salesperson sheet blocks its day, month and year.
            # QTD is banded too, though he named three: it sits between MTD and
            # YTD here, and leaving one group of four uncoloured would read as
            # a mistake rather than a choice.
            band = {j: _BAND[str(c).split()[0]]
                    for j, c in enumerate(disp.columns)
                    if str(c).split()[0] in _BAND}
            two.put(PP._render_chunk(A4._widen(best_fit[2], W), rt,
                                     list(range(len(disp))), col_bg=band),
                    gap=22)

        # ★★ EACH SHEET IS CROPPED BY ITS OWN CONTENT. `_footers` crops every
        # page it holds to ONE height — the height of what THAT sheet drew — so
        # appending page two onto page one's sheet would have cut the table off
        # the moment page one happened to be the shorter of the two. It did not
        # today, which is exactly the kind of luck that ships. Foot each sheet
        # separately, then join the finished pages.
        parts = [sheet] + ([two] if two is not None else [])
        pages = []
        for part in parts:
            part._footers()
            pages += part.pages
        buf = io.BytesIO()
        pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:],
                      resolution=A4.PAGE_W * 72.0 / A4.PAGE_PT_W)
        return buf.getvalue()
    finally:
        A4.MARGIN, A4.CONTENT_W, PP.PAD_Y = _keep
