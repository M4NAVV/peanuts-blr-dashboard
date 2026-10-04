"""Graph analysis VFL — every VFL store, this year against last, day by day.

Page 1 summarises; then the VFL portfolio, the two regions and a page per store:
daily sales (7-day average) for both years on the same calendar dates, the month's
TARGET per day, the region's movable festivals in a lane above, and three numbers
that answer "is the gap the festival moving?". Built from `festival_timing_pack.py`
(2 Oct 2026); in the VFL reports tab since 4 Oct.

★ FESTIVAL DATES come from the sheet's `impfestiveclaude` tab (his, 4 Oct), read
on every build, so an edit there shows in the next pack. `festive_dates.csv` is a
saved copy used only when the sheet cannot be read, and page one says so.
"""
from __future__ import annotations
import io, os, textwrap
import pandas as pd, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager as fm
from matplotlib.backends.backend_pdf import PdfPages
import loader as L, festive as F, targets as T

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "assets", "fonts", "NotoSans.ttf")
DRAFT = os.path.join(HERE, "festive_dates.csv")
INK, QUIET, RULE = "#14211a", "#6b766f", "#e3e6e0"
TY_C, LY_C, BAD = "#1d6b34", "#9aa39c", "#a3342a"
TG_C = "#a8771c"                          # the plan: a muted gold, apart from both years
YR = pd.DateOffset(years=1)
REGION_OF = {"East & NE": "East", "South": "South"}

# set by _setup() for each build — the drawing code below reads them as module state
df = ASOF = FY0 = FY1 = master = TAKEOVER = CODE_OF = TARGETS = PUJA = None
MONTHLY, FESTS = {}, []


def _rc():
    try:
        fm.fontManager.addfont(FONT)
        family = fm.FontProperties(fname=FONT).get_name()
    except Exception:
        family = "DejaVu Sans"             # LFS font missing: a plain face, never a crash
    plt.rcParams.update({"font.family": family, "font.size": 9, "axes.edgecolor": "#c9cdc6",
                         "axes.linewidth": .6, "xtick.color": "#5b665f", "ytick.color": "#5b665f",
                         "xtick.major.size": 0, "ytick.major.size": 0, "pdf.fonttype": 42})


def _norm(name):
    return (name or "").split("(")[0].split("/")[0].strip().lower()


def _parse_rows(tab):
    out = {}
    for _, r in tab.iterrows():
        c0 = r.iloc[0] if len(r) > 0 else None
        c2 = r.iloc[2] if len(r) > 2 else None
        n1, ty, _ = F._parse_cell(c0) if isinstance(c0, str) else (None, None, None)
        n2, ly, _ = F._parse_cell(c2) if isinstance(c2, str) else (None, None, None)
        name = (n1 or n2 or "").split("(")[0].split("/")[0].strip()
        if not name:
            continue
        seen = r.get("Seen in last year's sales")
        out[_norm(name)] = dict(name=name, ly=ly, ty=ty,
                                region=str(r.get("Region") if isinstance(r.get("Region"), str) else "All").strip(),
                                tenure=isinstance(r.get("Tenure1"), str),
                                seen=isinstance(seen, str) and bool(seen.strip()))
    return out


TAB = "impfestiveclaude"                  # his sheet's tab, added 4 Oct
SOURCE = ""                               # what page one says the dates came from


def _tab():
    """The impfestiveclaude tab, or None.

    ★ GOOGLE ANSWERS A WRONG TAB NAME WITH THE FIRST TAB, NOT AN ERROR — a
    misspelt name came back as 305,745 rows of sales. So the frame must LOOK
    like the festival table (an `FY …` column and a Region column) to be used.
    """
    try:
        base = F._url()
        if not base:
            return None
        u = base.split("&sheet=")[0] + "&sheet=" + TAB if "&sheet=" in base else None
        if not u:
            return None
        t = pd.read_csv(u, dtype=str)
    except Exception:
        return None
    ok = "Region" in t.columns and any(str(c).startswith("FY ") for c in t.columns)
    return t if ok and len(t) < 500 else None


def festivals():
    """[festival dicts] — from the sheet's impfestiveclaude tab; the copy saved in
    the repo (`festive_dates.csv`) only when the sheet cannot be read, and page
    one says which."""
    global SOURCE
    t = _tab()
    if t is not None:
        SOURCE, rows = f"Festival dates: the {TAB} sheet", _parse_rows(t)
    else:
        SOURCE = "Festival dates: saved copy (the sheet could not be read)"
        rows = _parse_rows(pd.read_csv(DRAFT, dtype=str)) if os.path.exists(DRAFT) else {}
    out = []
    for v in rows.values():
        if v.get("ty") is None or v.get("ly") is None:
            continue
        out.append(dict(name=v["name"], ly=v["ly"], ty=v["ty"], region=v.get("region", "All"),
                        shift=(v["ty"] - (v["ly"] + YR)).days,
                        major=bool(v.get("seen")) or bool(v.get("tenure"))))
    return out


def _setup(df_in, asof=None):
    global df, ASOF, FY0, FY1, master, TAKEOVER, CODE_OF, TARGETS, MONTHLY, FESTS, PUJA
    ASOF = pd.Timestamp(asof).normalize() if asof is not None else df_in["date"].max()
    df = df_in[df_in["date"] <= ASOF]
    FY0 = pd.Timestamp(ASOF.year if ASOF.month >= 4 else ASOF.year - 1, 4, 1)
    FY1 = pd.Timestamp(FY0.year + 1, 3, 31)
    master = L.load_store_master()
    TAKEOVER = L.takeover_map()
    CODE_OF = {str(n): int(c) for n, c in zip(master["tableau_name"],
                                              pd.to_numeric(master["code"], errors="coerce")) if pd.notna(c)}
    TARGETS = T.for_month(ASOF)
    MONTHLY = {}
    tt = T.load()
    if tt is not None:
        cols = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
        for _, r in tt.iterrows():
            MONTHLY[int(r["code"])] = [(float(r[c]) if c in tt.columns and pd.notna(r[c]) and float(r[c]) > 0
                                        else None) for c in cols]
    FESTS = festivals()
    PUJA = next((f for f in FESTS if f["name"].lower().startswith("durga puja")), None)
    if PUJA is None:
        raise ValueError("no Durga Puja dates for both years: check the ImpFestiveDates tab")


def daily_target(codes, starts):
    """★ THE PLAN AS A DAILY RATE, so it sits on the same scale as the sales lines: each
    month's target spread over its days — over the days FROM THE STORE'S START in the month
    it begins (South's April target covers 19–30 April, not all thirty). Summed across
    stores; a month any store has left blank is left blank for the total."""
    idx = pd.date_range(FY0, FY1)
    total = pd.Series(0.0, index=idx)
    for c, st in zip(codes, starts):
        row = MONTHLY.get(c)
        if not row:
            return None
        s = pd.Series(float("nan"), index=idx)
        for k, v in enumerate(row):
            m0 = (FY0 + pd.DateOffset(months=k)).normalize()
            m1 = m0 + pd.offsets.MonthEnd(0)
            a = max(m0, st)
            if v is None or a > m1:
                continue
            s[a:m1] = v / ((m1 - a).days + 1)
        if st > FY0:
            s[:st - pd.Timedelta(days=1)] = 0.0
        total = total + s
    return total if total.notna().any() else None


def target_due(codes):
    """★ PACE FROM HIS OWN MONTHLY PLAN, not an even spread. The targets tab weights the
    festive months heavily; against a straight line every store read red in October. Due =
    every past month's target + this month's pro rata. None if a month needed is blank."""
    m_idx = (ASOF.month - 4) % 12
    days_in = pd.Period(ASOF, "M").days_in_month
    due = 0.0
    for c in codes:
        row = MONTHLY.get(c)
        if not row or any(v is None for v in row[:m_idx + 1]):
            return None
        due += sum(row[:m_idx]) + row[m_idx] * ASOF.day / days_in
    return due

SHORT = {"Pohela Boishakh": "Poila Boishakh", "Navratri": "Navratri", "Durga Puja": "Puja / Dasara",
         "Diwali": "Diwali", "Vasant Panchami": "Saraswati Puja", "Makar Sankranti": "Sankranti",
         "Bohag Bihu": "Bihu", "Ganesh Chaturthi": "Ganesh Chaturthi", "Eid al-Fitr": "Eid",
         "Akshaya Tritiya": "Akshaya Tritiya", "Dhanteras": "Dhanteras"}


def lane_fests(region):
    """The region's MOVABLE festivals that showed in last year's sales. A festival
    on the same date every year cannot explain a gap between the two years."""
    # Navratri and Dhanteras are the build-up to Puja and Diwali, a week or two
    # earlier: drawn separately they stack four labels into three weeks. The
    # headline festival of each cluster carries it.
    skip = ("Navratri", "Dhanteras", "Mahalaya", "Kali Puja", "Govardhan")
    regions = ("East", "South", "All") if region == "Both" else (region, "All")
    out = [f for f in FESTS if f["major"] and f["shift"] != 0 and f["region"] in regions
           and not f["name"].startswith(skip)]
    seen, keep = set(), []
    for f in sorted(out, key=lambda f: f["ty"]):           # Kali Puja = Diwali night: one mark
        if (f["ly"], f["ty"]) in seen:
            continue
        seen.add((f["ly"], f["ty"]))
        keep.append(f)
    return keep


# ----------------------------------------------------------------------------- helpers
def pct(a, b):
    return (a - b) / b * 100 if b else None


def fp(p):
    return "—" if p is None else f"{p:+.1f}%"


def lakh(v):
    return f"Rs {v / 1e5:,.2f} L"


PARTLY = 5.0      # points lining-up must recover before the festival "explains part" of it


def reading(m):
    """What explains SEPTEMBER's gap — one phrase, from the same numbers as the verdict."""
    if m["ly_none"]:
        return "New store"
    if m["run"] is not None and m["run"] >= 0:
        return "No September gap"
    if m["al"] is not None and m["al"] >= 0:
        return "Festival timing"
    if m["al"] is not None and m["run"] is not None and m["al"] - m["run"] >= PARTLY:
        return "Partly festival"
    return "Store"


def store_series(store):
    """(daily sales, the day comparisons begin, the day the target year begins)."""
    d = df[df[L.COL_STORE_LABEL] == store].groupby("date")[L.COL_AMOUNT].sum()
    tk = TAKEOVER.get(store)
    start = FY0
    if tk is not None and pd.notna(tk) and pd.Timestamp(tk) > FY0:
        start = pd.Timestamp(tk)
    tgt_start = start                      # the target covers the year the store is ours
    # ★ BEGIN WHERE LAST YEAR BEGINS. Silchar's history starts 1 Jun 2025; compared
    # from April it read +88.6% against weeks that held nothing.
    ly_days = d[(d.index >= start - YR) & (d.index <= ASOF - YR) & (d > 0)].index
    if len(ly_days) and ly_days.min() > start - YR + pd.Timedelta(days=7):
        start = ly_days.min() + YR
    return d, start, tgt_start


def metrics_from(d, start, label, target=None, tgt_start=None, due=None):
    ty = d.reindex(pd.date_range(start, ASOF), fill_value=0.0)
    ly_all = d.reindex(pd.date_range(start - YR, FY1 - YR), fill_value=0.0)
    ly_all.index = ly_all.index + YR
    upto = ly_all[ly_all.index <= ASOF]
    pre_end = PUJA["ly"] + YR - pd.Timedelta(days=30)        # day before LY's 30-day run-up
    lead = (PUJA["ty"] - ASOF).days
    n = (ASOF - pre_end).days
    al_ty = ty[ty.index > ASOF - pd.Timedelta(days=n)].sum()
    al_end = PUJA["ly"] - pd.Timedelta(days=lead)
    al_ly = d[(d.index > al_end - pd.Timedelta(days=n)) & (d.index <= al_end)].sum()
    m = dict(store=label, start=start, d=d, ty=ty, ly=ly_all, pre_end=pre_end, lead=lead, n=n,
             ytd=pct(ty.sum(), upto.sum()),
             pre=pct(ty[ty.index <= pre_end].sum(), upto[upto.index <= pre_end].sum()),
             run_ty=ty[ty.index > pre_end].sum(), run_ly=upto[upto.index > pre_end].sum(),
             al_ty=al_ty, al_ly=al_ly, al_end=al_end, ly_none=upto.sum() == 0)
    m["run"] = pct(m["run_ty"], m["run_ly"])
    m["al"] = pct(al_ty, al_ly)
    m["read"] = reading(m)
    # ★ THE YEAR'S TARGET, AGAINST THE YEAR SO FAR. Achieved counts every day of the target
    # year (Silchar's April counts here even though it has no last year to compare with),
    # and is read against PACE — how much of the year has gone — never against 100%.
    ts = tgt_start or start
    m["target"] = target
    m["achieved"] = float(d[(d.index >= ts) & (d.index <= ASOF)].sum())
    m["ach_pct"] = m["achieved"] / target * 100 if target else None
    m["pace"] = ((ASOF - ts).days + 1) / ((FY1 - ts).days + 1) * 100
    m["pace_kind"] = "of the year gone"
    if due and target:
        m["pace"] = due / target * 100
        m["pace_kind"] = "due by today on the monthly plan"
    return m


def metrics(store):
    d, start, ts = store_series(store)
    code = CODE_OF.get(store, -1)
    tgt = TARGETS.get(code, {}).get("ytd")
    m = metrics_from(d, start, store, tgt, ts, target_due([code]))
    m["tgt_daily"] = daily_target([code], [ts])
    return m


def combined(stores):
    """Many stores as one: each counted only over the days IT is compared on (its own
    start, both years), so the total is like to like. Stores with no last year are left
    out of the comparison and named."""
    parts, left_out, target, codes, tstarts = [], [], 0.0, [], []
    for s in stores:
        d, start, ts = store_series(s)
        if d[(d.index >= start - YR) & (d.index <= ASOF - YR)].sum() <= 0:
            left_out.append(s)
            continue
        keep = ((d.index >= start - YR) & (d.index < FY0)) | (d.index >= start)
        parts.append(d[keep])
        target += TARGETS.get(CODE_OF.get(s, -1), {}).get("ytd") or 0.0
        codes.append(CODE_OF.get(s, -1))
        tstarts.append(ts)
    total = pd.concat(parts).groupby(level=0).sum() if parts else pd.Series(dtype=float)
    return total, left_out, (target or None), codes, tstarts


def verdict(m):
    if m["ly_none"]:
        return "A new store: there is no last year to compare with."
    if m["run"] is not None and m["run"] >= 0:
        if m["pre"] is not None and m["pre"] < 0:
            return (f"Down before the festive season ({fp(m['pre'])}) but up through last year's festival weeks "
                    f"({fp(m['run'])}): the festival is not where this store's gap is.")
        return (f"Up before the festive season ({fp(m['pre'])}) and through it ({fp(m['run'])}): "
                f"there is no decline for the festival to explain.")
    if m["al"] is not None and m["al"] >= 0:
        return (f"Lined up to each year's Puja the store is {fp(m['al'])}: the fall since "
                f"{m['pre_end'] + pd.Timedelta(days=1):%d %b} is the festival moving, not the store.")
    if m["al"] is not None and m["run"] is not None and m["al"] - m["run"] >= PARTLY:
        return (f"The festival moving explains part of it: lined up to Puja the store is {fp(m['al'])}, "
                f"not {fp(m['run'])}. The rest is the store.")
    return "Even lined up to the festival the store is down: the timing is not the reason."


def colour(p):
    return QUIET if p is None else (BAD if p < 0 else TY_C)


# ----------------------------------------------------------------------------- store page
def store_page(pdf, m, region, city, lane_region=None, note=None):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(.055, .925, m["store"], fontsize=22, color=INK)
    head = " · ".join(x for x in (city, region) if x)
    fig.text(.055, .893, f"{head} · daily sales, this year against last · "
             f"{m['start']:%d %b} – {ASOF:%d %b %Y}, last year on the same dates", fontsize=10, color=QUIET)
    fig.text(.945, .925, fp(m["ytd"]), fontsize=22, ha="right", color=colour(m["ytd"]))
    fig.text(.945, .893, "year to date vs last year", fontsize=10, ha="right", color=QUIET)
    if m.get("target"):
        on_pace = m["ach_pct"] >= m["pace"]
        fig.text(.945, .862, f"YTD target Rs {m['target'] / 1e7:,.2f} Cr  ·  {m['ach_pct']:.1f}% achieved  ·  "
                 f"{m['pace']:.0f}% {m['pace_kind']}", fontsize=9.5, ha="right",
                 color=(TY_C if on_pace else BAD))
    else:
        fig.text(.945, .862, "No YTD target in the targets tab", fontsize=9.5, ha="right", color=QUIET)

    fests = lane_fests(lane_region or REGION_OF.get(region, region))
    lane = fig.add_axes([.055, .755, .89, .08])
    lane.set_xlim(m["start"], FY1); lane.set_ylim(-1.3, 2.3); lane.axis("off")
    for yv, lab, col in ((1.0, "2025", LY_C), (0, "2026", TY_C)):
        lane.text(m["start"] - pd.Timedelta(days=3), yv, lab, fontsize=8, color=col, ha="right", va="center")
        lane.plot([m["start"], FY1], [yv, yv], color=RULE, lw=.6, zorder=0)
    last = {1.0: [], 0: []}                                  # stagger labels that would touch
    for f in fests:
        name = SHORT.get(f["name"], f["name"])
        x_ly, x_ty = f["ly"] + YR, f["ty"]
        if not (m["start"] <= x_ly <= FY1 or m["start"] <= x_ty <= FY1):
            continue
        lane.scatter([x_ly], [1.0], s=20, color=LY_C, zorder=3)
        lane.scatter([x_ty], [0], s=20, color=TY_C, zorder=3)
        lane.annotate("", xy=(x_ty, .1), xytext=(x_ly, .9),
                      arrowprops=dict(arrowstyle="->", color=INK, lw=.5, shrinkA=3, shrinkB=3))
        for yv, x, txt, col, va, base in ((1.0, x_ly, f"{name} {f['ly']:%d %b}", QUIET, "bottom", 1.28),
                                          (0, x_ty, f"{name} {f['ty']:%d %b} · {f['shift']:+d}d", TY_C, "top", -.28)):
            busy = {t for px, t in last[yv] if abs((x - px).days) < 52}
            tier = next(t for t in range(4) if t not in busy)       # first free level
            last[yv].append((x, tier))
            off = .55 * tier
            span = (FY1 - m["start"]).days
            pos = (x - m["start"]).days / span
            ha = "left" if pos < .06 else ("right" if pos > .94 else "center")
            lane.text(x, base + (off if yv else -off), txt, fontsize=6.6, color=col, ha=ha, va=va)

    ax = fig.add_axes([.055, .37, .89, .335], sharex=lane)
    ax.set_facecolor("none")
    ty7 = m["ty"].rolling(7, min_periods=7).mean()
    ly7 = m["ly"].rolling(7, min_periods=7).mean()
    ax.plot(ly7.index, ly7.values / 1e5, color=LY_C, lw=1.4, label="Last year (2025–26)")
    ax.plot(ty7.index, ty7.values / 1e5, color=TY_C, lw=2.1, label="This year (2026–27)")
    tg = m.get("tgt_daily")
    if tg is not None:
        tg = tg[tg.index >= m["start"]]
        ax.plot(tg.index, tg.values / 1e5, color=TG_C, lw=1.4, ls=(0, (5, 2.5)), drawstyle="steps-post",
                label="Target, per day")
    if ty7.notna().any():
        ax.scatter([ty7.index[-1]], [ty7.values[-1] / 1e5], color=TY_C, s=18, zorder=5)
        ax.annotate(f"today, {ASOF:%d %b}", xy=(ASOF, ty7.values[-1] / 1e5), xytext=(0, 11),
                    textcoords="offset points", fontsize=7.5, color=TY_C, ha="center",
                    bbox=dict(boxstyle="square,pad=.15", fc="white", ec="none"))
    peaks = [np.nanmax(ly7.values), np.nanmax(ty7.values)]
    if m.get("tgt_daily") is not None and m["tgt_daily"].notna().any():
        peaks.append(np.nanmax(m["tgt_daily"].values))
    top = np.nanmax(peaks) / 1e5 * 1.1
    ax.set_ylim(0, top if top > 0 else 1)
    for f in fests:
        ax.axvline(f["ly"] + YR, color=LY_C, lw=.6, ls=(0, (3, 3)), zorder=0)
        ax.axvline(f["ty"], color=TY_C, lw=.6, ls=(0, (3, 3)), zorder=0)
    ax.set_xlim(m["start"], FY1)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.1f} L"))
    ax.grid(axis="y", color=RULE, lw=.6)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.legend(loc="upper left", frameon=False, fontsize=8.5, ncol=3)
    if note:
        fig.text(.055, .874, note, fontsize=8.5, color=QUIET)
    fig.text(.055, .325, "Sales: 7-day averages.  Gold dashes: each month's target per day, as far as the targets "
             "tab is filled.  The lane above: festivals that move from year to year (draft dates).",
             fontsize=8, color=QUIET)

    pe = m["pre_end"]
    cells = [
        ("Before last year's festive season", f"{m['start']:%d %b} – {pe:%d %b}", m["pre"],
         f"How the {'business' if m.get('is_group') else 'store'} was trading when neither year had a festival."),
        ("During last year's season, on the calendar", f"{pe + pd.Timedelta(days=1):%d %b} – {ASOF:%d %b}", m["run"],
         f"This year {lakh(m['run_ty'])} against {lakh(m['run_ly'])}: last year's festival weeks, "
         f"this year's ordinary ones."),
        ("The same stretch, lined up to each year's Puja", f"{m['n']} days, {m['lead']} days before Puja", m["al"],
         f"This year {lakh(m['al_ty'])} against {lakh(m['al_ly'])} in the {m['n']} days ending "
         f"{m['al_end']:%d %b %Y}."),
    ]
    w = .89 / 3
    for i, (h, sub, val, note) in enumerate(cells):
        x = .055 + i * w
        fig.add_artist(plt.Line2D([x, x + w - .025], [.285, .285], color=INK, lw=.8))
        fig.text(x, .27, h, fontsize=10, color=INK, va="top")
        fig.text(x, .245, sub, fontsize=8.5, color=QUIET, va="top")
        fig.text(x, .222, fp(val), fontsize=24, va="top", color=colour(val))
        fig.text(x, .165, textwrap.fill(note, 50), fontsize=8.5, color=QUIET, va="top", linespacing=1.4)
    fig.add_artist(plt.Line2D([.055, .945], [.088, .088], color=RULE, lw=.8))
    fig.text(.055, .06, verdict(m), fontsize=11, color=INK, va="center")
    fig.text(.945, .06, f"Peanuts Retail · {ASOF:%d %b %Y}", fontsize=8, color=QUIET, ha="right")
    pdf.savefig(fig); plt.close(fig)


def tgt_txt(fig, y, m, size):
    """Achieved % of the year's target, coloured against PACE (how much of the year has gone)."""
    if not m.get("target"):
        fig.text(.79, y, "no target", fontsize=size - 1, ha="right", color=QUIET)
        return
    fig.text(.79, y, f"{m['ach_pct']:.1f}%", fontsize=size, ha="right",
             color=(TY_C if m["ach_pct"] >= m["pace"] else BAD))


# ----------------------------------------------------------------------------- summary page
def summary_page(pdf, rows, closed, totals):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(.055, .925, "Graph analysis VFL", fontsize=22, color=INK)
    fig.text(.055, .893, f"This year against last, {ASOF:%d %b %Y}. Puja falls {PUJA['shift']} days later "
             f"this year ({PUJA['ly']:%d %b %Y} to {PUJA['ty']:%d %b %Y}), so September compares last year's "
             "festival weeks with this year's ordinary ones.", fontsize=9.5, color=QUIET)
    fig.text(.055, .868, "Lined up = the same days before each year's Puja. Target achieved is coloured against "
             "the target due by today on the monthly plan.", fontsize=9.5, color=QUIET)
    fig.text(.945, .925, SOURCE, fontsize=8.5, color=QUIET, ha="right")
    cols = [("Store", .055, "left"), ("City", .185, "left"), ("Year to date", .37, "right"),
            ("Before the season", .475, "right"), ("Sept, on calendar", .58, "right"),
            ("Lined up to Puja", .685, "right"), ("Target achieved", .79, "right"), ("What explains Sept", .815, "left")]
    y = .815
    for name, x, ha in cols:
        fig.text(x, y, name.upper(), fontsize=7, color=QUIET, ha=ha)
    y -= .012
    fig.add_artist(plt.Line2D([.055, .945], [y, y], color=INK, lw=.8))
    step = min(.026, (y - .1) / (len(rows) + 6))
    for reg in ("East & NE", "South"):
        part = [r for r in rows if r["region"] == reg]
        if not part:
            continue
        y -= step * 1.25
        fig.text(.055, y, reg, fontsize=9.5, color=INK)
        t = totals[reg]
        for key, x in (("ytd", .37), ("pre", .475), ("run", .58), ("al", .685)):
            fig.text(x, y, fp(t[key]), fontsize=9.5, ha="right", color=colour(t[key]))
        tgt_txt(fig, y, t, 9.5)
        fig.text(.815, y, t["read"], fontsize=9, color=INK)
        y -= step * .45
        fig.add_artist(plt.Line2D([.055, .945], [y, y], color=RULE, lw=.6))
        for r in sorted(part, key=lambda r: (r["al"] is None, -(r["al"] or 0))):
            y -= step
            fig.text(.055, y, r["store"], fontsize=9, color=INK)
            fig.text(.185, y, r["city"], fontsize=9, color=QUIET)
            for key, x in (("ytd", .37), ("pre", .475), ("run", .58), ("al", .685)):
                fig.text(x, y, fp(r[key]), fontsize=9, ha="right", color=colour(r[key]))
            tgt_txt(fig, y, r["_m"], 9)
            fig.text(.815, y, r["read"], fontsize=9, color=(BAD if r["read"] == "Store" else INK))
    if closed:
        y -= step * 1.6
        fig.text(.055, y, "Not shown, no sales this year: " + ", ".join(closed) + ".", fontsize=8.5, color=QUIET)
    fig.add_artist(plt.Line2D([.055, .945], [.088, .088], color=RULE, lw=.8))
    fig.text(.055, .06, "What explains September — No September gap: up in last year's festival weeks.  Festival timing: "
             "down on the calendar, up when lined up.  Partly festival: lining up recovers 5+ points.  Store: down either way.",
             fontsize=8, color=QUIET, va="center")
    pdf.savefig(fig); plt.close(fig)



# ----------------------------------------------------------------------------- build
def build(df_in, asof=None):
    """-> (filename, pdf bytes). `df_in` is the VFL frame the app already holds."""
    _rc()
    _setup(df_in, asof)
    vfl = sorted(df[L.COL_STORE_LABEL].dropna().unique())
    m_by = master.set_index("tableau_name")
    rows, closed = [], []
    for s in vfl:
        reg = m_by.loc[s, "region"] if s in m_by.index else "?"
        city = str(m_by.loc[s, "city"]).title() if s in m_by.index and "city" in m_by.columns else ""
        code = m_by.loc[s, "code"] if s in m_by.index else 9999
        recent = df[(df[L.COL_STORE_LABEL] == s) & (df["date"] > ASOF - pd.Timedelta(days=30))][L.COL_AMOUNT].sum()
        if recent <= 0:
            closed.append(s)
            continue
        m = metrics(s)
        rows.append(dict(store=s, city=city, region=reg, code=pd.to_numeric(code, errors="coerce"),
                         ytd=m["ytd"], pre=m["pre"], run=m["run"], al=m["al"], read=m["read"], _m=m))
    groups = [("VFL portfolio", "Both", [r["store"] for r in rows]),
              ("East & North-East", "East", [r["store"] for r in rows if r["region"] == "East & NE"]),
              ("South", "South", [r["store"] for r in rows if r["region"] == "South"])]
    agg_pages, totals = [], {}
    for label, lane, stores in groups:
        if not stores:
            continue
        d, left_out, target, codes, tstarts = combined(stores)
        m = metrics_from(d, FY0, label, target, FY0, target_due(codes))
        m["tgt_daily"] = daily_target(codes, tstarts)
        m["is_group"] = True
        note = (f"{len(stores) - len(left_out)} stores, each counted over the days it can be compared"
                + (f"; {', '.join(left_out)} left out (no last year)" if left_out else "") + ".")
        agg_pages.append((m, lane, note))
        if label == "East & North-East":
            totals["East & NE"] = m
        elif label == "South":
            totals["South"] = m
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        summary_page(pdf, rows, closed, totals)
        for m, lane, note in agg_pages:
            store_page(pdf, m, "All VFL stores" if lane == "Both" else "Regional total", "",
                       lane_region=lane, note=note)
        for reg in ("East & NE", "South"):
            for r in sorted([r for r in rows if r["region"] == reg], key=lambda r: r["code"]):
                store_page(pdf, r["_m"], reg, r["city"])
    plt.close("all")
    return f"GRAPH ANALYSIS VFL {ASOF:%d-%m-%Y}.pdf", buf.getvalue()
