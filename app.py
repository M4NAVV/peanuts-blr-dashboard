"""
Peanuts (Manyavar) — Grand Kamraj Road, Bengaluru
Self-serve sales KPI dashboard.

Reads the daily sales export (published Google Sheet in production, local Excel
in development). Every viewer can choose which KPIs to see, switch the time
granularity (day → week → month → quarter → year), and compose their own layout
of charts in the "Build your view" tab. Auto-refreshes on a short cache TTL, so
updating the source sheet updates the dashboard with no redeploy.
"""

from __future__ import annotations

import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import loader as L

st.set_page_config(
    page_title="Peanuts Retail — Sales Dashboard",
    page_icon="🥜",
    layout="wide",
    initial_sidebar_state="auto",  # collapses on mobile, open on desktop
)

# --- Brand palette (Manyavar-ish maroon / gold) ---------------------------- #
MAROON = "#7A1F2B"
GOLD = "#C9A24B"
INK = "#2B2B2B"
SEQ = ["#7A1F2B", "#C9A24B", "#A8434F", "#E0C07A", "#5B6770", "#9AA5AD", "#3F5765",
       "#D98C5F", "#6B8E7F", "#B0454A"]

st.markdown(
    f"""
    <style>
      .stApp {{ background: #FAF7F2; }}
      h1, h2, h3 {{ color: {MAROON}; }}
      [data-testid="stMetricValue"] {{ color: {MAROON}; font-weight: 700; }}
      [data-testid="stMetricLabel"] {{ color: {INK}; }}
      div[data-testid="stMetric"] {{
        background: #FFFFFF; border: 1px solid #ECE4D6; border-radius: 12px;
        padding: 14px 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
      }}

      /* ---- Mobile responsiveness (phones / narrow screens) ---- */
      @media (max-width: 640px) {{
        /* Let column rows wrap instead of squishing side by side */
        [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; }}
        [data-testid="stHorizontalBlock"] > div {{
          min-width: 46% !important; flex: 1 1 46% !important;
        }}
        /* Tighter page padding + smaller headings on mobile */
        .block-container {{ padding: 0.6rem 0.7rem !important; }}
        [data-testid="stMetricValue"] {{ font-size: 1.15rem !important; }}
        [data-testid="stMetricLabel"] {{ font-size: 0.72rem !important; }}
        div[data-testid="stMetric"] {{ padding: 8px 10px; }}
        h1 {{ font-size: 1.4rem !important; }}
        h2, h3 {{ font-size: 1.1rem !important; }}
        .stTabs [data-baseweb="tab"] {{ padding: 6px 8px; font-size: 0.8rem; }}
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Data loading (cached; TTL gives the "auto-update" behaviour)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=1800, show_spinner="Loading sales data…")
def get_data() -> pd.DataFrame:
    return L.load_data()


def inr(x: float) -> str:
    """Compact Indian rupees: Cr / L / K."""
    if x is None or pd.isna(x):
        return "—"
    x = float(x)
    if abs(x) >= 1e7:
        return f"₹{x/1e7:.2f} Cr"
    if abs(x) >= 1e5:
        return f"₹{x/1e5:.2f} L"
    if abs(x) >= 1e3:
        return f"₹{x/1e3:.1f} K"
    return f"₹{x:,.0f}"


def fmt_in(x, dec: int = 2) -> str:
    """Indian digit grouping (1,69,709.00) with fixed decimals."""
    if x is None or pd.isna(x):
        return ""
    neg = x < 0
    x = abs(float(x))
    s = f"{x:.{dec}f}"
    intpart, _, frac = s.partition(".")
    if len(intpart) > 3:
        head, tail = intpart[:-3], intpart[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        intpart = head + "," + tail
    out = intpart + ("." + frac if dec else "")
    return ("-" if neg else "") + out


def fmt_metric(value: float, is_money: bool) -> str:
    if pd.isna(value):
        return "—"
    if is_money:
        return inr(value)
    if value >= 1000 or float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


try:
    df_all = get_data()
except FileNotFoundError as e:
    st.error(str(e))
    st.info(
        "**To get started:** drop the sales export at `data/sales.xlsx`, or set "
        "`SHEET_CSV_URL` in Streamlit secrets to a published Google Sheet."
    )
    st.stop()

fresh = L.data_freshness(df_all)

# --------------------------------------------------------------------------- #
# Sidebar — filters + view settings
# --------------------------------------------------------------------------- #
n_stores_all = df_all[L.COL_STORE_LABEL].nunique()
st.sidebar.title("🥜 Peanuts Retail")
st.sidebar.caption(f"All {n_stores_all} stores · Bengaluru + East India")

min_d, max_d = fresh["min_date"].date(), fresh["max_date"].date()
date_range = st.sidebar.date_input(
    "Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d,
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_d, end_d = date_range
else:
    start_d, end_d = min_d, max_d

stores = sorted(df_all[L.COL_STORE_LABEL].dropna().unique().tolist())
sel_store = st.sidebar.multiselect("Store", stores, default=[],
                                   help="Leave empty for all stores")
divisions = sorted(df_all[L.COL_DIVISION].dropna().unique().tolist())
sel_div = st.sidebar.multiselect("Division", divisions, default=[])
mwc_opts = sorted(df_all[L.COL_MWC].dropna().unique().tolist())
sel_mwc = st.sidebar.multiselect("Men / Women / Child", mwc_opts, default=[])

st.sidebar.markdown("### View settings")
granularity = st.sidebar.radio(
    "Time granularity", ["Day", "Week", "Month", "Quarter", "Year"],
    index=2, horizontal=True,
    help="Drives the trend charts and the default in Build-your-view.",
)

# Apply filters
mask = (df_all["date"].dt.date >= start_d) & (df_all["date"].dt.date <= end_d)
if sel_store:
    mask &= df_all[L.COL_STORE_LABEL].isin(sel_store)
if sel_div:
    mask &= df_all[L.COL_DIVISION].isin(sel_div)
if sel_mwc:
    mask &= df_all[L.COL_MWC].isin(sel_mwc)
df = df_all[mask].copy()

# Executive YoY needs full history (both years), so it honors the store /
# division / M-W-C filters but NOT the sidebar date range.
mask_exec = pd.Series(True, index=df_all.index)
if sel_store:
    mask_exec &= df_all[L.COL_STORE_LABEL].isin(sel_store)
if sel_div:
    mask_exec &= df_all[L.COL_DIVISION].isin(sel_div)
if sel_mwc:
    mask_exec &= df_all[L.COL_MWC].isin(sel_mwc)
df_exec = df_all[mask_exec].copy()

st.sidebar.markdown("---")
st.sidebar.caption(
    f"**Data through:** {fresh['max_date']:%d %b %Y}  \n**Rows:** {fresh['rows']:,}"
)
if st.sidebar.button("🔄 Refresh data now"):
    get_data.clear()
    st.rerun()

if df.empty:
    st.warning("No data for the selected filters.")
    st.stop()


# --------------------------------------------------------------------------- #
# Generic chart renderer (shared by Build-your-view and curated tabs)
# --------------------------------------------------------------------------- #
CHART_TYPES = ["Bar", "Horizontal bar", "Line", "Area", "Pie / Donut",
               "Treemap", "Heatmap (pivot)", "Table"]


def draw_view(cfg: dict, height: int = 360):
    """Render one configured view (metric × dimension[s] × chart type)."""
    view = L.build_view(
        df, cfg["metric"], cfg["group_dim"],
        split_dim=cfg.get("split_dim"), top=cfg.get("top"),
    )
    data = view["data"].copy()
    is_money = view["is_money"]
    order = view["order"]
    chart = cfg["chart"]
    has_split = view["split_dim"] is not None

    if data.empty:
        st.info("No data for this view.")
        return

    # Keep categorical/time order consistent.
    data["group"] = pd.Categorical(data["group"], categories=order, ordered=True)
    data = data.sort_values("group")

    color = "split" if has_split else None

    # Table branch first — it keeps full unscaled rupee values (Indian grouped).
    if chart == "Table":
        if has_split:
            pivot = data.pivot_table(index="group", columns="split", values="value",
                                     aggfunc="sum", observed=True).reset_index()
            pivot = pivot.rename(columns={"group": cfg["group_dim"]})
            if is_money:
                for c in pivot.columns[1:]:
                    pivot[c] = pivot[c].map(lambda v: fmt_in(v, 2))
            st.dataframe(pivot, use_container_width=True, hide_index=True)
        else:
            t = data[["group", "value"]].rename(columns={"group": cfg["group_dim"]})
            if is_money:
                t[view["metric"]] = t.pop("value").map(lambda v: fmt_in(v, 2))
                st.dataframe(t, use_container_width=True, hide_index=True)
            else:
                t = t.rename(columns={"value": view["metric"]})
                st.dataframe(
                    t, use_container_width=True, hide_index=True,
                    column_config={view["metric"]:
                                   st.column_config.NumberColumn(format="%.2f")},
                )
        return

    # Scale money into Indian units (₹ Cr / L / K) so axes never show millions.
    unit_lbl = ""
    if is_money:
        m = float(data["value"].abs().max() or 0)
        div, unit_lbl = (
            (1e7, "₹ Cr") if m >= 1e7 else
            (1e5, "₹ L") if m >= 1e5 else
            (1e3, "₹ K") if m >= 1e3 else (1.0, "₹")
        )
        data["value"] = data["value"] / div
    base = view["metric"].replace(" (₹)", "")
    axis_title = f"{base} ({unit_lbl})" if is_money else view["metric"]

    if chart in ("Bar", "Horizontal bar"):
        horizontal = chart == "Horizontal bar"
        fig = px.bar(
            data, x="value" if horizontal else "group",
            y="group" if horizontal else "value",
            color=color, orientation="h" if horizontal else "v",
            color_discrete_sequence=SEQ, barmode="group",
        )
        if horizontal:
            fig.update_layout(yaxis_title="", xaxis_title=axis_title)
            fig.update_yaxes(categoryorder="array", categoryarray=order[::-1])
            if is_money:
                fig.update_traces(hovertemplate="%{y}<br>%{x:.2f} " + unit_lbl + "<extra></extra>")
        else:
            fig.update_layout(xaxis_title="", yaxis_title=axis_title)
            if is_money:
                fig.update_traces(hovertemplate="%{x}<br>%{y:.2f} " + unit_lbl + "<extra></extra>")

    elif chart in ("Line", "Area"):
        fn = px.area if chart == "Area" else px.line
        fig = fn(data, x="group", y="value", color=color, markers=True,
                 color_discrete_sequence=SEQ)
        fig.update_layout(xaxis_title="", yaxis_title=axis_title)
        if is_money:
            fig.update_traces(hovertemplate="%{x}<br>%{y:.2f} " + unit_lbl + "<extra></extra>")

    elif chart == "Pie / Donut":
        agg = data.groupby("group", observed=True)["value"].sum().reset_index()
        fig = px.pie(agg, names="group", values="value", hole=0.5,
                     color_discrete_sequence=SEQ)
        if is_money:
            fig.update_traces(hovertemplate="%{label}<br>%{value:.2f} " + unit_lbl
                              + " (%{percent})<extra></extra>")

    elif chart == "Treemap":
        agg = data.groupby("group", observed=True)["value"].sum().reset_index()
        fig = px.treemap(agg, path=["group"], values="value",
                         color_discrete_sequence=SEQ)
        if is_money:
            fig.update_traces(
                texttemplate="%{label}<br>%{value:.2f} " + unit_lbl,
                hovertemplate="%{label}<br>%{value:.2f} " + unit_lbl + "<extra></extra>")

    elif chart == "Heatmap (pivot)":
        if not has_split:
            st.info("Heatmap needs a **split** dimension. Pick one, or choose another chart.")
            return
        pivot = data.pivot_table(index="split", columns="group", values="value",
                                 aggfunc="sum", observed=True)
        fig = px.imshow(pivot, color_continuous_scale="OrRd", aspect="auto",
                        labels=dict(color=axis_title))
        fig.update_layout(xaxis_title=cfg["group_dim"], yaxis_title=view["split_dim"])

    fig.update_layout(height=height, plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=10, b=10), legend_title_text=view["split_dim"] or "")
    st.plotly_chart(fig, use_container_width=True, key=cfg.get("_key"))


def exec_window_row(title, r):
    """One executive window (MTD/QTD/YTD…) as YoY metric cards, from a result dict."""
    cs, ce = r["cur_window"]
    ps, pe = r["prior_window"]
    rng = (f"`{cs:%d %b %Y} → {ce:%d %b %Y}` &nbsp;·&nbsp; "
           f"vs LY `{ps:%d %b %Y} → {pe:%d %b %Y}`") if cs is not None else ""
    st.markdown(f"**{title}** &nbsp; {rng}")
    cols = st.columns(4)
    specs = [
        ("Sales", r["cur"]["sales"], r["growth"]["sales"], True),
        ("Bills", r["cur"]["bills"], r["growth"]["bills"], False),
        ("Units", r["cur"]["units"], r["growth"]["units"], False),
        ("ATV", r["cur"]["atv"], r["growth"]["atv"], True),
    ]
    for col, (lbl, val, g, money) in zip(cols, specs):
        delta = f"{g:+.1f}% vs LY" if g is not None else None
        col.metric(lbl, inr(val) if money else f"{val:,}", delta)


# --------------------------------------------------------------------------- #
# Header + tabs
# --------------------------------------------------------------------------- #
st.title("Sales Dashboard")
scope = f"{len(sel_store)} store(s)" if sel_store else f"all {n_stores_all} stores"
st.caption(f"Peanuts Retail · {scope} · {start_d:%d %b %Y} → {end_d:%d %b %Y}")

(tab_report, tab_exec, tab_overview, tab_stores, tab_build, tab_trends, tab_cat,
 tab_staff, tab_cust, tab_merch) = st.tabs([
    "📋 MTD / YTD Report", "📊 Executive", "Overview", "🏬 Stores",
    "🔧 Build your view", "Trends", "Category mix", "Salespeople",
    "Customers", "Colors & sizes",
])

# =========================================================================== #
# MTD / YTD REPORT — region × store, year-on-year (the executive table)
# =========================================================================== #
with tab_report:
    st.subheader("Store-wise MTD / YTD — Year on Year")
    st.caption(
        "MTD = current month to date · YTD = financial year (Apr–Mar) to date · "
        "LY = same period last year · TY = this year · GD = growth/degrowth. "
        "All values in ₹, 2 decimals. Red = degrowth."
    )
    rep, rtypes = L.region_store_report(df_exec)

    compact = st.toggle(
        "📱 Compact view (best on mobile)", value=False,
        help="Shows the key columns only — easier to read on a phone.")
    if compact:
        show_cols = ["Region", "STORE CODE", "LOCATION",
                     "MTD TY", "GD MTD %", "YTD TY", "GD YTD %"]
    else:
        show_cols = list(rep.columns)
    rep_show = rep[show_cols]

    val_cols = [c for c in ["MTD LY", "MTD TY", "GD MTD Value",
                            "YTD LY", "YTD TY", "GD YTD Value"] if c in show_cols]
    pct_cols = [c for c in ["GD MTD %", "GD YTD %"] if c in show_cols]
    sign_cols = [c for c in ["GD MTD Value", "GD MTD %",
                             "GD YTD Value", "GD YTD %"] if c in show_cols]

    def _sign_color(v):
        if pd.isna(v):
            return ""
        return "color: #C0143C" if v < 0 else "color: #1B7F3B"

    def _row_bg(row):
        t = rtypes[row.name]
        if t == "subtotal":
            return ["background-color: #F4CCCC; font-weight: 700"] * len(row)
        if t == "grand":
            return ["background-color: #D9EAD3; font-weight: 700"] * len(row)
        # degrowing store → light red tint
        if pd.notna(row["GD YTD %"]) and row["GD YTD %"] < 0:
            return ["background-color: #FCE8E6"] * len(row)
        return [""] * len(row)

    styler = (
        rep_show.style
        .format({**{c: (lambda v: fmt_in(v, 2)) for c in val_cols},
                 **{c: (lambda v: f"{v:,.2f}%" if pd.notna(v) else "—")
                    for c in pct_cols}})
        .apply(_row_bg, axis=1)
        .map(_sign_color, subset=sign_cols)
    )
    st.dataframe(styler, use_container_width=True, hide_index=True,
                 height=(len(rep_show) + 1) * 36)

    st.download_button(
        "⬇ Download report (CSV)",
        rep.to_csv(index=False).encode(),
        file_name=f"peanuts_mtd_ytd_report_{L.as_of(df_exec):%Y%m%d}.csv",
        mime="text/csv",
    )

# =========================================================================== #
# EXECUTIVE — MTD / QTD / YTD, all year-on-year (fiscal year Apr–Mar)
# =========================================================================== #
with tab_exec:
    asof = L.as_of(df_exec)
    st.caption(
        f"Fiscal year **Apr–Mar**, each store counted from its **takeover date** "
        f"(South: 19 Apr 2025). All figures **year-on-year** vs the same period "
        f"last year. Data as of **{asof:%d %b %Y}**. "
        f"Respects the Store / Division filters (not the date range)."
    )
    wins = L.standard_windows(df_exec)

    exec_window_row("MTD — Month to date", L.window_yoy_takeover(df_exec, "MTD"))
    st.markdown("")
    exec_window_row("QTD — Quarter to date", L.window_yoy(df_exec, *wins["QTD"]))
    st.markdown("")
    exec_window_row("YTD — Financial year to date",
                    L.window_yoy_takeover(df_exec, "YTD"))
    st.markdown("")
    exec_window_row("Last completed month", L.window_yoy(df_exec, *wins["Last month"]))

    st.markdown("---")
    st.subheader("Monthly sales — this FY vs last FY")
    st.caption("Grouped by fiscal month (Apr→Mar). Bars appear per year where "
               "data exists; overlapping months show true YoY.")
    draw_view({"metric": "Sales (₹)", "group_dim": "Fiscal Month",
               "split_dim": "Financial Year", "chart": "Bar",
               "_key": "ex_yoy_month"}, height=400)

    st.markdown("---")
    st.subheader("Store YoY — YTD growth / degrowth")
    st.caption("This financial year to date vs same period last year, per store. "
               "Sorted to surface degrowth. “—” = no last-year data (new store).")
    sy = L.store_yoy(df_exec, "YTD").rename(columns={
        L.COL_STORE_LABEL: "Store", "cur": "YTD (₹)", "prior": "LY YTD (₹)",
        "growth": "Growth %"})
    sy = sy.sort_values("Growth %", ascending=True, na_position="last")
    st.dataframe(
        sy, use_container_width=True, hide_index=True,
        column_config={
            "YTD (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "LY YTD (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Growth %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

# =========================================================================== #
# OVERVIEW — selectable KPI cards + trend at chosen granularity
# =========================================================================== #
with tab_overview:
    scalar = L.all_scalar_kpis(df)
    default_cards = [
        "Sales (₹)", "Bills", "Units", "Active Stores",
        "Unique Customers", "Avg Bill Value / ATV (₹)",
        "Units per Bill / UPT", "Avg Selling Price / ASP (₹)",
    ]
    chosen = st.multiselect(
        "KPI cards to show", list(scalar.keys()), default=default_cards,
        help="Pick any KPIs — they update with the filters above.",
    )
    if chosen:
        cols = st.columns(4)
        for i, label in enumerate(chosen):
            value, is_money = scalar[label]
            cols[i % 4].metric(label, fmt_metric(value, is_money))

    st.markdown("---")
    st.subheader(f"Sales trend — by {granularity}")
    draw_view({"metric": "Sales (₹)", "group_dim": granularity, "chart": "Bar",
               "_key": "ov_trend"}, height=380)

    # Period-over-period deltas at the chosen granularity.
    tv = L.build_view(df, "Sales (₹)", granularity)["data"]
    if len(tv) >= 2:
        cur, prev = tv["value"].iloc[-1], tv["value"].iloc[-2]
        d1, d2 = st.columns(2)
        d1.metric(f"Latest {granularity.lower()} sales", inr(cur),
                  None if prev == 0 else f"{(cur-prev)/prev*100:+.1f}% vs previous")
        d2.metric(f"Periods in view ({granularity.lower()})", f"{len(tv)}")

# =========================================================================== #
# STORES — multi-store comparison
# =========================================================================== #
with tab_stores:
    st.subheader("Store comparison")
    rank_metric = st.selectbox(
        "Rank / compare stores by", list(L.METRICS.keys()), index=0,
        key="store_rank_metric",
    )
    colA, colB = st.columns([3, 2])
    with colA:
        st.caption("Leaderboard")
        draw_view({"metric": rank_metric, "group_dim": "Store",
                   "chart": "Horizontal bar", "top": 30, "_key": "st_bar"}, height=560)
    with colB:
        st.caption("Contribution")
        draw_view({"metric": rank_metric, "group_dim": "Store",
                   "chart": "Treemap", "top": 30, "_key": "st_tree"}, height=560)

    st.markdown("---")
    st.subheader(f"Store × {granularity} — {rank_metric}")
    st.caption("Darker = higher. Spot which stores drive which periods.")
    draw_view({"metric": rank_metric, "group_dim": granularity,
               "split_dim": "Store", "chart": "Heatmap (pivot)",
               "_key": "st_heat"}, height=520)

    st.markdown("---")
    ss_raw = L.store_summary(df)

    if "sales_psf" in ss_raw.columns:
        st.subheader("Sales per sq ft (carpet area)")
        st.caption(f"Sales in view ÷ carpet area — retail productivity. "
                   f"{start_d:%d %b %Y} → {end_d:%d %b %Y}.")
        psf = ss_raw.dropna(subset=["sales_psf"]).sort_values("sales_psf")
        fig = px.bar(psf, x="sales_psf", y=L.COL_STORE_LABEL, orientation="h",
                     color_discrete_sequence=[MAROON])
        fig.update_layout(height=520, plot_bgcolor="white", yaxis_title="",
                          xaxis_title="₹ per sq ft", margin=dict(t=10))
        fig.update_traces(hovertemplate="%{y}<br>₹%{x:,.0f}/sqft<extra></extra>")
        st.plotly_chart(fig, use_container_width=True)
        st.markdown("---")

    st.subheader("Per-store KPI table")
    ss = ss_raw.rename(columns={
        L.COL_STORE_LABEL: "Store", "sales": "Sales (₹)", "units": "Units",
        "bills": "Bills", "customers": "Customers", "atv": "ATV (₹)",
        "upt": "UPT", "asp": "ASP (₹)", "carpet_area": "Carpet Area (sqft)",
        "sales_psf": "Sales/sqft (₹)"})
    st.dataframe(
        ss, use_container_width=True, hide_index=True,
        column_config={
            "Sales (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "ATV (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "ASP (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "UPT": st.column_config.NumberColumn(format="%.2f"),
            "Carpet Area (sqft)": st.column_config.NumberColumn(format="%.0f"),
            "Sales/sqft (₹)": st.column_config.NumberColumn(format="₹%.0f"),
        },
    )

# =========================================================================== #
# BUILD YOUR VIEW — per-session panel builder
# =========================================================================== #
with tab_build:
    st.subheader("Build your own view")
    st.caption(
        "Pick a metric, a dimension to break it down by, and a chart. "
        "Add as many panels as you like — this layout is yours for this session."
    )

    if "panels" not in st.session_state:
        # Seed with a couple of useful defaults.
        st.session_state.panels = [
            {"title": "Sales by month", "metric": "Sales (₹)", "group_dim": "Month",
             "split_dim": "(none)", "chart": "Bar", "top": 15, "width": "Full"},
            {"title": "Sales by store", "metric": "Sales (₹)",
             "group_dim": "Store", "split_dim": "(none)",
             "chart": "Horizontal bar", "top": 25, "width": "Half"},
            {"title": "Sales by division", "metric": "Sales (₹)",
             "group_dim": "Division", "split_dim": "(none)",
             "chart": "Horizontal bar", "top": 12, "width": "Half"},
        ]

    with st.expander("➕ Add a panel", expanded=False):
        c1, c2, c3 = st.columns(3)
        n_metric = c1.selectbox("Metric", list(L.METRICS.keys()), key="nb_metric")
        n_group = c2.selectbox("Break down by", L.ALL_DIMS,
                               index=L.ALL_DIMS.index("Month"), key="nb_group")
        n_split = c3.selectbox("Split by (optional)", ["(none)"] + L.ALL_DIMS,
                               key="nb_split")
        c4, c5, c6 = st.columns(3)
        n_chart = c4.selectbox("Chart", CHART_TYPES, key="nb_chart")
        n_top = c5.slider("Top N (categories)", 3, 30, 12, key="nb_top")
        n_width = c6.selectbox("Width", ["Full", "Half"], key="nb_width")
        n_title = st.text_input("Panel title", value=f"{n_metric} by {n_group}",
                                key="nb_title")
        if st.button("Add panel", type="primary"):
            st.session_state.panels.append({
                "title": n_title, "metric": n_metric, "group_dim": n_group,
                "split_dim": n_split, "chart": n_chart, "top": n_top,
                "width": n_width,
            })
            st.rerun()

    top_row = st.columns([1, 1, 6])
    if top_row[0].button("🗑 Clear all"):
        st.session_state.panels = []
        st.rerun()
    if top_row[1].button("↺ Reset"):
        del st.session_state.panels
        st.rerun()

    # Render panels, honoring Full/Half width.
    panels = st.session_state.panels
    if not panels:
        st.info("No panels yet — use **➕ Add a panel** above.")
    i = 0
    while i < len(panels):
        p = panels[i]
        if p["width"] == "Half" and i + 1 < len(panels) and panels[i + 1]["width"] == "Half":
            cols = st.columns(2)
            for j, col in enumerate(cols):
                pp = panels[i + j]
                with col:
                    hdr = st.columns([6, 1])
                    hdr[0].markdown(f"**{pp['title']}**")
                    if hdr[1].button("✕", key=f"rm_{i+j}"):
                        st.session_state.panels.pop(i + j)
                        st.rerun()
                    draw_view({**pp, "_key": f"panel_{i+j}"}, height=320)
            i += 2
        else:
            hdr = st.columns([10, 1])
            hdr[0].markdown(f"**{p['title']}**")
            if hdr[1].button("✕", key=f"rm_{i}"):
                st.session_state.panels.pop(i)
                st.rerun()
            draw_view({**p, "_key": f"panel_{i}"}, height=360)
            i += 1

# =========================================================================== #
# TRENDS — respect chosen granularity
# =========================================================================== #
with tab_trends:
    st.subheader(f"Sales — by {granularity}")
    draw_view({"metric": "Sales (₹)", "group_dim": granularity, "chart": "Area",
               "_key": "tr_sales"}, height=340)

    colA, colB = st.columns(2)
    with colA:
        st.subheader(f"Bills — by {granularity}")
        draw_view({"metric": "Bills", "group_dim": granularity, "chart": "Line",
                   "_key": "tr_bills"}, height=320)
    with colB:
        st.subheader(f"Avg bill value — by {granularity}")
        draw_view({"metric": "Avg Bill Value / ATV (₹)", "group_dim": granularity,
                   "chart": "Line", "_key": "tr_atv"}, height=320)

    colC, colD = st.columns(2)
    with colC:
        st.subheader("Sales by day of week")
        draw_view({"metric": "Sales (₹)", "group_dim": "Weekday", "chart": "Bar",
                   "_key": "tr_wd"}, height=320)
    with colD:
        st.subheader(f"Discount — by {granularity}")
        draw_view({"metric": "Discount (₹)", "group_dim": granularity, "chart": "Bar",
                   "_key": "tr_disc"}, height=320)

# =========================================================================== #
# CATEGORY MIX
# =========================================================================== #
with tab_cat:
    colA, colB = st.columns([2, 1])
    with colA:
        st.subheader("Sales by Division")
        draw_view({"metric": "Sales (₹)", "group_dim": "Division",
                   "chart": "Horizontal bar", "top": 15, "_key": "cat_div"}, height=480)
    with colB:
        st.subheader("Men / Women / Child")
        draw_view({"metric": "Sales (₹)", "group_dim": "Men/Women/Child",
                   "chart": "Pie / Donut", "_key": "cat_mwc"}, height=340)

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Top Sections")
        draw_view({"metric": "Sales (₹)", "group_dim": "Section", "chart": "Table",
                   "top": 15, "_key": "cat_sec"})
    with c2:
        st.subheader("Top Departments (products)")
        draw_view({"metric": "Sales (₹)", "group_dim": "Department", "chart": "Table",
                   "top": 15, "_key": "cat_dep"})

# =========================================================================== #
# SALESPEOPLE
# =========================================================================== #
with tab_staff:
    sp = L.salesperson_summary(df)
    st.subheader("Salesperson leaderboard")
    st.caption(f"{len(sp)} salespeople in view")
    draw_view({"metric": "Sales (₹)", "group_dim": "Salesperson",
               "chart": "Horizontal bar", "top": 15, "_key": "sp_bar"}, height=520)
    st.dataframe(
        sp.rename(columns={L.COL_SALESPERSON: "Salesperson", "sales": "Sales (₹)",
                           "units": "Units", "bills": "Bills", "atv": "ATV (₹)"}),
        use_container_width=True, hide_index=True,
        column_config={
            "Sales (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "ATV (₹)": st.column_config.NumberColumn(format="₹%.2f"),
        },
    )

# =========================================================================== #
# CUSTOMERS
# =========================================================================== #
with tab_cust:
    cs = L.customer_stats(df)
    c1, c2, c3 = st.columns(3)
    total_bills = cs["new"] + cs["repeat"]
    c1.metric("New-customer bills", f"{cs['new']:,}")
    c2.metric("Repeat-customer bills", f"{cs['repeat']:,}")
    c3.metric("Repeat share of bills",
              f"{(cs['repeat']/total_bills*100):.1f}%" if total_bills else "—")

    colA, colB = st.columns(2)
    with colA:
        st.subheader("New vs repeat (bills)")
        pie = pd.DataFrame({"type": ["New", "Repeat"],
                            "bills": [cs["new"], cs["repeat"]]})
        fig = px.pie(pie, names="type", values="bills", hole=0.5,
                     color_discrete_sequence=[GOLD, MAROON])
        fig.update_layout(height=320, margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True)
    with colB:
        st.subheader("Repeat share by month")
        if not cs["trend"].empty:
            fig = px.line(cs["trend"], x="month_label", y="repeat_share", markers=True,
                          color_discrete_sequence=[MAROON])
            fig.update_layout(height=320, plot_bgcolor="white",
                              yaxis_title="Repeat share (%)", xaxis_title="",
                              margin=dict(t=10))
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Top customers by spend")
    mask_num = st.checkbox("Mask mobile numbers", value=True)
    top = cs["top"].rename(
        columns={L.COL_MOBILE: "Mobile", "spend": "Spend (₹)", "visits": "Visits"})
    if mask_num:
        top["Mobile"] = top["Mobile"].astype(str).apply(
            lambda m: m[:2] + "•••" + m[-2:] if len(m) >= 4 else "•••")
    st.dataframe(
        top, use_container_width=True, hide_index=True,
        column_config={"Spend (₹)": st.column_config.NumberColumn(format="₹%.2f")},
    )

# =========================================================================== #
# COLORS & SIZES
# =========================================================================== #
with tab_merch:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Best-selling colors")
        draw_view({"metric": "Units", "group_dim": "Color",
                   "chart": "Horizontal bar", "top": 15, "_key": "mz_col"}, height=520)
    with c2:
        st.subheader("Units by size")
        draw_view({"metric": "Units", "group_dim": "Size",
                   "chart": "Horizontal bar", "top": 15, "_key": "mz_size"}, height=520)
