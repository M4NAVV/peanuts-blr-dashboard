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
    return clean(_read_raw())


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


def standard_windows(df: pd.DataFrame) -> dict[str, tuple]:
    """MTD / QTD / YTD (fiscal) and the last completed month, as (start, end)."""
    asof = as_of(df)
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


def store_yoy(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Per-store sales for the window vs same period last year + growth %."""
    ps, pe = _sply(start, end)
    cur = (df[(df["date"] >= start) & (df["date"] <= end)]
           .groupby(COL_STORE_LABEL)[COL_AMOUNT].sum().rename("cur"))
    pri = (df[(df["date"] >= ps) & (df["date"] <= pe)]
           .groupby(COL_STORE_LABEL)[COL_AMOUNT].sum().rename("prior"))
    m = pd.concat([cur, pri], axis=1).fillna(0.0).reset_index()
    m["growth"] = m.apply(
        lambda r: ((r["cur"] - r["prior"]) / r["prior"] * 100)
        if r["prior"] > 0 else None, axis=1,
    )
    return m.sort_values("cur", ascending=False)


# --------------------------------------------------------------------------- #
# Region × store MTD/YTD YoY report (the executive table)
# --------------------------------------------------------------------------- #

_MASTER_PATH = os.path.join(os.path.dirname(__file__), "store_master.csv")
_REGION_ORDER = ["East & NE", "South"]

REPORT_COLS = [
    "Region", "DATE", "STORE CODE", "LOCATION",
    "MTD LY", "MTD TY", "GD MTD Value", "GD MTD %",
    "YTD LY", "YTD TY", "GD YTD Value", "GD YTD %",
]


def load_store_master() -> pd.DataFrame:
    m = pd.read_csv(_MASTER_PATH, dtype={"code": str})
    m["tableau_name"] = m["tableau_name"].astype(str).str.strip()
    return m


def _store_window_sales(df, start, end) -> pd.Series:
    return (df[(df["date"] >= start) & (df["date"] <= end)]
            .groupby(COL_STORE_LABEL)[COL_AMOUNT].sum())


def _growth_pct(ty: float, ly: float):
    return ((ty - ly) / ly * 100) if ly else None


def region_store_report(df: pd.DataFrame):
    """Region-grouped, store-wise MTD/YTD year-on-year table with subtotals and
    a grand total. Returns (display_df, row_types) where row_types marks each row
    as 'store' | 'subtotal' | 'grand' for styling."""
    wins = standard_windows(df)
    (ms, me), (ys, ye) = wins["MTD"], wins["YTD"]
    pms, pme = _sply(ms, me)
    pys, pye = _sply(ys, ye)
    mtd_ty, mtd_ly = _store_window_sales(df, ms, me), _store_window_sales(df, pms, pme)
    ytd_ty, ytd_ly = _store_window_sales(df, ys, ye), _store_window_sales(df, pys, pye)
    date_str = as_of(df).strftime("%d-%m-%Y")

    master = load_store_master()
    master["_rord"] = master["region"].map(
        {k: i for i, k in enumerate(_REGION_ORDER)}).fillna(99)
    master["_code_num"] = pd.to_numeric(master["code"], errors="coerce")
    master = master.sort_values(["_rord", "_code_num"])

    rows, types = [], []

    def _store_row(region, code, loc, mly, mty, yly, yty):
        return {
            "Region": region, "DATE": date_str, "STORE CODE": code, "LOCATION": loc,
            "MTD LY": mly, "MTD TY": mty,
            "GD MTD Value": mty - mly, "GD MTD %": _growth_pct(mty, mly),
            "YTD LY": yly, "YTD TY": yty,
            "GD YTD Value": yty - yly, "GD YTD %": _growth_pct(yty, yly),
        }

    def _total_row(label, sub):
        mly, mty = sub["MTD LY"].sum(), sub["MTD TY"].sum()
        yly, yty = sub["YTD LY"].sum(), sub["YTD TY"].sum()
        return {
            "Region": label, "DATE": "", "STORE CODE": "", "LOCATION": "",
            "MTD LY": mly, "MTD TY": mty,
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
                region, r["code"], r["location"],
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
