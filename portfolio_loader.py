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

_DIR = os.path.dirname(__file__)
_MASTER_PATH = os.path.join(_DIR, "portfolio_store_master.csv")
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
        try:
            import requests
            resp = requests.get(
                url, headers={"Accept-Encoding": "gzip, deflate"}, timeout=120)
            resp.raise_for_status()
            return pd.read_csv(
                io.BytesIO(resp.content), dtype=str, keep_default_na=False)
        except Exception:
            return pd.read_csv(url, dtype=str, keep_default_na=False)
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
    # Day-first Indian dates; fall back to flexible parsing for any stragglers.
    dt = pd.to_datetime(df[C_DATE], format="%d/%m/%Y", errors="coerce")
    miss = dt.isna()
    if miss.any():
        dt.loc[miss] = pd.to_datetime(
            df.loc[miss, C_DATE], dayfirst=True, errors="coerce")
    df["date"] = dt
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
    portfolio sheet, their YTD_LY is simply 0 and their YoY reads as 'new'."""
    return clean(_read_raw())


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
    start = _anchored_start(df, kind, asof)
    start.index = df.index
    prior_start = start - pd.DateOffset(years=1)
    cur = df[(df["date"] >= start) & (df["date"] <= asof)]

    # Per-store last-year end. A store is "closed" if it made no sale in the as-of
    # month; its last year is capped to the END of the month it last traded
    # (shifted back a year) — matching the sheet, e.g. a store that shut on 30 Apr
    # compares against the full last April. Open stores get the full window to
    # as-of − 1 year.
    closed = ty_end < asof.replace(day=1)
    closed_end = (ty_end + pd.offsets.MonthEnd(0)) - pd.DateOffset(years=1)
    ly_end_by_code = closed_end.where(closed, asof - pd.DateOffset(years=1))
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

    all_rows = []
    for region, grp in present.groupby("region", sort=False):
        region_rows = [_store_row(r) for _, r in grp.iterrows()]
        for sr in region_rows:
            rows.append(sr); types.append("store")
        region_df = pd.DataFrame(region_rows)
        all_rows.append(region_df)
        rows.append(_total_row(f"{region} Total", region_df))
        types.append("subtotal")

    grand = pd.concat(all_rows, ignore_index=True)
    rows.append(_total_row("Grand Total", grand))
    types.append("grand")
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
