"""
Breadth (whole-portfolio) data loader + sales-only KPI helpers.

This is the *breadth* layer that sits alongside `loader.py` (the *depth* layer).

  - loader.py     -> VFL only (Manyavar / Mohey), rich schema: division, brand,
                     salesperson, bills, units, productivity, PSFPD …
  - portfolio_loader.py -> ALL stores (63), sales-only: one `Total` per store/day.

The two reconcile: slicing this breadth frame to VFL brands reproduces the VFL
top line exactly (25.54 Cr for Apr-Jul 2026), so a Portfolio/VFL mode toggle on
top of the two sources stays internally consistent.

Source: a second tab of the *same* Google Sheet workbook as the VFL feed, read
via its own CSV /export URL in the `PORTFOLIO_CSV_URL` secret. Falls back to a
committed snapshot so the app runs before the secret is set.

Raw schema (must match the sheet headers exactly):
    DATE, STORE CODE, STORE NAME, LOCATION, CITY, Total
DATE is Indian day-first (e.g. 1/4/2025 = 1 April 2025).
"""

from __future__ import annotations

import io
import os

import pandas as pd

from projections import project_mtd, project_ytd

_DIR = os.path.dirname(__file__)
_MASTER_PATH = os.path.join(_DIR, "portfolio_store_master.csv")
_ATTRS_PATH = os.path.join(_DIR, "gd_store_attrs.csv")
# Committed fallback so the app works before PORTFOLIO_CSV_URL is configured.
_SNAPSHOT_CANDIDATES = ["portfolio_snapshot.csv", "25v26 data set all str.xlsx"]

# Raw column names as they appear in the sheet.
C_DATE, C_CODE, C_NAME, C_LOC, C_CITY, C_TOTAL = (
    "DATE", "STORE CODE", "STORE NAME", "LOCATION", "CITY", "Total")

# Brand-label unification (two Van Heusen stores spell it two ways).
_BRAND_FIX = {"VANHEUSEN": "VAN HEUSEN"}
_VFL_BRANDS = {"MANYAVAR", "MANYAVAR & MOHEY"}

# Region display order, shared with the VFL report for a consistent look.
REGION_ORDER = ["East & NE", "South"]

# Columns of the region x store report (portfolio flavour: multi-brand, so it
# carries BRAND and CITY that the VFL report doesn't need).
REPORT_COLS = [
    "Region", "STORE CODE", "CITY", "LOCATION", "BRAND",
    "Day Sales", "MTD LY", "MTD TY", "GD MTD Value", "GD MTD %",
    "YTD LY", "YTD TY", "GD YTD Value", "GD YTD %",
]


# --------------------------------------------------------------------------- #
# Source resolution + raw read
# --------------------------------------------------------------------------- #
def _sheet_url() -> str | None:
    """Portfolio CSV /export URL from env var (local testing) or Streamlit
    secrets (production). None -> fall back to the committed snapshot."""
    if os.environ.get("PORTFOLIO_CSV_URL"):
        return os.environ["PORTFOLIO_CSV_URL"]
    try:
        import streamlit as st
        return st.secrets.get("PORTFOLIO_CSV_URL")
    except Exception:
        return None


def _snapshot_path() -> str | None:
    for name in _SNAPSHOT_CANDIDATES:
        p = os.path.join(_DIR, name)
        if os.path.exists(p):
            return p
    return None


def _read_raw() -> pd.DataFrame:
    """Read the raw portfolio sheet: live CSV export if configured, else the
    committed snapshot (CSV or the original xlsx)."""
    url = _sheet_url()
    if url:
        # See `feed.read_csv`: same fast path, but the first failure's reason
        # survives and a sign-in page is refused instead of being parsed.
        import feed
        return feed.read_csv(url, expect=(C_DATE, C_CODE, C_TOTAL),
                             what="the portfolio sheet")
    snap = _snapshot_path()
    if snap:
        if snap.endswith(".xlsx"):
            return pd.read_excel(snap, sheet_name=0, dtype=str)
        return pd.read_csv(snap, dtype=str, keep_default_na=False)
    raise FileNotFoundError(
        "No portfolio source. Set PORTFOLIO_CSV_URL in Streamlit secrets, or "
        f"place a snapshot at {os.path.join(_DIR, _SNAPSHOT_CANDIDATES[0])}")


# --------------------------------------------------------------------------- #
# Master + cleaning
# --------------------------------------------------------------------------- #
def store_master() -> pd.DataFrame:
    m = pd.read_csv(_MASTER_PATH)
    m["code"] = pd.to_numeric(m["code"], errors="coerce").astype("Int64")
    m["takeover_date"] = pd.to_datetime(m["takeover_date"], errors="coerce")
    m["is_vfl"] = m["is_vfl"].astype(bool)
    return m


def _to_number(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False)
         .str.replace("₹", "", regex=False).str.strip(),
        errors="coerce")


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    """Typed, master-joined, takeover-anchored daily fact frame keyed on code."""
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    # Drop any footer/blank rows.
    df = df[df[C_CODE].astype(str).str.strip().str.lower().isin(
        {"", "total", "grand total", "nan"}) == False]  # noqa: E712

    df["code"] = pd.to_numeric(df[C_CODE], errors="coerce").astype("Int64")
    df["sales"] = _to_number(df[C_TOTAL]).fillna(0.0)
    # Day-first Indian dates — but proved from the column rather than assumed,
    # and by the same code the VFL feed uses, because the two conventions
    # disagreeing is exactly how 12 August once became 8 December. See `dates.py`.
    import dates as _dates
    df["date"] = _dates.parse(df[C_DATE], expect=_dates.DAY_FIRST,
                              label="portfolio")
    df = df[df["date"].notna() & df["code"].notna()].copy()

    # Join canonical identity from the master (dedupes location/brand casing).
    m = store_master().set_index("code")
    for col in ["brand", "location", "city", "region", "takeover_date", "is_vfl"]:
        df[col] = df["code"].map(m[col])
    # Any store not in the master keeps its raw label and is treated as East & NE.
    df["brand"] = df["brand"].fillna(
        df[C_NAME].astype(str).str.upper().str.strip().replace(_BRAND_FIX))
    df["location"] = df["location"].fillna(df[C_LOC].astype(str).str.title())
    df["city"] = df["city"].fillna(df[C_CITY].astype(str).str.upper())
    df["region"] = df["region"].fillna("East & NE")
    df["is_vfl"] = df["is_vfl"].fillna(df["brand"].isin(_VFL_BRANDS)).astype(bool)

    # Takeover anchor: drop pre-ownership sales (harmless where data starts later).
    keep = df["takeover_date"].isna() | (df["date"] >= df["takeover_date"])
    df = df[keep].copy()

    # Calendar helpers (fiscal Apr-Mar).
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["month_label"] = df["date"].dt.strftime("%b %Y")
    fy_start = df["date"].dt.year.where(df["date"].dt.month >= 4,
                                        df["date"].dt.year - 1)
    df["fy"] = "FY" + ((fy_start + 1) % 100).astype(int).astype(str).str.zfill(2)
    return df.reset_index(drop=True)


def load_portfolio() -> pd.DataFrame:
    """Public entry point — clean daily fact frame for all stores.

    Per the authoritative Growth-Degrowth sheet, stores that opened THIS fiscal
    year (South / 2526NA) have no last-year comparison — they show as NEW, not as
    degrowth. We do NOT invent last-year sales for them: with no 2025 rows in the
    portfolio sheet, their YTD_LY is simply 0 and their YoY reads as 'new'.

    If a night fill is configured and holds a day NEWER than anything in the
    sheet, its rows are appended here — before `clean()`, so they are typed,
    takeover-filtered and given fiscal columns by exactly the same code as every
    other row. A day the sheet already covers is ignored, so the paste and
    Tableau always win. Without `NIGHT_FILL_URL` set, nothing changes at all.
    `df.attrs["provisional_date"]` names the appended day, for reports that want
    to say so."""
    raw = _read_raw()
    provisional = None
    try:
        import night_fill
        extra = night_fill.raw_rows_if_newer(raw)
        if extra is not None and len(extra):
            provisional = pd.to_datetime(extra[C_DATE].iloc[0], dayfirst=True)
            raw = pd.concat([raw, extra], ignore_index=True)
    except Exception:
        provisional = None          # never let the overlay break the load
    df = clean(raw)
    df.attrs["provisional_date"] = provisional
    return df


# --------------------------------------------------------------------------- #
# Windows (fiscal, per-store takeover-anchored) + YoY
# --------------------------------------------------------------------------- #
def as_of(df: pd.DataFrame) -> pd.Timestamp:
    return df["date"].max()


def standard_windows(df: pd.DataFrame, asof=None) -> dict[str, tuple]:
    """MTD / QTD / YTD (fiscal) as (start, end)."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    mtd = (asof.replace(day=1), asof)
    q_start = {4: 4, 5: 4, 6: 4, 7: 7, 8: 7, 9: 7,
               10: 10, 11: 10, 12: 10, 1: 1, 2: 1, 3: 1}[asof.month]
    qtd = (pd.Timestamp(asof.year, q_start, 1), asof)
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    ytd = (pd.Timestamp(fy_year, 4, 1), asof)
    return {"MTD": mtd, "QTD": qtd, "YTD": ytd}


def _anchored_start(df: pd.DataFrame, kind: str, asof: pd.Timestamp) -> pd.Series:
    """Per-row current-window start, anchored to each store's takeover date so TY
    and LY line up. Stores without a takeover date use the plain fiscal start."""
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    tk = df["takeover_date"]
    m = tk.dt.month.where(tk.notna(), 4).astype(int)
    d = tk.dt.day.where(tk.notna(), 1).astype(int)
    if kind == "YTD":
        return pd.to_datetime(pd.DataFrame({"year": fy_year, "month": m, "day": d}))
    if kind == "MTD":
        base = pd.to_datetime(pd.DataFrame(
            {"year": asof.year, "month": asof.month, "day": 1}, index=df.index))
        anchored = pd.to_datetime(pd.DataFrame(
            {"year": asof.year, "month": m, "day": d}))
        anchored.index = df.index
        in_month = (m.values == asof.month) & (anchored > base)
        return base.mask(in_month, anchored)
    raise ValueError(kind)


def _fy_start(asof: pd.Timestamp) -> pd.Timestamp:
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    return pd.Timestamp(fy_year, 4, 1)


def _ty_end(df: pd.DataFrame, asof: pd.Timestamp) -> pd.Series:
    """Each store's last SELLING date this fiscal year (fy-start → as-of). Uses
    positive sales only — the sheet keeps zero-rows for closed stores right up to
    today, so a plain max(date) would miss that a store stopped trading. Stores
    absent from the index sold nothing this year → closed, and (per the
    Growth-Degrowth sheet) drop out of the report entirely."""
    cur = df[(df["date"] >= _fy_start(asof)) & (df["date"] <= asof)
             & (df["sales"] > 0)]
    return cur.groupby("code")["date"].max()


def closed_map() -> dict:
    """store code -> closure date, from the store master.

    The source sheet keeps zero-rows for a shut store indefinitely, so closure
    cannot be read off the sales data without also catching stores that merely
    paused trading. Only an explicit date counts — and the master's own CLOSURE
    DATE is that date (13 Aug; see `loader.closed_map`). The committed
    attributes file remains the fallback.
    """
    try:
        import master_lookup
        live = master_lookup.closed()
        if live:
            return dict(live)
    except Exception:
        pass
    try:
        a = pd.read_csv(_ATTRS_PATH)
    except Exception:
        return {}
    if not {"code", "closed"} <= set(a.columns):
        return {}
    code = pd.to_numeric(a["code"], errors="coerce")
    cl = pd.to_datetime(a["closed"], errors="coerce")
    ok = code.notna() & cl.notna()
    return dict(zip(code[ok].astype(int), cl[ok]))


def active_codes(df: pd.DataFrame, asof=None) -> set:
    """Store codes that traded this fiscal year (the ones the source sheet keeps)."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    return set(_ty_end(df, asof).index)


def _window_frames(df: pd.DataFrame, kind: str, asof: pd.Timestamp):
    """(current, prior-year) frames for MTD/YTD, matching the Growth-Degrowth
    sheet: only stores active this FY are kept, and a closed store's last-year is
    capped to the span it actually traded this year (so a store that shut on 30
    Apr compares Apr-vs-Apr, not Apr vs the full Apr-Jul). Open stores use the
    full last-year window (their last sale is ~as-of), so they're unaffected."""
    ty_end = _ty_end(df, asof)
    df = df[df["code"].isin(ty_end.index)]                      # active stores only

    # ★ NO STORE IN THIS SELECTION TRADED THIS YEAR. It is not the same as "no
    # rows": a store that shut last October still has a full year of history, so
    # the frame arrives populated and the caller's `df.empty` guard passes. The
    # per-store closure map below is then keyed on an empty index, and mapping a
    # column of codes through an empty datetime Series raises `TypeError: Cannot
    # cast DatetimeArray to dtype float64`.
    #
    # It reaches a user through the ordinary filters — the city ASANSOL, the
    # brand LONGHORNS, the stores Forum Mall / Galaxy Mall / Nh31A were each one
    # click away from a traceback, and every future closure adds another. Return
    # the empty pair and let the reports say they have nothing to show.
    if df.empty:
        return df, df.copy()

    start = _anchored_start(df, kind, asof)
    start.index = df.index
    prior_start = start - pd.DateOffset(years=1)
    cur = df[(df["date"] >= start) & (df["date"] <= asof)]

    # Per-store last-year end. A store that has SHUT gets its last year capped to
    # the END of the month it closed (shifted back a year) — a store that shut on
    # 30 Apr compares against the full last April, matching the sheet.
    #
    # Closure is taken from the curated `closed` attribute, NOT inferred from
    # "made no sale this month". That inference was wrong: a store merely paused
    # for operational reasons looked closed, its prior-year window was capped
    # away, and the month came back 0-vs-0 — hiding a full -100% as no movement
    # (code 69 Turtle City Centre GHT, Aug 2026).
    cl = closed_map()
    closed_by_code = pd.Series({c: cl[c] for c in ty_end.index if c in cl},
                               dtype="datetime64[ns]")
    # ★ AND NEVER PAST WHERE THIS YEAR HAS GOT TO. The month-end cap is there so
    # a store that shut on 30 April compares against the whole of last April —
    # but for a store shutting LATER THIS MONTH it ran last year to the end of
    # the month while this year had only reached the 16th, handing it fifteen
    # days it had not had. Vega Circle Mall, dated to close on 31 August, read
    # -51.8% instead of -49.5% the moment the date was entered, and threw a
    # spurious "no L2L" line showing -100% for the fortnight last year that this
    # year has not lived yet.
    ly_cap = asof - pd.DateOffset(years=1)
    closed_end = ((closed_by_code + pd.offsets.MonthEnd(0))
                  - pd.DateOffset(years=1))
    if len(closed_end):
        closed_end = closed_end.clip(upper=ly_cap)
    ly_end_by_code = closed_end.reindex(ty_end.index).fillna(ly_cap)
    ly_end = df["code"].map(ly_end_by_code)
    ly_end.index = df.index
    prior = df[(df["date"] >= prior_start) & (df["date"] <= ly_end)]
    return cur, prior


def _growth(ty: float, ly: float):
    return ((ty - ly) / ly * 100) if ly else None


def exec_yoy(df: pd.DataFrame, asof=None) -> dict:
    """MTD & YTD sales YoY for the exec cards — same active-store, capped-last-year
    basis as the Growth-Degrowth sheet, so the cards tie to the report totals."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    out = {}
    for kind in ("MTD", "YTD"):
        cur, prior = _window_frames(df, kind, asof)
        ty, ly = cur["sales"].sum(), prior["sales"].sum()
        out[kind] = {"ty": ty, "ly": ly, "growth": _growth(ty, ly)}
    return out


def region_yoy(df: pd.DataFrame, kind: str = "YTD", asof=None) -> pd.DataFrame:
    """Per-region TY/LY/growth for `kind`, takeover-anchored."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    cur, prior = _window_frames(df, kind, asof)
    ty = cur.groupby("region")["sales"].sum()
    ly = prior.groupby("region")["sales"].sum()
    out = pd.concat([ty.rename("ty"), ly.rename("ly")], axis=1).fillna(0.0)
    out = out.reindex([r for r in REGION_ORDER if r in out.index]
                      + [r for r in out.index if r not in REGION_ORDER])
    out["growth"] = out.apply(lambda r: _growth(r["ty"], r["ly"]), axis=1)
    return out.reset_index()


# --------------------------------------------------------------------------- #
# Region x store report (the executive MTD/YTD table)
# --------------------------------------------------------------------------- #
def region_store_report(df: pd.DataFrame, asof=None):
    """Region-grouped, store-wise MTD/YTD YoY table with subtotals + grand total.
    Returns (display_df, row_types) where row_types is 'store'|'subtotal'|'grand'.
    Respects whatever `df` is filtered to (region/brand/city/store)."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    mtd_cur, mtd_pri = _window_frames(df, "MTD", asof)
    ytd_cur, ytd_pri = _window_frames(df, "YTD", asof)
    g = lambda f: f.groupby("code")["sales"].sum()
    mtd_ty, mtd_ly = g(mtd_cur), g(mtd_pri)
    ytd_ty, ytd_ly = g(ytd_cur), g(ytd_pri)
    day_ty = g(df[df["date"] == asof])

    # Identity per store code — only stores active this FY (closed stores drop
    # out, matching the source Growth-Degrowth sheet).
    active = active_codes(df, asof)
    present = (df[df["code"].isin(active)][["code", "region", "city", "location", "brand"]]
               .drop_duplicates("code"))
    if present.empty:
        return pd.DataFrame(columns=REPORT_COLS), []
    present["_rord"] = present["region"].map(
        {k: i for i, k in enumerate(REGION_ORDER)}).fillna(99)
    present = present.sort_values(["_rord", "code"])

    rows, types = [], []

    def _store_row(r):
        c = r["code"]
        mly, mty = float(mtd_ly.get(c, 0.0)), float(mtd_ty.get(c, 0.0))
        yly, yty = float(ytd_ly.get(c, 0.0)), float(ytd_ty.get(c, 0.0))
        return {
            "Region": r["region"], "STORE CODE": int(c), "CITY": r["city"],
            "LOCATION": r["location"], "BRAND": r["brand"],
            "Day Sales": float(day_ty.get(c, 0.0)),
            "MTD LY": mly, "MTD TY": mty,
            "GD MTD Value": mty - mly, "GD MTD %": _growth(mty, mly),
            "YTD LY": yly, "YTD TY": yty,
            "GD YTD Value": yty - yly, "GD YTD %": _growth(yty, yly),
        }

    def _total_row(label, sub):
        mly, mty = sub["MTD LY"].sum(), sub["MTD TY"].sum()
        yly, yty = sub["YTD LY"].sum(), sub["YTD TY"].sum()
        return {
            "Region": label, "STORE CODE": "", "CITY": "", "LOCATION": "",
            "BRAND": "", "Day Sales": sub["Day Sales"].sum(),
            "MTD LY": mly, "MTD TY": mty,
            "GD MTD Value": mty - mly, "GD MTD %": _growth(mty, mly),
            "YTD LY": yly, "YTD TY": yty,
            "GD YTD Value": yty - yly, "GD YTD %": _growth(yty, yly),
        }

    # ★ THE LIKE-TO-LIKE SPLIT, mirroring the GD sheet above and both VFL
    # reports (Manav, 19 Aug: "yes, do the mirror for portfolio"). A store only
    # comparable over part of the window shows that part on its own line, with
    # the rest above it, and its own row still closes the pair. Only the MTD and
    # YTD pairs split; the day's sale is a different window.
    #
    # Last year needs no capping here — `_window_frames` has always cut it at a
    # closure, which is why a shut store reads one honest line on this feed and
    # why the VFL side had to be given the same cap before it could match.
    l2l_start, l2l_end = _l2l_spans(df, asof)
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    win_start = pd.Timestamp(fy_year, 4, 1)
    _yr = pd.DateOffset(years=1)

    def _part(frame, c, lo, hi):
        m = ((frame["code"] == c) & (frame["date"] >= lo) & (frame["date"] <= hi))
        return float(frame[m]["sales"].sum())

    def _halves(c, whole):
        s, e = l2l_start.get(c), l2l_end.get(c)
        if s is None or e is None or s > e:
            return []                      # no comparable span at all
        if s <= win_start and e >= asof:
            return []                      # the span covers the window
        inside = {"YTD TY": _part(ytd_cur, c, s, e),
                  "YTD LY": _part(ytd_pri, c, s - _yr, e - _yr),
                  "MTD TY": _part(mtd_cur, c, s, e),
                  "MTD LY": _part(mtd_pri, c, s - _yr, e - _yr)}
        outside = {k: whole[k] - inside[k] for k in inside}
        if all(abs(v) < 1 for v in outside.values()):
            return []
        return [("no L2L", outside), (f"L2L from {s:%d-%m-%Y}", inside)]

    def _half_row(r, note, v):
        return {
            "Region": "", "STORE CODE": "", "CITY": "", "BRAND": "",
            "LOCATION": f'{r["location"]} — {note}',
            "Day Sales": float("nan"),
            "MTD LY": v["MTD LY"], "MTD TY": v["MTD TY"],
            "GD MTD Value": v["MTD TY"] - v["MTD LY"],
            "GD MTD %": _growth(v["MTD TY"], v["MTD LY"]),
            "YTD LY": v["YTD LY"], "YTD TY": v["YTD TY"],
            "GD YTD Value": v["YTD TY"] - v["YTD LY"],
            "GD YTD %": _growth(v["YTD TY"], v["YTD LY"]),
        }

    l2l_rows, non_l2l_rows = [], []
    all_rows = []
    for region, grp in present.groupby("region", sort=False):
        region_rows = []
        for _, r in grp.iterrows():
            sr = _store_row(r)
            parts = _halves(r["code"], sr)
            for note, vals in parts:
                rows.append(_half_row(r, note, vals))
                types.append("split")
                (non_l2l_rows if note == "no L2L" else l2l_rows).append(vals)
            if not parts:
                s, e = l2l_start.get(r["code"]), l2l_end.get(r["code"])
                (l2l_rows if (s is not None and e is not None and s <= e)
                 else non_l2l_rows).append(sr)
            region_rows.append(sr)
            rows.append(sr)
            types.append("store")
        region_df = pd.DataFrame(region_rows)
        all_rows.append(region_df)
        rows.append(_total_row(f"{region} Total", region_df))
        types.append("subtotal")

    grand = pd.concat(all_rows, ignore_index=True)
    rows.append(_total_row("Grand Total", grand))
    types.append("grand")

    # The report's own like-to-like line — the figure the Executive Snapshot
    # prints, shown here rather than left for the reader to reconstruct.
    for label, part in (("LIKE TO LIKE", l2l_rows), ("NO L2L", non_l2l_rows)):
        if not part:
            continue
        t = {k: sum(float(p.get(k, 0.0) or 0.0) for p in part)
             for k in ("MTD LY", "MTD TY", "YTD LY", "YTD TY")}
        rows.append({
            "Region": label, "STORE CODE": "", "CITY": "", "LOCATION": "",
            "BRAND": "", "Day Sales": float("nan"),
            "MTD LY": t["MTD LY"], "MTD TY": t["MTD TY"],
            "GD MTD Value": t["MTD TY"] - t["MTD LY"],
            "GD MTD %": _growth(t["MTD TY"], t["MTD LY"]),
            "YTD LY": t["YTD LY"], "YTD TY": t["YTD TY"],
            "GD YTD Value": t["YTD TY"] - t["YTD LY"],
            "GD YTD %": _growth(t["YTD TY"], t["YTD LY"]),
        })
        types.append("summary")
    return pd.DataFrame(rows, columns=REPORT_COLS), types


# --------------------------------------------------------------------------- #
# Degrowth / contribution / city G-D / monthly / store list
# --------------------------------------------------------------------------- #
def store_yoy(df: pd.DataFrame, kind: str = "YTD", asof=None) -> pd.DataFrame:
    """Per-store TY/LY/growth for `kind`, with identity columns."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    cur, prior = _window_frames(df, kind, asof)
    ty = cur.groupby("code")["sales"].sum().rename("cur")
    ly = prior.groupby("code")["sales"].sum().rename("prior")
    active = active_codes(df, asof)
    ident = (df[df["code"].isin(active)][["code", "region", "city", "location", "brand"]]
             .drop_duplicates("code"))
    m = ident.merge(pd.concat([ty, ly], axis=1).fillna(0.0),
                    on="code", how="left").fillna({"cur": 0.0, "prior": 0.0})
    m["growth"] = m.apply(lambda r: _growth(r["cur"], r["prior"]), axis=1)
    m["shortfall"] = m["cur"] - m["prior"]
    return m


def degrowth_report(df: pd.DataFrame, asof=None, kind: str = "YTD") -> pd.DataFrame:
    """Stores in `kind` degrowth (TY < LY), worst first."""
    sy = store_yoy(df, kind, asof=asof)
    out = sy[sy["growth"].notna() & (sy["growth"] < 0)].copy()
    return out.sort_values("shortfall")[
        ["region", "code", "city", "location", "brand",
         "prior", "cur", "shortfall", "growth"]].reset_index(drop=True)


def contribution(df: pd.DataFrame, dim: str, window=None) -> pd.DataFrame:
    """Sales contribution by `dim` (brand/city/region/location) over an optional
    (start, end) window; share of total, largest first."""
    sub = df if window is None else df[
        (df["date"] >= window[0]) & (df["date"] <= window[1])]
    key = {"brand": "brand", "city": "city", "region": "region",
           "store": "location"}[dim]
    g = sub.groupby(key)["sales"].sum().sort_values(ascending=False)
    out = g.rename("sales").reset_index()
    total = out["sales"].sum()
    out["share"] = out["sales"] / total * 100 if total else 0.0
    return out


def city_gd(df: pd.DataFrame, kind: str = "YTD", asof=None) -> pd.DataFrame:
    """City-wise growth/degrowth for `kind`, takeover-anchored."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    cur, prior = _window_frames(df, kind, asof)
    ty = cur.groupby(["region", "city"])["sales"].sum().rename("cur")
    ly = prior.groupby(["region", "city"])["sales"].sum().rename("prior")
    out = pd.concat([ty, ly], axis=1).fillna(0.0).reset_index()
    out["gd"] = out["cur"] - out["prior"]
    out["growth"] = out.apply(lambda r: _growth(r["cur"], r["prior"]), axis=1)
    out["_rord"] = out["region"].map(
        {k: i for i, k in enumerate(REGION_ORDER)}).fillna(99)
    return out.sort_values(["_rord", "cur"], ascending=[True, False]).drop(
        columns="_rord").reset_index(drop=True)


def monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Sales by fiscal month with a same-month-last-year column."""
    g = df.groupby("month")["sales"].sum().reset_index().sort_values("month")
    g["ly_month"] = g["month"] - pd.DateOffset(years=1)
    ly = g.set_index("month")["sales"]
    g["ly_sales"] = g["ly_month"].map(ly)
    g["growth"] = g.apply(lambda r: _growth(r["sales"], r["ly_sales"]), axis=1)
    g["label"] = g["month"].dt.strftime("%b %Y")
    return g


def store_list(df: pd.DataFrame) -> pd.DataFrame:
    """One row per store with total sales, active-date span and VFL flag."""
    g = df.groupby("code").agg(
        region=("region", "first"), city=("city", "first"),
        location=("location", "first"), brand=("brand", "first"),
        is_vfl=("is_vfl", "first"), first_sale=("date", "min"),
        last_sale=("date", "max"), sales=("sales", "sum"),
    ).reset_index()
    g["_rord"] = g["region"].map(
        {k: i for i, k in enumerate(REGION_ORDER)}).fillna(99)
    return g.sort_values(["_rord", "sales"], ascending=[True, False]).drop(
        columns="_rord").reset_index(drop=True)


DAY_REPORT_COLS = ["Region", "STORE CODE", "CITY", "LOCATION", "BRAND",
                   "Same Day LY", "Same Date LY"]


def day_sales_ly_report(df: pd.DataFrame, day):
    """Per-store day-sales on the two last-year reference days of `day`:
      - Same Day LY  = same weekday a year ago  (day − 364 days = 52 weeks)
      - Same Date LY = same calendar date a year ago (day − 1 year)
    They differ because a year isn't a whole number of weeks. Region-grouped
    with subtotals + grand total; only stores active this fiscal year."""
    day = pd.Timestamp(day)
    same_day = day - pd.Timedelta(days=364)
    same_date = day - pd.DateOffset(years=1)
    g = lambda d: df[df["date"] == d].groupby("code")["sales"].sum()
    sd, dt = g(same_day), g(same_date)

    active = active_codes(df, day)
    present = (df[df["code"].isin(active)][["code", "region", "city", "location", "brand"]]
               .drop_duplicates("code"))
    if present.empty:
        return pd.DataFrame(columns=DAY_REPORT_COLS), []
    present["_rord"] = present["region"].map(
        {k: i for i, k in enumerate(REGION_ORDER)}).fillna(99)
    present = present.sort_values(["_rord", "code"])

    rows, types = [], []

    def _store_row(r):
        c = r["code"]
        return {"Region": r["region"], "STORE CODE": int(c), "CITY": r["city"],
                "LOCATION": r["location"], "BRAND": r["brand"],
                "Same Day LY": float(sd.get(c, 0.0)),
                "Same Date LY": float(dt.get(c, 0.0))}

    def _total_row(label, sub):
        return {"Region": label, "STORE CODE": "", "CITY": "", "LOCATION": "",
                "BRAND": "", "Same Day LY": sub["Same Day LY"].sum(),
                "Same Date LY": sub["Same Date LY"].sum()}

    all_rows = []
    for region, grp in present.groupby("region", sort=False):
        rrows = [_store_row(r) for _, r in grp.iterrows()]
        for sr in rrows:
            rows.append(sr); types.append("store")
        rdf = pd.DataFrame(rrows); all_rows.append(rdf)
        rows.append(_total_row(f"{region} Total", rdf)); types.append("subtotal")
    grand = pd.concat(all_rows, ignore_index=True)
    rows.append(_total_row("Grand Total", grand)); types.append("grand")
    return pd.DataFrame(rows, columns=DAY_REPORT_COLS), types


# --------------------------------------------------------------------------- #
# GROWTH-DEGROWTH SHEET — exact layout of the workbook's "to develop" sheet.
# Store identity (name/location/NEW-OLD/CLOSED/DOO) comes from gd_store_attrs.csv
# (extracted from that sheet); the figures are computed live from the data.
# --------------------------------------------------------------------------- #
GD_SHEET_COLS = [
    "Region", "NEW/OLD", "STORE CODE", "STORE NAME MAIN", "LOCATION", "CLOSED",
    "DOO", "Sum of YTD_LY", "Sum of YTD_TY", "Sum of GD_YTD_%", "Sum of MTD_LY",
    "Sum of MTD_TY", "Sum of GD_MTD_%", "Sum of DAY SALE FIGURE",
    "Sum of MONTH SALE LY", "Sum of PROJECTED MTD", "Sum of LY FULL SALES",
    "Sum of PROJECTED YTD", "Sum of TTM SALES",
]
def _newold_order(asof) -> list:
    """The tag order for this fiscal year, DERIVED — never a frozen list.

    It used to be the literal `["2526FY", "2526PY", "2526NA"]` while the tags
    themselves were derived from the as-of date. On 1 April 2027 every tag would
    have become `2627…`, matched nothing, and the sheet's whole NEW/OLD grouping
    would have collapsed into one bucket with no error — the same shape as the
    MW Data bomb. Closed stores sort last (Manav + chachu, 17 Aug).
    """
    p = _newold_prefix(asof)
    return [f"{p}FY", f"{p}PY", f"{p}NA", f"{p}CL"]
# The shape `gd_store_attrs_dyn` returns. Named because an EMPTY selection has to
# return these columns too: built from an empty row list the frame has no columns
# at all, and the next line — which reads `doo` — raised `KeyError: 'doo'`.
_GD_ATTR_COLS = ["code", "region", "store_name_main", "location_main", "closed",
                 "doo", "parent", "location_tl", "brand_order", "loc_order",
                 "sba", "ca", "new_old"]
_GD_VALUE_COLS = ["Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY",
                  "Sum of DAY SALE FIGURE", "Sum of MONTH SALE LY",
                  "Sum of PROJECTED MTD", "Sum of LY FULL SALES", "Sum of PROJECTED YTD", "Sum of TTM SALES"]


def gd_store_attrs() -> pd.DataFrame:
    a = pd.read_csv(os.path.join(_DIR, "gd_store_attrs.csv"))
    a["code"] = a["code"].astype(int)
    for c in ["closed", "doo", "store_name_main", "location_main", "region", "new_old"]:
        a[c] = a[c].fillna("").astype(str)
    return a


def _newold_prefix(asof) -> str:
    """`2526` for FY 2026-27 — the workbook's own way of naming the pair."""
    fy = asof.year if asof.month >= 4 else asof.year - 1
    return f"{(fy - 1) % 100:02d}{fy % 100:02d}"


def _newold_from_doo(doo, asof):
    """NEW/OLD label derived live from DOO + the current fiscal year, so it
    re-labels itself every year (2526FY/PY/NA → 2627FY/PY/NA next FY)."""
    fy = asof.year if asof.month >= 4 else asof.year - 1
    prior = fy - 1
    tag = _newold_prefix(asof)
    if not doo or pd.isna(doo):
        return f"{tag}FY"
    d = pd.to_datetime(doo)
    if d >= pd.Timestamp(fy, 4, 1):
        return f"{tag}NA"
    if d >= pd.Timestamp(prior, 4, 1):
        return f"{tag}PY"
    return f"{tag}FY"


def gd_store_attrs_dyn(df: pd.DataFrame, asof=None) -> pd.DataFrame:
    """Store attributes for the GD-family tabs, driven by the LIVE data so new
    stores wire in automatically. The store list is every store active this FY;
    curated attributes (DOO/CLOSED/PARENT/Location TL/SBA/CA/order) come from
    gd_store_attrs.csv when known, else are derived from the data — DOO = first
    sale date, name/location/region from the sheet, PARENT from the brand map,
    Location TL defaults to the store's location. NEW/OLD is always derived live
    from DOO."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    static = gd_store_attrs()
    known = static.set_index("code")
    active = active_codes(df, asof)
    first_sale = df[df["sales"] > 0].groupby("code")["date"].min()
    ident = df.drop_duplicates("code").copy()
    ident["code"] = ident["code"].astype(int)
    ident = ident.set_index("code")
    brand_parent = dict(zip(static["store_name_main"], static["parent"]))

    rows = []
    for c in sorted(int(x) for x in active):
        if c in known.index:
            r = known.loc[c].to_dict()
            r["code"] = c
        else:  # new / previously-unseen store — derive what we can from the data
            b = str(ident.loc[c, "brand"]) if c in ident.index else ""
            loc = str(ident.loc[c, "location"]) if c in ident.index else ""
            reg = ident.loc[c, "region"] if c in ident.index else "East & NE"
            fs = first_sale.get(c)
            r = {"code": c, "region": reg, "store_name_main": b, "location_main": loc,
                 "closed": "", "doo": fs.strftime("%Y-%m-%d") if pd.notna(fs) else "",
                 "parent": brand_parent.get(b, b or "—"), "location_tl": loc,
                 "brand_order": 9000 + c, "loc_order": 9000 + c,
                 "sba": float("nan"), "ca": float("nan")}
        rows.append(r)

    # No active store (a selection of stores that have all closed) still has to
    # come back with the columns every caller reads — see `_GD_ATTR_COLS`.
    out = pd.DataFrame(rows) if rows else pd.DataFrame(columns=_GD_ATTR_COLS)
    # ★ THE CLOSURE DATE COMES FROM THE MASTER, like the behaviour it drives.
    # This column used to be read from the committed attributes file while the
    # capping and the CL tag read `closed_map()` — so the day Manav dated Vega
    # Circle Mall's closure in the master, every report changed and the sheet's
    # own CLOSED column still said "(blank)". One fact, one source.
    _cl = {int(k): pd.Timestamp(v) for k, v in closed_map().items()}
    out["closed"] = [
        _cl[int(c)].strftime("%Y-%m-%d") if int(c) in _cl else (s or "")
        for c, s in zip(out["code"], out["closed"])
    ]

    out["new_old"] = [_newold_from_doo(d, asof) for d in out["doo"]]
    # ★ A CLOSED STORE IS ITS OWN CLASS (chachu, 16 Aug: "moving them downwards
    # in the sheet under a new head"). It outranks the DOO tag: what matters
    # about a shut store is that it is shut, not when it opened. The prefix is
    # the sheet's own, so it reads 2526CL beside 2526FY — see `_newold_order`.
    _shut = {int(k): pd.Timestamp(v) for k, v in closed_map().items()}
    out["new_old"] = [
        f"{_newold_prefix(asof)}CL"
        if (int(c) in _shut and _shut[int(c)] <= asof) else t
        for c, t in zip(out["code"], out["new_old"])
    ]
    for col in ["closed", "doo", "store_name_main", "location_main", "region",
                "parent", "location_tl", "new_old"]:
        out[col] = out[col].fillna("").astype(str)
    return out


def _l2l_spans(df: pd.DataFrame, asof):
    """Each store's comparable span, in this year's dates — Manav's rule.

    The same spans the Executive Snapshot compares over, so the sheet's own
    like-to-like line and page 1's tile are the same arithmetic rather than two
    calculations that happen to agree. Kept here as a thin call so there is one
    definition of "comparable" in the codebase, not two.
    """
    import exec_snapshot
    return exec_snapshot.l2l_bounds(df, "code", "sales", closed_map(), asof,
                                    opened=opened_map(df, asof))


def opened_map(df: pd.DataFrame, asof=None) -> dict:
    """store code -> opening date, as the sheet itself prints it.

    Deliberately the same `doo` the GD sheet shows in its own DOO column, so a
    reader can check the like-to-like span against the row it sits on rather
    than against a date held somewhere else.
    """
    a = gd_store_attrs_dyn(df, asof)
    out = {}
    for c, d in zip(a["code"], a["doo"]):
        ts = pd.to_datetime(d, errors="coerce")
        if pd.notna(ts):
            out[int(c)] = ts
    return out


def _comparable_throughout(a, start, end) -> bool:
    """True when a store's whole window is comparable — the ordinary store.

    A start alone is not enough: South's span opens on 19 April 2027, a year
    after its takeover and long past the end of this window, so every South
    store looked comparable and carried its whole turnover into the like-to-like
    line. The span has to actually exist.
    """
    c = int(a["code"])
    s, e = start.get(c), end.get(c)
    return s is not None and e is not None and s <= e


def _gd_frac(ty, ly):
    return ((ty - ly) / ly) if ly else None


def ttm_by_store(df, asof):
    """Trailing 12 months per store — but ONLY where the feed covers all twelve.

    Manav, 29 Aug: *"if you dont have data for last year fully, then give the
    TTM as a 0, instead of giving it as the ytd figure."*

    A store that began trading inside the window sums to a PART year that reads
    on the page as a whole one. In this feed that is every South store: they
    open 19 Apr 2026, so the window's first 233 days are empty and their TTM
    came out equal to their YTD to the rupee — sitting in a column headed
    "TTM SALES" beside East's real twelve months. A zero says "we do not have
    this"; a part year dressed as a year says something false.

    Coverage is read off the DATA, not off a `doo` attribute, for the same
    reason `l2l_bounds` reads it there: the curated date for South is a
    takeover, and this feed simply has no rows before it. A store's first sale
    here IS its left edge. A store that CLOSED inside the window keeps its
    figure — it traded the span it is being credited with.
    """
    ttm_start = asof - pd.DateOffset(years=1) + pd.Timedelta(days=1)
    win = df[(df["date"] >= ttm_start) & (df["date"] <= asof)]
    ttm = win.groupby("code")["sales"].sum()
    first = df.groupby("code")["date"].min()
    covered = set(first[first <= ttm_start].index)
    return ttm.where(ttm.index.isin(covered), 0.0)


def gd_sheet_report(df: pd.DataFrame, asof=None):
    """The GROWTH DEGROWTH SHEET, matching the workbook 1:1. Returns
    (display_df, row_types). Figures are live; identity from gd_store_attrs."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    attrs = gd_store_attrs_dyn(df, asof)
    # Nothing traded this year in this selection — every store in it has
    # closed. Return the report's own empty shape so the tab can say so.
    if attrs.empty:
        return pd.DataFrame(columns=GD_SHEET_COLS), []

    # Current-FY windows (active-only, close-capped) reused from the report engine.
    mtd_cur, mtd_pri = _window_frames(df, "MTD", asof)
    ytd_cur, ytd_pri = _window_frames(df, "YTD", asof)
    g = lambda f: f.groupby("code")["sales"].sum()
    mtd_ty, mtd_ly = g(mtd_cur), g(mtd_pri)
    ytd_ty, ytd_ly = g(ytd_cur), g(ytd_pri)
    day = g(df[df["date"] == asof])

    # Raw (uncapped) last-year same-month + last-full-fiscal-year totals.
    ly_month_start = asof.replace(day=1) - pd.DateOffset(years=1)
    ly_month_end = ly_month_start + pd.offsets.MonthEnd(0)
    month_ly = g(df[(df["date"] >= ly_month_start) & (df["date"] <= ly_month_end)])
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    ly_full = g(df[(df["date"] >= pd.Timestamp(fy_year - 1, 4, 1)) &
                   (df["date"] <= pd.Timestamp(fy_year, 3, 31))])

    # ★ TRAILING 12 MONTHS — rolling 365 days ending today, so it moves daily
    # like DAY SALE does rather than once a month. A store whose history does
    # not reach back across the whole window prints 0 rather than a part year:
    # see `ttm_by_store`. That is every South store on this feed, which is the
    # same reason South carries no history anywhere else on this sheet.
    ttm = ttm_by_store(df, asof)

    # Projection day-counts.
    fy_start = pd.Timestamp(fy_year, 4, 1)

    def _doo_ts(s):
        return pd.to_datetime(s) if s else fy_start

    def _store_row(a):
        c = int(a["code"])
        mty, mly = float(mtd_ty.get(c, 0.0)), float(mtd_ly.get(c, 0.0))
        yty, yly = float(ytd_ty.get(c, 0.0)), float(ytd_ly.get(c, 0.0))
        doo = _doo_ts(a["doo"])
        closed = pd.to_datetime(a["closed"]) if a["closed"] else None
        # Run-rate over the days actually traded (see projections.py).
        proj_mtd = project_mtd(mty, asof, doo, closed)
        proj_ytd = project_ytd(yty, fy_start, doo, asof, closed)
        return {
            "Region": a["region"], "NEW/OLD": a["new_old"], "STORE CODE": c,
            "STORE NAME MAIN": a["store_name_main"], "LOCATION": a["location_main"],
            "CLOSED": a["closed"] if a["closed"] else "(blank)", "DOO": a["doo"],
            "Sum of YTD_LY": yly, "Sum of YTD_TY": yty,
            "Sum of GD_YTD_%": _gd_frac(yty, yly),
            "Sum of MTD_LY": mly, "Sum of MTD_TY": mty,
            "Sum of GD_MTD_%": _gd_frac(mty, mly),
            "Sum of DAY SALE FIGURE": float(day.get(c, 0.0)),
            "Sum of MONTH SALE LY": float(month_ly.get(c, 0.0)),
            "Sum of PROJECTED MTD": proj_mtd,
            "Sum of LY FULL SALES": float(ly_full.get(c, 0.0)),
            "Sum of PROJECTED YTD": proj_ytd,
            "Sum of TTM SALES": float(ttm.get(c, 0.0)),
        }

    # ★★ THE SPLIT (chachu, 16 Aug; built 17 Aug). A store that has only PART of
    # a comparable year is shown as two lines and a subtotal: the span it has no
    # last year for, and the span it has. Silchar opened on 1 June last year, so
    # its single line read +112.2% — true, and useless. Split, it says what is
    # actually happening: two months of trade with nothing to compare, and the
    # months that DO compare are down 2.8%.
    #
    # The halves carry their own NEW/OLD label (Manav's call): the comparable
    # half `…FY`, the other `…NA`, which is what that tag has always meant. They
    # stay ADJACENT under the store's own block rather than being filed into two
    # different ones — the subtotal is the point, and a store split across the
    # page would lose it.
    #
    # Only the YTD and MTD pairs split. The day's sale, last year's full month,
    # the projections and last full year are different windows and would mean
    # nothing cut this way; they sit on the subtotal, where the store is whole.
    _l2l_start, _l2l_end = _l2l_spans(df, asof)
    _yr = pd.DateOffset(years=1)
    _split_cols = ["Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY"]

    def _window_part(frame, c, lo, hi):
        m = ((frame["code"] == c) & (frame["date"] >= lo) & (frame["date"] <= hi))
        return float(frame[m]["sales"].sum())

    def _split_rows(a, whole):
        """[] when the store is comparable throughout — the usual case."""
        c = int(a["code"])
        s, e = _l2l_start.get(c), _l2l_end.get(c)
        if s is None or e is None or s > e:
            return []                      # no comparable span at all: one line
        inside = {
            "Sum of YTD_TY": _window_part(ytd_cur, c, s, e),
            "Sum of YTD_LY": _window_part(ytd_pri, c, s - _yr, e - _yr),
            "Sum of MTD_TY": _window_part(mtd_cur, c, s, e),
            "Sum of MTD_LY": _window_part(mtd_pri, c, s - _yr, e - _yr),
        }
        outside = {k: whole[k] - inside[k] for k in _split_cols}
        if all(abs(v) < 1 for v in outside.values()):
            return []                      # comparable all the way through
        prefix = _newold_prefix(asof)

        def part(values, tag, note):
            d = {col: (float("nan") if col in _GD_VALUE_COLS else "")
                 for col in GD_SHEET_COLS}
            d.update({"Region": a["region"], "NEW/OLD": tag, "STORE CODE": c,
                      "STORE NAME MAIN": a["store_name_main"],
                      "LOCATION": f'{a["location_main"]} — {note}',
                      "CLOSED": "", "DOO": ""})
            d.update(values)
            d["Sum of GD_YTD_%"] = _gd_frac(d["Sum of YTD_TY"], d["Sum of YTD_LY"])
            d["Sum of GD_MTD_%"] = _gd_frac(d["Sum of MTD_TY"], d["Sum of MTD_LY"])
            return d

        return [part(outside, f"{prefix}NA", "no L2L"),
                part(inside, f"{prefix}FY", f"L2L from {s:%d-%m-%Y}")]

    def _total_row(label_region, label_newold, sub):
        d = {c: "" for c in GD_SHEET_COLS}
        d["Region"] = label_region
        d["NEW/OLD"] = label_newold
        for c in _GD_VALUE_COLS:
            d[c] = pd.to_numeric(sub[c], errors="coerce").fillna(0).sum()
        d["Sum of GD_YTD_%"] = _gd_frac(d["Sum of YTD_TY"], d["Sum of YTD_LY"])
        d["Sum of GD_MTD_%"] = _gd_frac(d["Sum of MTD_TY"], d["Sum of MTD_LY"])
        return d

    order = {k: i for i, k in enumerate(_newold_order(asof))}
    attrs["_r"] = attrs["region"].map({k: i for i, k in enumerate(REGION_ORDER)}).fillna(9)
    attrs["_n"] = attrs["new_old"].map(order).fillna(9)
    attrs = attrs.sort_values(["_r", "_n", "code"])

    rows, types = [], []
    grand_rows = []
    l2l_rows, non_l2l_rows = [], []          # for the footer summary
    for region, rgrp in attrs.groupby("region", sort=False):
        region_rows = []
        for newold, ngrp in rgrp.groupby("new_old", sort=False):
            srows = []
            for _, a in ngrp.iterrows():
                whole = _store_row(a)
                halves = _split_rows(a, whole)
                for h in halves:
                    rows.append(h)
                    types.append("split")
                    (non_l2l_rows if h["NEW/OLD"].endswith("NA")
                     else l2l_rows).append(h)
                if halves:
                    # The store's own line closes its two halves, so the sheet
                    # still shows the store as one thing. Labelled TOTAL, not
                    # "2526FY Total" — that is the block subtotal's label three
                    # rows down, and two different totals cannot share a name.
                    rows.append({**whole, "NEW/OLD": "TOTAL"})
                    types.append("storetotal")
                else:
                    rows.append(whole)
                    types.append("store")
                    (l2l_rows if _comparable_throughout(a, _l2l_start, _l2l_end)
                     else non_l2l_rows).append(whole)
                srows.append(whole)
            sdf = pd.DataFrame(srows)
            region_rows.append(sdf)
            rows.append(_total_row(region, f"{newold} Total", sdf))
            types.append("subtotal")
        rdf = pd.concat(region_rows, ignore_index=True)
        grand_rows.append(rdf)
        rows.append(_total_row(f"{region} Total", "", rdf))
        types.append("block")
    gdf = pd.concat(grand_rows, ignore_index=True)
    rows.append(_total_row("Grand Total", "", gdf))
    types.append("grand")

    # ★ THE FOOTER THAT MAKES THE SHEET SAY ITS OWN LIKE TO LIKE. Summing the
    # comparable lines gives the figure the Executive Snapshot prints on page 1,
    # to the rupee — the sheet now shows its working instead of disagreeing.
    if l2l_rows or non_l2l_rows:
        for label, part in (("LIKE TO LIKE", l2l_rows), ("NO L2L", non_l2l_rows)):
            if not part:
                continue
            r = _total_row(label, "", pd.DataFrame(part))
            # Only the compared columns mean anything on these lines. Blanked as
            # NaN, not as "" — the renderers format a number column and an empty
            # string is not one.
            for col in _GD_VALUE_COLS:
                if col not in _split_cols:
                    r[col] = float("nan")
            rows.append(r)
            types.append("summary")
    return pd.DataFrame(rows, columns=GD_SHEET_COLS), types


# --------------------------------------------------------------------------- #
# MW_DATA — monthly contribution grid (workbook's MW_DATA sheet). FY25-26 and
# FY26-27 are computed live; FY24-25 and older come from mw_data_historical.csv.
# --------------------------------------------------------------------------- #
# ★ THE GRID'S YEARS ARE DERIVED, NOT WRITTEN DOWN.
# This was a literal list ending at 2026-27, and `mw_data` chose each year's
# treatment by name (`if fy == "2026-27"`). On 1 Apr 2027 the new fiscal year
# would simply not have appeared — no error, no gap, a whole year of trade
# rendering nowhere while the old top row kept its current-year styling. Proved
# by simulation before the fix: a frame carrying Rs 37.68 Cr of FY27-28 sales
# produced the same ten years as today.
#
# The shape is the workbook's and is preserved exactly: ten years in rows of
# three, three and four, the top row ASCENDING so the current year sits last.
_MW_ROWS = (3, 3, 4)


def _fy_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[2:]}"


def _fy_of(ts) -> int:
    ts = pd.Timestamp(ts)
    return ts.year if ts.month >= 4 else ts.year - 1


def mw_blocks(asof=None) -> list[list[str]]:
    """The grid's fiscal years, laid out as the workbook lays them out."""
    cur = _fy_of(asof if asof is not None else pd.Timestamp.today())
    years = [cur - i for i in range(sum(_MW_ROWS))]      # newest first
    top, mid = _MW_ROWS[0], _MW_ROWS[0] + _MW_ROWS[1]
    return [[_fy_label(y) for y in reversed(years[:top])],
            [_fy_label(y) for y in years[top:mid]],
            [_fy_label(y) for y in years[mid:]]]


def mw_layout(mw: dict) -> list[list[str]]:
    """The rows of a grid that was already built — its own years, in its own
    order — so the tab, the PDF and the figures can never disagree about which
    years were drawn."""
    fys = list(mw)
    out, i = [], 0
    for n in _MW_ROWS:
        if i >= len(fys):
            break
        out.append(fys[i:i + n])
        i += n
    return out


def _fy_periods(start_year):
    return ([pd.Period(f"{start_year}-{m:02d}", "M") for m in range(4, 13)] +
            [pd.Period(f"{start_year + 1}-{m:02d}", "M") for m in range(1, 4)])


def mw_data(df: pd.DataFrame, asof=None, vfl_df=None) -> dict:
    """Per-FY monthly totals for the MW_DATA grid. Returns {fy: {type, months,
    grand}}. type 'region' (FY26-27: East&NE/South split) or 'std' (TOTAL/PRPL/
    MRIPL). FY25-26 & FY26-27 live from the data; older FYs from the snapshot."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    hist = pd.read_csv(os.path.join(_DIR, "mw_data_historical.csv"))
    hist["fy"] = hist["fy"].astype(str)
    d = df.copy()
    d["m"] = d["date"].dt.to_period("M")
    monthly = d.groupby(["m", "region"])["sales"].sum().unstack(fill_value=0)
    for r in REGION_ORDER:
        if r not in monthly.columns:
            monthly[r] = 0.0

    def _pct(x, tot):
        return (x / tot * 100) if tot else 0.0

    out = {}
    # Which years the feed can actually answer for, and which one is current.
    # Both were literals; a year is now "live" if the feed reaches back to its
    # 1 April, and "current" if the as-of date falls inside it — so the FY that
    # gets the region split moves with the calendar instead of staying 2026-27
    # forever.
    feed_from = df["date"].min() if len(df) else pd.NaT
    cur_fy = _fy_label(_fy_of(asof))

    for block in mw_blocks(asof):
        for fy in block:
            start_year = int(fy.split("-")[0])
            pers = _fy_periods(start_year)
            labels = [p.strftime("%b-%y") for p in pers]
            live = pd.notna(feed_from) and feed_from <= pd.Timestamp(start_year, 4, 1)

            if live and fy == cur_fy:  # region split, live
                ene = [float(monthly.loc[p, "East & NE"]) if p in monthly.index else 0.0 for p in pers]
                sth = [float(monthly.loc[p, "South"]) if p in monthly.index else 0.0 for p in pers]
                tot = [e + s for e, s in zip(ene, sth)]
                g_tot, g_ene, g_sth = sum(tot), sum(ene), sum(sth)
                months = [{
                    "month": labels[i], "total": tot[i], "ene": ene[i], "south": sth[i],
                    "cont": _pct(tot[i], g_tot),
                    "ene_contrib": _pct(ene[i], g_ene), "south_contrib": _pct(sth[i], g_sth),
                    "ene_pct": _pct(ene[i], tot[i]), "south_pct": _pct(sth[i], tot[i]),
                } for i in range(12)]
                # ★ THE VFL SLICE ON THE CURRENT BLOCK. Manav, 28 Aug: last
                # year's halves come off and the Manyavar/Mohey half-year goes
                # on instead — the portfolio block is every brand, and what he
                # wants beside it is how much of that is VFL, split by half.
                # Percentages are against VFL'S OWN total, not the portfolio's:
                # these rows answer "how is VFL's year shaped", not "how big is
                # VFL" — the money columns already answer that.
                vfl = None
                if vfl_df is not None and len(vfl_df):
                    v = vfl_df.copy()
                    v["m"] = v["date"].dt.to_period("M")
                    amt = "Sales" if "Sales" in v.columns else None
                    if amt is None:
                        import loader as _L
                        amt = _L.COL_AMOUNT
                    reg = "Region" if "Region" in v.columns else None
                    if reg is None:
                        import loader as _L
                        reg = _L.COL_REGION
                    vm = v.groupby(["m", reg])[amt].sum().unstack(fill_value=0)
                    for _r in REGION_ORDER:
                        if _r not in vm.columns:
                            vm[_r] = 0.0
                    v_ene = [float(vm.loc[q, "East & NE"]) if q in vm.index else 0.0
                             for q in pers]
                    v_sth = [float(vm.loc[q, "South"]) if q in vm.index else 0.0
                             for q in pers]
                    v_tot = [e + s_ for e, s_ in zip(v_ene, v_sth)]
                    vfl = {"label": "VFL",
                           "months": [{"total": v_tot[i], "ene": v_ene[i],
                                       "south": v_sth[i]} for i in range(12)],
                           "grand": {"total": sum(v_tot), "ene": sum(v_ene),
                                     "south": sum(v_sth)}}
                out[fy] = {"type": "region", "months": months, "vfl": vfl,
                           "grand": {"total": g_tot, "ene": g_ene, "south": g_sth,
                                     "ene_contrib": _pct(g_ene, g_tot),
                                     "south_contrib": _pct(g_sth, g_tot)}}
            elif live:             # std split (all PRPL), live
                tot = [float(monthly.loc[p].sum()) if p in monthly.index else 0.0 for p in pers]
                g = sum(tot)
                months = [{"month": labels[i], "total": tot[i], "prpl": tot[i],
                           "mripl": 0.0, "cont": _pct(tot[i], g)} for i in range(12)]
                out[fy] = {"type": "std", "months": months,
                           "grand": {"total": g, "prpl": g, "mripl": 0.0}}
            else:  # static from snapshot
                h = hist[hist["fy"] == fy].set_index("month_idx")
                tot = [float(h.loc[i, "total"]) if i in h.index else 0.0 for i in range(1, 13)]
                prpl = [float(h.loc[i, "prpl"]) if i in h.index else 0.0 for i in range(1, 13)]
                mripl = [float(h.loc[i, "mripl"]) if i in h.index else 0.0 for i in range(1, 13)]
                g = sum(tot)
                months = [{"month": labels[i], "total": tot[i], "prpl": prpl[i],
                           "mripl": mripl[i], "cont": _pct(tot[i], g)} for i in range(12)]
                out[fy] = {"type": "std", "months": months,
                           "grand": {"total": g, "prpl": sum(prpl), "mripl": sum(mripl)}}
    return out


# MW_DATA grid → HTML (matches the workbook layout: 3 stacked blocks, FY groups
# side-by-side, region split + contribution % for the current FY).
_MW_STD = (["MONTH", "TOTAL SALE", "PRPL", "MRIPL", "MONTHLY CONT  (%)"],
           [("month", "t"), ("total", "m"), ("prpl", "m"), ("mripl", "m"), ("cont", "p")])
_MW_REG = (["MONTH", "TOTAL SALE", "East and NE", "South", "MONTHLY CONT  (%)",
            "Month Contribution\nEast and NE", "Month Contribution\nSouth",
            "Percent of Sales\nRegion East and NE", "Percent of Sales\nRegion South"],
           [("month", "t"), ("total", "m"), ("ene", "m"), ("south", "m"), ("cont", "p"),
            ("ene_contrib", "p"), ("south_contrib", "p"), ("ene_pct", "p"), ("south_pct", "p")])


def mw_data_html(mw: dict) -> str:
    # ★ CLIENT WORKBOOK PALETTE, same as every report. This table was still on
    # the old maroon/gold scheme, so the app and the PDF of the SAME sheet did
    # not look like the same document.
    HDR, TOTAL, HALF = "#DAEEF3", "#FFFF00", "#DAEEF3"
    LINE, BODY, ALT = "#636363", "#FFFFFF", "#FFFFFF"
    def _m(v): return f"{v:,.0f}"
    def _p(v): return f"{v:,.2f}%"

    def _cols(fy):
        return _MW_REG if mw[fy]["type"] == "region" else _MW_STD

    def _cell(txt, align, bg, bold=False, color="#1f2937"):
        w = "800" if bold else "500"
        return (f'<td style="padding:3px 7px;text-align:{align};color:{color};'
                f'font-weight:{w};background:{bg};border:1px solid {LINE};'
                f'white-space:nowrap;font-variant-numeric:tabular-nums;">{txt}</td>')

    def _fmt(v, typ):
        if v is None or v == "":
            return ""
        if typ == "t":
            return str(v)
        return _m(v) if typ == "m" else _p(v)

    # A wide transparent spacer column that separates one FY group from the next.
    _GAP = 'style="border:none;background:transparent;min-width:26px;width:26px;padding:0;"'

    def block(fys):
        title, sub = "", ""
        for gi, fy in enumerate(fys):
            hdr, _ = _cols(fy)
            if gi:
                title += f"<th {_GAP}></th>"
                sub += f"<th {_GAP}></th>"
            title += (f'<th colspan="{len(hdr)}" style="background:{HDR};color:#111;'
                      f'font-weight:800;padding:6px 8px;border:1px solid {LINE};'
                      f'text-align:center;">MONTHLY CONT SHEET FY {fy}</th>')
            for h in hdr:
                sub += (f'<th style="background:{HDR};color:#111;font-weight:700;'
                        f'font-size:10px;padding:4px 6px;border:1px solid {LINE};'
                        f'text-align:center;white-space:pre-line;vertical-align:bottom;">{h}</th>')
        body = ""
        for i in range(12):
            tds, bg = "", BODY          # plain white body, no zebra — as the workbook
            for gi, fy in enumerate(fys):
                if gi:
                    tds += f"<td {_GAP}></td>"
                _, keys = _cols(fy)
                mrow = mw[fy]["months"][i]
                for k, typ in keys:
                    align = "left" if typ == "t" else "right"
                    tds += _cell(_fmt(mrow.get(k, ""), typ), align, bg)
            body += f"<tr>{tds}</tr>"
        # GRAND TOTAL
        gtds = ""
        for gi, fy in enumerate(fys):
            if gi:
                gtds += f"<td {_GAP}></td>"
            g = mw[fy]["grand"]
            if mw[fy]["type"] == "region":
                vals = [("GRAND TOTAL", "t"), (g["total"], "m"), (g["ene"], "m"),
                        (g["south"], "m"), ("", "p"), ("", "p"), ("", "p"),
                        (g["ene_contrib"], "p"), (g["south_contrib"], "p")]
            else:
                vals = [("GRAND TOTAL", "t"), (g["total"], "m"), (g["prpl"], "m"),
                        (g["mripl"], "m"), ("", "p")]
            for v, typ in vals:
                align = "left" if typ == "t" else "right"
                gtds += _cell(_fmt(v, typ), align, TOTAL, bold=True)
        body += f"<tr>{gtds}</tr>"

        # ── H1 / H2 ────────────────────────────────────────────────────────
        # Manav, 27 Aug: the business leans into Q3 and Q4, so the halves go
        # straight under GRAND TOTAL in this same table. Each FY block gets its
        # OWN halves — this year's beside last year's — and nothing is compared
        # across years here.
        # ★ A HALF IN PROGRESS IS NOT A HALF. On 26 Aug, H1 holds five months of
        # a six-month period and H2 holds nothing at all. The months already read
        # 0 for what has not happened, so summing them is right; what would be
        # wrong is letting the percentage columns imply the halves are finished.
        # The label carries the state instead.
        for lo, hi, name in ((0, 6, "H1  Apr-Sep"), (6, 12, "H2  Oct-Mar")):
            htds = ""
            for gi, fy in enumerate(fys):
                if gi:
                    htds += f"<td {_GAP}></td>"
                rowsl = mw[fy]["months"][lo:hi]
                g = mw[fy]["grand"]
                tot = sum(r.get("total") or 0 for r in rowsl)
                live = sum(1 for r in rowsl if (r.get("total") or 0) > 0)
                lbl = name if live in (0, hi - lo) else f"{name} ({live}/{hi-lo} mth)"
                pct = lambda a, b: (a / b * 100) if b else 0.0
                if mw[fy]["type"] == "region":
                    ene = sum(r.get("ene") or 0 for r in rowsl)
                    sth = sum(r.get("south") or 0 for r in rowsl)
                    vals = [(lbl, "t"), (tot, "m"), (ene, "m"), (sth, "m"),
                            (pct(tot, g["total"]), "p"),
                            (pct(ene, g["ene"]), "p"), (pct(sth, g["south"]), "p"),
                            (pct(ene, tot), "p"), (pct(sth, tot), "p")]
                else:
                    vals = [(lbl, "t"), (tot, "m"),
                            (sum(r.get("prpl") or 0 for r in rowsl), "m"),
                            (sum(r.get("mripl") or 0 for r in rowsl), "m"),
                            (pct(tot, g["total"]), "p")]
                for v, typ in vals:
                    align = "left" if typ == "t" else "right"
                    htds += _cell(_fmt(v, typ), align, HALF, bold=True)
            body += f"<tr>{htds}</tr>"

        # the VFL slice's halves, on the current block's own columns
        for lo, hi, name in ((0, 6, "H1  Apr-Sep"), (6, 12, "H2  Oct-Mar")):
            ptds, any_prior = "", False
            for gi, fy in enumerate(fys):
                if gi:
                    ptds += f"<td {_GAP}></td>"
                pr = mw[fy].get("vfl")
                n = len(_cols(fy)[0])
                if not pr:
                    ptds += "".join(_cell("", "right", BODY) for _ in range(n))
                    continue
                any_prior = True
                seg = pr["months"][lo:hi]; pg = pr["grand"]
                tot = sum(x["total"] for x in seg)
                ene = sum(x["ene"] for x in seg)
                sth = sum(x["south"] for x in seg)
                pc = lambda a, b: (a / b * 100) if b else 0.0
                vals = [(f"{name}  {pr['label']}", "t"), (tot, "m"), (ene, "m"), (sth, "m"),
                        (pc(tot, pg["total"]), "p"), (pc(ene, pg["ene"]), "p"),
                        (pc(sth, pg["south"]), "p"), (pc(ene, tot), "p"),
                        (pc(sth, tot), "p")]
                for v, typ in vals:
                    align = "left" if typ == "t" else "right"
                    ptds += _cell(_fmt(v, typ), align, BODY, bold=True)
            if any_prior:
                body += f"<tr>{ptds}</tr>"
        return (f'<table style="border-collapse:collapse;font-family:Inter,Segoe UI,'
                f'sans-serif;font-size:11px;margin:0 0 26px;">'
                f'<thead><tr>{title}</tr><tr>{sub}</tr></thead><tbody>{body}</tbody></table>')

    inner = "".join(block(b) for b in mw_layout(mw))
    return f'<div style="overflow-x:auto;max-width:100%;">{inner}</div>'


# --------------------------------------------------------------------------- #
# BRAND_WISE_GD — same GD figures as gd_sheet_report, grouped by PARENT company.
# --------------------------------------------------------------------------- #
BRAND_GD_COLS = [
    "PARENT", "STORE NAME MAIN", "LOCATION", "NEW/OLD", "CLOSED",
    "Sum of YTD_LY", "Sum of YTD_TY", "Sum of GD_YTD_%", "Sum of MTD_LY",
    "Sum of MTD_TY", "Sum of GD_MTD_%", "Sum of DAY SALE FIGURE",
    "Sum of MONTH SALE LY", "Sum of PROJECTED MTD", "Sum of LY FULL SALES",
    "Sum of PROJECTED YTD", "Sum of TTM SALES",
]
_BRAND_VALUE_COLS = ["Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY",
                     "Sum of DAY SALE FIGURE", "Sum of MONTH SALE LY",
                     "Sum of PROJECTED MTD", "Sum of LY FULL SALES", "Sum of PROJECTED YTD", "Sum of TTM SALES"]


def _gd_store_metrics(df: pd.DataFrame, asof: pd.Timestamp) -> dict:
    """Per-store GD figures (identical to gd_sheet_report), keyed by store code."""
    attrs = gd_store_attrs_dyn(df, asof).set_index("code")
    mtd_cur, mtd_pri = _window_frames(df, "MTD", asof)
    ytd_cur, ytd_pri = _window_frames(df, "YTD", asof)
    g = lambda f: f.groupby("code")["sales"].sum()
    mtd_ty, mtd_ly = g(mtd_cur), g(mtd_pri)
    ytd_ty, ytd_ly = g(ytd_cur), g(ytd_pri)
    day = g(df[df["date"] == asof])
    ly_month_start = asof.replace(day=1) - pd.DateOffset(years=1)
    ly_month_end = ly_month_start + pd.offsets.MonthEnd(0)
    month_ly = g(df[(df["date"] >= ly_month_start) & (df["date"] <= ly_month_end)])
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    ly_full = g(df[(df["date"] >= pd.Timestamp(fy_year - 1, 4, 1)) &
                   (df["date"] <= pd.Timestamp(fy_year, 3, 31))])
    # ★ TRAILING 12 MONTHS — a rolling 365 days ending today, so it moves every
    # day like DAY SALE and PROJECTED YTD do, rather than once a month. Stores
    # the window outruns print 0, not a part year — see `ttm_by_store`.
    ttm = ttm_by_store(df, asof)
    fy_start = pd.Timestamp(fy_year, 4, 1)
    out = {}
    for c in attrs.index:
        c = int(c)
        mty, mly = float(mtd_ty.get(c, 0.0)), float(mtd_ly.get(c, 0.0))
        yty, yly = float(ytd_ty.get(c, 0.0)), float(ytd_ly.get(c, 0.0))
        doo_s = attrs.loc[c, "doo"]
        doo = pd.to_datetime(doo_s) if doo_s else fy_start
        cl_s = attrs.loc[c, "closed"]
        closed = pd.to_datetime(cl_s) if cl_s else None
        proj_ytd = project_ytd(yty, fy_start, doo, asof, closed)
        out[c] = {
            "ytd_ly": yly, "ytd_ty": yty, "gd_ytd": _gd_frac(yty, yly),
            "mtd_ly": mly, "mtd_ty": mty, "gd_mtd": _gd_frac(mty, mly),
            "day": float(day.get(c, 0.0)), "month_ly": float(month_ly.get(c, 0.0)),
            "proj_mtd": project_mtd(mty, asof, doo, closed),
            "ly_full": float(ly_full.get(c, 0.0)), "proj_ytd": proj_ytd,
            "ttm": float(ttm.get(c, 0.0)),
        }
    return out


def brand_wise_gd_report(df: pd.DataFrame, asof=None):
    """BRAND_WISE_GD — GD figures grouped by PARENT company (alphabetical),
    store rows → 'PARENT Total' → 'Grand Total'. Returns (display_df, row_types)."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    metrics = _gd_store_metrics(df, asof)
    attrs = gd_store_attrs_dyn(df, asof)
    # Nothing traded this year in this selection — every store in it has
    # closed. Return the report's own empty shape so the tab can say so.
    if attrs.empty:
        return pd.DataFrame(columns=BRAND_GD_COLS), []

    def _store_row(a):
        m = metrics[int(a["code"])]
        return {
            "PARENT": a["parent"], "STORE NAME MAIN": a["store_name_main"],
            "LOCATION": a["location_main"], "NEW/OLD": a["new_old"],
            "CLOSED": a["closed"] if a["closed"] else "(blank)",
            "Sum of YTD_LY": m["ytd_ly"], "Sum of YTD_TY": m["ytd_ty"],
            "Sum of GD_YTD_%": m["gd_ytd"], "Sum of MTD_LY": m["mtd_ly"],
            "Sum of MTD_TY": m["mtd_ty"], "Sum of GD_MTD_%": m["gd_mtd"],
            "Sum of DAY SALE FIGURE": m["day"], "Sum of MONTH SALE LY": m["month_ly"],
            "Sum of PROJECTED MTD": m["proj_mtd"], "Sum of LY FULL SALES": m["ly_full"],
            "Sum of TTM SALES": m["ttm"],
            "Sum of PROJECTED YTD": m["proj_ytd"],
        }

    def _total_row(label, sub):
        d = {c: "" for c in BRAND_GD_COLS}
        d["PARENT"] = label
        for c in _BRAND_VALUE_COLS:
            d[c] = sub[c].sum()
        d["Sum of GD_YTD_%"] = _gd_frac(d["Sum of YTD_TY"], d["Sum of YTD_LY"])
        d["Sum of GD_MTD_%"] = _gd_frac(d["Sum of MTD_TY"], d["Sum of MTD_LY"])
        return d

    attrs = attrs.sort_values("brand_order")  # exact BRAND_WISE_GD sheet order
    rows, types, all_rows = [], [], []
    for parent, grp in attrs.groupby("parent", sort=False):
        srows = [_store_row(a) for _, a in grp.iterrows()]
        for sr in srows:
            rows.append(sr); types.append("store")
        sdf = pd.DataFrame(srows)
        all_rows.append(sdf)
        rows.append(_total_row(f"{parent} Total", sdf)); types.append("subtotal")
    gdf = pd.concat(all_rows, ignore_index=True)
    rows.append(_total_row("Grand Total", gdf)); types.append("grand")
    return pd.DataFrame(rows, columns=BRAND_GD_COLS), types


# --------------------------------------------------------------------------- #
# LOC_WISE_GD — same GD figures grouped by Location TL (geographic cluster).
# Column order differs from GD Sheet: DAY SALE FIGURE is last; carries STORE CODE.
# --------------------------------------------------------------------------- #
LOC_GD_COLS = [
    "Location TL", "STORE CODE", "NEW/OLD", "STORE NAME MAIN", "LOCATION",
    "Sum of YTD_LY", "Sum of YTD_TY", "Sum of GD_YTD_%", "Sum of MTD_LY",
    "Sum of MTD_TY", "Sum of GD_MTD_%", "Sum of MONTH SALE LY",
    "Sum of PROJECTED MTD", "Sum of LY FULL SALES", "Sum of PROJECTED YTD",
    "Sum of TTM SALES", "Sum of DAY SALE FIGURE",
]
_LOC_VALUE_COLS = ["Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY",
                   "Sum of MONTH SALE LY", "Sum of PROJECTED MTD", "Sum of LY FULL SALES",
                   "Sum of PROJECTED YTD", "Sum of TTM SALES", "Sum of DAY SALE FIGURE"]


def loc_wise_gd_report(df: pd.DataFrame, asof=None):
    """LOC_WISE_GD — GD figures grouped by Location TL (exact sheet order),
    store rows → 'Location TL Total' → 'Grand Total'."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    metrics = _gd_store_metrics(df, asof)
    attrs = gd_store_attrs_dyn(df, asof)
    # Nothing traded this year in this selection — every store in it has
    # closed. Return the report's own empty shape so the tab can say so.
    if attrs.empty:
        return pd.DataFrame(columns=LOC_GD_COLS), []

    def _store_row(a):
        c = int(a["code"])
        m = metrics[c]
        return {
            "Location TL": a["location_tl"], "STORE CODE": c, "NEW/OLD": a["new_old"],
            "STORE NAME MAIN": a["store_name_main"], "LOCATION": a["location_main"],
            "Sum of YTD_LY": m["ytd_ly"], "Sum of YTD_TY": m["ytd_ty"],
            "Sum of GD_YTD_%": m["gd_ytd"], "Sum of MTD_LY": m["mtd_ly"],
            "Sum of MTD_TY": m["mtd_ty"], "Sum of GD_MTD_%": m["gd_mtd"],
            "Sum of MONTH SALE LY": m["month_ly"], "Sum of PROJECTED MTD": m["proj_mtd"],
            "Sum of LY FULL SALES": m["ly_full"], "Sum of PROJECTED YTD": m["proj_ytd"],
            "Sum of TTM SALES": m["ttm"],
            "Sum of DAY SALE FIGURE": m["day"],
        }

    def _total_row(label, sub):
        d = {c: "" for c in LOC_GD_COLS}
        d["Location TL"] = label
        for c in _LOC_VALUE_COLS:
            d[c] = sub[c].sum()
        d["Sum of GD_YTD_%"] = _gd_frac(d["Sum of YTD_TY"], d["Sum of YTD_LY"])
        d["Sum of GD_MTD_%"] = _gd_frac(d["Sum of MTD_TY"], d["Sum of MTD_LY"])
        return d

    attrs = attrs.sort_values("loc_order")  # exact LOC_WISE_GD sheet order
    rows, types, all_rows = [], [], []
    for tl, grp in attrs.groupby("location_tl", sort=False):
        srows = [_store_row(a) for _, a in grp.iterrows()]
        for sr in srows:
            rows.append(sr); types.append("store")
        sdf = pd.DataFrame(srows)
        all_rows.append(sdf)
        rows.append(_total_row(f"{tl} Total", sdf)); types.append("subtotal")
    gdf = pd.concat(all_rows, ignore_index=True)
    rows.append(_total_row("Grand Total", gdf)); types.append("grand")
    return pd.DataFrame(rows, columns=LOC_GD_COLS), types


# --------------------------------------------------------------------------- #
# AVERAGE — store productivity (SBA/CA/operation days/AVG DAY SALE/PSFPD),
# grouped by PARENT. One row per store (no Manyavar/Mohey split), and a clean
# AVG DAY SALE = YTD_TY / operation days (the sheet's own formula is unreliable).
# --------------------------------------------------------------------------- #
AVG_COLS = [
    "PARENT", "STORE CODE", "STORE NAME MAIN", "LOCATION", "NEW/OLD", "SBA", "CA",
    "DOO", "CLOSED", "Sum of YTD_LY", "Sum of YTD_TY", "Sum of GD_YTD_%",
    "Average of OPERATION", "Sum of AVG DAY SALE", "Sum of AVG MONTH SALE",
    "Sum of PSFPD",
]


def average_report(df: pd.DataFrame, asof=None):
    """AVERAGE — per-store productivity grouped by PARENT. Operation days = days
    traded this FY; AVG DAY SALE = YTD_TY / operation days; AVG MONTH = ×30;
    PSFPD = AVG DAY SALE / CA. Returns (display_df, row_types)."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    metrics = _gd_store_metrics(df, asof)
    attrs = gd_store_attrs_dyn(df, asof)
    # Nothing traded this year in this selection — every store in it has
    # closed. Return the report's own empty shape so the tab can say so.
    if attrs.empty:
        return pd.DataFrame(columns=AVG_COLS), []
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    fy_start = pd.Timestamp(fy_year, 4, 1)

    def _op_days(a):
        doo = pd.to_datetime(a["doo"]) if a["doo"] else fy_start
        close = pd.to_datetime(a["closed"]) if a["closed"] else asof
        return max((min(asof, close) - max(fy_start, doo)).days + 1, 1)

    def _store_row(a):
        c = int(a["code"])
        m = metrics[c]
        op = _op_days(a)
        yty = m["ytd_ty"]
        ca = float(a["ca"]) if a["ca"] else 0.0
        ads = yty / op
        return {
            "PARENT": a["parent"], "STORE CODE": c, "STORE NAME MAIN": a["store_name_main"],
            "LOCATION": a["location_main"], "NEW/OLD": a["new_old"],
            "SBA": float(a["sba"]) if a["sba"] else 0.0, "CA": ca, "DOO": a["doo"],
            "CLOSED": a["closed"] if a["closed"] else "(blank)",
            "Sum of YTD_LY": m["ytd_ly"], "Sum of YTD_TY": yty,
            "Sum of GD_YTD_%": m["gd_ytd"], "Average of OPERATION": op,
            "Sum of AVG DAY SALE": ads, "Sum of AVG MONTH SALE": ads * 30,
            "Sum of PSFPD": (ads / ca) if ca else 0.0, "_op": op, "_ca": ca,
        }

    def _total_row(label, sdf):
        d = {c: "" for c in AVG_COLS}
        d["PARENT"] = label
        d["Sum of YTD_LY"] = sdf["Sum of YTD_LY"].sum()
        d["Sum of YTD_TY"] = sdf["Sum of YTD_TY"].sum()
        d["Sum of GD_YTD_%"] = _gd_frac(d["Sum of YTD_TY"], d["Sum of YTD_LY"])
        op_sum, ca_sum = sdf["_op"].sum(), sdf["_ca"].sum()
        d["Average of OPERATION"] = sdf["_op"].mean()
        ads = d["Sum of YTD_TY"] / op_sum if op_sum else 0.0
        d["Sum of AVG DAY SALE"] = ads
        d["Sum of AVG MONTH SALE"] = ads * 30
        d["Sum of PSFPD"] = (ads / ca_sum) if ca_sum else 0.0
        return d

    attrs = attrs.sort_values(["parent", "code"])
    rows, types, all_rows = [], [], []
    for parent, grp in attrs.groupby("parent", sort=True):
        srows = [_store_row(a) for _, a in grp.iterrows()]
        for sr in srows:
            rows.append(sr); types.append("store")
        sdf = pd.DataFrame(srows)
        all_rows.append(sdf)
        rows.append(_total_row(f"{parent} Total", sdf)); types.append("subtotal")
    gdf = pd.concat(all_rows, ignore_index=True)
    rows.append(_total_row("Grand Total", gdf)); types.append("grand")
    return pd.DataFrame(rows, columns=AVG_COLS), types
