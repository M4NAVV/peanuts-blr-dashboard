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
                       row_types=None, font_px=12.5, full_width=True):
    """Compact, high-contrast HTML table built with INLINE styles (so colors
    always render in Streamlit): maroon header, zebra rows, tabular right-aligned
    numbers, shaded subtotals/totals, and red/green on growth columns."""
    money, pct, sign = set(money_cols), set(pct_cols), set(sign_cols)
    cols = list(disp.columns)

    def align(c):
        return "right" if (c in money or c in pct) else "left"

    ths = "".join(
        f'<th style="background:{MAROON};color:#fff;font-weight:700;'
        f'font-size:{font_px - 1:.0f}px;text-transform:uppercase;letter-spacing:.02em;'
        f'padding:8px 10px;text-align:{align(c)};position:sticky;top:0;'
        f'white-space:nowrap;">{c}</th>' for c in cols)

    trs = []
    for i in range(len(disp)):
        t = row_types[i] if row_types is not None else "store"
        if t == "subtotal":
            rbg, fw = "#F6D9D5", "700"
        elif t == "grand":
            rbg, fw = "#CDE8CF", "800"
        else:
            rbg, fw = ("#FFFFFF" if i % 2 == 0 else "#FAF6EF"), "500"
        tds = []
        for c in cols:
            v = disp.iloc[i][c]
            if c in money:
                txt = fmt_in(v, 2) if pd.notna(v) else "—"
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
                f'<td style="padding:5px 10px;text-align:{align(c)};color:{color};'
                f'font-weight:{fw};background:{rbg};border-bottom:1px solid #ECE4D6;'
                f'white-space:nowrap;font-variant-numeric:tabular-nums;">{txt}</td>')
        trs.append(f"<tr>{''.join(tds)}</tr>")

    width_css = "width:100%;" if full_width else "width:auto;"
    table = (
        f'<table style="border-collapse:collapse;{width_css}'
        f'font-family:Inter,-apple-system,Segoe UI,sans-serif;font-size:{font_px}px;">'
        f'<thead><tr>{ths}</tr></thead><tbody>{"".join(trs)}</tbody></table>')
    if not full_width:
        return table
    return (f'<div style="overflow-x:auto;border:1px solid #E7E1D6;'
            f'border-radius:10px;">{table}</div>')


def render_fit_to_screen(table_html, panel_h=680):
    """Render the report with a 'Full screen' button. Clicking it overlays the
    whole browser window and scales the table (CSS transform) to fit exactly —
    no scrollbars, nothing cut off — so a single screenshot of the screen
    captures every row and column. Esc or the button exits. Auto-refits on
    load / resize / enter / exit."""
    doc = f"""
    <div id="fitwrap" style="width:100%;height:{panel_h}px;overflow:hidden;
         background:#fff;display:flex;flex-direction:column;align-items:center;">
      <button id="fsbtn" style="align-self:flex-start;margin:2px 0 10px;padding:9px 18px;
              border:0;border-radius:8px;background:{MAROON};color:#fff;font-weight:700;
              font-size:14px;cursor:pointer;font-family:Inter,Segoe UI,sans-serif;">
        ⛶ Full screen — fit all data
      </button>
      <div id="fitinner" style="flex:1;width:100%;overflow:hidden;display:flex;
           justify-content:center;align-items:flex-start;">
        <div id="fittable" style="transform-origin:top center;">{table_html}</div>
      </div>
    </div>
    <script>
      var wrap=document.getElementById('fitwrap');
      var inner=document.getElementById('fitinner');
      var t=document.getElementById('fittable');
      var btn=document.getElementById('fsbtn');
      var big=false, saved={{}};
      function fit() {{
        t.style.transform='scale(1)';
        var s=Math.min(inner.clientWidth/t.scrollWidth,
                       inner.clientHeight/t.scrollHeight);
        t.style.transform='scale('+Math.min(s,2.6)+')';
      }}
      function chrome(hide) {{
        try {{
          var d=window.parent.document;
          d.querySelectorAll('header[data-testid="stHeader"]')
           .forEach(function(e){{ e.style.display = hide?'none':''; }});
        }} catch(e){{}}
      }}
      function enter() {{
        var f=window.frameElement;
        try {{
          saved={{pos:f.style.position,top:f.style.top,left:f.style.left,
                 w:f.style.width,h:f.style.height,z:f.style.zIndex}};
          f.style.position='fixed'; f.style.top='0'; f.style.left='0';
          f.style.width='100vw'; f.style.height='100vh'; f.style.zIndex='2147483647';
        }} catch(e){{}}
        wrap.style.height='100vh'; inner.style.alignItems='center';
        chrome(true); big=true; btn.textContent='✕  Exit full screen (Esc)';
        setTimeout(fit,30); setTimeout(fit,150);
      }}
      function exit() {{
        var f=window.frameElement;
        try {{ f.style.position=saved.pos||''; f.style.top=saved.top||'';
               f.style.left=saved.left||''; f.style.width=saved.w||'';
               f.style.height=saved.h||''; f.style.zIndex=saved.z||''; }} catch(e){{}}
        wrap.style.height='{panel_h}px'; inner.style.alignItems='flex-start';
        chrome(false); big=false; btn.textContent='⛶ Full screen — fit all data';
        setTimeout(fit,30);
      }}
      btn.addEventListener('click', function(){{ big?exit():enter(); }});
      document.addEventListener('keydown', function(e){{ if(e.key==='Escape'&&big) exit(); }});
      window.addEventListener('resize', fit);
      window.addEventListener('load', fit);
      setTimeout(fit,50); setTimeout(fit,300);
    </script>"""
    components.html(doc, height=panel_h, scrolling=False)


def _fmt_cell_money(v):
    return fmt_in(v, 2) if pd.notna(v) else "—"


def _fmt_cell_pct(v):
    return f"{v:,.2f}%" if pd.notna(v) else "—"


def table_to_png(sdf, title, subtitle="", row_bg=None, signed_cols=(),
                 header_bg=MAROON):
    """Render a string DataFrame to a readable PNG (for sharing), matching the
    dashboard look. Colors signed columns red/green by sign and shades rows via
    `row_bg` (list per row)."""
    import io
    # Use matplotlib's object-oriented API (Figure + Agg canvas) rather than
    # pyplot. pyplot keeps a global, non-thread-safe figure-manager state; when
    # invoked from Streamlit's ScriptRunner worker thread it segfaults the Agg
    # C-extension. Building a Figure directly touches no global state.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    cols = list(sdf.columns)
    nrow, ncol = len(sdf), len(cols)
    widths = [max([len(str(c))] + [len(str(x)) for x in sdf[c]]) for c in cols]
    fig_w = min(1.0 + 0.135 * sum(widths), 30)
    fig_h = 1.2 + (nrow + 1) * 0.36
    fig = Figure(figsize=(fig_w, fig_h), dpi=170)
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.axis("off")
    if title or subtitle:
        ax.set_title("\n".join(t for t in (title, subtitle) if t),
                     fontsize=13, weight="bold", color="#7A1F2B", pad=12)
    tbl = ax.table(cellText=sdf.values.tolist(), colLabels=cols,
                   cellLoc="center", loc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1, 1.45)
    tbl.auto_set_column_width(list(range(ncol)))
    signed = set(signed_cols)
    for j in range(ncol):
        h = tbl[0, j]
        h.set_facecolor(header_bg)
        h.set_text_props(color="white", weight="bold")
    for i in range(nrow):
        bg = row_bg[i] if row_bg else None
        for j, c in enumerate(cols):
            cell = tbl[i + 1, j]
            if bg:
                cell.set_facecolor(bg)
            val = str(sdf.iat[i, j]).strip()
            if c in signed and val not in ("", "—"):
                cell.set_text_props(
                    color="#C0143C" if val.startswith("-") else "#137a3a",
                    weight="bold")
            elif bg:
                cell.set_text_props(weight="bold")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    return buf.getvalue()


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
    f"**Data through:** {fresh['max_date']:%d %b %Y}  \n**Rows:** {fresh['rows']:,}")
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

(tab_report, tab_degrowth, tab_exec, tab_overview, tab_stores, tab_build,
 tab_trends, tab_cat, tab_staff, tab_cust, tab_merch) = st.tabs([
    "📋 MTD / YTD Report", "📉 Degrowth", "📊 Executive", "Overview", "🏬 Stores",
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
        st.caption("Click **Full screen** below — the whole table scales to fit your "
                   "screen with nothing cut off. Take your screenshot, then press Esc "
                   "(or the button) to exit.")
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

    if not cs["trend"].empty:
        st.subheader("Repeat share by month")
        rt = cs["trend"][["month_label", "repeat_share", "bills"]].rename(
            columns={"month_label": "Month", "repeat_share": "Repeat share %",
                     "bills": "Bills"})
        st.dataframe(
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
