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

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import loader as L

st.set_page_config(
    page_title="Peanuts Bengaluru — Sales Dashboard",
    page_icon="🥜",
    layout="wide",
    initial_sidebar_state="expanded",
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
st.sidebar.title("🥜 Peanuts Bengaluru")
st.sidebar.caption("Grand Kamraj Road")

min_d, max_d = fresh["min_date"].date(), fresh["max_date"].date()
date_range = st.sidebar.date_input(
    "Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d,
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_d, end_d = date_range
else:
    start_d, end_d = min_d, max_d

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
if sel_div:
    mask &= df_all[L.COL_DIVISION].isin(sel_div)
if sel_mwc:
    mask &= df_all[L.COL_MWC].isin(sel_mwc)
df = df_all[mask].copy()

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
    tickpre = "₹" if is_money else ""

    if chart in ("Bar", "Horizontal bar"):
        horizontal = chart == "Horizontal bar"
        fig = px.bar(
            data, x="value" if horizontal else "group",
            y="group" if horizontal else "value",
            color=color, orientation="h" if horizontal else "v",
            color_discrete_sequence=SEQ, barmode="group",
        )
        if horizontal:
            fig.update_layout(xaxis_tickprefix=tickpre, yaxis_title="", xaxis_title=view["metric"])
            fig.update_yaxes(categoryorder="array", categoryarray=order[::-1])
        else:
            fig.update_layout(yaxis_tickprefix=tickpre, xaxis_title="", yaxis_title=view["metric"])

    elif chart in ("Line", "Area"):
        fn = px.area if chart == "Area" else px.line
        fig = fn(data, x="group", y="value", color=color, markers=True,
                 color_discrete_sequence=SEQ)
        fig.update_layout(yaxis_tickprefix=tickpre, xaxis_title="", yaxis_title=view["metric"])

    elif chart == "Pie / Donut":
        agg = data.groupby("group", observed=True)["value"].sum().reset_index()
        fig = px.pie(agg, names="group", values="value", hole=0.5,
                     color_discrete_sequence=SEQ)

    elif chart == "Treemap":
        agg = data.groupby("group", observed=True)["value"].sum().reset_index()
        fig = px.treemap(agg, path=["group"], values="value",
                         color_discrete_sequence=SEQ)

    elif chart == "Heatmap (pivot)":
        if not has_split:
            st.info("Heatmap needs a **split** dimension. Pick one, or choose another chart.")
            return
        pivot = data.pivot_table(index="split", columns="group", values="value",
                                 aggfunc="sum", observed=True)
        fig = px.imshow(pivot, color_continuous_scale="OrRd", aspect="auto",
                        labels=dict(color=view["metric"]))
        fig.update_layout(xaxis_title=cfg["group_dim"], yaxis_title=view["split_dim"])

    else:  # Table
        if has_split:
            pivot = data.pivot_table(index="group", columns="split", values="value",
                                     aggfunc="sum", observed=True).reset_index()
            pivot = pivot.rename(columns={"group": cfg["group_dim"]})
            st.dataframe(pivot, use_container_width=True, hide_index=True)
        else:
            t = data[["group", "value"]].rename(
                columns={"group": cfg["group_dim"], "value": view["metric"]})
            fmt = "₹%d" if is_money else "%.2f"
            st.dataframe(
                t, use_container_width=True, hide_index=True,
                column_config={view["metric"]: st.column_config.NumberColumn(format=fmt)},
            )
        return

    fig.update_layout(height=height, plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=10, b=10), legend_title_text=view["split_dim"] or "")
    st.plotly_chart(fig, use_container_width=True, key=cfg.get("_key"))


# --------------------------------------------------------------------------- #
# Header + tabs
# --------------------------------------------------------------------------- #
st.title("Sales Dashboard")
st.caption(
    f"Peanuts — Grand Kamraj Road, Bengaluru · {start_d:%d %b %Y} → {end_d:%d %b %Y}"
)

tabs = st.tabs([
    "Overview", "🔧 Build your view", "Trends", "Category mix",
    "Salespeople", "Customers", "Colors & sizes",
])

# =========================================================================== #
# OVERVIEW — selectable KPI cards + trend at chosen granularity
# =========================================================================== #
with tabs[0]:
    scalar = L.all_scalar_kpis(df)
    default_cards = [
        "Sales (₹)", "Bills", "Units", "Unique Customers",
        "Avg Bill Value / ATV (₹)", "Units per Bill / UPT",
        "Avg Selling Price / ASP (₹)", "Discount (₹)",
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
# BUILD YOUR VIEW — per-session panel builder
# =========================================================================== #
with tabs[1]:
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
            {"title": "Sales by division", "metric": "Sales (₹)",
             "group_dim": "Division", "split_dim": "(none)",
             "chart": "Horizontal bar", "top": 12, "width": "Half"},
            {"title": "Units by Men/Women/Child", "metric": "Units",
             "group_dim": "Men/Women/Child", "split_dim": "(none)",
             "chart": "Pie / Donut", "top": 10, "width": "Half"},
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
with tabs[2]:
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
with tabs[3]:
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
with tabs[4]:
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
            "Sales (₹)": st.column_config.NumberColumn(format="₹%d"),
            "ATV (₹)": st.column_config.NumberColumn(format="₹%d"),
        },
    )

# =========================================================================== #
# CUSTOMERS
# =========================================================================== #
with tabs[5]:
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
        column_config={"Spend (₹)": st.column_config.NumberColumn(format="₹%d")},
    )

# =========================================================================== #
# COLORS & SIZES
# =========================================================================== #
with tabs[6]:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Best-selling colors")
        draw_view({"metric": "Units", "group_dim": "Color",
                   "chart": "Horizontal bar", "top": 15, "_key": "mz_col"}, height=520)
    with c2:
        st.subheader("Units by size")
        draw_view({"metric": "Units", "group_dim": "Size",
                   "chart": "Horizontal bar", "top": 15, "_key": "mz_size"}, height=520)
