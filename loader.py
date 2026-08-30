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

import projections as PROJ

# Column names as they appear in the raw Tableau export.
COL_STORE = "SHORT_NAME"
COL_DATE = "Bill Date"
COL_BILL = "Bill No"
# One bill, identified the only way it is unique — see `clean`.
COL_BILL_UID = "bill_uid"
COL_MOBILE = "CUSTOMER_MOBILE"
COL_SALESPERSON = "Name (Dm Salesperson)"
COL_DIVISION = "Division"
COL_SECTION = "Section"
COL_MWC = "Men/Women/Child"
COL_DEPARTMENT = "Department"
COL_SIZE = "Size"
COL_COLOR = "CATEGORY2"
# The colour NAME with its range-code prefix removed — see `clean`.
COL_COLOR_NAME = "color_name"
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
        # Published Google Sheet -> CSV, read as strings; cleaning handles types.
        # `feed.read_csv` keeps the gzip fast path (Google serves the export
        # compressed, roughly halving transfer time on a ~279k-row sheet) and
        # the plain retry, but carries the first failure's REASON and refuses a
        # sign-in page rather than parsing one into a one-column frame.
        import feed
        return feed.read_csv(url, expect=(COL_DATE, COL_AMOUNT),
                             what="the VFL sales sheet")
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
    """Parse Bill Date on the convention the column PROVES, not the one assumed.

    The Tableau export writes month first. It used to be parsed on that belief,
    with anything that failed handed to flexible inference — so a source that
    changed format would have been 35% silently wrong with nothing failing at
    all. `dates.parse` reads the convention off the data and records what it
    found; `validation` refuses on the disagreement. See `dates.py`.
    """
    import dates
    return dates.parse(series, expect=dates.MONTH_FIRST, label="vfl")


DIVISION_ALIASES = {
    "TWAMEV MEN": "TWAMEV-MEN",
    "MANYAVAR": "MANYAVAR ACCESSORIES",
}


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

    # Divisions renamed at source mid-stream. On 7 Aug 2026 the POS stopped
    # booking "TWAMEV-MEN" and started booking "TWAMEV MEN"; likewise
    # "MANYAVAR ACCESSORIES" became a bare "MANYAVAR". Left alone that strands
    # ~13 Cr of history on the retired spelling and makes the new one look like
    # a division with no last year — reports would show a catastrophic decline
    # that never happened, and the brand total would look fine, which makes it
    # harder to spot. Folding keeps year-on-year continuous whichever spelling
    # arrives. Add to this map whenever a division is renamed at source.
    df[COL_DIVISION] = (df[COL_DIVISION].astype(str).str.strip()
                        .replace(DIVISION_ALIASES))

    # ★ SIZE: THE SAME SIZE ARRIVES UNDER TWO LABELS. The export writes both
    # "L" and " L", "XL" and " XL", "M" and "  M" — every major size has a
    # whitespace twin, and Rs 101.92 Cr of sales sits in the affected labels.
    # Grouped as stored, the "Units by size" chart drew L twice (47,880 units
    # under " L" and 1,909 more under "L") and a buyer reading a size curve off
    # it would under-order every core size by about 4%. Whitespace carries no
    # meaning here, so it is folded at source.
    df[COL_SIZE] = (df[COL_SIZE].astype(str).str.strip().str.upper()
                    .replace({"NAN": ""}))
    # ★ AND THE BIGGEST BAR ON THAT CHART WAS BLANK. 58,399 units carry no size
    # at all — sarees, accessories, lowers — because they genuinely have none.
    # That is real data and must not be dropped, but an unlabelled bar taller
    # than every actual size makes the chart unreadable and tells a reader
    # nothing. Named, it says what it is.
    df.loc[df[COL_SIZE] == "", COL_SIZE] = "(no size)"

    # ★ COLOUR: ONE COLOUR, SEVERAL RANGE CODES. CATEGORY2 is written
    # "302-Cream", and the same colour recurs under different numeric prefixes
    # across ranges — cream alone appears as 302-Cream, 402-CREAM, 102-CREAM and
    # a bare CREAM, together 38,877 units. That makes cream the single
    # best-selling colour in the estate, while the chart showed its largest
    # fragment at 35,034 and split the rest into three more bars.
    #
    # The raw code is KEPT, because a range code may matter to a buyer. This is
    # a second, foldable column for the questions that are about colour rather
    # than about a season's range.
    df[COL_COLOR_NAME] = (df[COL_COLOR].astype(str)
                          .str.replace(r"^\s*\d+\s*-\s*", "", regex=True)
                          .str.strip().str.upper().replace({"NAN": ""}))

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

    # ★★ WHAT MAKES A BILL ONE BILL: STORE, DAY AND NUMBER TOGETHER (17 Aug).
    #
    # `Bill No` is a PER-STORE sequence — `PM/00029/Apr-26` exists at 22 stores
    # at once — so counting distinct bill numbers across stores merges bills that
    # have nothing to do with each other. It understated the VFL year-to-date by
    # 61% (10,285 against 26,208) and doubled the average ticket with it
    # (Rs 28,306 against Rs 12,884), which is where "bills collapsing, ticket way
    # up" came from: bills actually moved -1.8%, not -18.7%.
    #
    # The DAY belongs in the key too, and South proves why: at the 19 April
    # takeover the previous operator's sequence and ours overlap, so CMH Road has
    # a real `PM/00001/Apr-26` on the 1st AND another on the 19th. 1,597 pairs
    # look like that, every one of them around a takeover.
    #
    # ★ NULL STAYS NULL. The night fill appends rows with no bill number at all,
    # because a night's takings carry no bill numbers and inventing them would be
    # fabricating transactions. Building the key by string concatenation would
    # have turned each of those into the countable bill "store|date|nan" — so the
    # key is null wherever the number is, and `nunique` keeps ignoring them.
    _bill = df[COL_BILL].astype(str).str.strip()
    df[COL_BILL_UID] = (
        df[COL_STORE_LABEL].astype(str) + "␟"
        + df["date"].dt.strftime("%Y-%m-%d") + "␟" + _bill
    ).where(df[COL_BILL].notna() & _bill.ne("") & _bill.ne("nan"), pd.NA)

    # Indian fiscal calendar (Apr–Mar). FY26 = Apr 2025 → Mar 2026.
    fy_start_year = df["date"].dt.year.where(df["date"].dt.month >= 4,
                                             df["date"].dt.year - 1)
    df["fy_start_year"] = fy_start_year
    df["fy"] = "FY" + ((fy_start_year + 1) % 100).astype(int).astype(str).str.zfill(2)
    df["fy_month_idx"] = (df["date"].dt.month - 4) % 12 + 1  # Apr=1 … Mar=12
    df["fy_month"] = df["date"].dt.strftime("%b")

    return df.reset_index(drop=True)


def load_data() -> pd.DataFrame:
    """Public entry point. Streamlit caching is applied in app.py.

    If a night fill is configured and holds a day NEWER than anything in the VFL
    sheet, its rows are appended before `clean()`, so they are typed and enriched
    by the same code as every other row. A day the sheet already covers is
    ignored, so Tableau always wins once it lands — the same forward-only rule
    the portfolio side follows. `df.attrs["provisional_date"]` names the day.

    Those rows are COARSE by nature: see night_fill.vfl_rows_if_newer. Sales,
    brand line, gender and units are faithful; bills cannot be represented and
    the finer dimensions read "(PROVISIONAL)".
    """
    raw = _read_raw()
    provisional = None
    try:
        import night_fill
        extra = night_fill.vfl_rows_if_newer(raw)
        if extra is not None and len(extra):
            provisional = _parse_dates(extra[COL_DATE]).max()
            raw = pd.concat([raw, extra], ignore_index=True)
    except Exception:
        provisional = None          # never let the overlay break the load
    df = clean(raw)
    df = _apply_takeover_filter(df)
    df = _enrich(df)
    if night_fill._PROVISIONAL_COL not in df.columns:
        df[night_fill._PROVISIONAL_COL] = False
    df[night_fill._PROVISIONAL_COL] = df[night_fill._PROVISIONAL_COL].fillna(False)
    df.attrs["provisional_date"] = provisional
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
    """Keep each store's sales from ONE YEAR BEFORE its takeover date onward.

    The current-year windows are anchored to the takeover date (see report_frames),
    so pre-ownership sales never count as *ours*. But we retain the prior year of
    history so year-on-year analytics can compare a newly taken-over store — e.g.
    South (taken over 19 Apr 2026) — against the same location's prior-year sales
    from the previous operator. The takeover date itself stays accurate; this only
    controls how far back the comparison baseline reaches. Stores without a mapped
    takeover date keep all rows."""
    tk = takeover_map()
    base = df[COL_STORE_LABEL].map(tk) - pd.DateOffset(years=1)   # takeover − 1yr
    # Reach back to the START of the fiscal year (Apr–Mar) containing that date, so
    # a store taken over mid-year (e.g. South, 19 Apr) keeps its FULL prior fiscal
    # year as the YoY baseline — otherwise 'LY Full Sales' loses 1–18 Apr. The
    # takeover-anchored current-year windows (report_frames) are unchanged.
    fy_y = base.dt.year.where(base.dt.month >= 4, base.dt.year - 1)
    start = pd.to_datetime(
        dict(year=fy_y.fillna(1900).astype(int), month=4, day=1)).where(base.notna())
    keep = start.isna() | (df["date"] >= start)
    return df[keep].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# KPI helpers — all operate on the cleaned frame.
# --------------------------------------------------------------------------- #

def bill_count(df: pd.DataFrame) -> int:
    """Bills — the distinct bill numbers in the frame.

    ★ THIS WAS BRIEFLY SOMETHING CLEVERER AND IT WAS WRONG. On 30 Aug, auditing
    Orion Mall's 1-29 August against the GINESYS POS, the sales agreed to Rs 78
    but the bill count read 430 against the POS's 451. Twenty-two bills in that
    window carried both sale lines and a return line, and 430 + 22 = 452 — one
    away from 451. So a rule was written that counted an exchange as two memos,
    a sale and a credit, and it shipped.

    ⚠ THE 21 MISSING BILLS WERE NOT EXCHANGES. THE DAY WAS NOT FINISHED.
    The feed's 29 August was still filling when the comparison was made; the
    POS report had been printed on the 30th against a settled day. Once the
    feed completed, the SAME window gave 451 distinct bills — the POS's number,
    exactly — and the clever rule was counting the twenty-two exchanges twice,
    pushing Orion's ABV to Rs 8,073 against the POS's Rs 8,467. It made the
    error it was written to fix, in the opposite direction.

    ★ NEVER RECONCILE AGAINST THE FEED'S MOST RECENT DAY. It is the one day
    that can still change, and a shortfall in it will find a plausible
    explanation among whatever else is nearby — here, a count of exchanges that
    happened to sit one away from the gap. Compare on a settled window, or the
    coincidence does the reasoning for you.

    The function is kept, rather than the five `nunique()` calls it replaced,
    because one definition in one place is still right — and a test fails if a
    sixth caller starts counting bills its own way.
    """
    if COL_BILL_UID not in df.columns or df.empty:
        return 0
    return int(df[COL_BILL_UID].nunique())


def headline_kpis(df: pd.DataFrame) -> dict:
    """Top-line KPIs for the overview cards."""
    total_sales = df[COL_AMOUNT].sum()
    total_units = df[COL_QTY].sum()
    bills = bill_count(df)
    customers = df[COL_MOBILE].replace("", pd.NA).nunique()
    discount = df[COL_PROMO].sum()

    per_bill = df.groupby(COL_BILL_UID).agg(
        amt=(COL_AMOUNT, "sum"), qty=(COL_QTY, "sum")
    )
    atv = per_bill["amt"].mean() if len(per_bill) else 0
    upt = per_bill["qty"].mean() if len(per_bill) else 0
    asp = (total_sales / total_units) if total_units else 0

    cust_bills = (
        df[df[COL_MOBILE].replace("", pd.NA).notna()]
        .groupby(COL_MOBILE)[COL_BILL_UID]
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
            bills=(COL_BILL_UID, "nunique"),
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
        .agg(sales=(COL_AMOUNT, "sum"), bills=(COL_BILL_UID, "nunique"), units=(COL_QTY, "sum"))
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
            bills=(COL_BILL_UID, "nunique"),
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
            bills=(COL_BILL_UID, "nunique"),
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
            bills=(COL_BILL_UID, "nunique"),
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
        valid.groupby([COL_MOBILE, COL_BILL_UID])
        .agg(date=("date", "min"), amt=(COL_AMOUNT, "sum"))
        .reset_index()
        .merge(first, on=COL_MOBILE)
    )
    bills["is_repeat"] = bills["date"] > bills["first_date"]

    top = (
        valid.groupby(COL_MOBILE)
        .agg(spend=(COL_AMOUNT, "sum"), visits=(COL_BILL_UID, "nunique"))
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
    "Color": COL_COLOR_NAME,
    "Color (with range code)": COL_COLOR,
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
            bills=(COL_BILL_UID, "nunique"),
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
    bills = bill_count(sub)              # an exchange is two memos
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


_DOO_PATH = os.path.join(os.path.dirname(__file__), "gd_store_attrs.csv")


def doo_map() -> dict:
    """store code -> date of opening (Timestamp).

    `store_master.csv` carries only `takeover_date` — when we took the store
    over, which for all of East & NE is a blanket 2025-04-01 and is NOT an
    opening date. The real per-store DOO lives in `gd_store_attrs.csv` (the
    curated workbook attributes the Portfolio sheets already read), so the VFL
    reports source it from there and fall back to the takeover date only for a
    code that file doesn't know about.
    """
    try:
        a = pd.read_csv(_DOO_PATH)
    except Exception:
        return {}
    if not {"code", "doo"} <= set(a.columns):
        return {}
    code = pd.to_numeric(a["code"], errors="coerce")
    doo = pd.to_datetime(a["doo"], errors="coerce")
    ok = code.notna() & doo.notna()
    return dict(zip(code[ok].astype(int), doo[ok]))


def closed_map() -> dict:
    """store code -> closure date (Timestamp), for stores that have shut.

    A closed store stops accruing elapsed days, so its year-to-date figures must
    be projected over the period it actually traded rather than to today.

    ★ THE STORE MASTER IS THE AUTHORITY (13 Aug). It carries CLOSURE DATE, and
    Manav maintains it; the committed `gd_store_attrs.csv` is a snapshot that
    only changes when someone edits the repo. It knew three closures while the
    master knew thirteen, so ten shut stores were still being counted as open
    everywhere. The snapshot stays as the fallback for when the sheet cannot be
    reached — a missing map would mean "nothing has ever closed", which is a
    wrong answer rather than a missing one.
    """
    try:
        import master_lookup
        live = master_lookup.closed()
        if live:
            return dict(live)
    except Exception:
        pass                          # fall through to the committed snapshot
    try:
        a = pd.read_csv(_DOO_PATH)
    except Exception:
        return {}
    if not {"code", "closed"} <= set(a.columns):
        return {}
    code = pd.to_numeric(a["code"], errors="coerce")
    cl = pd.to_datetime(a["closed"], errors="coerce")
    ok = code.notna() & cl.notna()
    return dict(zip(code[ok].astype(int), cl[ok]))


def _doo_series(codes, fallback):
    """DOO per store code as dd-mm-YYYY, falling back to `fallback` (a datetime
    Series, normally the takeover date) where the code has no curated DOO."""
    m = doo_map()
    mapped = pd.to_numeric(codes, errors="coerce").map(m)
    return pd.to_datetime(mapped).fillna(
        pd.to_datetime(fallback, errors="coerce")).dt.strftime("%d-%m-%Y")


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


def report_frames(df: pd.DataFrame, kind: str, asof=None, anchor_takeover: bool = True,
                  new_store_no_ly: bool = False):
    """Current & same-period-last-year frames for kind in {MTD, YTD}. Each store's
    window is anchored to its takeover date (so TY and LY line up); pass
    `anchor_takeover=False` to use a plain 1-Apr fiscal start instead (matches the
    monthly review sheet). `new_store_no_ly=True` zeros the last-year frame for
    stores whose opening date (store_master) is in the current FY — the report's
    new-store view. Off by default so the main dashboard stays historical.
    `asof` (the to-date reference) defaults to latest data."""
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
    prior_mask = (df["date"] >= prior_start) & (df["date"] <= prior_end)
    if new_store_no_ly:
        # Stores that opened THIS fiscal year (per the store master) have no
        # comparable last year — zero their prior frame, matching the source sheet
        # (new stores show YTD_LY = "-" / GD = new).
        opened = pd.to_datetime(df[COL_STORE_LABEL].map(takeover_map()), errors="coerce")
        prior_mask &= ~(opened >= pd.Timestamp(fy_year, 4, 1))
    # ★★ LAST YEAR STOPS WHERE A CLOSED STORE'S THIS YEAR STOPS (19 Aug 2026).
    #
    # This feed had no closure handling at all, so a shut store compared its
    # FULL last year against a this year that ends with the shutter. Roodraksh
    # Mall closed 31 July and read -22.0% where the truth is -16.1%; last year's
    # 1-18 August, Rs 1,72,537 over 62 rows, had no counterpart to be compared
    # against. The portfolio feed has always cut this (`_window_frames`), which
    # is why the same store reads correctly there.
    #
    # ★ DONE HERE, AT THE SOURCE, RATHER THAN IN THE TWO REPORTS THAT SHOWED IT.
    # Manav asked his team and took the wider fix: patching the executive screens
    # alone would have left the degrowth watchlists and the morning manager
    # reports on the old basis — trading a visible inconsistency for a hidden
    # one. Every VFL surface now uses one closure rule.
    #
    # Cut on the closure DAY, where the portfolio cuts at its MONTH-END. All 13
    # recorded closures are month-ends so the two agree today; the day is the
    # stricter reading and matches the like-to-like spans.
    _shut = closure_cutoffs(asof)
    if _shut:
        _lim = df[COL_STORE_LABEL].map(_shut) - pd.DateOffset(years=1)
        prior_mask &= ~(_lim.notna() & (df["date"] > _lim))
    prior = df[prior_mask]
    return cur, prior


def _frame_metrics(f: pd.DataFrame) -> dict:
    """Sales and units off every row; bills and ticket off the SETTLED ones.

    ★ 14 Aug. A night fill carries a day's takings faithfully and carries no
    bill numbers at all, so the two halves of this block have to be drawn from
    different sets: sales and units include the provisional day, bills and the
    average ticket stop at the last settled one. Dividing the fuller numerator
    by the thinner denominator is the same mismatched-halves error that made a
    city read 380% conversion — and it is why this whole block used to drop the
    provisional day, which cost the dashboard a day it actually had.
    """
    settled = (f[~f["_provisional"].astype(bool)]
               if "_provisional" in f.columns else f)
    sales = f[COL_AMOUNT].sum()
    units = f[COL_QTY].sum()
    bills = bill_count(settled)          # an exchange is two memos
    s_sales = settled[COL_AMOUNT].sum()
    return {"sales": sales, "bills": bills, "units": int(units),
            "atv": s_sales / bills if bills else 0.0,
            # True when the sales above include a day the bills do not.
            "part_settled": bool(len(settled) != len(f))}


def window_yoy_takeover(df: pd.DataFrame, kind: str, asof=None) -> dict:
    """YoY for MTD/YTD using per-store takeover-anchored windows (for exec cards).

    ★ 14 Aug: THE NIGHT FILL'S DAY IS COUNTED HERE NOW (Manav: the fill works on
    the PDFs, "so can we apply the same principle to the dash data"). It used to
    be dropped whole, because a fill carries no bill numbers and dividing its
    sales by yesterday's bills overstates the ticket. Dropping it also cost the
    dashboard a day of real money it was holding — the VFL month read Rs 2.78 Cr
    against the Rs 2.93 Cr it had. `_frame_metrics` now splits the difference the
    honest way: sales and units count the provisional day, bills and the average
    ticket stop at the last settled one, and `part_settled` says so.
    """
    cur, prior = report_frames(df, kind, asof=asof)
    c, p = _frame_metrics(cur), _frame_metrics(prior)
    # `part_settled` is a flag, not a figure — and a bool is an int in Python,
    # so it would otherwise arrive here as a growth rate of its own.
    growth = {k: ((c[k] - p[k]) / p[k] * 100 if p[k] else None)
              for k in c if isinstance(c[k], (int, float))
              and not isinstance(c[k], bool)}
    def _rng(f):
        return (f["date"].min(), f["date"].max()) if len(f) else (None, None)
    def _settled_end(f):
        s = (f[~f["_provisional"].astype(bool)] if "_provisional" in f.columns
             else f)
        return s["date"].max() if len(s) else None
    return {"cur": c, "prior": p, "growth": growth,
            "cur_window": _rng(cur), "prior_window": _rng(prior),
            # Where the bills stop, when that is not where the sales stop.
            "bills_to": _settled_end(cur) if c.get("part_settled") else None}


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

    # ★ THE LIKE-TO-LIKE SPLIT, the same rule as the GD sheets on both feeds
    # (Manav, 19 Aug: "we can make this change in the mtd/ytd reports tab also").
    # A store only comparable over part of the window shows that part on its own
    # line, with the rest above it, and its own row still closes the pair — so
    # the growth on the comparable half is not diluted by months with no last
    # year. Only the MTD and YTD pairs split; the day's sale is a different
    # window and would mean nothing cut this way.
    l2l_start, l2l_end = _l2l_spans_vfl(df, asof)
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    win_start = pd.Timestamp(fy_year, 4, 1)
    _yr = pd.DateOffset(years=1)

    def _part(frame, label, lo, hi):
        m = ((frame[COL_STORE_LABEL] == label) & (frame["date"] >= lo)
             & (frame["date"] <= hi))
        return float(frame[m][COL_AMOUNT].sum())

    def _halves(label, whole):
        s, e = l2l_start.get(label), l2l_end.get(label)
        if s is None or e is None or s > e:
            return []                     # no comparable span at all
        if s <= win_start and e >= asof:
            return []                     # the span covers the window
        inside = {"YTD TY": _part(ytd_cur, label, s, e),
                  "YTD LY": _part(ytd_pri, label, s - _yr, e - _yr),
                  "MTD TY": _part(mtd_cur, label, s, e),
                  "MTD LY": _part(mtd_pri, label, s - _yr, e - _yr)}
        outside = {k: whole[k] - inside[k] for k in inside}
        if all(abs(v) < 1 for v in outside.values()):
            return []
        return [("no L2L", outside), (f"L2L from {s:%d-%m-%Y}", inside)]

    def _half_row(loc, note, v):
        """Only the compared columns mean anything on a half."""
        return {
            "Region": "", "DATE": "", "STORE CODE": "",
            "LOCATION": f"{loc} — {note}",
            "Day Sales": float("nan"),
            "MTD LY": v["MTD LY"], "MTD TY": v["MTD TY"],
            "GD MTD Value": v["MTD TY"] - v["MTD LY"],
            "GD MTD %": _growth_pct(v["MTD TY"], v["MTD LY"]),
            "YTD LY": v["YTD LY"], "YTD TY": v["YTD TY"],
            "GD YTD Value": v["YTD TY"] - v["YTD LY"],
            "GD YTD %": _growth_pct(v["YTD TY"], v["YTD LY"]),
        }

    l2l_rows, non_l2l_rows = [], []
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
            parts = _halves(name, sr)
            for note, vals in parts:
                rows.append(_half_row(r["location"], note, vals))
                types.append("split")
                (non_l2l_rows if note == "no L2L" else l2l_rows).append(vals)
            if not parts:
                s, e = l2l_start.get(name), l2l_end.get(name)
                (l2l_rows if (s is not None and e is not None and s <= e)
                 else non_l2l_rows).append(sr)
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

    # The report's own like-to-like line — the figure the Executive Snapshot
    # prints, shown here rather than left for the reader to reconstruct.
    for label, part in (("LIKE TO LIKE", l2l_rows), ("NO L2L", non_l2l_rows)):
        if not part:
            continue
        t = {k: sum(float(p.get(k, 0.0) or 0.0) for p in part)
             for k in ("MTD LY", "MTD TY", "YTD LY", "YTD TY")}
        rows.append({
            "Region": label, "DATE": "", "STORE CODE": "", "LOCATION": "",
            "Day Sales": float("nan"),
            "MTD LY": t["MTD LY"], "MTD TY": t["MTD TY"],
            "GD MTD Value": t["MTD TY"] - t["MTD LY"],
            "GD MTD %": _growth_pct(t["MTD TY"], t["MTD LY"]),
            "YTD LY": t["YTD LY"], "YTD TY": t["YTD TY"],
            "GD YTD Value": t["YTD TY"] - t["YTD LY"],
            "GD YTD %": _growth_pct(t["YTD TY"], t["YTD LY"]),
        })
        types.append("summary")

    return pd.DataFrame(rows, columns=REPORT_COLS), types


def all_scalar_kpis(df: pd.DataFrame) -> dict[str, tuple[float, bool]]:
    """Every metric as a single scalar over `df`, for the selectable KPI cards.
    Returns {label: (value, is_money)}."""
    sales = df[COL_AMOUNT].sum()
    net = df["net_amount"].sum()
    units = df[COL_QTY].sum()
    bills = bill_count(df)               # an exchange is two memos
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


# The workbook's VFL sheet shows only FOUR brand-lines: the minor men's line
# (Manthan) folds into Manyavar and the minor women's line (Mebaz) into Mohey.
BRANDLINE_VFL_ORDER = ["MANYAVAR", "TWAMEV MEN", "MOHEY", "TWAMEV-WOMEN"]
BRANDLINE_VFL_GENDER = {"MANYAVAR": "MEN", "TWAMEV MEN": "MEN",
                        "MOHEY": "WOMEN", "TWAMEV-WOMEN": "WOMEN"}


def brand_line_vfl(df: pd.DataFrame) -> pd.Series:
    """Coarse brand-line matching the workbook VFL sheet (4 lines): MANYAVAR /
    TWAMEV MEN / MOHEY / TWAMEV-WOMEN. Manthan folds into Manyavar, Mebaz into
    Mohey, anything else into Manyavar."""
    d = df[COL_DIVISION].astype(str).str.upper()
    out = pd.Series("MANYAVAR", index=df.index)
    out[d.str.contains("TWAMEV-MEN", regex=False)] = "TWAMEV MEN"
    out[d.str.startswith("MOHEY")] = "MOHEY"
    out[d.eq("MEBAZ")] = "MOHEY"
    out[d.str.contains("TWAMEV-WOMEN", regex=False)] = "TWAMEV-WOMEN"
    return out

# Column layout mirroring the source pivot (BRAND_WISE_GD / VFL tabs).
GD_VALUE_COLS = ["YTD LY", "YTD TY", "MTD LY", "MTD TY", "Day Sales",
                 "Month Sale LY", "Projected MTD", "LY Full Sales",
                 "Projected YTD", "TTM Sales"]


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
    # ★ TRAILING 12 MONTHS — rolling 365 days ending today, moving daily.
    # Unlike the portfolio feed, South HAS a full year here: the VFL sheet
    # carries its previous operator's history, which is the same reason South
    # shows a real YoY on this pack and none on the portfolio one.
    #
    # ★★ A STORE THE WINDOW OUTRUNS CONTRIBUTES NOTHING (Manav, 29 Aug — the
    # portfolio rule, brought across: "if you dont have data for last year
    # fully, then give the TTM as a 0"). Its rows are dropped from the window
    # BEFORE any grouping, so the rule holds however the sheet is cut — by
    # store, by brand line, by region — and a part year can never be summed
    # into a figure headed TTM. On this feed that is Dibrugarh alone: it opens
    # 23 Jan 2026, and every other store, South included, reaches back past the
    # window's left edge. Coverage is read off the DATA, not off a `doo`
    # attribute, for the reason `l2l_bounds` gives — South's recorded date is a
    # takeover, and here its history predates it.
    ttm_start = asof - pd.DateOffset(years=1) + pd.Timedelta(days=1)
    ttm = df[(df["date"] >= ttm_start) & (df["date"] <= asof)]
    if COL_STORE_LABEL in df.columns:
        first = df.groupby(COL_STORE_LABEL)["date"].min()
        short = set(first[first > ttm_start].index)
        if short:
            ttm = ttm[~ttm[COL_STORE_LABEL].isin(short)]
    return asof, day, ly_month, ly_full, ttm


def _gd_by(df: pd.DataFrame, keys, asof=None, anchor_takeover: bool = True,
           new_store_no_ly: bool = False) -> pd.DataFrame:
    """Growth/degrowth grouped by `keys` (list of columns). YTD/MTD TY & LY come
    from report_frames (takeover-anchored unless `anchor_takeover=False`); adds
    day-sale, LY same-month, LY full year, run-rate projections and GD% columns.
    `new_store_no_ly=True` zeros last-year for stores opened this FY (report view)."""
    asof, day, ly_month, ly_full, ttm = _extra_gd_windows(df, asof)
    ycur, ypri = report_frames(df, "YTD", asof=asof, anchor_takeover=anchor_takeover,
                               new_store_no_ly=new_store_no_ly)
    mcur, mpri = report_frames(df, "MTD", asof=asof, anchor_takeover=anchor_takeover,
                               new_store_no_ly=new_store_no_ly)

    def g(f):
        return f.groupby(keys)[COL_AMOUNT].sum()

    out = pd.DataFrame({
        "YTD LY": g(ypri), "YTD TY": g(ycur),
        "MTD LY": g(mpri), "MTD TY": g(mcur),
        "Day Sales": g(day), "Month Sale LY": g(ly_month),
        "LY Full Sales": g(ly_full), "TTM Sales": g(ttm),
    }).fillna(0.0)

    # Run-rate projections (projections.py). Rows here can be brand-lines rather
    # than stores, so there is no meaningful per-row DOO — the period start is
    # the plain fiscal/month start. `vfl_gd_report` recomputes its own store rows
    # against their real DOO and closure afterwards.
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    out["Projected MTD"] = PROJ.project(
        out["MTD TY"], asof.replace(day=1), asof, None, PROJ.month_days(asof))
    out["Projected YTD"] = PROJ.project(
        out["YTD TY"], pd.Timestamp(fy_year, 4, 1), asof, None, PROJ.YEAR_DAYS)

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
            "LY Full Sales", "Projected YTD", "TTM Sales"]
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
            "LY Full Sales", "Projected YTD", "TTM Sales"]
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
            "LY Full Sales", "TTM Sales"]
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
    out["DOO"] = _doo_series(out["code"], out["takeover_date"])
    out = out.rename(columns={"region": "Region", "city": "Master Location",
                              "location": "Location", "code": "Store Code",
                              "_bl": "Brand", "_gender": "Gender"})
    cols = ["Region", "Master Location", "Store Code", "Location", "DOO",
            "Gender", "Brand", "YTD LY", "YTD TY", "GD YTD %", "MTD LY", "MTD TY",
            "GD MTD %", "Day Sales", "Month Sale LY", "Projected MTD",
            "LY Full Sales", "Projected YTD", "TTM Sales"]
    return out[cols]


_GD_OUT_COLS = ["YTD LY", "YTD TY", "GD YTD %", "MTD LY", "MTD TY", "GD MTD %",
                "Day Sales", "Month Sale LY", "Projected MTD", "LY Full Sales",
                "Projected YTD"]


# --------------------------------------------------------------------------- #
# VFL sheet (exact workbook format) — Region → Master Location → Store → Gender
# → brand-line, with the full tier of subtotals. Matches the "VFL" sheet 1:1.
# --------------------------------------------------------------------------- #
VFL_GD_COLS = [
    "Region", "Master Location", "STORE CODE", "MEN/WOMEN/KIDS", "STORE NAME",
    "LOCATION", "DOO", "Sum of YTD_LY", "Sum of YTD_TY", "Sum of GD_YTD_%",
    "Sum of MTD_LY", "Sum of MTD_TY", "Sum of GD_MTD_%", "Sum of DAY SALE FIGURE",
    "Sum of PROJECTED MTD", "Sum of MONTH SALE LY", "Sum of PROJECTED YTD",
    "Sum of LY FULL SALES", "Sum of TTM SALES",
]
VFL_GD_MONEY = ["Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY",
                "Sum of DAY SALE FIGURE", "Sum of PROJECTED MTD",
                "Sum of MONTH SALE LY", "Sum of PROJECTED YTD", "Sum of LY FULL SALES",
                "Sum of TTM SALES"]
VFL_GD_PCT = ["Sum of GD_YTD_%", "Sum of GD_MTD_%"]
# brand-line detail column (loader name) -> workbook "Sum of ..." money column
_VFL_SUM_SRC = {"YTD LY": "Sum of YTD_LY", "YTD TY": "Sum of YTD_TY",
                "MTD LY": "Sum of MTD_LY", "MTD TY": "Sum of MTD_TY",
                "Day Sales": "Sum of DAY SALE FIGURE",
                "Projected MTD": "Sum of PROJECTED MTD",
                "Month Sale LY": "Sum of MONTH SALE LY",
                "Projected YTD": "Sum of PROJECTED YTD",
                "LY Full Sales": "Sum of LY FULL SALES",
                "TTM Sales": "Sum of TTM SALES"}
_VFL_SUM_COLS = list(_VFL_SUM_SRC)


def _vfl_gd_frac(ty, ly):
    """Growth %, percent units; blank (NaN) when there's no last-year base."""
    return (ty - ly) / ly * 100 if ly else float("nan")


def closure_cutoffs(asof) -> dict:
    """{store label: closure date} for closures that have already happened."""
    shut = closed_map()
    if not shut:
        return {}
    asof = pd.Timestamp(asof)
    master = load_store_master()
    out = {}
    for n, c in zip(master["tableau_name"], master["code"]):
        try:
            code = int(c)
        except (TypeError, ValueError):
            continue                      # code is a STRING column — see below
        if code in shut and pd.Timestamp(shut[code]) <= asof:
            out[str(n)] = pd.Timestamp(shut[code])
    return out


def _l2l_spans_vfl(df: pd.DataFrame, asof):
    """Each store's comparable span on THIS feed, keyed by store label.

    The same call the portfolio sheet makes, and the same one the Executive
    Snapshot compares over — one definition of "comparable" in the codebase,
    not three. Keyed by label because that is what the VFL feed is keyed by;
    `l2l_bounds` does not care which, and reads South's takeover date correctly
    on either feed without being told which feed it is on.
    """
    import exec_snapshot
    master = load_store_master()
    # ⚠️ `master["code"]` is a STRING column while `closed_map` and `doo_map`
    # are keyed by INT. Without the cast every lookup below misses and both maps
    # come back EMPTY — which does not raise: the spans simply open at the
    # feed's left edge and never close, so a shut store compares a full last
    # year against a part year. Cast, exactly as the snapshot does.
    code_of = {str(n): int(c) for n, c in zip(master["tableau_name"],
                                              master["code"])
               if str(c).strip() not in ("", "nan", "None")}
    here = set(df[COL_STORE_LABEL].dropna().astype(str).unique())
    shut, doo = closed_map(), doo_map()
    shut_by_label = {s: shut[c] for s, c in code_of.items()
                     if c in shut and s in here}
    open_by_label = {s: doo[c] for s, c in code_of.items()
                     if c in doo and s in here}
    # The failure above, made loud — but only when there are stores to match.
    # An empty selection is a filter, not a fault, and must still render.
    if here and not open_by_label:
        raise RuntimeError("VFL like-to-like: no store matched the master — "
                           "spans would silently span everything")
    return exec_snapshot.l2l_bounds(df, COL_STORE_LABEL, COL_AMOUNT,
                                    shut_by_label, asof, opened=open_by_label)


def vfl_gd_report(df: pd.DataFrame, asof=None, gen_date=None):
    """The VFL sheet, matching the workbook 1:1. Region → Master Location → Store
    → Gender (MEN/WOMEN) → brand-line detail, with MEN/WOMEN, store, location,
    region and grand totals. Returns (display_df, row_types).  Group labels show
    once per group (blank on repeats), exactly like the Excel outline."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    # `gen_date` = the day the review is run (the live current date). The workbook
    # sums through `asof` (month-end) but PROJECTS on the gen-date elapsed days.
    gen_date = as_of(df) if gen_date is None else pd.Timestamp(gen_date)

    # 4-line brand detail per store (Manthan→Manyavar, Mebaz→Mohey), takeover-anchored.
    d = df.copy()
    d["_blv"] = brand_line_vfl(d)
    sb = _gd_by(d, [COL_STORE_LABEL, "_blv"], asof=asof)
    master = load_store_master()[["tableau_name", "code", "location", "city",
                                  "region", "takeover_date"]]
    sb = sb.merge(master, left_on=COL_STORE_LABEL, right_on="tableau_name", how="left")
    sb["Store Code"] = pd.to_numeric(sb["code"], errors="coerce").astype("Int64")
    sb["Gender"] = sb["_blv"].map(BRANDLINE_VFL_GENDER).fillna("MEN")
    sb["Brand"] = sb["_blv"]
    sb["Region"] = sb["region"]
    sb["Master Location"] = sb["city"].astype(str).str.title().replace(
        {"Kolkata": "Kolkatta"})
    sb["Location"] = sb["location"]
    sb["DOO"] = _doo_series(sb["Store Code"], sb["takeover_date"])

    # Projections on the GEN-DATE operational days — the shared rule in
    # projections.py: achieved / days actually traded x 365 (year) or x 30 (month).
    # Both denominators run from the later of the period start and the store's
    # DOO, so a store opened mid-period is rated on the days it has traded.
    #
    # ⚠️ This REPLACED a per-store 347-day fiscal window that reproduced the
    # 05-08-2026 workbook to 0.00% on 20 of 21 stores. Manav restated the rule as
    # a flat 365 on 9 Aug, which is what the portfolio pack always used; the two
    # packs now agree with each other and with him, and no longer with that
    # workbook's YTD projection column. Deliberate — do not "fix" it back.
    rm_start = asof.replace(day=1)
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    fy_start = pd.Timestamp(fy_year, 4, 1)
    _doo = pd.to_datetime(sb["Store Code"].map(doo_map()), errors="coerce")
    _doo = _doo.fillna(pd.to_datetime(sb["takeover_date"], errors="coerce"))
    _closed = pd.to_datetime(sb["Store Code"].map(closed_map()), errors="coerce")
    ytd_start = _doo.where(_doo > fy_start, fy_start)
    mtd_start = _doo.where(_doo > rm_start, rm_start)
    op_ytd = ((gen_date - ytd_start).dt.days + 1).clip(lower=1)
    op_mtd = ((gen_date - mtd_start).dt.days + 1).clip(lower=1)
    shut = _closed.notna() & (_closed <= gen_date)
    # A closed store's period is over: freeze at what it actually took.
    sb["Projected MTD"] = (sb["MTD TY"] * PROJ.month_days(asof) / op_mtd).where(
        ~shut, sb["MTD TY"])
    sb["Projected YTD"] = (sb["YTD TY"] * PROJ.YEAR_DAYS / op_ytd).where(
        ~shut, sb["YTD TY"])

    # Drop pure-return / all-zero brand-lines (no positive activity), like the sheet.
    keep = ((sb["YTD LY"] > 0) | (sb["YTD TY"] > 0)
            | (sb["MTD LY"] > 0) | (sb["MTD TY"] > 0))
    sb = sb[keep].reset_index(drop=True)

    rows, types = [], []

    def emit(region, mloc, code, gender, sname, loc, doo, s, rtype):
        d = dict.fromkeys(VFL_GD_COLS, "")
        d["Region"], d["Master Location"], d["STORE CODE"] = region, mloc, code
        d["MEN/WOMEN/KIDS"], d["STORE NAME"], d["LOCATION"], d["DOO"] = gender, sname, loc, doo
        for src, dst in _VFL_SUM_SRC.items():
            d[dst] = s[src]
        d["Sum of GD_YTD_%"] = _vfl_gd_frac(s["YTD TY"], s["YTD LY"])
        d["Sum of GD_MTD_%"] = _vfl_gd_frac(s["MTD TY"], s["MTD LY"])
        rows.append(d)
        types.append(rtype)

    def sums(frame):
        return {c: float(frame[c].sum()) for c in _VFL_SUM_COLS}

    def rowsum(r):
        return {c: float(r[c]) for c in _VFL_SUM_COLS}

    # ----------------------------------------------------------------- #
    # ★★ THE LIKE-TO-LIKE SPLIT, the same rule the portfolio GD sheet got on
    # 17 Aug and which Manav asked for here on 19 Aug: *"that rule we made for
    # the portfolio growth degrowth table, where it splits a store into no l2l
    # and l2l, to give an accurate read. i want to implement that same rule in
    # the VFL growth degrowth also."*
    #
    # A store that is only comparable over part of the window has that part cut
    # out and shown on its own line, with the rest on a second line, so the
    # growth on the comparable half is not diluted by months that have no last
    # year at all. The store's own total row still closes the block, so the
    # store is never split across the page — the subtotal is the point.
    #
    # Only the YTD and MTD pairs split. The day's sale, last year's full month,
    # the projections and last full year are different windows and would mean
    # nothing cut this way; they sit on the store total, where it is whole.
    _l2l_start, _l2l_end = _l2l_spans_vfl(df, asof)
    _l2l_win_start = fy_start          # 1 April; a span opening on or before it
    _yr = pd.DateOffset(years=1)       # clips nothing off this year's window
    _y_cur, _y_pri = report_frames(df, "YTD", asof=asof)
    _m_cur, _m_pri = report_frames(df, "MTD", asof=asof)
    _split_src = ["YTD LY", "YTD TY", "MTD LY", "MTD TY"]

    def _part(frame, label, lo, hi):
        m = ((frame[COL_STORE_LABEL] == label) & (frame["date"] >= lo)
             & (frame["date"] <= hi))
        return float(frame[m][COL_AMOUNT].sum())

    def _split_halves(label, whole):
        """[] when the store is comparable throughout — the usual case."""
        s, e = _l2l_start.get(label), _l2l_end.get(label)
        if s is None or e is None or s > e:
            return []                     # no comparable span at all: one line
        # ★ THE TEST IS WHETHER THE SPAN CLIPS THE WINDOW, not whether two
        # sums differ. This sheet DROPS pure-return brand lines ("like the
        # sheet"), so a store total can sit a few thousand rupees off the raw
        # frames — Agartala carries a TWAMEV MEN line at YTD LY -9,999 with no
        # this-year counterpart. Reading that residual as "outside the span"
        # split a store that is comparable from 2023 and put a phantom -100%
        # line under it. Only a real clip splits a store.
        if s <= _l2l_win_start and e >= asof:
            return []
        inside = {"YTD TY": _part(_y_cur, label, s, e),
                  "YTD LY": _part(_y_pri, label, s - _yr, e - _yr),
                  "MTD TY": _part(_m_cur, label, s, e),
                  "MTD LY": _part(_m_pri, label, s - _yr, e - _yr)}
        outside = {k: whole[k] - inside[k] for k in _split_src}
        if all(abs(v) < 1 for v in outside.values()):
            return []                     # comparable all the way through
        return [("NO L2L", outside), (f"L2L FROM {s:%d-%m-%Y}", inside)]

    def emit_split(gender_label, loc, values):
        """A half-line: only the compared columns mean anything on it."""
        d = dict.fromkeys(VFL_GD_COLS, "")
        for c in VFL_GD_MONEY:
            d[c] = float("nan")
        d["MEN/WOMEN/KIDS"], d["LOCATION"] = gender_label, loc
        for src in _split_src:
            d[_VFL_SUM_SRC[src]] = values[src]
        d["Sum of GD_YTD_%"] = _vfl_gd_frac(values["YTD TY"], values["YTD LY"])
        d["Sum of GD_MTD_%"] = _vfl_gd_frac(values["MTD TY"], values["MTD LY"])
        rows.append(d)
        types.append("split")

    def comparable_throughout(label) -> bool:
        """A start alone is not enough — the span has to actually exist."""
        s, e = _l2l_start.get(label), _l2l_end.get(label)
        return s is not None and e is not None and s <= e

    l2l_rows, non_l2l_rows = [], []       # for the footer summary

    for region in [r for r in _REGION_ORDER if r in sb["Region"].unique()]:
        rdf = sb[sb["Region"] == region]
        r_pend = region
        for mloc in sorted(rdf["Master Location"].dropna().unique()):
            mdf = rdf[rdf["Master Location"] == mloc]
            m_pend = mloc
            for code in sorted(c for c in mdf["Store Code"].dropna().unique()):
                cdf = mdf[mdf["Store Code"] == code]
                c_pend = str(int(code))
                for gender in ["MEN", "WOMEN"]:
                    gdf = cdf[cdf["Gender"] == gender].sort_values(
                        by="Brand", key=lambda s: s.map(
                            {b: i for i, b in enumerate(BRANDLINE_VFL_ORDER)}).fillna(99))
                    if gdf.empty:
                        continue
                    g_pend = gender
                    for _, br in gdf.iterrows():
                        emit(r_pend, m_pend, c_pend, g_pend, br["Brand"],
                             br["Location"], br["DOO"], rowsum(br), "store")
                        r_pend = m_pend = c_pend = g_pend = ""
                    emit("", "", "", f"{gender} Total", "", "", "", sums(gdf), "storetotal")
                # The store's like-to-like halves sit between its gender totals
                # and its own total, so the total still closes the block.
                _label = str(cdf[COL_STORE_LABEL].iloc[0])
                _whole = sums(cdf)
                _halves = _split_halves(_label, _whole)
                for _tag, _vals in _halves:
                    emit_split(_tag, str(cdf["Location"].iloc[0]), _vals)
                    (non_l2l_rows if _tag == "NO L2L" else l2l_rows).append(_vals)
                if not _halves:
                    (l2l_rows if comparable_throughout(_label)
                     else non_l2l_rows).append(_whole)
                emit("", "", f"{int(code)} Total", "", "", "", "", _whole, "subtotal")
            # Location totals get their own type so consumers can tell them
            # apart from the {code} Total rows above (both used to be
            # "subtotal"): the workbook colours them differently, and the PDF's
            # under-50k day-sale rule must fire on the STORE total only.
            emit("", f"{mloc} Total", "", "", "", "", "", sums(mdf), "loctotal")
        emit(f"{region} Total", "", "", "", "", "", "", sums(rdf), "block")
    emit("Grand Total", "", "", "", "", "", "", sums(sb), "grand")

    # ★ THE FOOTER THAT MAKES THE SHEET SAY ITS OWN LIKE TO LIKE. Summing the
    # comparable halves gives the figure the Executive Snapshot prints, to the
    # rupee — the sheet shows its working instead of quietly disagreeing with
    # page 1. Same two lines, same names, as the portfolio sheet's footer.
    for label, part in (("LIKE TO LIKE", l2l_rows), ("NO L2L", non_l2l_rows)):
        if not part:
            continue
        d = dict.fromkeys(VFL_GD_COLS, "")
        for c in VFL_GD_MONEY:
            d[c] = float("nan")
        d["Region"] = label
        tot = {k: sum(float(p.get(k, 0.0) or 0.0) for p in part)
               for k in _split_src}
        for src in _split_src:
            d[_VFL_SUM_SRC[src]] = tot[src]
        d["Sum of GD_YTD_%"] = _vfl_gd_frac(tot["YTD TY"], tot["YTD LY"])
        d["Sum of GD_MTD_%"] = _vfl_gd_frac(tot["MTD TY"], tot["MTD LY"])
        rows.append(d)
        types.append("summary")

    return pd.DataFrame(rows, columns=VFL_GD_COLS), types


# --------------------------------------------------------------------------- #
# VFL_GENDER sheet (exact) — gender contribution %. Region → Master Location →
# Location → Store → gender rows, {code} Total = store share of its location,
# region totals = region share of grand; plus a Region × Gender summary block.
# --------------------------------------------------------------------------- #
VFL_GENDER_COLS = ["Region", "Master Location", "LOCATION", "STORE CODE",
                   "MEN/WOMEN/KIDS", "Sum of MTD_TY", "GENDER CONTRIBUTION MTD",
                   "Sum of YTD_TY", "GENDER CONTRIBUTION YTD"]
VFL_GENDER_MONEY = ["Sum of MTD_TY", "Sum of YTD_TY",
                     "Sum of TTM SALES"]
VFL_GENDER_PCT = ["GENDER CONTRIBUTION MTD", "GENDER CONTRIBUTION YTD"]
VFL_GSUM_COLS = ["Region", "MEN/WOMEN/KIDS", "Sum of MTD_TY", "GENDER CONTRIBUTION MTD",
                 "Sum of YTD_TY", "GENDER CONTRIBUTION YTD"]


def vfl_gender_report(df: pd.DataFrame, asof=None):
    """The VFL_GENDER sheet, 1:1. Returns (main_df, main_rtypes, summary_df,
    summary_rtypes). Contribution %: gender share within store; the {code} Total
    row = that store's share of its LOCATION (so multi-store locations split);
    region totals = region share of the grand. Summary = Region × Gender."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    d = df.copy()
    d["_g"] = brand_gender(d)
    mcur, _ = report_frames(d, "MTD", asof=asof)
    ycur, _ = report_frames(d, "YTD", asof=asof)
    master = load_store_master()[["tableau_name", "code", "location", "city", "region"]]

    def agg(f):
        return f.groupby([COL_STORE_LABEL, "_g"])[COL_AMOUNT].sum()

    t = pd.DataFrame({"mtd": agg(mcur), "ytd": agg(ycur)}).fillna(0.0).reset_index()
    t = t.merge(master, left_on=COL_STORE_LABEL, right_on="tableau_name", how="left")
    t = t[t["code"].notna()].copy()
    t["code"] = pd.to_numeric(t["code"], errors="coerce").astype(int)
    t["Region"] = t["region"]
    t["Master Location"] = t["city"].astype(str).str.title().replace({"Kolkata": "Kolkatta"})
    t["Location"] = t["location"]
    t["__g"] = t["_g"].map({g: i for i, g in enumerate(GENDER_ORDER)}).fillna(9)

    grand_mtd, grand_ytd = t["mtd"].sum(), t["ytd"].sum()
    st_mtd = t.groupby("code")["mtd"].transform("sum")
    st_ytd = t.groupby("code")["ytd"].transform("sum")
    loc_key = ["Region", "Master Location", "Location"]
    loc_mtd = t.groupby(loc_key)["mtd"].transform("sum")
    loc_ytd = t.groupby(loc_key)["ytd"].transform("sum")
    t["g_mtd"] = t["mtd"] / st_mtd.replace(0, pd.NA) * 100          # gender within store
    t["g_ytd"] = t["ytd"] / st_ytd.replace(0, pd.NA) * 100
    t["sl_mtd"] = st_mtd / loc_mtd.replace(0, pd.NA) * 100          # store within location
    t["sl_ytd"] = st_ytd / loc_ytd.replace(0, pd.NA) * 100

    rows, types = [], []

    def emit(reg, mloc, loc, code, gender, mtd, gmtd, ytd, gytd, rtype):
        rows.append({"Region": reg, "Master Location": mloc, "LOCATION": loc,
                     "STORE CODE": code, "MEN/WOMEN/KIDS": gender,
                     "Sum of MTD_TY": mtd, "GENDER CONTRIBUTION MTD": gmtd,
                     "Sum of YTD_TY": ytd, "GENDER CONTRIBUTION YTD": gytd})
        types.append(rtype)

    for region in [r for r in _REGION_ORDER if r in t["Region"].unique()]:
        rdf = t[t["Region"] == region]
        r_pend = region
        for mloc in sorted(rdf["Master Location"].dropna().unique()):
            mdf = rdf[rdf["Master Location"] == mloc]
            m_pend = mloc
            # Locations ordered by their lowest store code (keeps same-location
            # stores adjacent, matching the workbook's pivot order).
            loc_order = mdf.groupby("Location")["code"].min().sort_values().index
            for loc in loc_order:
                ldf = mdf[mdf["Location"] == loc]
                l_pend = loc
                for code in sorted(ldf["code"].unique()):
                    cdf = ldf[ldf["code"] == code].sort_values("__g")
                    c_pend = str(code)
                    for _, rr in cdf.iterrows():
                        emit(r_pend, m_pend, l_pend, c_pend, rr["_g"], rr["mtd"],
                             rr["g_mtd"], rr["ytd"], rr["g_ytd"], "store")
                        r_pend = m_pend = l_pend = c_pend = ""
                    emit("", "", "", f"{code} Total", "", cdf["mtd"].sum(),
                         cdf["sl_mtd"].iloc[0], cdf["ytd"].sum(), cdf["sl_ytd"].iloc[0],
                         "subtotal")
        emit(f"{region} Total", "", "", "", "", rdf["mtd"].sum(),
             rdf["mtd"].sum() / grand_mtd * 100 if grand_mtd else 0,
             rdf["ytd"].sum(), rdf["ytd"].sum() / grand_ytd * 100 if grand_ytd else 0,
             "block")
    main = pd.DataFrame(rows, columns=VFL_GENDER_COLS)

    # ---- Region × Gender summary ----
    srows, stypes = [], []

    def semit(reg, gender, mtd, gmtd, ytd, gytd, rtype):
        srows.append({"Region": reg, "MEN/WOMEN/KIDS": gender, "Sum of MTD_TY": mtd,
                      "GENDER CONTRIBUTION MTD": gmtd, "Sum of YTD_TY": ytd,
                      "GENDER CONTRIBUTION YTD": gytd})
        stypes.append(rtype)

    for region in [r for r in _REGION_ORDER if r in t["Region"].unique()]:
        rdf = t[t["Region"] == region]
        rmtd, rytd = rdf["mtd"].sum(), rdf["ytd"].sum()
        for g in GENDER_ORDER:
            gdf = rdf[rdf["_g"] == g]
            if gdf.empty:
                continue
            semit(region, g, gdf["mtd"].sum(),
                  gdf["mtd"].sum() / rmtd * 100 if rmtd else 0, gdf["ytd"].sum(),
                  gdf["ytd"].sum() / rytd * 100 if rytd else 0, "store")
        semit(f"{region} Total", "", rmtd, rmtd / grand_mtd * 100 if grand_mtd else 0,
              rytd, rytd / grand_ytd * 100 if grand_ytd else 0, "block")
    semit("Grand Total", "", grand_mtd, 100.0, grand_ytd, 100.0, "grand")
    summary = pd.DataFrame(srows, columns=VFL_GSUM_COLS)
    return main, types, summary, stypes


def loc_store_gd(df: pd.DataFrame, asof=None, anchor_takeover: bool = True) -> pd.DataFrame:
    """Store G/D tagged with city, for the LOCATION-WISE report (the app groups
    by city with per-city subtotals). Mirrors the source LOC_WISE_GD sheet —
    new-this-FY stores (e.g. Bengaluru) show no last year, to tally with the report."""
    out = _gd_by(df, [COL_STORE_LABEL], asof=asof, anchor_takeover=anchor_takeover,
                 new_store_no_ly=True)
    master = load_store_master()[["tableau_name", "code", "location", "city", "region"]]
    out = out.merge(master, left_on=COL_STORE_LABEL, right_on="tableau_name", how="left")
    out["code"] = pd.to_numeric(out["code"], errors="coerce")
    out["__r"] = out["region"].map({r: i for i, r in enumerate(_REGION_ORDER)}).fillna(9)
    out = out.sort_values(["city", "__r", "code"]).reset_index(drop=True)
    out = out.rename(columns={"city": "City", "region": "Region",
                              "code": "Store Code", "location": "Location"})
    return out[["City", "Region", "Store Code", "Location"] + _GD_OUT_COLS]


def store_lfl(df: pd.DataFrame, asof=None, anchor_takeover: bool = True) -> pd.DataFrame:
    """Store G/D with a like-for-like class derived from each store's FIRST sale
    date in the data: 'Like-for-like' (open before last FY), 'Opened last FY'
    (partial LY) or 'New this FY' (no LY). Mirrors the source NEW/OLD FY/PY/NA
    split, so same-store growth can be read apart from new-store growth."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    cur_start = pd.Timestamp(fy_year, 4, 1)
    prior_start = pd.Timestamp(fy_year - 1, 4, 1)
    first = df.groupby(COL_STORE_LABEL)["date"].min()

    def _cls(store):
        fs = first.get(store)
        if pd.isna(fs):
            return "New this FY"
        fs = pd.Timestamp(fs)
        if fs >= cur_start:
            return "New this FY"
        if fs >= prior_start:
            return "Opened last FY"
        return "Like-for-like"

    out = _gd_by(df, [COL_STORE_LABEL], asof=asof, anchor_takeover=anchor_takeover)
    out["Class"] = out[COL_STORE_LABEL].map(_cls)
    master = load_store_master()[["tableau_name", "code", "location", "city", "region"]]
    out = out.merge(master, left_on=COL_STORE_LABEL, right_on="tableau_name", how="left")
    out["code"] = pd.to_numeric(out["code"], errors="coerce")
    _corder = {"Like-for-like": 0, "Opened last FY": 1, "New this FY": 2}
    out["__r"] = out["region"].map({r: i for i, r in enumerate(_REGION_ORDER)}).fillna(9)
    out["__c"] = out["Class"].map(_corder).fillna(9)
    out = out.sort_values(["__r", "__c", "code"]).reset_index(drop=True)
    out = out.rename(columns={"region": "Region", "code": "Store Code",
                              "location": "Location", "city": "City"})
    return out[["Region", "Class", "Store Code", "Location", "City"] + _GD_OUT_COLS]


def monthly_contribution(df: pd.DataFrame, asof=None) -> pd.DataFrame:
    """Month-by-month sales for the current fiscal year with each month's share
    of the YTD total, split East & NE / South and each region's share of the
    month. Mirrors the source MW_DATA monthly-contribution view."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    cur = df[(df["date"] >= pd.Timestamp(fy_year, 4, 1)) & (df["date"] <= asof)].copy()
    cur["_m"] = cur["date"].values.astype("datetime64[M]")
    piv = cur.pivot_table(index="_m", columns=COL_REGION, values=COL_AMOUNT,
                          aggfunc="sum", fill_value=0.0).sort_index()
    for r in _REGION_ORDER:
        if r not in piv.columns:
            piv[r] = 0.0
    piv["Total"] = piv[_REGION_ORDER].sum(axis=1)
    grand = piv["Total"].sum()
    tot = piv["Total"].replace(0, pd.NA)
    return pd.DataFrame({
        "Month": [pd.Timestamp(m).strftime("%b %Y") for m in piv.index],
        "East & NE": piv["East & NE"].values,
        "South": piv["South"].values,
        "Total Sale": piv["Total"].values,
        "Month Contrib %": (piv["Total"] / grand * 100).values if grand else 0.0,
        "East & NE %": (piv["East & NE"] / tot * 100).values,
        "South %": (piv["South"] / tot * 100).values,
    })


def store_productivity(df: pd.DataFrame, asof=None, anchor_takeover: bool = True) -> pd.DataFrame:
    """Per-store productivity: YTD sales, floor area (sq ft), operational days,
    average daily sale, sales per sq ft, and sales per sq ft per day. Mirrors the
    source AVG BRAND WISE / PSFPD sheet (area from store_master.sb)."""
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    fy_year = asof.year if asof.month >= 4 else asof.year - 1
    fy_start = pd.Timestamp(fy_year, 4, 1)
    out = _gd_by(df, [COL_STORE_LABEL], asof=asof, anchor_takeover=anchor_takeover,
                 new_store_no_ly=True)
    master = load_store_master()[["tableau_name", "code", "location", "city",
                                  "region", "sb", "ca", "takeover_date"]]
    out = out.merge(master, left_on=COL_STORE_LABEL, right_on="tableau_name", how="left")
    out["code"] = pd.to_numeric(out["code"], errors="coerce")
    out["SBA"] = pd.to_numeric(out["sb"], errors="coerce")
    out["CA"] = pd.to_numeric(out["ca"], errors="coerce")
    tk = pd.to_datetime(out["takeover_date"], errors="coerce")
    start = tk.where(tk > fy_start, fy_start)
    out["Op Days"] = ((asof - start).dt.days + 1).clip(lower=1)
    yt = out["YTD TY"]
    out["Avg Day Sale"] = yt / out["Op Days"]
    out["Avg Month Sale"] = out["Avg Day Sale"] * 30.0
    # PSFPD (per sq ft per day) is on CARPET area in the source sheet
    out["PSFPD"] = out["Avg Day Sale"] / out["CA"].replace(0, pd.NA)
    out["__r"] = out["region"].map({r: i for i, r in enumerate(_REGION_ORDER)}).fillna(9)
    out = out.sort_values(["__r", "code"]).reset_index(drop=True)
    out = out.rename(columns={"region": "Region", "code": "Store Code",
                              "location": "Location", "city": "City"})
    return out[["Region", "Store Code", "Location", "City", "SBA", "CA",
                "YTD LY", "YTD TY", "GD YTD %", "Op Days", "Avg Day Sale",
                "Avg Month Sale", "PSFPD"]]


DAY_REPORT_COLS = ["Region", "STORE CODE", "LOCATION", "Same Day LY", "Same Date LY"]


def day_sales_ly_report(df: pd.DataFrame, day):
    """Per-store day-sales on the two last-year reference days of `day`:
      - Same Day LY  = same weekday a year ago  (day − 364 days = 52 weeks)
      - Same Date LY = same calendar date a year ago (day − 1 year)
    They differ because a year isn't a whole number of weeks. Region-grouped
    with subtotals + grand total. South's references come from its retained
    pre-takeover history (see _apply_takeover_filter)."""
    day = pd.Timestamp(day)
    same_day = day - pd.Timedelta(days=364)
    same_date = day - pd.DateOffset(years=1)
    g = lambda d: df[df["date"] == d].groupby(COL_STORE_LABEL)[COL_AMOUNT].sum()
    sd, dt = g(same_day), g(same_date)
    master = load_store_master()
    present = set(df[COL_STORE_LABEL].dropna().unique())
    master = master[master["tableau_name"].isin(present)].copy()
    if master.empty:
        return pd.DataFrame(columns=DAY_REPORT_COLS), []
    master["_rord"] = master["region"].map(
        {k: i for i, k in enumerate(_REGION_ORDER)}).fillna(99)
    master["_code"] = pd.to_numeric(master["code"], errors="coerce")
    master = master.sort_values(["_rord", "_code"])

    rows, types = [], []

    def _store_row(r):
        n = r["tableau_name"]
        return {"Region": r["region"], "STORE CODE": r["code"],
                "LOCATION": r["location"], "Same Day LY": float(sd.get(n, 0.0)),
                "Same Date LY": float(dt.get(n, 0.0))}

    def _total_row(label, sub):
        return {"Region": label, "STORE CODE": "", "LOCATION": "",
                "Same Day LY": sub["Same Day LY"].sum(),
                "Same Date LY": sub["Same Date LY"].sum()}

    all_rows = []
    for region, grp in master.groupby("region", sort=False):
        rrows = [_store_row(r) for _, r in grp.iterrows()]
        for sr in rrows:
            rows.append(sr); types.append("store")
        rdf = pd.DataFrame(rrows); all_rows.append(rdf)
        rows.append(_total_row(f"{region} Total", rdf)); types.append("subtotal")
    grand = pd.concat(all_rows, ignore_index=True)
    rows.append(_total_row("Grand Total", grand)); types.append("grand")
    return pd.DataFrame(rows, columns=DAY_REPORT_COLS), types


# --------------------------------------------------------------------------- #
# Degrowth drivers — why a store is down, not just that it is
# --------------------------------------------------------------------------- #
DRIVERS_PERIODS = ("YTD", "MTD")
DRIVERS_PCT = ["Degrowth %"]


def drivers_money(kind: str = "YTD"):
    return [f"{kind} LY", f"{kind} TY", "Shortfall"]


def drivers_cols(kind: str = "YTD"):
    return ["DATE", "Region", "STORE CODE", "LOCATION", "Brand",
            "Division", "Section", "Department",
            f"{kind} LY", f"{kind} TY", "Shortfall", "Degrowth %"]
# Division (31) -> Section (160) -> Department (612). The hierarchy nests: no
# department spans two sections, so the three read as one path rather than three
# independent tags. `level` picks which of them the product rows are grouped at;
# the columns above it are filled in as context, the ones below left blank.
DRIVERS_LEVELS = {"division": [COL_DIVISION],
                  "section": [COL_DIVISION, COL_SECTION],
                  "department": [COL_DIVISION, COL_SECTION, COL_DEPARTMENT]}


def degrowth_drivers(df: pd.DataFrame, asof=None, kind: str = "YTD",
                     top_products: int = 3, products_under: str = "worst",
                     level: str = "division", only_declining: bool = True,
                     stores_only=None, anchor_takeover: bool = True,
                     both_ways: bool = False):
    """Every declining store, decomposed: products, then brand totals, then the
    store total beneath them.

    A store total says a shop is down; it does not say what to do about it. The
    shortfall is broken out in RUPEES, which is the form that adds up — the
    brand totals sum to the store total, so the attribution is complete and can
    be checked rather than taken on trust. Percentages cannot do that, and they
    over-weight small lines: a ₹1L brand collapsing reads as -80% beside a ₹20L
    brand losing -15%, which is six times the money.

    It also exposes OFFSETS that a store total hides. M.G. Road and Siliguri
    both look mild at about -7%, but Siliguri is Twamev -₹17.8L partly masked by
    Mohey +₹9.5L — a large problem and a large success, not a small problem.

    Totals sit BELOW the rows they summarise, matching the review workbook:
    products, then that brand's total, then the store's total last. The identity
    columns repeat on every row, so any row still identifies its own store once
    the table is sorted or filtered.

    `products_under`: "every" breaks out every brand including those that GREW
    (so an offsetting gain is visible, not just its net effect); "all" only
    declining brands; "worst" only the worst-declining one.

    ★ `both_ways` — TAKE THE TOP `top_products` IN EACH DIRECTION, not just the
    worst. The rows are sorted most-negative-first and truncated with `head`,
    so `top_products` has always meant "the N worst", never "the N biggest
    movers". For a sheet that prints ONE table of losses that is right. For the
    driver sheet, which prints a falling table AND a growing table, it starves
    the second one: growth could only appear if it survived a worst-first cut.
    Measured on 30 Aug, at ten per brand, the month hid Rs 36.1 lakh of growth
    at Jayanagar and Rs 11.1 lakh at Commercial Street — invisible, while the
    losses beside them were listed in full.

    Off by default, because every other caller wants exactly the worst.

    Returns (display_df, row_types) — products plain, brand totals 'subtotal',
    store totals 'block'.
    """
    asof = as_of(df) if asof is None else pd.Timestamp(asof)
    # MTD answers a different question from YTD: whether a decline is history
    # or happening right now. A store can be badly down on the year while
    # trading level this month, or the reverse — and those need opposite
    # responses.
    kind = kind if kind in DRIVERS_PERIODS else "YTD"
    cur, pri = report_frames(df, kind, asof=asof, anchor_takeover=anchor_takeover)
    master = load_store_master().set_index("tableau_name")

    def total(frame, keys):
        return frame.groupby(keys)[COL_AMOUNT].sum()

    stores = pd.DataFrame({"ty": total(cur, [COL_STORE_LABEL]),
                           "ly": total(pri, [COL_STORE_LABEL])}).fillna(0.0)
    stores["short"] = stores["ty"] - stores["ly"]
    # `only_declining` is right for the group view — a watchlist of stores with
    # a problem. It is wrong for a per-store snapshot sent to that store's own
    # manager, where a good month should read as a good month rather than the
    # manager receiving nothing. There "Shortfall" is simply a surplus.
    if only_declining:
        stores = stores[stores["short"] < 0]
    if stores_only is not None:
        stores = stores[stores.index.isin(set(stores_only))]
    stores = stores.sort_values("short")

    br_c, br_p = total(cur, [COL_STORE_LABEL, COL_BRAND]), total(pri, [COL_STORE_LABEL, COL_BRAND])
    prod_keys = DRIVERS_LEVELS.get(level, DRIVERS_LEVELS["division"])
    dv_c = total(cur, [COL_STORE_LABEL, COL_BRAND] + prod_keys)
    dv_p = total(pri, [COL_STORE_LABEL, COL_BRAND] + prod_keys)

    def _frame(c, p, key):
        f = pd.DataFrame({"ty": c.get(key, pd.Series(dtype=float)),
                          "ly": p.get(key, pd.Series(dtype=float))}).fillna(0.0)
        f["short"] = f["ty"] - f["ly"]
        return f.sort_values("short")

    date_txt = f"{asof:%d-%m-%Y}"
    rows, types = [], []
    ident = {}

    def emit(r, brand, path, rtype):
        # No prior-year sales means there is no growth rate, only a value.
        # Reporting that as 0% or infinity would both mislead.
        gd = (r["ty"] - r["ly"]) / r["ly"] * 100 if r["ly"] else None
        # A bare string must not be iterated into characters — that silently
        # spreads "Total" across the three columns as T / o / t.
        path = [path] if isinstance(path, str) else list(path)
        path = [str(x) for x in path] + [""] * (3 - len(path))
        rows.append({**ident, "Brand": brand,
                     "Division": path[0], "Section": path[1],
                     "Department": path[2],
                     f"{kind} LY": r["ly"], f"{kind} TY": r["ty"],
                     "Shortfall": r["short"], "Degrowth %": gd})
        types.append(rtype)

    for store, s in stores.iterrows():
        m = master.loc[store] if store in master.index else None
        # Identity repeats on EVERY row rather than sitting in a header. It
        # costs width but the table stays sortable and filterable, and a row
        # lifted out of context still says which store it belongs to.
        ident = {"DATE": date_txt,
                 "Region": "" if m is None else str(m.get("region", "")),
                 "STORE CODE": "" if m is None else str(m.get("code", "")),
                 "LOCATION": str(store)}

        brands = _frame(br_c, br_p, store)
        worst = brands.index[0] if len(brands) else None
        for brand, b in brands.iterrows():
            show = (products_under == "every"
                    or (products_under == "all" and b["short"] < 0)
                    or (products_under == "worst" and brand == worst
                        and b["short"] < 0))
            if show:
                _dv = _frame(dv_c, dv_p, (store, brand))
                if both_ways and len(_dv) > top_products:
                    # the worst N and the best N — sorted ascending, so head
                    # and tail. A division cannot be both, and `head`/`tail`
                    # overlapping is why the length is checked first.
                    _dv = pd.concat([_dv.head(top_products),
                                     _dv.tail(top_products)])
                    _dv = _dv[~_dv.index.duplicated()].sort_values("short")
                else:
                    _dv = _dv.head(top_products)
                for div, d in _dv.iterrows():
                    # Under "every" a growing brand is shown too, so its rows
                    # are whatever moved most — that is how an offset becomes
                    # visible rather than just its net effect.
                    # A line with nothing on either side is noise, not detail.
                    if abs(d["ly"]) < 1 and abs(d["ty"]) < 1:
                        continue
                    if d["short"] < 0 or products_under == "every":
                        emit(d, str(brand),
                             div if isinstance(div, tuple) else (div,), "store")
            # 'subtotal' rather than 'storetotal': the latter is the palest
            # tier and barely reads against white, and a brand total is the row
            # a reader scans for. Store totals stay blue, so the two tiers stay
            # distinct.
            emit(b, str(brand), ("Total",), "subtotal")
        emit(s, "TOTAL", (), "block")

    out = pd.DataFrame(rows, columns=drivers_cols(kind))
    # Only keep the product columns the chosen level actually fills. Rendering
    # Section and Department as permanently blank at Division level just asks
    # the reader to wonder what is missing.
    depth = len(DRIVERS_LEVELS.get(level, DRIVERS_LEVELS["division"]))
    drop = [c for c in ("Division", "Section", "Department")[depth:]]
    return out.drop(columns=drop), types
