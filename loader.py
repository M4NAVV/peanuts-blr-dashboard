"""
Data loader + KPI helpers for the Peanuts (Manyavar) Bengaluru sales dashboard.

Single source of truth for reading and cleaning the sales export, whether it
comes from a published Google Sheet (hosted / production) or a local Excel file
(local development). Everything downstream reads a clean, typed DataFrame from
`load_data()`.

The cleaning is deliberately defensive because the same export gets re-imported
into Google Sheets every day, which can:
  - append a "Grand Total" footer row,
  - reformat numbers with thousands separators ("17,536"),
  - reformat / reparse the Bill Date column.
"""

from __future__ import annotations

import io
import os
from datetime import datetime

import pandas as pd

# Column names as they appear in the raw Tableau export.
COL_STORE = "SHORT_NAME"
COL_DATE = "Bill Date"
COL_BILL = "Bill No"
COL_MOBILE = "CUSTOMER_MOBILE"
COL_SALESPERSON = "Name (Dm Salesperson)"
COL_DIVISION = "Division"
COL_SECTION = "Section"
COL_MWC = "Men/Women/Child"
COL_DEPARTMENT = "Department"
COL_SIZE = "Size"
COL_COLOR = "CATEGORY2"
COL_STYLE = "CATEGORY1"
COL_AMOUNT = "Bill Amount"
COL_QTY = "Bill Quantity"
COL_PROMO = "Promotion Amount"

NUMERIC_COLS = [COL_AMOUNT, COL_QTY, COL_PROMO]

# Cleaned, display-friendly store name (derived in clean()).
COL_STORE_LABEL = "store"

# Store-master attributes joined onto the data (in _enrich()).
COL_REGION = "region"
COL_STATE = "state"
COL_CITY = "city"
COL_FORMAT = "store_format"

# Brand, derived from the Division name (in clean()).
COL_BRAND = "brand"


def _brand_of(division) -> str:
    d = str(division).upper()
    if "MOHEY" in d:
        return "Mohey"
    if "TWAMEV" in d:
        return "Twamev"
    if d == "MEBAZ":
        return "Mebaz"
    if d == "MANTHAN":
        return "Manthan"
    if d in ("MANU", "DEFUNCT NEW", "OUTPUT ITEM", "NAN", ""):
        return "Other"
    return "Manyavar"

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
# Prefer the full multi-store export; fall back to the single-store file.
_LOCAL_CANDIDATES = ["fulldata.xlsx", "sales.xlsx"]


def _local_excel() -> str | None:
    for name in _LOCAL_CANDIDATES:
        p = os.path.join(_DATA_DIR, name)
        if os.path.exists(p):
            return p
    return None


def _read_raw() -> pd.DataFrame:
    """Read the raw sheet from the Google Sheet CSV URL if configured, else the
    local Excel file. Kept separate from cleaning so the source can change
    without touching the cleaning logic."""
    url = _sheet_url()
    if url:
        # Published Google Sheet -> CSV. Read as strings; cleaning handles types.
        # Fetch with gzip: Google serves the export compressed, which roughly
        # halves transfer time vs pandas' plain urllib read (~10s vs ~20s for
        # our ~265k-row sheet). Fall back to a plain read on any error.
        try:
            import io
            import requests

            resp = requests.get(
                url, headers={"Accept-Encoding": "gzip, deflate"}, timeout=120)
            resp.raise_for_status()
            return pd.read_csv(
                io.BytesIO(resp.content), dtype=str, keep_default_na=False)
        except Exception:
            return pd.read_csv(url, dtype=str, keep_default_na=False)
    local = _local_excel()
    if local:
        return pd.read_excel(local, sheet_name=0, dtype=str)
    raise FileNotFoundError(
        "No data source found. Set SHEET_CSV_URL in Streamlit secrets, or place "
        f"the export at {os.path.join(_DATA_DIR, _LOCAL_CANDIDATES[0])}"
    )


def _sheet_url() -> str | None:
    """Read the published-sheet CSV URL from Streamlit secrets or env var.
    Returns None when running locally without it (falls back to Excel)."""
    # Env var takes precedence (handy for local testing against the live sheet).
    if os.environ.get("SHEET_CSV_URL"):
        return os.environ["SHEET_CSV_URL"]
    try:
        import streamlit as st

        return st.secrets.get("SHEET_CSV_URL")  # type: ignore[no-any-return]
    except Exception:
        return None


def _to_number(series: pd.Series) -> pd.Series:
    """Coerce a possibly comma/currency-formatted string column to float."""
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("₹", "", regex=False)  # rupee sign
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _parse_dates(series: pd.Series) -> pd.Series:
    """Parse Bill Date robustly. The raw export is US-style M/D/YYYY, but once the
    file has passed through Google Sheets it may come back ISO (YYYY-MM-DD) or in
    another locale. Try the known format first, then fall back to inference."""
    s = series.astype(str).str.strip()
    # Known raw format from the Tableau export.
    dt = pd.to_datetime(s, format="%m/%d/%Y", errors="coerce")
    # Fill any that failed (e.g. Sheets reformatted them) with flexible parsing.
    missing = dt.isna()
    if missing.any():
        dt.loc[missing] = pd.to_datetime(s[missing], errors="coerce")
    return dt


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Turn a raw export into a clean, typed, analysis-ready DataFrame."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Drop the "Grand Total" footer row (and any fully blank rows).
    if "Sr No" in df.columns:
        df = df[df["Sr No"].astype(str).str.strip().str.lower() != "grand total"]
    if COL_STORE in df.columns:
        df = df[df[COL_STORE].astype(str).str.strip().str.lower() != "total"]

    for c in NUMERIC_COLS:
        if c in df.columns:
            df[c] = _to_number(df[c])

    df["date"] = _parse_dates(df[COL_DATE])
    df = df[df["date"].notna()].copy()

    # Drop rows with no monetary value (defensive against stray blank lines).
    df = df[df[COL_AMOUNT].notna()].copy()

    # Derived calendar fields for trend charts.
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["month_label"] = df["date"].dt.strftime("%b %Y")
    df["weekday"] = df["date"].dt.day_name()
    df["date_only"] = df["date"].dt.date

    # Net sales after promotion (discount). Promotion is the discount amount.
    df[COL_PROMO] = df[COL_PROMO].fillna(0)
    df["net_amount"] = df[COL_AMOUNT] - df[COL_PROMO]

    # Brand, derived from Division (Manyavar / Mohey / Twamev / …).
    df[COL_BRAND] = df[COL_DIVISION].map(_brand_of)

    # Blank mobiles -> NA so unique-customer counts don't lump them as one.
    df["mobile_clean"] = (
        df[COL_MOBILE].astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA})
    )

    # Display-friendly store name: drop the "Peanuts [Retail] -" prefix.
    df[COL_STORE_LABEL] = (
        df[COL_STORE].astype(str)
        .str.replace(r"(?i)^\s*peanuts\s*(?:retail)?\s*[-–]?\s*", "", regex=True)
        .str.strip()
    )

    # Indian fiscal calendar (Apr–Mar). FY26 = Apr 2025 → Mar 2026.
    fy_start_year = df["date"].dt.year.where(df["date"].dt.month >= 4,
                                             df["date"].dt.year - 1)
    df["fy_start_year"] = fy_start_year
    df["fy"] = "FY" + ((fy_start_year + 1) % 100).astype(int).astype(str).str.zfill(2)
    df["fy_month_idx"] = (df["date"].dt.month - 4) % 12 + 1  # Apr=1 … Mar=12
    df["fy_month"] = df["date"].dt.strftime("%b")

    return df.reset_index(drop=True)


def load_data() -> pd.DataFrame:
    """Public entry point. Streamlit caching is applied in app.py."""
    df = clean(_read_raw())
    df = _apply_takeover_filter(df)
    df = _enrich(df)
    return df


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Join store-master attributes (region / state / city / format) onto rows,
    so they become filterable dimensions."""
    m = load_store_master().set_index("tableau_name")
    for src, dst in [("region", COL_REGION), ("state", COL_STATE),
                     ("city", COL_CITY), ("format", COL_FORMAT)]:
        if src in m.columns:
            df[dst] = df[COL_STORE_LABEL].map(m[src])
    return df


def _apply_takeover_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows before each store's takeover date — pre-ownership sales from the
    previous operator don't count. Stores without a mapped date keep all rows."""
    tk = takeover_map()
    start = df[COL_STORE_LABEL].map(tk)
    keep = start.isna() | (df["date"] >= start)
    return df[keep].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# KPI helpers — all operate on the cleaned frame.
# --------------------------------------------------------------------------- #

def headline_kpis(df: pd.DataFrame) -> dict:
    """Top-line KPIs for the overview cards."""
    total_sales = df[COL_AMOUNT].sum()
    total_units = df[COL_QTY].sum()
    bills = df[COL_BILL].nunique()
    customers = df[COL_MOBILE].replace("", pd.NA).nunique()
    discount = df[COL_PROMO].sum()

    per_bill = df.groupby(COL_BILL).agg(
        amt=(COL_AMOUNT, "sum"), qty=(COL_QTY, "sum")
    )
    atv = per_bill["amt"].mean() if len(per_bill) else 0
    upt = per_bill["qty"].mean() if len(per_bill) else 0
    asp = (total_sales / total_units) if total_units else 0

    cust_bills = (
        df[df[COL_MOBILE].replace("", pd.NA).notna()]
        .groupby(COL_MOBILE)[COL_BILL]
        .nunique()
    )
    repeat_rate = (cust_bills > 1).mean() * 100 if len(cust_bills) else 0

    return {
        "total_sales": total_sales,
        "total_units": int(total_units),
        "bills": int(bills),
        "customers": int(customers),
        "discount": discount,
        "atv": atv,
        "upt": upt,
        "asp": asp,
        "repeat_rate": repeat_rate,
    }


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Sales / bills / units by calendar month, chronologically ordered."""
    g = (
        df.groupby("month")
        .agg(
            sales=(COL_AMOUNT, "sum"),
            bills=(COL_BILL, "nunique"),
            units=(COL_QTY, "sum"),
            discount=(COL_PROMO, "sum"),
        )
        .reset_index()
        .sort_values("month")
    )
    g["atv"] = g["sales"] / g["bills"].where(g["bills"] != 0)
    g["month_label"] = g["month"].dt.strftime("%b %Y")
    return g


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.groupby("date")
        .agg(sales=(COL_AMOUNT, "sum"), bills=(COL_BILL, "nunique"), units=(COL_QTY, "sum"))
        .reset_index()
        .sort_values("date")
    )
    return g


def dimension_summary(df: pd.DataFrame, col: str, top: int | None = None) -> pd.DataFrame:
    """Sales / units / bills grouped by any categorical column."""
    g = (
        df.groupby(col)
        .agg(
            sales=(COL_AMOUNT, "sum"),
            units=(COL_QTY, "sum"),
            bills=(COL_BILL, "nunique"),
        )
        .reset_index()
        .sort_values("sales", ascending=False)
    )
    if top:
        g = g.head(top)
    return g


def salesperson_summary(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.groupby(COL_SALESPERSON)
        .agg(
            sales=(COL_AMOUNT, "sum"),
            units=(COL_QTY, "sum"),
            bills=(COL_BILL, "nunique"),
        )
        .reset_index()
        .sort_values("sales", ascending=False)
    )
    g["atv"] = g["sales"] / g["bills"].where(g["bills"] != 0)
    return g


def store_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-store KPI table (sales, bills, units, ATV, UPT, ASP), best first."""
    g = (
        df.groupby(COL_STORE_LABEL)
        .agg(
            sales=(COL_AMOUNT, "sum"),
            units=(COL_QTY, "sum"),
            bills=(COL_BILL, "nunique"),
            customers=("mobile_clean", "nunique"),
        )
        .reset_index()
        .sort_values("sales", ascending=False)
    )
    g["atv"] = g["sales"] / g["bills"].where(g["bills"] != 0)
    g["upt"] = g["units"] / g["bills"].where(g["bills"] != 0)
    g["asp"] = g["sales"] / g["units"].where(g["units"] != 0)

    # Carpet area -> sales per sq ft (retail productivity).
    m = load_store_master()
    if "ca" in m.columns:
        areas = dict(zip(m["tableau_name"], pd.to_numeric(m["ca"], errors="coerce")))
        g["carpet_area"] = g[COL_STORE_LABEL].map(areas)
        g["sales_psf"] = g["sales"] / g["carpet_area"].where(g["carpet_area"] > 0)
    return g


def customer_stats(df: pd.DataFrame) -> dict:
    """New vs repeat split at the bill level, plus a monthly repeat trend."""
    valid = df[df[COL_MOBILE].replace("", pd.NA).notna()].copy()
    if valid.empty:
        return {"new": 0, "repeat": 0, "top": pd.DataFrame(), "trend": pd.DataFrame()}

    # First purchase date per customer.
    first = valid.groupby(COL_MOBILE)["date"].min().rename("first_date")
    bills = (
        valid.groupby([COL_MOBILE, COL_BILL])
        .agg(date=("date", "min"), amt=(COL_AMOUNT, "sum"))
        .reset_index()
        .merge(first, on=COL_MOBILE)
    )
    bills["is_repeat"] = bills["date"] > bills["first_date"]

    top = (
        valid.groupby(COL_MOBILE)
        .agg(spend=(COL_AMOUNT, "sum"), visits=(COL_BILL, "nunique"))
        .reset_index()
        .sort_values("spend", ascending=False)
        .head(20)
    )

    bills["month"] = bills["date"].dt.to_period("M").dt.to_timestamp()
    trend = (
        bills.groupby("month")["is_repeat"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"mean": "repeat_share", "count": "bills"})
    )
    trend["repeat_share"] *= 100
    trend["month_label"] = trend["month"].dt.strftime("%b %Y")

    return {
        "new": int((~bills["is_repeat"]).sum()),
        "repeat": int(bills["is_repeat"].sum()),
        "top": top,
        "trend": trend,
    }


def data_freshness(df: pd.DataFrame) -> dict:
    return {
        "min_date": df["date"].min(),
        "max_date": df["date"].max(),
        "rows": len(df),
    }


# --------------------------------------------------------------------------- #
# Generic metric + dimension engine (powers the "Build your view" tab)
# --------------------------------------------------------------------------- #

# Friendly metric name -> internal key. All metrics are derivable from six base
# aggregates, so any dimension can be sliced by any metric.
METRICS: dict[str, str] = {
    "Sales (₹)": "sales",
    "Net Sales after discount (₹)": "net_sales",
    "Units": "units",
    "Bills": "bills",
    "Unique Customers": "customers",
    "Active Stores": "stores",
    "Discount (₹)": "discount",
    "Avg Bill Value / ATV (₹)": "atv",
    "Units per Bill / UPT": "upt",
    "Avg Selling Price / ASP (₹)": "asp",
    "Discount %": "disc_pct",
}

# Which metrics are rupee values (for formatting in the UI).
MONEY_METRICS = {"sales", "net_sales", "discount", "atv", "asp"}

# Friendly categorical dimension name -> column.
CAT_DIMS: dict[str, str] = {
    "Store": COL_STORE_LABEL,
    "Region": COL_REGION,
    "Brand": COL_BRAND,
    "Division": COL_DIVISION,
    "Section": COL_SECTION,
    "Department": COL_DEPARTMENT,
    "Men/Women/Child": COL_MWC,
    "Size": COL_SIZE,
    "Color": COL_COLOR,
    "Style code": COL_STYLE,
    "Salesperson": COL_SALESPERSON,
}

# Time-based dimensions (granularity), coarse to fine handled internally.
# "Financial Year" and "Fiscal Month" enable YoY breakdowns in the builder.
TIME_DIMS = ["Day", "Week", "Month", "Quarter", "Year",
             "Financial Year", "Fiscal Month", "Weekday"]

_FY_MONTH_ORDER = ["Apr", "May", "Jun", "Jul", "Aug", "Sep",
                   "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]

# Everything selectable as a "group by".
ALL_DIMS = TIME_DIMS + list(CAT_DIMS.keys())

_WEEKDAY_ORDER = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]


def _period_label(ts: pd.Timestamp, dim: str) -> str:
    if dim == "Day":
        return ts.strftime("%d %b %Y")
    if dim == "Week":
        return "w/o " + ts.strftime("%d %b %y")
    if dim == "Month":
        return ts.strftime("%b %Y")
    if dim == "Quarter":
        return f"Q{ts.quarter} {ts.year}"
    if dim == "Year":
        return ts.strftime("%Y")
    return ts.strftime("%d %b %Y")


def _dim_column(work: pd.DataFrame, dim: str, name: str) -> tuple[str, list | None]:
    """Add a label column `name` to `work` for dimension `dim`.
    Returns the column name and an explicit category order (or None)."""
    if dim in CAT_DIMS:
        work[name] = work[CAT_DIMS[dim]].fillna("(blank)").astype(str)
        return name, None

    if dim == "Weekday":
        work[name] = work["date"].dt.day_name()
        return name, _WEEKDAY_ORDER

    if dim == "Financial Year":
        work[name] = work["fy"]
        order = (
            work[["fy_start_year", "fy"]].drop_duplicates()
            .sort_values("fy_start_year")["fy"].tolist()
        )
        return name, order

    if dim == "Fiscal Month":
        work[name] = work["fy_month"]
        present = set(work[name].unique())
        return name, [m for m in _FY_MONTH_ORDER if m in present]

    freq = {"Day": "D", "Week": "W", "Month": "M", "Quarter": "Q", "Year": "Y"}[dim]
    starts = work["date"].dt.to_period(freq).dt.start_time
    work["_ts_" + name] = starts
    work[name] = starts.map(lambda t: _period_label(t, dim))
    order = (
        work[["_ts_" + name, name]]
        .drop_duplicates()
        .sort_values("_ts_" + name)[name]
        .tolist()
    )
    return name, order


def _agg_base(work: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return (
        work.groupby(group_cols, dropna=False)
        .agg(
            sales=(COL_AMOUNT, "sum"),
            net_sales=("net_amount", "sum"),
            units=(COL_QTY, "sum"),
            bills=(COL_BILL, "nunique"),
            customers=("mobile_clean", "nunique"),
            stores=(COL_STORE_LABEL, "nunique"),
            discount=(COL_PROMO, "sum"),
        )
        .reset_index()
    )


def _derive_metric(base: pd.DataFrame, metric_key: str) -> pd.DataFrame:
    b = base.copy()
    if metric_key == "atv":
        b["value"] = b["sales"] / b["bills"].where(b["bills"] != 0)
    elif metric_key == "upt":
        b["value"] = b["units"] / b["bills"].where(b["bills"] != 0)
    elif metric_key == "asp":
        b["value"] = b["sales"] / b["units"].where(b["units"] != 0)
    elif metric_key == "disc_pct":
        b["value"] = b["discount"] / b["sales"].where(b["sales"] != 0) * 100
    else:
        b["value"] = b[metric_key]
    return b


# --------------------------------------------------------------------------- #
# Executive YoY metrics (MTD / QTD / YTD vs same period last year)
# --------------------------------------------------------------------------- #

def as_of(df: pd.DataFrame) -> pd.Timestamp:
    """Latest date present — the reference point for all to-date windows."""
    return df["date"].max()


def _sply(start: pd.Timestamp, end: pd.Timestamp):
    """Same period last year: shift both bounds back exactly one year."""
    off = pd.DateOffset(years=1)
    return start - off, end - off


def _window_metrics(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    sub = df[(df["date"] >= start) & (df["date"] <= end)]
    sales = sub[COL_AMOUNT].sum()
    bills = sub[COL_BILL].nunique()
    units = sub[COL_QTY].sum()
    return {
        "sales": sales,
        "bills": int(bills),
        "units": int(units),
        "atv": sales / bills if bills else 0.0,
    }


def window_yoy(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Current window vs the same period last year, with growth % per metric."""
    cur = _window_metrics(df, start, end)
    ps, pe = _sply(start, end)
    prior = _window_metrics(df, ps, pe)
    growth = {
        k: ((cur[k] - prior[k]) / prior[k] * 100 if prior[k] else None)
        for k in cur
    }
    return {
        "cur": cur, "prior": prior, "growth": growth,
        "cur_window": (start, end), "prior_window": (ps, pe),
    }


def standard_windows(df: pd.DataFrame, asof=None) -> dict[str, tuple]:
    """MTD / QTD / YTD (fiscal) and the last completed month, as (start, end).
    `asof` defaults to the latest data date; pass a date to report as of it."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    mtd = (asof.replace(day=1), asof)

    q_start_month = {4: 4, 5: 4, 6: 4, 7: 7, 8: 7, 9: 7,
                     10: 10, 11: 10, 12: 10, 1: 1, 2: 1, 3: 1}[asof.month]
    qtd = (pd.Timestamp(asof.year, q_start_month, 1), asof)

    fy_start_year = asof.year if asof.month >= 4 else asof.year - 1
    ytd = (pd.Timestamp(fy_start_year, 4, 1), asof)

    first_of_month = asof.replace(day=1)
    last_month_end = first_of_month - pd.Timedelta(days=1)
    last_month = (last_month_end.replace(day=1), last_month_end)

    return {"MTD": mtd, "QTD": qtd, "YTD": ytd, "Last month": last_month}


def store_yoy(df: pd.DataFrame, kind: str = "YTD", asof=None) -> pd.DataFrame:
    """Per-store sales YoY using per-store takeover-anchored windows + growth %."""
    cur_f, pri_f = report_frames(df, kind, asof=asof)
    cur = cur_f.groupby(COL_STORE_LABEL)[COL_AMOUNT].sum().rename("cur")
    pri = pri_f.groupby(COL_STORE_LABEL)[COL_AMOUNT].sum().rename("prior")
    m = pd.concat([cur, pri], axis=1).fillna(0.0).reset_index()
    m["growth"] = m.apply(
        lambda r: ((r["cur"] - r["prior"]) / r["prior"] * 100)
        if r["prior"] > 0 else None, axis=1,
    )
    return m.sort_values("cur", ascending=False)


def degrowth_report(df: pd.DataFrame, asof=None, kind: str = "YTD") -> pd.DataFrame:
    """Stores in `kind` (MTD/YTD) degrowth — This Year < Last Year — worst first,
    with the ₹ shortfall and degrowth %. Respects whatever `df` is filtered to."""
    sy = store_yoy(df, kind, asof=asof)
    m = load_store_master()[["tableau_name", "code", "location", "region"]]
    out = sy.merge(m, left_on=COL_STORE_LABEL, right_on="tableau_name", how="left")
    out = out[out["growth"].notna() & (out["growth"] < 0)].copy()
    out["shortfall"] = out["cur"] - out["prior"]
    out["code"] = pd.to_numeric(out["code"], errors="coerce")
    out = out.sort_values("code").reset_index(drop=True)
    return out[["region", "code", "location", "prior", "cur",
                "shortfall", "growth"]]


def movement_summary(df: pd.DataFrame, asof=None) -> dict:
    """Store-count and value movement (growing vs degrowing) for MTD and YTD,
    year-on-year. Respects whatever `df` is filtered to and the `asof` date."""
    master_names = set(load_store_master()["tableau_name"])
    present = [s for s in df[COL_STORE_LABEL].dropna().unique() if s in master_names]
    res = {}
    for kind in ("MTD", "YTD"):
        cur_f, pri_f = report_frames(df, kind, asof=asof)
        ty = (cur_f.groupby(COL_STORE_LABEL)[COL_AMOUNT].sum()
              .reindex(present, fill_value=0.0))
        ly = (pri_f.groupby(COL_STORE_LABEL)[COL_AMOUNT].sum()
              .reindex(present, fill_value=0.0))
        diff = ty - ly
        res[kind] = {
            "total": len(present),
            "growing": int((diff > 0).sum()),
            "degrowing": int((diff < 0).sum()),
            "growth_value": float(diff[diff > 0].sum()),
            "degrowth_value": float(diff[diff < 0].sum()),
            "net_value": float(diff.sum()),
        }
    return res


# --------------------------------------------------------------------------- #
# Region × store MTD/YTD YoY report (the executive table)
# --------------------------------------------------------------------------- #

_MASTER_PATH = os.path.join(os.path.dirname(__file__), "store_master.csv")
_REGION_ORDER = ["East & NE", "South"]

REPORT_COLS = [
    "Region", "DATE", "STORE CODE", "LOCATION",
    "MTD LY", "MTD TY", "GD MTD Value", "GD MTD %", "Day Sales",
    "YTD LY", "YTD TY", "GD YTD Value", "GD YTD %",
]


def load_store_master() -> pd.DataFrame:
    m = pd.read_csv(_MASTER_PATH, dtype={"code": str})
    m["tableau_name"] = m["tableau_name"].astype(str).str.strip()
    if "takeover_date" in m.columns:
        m["takeover_date"] = pd.to_datetime(m["takeover_date"], errors="coerce")
    return m


def takeover_map() -> dict:
    """store label -> takeover Timestamp (each store's reporting-year anchor)."""
    m = load_store_master()
    if "takeover_date" not in m.columns:
        return {}
    return dict(zip(m["tableau_name"], m["takeover_date"]))


def _anchor_md(df: pd.DataFrame, anchor_takeover: bool = True):
    """Per-row (month, day) of each store's window start. With `anchor_takeover`
    (default) that's the store's takeover date; otherwise it's a plain fiscal-year
    start (1 Apr) for every store — which is how the monthly source sheet counts."""
    if not anchor_takeover:
        return (pd.Series(4, index=df.index), pd.Series(1, index=df.index))
    tk = takeover_map()
    md = {s: ((d.month, d.day) if pd.notna(d) else (4, 1)) for s, d in tk.items()}
    m = df[COL_STORE_LABEL].map(lambda s: md.get(s, (4, 1))[0]).astype(int)
    d = df[COL_STORE_LABEL].map(lambda s: md.get(s, (4, 1))[1]).astype(int)
    return m, d


def report_frames(df: pd.DataFrame, kind: str, asof=None, anchor_takeover: bool = True):
    """Current & same-period-last-year frames for kind in {MTD, YTD}. Each store's
    window is anchored to its takeover date (so TY and LY line up); pass
    `anchor_takeover=False` to use a plain 1-Apr fiscal start instead (matches the
    monthly review sheet). `asof` (the to-date reference) defaults to latest data."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    m, d = _anchor_md(df, anchor_takeover=anchor_takeover)

    if kind == "YTD":
        cur_start = pd.to_datetime(pd.DataFrame({"year": fy_year, "month": m, "day": d}))
    elif kind == "MTD":
        base = pd.to_datetime(pd.DataFrame(
            {"year": asof.year, "month": asof.month, "day": 1}, index=df.index))
        anchored = pd.to_datetime(pd.DataFrame(
            {"year": asof.year, "month": m, "day": d}))
        # If the takeover falls inside the current month, start from it.
        in_month = (m == asof.month) & (anchored > base)
        cur_start = base.mask(in_month, anchored)
    else:
        raise ValueError(kind)

    cur_start.index = df.index
    prior_start = cur_start - pd.DateOffset(years=1)
    cur_end = asof
    prior_end = asof - pd.DateOffset(years=1)
    cur = df[(df["date"] >= cur_start) & (df["date"] <= cur_end)]
    prior = df[(df["date"] >= prior_start) & (df["date"] <= prior_end)]
    return cur, prior


def _frame_metrics(f: pd.DataFrame) -> dict:
    sales = f[COL_AMOUNT].sum()
    bills = f[COL_BILL].nunique()
    units = f[COL_QTY].sum()
    return {"sales": sales, "bills": int(bills), "units": int(units),
            "atv": sales / bills if bills else 0.0}


def window_yoy_takeover(df: pd.DataFrame, kind: str, asof=None) -> dict:
    """YoY for MTD/YTD using per-store takeover-anchored windows (for exec cards)."""
    cur, prior = report_frames(df, kind, asof=asof)
    c, p = _frame_metrics(cur), _frame_metrics(prior)
    growth = {k: ((c[k] - p[k]) / p[k] * 100 if p[k] else None) for k in c}
    def _rng(f):
        return (f["date"].min(), f["date"].max()) if len(f) else (None, None)
    return {"cur": c, "prior": p, "growth": growth,
            "cur_window": _rng(cur), "prior_window": _rng(prior)}


def _store_window_sales(df, start, end) -> pd.Series:
    return (df[(df["date"] >= start) & (df["date"] <= end)]
            .groupby(COL_STORE_LABEL)[COL_AMOUNT].sum())


def _growth_pct(ty: float, ly: float):
    return ((ty - ly) / ly * 100) if ly else None


def region_store_report(df: pd.DataFrame, asof=None):
    """Region-grouped, store-wise MTD/YTD year-on-year table with subtotals and
    a grand total. Returns (display_df, row_types) where row_types marks each row
    as 'store' | 'subtotal' | 'grand' for styling. `asof` = the to-date reference
    (defaults to the latest data date)."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    mtd_cur, mtd_pri = report_frames(df, "MTD", asof=asof)
    ytd_cur, ytd_pri = report_frames(df, "YTD", asof=asof)
    g = lambda f: f.groupby(COL_STORE_LABEL)[COL_AMOUNT].sum()
    mtd_ty, mtd_ly = g(mtd_cur), g(mtd_pri)
    ytd_ty, ytd_ly = g(ytd_cur), g(ytd_pri)
    day_ty = g(df[df["date"] == asof])   # sales on the as-of day
    date_str = asof.strftime("%d-%m-%Y")

    master = load_store_master()
    # Only show stores that survive the current filters (region/store/brand/…).
    present = set(df[COL_STORE_LABEL].dropna().unique())
    master = master[master["tableau_name"].isin(present)]
    master["_rord"] = master["region"].map(
        {k: i for i, k in enumerate(_REGION_ORDER)}).fillna(99)
    master["_code_num"] = pd.to_numeric(master["code"], errors="coerce")
    master = master.sort_values(["_rord", "_code_num"])

    if master.empty:
        return pd.DataFrame(columns=REPORT_COLS), []

    rows, types = [], []

    def _store_row(region, code, loc, day, mly, mty, yly, yty):
        return {
            "Region": region, "DATE": date_str, "STORE CODE": code, "LOCATION": loc,
            "Day Sales": day, "MTD LY": mly, "MTD TY": mty,
            "GD MTD Value": mty - mly, "GD MTD %": _growth_pct(mty, mly),
            "YTD LY": yly, "YTD TY": yty,
            "GD YTD Value": yty - yly, "GD YTD %": _growth_pct(yty, yly),
        }

    def _total_row(label, sub):
        mly, mty = sub["MTD LY"].sum(), sub["MTD TY"].sum()
        yly, yty = sub["YTD LY"].sum(), sub["YTD TY"].sum()
        return {
            "Region": label, "DATE": "", "STORE CODE": "", "LOCATION": "",
            "Day Sales": sub["Day Sales"].sum(), "MTD LY": mly, "MTD TY": mty,
            "GD MTD Value": mty - mly, "GD MTD %": _growth_pct(mty, mly),
            "YTD LY": yly, "YTD TY": yty,
            "GD YTD Value": yty - yly, "GD YTD %": _growth_pct(yty, yly),
        }

    all_store_rows = []
    for region, grp in master.groupby("region", sort=False):
        region_rows = []
        for _, r in grp.iterrows():
            name = r["tableau_name"]
            sr = _store_row(
                region, r["code"], r["location"], float(day_ty.get(name, 0.0)),
                float(mtd_ly.get(name, 0.0)), float(mtd_ty.get(name, 0.0)),
                float(ytd_ly.get(name, 0.0)), float(ytd_ty.get(name, 0.0)),
            )
            region_rows.append(sr)
            rows.append(sr)
            types.append("store")
        region_df = pd.DataFrame(region_rows)
        all_store_rows.append(region_df)
        rows.append(_total_row(f"{region} Total", region_df))
        types.append("subtotal")

    grand = pd.concat(all_store_rows, ignore_index=True)
    rows.append(_total_row("Grand Total", grand))
    types.append("grand")

    return pd.DataFrame(rows, columns=REPORT_COLS), types


def all_scalar_kpis(df: pd.DataFrame) -> dict[str, tuple[float, bool]]:
    """Every metric as a single scalar over `df`, for the selectable KPI cards.
    Returns {label: (value, is_money)}."""
    sales = df[COL_AMOUNT].sum()
    net = df["net_amount"].sum()
    units = df[COL_QTY].sum()
    bills = df[COL_BILL].nunique()
    customers = df["mobile_clean"].nunique()
    stores = df[COL_STORE_LABEL].nunique()
    discount = df[COL_PROMO].sum()
    vals = {
        "sales": sales,
        "net_sales": net,
        "units": units,
        "bills": bills,
        "customers": customers,
        "stores": stores,
        "discount": discount,
        "atv": sales / bills if bills else 0,
        "upt": units / bills if bills else 0,
        "asp": sales / units if units else 0,
        "disc_pct": (discount / sales * 100) if sales else 0,
    }
    return {
        label: (vals[key], key in MONEY_METRICS)
        for label, key in METRICS.items()
    }


def build_view(
    df: pd.DataFrame,
    metric_label: str,
    group_dim: str,
    split_dim: str | None = None,
    top: int | None = None,
) -> dict:
    """Aggregate `metric_label` by `group_dim` (and optional `split_dim`).

    Returns a dict with the tidy result frame plus the column names and the
    category order, so the UI can render any chart type consistently."""
    metric_key = METRICS[metric_label]
    work = df.copy()

    gcol, gorder = _dim_column(work, group_dim, "_g")
    group_cols = [gcol]
    scol = None
    if split_dim and split_dim not in ("(none)", None):
        scol, _ = _dim_column(work, split_dim, "_s")
        group_cols.append(scol)

    base = _agg_base(work, group_cols)
    res = _derive_metric(base, metric_key)

    # For categorical group dims, order by the metric and apply Top-N.
    if gorder is None:
        totals = (
            res.groupby(gcol)["value"].sum().sort_values(ascending=False).index.tolist()
        )
        gorder = totals[: top] if top else totals
        res = res[res[gcol].isin(gorder)]
    # Time dims keep chronological order (already in gorder); no Top-N.

    return {
        "data": res[[c for c in [gcol, scol, "value"] if c]].rename(
            columns={gcol: "group", scol: "split"} if scol else {gcol: "group"}
        ),
        "group_dim": group_dim,
        "split_dim": split_dim if scol else None,
        "metric": metric_label,
        "metric_key": metric_key,
        "order": gorder,
        "is_money": metric_key in MONEY_METRICS,
    }


# --------------------------------------------------------------------------- #
# Gender-wise & Brand-wise Growth/Degrowth + Gender contribution %
# (FY YoY, takeover-anchored — mirrors the "GROWTH DEGROWTH SHEET" tabs)
# --------------------------------------------------------------------------- #
GENDER_ORDER = ["MEN", "WOMEN"]
BRAND_ORDER = ["Manyavar", "Mohey", "Twamev", "Mebaz", "Manthan", "Other"]


def brand_gender(df: pd.DataFrame) -> pd.Series:
    """Source-sheet gender: classify each line by its BRAND-LINE, not the
    product Men/Women/Child category. WOMEN = Mohey* / Twamev-Women / Mebaz;
    everything else (Manyavar incl. its kids items, Manthan, Twamev-Men) = MEN.
    This mirrors how the GROWTH DEGROWTH sheet assigns MEN/WOMEN."""
    div = df[COL_DIVISION].astype(str).str.upper()
    is_women = (div.str.startswith("MOHEY")
                | div.str.contains("TWAMEV-WOMEN", regex=False)
                | div.eq("MEBAZ"))
    g = pd.Series("MEN", index=df.index)
    g[is_women] = "WOMEN"
    return g


# Fine brand-line for the store×brand report (deepest VFL level). Each line is
# gender-pure, so it rolls up cleanly into the MEN/WOMEN totals of brand_gender.
BRANDLINE_ORDER = ["MANYAVAR", "TWAMEV MEN", "MANTHAN",
                   "MOHEY", "TWAMEV-WOMEN", "MEBAZ"]
BRANDLINE_GENDER = {"MANYAVAR": "MEN", "TWAMEV MEN": "MEN", "MANTHAN": "MEN",
                    "MOHEY": "WOMEN", "TWAMEV-WOMEN": "WOMEN", "MEBAZ": "WOMEN"}


def brand_line(df: pd.DataFrame) -> pd.Series:
    """Fine brand-line per row: MANYAVAR / TWAMEV MEN / MANTHAN / MOHEY /
    TWAMEV-WOMEN / MEBAZ. Everything else (any other Division) folds into
    MANYAVAR, per the source sheet."""
    d = df[COL_DIVISION].astype(str).str.upper()
    out = pd.Series("MANYAVAR", index=df.index)          # others -> Manyavar
    out[d.str.contains("TWAMEV-MEN", regex=False)] = "TWAMEV MEN"
    out[d.eq("MANTHAN")] = "MANTHAN"
    out[d.str.startswith("MOHEY")] = "MOHEY"
    out[d.str.contains("TWAMEV-WOMEN", regex=False)] = "TWAMEV-WOMEN"
    out[d.eq("MEBAZ")] = "MEBAZ"
    return out

# Column layout mirroring the source pivot (BRAND_WISE_GD / VFL tabs).
GD_VALUE_COLS = ["YTD LY", "YTD TY", "MTD LY", "MTD TY", "Day Sales",
                 "Month Sale LY", "Projected MTD", "LY Full Sales",
                 "Projected YTD"]


def _extra_gd_windows(df: pd.DataFrame, asof=None):
    """Frames for the non-YoY columns: today's day-sale, last-year same calendar
    month (full), and the prior full fiscal year (Apr–Mar)."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    day = df[df["date"] == asof]
    ly_m_start = asof.replace(day=1) - pd.DateOffset(years=1)
    ly_m_end = ly_m_start + pd.offsets.MonthEnd(0)
    ly_month = df[(df["date"] >= ly_m_start) & (df["date"] <= ly_m_end)]
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    ly_full = df[(df["date"] >= pd.Timestamp(fy_year - 1, 4, 1)) &
                 (df["date"] <= pd.Timestamp(fy_year, 3, 31))]
    return asof, day, ly_month, ly_full


def _gd_by(df: pd.DataFrame, keys, asof=None, anchor_takeover: bool = True) -> pd.DataFrame:
    """Growth/degrowth grouped by `keys` (list of columns). YTD/MTD TY & LY come
    from report_frames (takeover-anchored unless `anchor_takeover=False`); adds
    day-sale, LY same-month, LY full year, run-rate projections and GD% columns."""
    import calendar
    asof, day, ly_month, ly_full = _extra_gd_windows(df, asof)
    ycur, ypri = report_frames(df, "YTD", asof=asof, anchor_takeover=anchor_takeover)
    mcur, mpri = report_frames(df, "MTD", asof=asof, anchor_takeover=anchor_takeover)

    def g(f):
        return f.groupby(keys)[COL_AMOUNT].sum()

    out = pd.DataFrame({
        "YTD LY": g(ypri), "YTD TY": g(ycur),
        "MTD LY": g(mpri), "MTD TY": g(mcur),
        "Day Sales": g(day), "Month Sale LY": g(ly_month),
        "LY Full Sales": g(ly_full),
    }).fillna(0.0)

    # Simple run-rate projections (calendar-day based). NOTE: the source sheet
    # projects on OPERATIONAL days — calibrate here once that formula is known.
    dim_total = calendar.monthrange(asof.year, asof.month)[1]
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    days_elapsed = (asof - pd.Timestamp(fy_year, 4, 1)).days + 1
    out["Projected MTD"] = out["MTD TY"] * dim_total / max(asof.day, 1)
    out["Projected YTD"] = out["YTD TY"] * 365.0 / max(days_elapsed, 1)

    ly_ytd = out["YTD LY"].replace(0, pd.NA)
    ly_mtd = out["MTD LY"].replace(0, pd.NA)
    out["GD YTD %"] = (out["YTD TY"] - out["YTD LY"]) / ly_ytd * 100
    out["GD MTD %"] = (out["MTD TY"] - out["MTD LY"]) / ly_mtd * 100
    return out.reset_index()


def brand_wise_gd(df: pd.DataFrame, asof=None, anchor_takeover: bool = True) -> pd.DataFrame:
    """Brand-wise growth/degrowth (Manyavar / Mohey / Twamev / Mebaz / Manthan),
    columns ordered like the BRAND_WISE_GD tab. Respects the filtered `df`."""
    out = _gd_by(df, [COL_BRAND], asof=asof, anchor_takeover=anchor_takeover).rename(
        columns={COL_BRAND: "Brand"})
    out["__o"] = out["Brand"].map({b: i for i, b in enumerate(BRAND_ORDER)}).fillna(99)
    out = out.sort_values("__o").drop(columns="__o").reset_index(drop=True)
    cols = ["Brand", "YTD LY", "YTD TY", "GD YTD %", "MTD LY", "MTD TY",
            "GD MTD %", "Day Sales", "Month Sale LY", "Projected MTD",
            "LY Full Sales", "Projected YTD"]
    return out[cols]


def gender_wise_gd(df: pd.DataFrame, asof=None, anchor_takeover: bool = True) -> pd.DataFrame:
    """Gender-wise growth/degrowth, Region → Gender (MEN/WOMEN), classified by
    brand-line to match the source sheet."""
    df = df.copy()
    df["_gender"] = brand_gender(df)
    out = _gd_by(df, [COL_REGION, "_gender"], asof=asof,
                 anchor_takeover=anchor_takeover).rename(
        columns={COL_REGION: "Region", "_gender": "Gender"})
    out["__g"] = out["Gender"].map({g: i for i, g in enumerate(GENDER_ORDER)}).fillna(99)
    out["__r"] = out["Region"].map({r: i for i, r in enumerate(_REGION_ORDER)}).fillna(99)
    out = out.sort_values(["__r", "__g"]).drop(columns=["__r", "__g"]).reset_index(drop=True)
    cols = ["Region", "Gender", "YTD LY", "YTD TY", "GD YTD %", "MTD LY",
            "MTD TY", "GD MTD %", "Day Sales", "Month Sale LY", "Projected MTD",
            "LY Full Sales", "Projected YTD"]
    return out[cols]


def gender_contribution(df: pd.DataFrame, asof=None, anchor_takeover: bool = True):
    """Gender contribution %: store × gender with MTD_TY & YTD_TY and each
    gender's share within its store; plus a region × gender summary. Mirrors
    the VFL_GENDER tab. Returns (detail_df, summary_df)."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    df = df.copy()
    df["_gender"] = brand_gender(df)
    ycur, _ = report_frames(df, "YTD", asof=asof, anchor_takeover=anchor_takeover)
    mcur, _ = report_frames(df, "MTD", asof=asof, anchor_takeover=anchor_takeover)
    master = load_store_master()[["tableau_name", "code", "location", "city", "region"]]

    def by(f, keys):
        return f.groupby(keys)[COL_AMOUNT].sum()

    # ---- store × gender detail ----
    d = pd.DataFrame({
        "MTD TY": by(mcur, [COL_STORE_LABEL, "_gender"]),
        "YTD TY": by(ycur, [COL_STORE_LABEL, "_gender"]),
    }).fillna(0.0).reset_index()
    d = d.merge(master, left_on=COL_STORE_LABEL, right_on="tableau_name", how="left")
    st_mtd = d.groupby(COL_STORE_LABEL)["MTD TY"].transform("sum")
    st_ytd = d.groupby(COL_STORE_LABEL)["YTD TY"].transform("sum")
    d["Contrib MTD %"] = d["MTD TY"] / st_mtd.replace(0, pd.NA) * 100
    d["Contrib YTD %"] = d["YTD TY"] / st_ytd.replace(0, pd.NA) * 100
    d["code"] = pd.to_numeric(d["code"], errors="coerce")
    d["__g"] = d["_gender"].map({g: i for i, g in enumerate(GENDER_ORDER)}).fillna(99)
    d["__r"] = d["region"].map({r: i for i, r in enumerate(_REGION_ORDER)}).fillna(99)
    d = d.sort_values(["__r", "code", "__g"]).reset_index(drop=True)
    detail = d[["region", "city", "location", "code", "_gender", "MTD TY",
                "Contrib MTD %", "YTD TY", "Contrib YTD %"]].rename(
        columns={"region": "Region", "city": "Master Location",
                 "location": "Location", "code": "Store Code", "_gender": "Gender"})

    # ---- region × gender summary ----
    s = pd.DataFrame({
        "MTD TY": by(mcur, [COL_REGION, "_gender"]),
        "YTD TY": by(ycur, [COL_REGION, "_gender"]),
    }).fillna(0.0).reset_index()
    r_mtd = s.groupby(COL_REGION)["MTD TY"].transform("sum")
    r_ytd = s.groupby(COL_REGION)["YTD TY"].transform("sum")
    s["Contrib MTD %"] = s["MTD TY"] / r_mtd.replace(0, pd.NA) * 100
    s["Contrib YTD %"] = s["YTD TY"] / r_ytd.replace(0, pd.NA) * 100
    s["__g"] = s["_gender"].map({g: i for i, g in enumerate(GENDER_ORDER)}).fillna(99)
    s["__r"] = s[COL_REGION].map({r: i for i, r in enumerate(_REGION_ORDER)}).fillna(99)
    s = s.sort_values(["__r", "__g"]).reset_index(drop=True)
    summary = s[[COL_REGION, "_gender", "MTD TY", "Contrib MTD %", "YTD TY",
                 "Contrib YTD %"]].rename(columns={COL_REGION: "Region",
                                                    "_gender": "Gender"})
    return detail, summary


def gender_store_gd(df: pd.DataFrame, asof=None, anchor_takeover: bool = True) -> pd.DataFrame:
    """Store × gender growth/degrowth (brand-line gender), like the VFL tab
    (pages 10-12): one row per store per gender, with the full GD column set.
    Region / Master Location / Store Code / Location come from the master."""
    df = df.copy()
    df["_gender"] = brand_gender(df)
    out = _gd_by(df, [COL_STORE_LABEL, "_gender"], asof=asof,
                 anchor_takeover=anchor_takeover)
    master = load_store_master()[["tableau_name", "code", "location", "city", "region"]]
    out = out.merge(master, left_on=COL_STORE_LABEL, right_on="tableau_name", how="left")
    out["code"] = pd.to_numeric(out["code"], errors="coerce")
    out["__g"] = out["_gender"].map({g: i for i, g in enumerate(GENDER_ORDER)}).fillna(9)
    out["__r"] = out["region"].map({r: i for i, r in enumerate(_REGION_ORDER)}).fillna(9)
    out = out.sort_values(["__r", "code", "__g"]).reset_index(drop=True)
    out = out.rename(columns={"region": "Region", "city": "Master Location",
                              "location": "Location", "code": "Store Code",
                              "_gender": "Gender"})
    cols = ["Region", "Master Location", "Store Code", "Location", "Gender",
            "YTD LY", "YTD TY", "GD YTD %", "MTD LY", "MTD TY", "GD MTD %",
            "Day Sales", "Projected MTD", "Month Sale LY", "Projected YTD",
            "LY Full Sales"]
    return out[cols]


def store_brand_gd(df: pd.DataFrame, asof=None, anchor_takeover: bool = True) -> pd.DataFrame:
    """Store × brand-line growth/degrowth — the deepest VFL level: one row per
    brand-line per store (MANYAVAR / TWAMEV MEN / MANTHAN / MOHEY / TWAMEV-WOMEN /
    MEBAZ), ordered by gender then brand, with the DOO (takeover date). The app
    adds the MEN/WOMEN gender subtotals, per-store totals, region + grand totals.
    Gender is carried as a helper column (each brand-line is gender-pure, so the
    MEN/WOMEN totals match the Gender G/D report)."""
    df = df.copy()
    df["_bl"] = brand_line(df)
    out = _gd_by(df, [COL_STORE_LABEL, "_bl"], asof=asof,
                 anchor_takeover=anchor_takeover)
    master = load_store_master()[["tableau_name", "code", "location", "city",
                                  "region", "takeover_date"]]
    out = out.merge(master, left_on=COL_STORE_LABEL, right_on="tableau_name", how="left")
    out["code"] = pd.to_numeric(out["code"], errors="coerce")
    out["_gender"] = out["_bl"].map(BRANDLINE_GENDER).fillna("MEN")
    out["__r"] = out["region"].map({r: i for i, r in enumerate(_REGION_ORDER)}).fillna(9)
    out["__g"] = out["_gender"].map({"MEN": 0, "WOMEN": 1}).fillna(9)
    out["__b"] = out["_bl"].map({b: i for i, b in enumerate(BRANDLINE_ORDER)}).fillna(99)
    out = out.sort_values(["__r", "code", "__g", "__b"]).reset_index(drop=True)
    out["DOO"] = pd.to_datetime(out["takeover_date"], errors="coerce").dt.strftime("%d-%m-%Y")
    out = out.rename(columns={"region": "Region", "city": "Master Location",
                              "location": "Location", "code": "Store Code",
                              "_bl": "Brand", "_gender": "Gender"})
    cols = ["Region", "Master Location", "Store Code", "Location", "DOO",
            "Gender", "Brand", "YTD LY", "YTD TY", "GD YTD %", "MTD LY", "MTD TY",
            "GD MTD %", "Day Sales", "Month Sale LY", "Projected MTD",
            "LY Full Sales", "Projected YTD"]
    return out[cols]
