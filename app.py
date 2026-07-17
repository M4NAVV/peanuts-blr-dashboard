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
import streamlit.components.v1 as components

import loader as L
from imaging import table_to_png

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
# Data loading (cached). The sheet is refreshed once a day (morning re-import),
# so we cache for 6h — after the first load everyone gets it instantly — and
# expose a manual "Refresh" button + a "data as of" timestamp for on-demand
# updates. This avoids re-downloading the ~265k-row sheet on a short TTL.
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=21600, show_spinner="Loading sales data… (first load ~10s)")
def _load_cached():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    df = L.load_data()
    return df, datetime.now(ZoneInfo("Asia/Kolkata"))


def get_data() -> pd.DataFrame:
    return _load_cached()[0]


def data_loaded_at():
    """When the currently-cached data was fetched (IST)."""
    return _load_cached()[1]


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


# --------------------------------------------------------------------------- #
# Custom KPI cards (big number + YoY badge + inline SVG sparkline)
# --------------------------------------------------------------------------- #
def _sparkline_svg(values, w=118, h=34, color=GOLD) -> str:
    vals = [float(v) for v in (values or []) if v is not None and not pd.isna(v)]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = [f"{i/(n-1)*w:.1f},{h - ((v-lo)/rng)*(h-6) - 3:.1f}" for i, v in enumerate(vals)]
    poly = " ".join(pts)
    area = f"0,{h} " + poly + f" {w},{h}"
    last_x, last_y = pts[-1].split(",")
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'style="overflow:visible">'
        f'<polygon points="{area}" fill="{color}22"/>'
        f'<polyline points="{poly}" fill="none" stroke="{color}" '
        f'stroke-width="1.6" stroke-linejoin="round"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.4" fill="{color}"/></svg>'
    )


def kpi_card(label, value, delta_pct=None, spark=None, hero=False) -> str:
    """HTML for one KPI card: label, big value, YoY badge, optional sparkline."""
    delta_html = "&nbsp;"
    if delta_pct is not None and not pd.isna(delta_pct):
        up = delta_pct >= 0
        color = "#1B7F3B" if up else "#C0143C"
        arrow = "▲" if up else "▼"
        delta_html = (
            f'<span style="color:{color};font-weight:700;font-size:.82rem;">'
            f'{arrow} {abs(delta_pct):.1f}%</span>'
            f'<span style="color:#9a9a9a;font-weight:500;font-size:.72rem;"> YoY</span>'
        )
    spark_html = _sparkline_svg(spark) if spark is not None else ""
    val_size = "2.0rem" if hero else "1.5rem"
    minh = "112px" if hero else "96px"
    return (
        f'<div style="background:#fff;border:1px solid #ECE4D6;border-radius:14px;'
        f'padding:14px 16px;box-shadow:0 1px 4px rgba(0,0,0,.05);min-height:{minh};'
        f'display:flex;flex-direction:column;justify-content:space-between;">'
        f'<div style="color:#6b6b6b;font-size:.78rem;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:.03em;">{label}</div>'
        f'<div style="color:{MAROON};font-size:{val_size};font-weight:800;'
        f'line-height:1.15;margin:4px 0;">{value}</div>'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-end;'
        f'gap:8px;">{delta_html}{spark_html}</div></div>'
    )


def stat_card(title, rows) -> str:
    """A titled card with several label→value rows (colored)."""
    body = "".join(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:4px 0;">'
        f'<span style="color:#6b6b6b;font-size:.86rem;">{lbl}</span>'
        f'<span style="color:{col};font-weight:800;font-size:1.02rem;'
        f'font-variant-numeric:tabular-nums;">{val}</span></div>'
        for lbl, val, col in rows)
    return (
        f'<div style="background:#fff;border:1px solid #ECE4D6;border-radius:14px;'
        f'padding:14px 16px;box-shadow:0 1px 4px rgba(0,0,0,.05);min-height:158px;">'
        f'<div style="color:{MAROON};font-weight:700;font-size:.78rem;'
        f'text-transform:uppercase;letter-spacing:.03em;margin-bottom:8px;'
        f'border-bottom:1px solid #EFE7D8;padding-bottom:7px;">{title}</div>'
        f'{body}</div>')


GRN_TXT, RED_TXT = "#137a3a", "#C0143C"


def styled_report_html(disp, money_cols=(), pct_cols=(), sign_cols=(),
                       row_types=None, font_px=12.5, full_width=True,
                       compact=False):
    """Compact, high-contrast HTML table built with INLINE styles (so colors
    always render in Streamlit): maroon header, zebra rows, tabular right-aligned
    numbers, shaded subtotals/totals, and red/green on growth columns.

    Headers always wrap onto multiple lines (never truncated), so columns size to
    their data rather than to a long header — keeping every report compact and
    readable at full font. `compact=True` adds extra width-savers for the very
    wide sheets (tighter padding + whole-rupee money on the 16-column Gender G/D
    detail) so they fit one screen without shrinking the font."""
    money, pct, sign = set(money_cols), set(pct_cols), set(sign_cols)
    cols = list(disp.columns)
    money_dp = 0 if compact else 2
    th_pad = "6px 6px" if compact else "8px 10px"
    td_pad = "3px 7px" if compact else "5px 10px"

    def align(c):
        return "right" if (c in money or c in pct) else "left"

    ths = "".join(
        f'<th style="background:{MAROON};color:#fff;font-weight:700;'
        f'font-size:{font_px - 1:.0f}px;text-transform:uppercase;letter-spacing:.01em;'
        f'padding:{th_pad};text-align:center;position:sticky;top:0;'
        f'line-height:1.15;white-space:normal;vertical-align:bottom;">{c}</th>'
        for c in cols)

    trs = []
    for i in range(len(disp)):
        t = row_types[i] if row_types is not None else "store"
        if t == "subtotal":
            rbg, fw = "#F6D9D5", "700"
        elif t == "grand":
            rbg, fw = "#CDE8CF", "800"
        elif t == "storetotal":
            rbg, fw = "#FBEEE6", "700"
        elif t == "block":
            rbg, fw = "#D6E4F5", "800"          # store-block total (blue)
        else:
            rbg, fw = ("#FFFFFF" if i % 2 == 0 else "#FAF6EF"), "500"
        tds = []
        for c in cols:
            v = disp.iloc[i][c]
            if c in money:
                txt = fmt_in(v, money_dp) if pd.notna(v) else "—"
            elif c in pct:
                txt = f"{v:,.2f}%" if pd.notna(v) else "—"
            else:
                txt = "" if (isinstance(v, float) and pd.isna(v)) else str(v)
            color = "#1f2937"
            if c in sign and pd.notna(v):
                try:
                    color = RED_TXT if float(v) < 0 else GRN_TXT
                except (TypeError, ValueError):
                    pass
            tds.append(
                f'<td style="padding:{td_pad};text-align:{align(c)};color:{color};'
                f'font-weight:{fw};background:{rbg};border-bottom:1px solid #ECE4D6;'
                f'white-space:nowrap;font-variant-numeric:tabular-nums;">{txt}</td>')
        trs.append(f"<tr>{''.join(tds)}</tr>")

    # Always size the table to its content (width:auto) so column widths depend
    # only on the data, never on the container — no stretching / no dead
    # whitespace inside columns when the page is wide or zoomed out. `full_width`
    # only controls whether we add the horizontal-scroll wrapper.
    table = (
        f'<table style="border-collapse:collapse;width:auto;'
        f'font-family:Inter,-apple-system,Segoe UI,sans-serif;font-size:{font_px}px;">'
        f'<thead><tr>{ths}</tr></thead><tbody>{"".join(trs)}</tbody></table>')
    if not full_width:
        return table
    return (f'<div style="overflow-x:auto;max-width:100%;border:1px solid #E7E1D6;'
            f'border-radius:10px;display:inline-block;">{table}</div>')


def render_fit_to_screen(table_html, panel_h=600):
    """A single button that opens the table in native browser full screen,
    auto-scaled to fit — no scrollbars, nothing cut off. The full-screen area
    holds only the table (the button is outside it), so a screenshot is clean.
    Esc exits, browser-native — no on-screen controls."""
    doc = f"""
    <button id="fsbtn" style="padding:9px 18px;border:0;border-radius:8px;
            background:{MAROON};color:#fff;font-weight:700;font-size:14px;cursor:pointer;
            font-family:Inter,Segoe UI,sans-serif;margin:0 0 10px;">
      ⛶ Open in full screen
    </button>
    <div id="stage" style="width:100%;height:{panel_h}px;overflow:hidden;background:#fff;
         display:flex;justify-content:center;align-items:flex-start;">
      <div id="fittable" style="transform-origin:top center;">{table_html}</div>
    </div>
    <script>
      var stage=document.getElementById('stage'),
          t=document.getElementById('fittable'),
          btn=document.getElementById('fsbtn');
      function fit() {{
        t.style.transform='scale(1)';
        var s=Math.min(stage.clientWidth/t.scrollWidth,
                       stage.clientHeight/t.scrollHeight);
        t.style.transform='scale('+Math.min(s,2.6)+')';
      }}
      btn.onclick=function(){{
        var req=stage.requestFullscreen||stage.webkitRequestFullscreen;
        if(req) req.call(stage);
      }};
      function onFs(){{
        var on=(document.fullscreenElement||document.webkitFullscreenElement)===stage;
        stage.style.height=on?'100vh':'{panel_h}px';
        stage.style.alignItems=on?'center':'flex-start';
        setTimeout(fit,30); setTimeout(fit,150);
      }}
      document.addEventListener('fullscreenchange',onFs);
      document.addEventListener('webkitfullscreenchange',onFs);
      window.addEventListener('resize',fit);
      window.addEventListener('load',fit);
      setTimeout(fit,50); setTimeout(fit,300);
    </script>"""
    components.html(doc, height=panel_h+58, scrolling=False)


def _fmt_cell_money(v):
    return fmt_in(v, 2) if pd.notna(v) else "—"


def _fmt_cell_pct(v):
    return f"{v:,.2f}%" if pd.notna(v) else "—"


# st.dataframe serializes to Arrow via pyarrow, which can segfault on object
# columns holding non-primitive Python values. Route every st.dataframe through
# this: it str-casts ONLY columns that actually contain such values, leaving
# clean numeric/string frames (and their column_config formatting) untouched.
_st_dataframe = st.dataframe


def _arrow_safe(df):
    if not isinstance(df, pd.DataFrame):
        return df  # Stylers etc. — leave as-is
    out = None
    for c in df.columns:
        if df[c].dtype == object:
            col = df[c]
            ok = col.map(lambda v: v is None or isinstance(v, (str, int, float, bool)))
            if not bool(ok.all()):
                if out is None:
                    out = df.copy()
                out[c] = col.astype(str)
    return out if out is not None else df


def _safe_dataframe(data, **kwargs):
    _st_dataframe(_arrow_safe(data), **kwargs)


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
# Sidebar — exhaustive, cascading filters + view settings
# --------------------------------------------------------------------------- #
n_stores_all = df_all[L.COL_STORE_LABEL].nunique()
st.sidebar.title("🥜 Peanuts Retail")
st.sidebar.caption(f"All {n_stores_all} stores · Bengaluru + East India")

min_d, max_d = fresh["min_date"].date(), fresh["max_date"].date()

# ---- Date: single day or custom range ----
st.sidebar.markdown("#### 📅 Date")
date_mode = st.sidebar.radio(
    "Date mode", ["Custom range", "Single day"], horizontal=True,
    label_visibility="collapsed", key="f_date_mode")
if date_mode == "Single day":
    one = st.sidebar.date_input("Day", value=max_d, min_value=min_d,
                                max_value=max_d, key="f_day")
    start_d = end_d = one
else:
    dr = st.sidebar.date_input("Range", value=(min_d, max_d), min_value=min_d,
                               max_value=max_d, key="f_range")
    if isinstance(dr, tuple) and len(dr) == 2:
        start_d, end_d = dr
    elif isinstance(dr, tuple) and len(dr) == 1:
        start_d = end_d = dr[0]
    else:
        start_d = end_d = dr


def _msel(container, label, options, key):
    return container.multiselect(label, options, default=[], key=key)


# ---- Region (prominent — North East vs South) ----
st.sidebar.markdown("#### 🧭 Region")
sel_region = st.sidebar.multiselect(
    "Region", sorted(df_all[L.COL_REGION].dropna().unique()), default=[],
    key="f_region", label_visibility="collapsed",
    help="North East vs South — leave empty for all")
_rpool = df_all[df_all[L.COL_REGION].isin(sel_region)] if sel_region else df_all

# ---- Store (cascading: state → city → store) ----
with st.sidebar.expander("🏬 Store", expanded=False):
    sel_state = _msel(st, "State",
                      sorted(_rpool[L.COL_STATE].dropna().unique()), "f_state")
    pool = _rpool[_rpool[L.COL_STATE].isin(sel_state)] if sel_state else _rpool
    sel_city = _msel(st, "City",
                     sorted(pool[L.COL_CITY].dropna().unique()), "f_city")
    pool = pool[pool[L.COL_CITY].isin(sel_city)] if sel_city else pool
    sel_store = _msel(st, "Store",
                      sorted(pool[L.COL_STORE_LABEL].dropna().unique()), "f_store")

# ---- Product (cascading: brand → division → section → department) ----
with st.sidebar.expander("👕 Product", expanded=False):
    sel_brand = _msel(st, "Brand",
                      sorted(df_all[L.COL_BRAND].dropna().unique()), "f_brand")
    _bpool = df_all[df_all[L.COL_BRAND].isin(sel_brand)] if sel_brand else df_all
    sel_div = _msel(st, "Division",
                    sorted(_bpool[L.COL_DIVISION].dropna().unique()), "f_div")
    ppool = _bpool[_bpool[L.COL_DIVISION].isin(sel_div)] if sel_div else _bpool
    sel_sec = _msel(st, "Section",
                    sorted(ppool[L.COL_SECTION].dropna().unique()), "f_sec")
    ppool = ppool[ppool[L.COL_SECTION].isin(sel_sec)] if sel_sec else ppool
    sel_dep = _msel(st, "Department",
                    sorted(ppool[L.COL_DEPARTMENT].dropna().unique()), "f_dep")
    sel_mwc = _msel(st, "Men / Women / Child",
                    sorted(df_all[L.COL_MWC].dropna().unique()), "f_mwc")
    sel_size = _msel(st, "Size",
                     sorted(df_all[L.COL_SIZE].dropna().unique()), "f_size")
    sel_color = _msel(st, "Color",
                      sorted(df_all[L.COL_COLOR].dropna().unique()), "f_color")
    sel_style = _msel(st, "Style code",
                      sorted(df_all[L.COL_STYLE].dropna().unique()), "f_style")

# ---- People ----
with st.sidebar.expander("🧑‍💼 People", expanded=False):
    sel_sp = _msel(st, "Salesperson",
                   sorted(df_all[L.COL_SALESPERSON].dropna().unique()), "f_sp")

st.sidebar.markdown("#### View settings")
granularity = st.sidebar.radio(
    "Time granularity", ["Day", "Week", "Month", "Quarter", "Year"],
    index=2, horizontal=True,
    help="Drives the trend tables and the default in Build-your-view.")

_FILTER_KEYS = ["f_region", "f_state", "f_city", "f_store", "f_brand",
                "f_div", "f_sec", "f_dep", "f_mwc", "f_size", "f_color", "f_style",
                "f_sp"]
if st.sidebar.button("↺ Reset all filters"):
    for _k in _FILTER_KEYS:
        st.session_state.pop(_k, None)
    st.rerun()

# ---- Apply filters ----
_CAT_FILTERS = [
    ("Region", L.COL_REGION, sel_region), ("State", L.COL_STATE, sel_state),
    ("City", L.COL_CITY, sel_city), ("Store", L.COL_STORE_LABEL, sel_store),
    ("Brand", L.COL_BRAND, sel_brand), ("Division", L.COL_DIVISION, sel_div),
    ("Section", L.COL_SECTION, sel_sec), ("Department", L.COL_DEPARTMENT, sel_dep),
    ("M/W/C", L.COL_MWC, sel_mwc), ("Size", L.COL_SIZE, sel_size),
    ("Color", L.COL_COLOR, sel_color), ("Style", L.COL_STYLE, sel_style),
    ("Salesperson", L.COL_SALESPERSON, sel_sp),
]


def _cat_mask(frame):
    m = pd.Series(True, index=frame.index)
    for _lbl, col, sel in _CAT_FILTERS:
        if sel and col in frame.columns:
            m &= frame[col].isin(sel)
    return m


cat_mask = _cat_mask(df_all)
date_mask = (df_all["date"].dt.date >= start_d) & (df_all["date"].dt.date <= end_d)
df = df_all[cat_mask & date_mask].copy()
# Executive / report YoY need full history — apply all filters EXCEPT date range.
df_exec = df_all[cat_mask].copy()

active_filters = [(lbl, sel) for lbl, _col, sel in _CAT_FILTERS if sel]

st.sidebar.markdown("---")
st.sidebar.caption(
    f"**Data through:** {fresh['max_date']:%d %b %Y}  \n**Rows:** {fresh['rows']:,}  \n"
    f"**Loaded:** {data_loaded_at():%d %b, %I:%M %p} IST")
if st.sidebar.button("🔄 Refresh data now"):
    _load_cached.clear()
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
    """Render one configured view as a numbers table (charts removed — numbers only)."""
    view = L.build_view(
        df, cfg["metric"], cfg["group_dim"],
        split_dim=cfg.get("split_dim"), top=cfg.get("top"),
    )
    data = view["data"].copy()
    is_money = view["is_money"]
    order = view["order"]
    has_split = view["split_dim"] is not None

    if data.empty:
        st.info("No data for this view.")
        return

    # Keep categorical/time order consistent.
    data["group"] = pd.Categorical(data["group"], categories=order, ordered=True)
    data = data.sort_values("group")

    if has_split:
        pivot = data.pivot_table(index="group", columns="split", values="value",
                                 aggfunc="sum", observed=True).reset_index()
        pivot = pivot.rename(columns={"group": cfg["group_dim"]})
        if is_money:
            for c in pivot.columns[1:]:
                pivot[c] = pivot[c].map(lambda v: fmt_in(v, 2))
        _safe_dataframe(pivot, use_container_width=True, hide_index=True)
    else:
        t = data[["group", "value"]].rename(columns={"group": cfg["group_dim"]})
        if is_money:
            t[view["metric"]] = t.pop("value").map(lambda v: fmt_in(v, 2))
            _safe_dataframe(t, use_container_width=True, hide_index=True)
        else:
            t = t.rename(columns={"value": view["metric"]})
            _safe_dataframe(
                t, use_container_width=True, hide_index=True,
                column_config={view["metric"]:
                               st.column_config.NumberColumn(format="%.2f")},
            )


def exec_window_row(title, r):
    """One executive window (MTD/QTD/YTD…) as YoY KPI cards, from a result dict."""
    cs, ce = r["cur_window"]
    ps, pe = r["prior_window"]
    rng = (f"`{cs:%d %b %Y} → {ce:%d %b %Y}` &nbsp;·&nbsp; "
           f"vs LY `{ps:%d %b %Y} → {pe:%d %b %Y}`") if cs is not None else ""
    st.markdown(f"**{title}** &nbsp; {rng}")
    cols = st.columns(4)
    specs = [
        ("Sales", inr(r["cur"]["sales"]), r["growth"]["sales"]),
        ("Bills", f'{r["cur"]["bills"]:,}', r["growth"]["bills"]),
        ("Units", f'{r["cur"]["units"]:,}', r["growth"]["units"]),
        ("Avg Bill", inr(r["cur"]["atv"]), r["growth"]["atv"]),
    ]
    for col, (lbl, val, g) in zip(cols, specs):
        col.markdown(kpi_card(lbl, val, g), unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Header + tabs
# --------------------------------------------------------------------------- #
st.title("Sales Dashboard")
scope = f"{len(sel_store)} store(s)" if sel_store else f"all {n_stores_all} stores"
_dlabel = (f"{start_d:%d %b %Y}" if start_d == end_d
           else f"{start_d:%d %b %Y} → {end_d:%d %b %Y}")
st.caption(f"Peanuts Retail · {scope} · {_dlabel}")

# Store & value movement (MTD / YTD, YoY) — respects filters + as-of date.
_mv = L.movement_summary(df_exec, asof=pd.Timestamp(end_d))
_m, _y = _mv["MTD"], _mv["YTD"]
GRN, RED = "#137a3a", "#C0143C"
_c = st.columns(4)
_c[0].markdown(stat_card("MTD · Stores", [
    ("Total Stores", f"{_m['total']}", INK),
    ("Growing", f"{_m['growing']}", GRN),
    ("De-Growing", f"{_m['degrowing']}", RED)]), unsafe_allow_html=True)
_c[1].markdown(stat_card("YTD · Stores", [
    ("Total Stores", f"{_y['total']}", INK),
    ("Growing", f"{_y['growing']}", GRN),
    ("De-Growing", f"{_y['degrowing']}", RED)]), unsafe_allow_html=True)
_c[2].markdown(stat_card("MTD · Growth / Degrowth Value", [
    ("Total (Net)", inr(_m["net_value"]), GRN if _m["net_value"] >= 0 else RED),
    ("Growth Value", inr(_m["growth_value"]), GRN),
    ("Degrowth Value", inr(_m["degrowth_value"]), RED)]), unsafe_allow_html=True)
_c[3].markdown(stat_card("YTD · Growth / Degrowth Value", [
    ("Total (Net)", inr(_y["net_value"]), GRN if _y["net_value"] >= 0 else RED),
    ("Growth Value", inr(_y["growth_value"]), GRN),
    ("Degrowth Value", inr(_y["degrowth_value"]), RED)]), unsafe_allow_html=True)

# Active-filter chips.
if active_filters:
    chips = " ".join(
        f'<span style="background:#F1E9DA;color:#7A1F2B;border-radius:10px;'
        f'padding:2px 9px;margin:2px;font-size:.74rem;font-weight:600;'
        f'display:inline-block;">{lbl}: {", ".join(map(str, sel[:3]))}'
        f'{f" +{len(sel) - 3}" if len(sel) > 3 else ""}</span>'
        for lbl, sel in active_filters)
    st.markdown("**Filters:** " + chips, unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Gender / Brand growth-degrowth rendering helpers
# --------------------------------------------------------------------------- #
GD_MONEY = ["YTD LY", "YTD TY", "MTD LY", "MTD TY", "Day Sales", "Month Sale LY",
            "Projected MTD", "LY Full Sales", "Projected YTD"]
GD_PCT = ["GD YTD %", "GD MTD %"]
GD_ORDER = ["YTD LY", "YTD TY", "GD YTD %", "MTD LY", "MTD TY", "GD MTD %",
            "Day Sales", "Month Sale LY", "Projected MTD", "LY Full Sales",
            "Projected YTD"]


def _gd_total(rows_df, label_cols, label):
    """A totals row: sum money cols, recompute GD% from the summed LY/TY."""
    r = {c: "" for c in rows_df.columns}
    for c in label_cols:
        r[c] = ""
    r[label_cols[0]] = label
    for c in GD_MONEY:
        if c in rows_df.columns:
            r[c] = pd.to_numeric(rows_df[c], errors="coerce").sum()
    r["GD YTD %"] = ((r["YTD TY"] - r["YTD LY"]) / r["YTD LY"] * 100
                     if r.get("YTD LY") else None)
    r["GD MTD %"] = ((r["MTD TY"] - r["MTD LY"]) / r["MTD LY"] * 100
                     if r.get("MTD LY") else None)
    return r


def render_gd_table(disp, label_cols, key, region_grouped=False):
    """Render a growth/degrowth DataFrame styled like the source sheet: money
    columns, red/green GD%, region subtotals (optional) + grand total, CSV/PNG."""
    cols = list(label_cols) + [c for c in GD_ORDER if c in disp.columns]
    disp = disp[cols].copy()
    rows, rtypes = [], []
    if region_grouped and "Region" in disp.columns:
        for reg in [r for r in ["East & NE", "South"] if r in disp["Region"].unique()]:
            sub = disp[disp["Region"] == reg]
            for _, rr in sub.iterrows():
                rows.append(rr.to_dict())
                rtypes.append("store")
            rows.append(_gd_total(sub, label_cols, f"{reg} Total"))
            rtypes.append("subtotal")
    else:
        for _, rr in disp.iterrows():
            rows.append(rr.to_dict())
            rtypes.append("store")
    rows.append(_gd_total(disp, label_cols, "Grand Total"))
    rtypes.append("grand")
    table = pd.DataFrame(rows)[cols]

    money = [c for c in GD_MONEY if c in cols]
    st.markdown(
        styled_report_html(table, money_cols=money, pct_cols=GD_PCT,
                           sign_cols=GD_PCT, row_types=rtypes),
        unsafe_allow_html=True)
    st.write("")
    st.download_button("⬇ Download (CSV)", table.to_csv(index=False).encode(),
                       file_name=f"{key}.csv", mime="text/csv",
                       key=f"{key}_csv", use_container_width=True)
    return table


def gd_basis_control(key, picker_date):
    """Renders the 'Live to-date / Month-end review' toggle shared by the G/D
    tabs and returns the resolved as-of date. Month-end review snaps to the last
    day of the month *before* the picker's month, reproducing a monthly review
    sheet (takeover-anchoring is unchanged either way)."""
    basis = st.radio(
        "As-of basis", ["Live to-date", "Month-end review"], horizontal=True,
        key=key, label_visibility="collapsed",
        help="Live = up to the date picker. Month-end = the last completed "
             "month, matching the monthly G/D sheet.")
    d = pd.Timestamp(picker_date)
    if basis == "Month-end review":
        asof = d.replace(day=1) - pd.Timedelta(days=1)
        st.caption(f"Reviewing **{asof:%B %Y}** (month-end · matches the monthly "
                   "G/D sheet). Stores counted from their takeover date.")
    else:
        asof = d
        st.caption(f"Live to **{asof:%d %b %Y}** (follows the date picker). "
                   "Stores counted from their takeover date.")
    return asof


def _grouped_gd_rows(detail, sum_cols, pct_fill, label_cols):
    """Region → Store → row grouping shared by the detailed pages-10-15 views.
    Emits data rows + a per-store total (only when a store has >1 sub-row),
    region subtotals, and a grand total. `sum_cols` are summed on total rows;
    `pct_fill(total_dict, sub_df)` sets the %/derived columns. Returns
    (rows, row_types)."""
    def total_row(sub, put_col, label):
        r = {c: "" for c in detail.columns}
        r[put_col] = label
        for c in sum_cols:
            r[c] = pd.to_numeric(sub[c], errors="coerce").sum()
        pct_fill(r, sub)
        return r

    rows, rtypes = [], []
    for reg in [r for r in ["East & NE", "South"] if r in detail["Region"].unique()]:
        rsub = detail[detail["Region"] == reg]
        for code in pd.unique(rsub["Store Code"]):
            ssub = rsub[rsub["Store Code"] == code]
            for _, rr in ssub.iterrows():
                rows.append(rr.to_dict())
                rtypes.append("store")
            if len(ssub) > 1:                      # per-store total, gender-split
                tr = total_row(ssub, "Gender", "Total")
                tr["Store Code"] = code
                tr["Location"] = ssub["Location"].iloc[0]
                rows.append(tr)
                rtypes.append("storetotal")
        rows.append(total_row(rsub, "Region", f"{reg} Total"))
        rtypes.append("subtotal")
    rows.append(total_row(detail, "Region", "Grand Total"))
    rtypes.append("grand")
    return rows, rtypes


def render_gd_grouped(detail, key):
    """Store × gender growth/degrowth, PDF pages 10-12 format: Region → Store →
    Gender, per-store totals, region subtotals, grand total; full GD columns.
    Rendered compact (wrapped headers, tight columns, whole-rupee) so all 16
    columns fit on one screen without horizontal scrolling."""
    label_cols = ["Region", "Master Location", "Store Code", "Location", "Gender"]
    cols = label_cols + [c for c in GD_ORDER if c in detail.columns]
    detail = detail[cols].copy()

    def pct_fill(r, _sub):
        r["GD YTD %"] = ((r["YTD TY"] - r["YTD LY"]) / r["YTD LY"] * 100
                         if r.get("YTD LY") else None)
        r["GD MTD %"] = ((r["MTD TY"] - r["MTD LY"]) / r["MTD LY"] * 100
                         if r.get("MTD LY") else None)

    rows, rtypes = _grouped_gd_rows(
        detail, [c for c in GD_MONEY if c in cols], pct_fill, label_cols)
    table = pd.DataFrame(rows)[cols]
    money = [c for c in GD_MONEY if c in cols]
    st.markdown(
        styled_report_html(table, money_cols=money, pct_cols=GD_PCT,
                           sign_cols=GD_PCT, row_types=rtypes, compact=True),
        unsafe_allow_html=True)
    st.write("")
    st.download_button("⬇ Download (CSV)", table.to_csv(index=False).encode(),
                       file_name=f"{key}.csv", mime="text/csv",
                       key=f"{key}_csv", use_container_width=True)
    return table


def render_gender_mix_grouped(detail, key):
    """Store × gender contribution %, PDF pages 13-15 format: Region → Store →
    Gender, per-store totals (=100%), region subtotals, grand total."""
    cols = ["Region", "Master Location", "Store Code", "Location", "Gender",
            "MTD TY", "Contrib MTD %", "YTD TY", "Contrib YTD %"]
    cols = [c for c in cols if c in detail.columns]
    detail = detail[cols].copy()

    def pct_fill(r, _sub):
        r["Contrib MTD %"] = 100.0
        r["Contrib YTD %"] = 100.0

    rows, rtypes = _grouped_gd_rows(
        detail, ["MTD TY", "YTD TY"], pct_fill, cols)
    table = pd.DataFrame(rows)[cols]
    st.markdown(
        styled_report_html(table, money_cols=["MTD TY", "YTD TY"],
                           pct_cols=["Contrib MTD %", "Contrib YTD %"],
                           row_types=rtypes),
        unsafe_allow_html=True)
    st.write("")
    st.download_button("⬇ Download (CSV)", table.to_csv(index=False).encode(),
                       file_name=f"{key}.csv", mime="text/csv",
                       key=f"{key}_csv", use_container_width=True)
    return table


def build_store_brand_gd(detail):
    """Store × brand-line G/D grouped for display: per store, MEN brand-lines +
    MEN Total (peach), WOMEN brand-lines + WOMEN Total (peach), a store total
    (blue block), then region subtotals (pink) and a grand total (green).
    Returns (table, cols, rtypes)."""
    label_cols = ["Region", "Master Location", "Store Code", "Location", "Brand"]
    val_order = [c for c in GD_ORDER if c in detail.columns]
    out_cols = label_cols + val_order

    def total_row(sub, put_col, label):
        r = {c: "" for c in out_cols}
        r[put_col] = label
        for c in GD_MONEY:
            if c in val_order:
                r[c] = pd.to_numeric(sub[c], errors="coerce").sum()
        r["GD YTD %"] = ((r["YTD TY"] - r["YTD LY"]) / r["YTD LY"] * 100
                         if r.get("YTD LY") else None)
        r["GD MTD %"] = ((r["MTD TY"] - r["MTD LY"]) / r["MTD LY"] * 100
                         if r.get("MTD LY") else None)
        return r

    rows, rtypes = [], []
    for reg in [r for r in ["East & NE", "South"] if r in detail["Region"].unique()]:
        rsub = detail[detail["Region"] == reg]
        for code in pd.unique(rsub["Store Code"]):
            ssub = rsub[rsub["Store Code"] == code]
            loc = ssub["Location"].iloc[0]
            for gender in ["MEN", "WOMEN"]:
                gsub = ssub[ssub["Gender"] == gender]
                if gsub.empty:
                    continue
                for _, rr in gsub.iterrows():
                    rows.append({c: rr[c] for c in out_cols})
                    rtypes.append("store")
                gt = total_row(gsub, "Brand", f"{gender} Total")
                gt["Location"], gt["Store Code"] = loc, code
                rows.append(gt)
                rtypes.append("storetotal")            # peach gender subtotal
            stt = total_row(ssub, "Brand", "Store Total")
            stt["Location"], stt["Store Code"] = loc, code
            rows.append(stt)
            rtypes.append("block")                     # blue store total
        rows.append(total_row(rsub, "Region", f"{reg} Total"))
        rtypes.append("subtotal")                      # pink region subtotal
    rows.append(total_row(detail, "Region", "Grand Total"))
    rtypes.append("grand")                             # green grand total
    return pd.DataFrame(rows)[out_cols], out_cols, rtypes


def render_store_brand_gd(detail, key):
    """Render the store × brand-line G/D table (widest sheet → compact)."""
    table, cols, rtypes = build_store_brand_gd(detail)
    money = [c for c in GD_MONEY if c in cols]
    st.markdown(
        styled_report_html(table, money_cols=money, pct_cols=GD_PCT,
                           sign_cols=GD_PCT, row_types=rtypes, compact=True),
        unsafe_allow_html=True)
    st.write("")
    st.download_button("⬇ Download (CSV)", table.to_csv(index=False).encode(),
                       file_name=f"{key}.csv", mime="text/csv",
                       key=f"{key}_csv", use_container_width=True)
    return table


(tab_report, tab_degrowth, tab_gender_gd, tab_brand_gd, tab_storebrand,
 tab_gender_mix, tab_exec, tab_overview, tab_stores, tab_build,
 tab_trends, tab_cat, tab_staff, tab_cust, tab_merch) = st.tabs([
    "📋 MTD / YTD Report", "📉 Degrowth",
    "🧑‍🤝‍🧑 Gender G/D", "🏷️ Brand G/D", "🏬 Store × Brand G/D", "⚖️ Gender Mix",
    "📊 Executive", "Overview", "🏬 Stores",
    "🔧 Build your view", "Trends", "Category mix", "Salespeople",
    "Customers", "Colors & sizes",
])

# =========================================================================== #
# MTD / YTD REPORT — region × store, year-on-year (the executive table)
# =========================================================================== #
with tab_report:
    st.subheader("Store-wise MTD / YTD — Year on Year")
    st.caption(
        f"**As of {end_d:%d %b %Y}** (follows the date picker). "
        "MTD = month to date · YTD = financial year (Apr–Mar) to date · "
        "LY = same period last year · TY = this year · GD = growth/degrowth. "
        "All values in ₹, 2 decimals. Red = degrowth."
    )
    rep, rtypes = L.region_store_report(df_exec, asof=pd.Timestamp(end_d))
    if rep.empty:
        st.info("No stores match the current filters.")
        st.stop()

    _t1, _t2 = st.columns(2)
    compact = _t1.toggle(
        "📱 Compact view (best on mobile)", value=False,
        help="Shows the key columns only — easier to read on a phone.")
    fullscreen = _t2.toggle(
        "🖥️ Full-screen fit view (for screenshots)", value=False,
        help="Scales the whole table to fit one screen — no scrolling — so a "
             "single screenshot captures every row and column.")
    if compact:
        show_cols = ["Region", "DATE", "STORE CODE", "LOCATION",
                     "MTD TY", "GD MTD %", "Day Sales", "YTD TY", "GD YTD %"]
    else:
        show_cols = list(rep.columns)
    rep_show = rep[show_cols]

    val_cols = [c for c in ["Day Sales", "MTD LY", "MTD TY", "GD MTD Value",
                            "YTD LY", "YTD TY", "GD YTD Value"] if c in show_cols]
    pct_cols = [c for c in ["GD MTD %", "GD YTD %"] if c in show_cols]
    sign_cols = [c for c in ["GD MTD Value", "GD MTD %",
                             "GD YTD Value", "GD YTD %"] if c in show_cols]

    if fullscreen:
        st.caption("Opens the whole table in full screen, scaled to fit — nothing "
                   "cut off. Screenshot it, then press Esc to exit.")
        render_fit_to_screen(
            styled_report_html(rep_show, money_cols=val_cols, pct_cols=pct_cols,
                               sign_cols=sign_cols, row_types=rtypes,
                               full_width=False))
    else:
        st.markdown(
            styled_report_html(rep_show, money_cols=val_cols, pct_cols=pct_cols,
                               sign_cols=sign_cols, row_types=rtypes),
            unsafe_allow_html=True)
    st.write("")

    _c1, _c2 = st.columns(2)
    _c1.download_button(
        "⬇ Download report (CSV)",
        rep.to_csv(index=False).encode(),
        file_name=f"peanuts_mtd_ytd_report_{end_d:%Y%m%d}.csv",
        mime="text/csv", use_container_width=True,
    )
    if _c2.button("🖼️ Generate shareable image (PNG)", key="rep_png_btn",
                  use_container_width=True):
        sdf = rep_show.copy()
        _money = [c for c in ["Day Sales", "MTD LY", "MTD TY", "GD MTD Value",
                              "YTD LY", "YTD TY", "GD YTD Value"] if c in sdf.columns]
        _pct = [c for c in ["GD MTD %", "GD YTD %"] if c in sdf.columns]
        for c in _money:
            sdf[c] = sdf[c].map(_fmt_cell_money)
        for c in _pct:
            sdf[c] = sdf[c].map(_fmt_cell_pct)
        sdf = sdf.astype(str)
        row_bg = []
        for _k, _t in enumerate(rtypes):
            if _t == "subtotal":
                row_bg.append("#F6D9D5")
            elif _t == "grand":
                row_bg.append("#CDE8CF")
            else:
                row_bg.append("#FFFFFF" if _k % 2 == 0 else "#FAF6EF")
        st.session_state["rep_png"] = table_to_png(
            sdf, "", row_bg=row_bg, signed_cols=_money + _pct)
    if st.session_state.get("rep_png"):
        st.download_button(
            "⬇ Download image", st.session_state["rep_png"],
            file_name=f"peanuts_mtd_ytd_{end_d:%Y%m%d}.png", mime="image/png")
        st.image(st.session_state["rep_png"],
                 caption="Preview — share this picture in the group")

# =========================================================================== #
# DEGROWTH — stores below last year (watchlist)
# =========================================================================== #
with tab_degrowth:
    st.subheader("Degrowth watchlist")
    dg_kind = st.radio("Period", ["YTD", "MTD"], horizontal=True, key="dg_kind")
    st.caption(
        f"Stores where **{dg_kind} This Year < Last Year**, as of "
        f"**{end_d:%d %b %Y}** — sorted by store code. Respects all filters.")
    dg = L.degrowth_report(df_exec, asof=pd.Timestamp(end_d), kind=dg_kind)

    if dg.empty:
        st.success("🎉 No stores in degrowth for this selection.")
    else:
        _tot = dg["shortfall"].sum()
        _ly = dg["prior"].sum()
        _pct = (_tot / _ly * 100) if _ly else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Stores degrowing", f"{len(dg)}")
        c2.metric("Total shortfall", inr(_tot))
        c3.metric("Degrowth %", f"{_pct:.2f}%")

        disp = dg.copy()
        disp.insert(0, "DATE", f"{end_d:%d-%m-%Y}")
        disp = disp.rename(columns={
            "region": "Region", "code": "STORE CODE", "location": "LOCATION",
            "prior": f"{dg_kind} LY", "cur": f"{dg_kind} TY",
            "shortfall": "Shortfall", "growth": "Degrowth %"})

        val_cols = [f"{dg_kind} LY", f"{dg_kind} TY", "Shortfall"]
        st.markdown(
            styled_report_html(disp, money_cols=val_cols, pct_cols=["Degrowth %"],
                               sign_cols=["Shortfall", "Degrowth %"]),
            unsafe_allow_html=True)
        st.write("")
        _d1, _d2 = st.columns(2)
        _d1.download_button(
            "⬇ Download degrowth list (CSV)", disp.to_csv(index=False).encode(),
            file_name=f"peanuts_degrowth_{dg_kind}_{end_d:%Y%m%d}.csv",
            mime="text/csv", use_container_width=True)
        if _d2.button("🖼️ Generate shareable image (PNG)", key="dg_png_btn",
                      use_container_width=True):
            sdf = disp.copy()
            for c in [f"{dg_kind} LY", f"{dg_kind} TY", "Shortfall"]:
                sdf[c] = sdf[c].map(_fmt_cell_money)
            sdf["Degrowth %"] = sdf["Degrowth %"].map(_fmt_cell_pct)
            sdf = sdf.astype(str)
            dg_bg = ["#FFFFFF" if k % 2 == 0 else "#FAF6EF" for k in range(len(sdf))]
            st.session_state["dg_png"] = table_to_png(
                sdf, "", row_bg=dg_bg, signed_cols=["Shortfall", "Degrowth %"])
        if st.session_state.get("dg_png"):
            st.download_button(
                "⬇ Download image", st.session_state["dg_png"],
                file_name=f"peanuts_degrowth_{dg_kind}_{end_d:%Y%m%d}.png",
                mime="image/png")
            st.image(st.session_state["dg_png"],
                     caption="Preview — share this picture in the group")

# =========================================================================== #
# GENDER-WISE GROWTH / DEGROWTH  (Region → Gender, FY YoY)
# =========================================================================== #
with tab_gender_gd:
    st.subheader("Gender-wise Growth / Degrowth")
    st.caption("Store × gender, MTD & YTD this year vs last (fiscal Apr–Mar). "
               "Red = degrowth. Gender follows the brand line "
               "(Mohey / Twamev-Women / Mebaz = Women).")
    c1, c2 = st.columns(2)
    with c1:
        view = st.radio("View", ["Store detail", "Region summary"], horizontal=True,
                        key="gender_gd_view", label_visibility="collapsed")
    with c2:
        gd_asof = gd_basis_control("gender_gd_basis", end_d)
    if view == "Store detail":
        g = L.gender_store_gd(df_exec, asof=gd_asof)
        if g.empty:
            st.info("No data for the current filters.")
        else:
            render_gd_grouped(g, f"gender_gd_store_{gd_asof:%Y%m%d}")
    else:
        g = L.gender_wise_gd(df_exec, asof=gd_asof)
        if g.empty:
            st.info("No data for the current filters.")
        else:
            render_gd_table(g, ["Region", "Gender"], f"gender_gd_{gd_asof:%Y%m%d}",
                            region_grouped=True)

# =========================================================================== #
# BRAND-WISE GROWTH / DEGROWTH  (Manyavar / Mohey / Twamev / …, FY YoY)
# =========================================================================== #
with tab_brand_gd:
    st.subheader("Brand-wise Growth / Degrowth")
    st.caption("MTD & YTD YoY by brand. Scope = the Manyavar-group brands in "
               "the sales feed.")
    gd_asof = gd_basis_control("brand_gd_basis", end_d)
    b = L.brand_wise_gd(df_exec, asof=gd_asof)
    if b.empty:
        st.info("No data for the current filters.")
    else:
        render_gd_table(b, ["Brand"], f"brand_gd_{gd_asof:%Y%m%d}")

# =========================================================================== #
# STORE × BRAND G/D — brand-line detail within each store (deepest VFL level)
# =========================================================================== #
with tab_storebrand:
    st.subheader("Store × Brand-line Growth / Degrowth")
    st.caption("Each store broken down by brand-line (Manyavar / Twamev Men / "
               "Manthan / Mohey / Twamev-Women / Mebaz — any other division folds "
               "into Manyavar), grouped by gender: **MEN Total** and **WOMEN "
               "Total** (peach), a **Store Total** (blue), then region & grand "
               "totals. Takeover-anchored, red = degrowth.")
    sb_asof = gd_basis_control("storebrand_basis", end_d)
    sb = L.store_brand_gd(df_exec, asof=sb_asof)
    if sb.empty:
        st.info("No data for the current filters.")
    else:
        render_store_brand_gd(sb, f"store_brand_gd_{sb_asof:%Y%m%d}")

# =========================================================================== #
# GENDER MIX — contribution %  (Region × Gender + store detail)
# =========================================================================== #
with tab_gender_mix:
    st.subheader("Gender-wise Contribution %")
    st.caption("Each gender's share of sales, MTD & YTD.")
    c1, c2 = st.columns(2)
    with c1:
        view = st.radio("View", ["Store detail", "Region summary"], horizontal=True,
                        key="gender_mix_view", label_visibility="collapsed")
    with c2:
        gd_asof = gd_basis_control("gender_mix_basis", end_d)
    detail, summary = L.gender_contribution(df_exec, asof=gd_asof)
    if summary.empty:
        st.info("No data for the current filters.")
    elif view == "Store detail":
        render_gender_mix_grouped(detail, f"gender_mix_store_{gd_asof:%Y%m%d}")
    else:
        srows, srtypes = [], []
        for reg in [r for r in ["East & NE", "South"] if r in summary["Region"].unique()]:
            sub = summary[summary["Region"] == reg]
            for _, rr in sub.iterrows():
                srows.append(rr.to_dict())
                srtypes.append("store")
            srows.append({"Region": f"{reg} Total", "Gender": "",
                          "MTD TY": sub["MTD TY"].sum(), "Contrib MTD %": 100.0,
                          "YTD TY": sub["YTD TY"].sum(), "Contrib YTD %": 100.0})
            srtypes.append("subtotal")
        gt = {"Region": "Grand Total", "Gender": "",
              "MTD TY": summary["MTD TY"].sum(), "Contrib MTD %": 100.0,
              "YTD TY": summary["YTD TY"].sum(), "Contrib YTD %": 100.0}
        srows.append(gt)
        srtypes.append("grand")
        stab = pd.DataFrame(srows)[["Region", "Gender", "MTD TY",
                                    "Contrib MTD %", "YTD TY", "Contrib YTD %"]]
        st.markdown(
            styled_report_html(stab, money_cols=["MTD TY", "YTD TY"],
                               pct_cols=["Contrib MTD %", "Contrib YTD %"],
                               row_types=srtypes),
            unsafe_allow_html=True)
        st.write("")
        st.download_button(
            "⬇ Download (CSV)", summary.to_csv(index=False).encode(),
            file_name=f"gender_mix_{gd_asof:%Y%m%d}.csv", mime="text/csv",
            use_container_width=True)

# =========================================================================== #
# EXECUTIVE — MTD / QTD / YTD, all year-on-year (fiscal year Apr–Mar)
# =========================================================================== #
with tab_exec:
    asof = pd.Timestamp(end_d)
    st.caption(
        f"**As of {asof:%d %b %Y}** (follows the date picker). Fiscal year "
        f"**Apr–Mar**, each store counted from its **takeover date** "
        f"(South: 19 Apr 2025). All figures **year-on-year** vs the same period "
        f"last year. Respects the Store / filters."
    )
    wins = L.standard_windows(df_exec, asof=asof)
    mtd_r = L.window_yoy_takeover(df_exec, "MTD", asof=asof)
    ytd_r = L.window_yoy_takeover(df_exec, "YTD", asof=asof)

    # Hero scorecard — the headline numbers.
    h = st.columns(4)
    h[0].markdown(kpi_card("YTD Sales", inr(ytd_r["cur"]["sales"]),
                           ytd_r["growth"]["sales"], hero=True), unsafe_allow_html=True)
    h[1].markdown(kpi_card("MTD Sales", inr(mtd_r["cur"]["sales"]),
                           mtd_r["growth"]["sales"], hero=True), unsafe_allow_html=True)
    h[2].markdown(kpi_card("YTD Bills", f'{ytd_r["cur"]["bills"]:,}',
                           ytd_r["growth"]["bills"], hero=True), unsafe_allow_html=True)
    h[3].markdown(kpi_card("YTD Avg Bill", inr(ytd_r["cur"]["atv"]),
                           ytd_r["growth"]["atv"], hero=True), unsafe_allow_html=True)
    st.markdown("---")

    exec_window_row("MTD — Month to date", mtd_r)
    st.markdown("")
    exec_window_row("QTD — Quarter to date", L.window_yoy(df_exec, *wins["QTD"]))
    st.markdown("")
    exec_window_row("YTD — Financial year to date", ytd_r)
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
    sy = L.store_yoy(df_exec, "YTD", asof=asof).rename(columns={
        L.COL_STORE_LABEL: "Store", "cur": "YTD (₹)", "prior": "LY YTD (₹)",
        "growth": "Growth %"})
    sy = sy.sort_values("Growth %", ascending=True, na_position="last")
    _safe_dataframe(
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
        "Break stores down by", list(L.METRICS.keys()), index=0,
        key="store_rank_metric",
    )
    st.markdown(f"**Store × {granularity} — {rank_metric}**")
    draw_view({"metric": rank_metric, "group_dim": granularity,
               "split_dim": "Store", "_key": "st_pivot"})

    st.markdown("---")
    ss_raw = L.store_summary(df)
    st.caption("Sales/sqft = sales in view ÷ carpet area (retail productivity). "
               "Click a column header to sort.")

    st.subheader("Per-store KPI table")
    ss = ss_raw.rename(columns={
        L.COL_STORE_LABEL: "Store", "sales": "Sales (₹)", "units": "Units",
        "bills": "Bills", "customers": "Customers", "atv": "ATV (₹)",
        "upt": "UPT", "asp": "ASP (₹)", "carpet_area": "Carpet Area (sqft)",
        "sales_psf": "Sales/sqft (₹)"})
    _safe_dataframe(
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
        "Pick a metric and a dimension to break it down by (optionally a second "
        "dimension to split by) — you get a numbers table. Add as many as you like; "
        "this layout is yours for this session."
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
        c4, c5 = st.columns(2)
        n_top = c4.slider("Top N (categories)", 3, 50, 15, key="nb_top")
        n_width = c5.selectbox("Width", ["Full", "Half"], key="nb_width")
        n_title = st.text_input("Panel title", value=f"{n_metric} by {n_group}",
                                key="nb_title")
        if st.button("Add table", type="primary"):
            st.session_state.panels.append({
                "title": n_title, "metric": n_metric, "group_dim": n_group,
                "split_dim": n_split, "top": n_top, "width": n_width,
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
    st.caption(f"{len(sp)} salespeople in view · click a column header to sort")
    _safe_dataframe(
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

    if not cs["trend"].empty:
        st.subheader("Repeat share by month")
        rt = cs["trend"][["month_label", "repeat_share", "bills"]].rename(
            columns={"month_label": "Month", "repeat_share": "Repeat share %",
                     "bills": "Bills"})
        _safe_dataframe(
            rt, use_container_width=True, hide_index=True,
            column_config={"Repeat share %":
                           st.column_config.NumberColumn(format="%.1f%%")},
        )

    st.subheader("Top customers by spend")
    mask_num = st.checkbox("Mask mobile numbers", value=True)
    top = cs["top"].rename(
        columns={L.COL_MOBILE: "Mobile", "spend": "Spend (₹)", "visits": "Visits"})
    if mask_num:
        top["Mobile"] = top["Mobile"].astype(str).apply(
            lambda m: m[:2] + "•••" + m[-2:] if len(m) >= 4 else "•••")
    _safe_dataframe(
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
