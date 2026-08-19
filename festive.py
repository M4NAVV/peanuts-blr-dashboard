"""Festive-window reports — the Puja and Diwali run-ups, this year against last.

★ WHY THESE CANNOT BE A NORMAL WINDOW. Puja fell on 13 Oct 2024, 2 Oct 2025 and
falls on 20 Oct 2026; Diwali moves the same way. The season is therefore three
weeks apart on the calendar from one year to the next, so every window the
dashboard already has — MTD, YTD, same date last year — compares the run-up to
something that is not a run-up. These windows are anchored to the FESTIVAL: the
last N days ending on the festival date, inclusive, each year on its own date.

Verified against the workbooks Manav sent (PUJA45/PUJA30, generated 2 Oct 2025):
applying that rule to the dates in his own ImpFestiveDates tab reproduces those
files' windows exactly — 19 Aug → 2 Oct 2025 for the 45, 3 Sep → 2 Oct for the 30.

★ LAST YEAR IS TRUNCATED TO THE SAME ELAPSED DAYS (Manav, 14 Aug). The workbooks
could not settle this because both were generated on the FINAL day of the
window, where every column collapses: projected equalled achieved on all 95
rows, and "LY full" equalled "LY" on all 77. Read mid-window with last year's
whole window as the denominator, day 15 of 45 would show ~33% and read as a
collapse. So `ly` runs to the same elapsed day, and `ly_full` — the whole of
last year's window — stays beside it as the season's target.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import pandas as pd

import projections as PROJ

URL_ENV = "FESTIVE_DATES_URL"
_SHEET = "ImpFestiveDates"
_PORTFOLIO_ENV = "PORTFOLIO_CSV_URL"

_LAST_PROBLEM = None


def last_problem():
    """Why the festive dates were not used, or None. Surfaced on screen — a
    report that silently reports nothing is worse than one that says why."""
    return _LAST_PROBLEM


def _secret(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        return st.secrets.get(name)
    except Exception:
        return None


def _url():
    """The tab, addressed BY NAME through the gviz endpoint.

    Every other feed here is addressed by gid, which is what a URL loses when
    it is edited by hand — the night fill lost its gid and silently served the
    workbook's first tab. A name cannot be mangled the same way, and this tab is
    new enough to have no gid written down anywhere.
    """
    explicit = _secret(URL_ENV)
    if explicit:
        return explicit
    base = _secret(_PORTFOLIO_ENV)
    if not base:
        return None
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", str(base))
    return (f"https://docs.google.com/spreadsheets/d/{m.group(1)}"
            f"/gviz/tq?tqx=out:csv&sheet={_SHEET}") if m else None


def _parse_cell(cell):
    """'Durga Puja / Dussehra (Vijayadashami): Tuesday, October 20, 2026'.

    Returns (name, date, why_not). The date is free text inside a label, so the
    parse is deliberate about what it cannot read rather than guessing: a range
    means its END ("29 Sept – 02 October" is the last day), a parenthetical is
    dropped, and a cell with no year is refused rather than assumed to be this
    one — `Mahalaya : Saturday, October 10` is exactly that cell.
    """
    if not isinstance(cell, str) or ":" not in cell:
        return None, None, "no ':' between the name and the date"
    name, _, rest = cell.partition(":")
    rest = rest.split("–")[-1].split("-")[-1].strip().rstrip(".")
    rest = re.sub(r"\(.*?\)", "", rest).strip()
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s*(\d{4})?", rest)
    if not m:
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s*(\d{4})?", rest)
        if not m:
            return name.strip(), None, f"no month and day in {rest!r}"
        day, mon, yr = m.group(1), m.group(2), m.group(3)
    else:
        mon, day, yr = m.group(1), m.group(2), m.group(3)
    if not yr:
        return name.strip(), None, "the cell carries no year"
    try:
        return name.strip(), pd.Timestamp(f"{int(day)} {mon[:3]} {yr}"), None
    except Exception:
        return name.strip(), None, f"could not read a date from {rest!r}"


def _tenures(row) -> list[int]:
    out = []
    for key in ("Tenure1", "Tenure2"):
        v = row.get(key)
        if isinstance(v, str):
            m = re.search(r"\d+", v)
            if m:
                out.append(int(m.group()))
    return sorted(set(out), reverse=True)


@dataclass
class Window:
    festival: str
    tenure: int
    ty_start: pd.Timestamp
    ty_end: pd.Timestamp
    ly_start: pd.Timestamp
    ly_end: pd.Timestamp          # last year's FULL window
    elapsed: int                  # days of this year's window already traded
    asof: pd.Timestamp

    @property
    def ly_cut(self) -> pd.Timestamp:
        """Last year, truncated to the same elapsed days — the like-for-like."""
        return self.ly_start + pd.Timedelta(days=max(self.elapsed, 1) - 1)

    @property
    def ty_cut(self) -> pd.Timestamp:
        return min(self.asof, self.ty_end)

    @property
    def started(self) -> bool:
        return self.elapsed > 0

    @property
    def label(self) -> str:
        return f"{self.festival} {self.tenure}"

    def basis(self) -> str:
        if not self.started:
            return (f"opens {self.ty_start:%d %b %Y} — {(self.ty_start - self.asof).days}"
                    f" days from now")
        return (f"day {self.elapsed} of {self.tenure} · "
                f"{self.ty_start:%d %b} → {self.ty_cut:%d %b %Y} against "
                f"{self.ly_start:%d %b} → {self.ly_cut:%d %b %Y}")


def festive_windows(asof=None, url=None) -> list[Window]:
    """Every festival in the tab that carries a tenure, both years and both
    lengths. Empty (with `last_problem` set) when the tab cannot be read."""
    global _LAST_PROBLEM
    asof = pd.Timestamp.today().normalize() if asof is None else pd.Timestamp(asof)
    u = url or _url()
    if not u:
        _LAST_PROBLEM = f"no URL for the {_SHEET} tab and $PORTFOLIO_CSV_URL is not set"
        return []
    try:
        d = pd.read_csv(u, dtype=str)
    except Exception as e:
        _LAST_PROBLEM = f"could not read the {_SHEET} tab ({type(e).__name__})"
        return []
    if d.shape[1] < 3:
        _LAST_PROBLEM = (f"the {_SHEET} tab has {d.shape[1]} column(s) — expected "
                         "this year, last year and the tenures")
        return []

    ty_col, ly_col = d.columns[0], d.columns[2]
    out, refused = [], []
    for _, row in d.iterrows():
        tens = _tenures(row)
        if not tens:
            continue                       # only dated festivals carry a window
        name, ty, why_ty = _parse_cell(row[ty_col])
        _, ly, why_ly = _parse_cell(row[ly_col])
        short = re.split(r"[/(]", name or "festival")[0].strip()
        if ty is None or ly is None:
            refused.append(f"{short}: {why_ty or why_ly}")
            continue
        for n in tens:
            ty_start = ty - pd.Timedelta(days=n - 1)
            elapsed = 0
            if asof >= ty_start:
                elapsed = int((min(asof, ty) - ty_start).days) + 1
            out.append(Window(festival=short, tenure=n, ty_start=ty_start, ty_end=ty,
                              ly_start=ly - pd.Timedelta(days=n - 1), ly_end=ly,
                              elapsed=elapsed, asof=asof))

    # ★★ A WINDOW FROM A FINISHED YEAR IS NOT A WINDOW (19 Aug 2026).
    # The tab holds one season's dates. Read on 19 Aug 2027 it returned the 2026
    # festivals — Durga Puja "day 45 of 45", complete, with `last_problem` None:
    # a whole tab of last year's run-ups presented as this year's, silently. The
    # dates carry their own year, so the tab can be asked whether it has been
    # rolled forward rather than trusted to have been.
    fy = asof.year if asof.month >= 4 else asof.year - 1
    fy_start, fy_end = pd.Timestamp(fy, 4, 1), pd.Timestamp(fy + 1, 3, 31)
    stale = [w for w in out if not (fy_start <= w.ty_end <= fy_end)]
    out = [w for w in out if fy_start <= w.ty_end <= fy_end]
    if stale:
        seasons = sorted({f"{w.ty_end:%Y}" for w in stale})
        refused.append(
            f"the {_SHEET} tab still holds {', '.join(seasons)} dates — it has "
            f"not been rolled forward to FY{fy}-{str(fy + 1)[-2:]}, so "
            f"{len(stale)} window(s) were left out")
    _LAST_PROBLEM = "; ".join(refused) if refused else None
    return sorted(out, key=lambda w: (w.ty_end, -w.tenure))


# --------------------------------------------------------------------------- #
# The figures
# --------------------------------------------------------------------------- #
def store_figures(pf: pd.DataFrame, w: Window) -> pd.DataFrame:
    """One row per store: this year so far, last year to the same day, last
    year's whole window, today's sale, and the projection to the full tenure."""
    import portfolio_loader as PL

    def total(a, b):
        m = (pf["date"] >= a) & (pf["date"] <= b)
        return pf[m].groupby("code")["sales"].sum()

    ty = total(w.ty_start, w.ty_cut) if w.started else pd.Series(dtype=float)
    ly = total(w.ly_start, w.ly_cut) if w.started else pd.Series(dtype=float)
    ly_full = total(w.ly_start, w.ly_end)
    day = pf[pf["date"] == w.asof].groupby("code")["sales"].sum()

    attrs = PL.gd_store_attrs_dyn(pf, w.asof).set_index("code")
    shut = PL.closed_map()
    rows = []
    for c in attrs.index:
        c = int(c)
        a = attrs.loc[c]
        doo = pd.to_datetime(a.get("doo"), errors="coerce")
        closed = pd.to_datetime(shut.get(c), errors="coerce")
        t = float(ty.get(c, 0.0))
        start = max(w.ty_start, doo) if pd.notna(doo) else w.ty_start
        proj = PROJ.project(t, start, w.ty_cut,
                            None if pd.isna(closed) else closed,
                            period_days=float(w.tenure)) if w.started else 0.0
        rows.append({
            "code": c,
            "new_old": a.get("new_old", ""),
            "store": a.get("store_name_main", ""),
            "location": a.get("location_main", ""),
            "parent": a.get("parent", ""),
            "location_tl": a.get("location_tl", ""),
            "closed": "" if pd.isna(closed) else f"{closed:%d-%m-%Y}",
            "doo": "" if pd.isna(doo) else f"{doo:%d-%m-%Y}",
            "ly": float(ly.get(c, 0.0)),
            "ty": t,
            "ly_full": float(ly_full.get(c, 0.0)),
            "day": float(day.get(c, 0.0)),
            "projected": float(proj),
        })
    f = pd.DataFrame(rows)
    # The workbook's GDYTD: this year as a PERCENTAGE OF last year, so 100 is
    # flat. Not a growth rate — a different convention from every other G/D
    # sheet here, and the sheets are labelled so nobody reads it as one.
    f["gd"] = [(t / l * 100) if l else None for t, l in zip(f["ty"], f["ly"])]
    return f




# --------------------------------------------------------------------------- #
# VFL figures — the same windows on the transactional feed
# --------------------------------------------------------------------------- #
def vfl_figures(df: pd.DataFrame, w: Window) -> pd.DataFrame:
    """One row per VFL store, with its brand line and city, on the same basis."""
    import loader as L

    amt, lab = L.COL_AMOUNT, L.COL_STORE_LABEL

    def total(a, b):
        m = (df["date"] >= a) & (df["date"] <= b)
        return df[m].groupby(lab)[amt].sum()

    ty = total(w.ty_start, w.ty_cut) if w.started else pd.Series(dtype=float)
    ly = total(w.ly_start, w.ly_cut) if w.started else pd.Series(dtype=float)
    ly_full = total(w.ly_start, w.ly_end)
    day = df[df["date"] == w.asof].groupby(lab)[amt].sum()

    master = L.load_store_master()
    tk = dict(zip(master["tableau_name"], master["takeover_date"]))
    shut_by_code = L.closed_map()
    code_of = {str(n): int(c) for n, c in zip(master["tableau_name"], master["code"])
               if pd.notna(c)}
    info = master.set_index("tableau_name")
    rows = []
    for s in sorted(set(master["tableau_name"]) & set(df[lab].dropna().unique())):
        a = info.loc[s]
        doo = pd.to_datetime(tk.get(s), errors="coerce")
        closed = pd.to_datetime(shut_by_code.get(code_of.get(s)), errors="coerce")
        t = float(ty.get(s, 0.0))
        start = max(w.ty_start, doo) if pd.notna(doo) else w.ty_start
        proj = PROJ.project(t, start, w.ty_cut, None if pd.isna(closed) else closed,
                            period_days=float(w.tenure)) if w.started else 0.0
        rows.append({
            "code": code_of.get(s, 0), "new_old": "", "store": str(a.get("format", "")),
            "location": a.get("location", s), "parent": str(a.get("format", "")),
            "location_tl": str(a.get("city", "")).title(),
            "closed": "" if pd.isna(closed) else f"{closed:%d-%m-%Y}",
            "doo": "" if pd.isna(doo) else f"{doo:%d-%m-%Y}",
            "ly": float(ly.get(s, 0.0)), "ty": t,
            "ly_full": float(ly_full.get(s, 0.0)),
            "day": float(day.get(s, 0.0)), "projected": float(proj),
        })
    f = pd.DataFrame(rows)
    f["gd"] = [(t / l * 100) if l else None for t, l in zip(f["ty"], f["ly"])]
    return f


# --------------------------------------------------------------------------- #
# The three sheets, laid out as the workbook lays them out
# --------------------------------------------------------------------------- #
# ★ COLUMN NAMES AND OUTLINE ARE THE WORKBOOK'S, VERBATIM (Manav, 14 Aug:
# "the formatting and the design should be the same as the excel"). So the
# headers keep their pivot wording — `Sum of YTD_LY` for a window that is not a
# year to date, `Sum of GDYTD` for a percentage of last year — a group label is
# printed once and blank on its repeats, `(blank)` marks an empty CLOSED cell,
# and a group closes with `<name> Total` above a final `Grand Total`.
# Presentation stays the pack's: its fonts, its grid, its header blue and its
# yellow total row, so a festive sheet and a G/D sheet are one document.
_MONEY_COLS = ("Sum of YTD_LY", "Sum of YTD_TY", "Sum of DAY SALE FIGURE",
               "Sum of LY FULL SALES", "Sum of PROJECTED YTD")

GD_COLS = ["NEW/OLD", "STORE NAME", "LOCATION", "CLOSED", "DOO",
           "Sum of YTD_LY", "Sum of YTD_TY", "Sum of GDYTD",
           "Sum of DAY SALE FIGURE", "Sum of LY FULL SALES", "Sum of PROJECTED YTD"]
BW_COLS = ["PARENT", "STORE NAME", "LOCATION", "NEW/OLD", "CLOSED",
           "Sum of YTD_LY", "Sum of YTD_TY", "Sum of GDYTD",
           "Sum of DAY SALE FIGURE", "Sum of LY FULL SALES", "Sum of PROJECTED YTD"]
LW_COLS = ["Location TL", "NEW/OLD", "STORE NAME", "LOCATION",
           "Sum of YTD_LY", "Sum of YTD_TY", "Sum of GDYTD",
           "Sum of PROJECTED YTD", "Sum of LY FULL SALES"]

_LEFT = ("NEW/OLD", "STORE NAME", "LOCATION", "PARENT", "Location TL",
         "CLOSED", "DOO")


def _gd_pct(ty, ly):
    """This year as a percentage of last year — the workbook's GDYTD.

    Its own files print `#DIV/0!` wherever a store has no last year; a new store
    is a fact, not an arithmetic accident, so this says so.
    """
    if not ly:
        return "new" if ty else ""
    return f"{ty / ly * 100:,.2f}"


def _totals(part):
    return {k: float(part[k].sum())
            for k in ("ly", "ty", "day", "ly_full", "projected")}


def _fill_figures(row, t):
    row["Sum of YTD_LY"], row["Sum of YTD_TY"] = t["ly"], t["ty"]
    row["Sum of GDYTD"] = _gd_pct(t["ty"], t["ly"])
    if "Sum of DAY SALE FIGURE" in row:
        row["Sum of DAY SALE FIGURE"] = t["day"]
    row["Sum of LY FULL SALES"] = t["ly_full"]
    row["Sum of PROJECTED YTD"] = t["projected"]
    return row


def _report(f, cols, group_col, second_col=None):
    """A pivot in the workbook's outline: group label once, then its stores,
    then `<group> Total`; a `Grand Total` closes the sheet."""
    rows, types = [], []
    f = f.copy()
    f[group_col] = f[group_col].fillna("").astype(str)
    groups = [g for g in sorted(f[group_col].unique()) if str(g).strip()]
    for g in groups:
        part = f[f[group_col] == g].sort_values(["store", "location"])
        first = True
        for _, r in part.iterrows():
            row = {c: "" for c in cols}
            row[cols[0]] = g if first else ""          # printed once, as the pivot does
            first = False
            row["STORE NAME"], row["LOCATION"] = r["store"], r["location"]
            if "NEW/OLD" in row and cols[0] != "NEW/OLD":
                row["NEW/OLD"] = r["new_old"]
            if "CLOSED" in row:
                row["CLOSED"] = r["closed"] or "(blank)"
            if "DOO" in row:
                row["DOO"] = r["doo"]
            rows.append(_fill_figures(row, {k: r[k] for k in
                                            ("ly", "ty", "day", "ly_full", "projected")}))
            types.append("store")
        tr = {c: "" for c in cols}
        tr[cols[0]] = f"{g} Total"
        rows.append(_fill_figures(tr, _totals(part)))
        types.append("subtotal")
    gr = {c: "" for c in cols}
    gr[cols[0]] = "Grand Total"
    rows.append(_fill_figures(gr, _totals(f)))
    types.append("grand")
    return pd.DataFrame(rows, columns=cols), types


def gd_report(f):
    """The GD sheet groups by NEW/OLD, which is a portfolio attribute. The VFL
    master carries no such flag, so that feed groups by brand line instead —
    and the column is HEADED brand line, rather than saying NEW/OLD over a
    column of brand names."""
    if f["new_old"].astype(str).str.strip().any():
        return _report(f, GD_COLS, "new_old")
    cols = ["BRAND"] + GD_COLS[1:]
    return _report(f, cols, "parent")


def brand_report(f):
    return _report(f, BW_COLS, "parent")


def location_report(f):
    return _report(f, LW_COLS, "location_tl")


def day_ladder(sales: pd.Series, w: Window) -> pd.DataFrame:
    """Both windows day by day with their running totals, as the workbook
    prints them beside the store table: last year's dates and this year's,
    each with weekday, the day's amount and the total so far."""
    def ladder(a, b):
        days = pd.date_range(a, b, freq="D")
        amt = [float(sales.get(d, 0.0)) for d in days]
        run, acc = [], 0.0
        for v in amt:
            acc += v
            run.append(acc)
        return days, amt, run

    ld, la, lr = ladder(w.ly_start, w.ly_end)
    td, ta, tr = ladder(w.ty_start, w.ty_cut) if w.started else ([], [], [])
    rows = []
    for i in range(w.tenure):
        rows.append({
            f"Date-{w.ly_start:%Y}": f"{ld[i]:%d-%m-%Y}" if i < len(ld) else "",
            "Day": f"{ld[i]:%A}" if i < len(ld) else "",
            # Missing days are ABSENT, not zero: this year's side is empty
            # beyond the day reached, and a zero there would read as a day with
            # no trade rather than a day that has not happened.
            "Amount": la[i] if i < len(la) else None,
            "Running Total": lr[i] if i < len(lr) else None,
            f"Date {w.ty_start:%Y}": f"{td[i]:%d-%m-%Y}" if i < len(td) else "",
            "Day ": f"{td[i]:%A}" if i < len(td) else "",
            "Amount ": ta[i] if i < len(ta) else None,
            "Running Total ": tr[i] if i < len(tr) else None,
        })
    return pd.DataFrame(rows)


def sheet_title(w: Window, what: str) -> str:
    """`PUJA 45 GROWTH DEGROWTH SHEET 25-26 VS 26-27` — the workbook's own
    wording, with the two fiscal years read off the windows themselves."""
    fy = lambda d: (f"{str(d.year)[2:]}-{str(d.year + 1)[2:]}" if d.month >= 4
                    else f"{str(d.year - 1)[2:]}-{str(d.year)[2:]}")
    name = "PUJA" if "puja" in w.festival.lower() else w.festival.upper()
    return (f"{name} {w.tenure} {what} SHEET "
            f"{fy(w.ly_end)} VS {fy(w.ty_end)}")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _sheet_image(df, types, w, title):
    """The sheet, with the workbook's DATE stamp above it."""
    import report_td as RT

    header = list(df.columns)
    aligns = ["l" if c in _LEFT else "r" for c in header]
    grid = []
    for (_, row), t in zip(df.iterrows(), types):
        fill = RT.TOTAL_BG if t == "grand" else (RT.HDR_BG if t == "subtotal" else None)
        cells = [RT.cell(RT._money(row[c]) if (c in _MONEY_COLS and row[c] != "")
                         else (row[c] or ""),
                         align=aligns[i], fill=fill, bold=t in ("grand", "subtotal"))
                 for i, c in enumerate(header)]
        grid.append((cells, RT.ROW_H))
    stamp = f"DATE   {w.asof:%d-%m-%Y}        {title}"
    return RT._draw_grid(header, grid, title=stamp)


def _ladder_image(ladder, w):
    """The day ladder — both years' takings day by day, with running totals.

    ★ ITS OWN PAGE (Manav, 16 Aug). It used to sit beside the Growth/Degrowth
    sheet, the two sharing page one the way the workbook lays them out. Read on a
    screen rather than on a spread, the pair made each half half as legible.
    """
    import report_td as RT
    lh = list(ladder.columns)
    lg = []
    for _, row in ladder.iterrows():
        lg.append(([RT.cell(RT._money(v) if isinstance(v, float) else (v or ""),
                            align="r" if isinstance(v, float) else "l")
                    for v in row], RT.ROW_H))
    return RT._draw_grid(lh, lg, title=f"{w.tenure} DAYS TO {w.festival.upper()}")


def festive_sheets(f: pd.DataFrame, sales: pd.Series, w: Window) -> list[tuple]:
    """(section title, image) for each sheet of one window's report.

    Four sheets: the day ladder leads, then the three growth sheets.
    """
    gd, gt = gd_report(f)
    bw, bt = brand_report(f)
    lw, lt = location_report(f)
    return [
        (f"{w.label} — {w.tenure} days to {w.festival}",
         _ladder_image(day_ladder(sales, w), w)),
        (f"{w.label} — Growth / Degrowth",
         _sheet_image(gd, gt, w, sheet_title(w, "GROWTH DEGROWTH"))),
        (f"{w.label} — Brand wise",
         _sheet_image(bw, bt, w, sheet_title(w, "BRAND WISE GROWTH DEGROWTH"))),
        (f"{w.label} — Location wise",
         _sheet_image(lw, lt, w, sheet_title(w, "LOCATION WISE GROWTH DEGROWTH"))),
    ]


def build_festive_pdf(df: pd.DataFrame, w: Window, basis_label="",
                      vfl: bool = False) -> tuple[str, bytes]:
    """One window's report as a PDF, from either feed."""
    import loader as L
    import report_td as RT
    if vfl:
        f = vfl_figures(df, w)
        sales = df.groupby("date")[L.COL_AMOUNT].sum()
    else:
        f = store_figures(df, w)
        sales = df.groupby("date")["sales"].sum()
    with RT._LOCK:
        pdf = RT._pdf_from(festive_sheets(f, sales, w),
                           f"As of {w.asof:%d %b %Y} · {w.basis()}"
                           + (f" · {basis_label}" if basis_label else ""))
    tag = "VFL " if vfl else ""
    return (f"{tag}{w.festival.upper()} {w.tenure} {w.ty_end:%d-%m-%Y}.pdf", pdf)
