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
import portfolio_loader as PL
from imaging import table_to_png

st.set_page_config(
    page_title="VFL × Peanuts Retail — Sales Dashboard",
    page_icon="Ⓜ️",
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

      /* ---- Top navigation: 7 report pills + a "More" overflow menu ---- */
      [data-testid="stButtonGroup"] {{ margin: 16px 0 !important; }}
      [data-testid^="stBaseButton-segmented_control"] {{
        border-radius: 999px !important; padding: 4px 12px !important;
        font-weight: 600 !important; font-size: 0.78rem !important;
        white-space: nowrap !important; min-height: 34px !important;
        color: {MAROON} !important; background: #FFFFFF !important;
        border: 1px solid #ECE4D6 !important; transition: all .12s ease;
      }}
      [data-testid^="stBaseButton-segmented_control"] p {{
        color: {MAROON} !important; white-space: nowrap !important; font-size: 0.78rem !important;
      }}
      [data-testid^="stBaseButton-segmented_control"]:hover {{
        background: #FBEFEA !important; border-color: {MAROON} !important;
      }}
      [data-testid="stBaseButton-segmented_controlActive"] {{
        background: {MAROON} !important; border-color: {MAROON} !important;
        box-shadow: 0 1px 4px rgba(122,31,43,.28);
      }}
      [data-testid="stBaseButton-segmented_controlActive"] p {{ color: #FFFFFF !important; }}

      /* "More" popover trigger — same pill look + height as the tabs */
      [data-testid="stPopoverButton"] {{
        border-radius: 999px !important; padding: 4px 14px !important;
        min-height: 34px !important; font-weight: 600 !important;
        font-size: 0.78rem !important; color: {MAROON} !important;
        background: #FFFFFF !important; border: 1px solid #ECE4D6 !important;
      }}
      [data-testid="stPopoverButton"] p {{ font-size: 0.78rem !important; }}
      [data-testid="stPopoverButton"]:hover {{
        background: #FBEFEA !important; border-color: {MAROON} !important;
      }}
      /* menu items inside the "More" popover — clean left-aligned list */
      [data-testid="stPopoverBody"] [data-testid="stButton"] button {{
        justify-content: flex-start !important; text-align: left !important;
        border: none !important; background: transparent !important;
        color: {INK} !important; font-weight: 500 !important;
        border-radius: 8px !important; padding: 6px 10px !important;
      }}
      [data-testid="stPopoverBody"] [data-testid="stButton"] button:hover {{
        background: #FBEFEA !important; color: {MAROON} !important;
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
    # Carried out of the cache explicitly; attrs are not guaranteed to survive it.
    return (df, datetime.now(ZoneInfo("Asia/Kolkata")),
            df.attrs.get("provisional_date"))


def get_data() -> pd.DataFrame:
    return _load_cached()[0]


def vfl_provisional_date():
    """The day VFL data came from the night fill rather than the sheet, if any."""
    try:
        return _load_cached()[2]
    except Exception:
        return None


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


# The client's workbook palette, sampled off their reference PDF — the same
# constants the report PDFs use (see portfolio_pdf.py).
WB_HDR_BG, WB_INK = "#DAEEF3", "#000000"
WB_TOTAL, WB_NEG, WB_GRID = "#FFFF00", "#FF0000", "#9AA0A6"
# GD/Brand/Loc/Average sheets colour every total tier the same yellow; the VFL
# sheets grade them instead.
WB_ROWS = {"subtotal": WB_TOTAL, "grand": WB_TOTAL,
           "storetotal": WB_TOTAL, "block": WB_TOTAL, "loctotal": WB_TOTAL}
WB_ROWS_VFL = {"storetotal": "#FDE9D9", "subtotal": "#95B3D7",
               "loctotal": "#92D050", "block": "#92D050", "grand": WB_TOTAL}


def styled_report_html(disp, money_cols=(), pct_cols=(), sign_cols=(),
                       row_types=None, font_px=12.5, full_width=True,
                       compact=False, palette="workbook"):
    """Compact, high-contrast HTML table built with INLINE styles (so colors
    always render in Streamlit): tabular right-aligned numbers, shaded
    subtotals/totals, and negatives in red.

    Colours are the client's own, sampled off their GROWTH DEGROWTH workbook
    print, so the dashboard and the report PDFs read as one document rather than
    two systems that happen to share numbers. `palette="vfl"` selects the graded
    tiers their VFL sheets use instead of the flat yellow of the GD sheets.

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

    tiers = WB_ROWS_VFL if palette == "vfl" else WB_ROWS
    ths = "".join(
        f'<th style="background:{WB_HDR_BG};color:{WB_INK};font-weight:700;'
        f'font-size:{font_px - 1:.0f}px;text-transform:uppercase;letter-spacing:.01em;'
        f'padding:{th_pad};text-align:center;position:sticky;top:0;'
        f'line-height:1.15;white-space:normal;vertical-align:bottom;'
        f'border:1px solid {WB_GRID};">{c}</th>'
        for c in cols)

    trs = []
    for i in range(len(disp)):
        t = row_types[i] if row_types is not None else "store"
        # White body, no zebra — the workbook relies on the grid, not banding.
        rbg = tiers.get(t, "#FFFFFF")
        fw = "700" if t in tiers else "500"
        tds = []
        for c in cols:
            v = disp.iloc[i][c]
            if c in money:
                txt = fmt_in(v, money_dp) if pd.notna(v) else "—"
            elif c in pct:
                txt = f"{v:,.2f}%" if pd.notna(v) else "—"
            else:
                txt = "" if (isinstance(v, float) and pd.isna(v)) else str(v)
            # Negatives are red TEXT, not a red fill. On screen a solid fill
            # fights the total-row shading and reads as a block of alarm; the
            # figures are what matter, so the colour goes on them.
            cbg, color, cfw = rbg, WB_INK, fw
            if c in sign and pd.notna(v):
                try:
                    if float(v) < 0:
                        color, cfw = WB_NEG, "700"
                except (TypeError, ValueError):
                    pass
            tds.append(
                f'<td style="padding:{td_pad};text-align:{align(c)};color:{color};'
                f'font-weight:{cfw};background:{cbg};border:1px solid {WB_GRID};'
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
    return (f'<div style="overflow-x:auto;max-width:100%;border:1px solid {WB_GRID};'
            f'border-radius:4px;display:inline-block;">{table}</div>')


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


# =========================================================================== #
# PORTFOLIO MODE — breadth layer (all 63 stores, sales-only)
# A self-contained render path so the VFL (depth) code below stays untouched.
# =========================================================================== #
@st.cache_data(ttl=21600, show_spinner="Loading portfolio sales…")
def _load_portfolio_cached():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    df = PL.load_portfolio()
    # Carried out of the cache explicitly rather than read off df.attrs, which
    # is not guaranteed to survive caching.
    return (df, datetime.now(ZoneInfo("Asia/Kolkata")),
            df.attrs.get("provisional_date"))


def _open_store_count() -> int | None:
    """Stores the master says are trading — the estate the feed should carry."""
    try:
        import loader as _L
        m = PL.store_master().dropna(subset=["code"])
        shut = _L.closed_map()
        today = pd.Timestamp.today().normalize()
        return int(sum(1 for c in m["code"].astype(int)
                       if not (c in shut and pd.Timestamp(shut[c]) <= today)))
    except Exception:
        return None


def _gate(df, kind, *, date_col, store_col, value_col, expect_stores=None):
    """Refuse to serve a feed that is not fit, and say why on screen.

    The override exists because a check can be wrong, and a wrong check must
    not take the dashboard away from the team. It is deliberate, it is visible,
    and the numbers are labelled unvalidated while it is on.
    """
    import validation
    rep = validation.validate(df, kind, date_col=date_col, store_col=store_col,
                              value_col=value_col, expect_stores=expect_stores)
    if rep.problems:
        st.error("**This data does not look right, so it is not being shown.**")
        for p in rep.problems:
            st.markdown(f"- {p}")
        st.caption(f"What arrived: {rep.summary()}"
                   + (f" · last good load: {rep.baseline['rows']:,} rows through "
                      f"{rep.baseline['max_date']}" if rep.baseline else ""))
        if not st.checkbox("Show it anyway (numbers are unverified)",
                           key=f"override_{kind}"):
            st.stop()
        st.warning("Showing unverified data — treat every figure as suspect.")
    for w in rep.warnings:
        st.warning(w)
    return rep


def _cr(x) -> str:
    return f"₹{(x or 0) / 1e7:,.2f} Cr"


_PF_TABS = ["📈 MW Data", "🧾 GD Sheet", "🏷️ Brand-wise GD", "🗺️ Loc-wise GD",
            "📐 Average", "📊 Executive", "📋 MTD / YTD Report", "📉 Degrowth",
            "🎯 Day Targets", "🥧 Contribution", "🏙️ City-wise G/D", "🏬 Stores",
            "📅 Monthly", "📄 Report PDF", "📑 REPORT T.D."]


def render_portfolio():
    try:
        pf_all, pf_at, pf_provisional = _load_portfolio_cached()
    except Exception as e:                      # the boundary — see `feed.py`
        st.error(f"**The portfolio data could not be loaded.** {e}")
        st.info("Nothing below would be trustworthy without it, so the page "
                "stops here. Fix the source and press R to reload.")
        st.stop()
    _gate(pf_all, "portfolio", date_col="date", store_col="code",
          value_col="sales", expect_stores=_open_store_count())

    # ---- Sidebar: portfolio brand + cascading sales-only filters ----
    st.sidebar.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin:0 0 2px;">'
        f'<div style="width:38px;height:38px;border-radius:9px;background:{GOLD};'
        f'color:{MAROON};font-weight:800;font-size:20px;font-family:Georgia,serif;'
        f'display:flex;align-items:center;justify-content:center;flex:0 0 auto;">◎</div>'
        f'<div style="font-size:18px;font-weight:800;color:{MAROON};line-height:1.12;">'
        f'Whole Portfolio</div></div>', unsafe_allow_html=True)
    st.sidebar.caption(
        f"{pf_all['code'].nunique()} stores · {pf_all['brand'].nunique()} brands · "
        f"sales-only breadth view")
    # Always state the last day the data covers. Portfolio mode had no freshness
    # line at all, so a stale cache and a fresh one looked identical — the point
    # of the reliability audit's fourth finding, and how a missing night fill
    # went unnoticed.
    st.sidebar.caption(
        f"**Data through {pf_all['date'].max():%d %b %Y}** · "
        f"loaded {pf_at:%H:%M}")
    if pf_provisional is not None:
        # The latest day came from the night fill, before the morning paste.
        # Say so wherever it is used: a provisional figure that looks final is
        # the failure this whole pipeline exists to avoid.
        st.sidebar.warning(
            f"**{pf_provisional:%d %b}** is provisional — taken from the night "
            f"fill, not yet pasted or replaced by Tableau.")
    else:
        # A configured night fill that yields nothing is worth saying out loud:
        # it went dead once already when the tab's columns were rearranged, and
        # nothing on screen showed it.
        try:
            import night_fill as _NF
            if _NF.last_problem():
                st.sidebar.caption(f"Night fill not used — {_NF.last_problem()}.")
        except Exception:
            pass

    min_d, max_d = pf_all["date"].min().date(), pf_all["date"].max().date()
    st.sidebar.markdown("#### 📅 Date")
    start_d = st.sidebar.date_input("From", value=min_d, min_value=min_d,
                                    max_value=max_d, key="pf_from")
    end_d = st.sidebar.date_input("To", value=max_d, min_value=min_d,
                                  max_value=max_d, key="pf_to")
    if start_d > end_d:                 # tolerate an inverted pick, don't blank out
        st.sidebar.warning("From is after To — showing the range flipped.")
        start_d, end_d = end_d, start_d

    # Scope: quickly focus on VFL vs the rest (the user's core ask).
    scope = st.sidebar.radio("Scope", ["All brands", "VFL only", "Non-VFL only"],
                             key="pf_scope", horizontal=False)
    _pool = pf_all
    if scope == "VFL only":
        _pool = _pool[_pool["is_vfl"]]
    elif scope == "Non-VFL only":
        _pool = _pool[~_pool["is_vfl"]]

    with st.sidebar.expander("🧭 Region", expanded=False):
        sel_region = st.multiselect(
            "Region", sorted(_pool["region"].dropna().unique()), default=[],
            key="pf_f_region")
    if sel_region:
        _pool = _pool[_pool["region"].isin(sel_region)]

    with st.sidebar.expander("🏬 Store", expanded=False):
        sel_city = st.multiselect(
            "City", sorted(_pool["city"].dropna().unique()), default=[],
            key="pf_f_city")
        _cpool = _pool[_pool["city"].isin(sel_city)] if sel_city else _pool
        sel_store = st.multiselect(
            "Store (location)", sorted(_cpool["location"].dropna().unique()),
            default=[], key="pf_f_store")

    with st.sidebar.expander("🏷️ Brand", expanded=False):
        sel_brand = st.multiselect(
            "Brand", sorted(_pool["brand"].dropna().unique()), default=[],
            key="pf_f_brand")

    with st.sidebar.expander("🌱 Growth / Degrowth", expanded=False):
        sel_gd = st.multiselect("Growth / Degrowth", ["Growing", "De-Growing"],
                                 default=[], key="pf_f_gd")
        st.caption("Stores whose YTD sales are up / down vs last year "
                   "(takeover-anchored, as of the date picker end).")

    if st.sidebar.button("↺ Reset portfolio filters"):
        for _k in ["pf_scope", "pf_f_region", "pf_f_city", "pf_f_store",
                   "pf_f_brand", "pf_f_gd"]:
            st.session_state.pop(_k, None)
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Portfolio data loaded {pf_at:%d %b %Y, %I:%M %p} IST")
    if st.sidebar.button("🔄 Refresh portfolio data"):
        _load_portfolio_cached.clear()
        # Report T.D. reads the VFL feed from this mode (South's last year lives
        # only there), so refreshing here has to clear that cache too — it is
        # the only refresh control this mode offers, and a button that silently
        # leaves half the data stale is worse than no button.
        _load_cached.clear()
        st.rerun()

    # ---- Apply category filters ----
    pf = _pool
    if sel_city:
        pf = pf[pf["city"].isin(sel_city)]
    if sel_store:
        pf = pf[pf["location"].isin(sel_store)]
    if sel_brand:
        pf = pf[pf["brand"].isin(sel_brand)]
    if sel_gd:
        _yoy = PL.store_yoy(pf, kind="YTD", asof=pd.Timestamp(end_d))
        keep = set()
        if "Growing" in sel_gd:
            keep |= set(_yoy.loc[_yoy["growth"] > 0, "code"])
        if "De-Growing" in sel_gd:
            keep |= set(_yoy.loc[_yoy["growth"] < 0, "code"])
        pf = pf[pf["code"].isin(keep)]

    asof = pd.Timestamp(end_d)

    # ---- Header + nav ----
    st.markdown(
        f"### 🌐 Whole-Portfolio View "
        f"<span style='font-size:.7em;color:#8a8a8a;'>· sales across all brands</span>",
        unsafe_allow_html=True)
    if "pf_active_nav" not in st.session_state:
        st.session_state["pf_active_nav"] = _PF_TABS[0]
    nav = st.segmented_control(
        "Section", _PF_TABS, key="pf_active_nav", label_visibility="collapsed")
    nav = nav or st.session_state["pf_active_nav"] or _PF_TABS[0]

    if pf.empty:
        st.info("No stores match the current filters.")
        return

    _money = ["Day Sales", "MTD LY", "MTD TY", "GD MTD Value",
              "YTD LY", "YTD TY", "GD YTD Value"]
    _pct = ["GD MTD %", "GD YTD %"]
    _sign = ["GD MTD Value", "GD MTD %", "GD YTD Value", "GD YTD %"]

    # ===================== Executive ===================== #
    if nav == "📊 Executive":
        st.caption(
            f"**As of {end_d:%d %b %Y}** · MTD / YTD (fiscal Apr–Mar) vs same "
            "period last year. Matches the Growth-Degrowth sheet: only stores "
            "active this year, closed stores' last year capped to their span, "
            "new stores (South) have no last-year compare.")
        ex = PL.exec_yoy(pf, asof=asof)
        cols = st.columns(2)
        for col, key in zip(cols, ["MTD", "YTD"]):
            v = ex[key]
            col.markdown(
                kpi_card(f"{key} Sales", _cr(v["ty"]), delta_pct=v["growth"]),
                unsafe_allow_html=True)
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # VFL vs non-VFL split (YTD)
        c1, c2 = st.columns(2)
        for col, (frame, title) in zip(
                (c1, c2), [(pf[pf["is_vfl"]], "VFL (Manyavar / Mohey)"),
                           (pf[~pf["is_vfl"]], "Non-VFL brands")]):
            if frame.empty:
                col.markdown(stat_card(title, [("YTD", "—", "#6b6b6b")]),
                             unsafe_allow_html=True)
                continue
            e = PL.exec_yoy(frame, asof=asof)["YTD"]
            g = e["growth"]
            gcol = GRN_TXT if (g is None or g >= 0) else RED_TXT
            gtxt = "new" if g is None else f"{g:+.1f}%"
            col.markdown(stat_card(title, [
                ("YTD This Year", _cr(e["ty"]), MAROON),
                ("YTD Last Year", _cr(e["ly"]), "#6b6b6b"),
                ("Growth YoY", gtxt, gcol),
            ]), unsafe_allow_html=True)

        st.markdown("#### Region YoY (YTD)")
        rg = PL.region_yoy(pf, "YTD", asof=asof)
        rg_disp = rg.rename(columns={"region": "Region", "ty": "This Year",
                                     "ly": "Last Year"})
        rg_disp["GD Value"] = rg_disp["This Year"] - rg_disp["Last Year"]
        rg_disp["GD %"] = rg["growth"]
        html = styled_report_html(
            rg_disp[["Region", "Last Year", "This Year", "GD Value", "GD %"]],
            money_cols=["Last Year", "This Year", "GD Value"], pct_cols=["GD %"],
            sign_cols=["GD Value", "GD %"])
        st.markdown(html, unsafe_allow_html=True)

    # ===================== MTD / YTD Report ===================== #
    elif nav == "📋 MTD / YTD Report":
        st.caption(
            f"**As of {end_d:%d %b %Y}** · region × store, year-on-year. "
            "MTD = month to date · YTD = fiscal (Apr–Mar) to date · "
            "TY/LY = this/last year · Red = degrowth.")
        rep, rtypes = PL.region_store_report(pf, asof=asof)
        if rep.empty:
            st.info("No stores match the current filters.")
            return
        st.markdown(
            styled_report_html(rep, money_cols=_money, pct_cols=_pct,
                               sign_cols=_sign, row_types=rtypes),
            unsafe_allow_html=True)

    # ===================== Degrowth ===================== #
    elif nav == "📉 Degrowth":
        kind = st.radio("Period", ["YTD", "MTD"], horizontal=True, key="pf_dg_kind")
        st.caption(f"Stores in {kind} degrowth (this year < last year), "
                   f"biggest ₹ shortfall first. As of {end_d:%d %b %Y}.")
        dg = PL.degrowth_report(pf, asof=asof, kind=kind)
        if dg.empty:
            st.success("No stores in degrowth for the current scope. 🎉")
            return
        disp = dg.rename(columns={
            "region": "Region", "code": "Code", "city": "City",
            "location": "Location", "brand": "Brand", "prior": "LY",
            "cur": "TY", "shortfall": "Shortfall", "growth": "Degrowth %"})
        disp["Code"] = disp["Code"].astype(int)
        html = styled_report_html(
            disp, money_cols=["LY", "TY", "Shortfall"], pct_cols=["Degrowth %"],
            sign_cols=["Shortfall", "Degrowth %"])
        _south = (dg["region"] == "South").sum()
        st.markdown(f"**{len(dg)} stores** in {kind} degrowth · total shortfall "
                    f"**{_cr(dg['shortfall'].sum())}**"
                    + (f" · incl. **{_south} South**" if _south else ""))
        st.markdown(html, unsafe_allow_html=True)

    # ===================== Contribution ===================== #
    elif nav == "🥧 Contribution":
        dim = st.radio("Break down by", ["Brand", "City", "Region", "Store"],
                       horizontal=True, key="pf_contrib_dim")
        st.caption(f"Sales contribution over **{start_d:%d %b %Y} – "
                   f"{end_d:%d %b %Y}**, largest first.")
        c = PL.contribution(pf, dim.lower(), window=(pd.Timestamp(start_d), asof))
        keycol = {"Brand": "brand", "City": "city", "Region": "region",
                  "Store": "location"}[dim]
        c = c.rename(columns={keycol: dim, "sales": "Sales", "share": "Share %"})
        fig = px.bar(c.head(20), x="Sales", y=dim, orientation="h",
                     text=c.head(20)["Share %"].map(lambda v: f"{v:.1f}%"))
        fig.update_layout(yaxis=dict(autorange="reversed"), height=460,
                          margin=dict(l=8, r=8, t=8, b=8),
                          plot_bgcolor="#fff", paper_bgcolor="#fff")
        fig.update_traces(marker_color=MAROON, textposition="outside")
        st.plotly_chart(fig, use_container_width=True)
        disp = c.copy()
        html = styled_report_html(disp, money_cols=["Sales"], pct_cols=["Share %"])
        st.markdown(html, unsafe_allow_html=True)

    # ===================== City-wise G/D ===================== #
    elif nav == "🏙️ City-wise G/D":
        kind = st.radio("Period", ["YTD", "MTD"], horizontal=True, key="pf_city_kind")
        st.caption(f"City-wise growth/degrowth, {kind} year-on-year. "
                   f"As of {end_d:%d %b %Y}.")
        cg = PL.city_gd(pf, kind=kind, asof=asof)
        disp = cg.rename(columns={"region": "Region", "city": "City",
                                  "prior": "LY", "cur": "TY", "gd": "GD Value",
                                  "growth": "GD %"})[
            ["Region", "City", "LY", "TY", "GD Value", "GD %"]]
        html = styled_report_html(
            disp, money_cols=["LY", "TY", "GD Value"], pct_cols=["GD %"],
            sign_cols=["GD Value", "GD %"])
        st.markdown(html, unsafe_allow_html=True)

    # ===================== Stores ===================== #
    elif nav == "🏬 Stores":
        st.caption("Every store in scope with total sales and active span.")
        sl = PL.store_list(pf)
        disp = sl.rename(columns={
            "code": "Code", "region": "Region", "city": "City",
            "location": "Location", "brand": "Brand", "is_vfl": "VFL",
            "first_sale": "First sale", "last_sale": "Last sale",
            "sales": "Total sales"})
        disp["Code"] = disp["Code"].astype(int)
        disp["VFL"] = disp["VFL"].map({True: "✓", False: ""})
        disp["First sale"] = pd.to_datetime(disp["First sale"]).dt.strftime("%d %b %y")
        disp["Last sale"] = pd.to_datetime(disp["Last sale"]).dt.strftime("%d %b %y")
        html = styled_report_html(
            disp[["Region", "Code", "City", "Location", "Brand", "VFL",
                  "First sale", "Last sale", "Total sales"]],
            money_cols=["Total sales"])
        st.markdown(f"**{len(sl)} stores** · total **{_cr(sl['sales'].sum())}**")
        st.markdown(html, unsafe_allow_html=True)

    # ===================== Monthly ===================== #
    elif nav == "📅 Monthly":
        st.caption("Sales by fiscal month with same-month-last-year comparison "
                   "(reflects the current scope/filters).")
        mo = PL.monthly(pf)
        fig = go.Figure()
        fig.add_bar(x=mo["label"], y=mo["ly_sales"] / 1e7, name="Last Year",
                    marker_color="#D9C7A6")
        fig.add_bar(x=mo["label"], y=mo["sales"] / 1e7, name="This Year",
                    marker_color=MAROON)
        fig.update_layout(barmode="group", height=420, bargap=0.25,
                          margin=dict(l=8, r=8, t=8, b=8), plot_bgcolor="#fff",
                          paper_bgcolor="#fff", yaxis_title="₹ Cr",
                          legend=dict(orientation="h", y=1.08))
        st.plotly_chart(fig, use_container_width=True)
        disp = mo.rename(columns={"label": "Month", "sales": "This Year",
                                  "ly_sales": "Last Year", "growth": "Growth %"})
        html = styled_report_html(
            disp[["Month", "Last Year", "This Year", "Growth %"]],
            money_cols=["Last Year", "This Year"], pct_cols=["Growth %"],
            sign_cols=["Growth %"])
        st.markdown(html, unsafe_allow_html=True)

    # ===================== Day Targets (historical day sales) ===================== #
    elif nav == "🎯 Day Targets":
        _dmin, _dmax = pf["date"].min().date(), pf["date"].max().date()
        day = pd.Timestamp(st.date_input(
            "Day", value=_dmax, min_value=_dmin, max_value=_dmax, key="pf_dayt_day"))
        sd_d = day - pd.Timedelta(days=364)
        dt_d = day - pd.DateOffset(years=1)
        st.caption(
            f"**{day:%A %d %b %Y}** · **Same Day LY** = {sd_d:%A %d %b %Y} "
            f"(same weekday, −52 weeks) · **Same Date LY** = {dt_d:%A %d %b %Y} "
            "(same calendar date). Per-store last-year day sales, for setting day "
            "targets. New stores (e.g. South) have no last year in the portfolio "
            "sheet — use the VFL view for their history.")
        rep, rtypes = PL.day_sales_ly_report(pf, day)
        if rep.empty:
            st.info("No stores match the current filters.")
            return
        st.markdown(
            styled_report_html(rep, money_cols=["Same Day LY", "Same Date LY"],
                               row_types=rtypes),
            unsafe_allow_html=True)

    # ===================== GD Sheet (exact workbook layout) ===================== #
    elif nav == "🧾 GD Sheet":
        _dmin, _dmax = pf["date"].min().date(), pf["date"].max().date()
        asof_d = pd.Timestamp(st.date_input(
            "As of", value=_dmax, min_value=_dmin, max_value=_dmax, key="pf_gd_asof"))
        ly_d = asof_d - pd.DateOffset(years=1)
        st.markdown(
            f"**CURRENT YEAR DATE:** {asof_d:%d-%m-%Y} ({asof_d:%A})  ·  "
            f"**LAST YEAR DATE:** {ly_d:%d-%m-%Y} ({ly_d:%A})")
        rep, rtypes = PL.gd_sheet_report(pf, asof=asof_d)
        if rep.empty:
            st.info("No stores match the current filters.")
            return

        # Block 2 — region summary
        _tot = rep.loc[[t in ("block", "grand") for t in rtypes]].copy()
        _tot["Region"] = _tot["Region"].str.replace(" Total", "", regex=False)
        _sum_cols = ["Sum of MTD_TY", "Sum of PROJECTED MTD", "Sum of MONTH SALE LY",
                     "Sum of YTD_TY", "Sum of PROJECTED YTD", "Sum of LY FULL SALES"]
        st.markdown("##### Region summary")
        st.markdown(styled_report_html(_tot[["Region"] + _sum_cols],
                                       money_cols=_sum_cols), unsafe_allow_html=True)

        # Block 3 — GROWTH DEGROWTH SHEET (the full 18-column table)
        st.markdown("##### GROWTH DEGROWTH SHEET")
        disp = rep.copy()
        for c in ["Sum of GD_YTD_%", "Sum of GD_MTD_%"]:
            disp[c] = pd.to_numeric(disp[c], errors="coerce") * 100
        _money = ["Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY",
                  "Sum of DAY SALE FIGURE", "Sum of MONTH SALE LY",
                  "Sum of PROJECTED MTD", "Sum of LY FULL SALES", "Sum of PROJECTED YTD"]
        _pct = ["Sum of GD_YTD_%", "Sum of GD_MTD_%"]
        st.markdown(
            styled_report_html(disp, money_cols=_money, pct_cols=_pct,
                               sign_cols=_pct, row_types=rtypes, compact=True),
            unsafe_allow_html=True)

    # ===================== Brand-wise GD (grouped by parent company) ===================== #
    elif nav == "🏷️ Brand-wise GD":
        _dmin, _dmax = pf["date"].min().date(), pf["date"].max().date()
        asof_d = pd.Timestamp(st.date_input(
            "As of", value=_dmax, min_value=_dmin, max_value=_dmax, key="pf_brand_asof"))
        ly_d = asof_d - pd.DateOffset(years=1)
        st.markdown(
            f"**CURRENT YEAR DATE:** {asof_d:%d-%m-%Y} ({asof_d:%A})  ·  "
            f"**LAST YEAR DATE:** {ly_d:%d-%m-%Y} ({ly_d:%A})")

        # Region summary (same block as GD Sheet)
        _gdrep, _gdtypes = PL.gd_sheet_report(pf, asof=asof_d)
        _tot = _gdrep.loc[[t in ("block", "grand") for t in _gdtypes]].copy()
        _tot["Region"] = _tot["Region"].str.replace(" Total", "", regex=False)
        _sum_cols = ["Sum of MTD_TY", "Sum of PROJECTED MTD", "Sum of MONTH SALE LY",
                     "Sum of YTD_TY", "Sum of PROJECTED YTD", "Sum of LY FULL SALES"]
        st.markdown("##### Region summary")
        st.markdown(styled_report_html(_tot[["Region"] + _sum_cols],
                                       money_cols=_sum_cols), unsafe_allow_html=True)

        # Main table grouped by PARENT
        st.markdown("##### BRAND WISE GROWTH DEGROWTH")
        rep, rtypes = PL.brand_wise_gd_report(pf, asof=asof_d)
        disp = rep.copy()
        for c in ["Sum of GD_YTD_%", "Sum of GD_MTD_%"]:
            disp[c] = pd.to_numeric(disp[c], errors="coerce") * 100
        _money = ["Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY",
                  "Sum of DAY SALE FIGURE", "Sum of MONTH SALE LY",
                  "Sum of PROJECTED MTD", "Sum of LY FULL SALES", "Sum of PROJECTED YTD"]
        _pct = ["Sum of GD_YTD_%", "Sum of GD_MTD_%"]
        st.markdown(
            styled_report_html(disp, money_cols=_money, pct_cols=_pct,
                               sign_cols=_pct, row_types=rtypes, compact=True),
            unsafe_allow_html=True)

    # ===================== Loc-wise GD (grouped by Location TL) ===================== #
    elif nav == "🗺️ Loc-wise GD":
        _dmin, _dmax = pf["date"].min().date(), pf["date"].max().date()
        asof_d = pd.Timestamp(st.date_input(
            "As of", value=_dmax, min_value=_dmin, max_value=_dmax, key="pf_loc_asof"))
        ly_d = asof_d - pd.DateOffset(years=1)
        st.markdown(
            f"**CURRENT YEAR DATE:** {asof_d:%d-%m-%Y} ({asof_d:%A})  ·  "
            f"**LAST YEAR DATE:** {ly_d:%d-%m-%Y} ({ly_d:%A})")

        _gdrep, _gdtypes = PL.gd_sheet_report(pf, asof=asof_d)
        _tot = _gdrep.loc[[t in ("block", "grand") for t in _gdtypes]].copy()
        _tot["Region"] = _tot["Region"].str.replace(" Total", "", regex=False)
        _sum_cols = ["Sum of MTD_TY", "Sum of PROJECTED MTD", "Sum of MONTH SALE LY",
                     "Sum of YTD_TY", "Sum of PROJECTED YTD", "Sum of LY FULL SALES"]
        st.markdown("##### Region summary")
        st.markdown(styled_report_html(_tot[["Region"] + _sum_cols],
                                       money_cols=_sum_cols), unsafe_allow_html=True)

        st.markdown("##### LOCATION WISE GROWTH DEGROWTH")
        rep, rtypes = PL.loc_wise_gd_report(pf, asof=asof_d)
        disp = rep.copy()
        for c in ["Sum of GD_YTD_%", "Sum of GD_MTD_%"]:
            disp[c] = pd.to_numeric(disp[c], errors="coerce") * 100
        _money = ["Sum of YTD_LY", "Sum of YTD_TY", "Sum of MTD_LY", "Sum of MTD_TY",
                  "Sum of MONTH SALE LY", "Sum of PROJECTED MTD", "Sum of LY FULL SALES",
                  "Sum of PROJECTED YTD", "Sum of DAY SALE FIGURE"]
        _pct = ["Sum of GD_YTD_%", "Sum of GD_MTD_%"]
        st.markdown(
            styled_report_html(disp, money_cols=_money, pct_cols=_pct,
                               sign_cols=_pct, row_types=rtypes, compact=True),
            unsafe_allow_html=True)

    # ===================== Average (store productivity) ===================== #
    elif nav == "📐 Average":
        _dmin, _dmax = pf["date"].min().date(), pf["date"].max().date()
        asof_d = pd.Timestamp(st.date_input(
            "As of", value=_dmax, min_value=_dmin, max_value=_dmax, key="pf_avg_asof"))
        ly_d = asof_d - pd.DateOffset(years=1)
        st.markdown(
            f"**CURRENT YEAR DATE:** {asof_d:%d-%m-%Y} ({asof_d:%A})  ·  "
            f"**LAST YEAR DATE:** {ly_d:%d-%m-%Y} ({ly_d:%A})")
        st.caption(
            "Store productivity by parent company, one row per store. Operation "
            "days = days traded this FY; **AVG DAY SALE = YTD_TY ÷ operation days** "
            "(a clean run-rate — the workbook's own formula is unreliable); AVG "
            "MONTH = ×30; PSFPD = AVG DAY SALE ÷ CA.")

        _gdrep, _gdtypes = PL.gd_sheet_report(pf, asof=asof_d)
        _tot = _gdrep.loc[[t in ("block", "grand") for t in _gdtypes]].copy()
        _tot["Region"] = _tot["Region"].str.replace(" Total", "", regex=False)
        _sum_cols = ["Sum of MTD_TY", "Sum of PROJECTED MTD", "Sum of MONTH SALE LY",
                     "Sum of YTD_TY", "Sum of PROJECTED YTD", "Sum of LY FULL SALES"]
        st.markdown("##### Region summary")
        st.markdown(styled_report_html(_tot[["Region"] + _sum_cols],
                                       money_cols=_sum_cols), unsafe_allow_html=True)

        st.markdown("##### AVG BRAND WISE SHEET")
        rep, rtypes = PL.average_report(pf, asof=asof_d)
        disp = rep.copy()
        disp["Sum of GD_YTD_%"] = pd.to_numeric(disp["Sum of GD_YTD_%"], errors="coerce") * 100
        _money = ["SBA", "CA", "Sum of YTD_LY", "Sum of YTD_TY", "Average of OPERATION",
                  "Sum of AVG DAY SALE", "Sum of AVG MONTH SALE", "Sum of PSFPD"]
        _pct = ["Sum of GD_YTD_%"]
        for _c in _money:  # blanks in total rows -> NaN so money formatting shows "—"
            disp[_c] = pd.to_numeric(disp[_c], errors="coerce")
        st.markdown(
            styled_report_html(disp, money_cols=_money, pct_cols=_pct,
                               sign_cols=_pct, row_types=rtypes),
            unsafe_allow_html=True)

    # ===================== MW Data (monthly contribution grid) ===================== #
    elif nav == "📈 MW Data":
        st.caption(
            "Monthly contribution by fiscal year (whole portfolio, all brands — "
            "ignores the sidebar filters). **FY25-26 & FY26-27 live** from the "
            "sales data (current FY updates daily); **FY24-25 and earlier** from "
            "the workbook. The current FY shows the East & NE / South split.")
        st.markdown(PL.mw_data_html(PL.mw_data(pf_all)), unsafe_allow_html=True)

    # ===================== Report PDF (the five sheets, one shareable file) ==== #
    elif nav == "📄 Report PDF":
        import portfolio_pdf as PPDF
        st.subheader("📄 Portfolio report (PDF)")
        st.caption(
            "Compiles the five workbook sheets — **MW Data, GD Sheet, Brand-wise, "
            "Loc-wise, Average** — into one shareable, print-clean PDF. The four "
            "G/D sheets honour the current sidebar filters and the date below; "
            "MW Data always covers the whole portfolio (like its tab).")
        _dmin, _dmax = pf["date"].min().date(), pf["date"].max().date()
        pdf_asof = pd.Timestamp(st.date_input(
            "As of", value=_dmax, min_value=_dmin, max_value=_dmax, key="pf_pdf_asof"))
        basis = f"Live to {pdf_asof:%d %b %Y}"
        if pf_provisional is not None and pd.Timestamp(pdf_asof) >= pf_provisional:
            basis += f" · {pf_provisional:%d %b} provisional (night fill)"
        if st.button("🧾 Generate PDF", key="pf_pdf_gen", type="primary",
                     use_container_width=True):
            with st.spinner("Building the report pack…"):
                try:
                    # The VFL frame supplies last year for South, whose history
                    # predates the takeover and is absent from the portfolio
                    # feed. Same cache the VFL side uses.
                    st.session_state["pf_pdf"] = PPDF.build(
                        pf, pf_all, pdf_asof, basis, vfl_df=get_data())
                    st.session_state["pf_pdf_name"] = (
                        f"peanuts_portfolio_{pdf_asof:%Y%m%d}.pdf")
                except Exception as e:                    # surface, don't crash tab
                    st.session_state["pf_pdf"] = None
                    st.error(f"Could not build the PDF: {e}")
        if st.session_state.get("pf_pdf"):
            st.success("PDF ready.")
            st.download_button(
                "⬇ Download PDF", st.session_state["pf_pdf"],
                file_name=st.session_state.get("pf_pdf_name", "portfolio.pdf"),
                mime="application/pdf", use_container_width=True)

    elif nav == "📑 REPORT T.D.":
        # A SEPARATE REPORTING VERTICAL. These reproduce the operational
        # workbooks (L-to-L, month-wise totals, night SMS) and deliberately look
        # like those Excel files rather than like the report packs above, which
        # keep the growth-degrowth palette. Nothing here touches those.
        import report_td as RTD
        st.subheader("📑 Report T.D.")
        st.caption(
            "Reproductions of the operational workbooks, in their own format. "
            "Pick one to download it as a PDF, or several to get them as a ZIP. "
            "These are independent of the report packs on the other tabs.")

        # South's last year is the previous operator's history, which only the
        # VFL feed retains — the portfolio feed has no South last year at all.
        # Show what the report will be built from. Every page is stamped with
        # this date too, so a stale cache produces a report that says so rather
        # than one that looks current.
        try:
            _td_asof = L.as_of(get_data())
            st.caption(f"Sales data through **{_td_asof:%d %b %Y}**. "
                       "Use *Refresh portfolio data* in the sidebar if the sheet "
                       "has been updated since.")
        except Exception:
            pass

        available = {
            "south_ltol": "South L-to-L sheet  ·  current month first, then each "
                          "earlier month of the year",
            "east_ltol": "East & NE L-to-L sheet  ·  current month first, then "
                         "each earlier month of the year",
            "mw_south": "South month-wise total sale  ·  25-26 vs 26-27",
            "mw_east": "East & NE month-wise total sale  ·  overall, then the "
                       "Mohey Manyavar stores",
            "night_sms": "Night sale SMS  ·  every store, city by city, with "
                         "city subtotals + the daily KPI table",
        }
        chosen = [k for k, label in available.items()
                  if st.checkbox(label, value=True, key=f"td_{k}")]
        if "night_sms" in chosen:
            st.caption("ℹ️ Night SMS: target columns are **blank until targets "
                       "exist**, and manual sale is blank until the night fill "
                       "has that column. Everything else is live.")
            st.caption("ℹ️ One file for the whole estate: **city and location "
                       "subtotals** in both tables, cities from the night "
                       "fill's own CITY column, and the brand-line split kept "
                       "for the VFL stores that fill it. Each store's year runs "
                       "from its own takeover date. A store that made its day "
                       "target prints **green**, one under its region's floor "
                       "(Rs 10,000 East & NE, Rs 50,000 South) prints **red**.")
        if "east_ltol" in chosen:
            # Its like-to-like and new-store columns follow Manav's stated rules
            # (11-12 Aug), which the older workbook does not: it re-decides
            # new/old every month, so a store can switch sides mid-year.
            st.caption("ℹ️ East L-to-L: new/old is fixed for the year against "
                       "1 April of the previous year, so **June and July read a "
                       "few points higher** than the old workbook, which decided "
                       "it month by month.")
        if "mw_east" in chosen:
            # Its last-year store COUNT (and so the last-year store average and
            # carpet area) comes from a comparable-store list kept by hand, which
            # no data we hold reproduces. The sales columns are exact both years.
            st.caption("⚠️ East month-wise: last-year **store counts, store "
                       "averages and carpet area** are computed from the data and "
                       "will differ from the workbook, which uses a hand-kept "
                       "comparable-store list. All sales figures match.")

        if st.button("🧾 Generate", key="td_gen", type="primary",
                     use_container_width=True, disabled=not chosen):
            with st.spinner("Building…"):
                try:
                    # Portfolio mode never loads the VFL frame, so pull it here
                    # through the same cache the VFL side uses — South's last
                    # year exists only in that feed.
                    vdf = get_data()
                    v_asof = L.as_of(vdf)
                    basis = f"Live to {v_asof:%d %b %Y}"
                    built = []
                    if "south_ltol" in chosen:
                        built.append(RTD.build_south_ltol(vdf, v_asof, basis))
                    if "east_ltol" in chosen:
                        built.append(RTD.build_east_ltol(pf_all, v_asof, basis))
                    if "mw_south" in chosen:
                        built.append(RTD.build_month_wise_south(vdf, v_asof, basis))
                    if "mw_east" in chosen:
                        built.append(
                            RTD.build_month_wise_east(pf_all, vdf, v_asof, basis))
                    if "night_sms" in chosen:
                        # Reads the night fill directly — it is the only source
                        # for the day's figures at the hour this goes out.
                        built.append(RTD.build_night_sms(pf_all, basis_label=basis))
                    name, payload, mime = RTD.bundle(built)
                    st.session_state["td_out"] = (name, payload, mime)
                except Exception as e:                    # surface, don't crash tab
                    st.session_state["td_out"] = None
                    st.error(f"Could not build: {e}")

        if st.session_state.get("td_out"):
            name, payload, mime = st.session_state["td_out"]
            st.success(f"Ready — {name}")
            st.download_button(f"⬇ Download {name}", payload, file_name=name,
                               mime=mime, use_container_width=True)


# ---- Top-level data mode: whole-Portfolio breadth vs VFL depth ----
_MODE_VFL, _MODE_PORTFOLIO = "🔷 VFL", "🌐 Portfolio"
_mode = st.sidebar.radio(
    "Data view", [_MODE_VFL, _MODE_PORTFOLIO], key="data_mode", horizontal=True,
    label_visibility="collapsed",
    help="VFL = deep Manyavar/Mohey analytics. Portfolio = all stores, sales-only.")
if _mode == _MODE_PORTFOLIO:
    render_portfolio()
    st.stop()

try:
    df_all = get_data()
except FileNotFoundError as e:
    st.error(str(e))
    st.info(
        "**To get started:** drop the sales export at `data/sales.xlsx`, or set "
        "`SHEET_CSV_URL` in Streamlit secrets to a published Google Sheet."
    )
    st.stop()
except Exception as e:
    # Everything else that can go wrong with a sheet — revoked link, sharing
    # changed, a sign-in page served instead of CSV. `feed.py` names the cause;
    # this used to escape as a red traceback with a message about a connection
    # reset, whatever had actually happened.
    st.error(f"**The sales data could not be loaded.** {e}")
    st.info("Every figure on this page comes from that sheet, so the page "
            "stops here rather than showing part of one. Fix the source and "
            "press R to reload.")
    st.stop()

_gate(df_all, "vfl", date_col="date", store_col=L.COL_STORE_LABEL,
      value_col=L.COL_AMOUNT)

fresh = L.data_freshness(df_all)

# --------------------------------------------------------------------------- #
# Sidebar — exhaustive, cascading filters + view settings
# --------------------------------------------------------------------------- #
n_stores_all = df_all[L.COL_STORE_LABEL].nunique()
_regions_txt = ", ".join(
    r for r in ["East & NE", "South"]
    if r in set(df_all[L.COL_REGION].dropna().unique())) or "—"
st.sidebar.markdown(
    f'<div style="display:flex;align-items:center;gap:10px;margin:0 0 2px;">'
    f'<div style="width:38px;height:38px;border-radius:9px;background:{MAROON};'
    f'color:#fff;font-weight:800;font-size:23px;font-family:Georgia,serif;'
    f'display:flex;align-items:center;justify-content:center;flex:0 0 auto;">M</div>'
    f'<div style="font-size:19px;font-weight:800;color:{MAROON};line-height:1.12;">'
    f'VFL <span style="color:{GOLD};">×</span> Peanuts Retail</div></div>',
    unsafe_allow_html=True)
st.sidebar.caption(f"Store Count {n_stores_all} · {_regions_txt}")

min_d, max_d = fresh["min_date"].date(), fresh["max_date"].date()

# ---- Date: separate From / To pickers (one calendar each) ----
st.sidebar.markdown("#### 📅 Date")
start_d = st.sidebar.date_input("From", value=min_d, min_value=min_d,
                                max_value=max_d, key="f_from")
end_d = st.sidebar.date_input("To", value=max_d, min_value=min_d,
                              max_value=max_d, key="f_to")
if start_d > end_d:                     # tolerate an inverted pick, don't blank out
    st.sidebar.warning("From is after To — showing the range flipped.")
    start_d, end_d = end_d, start_d


def _msel(container, label, options, key):
    return container.multiselect(label, options, default=[], key=key)


# ---- Region (same dropdown format as the other filters) ----
with st.sidebar.expander("🧭 Region", expanded=False):
    sel_region = _msel(st, "Region",
                       sorted(df_all[L.COL_REGION].dropna().unique()), "f_region")
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

# ---- Growth / Degrowth (stores by YTD YoY — same dropdown format) ----
with st.sidebar.expander("🌱 Growth / Degrowth", expanded=False):
    sel_gd = _msel(st, "Growth / Degrowth", ["Growing", "De-Growing"], "f_gd")
    st.caption("Stores whose YTD sales are up / down vs last year "
               "(takeover-anchored, as of the date picker).")

gd_stores = None
if sel_gd:
    _yoy = L.store_yoy(df_all, kind="YTD", asof=pd.Timestamp(end_d))
    gd_stores = set()
    if "Growing" in sel_gd:
        gd_stores |= set(_yoy.loc[_yoy["growth"] > 0, L.COL_STORE_LABEL])
    if "De-Growing" in sel_gd:
        gd_stores |= set(_yoy.loc[_yoy["growth"] < 0, L.COL_STORE_LABEL])

_GRAN_OPTS = ["Day", "Week", "Month", "Quarter", "Year"]


def gran_control(key, label="Time granularity"):
    """Per-tab time-granularity picker (was a global sidebar setting).

    Lives with the charts it drives so the sidebar stays filters-only. Each
    caller keeps its own selection; Month is the default everywhere.
    """
    return st.radio(key=key, label=label, options=_GRAN_OPTS, index=2,
                    horizontal=True)


_FILTER_KEYS = ["f_region", "f_state", "f_city", "f_store", "f_brand",
                "f_div", "f_sec", "f_dep", "f_mwc", "f_size", "f_color", "f_style",
                "f_sp", "f_gd"]
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
    if gd_stores is not None:                       # growth/degrowth store filter
        m &= frame[L.COL_STORE_LABEL].isin(gd_stores)
    return m


cat_mask = _cat_mask(df_all)
date_mask = (df_all["date"].dt.date >= start_d) & (df_all["date"].dt.date <= end_d)
df = df_all[cat_mask & date_mask].copy()
# Executive / report YoY need full history — apply all filters EXCEPT date range.
df_exec = df_all[cat_mask].copy()

active_filters = [(lbl, sel) for lbl, _col, sel in _CAT_FILTERS if sel]
if sel_gd:
    active_filters.append(("Growth/Degrowth", sel_gd))

st.sidebar.markdown("---")
st.sidebar.caption(
    f"**Data through:** {fresh['max_date']:%d %b %Y}  \n**Rows:** {fresh['rows']:,}  \n"
    f"**Loaded:** {data_loaded_at():%d %b, %I:%M %p} IST")
_vfl_prov = vfl_provisional_date()
if _vfl_prov is not None:
    # The latest day came from the night fill, before it reached this sheet.
    # It carries sales, brand line, gender and units but no bill-level detail,
    # so say so rather than let a coarse day pass for a settled one.
    st.sidebar.warning(
        f"**{_vfl_prov:%d %b}** is provisional — from the night fill, so it has "
        f"no division, category or bill detail yet.")
if st.sidebar.button("🔄 Refresh data now"):
    _load_cached.clear()
    _load_portfolio_cached.clear()
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
st.caption(f"VFL × Peanuts Retail · {scope} · {_dlabel}")

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


def gd_asof_note(picker_date):
    """As-of date for the G/D tabs — always live to the date picker.

    These used to carry a Live/Month-end toggle, with the VFL tabs defaulting to
    month-end so they reproduced the monthly review sheet. Live-to-date is now
    the only basis: the reports are read as a current view of trading, not as a
    reconstruction of a past review, and two bases meant two sets of numbers to
    explain. A month-end view is still reachable by setting the sidebar To date
    to a month end.
    """
    asof = pd.Timestamp(picker_date)
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


def render_loc_gd(detail, key):
    """City / location-wise G/D: stores grouped by city with per-city subtotals
    and a grand total (mirrors the source LOC_WISE_GD sheet)."""
    label_cols = ["City", "Region", "Store Code", "Location"]
    cols = label_cols + [c for c in GD_ORDER if c in detail.columns]
    disp = detail[cols].copy()
    rows, rtypes = [], []
    for city in [c for c in pd.unique(disp["City"]) if pd.notna(c)]:
        sub = disp[disp["City"] == city]
        for _, rr in sub.iterrows():
            rows.append(rr.to_dict())
            rtypes.append("store")
        rows.append(_gd_total(sub, label_cols, f"{city} Total"))
        rtypes.append("subtotal")
    rows.append(_gd_total(disp, label_cols, "Grand Total"))
    rtypes.append("grand")
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


def render_monthly_contrib(mc, key):
    """Monthly-contribution table + a grand-total row."""
    grand = mc["Total Sale"].sum()
    tot = {"Month": "Grand Total", "East & NE": mc["East & NE"].sum(),
           "South": mc["South"].sum(), "Total Sale": grand,
           "Month Contrib %": 100.0,
           "East & NE %": (mc["East & NE"].sum() / grand * 100) if grand else None,
           "South %": (mc["South"].sum() / grand * 100) if grand else None}
    disp = pd.concat([mc, pd.DataFrame([tot])], ignore_index=True)
    rtypes = ["store"] * len(mc) + ["grand"]
    st.markdown(
        styled_report_html(disp, money_cols=["East & NE", "South", "Total Sale"],
                           pct_cols=["Month Contrib %", "East & NE %", "South %"],
                           row_types=rtypes),
        unsafe_allow_html=True)
    st.write("")
    st.download_button("⬇ Download (CSV)", disp.to_csv(index=False).encode(),
                       file_name=f"{key}.csv", mime="text/csv",
                       key=f"{key}_csv", use_container_width=True)
    return disp


def render_productivity(pr, key):
    """Store productivity table (SBA/CA area, YTD, GD%, op days, avg day/month
    sale, PSFPD), region-grouped with subtotals where ratios are recomputed."""
    cols = ["Region", "Store Code", "Location", "City", "SBA", "CA", "YTD LY",
            "YTD TY", "GD YTD %", "Op Days", "Avg Day Sale", "Avg Month Sale", "PSFPD"]
    money = ["YTD LY", "YTD TY", "Avg Day Sale", "Avg Month Sale", "PSFPD"]
    intcols = ["SBA", "CA", "Op Days"]

    def total(sub, label):
        ca = pd.to_numeric(sub["CA"], errors="coerce").sum()
        ly = pd.to_numeric(sub["YTD LY"], errors="coerce").sum()
        ty = pd.to_numeric(sub["YTD TY"], errors="coerce").sum()
        opd = pd.to_numeric(sub["Op Days"], errors="coerce").mean()
        return {"Region": label, "Store Code": "", "Location": "", "City": "",
                "SBA": pd.to_numeric(sub["SBA"], errors="coerce").sum(), "CA": ca,
                "YTD LY": ly, "YTD TY": ty,
                "GD YTD %": ((ty - ly) / ly * 100) if ly else None,
                "Op Days": opd,
                "Avg Day Sale": ty / opd if opd else None,
                "Avg Month Sale": (ty / opd * 30) if opd else None,
                "PSFPD": (ty / opd / ca) if ca and opd else None}

    rows, rtypes = [], []
    for reg in [r for r in ["East & NE", "South"] if r in pr["Region"].unique()]:
        sub = pr[pr["Region"] == reg]
        for _, r in sub.iterrows():
            rows.append(r.to_dict())
            rtypes.append("store")
        rows.append(total(sub, f"{reg} Total"))
        rtypes.append("subtotal")
    rows.append(total(pr, "Grand Total"))
    rtypes.append("grand")
    table = pd.DataFrame(rows)[cols]

    def _intfmt(v):
        try:
            return f"{float(v):,.0f}" if pd.notna(v) and str(v) != "" else ""
        except (TypeError, ValueError):
            return str(v)
    for c in intcols:
        table[c] = table[c].map(_intfmt)

    st.markdown(
        styled_report_html(table, money_cols=money, pct_cols=["GD YTD %"],
                           sign_cols=["GD YTD %"], row_types=rtypes),
        unsafe_allow_html=True)
    st.write("")
    st.download_button("⬇ Download (CSV)", table.to_csv(index=False).encode(),
                       file_name=f"{key}.csv", mime="text/csv",
                       key=f"{key}_csv", use_container_width=True)
    return table


# Top-level navigation (NOT st.tabs, which snaps back to the first tab on every
# rerun). The 7 main reports show as pills; the rest live in a "More" overflow
# menu. Selection lives in session_state (active_nav), so it PERSISTS on rerun.
_TAB_LABELS = [
    "🧾 VFL G/D", "🧾 VFL Gender", "📄 Report PDF",
    "📋 MTD / YTD Report", "📉 Degrowth", "🔎 Degrowth Drivers",
    "📸 Morning snapshots",
    "🧑‍🤝‍🧑 Gender G/D", "🏷️ Brand G/D", "🏬 Store × Brand G/D", "⚖️ Gender Mix",
    "📊 Executive", "🎯 Day Targets", "🏙️ City-wise G/D", "📅 Monthly Contribution",
    "📐 Store Productivity", "Overview", "🏬 Stores",
    "🔧 Build your view", "Trends", "Category mix", "Salespeople",
    "Customers", "Colors & sizes",
]
_PILL_TABS = _TAB_LABELS[:7]          # main reports shown as pills
_MORE_TABS = _TAB_LABELS[7:]          # the rest, in a "More" overflow menu

if "active_nav" not in st.session_state:
    st.session_state["active_nav"] = _PILL_TABS[0]
    st.session_state["nav_pills"] = _PILL_TABS[0]


def _on_pills():                      # a pill was clicked → it becomes the section
    v = st.session_state.get("nav_pills")
    if v:
        st.session_state["active_nav"] = v


def _pick_more(lbl):                  # a "More" item was picked → clear the pills
    st.session_state["active_nav"] = lbl
    st.session_state["nav_pills"] = None


nav = st.session_state["active_nav"]
_more_active = nav in _MORE_TABS
if _more_active:                      # tint the "More" button when its section is open
    st.markdown(
        f"<style>[data-testid='stPopoverButton']{{background:{MAROON}!important;"
        f"border-color:{MAROON}!important;}}"
        f"[data-testid='stPopoverButton'] p{{color:#fff!important;}}</style>",
        unsafe_allow_html=True)

_nav_l, _nav_r = st.columns([5, 1], vertical_alignment="center", gap="small")
with _nav_l:
    st.segmented_control("Section", _PILL_TABS, key="nav_pills",
                         on_change=_on_pills, label_visibility="collapsed")
with _nav_r:
    with st.popover("More  ▾", use_container_width=True):
        st.caption("Jump to a section")
        for _lbl in _MORE_TABS:
            st.button(_lbl, key=f"more_{_lbl}", use_container_width=True,
                      on_click=_pick_more, args=(_lbl,))

# =========================================================================== #
# MTD / YTD REPORT — region × store, year-on-year (the executive table)
# =========================================================================== #
if nav == "📋 MTD / YTD Report":
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
if nav == "📸 Morning snapshots":
    import io as _io
    import zipfile
    import snapshots as SN

    st.subheader("Morning snapshots")
    st.caption(
        "The set that goes into the WhatsApp group each morning, as one ZIP of "
        "PNGs. **Sidebar filters are ignored** — these are always the full "
        f"estate, as of **{end_d:%d %b %Y}**. Per-store files are for sending "
        "to that store's manager, so each shows only their own store.")

    _asof = pd.Timestamp(end_d)
    _master = L.load_store_master().set_index("tableau_name")
    _closed = L.closed_map()
    # Unfiltered on purpose: a morning broadcast filtered by whatever was left
    # in the sidebar would be quietly wrong, and nobody receiving it could tell.
    _src = df_all

    _stores = [st_ for st_ in sorted(_src[L.COL_STORE_LABEL].dropna().unique())
               if not (st_ in _master.index
                       and int(_master.loc[st_, "code"]) in _closed)]

    c1, c2, c3 = st.columns(3)
    want_store_wise = c1.checkbox("Store-wise MTD / YTD", value=True,
                                  help="One image, both periods, year on year.")
    want_degrowth = c2.checkbox("Degrowth by region", value=True,
                                help="MTD and YTD × South and East & NE = 4.")
    want_drivers = c3.checkbox("Per-store drivers", value=True,
                               help=f"{len(_stores)} stores × MTD and YTD.")

    _n = (1 if want_store_wise else 0) + (4 if want_degrowth else 0) \
        + (len(_stores) * 2 if want_drivers else 0)
    st.caption(f"**{_n} image(s)** — `shared/` for the group, `by-store/` for "
               "individual managers.")

    if st.button("📦 Build the ZIP", type="primary", disabled=_n == 0,
                 use_container_width=True):
        bar = st.progress(0.0, text="Starting…")
        buf, failed = _io.BytesIO(), []
        # A list rather than an int: this block runs at module scope, where a
        # closure cannot rebind a plain counter.
        done = [0]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            def _add(folder, made):
                if made:
                    z.writestr(f"{folder}/{made[0]}", made[1])
                done[0] += 1
                bar.progress(min(done[0] / max(_n, 1), 1.0),
                             text=f"{done[0]} of {_n} — "
                                  f"{made[0] if made else 'skipped'}")

            try:
                if want_store_wise:
                    _add("shared", SN.store_wise(L, _src, _asof))
                if want_degrowth:
                    for _k in ("MTD", "YTD"):
                        for _r in ("South", "East & NE"):
                            _add("shared",
                                 SN.degrowth_region(L, _src, _asof, _k, _r))
                if want_drivers:
                    for _st in _stores:
                        _code = (int(_master.loc[_st, "code"])
                                 if _st in _master.index else None)
                        for _k in ("MTD", "YTD"):
                            try:
                                _add("by-store",
                                     SN.drivers_store(L, _src, _asof, _k, _st,
                                                      _code))
                            except Exception as e:      # one store must not
                                failed.append(f"{_st} {_k}: {e}")  # sink the run
                                done[0] += 1
            except Exception as e:
                st.error(f"Could not finish the ZIP: {e}")
                bar.empty()
                st.stop()
        bar.empty()
        st.session_state["snap_zip"] = buf.getvalue()
        st.session_state["snap_name"] = f"snapshots_{_asof:%Y-%m-%d}.zip"
        if failed:
            st.warning(f"{len(failed)} snapshot(s) failed: " + "; ".join(failed[:5]))
        st.success(f"{done[0]} image(s) · "
                   f"{len(st.session_state['snap_zip']) / 1e6:.1f} MB")

    if st.session_state.get("snap_zip"):
        st.download_button("⬇ Download the ZIP", st.session_state["snap_zip"],
                           file_name=st.session_state.get("snap_name",
                                                          "snapshots.zip"),
                           mime="application/zip", use_container_width=True)
        st.caption("Send these as **documents** in WhatsApp, not photos — "
                   "photos get recompressed and the detail is lost.")

if nav == "🔎 Degrowth Drivers":
    st.subheader("Degrowth drivers")
    dd_kind = st.radio("Period", list(L.DRIVERS_PERIODS), horizontal=True,
                       key="dd_kind",
                       help="YTD is the year's story; MTD says whether the "
                            "decline is still happening this month.")
    st.caption(
        f"Why each declining store is down on **{dd_kind}**, not just that it "
        "is. Every store's shortfall is decomposed into **rupees** by brand, "
        "then into the worst products beneath the brand doing most of the "
        "damage. The brand rows sum to the store's shortfall, so the "
        f"attribution is complete. As of **{end_d:%d %b %Y}** — respects all "
        "filters.")
    dd_depth = st.radio(
        "Product detail", ["Every brand", "Every declining brand",
                           "Worst brand only"],
        horizontal=True, key="dd_depth",
        help="How far to break brands down into products. 'Every brand' also "
             "breaks out brands that GREW, which is how you see what is "
             "offsetting a decline.")
    dd_n = st.slider("Products shown per brand", 1, 6, 3, key="dd_n")
    dd_level = st.radio(
        "Detail level", ["Division", "Section", "Department"],
        horizontal=True, key="dd_level",
        help="Division (31) is the readable level; Section (160) and "
             "Department (612) narrow it further. The level decides what the "
             "worst lines are ranked at, not how many rows are shown.")

    drv, drv_types = L.degrowth_drivers(
        df_exec, asof=pd.Timestamp(end_d), kind=dd_kind, top_products=dd_n,
        products_under={"Every brand": "every",
                        "Every declining brand": "all",
                        "Worst brand only": "worst"}[dd_depth],
        level=dd_level.lower())

    if drv.empty:
        st.success("🎉 No stores in degrowth for this selection.")
    else:
        _stores = drv_types.count("block")
        _short = float(drv.loc[[t == "block" for t in drv_types], "Shortfall"].sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Stores degrowing", f"{_stores}")
        c2.metric("Total shortfall", inr(_short))
        c3.metric("Rows", f"{len(drv)}")
        # A store can be masking a large decline with a large gain elsewhere;
        # that is the case worth pointing at, since a store total hides it.
        _off = [str(drv.iloc[i]["Brand"])
                for i, t in enumerate(drv_types)
                if t == "subtotal" and drv.iloc[i]["Shortfall"] > 0]
        if _off:
            st.info("Some declining stores have a **growing** brand offsetting "
                    "the fall — the store total hides it: "
                    + ", ".join(sorted(set(_off))))
        st.markdown(
            styled_report_html(drv, money_cols=L.drivers_money(dd_kind),
                               pct_cols=L.DRIVERS_PCT,
                               sign_cols=["Shortfall"] + L.DRIVERS_PCT,
                               row_types=drv_types),
            unsafe_allow_html=True)
        st.download_button("⬇ Download (CSV)", drv.to_csv(index=False).encode(),
                           file_name=f"degrowth_drivers_{dd_kind.lower()}_"
                                     f"{end_d:%Y%m%d}.csv",
                           mime="text/csv")

if nav == "📉 Degrowth":
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
if nav == "🧑‍🤝‍🧑 Gender G/D":
    st.subheader("Gender-wise Growth / Degrowth")
    st.caption("Store × gender, MTD & YTD this year vs last (fiscal Apr–Mar). "
               "Red = degrowth. Gender follows the brand line "
               "(Mohey / Twamev-Women / Mebaz = Women).")
    c1, c2 = st.columns(2)
    with c1:
        view = st.radio("View", ["Store detail", "Region summary"], horizontal=True,
                        key="gender_gd_view", label_visibility="collapsed")
    with c2:
        gd_asof = gd_asof_note(end_d)
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
if nav == "🏷️ Brand G/D":
    st.subheader("Brand-wise Growth / Degrowth")
    st.caption("MTD & YTD YoY by brand. Scope = the Manyavar-group brands in "
               "the sales feed.")
    gd_asof = gd_asof_note(end_d)
    b = L.brand_wise_gd(df_exec, asof=gd_asof)
    if b.empty:
        st.info("No data for the current filters.")
    else:
        render_gd_table(b, ["Brand"], f"brand_gd_{gd_asof:%Y%m%d}")

# =========================================================================== #
# STORE × BRAND G/D — brand-line detail within each store (deepest VFL level)
# =========================================================================== #
if nav == "🏬 Store × Brand G/D":
    st.subheader("Store × Brand-line Growth / Degrowth")
    st.caption("Each store broken down by brand-line (Manyavar / Twamev Men / "
               "Manthan / Mohey / Twamev-Women / Mebaz — any other division folds "
               "into Manyavar), grouped by gender: **MEN Total** and **WOMEN "
               "Total** (peach), a **Store Total** (blue), then region & grand "
               "totals. Takeover-anchored, red = degrowth.")
    sb_asof = gd_asof_note(end_d)
    sb = L.store_brand_gd(df_exec, asof=sb_asof)
    if sb.empty:
        st.info("No data for the current filters.")
    else:
        render_store_brand_gd(sb, f"store_brand_gd_{sb_asof:%Y%m%d}")

# =========================================================================== #
# VFL G/D — the workbook "VFL" sheet, 1:1.
# =========================================================================== #
if nav == "🧾 VFL G/D":
    st.subheader("VFL — Growth / Degrowth")
    st.caption("The workbook **VFL** sheet, 1:1. Region → Master Location → Store "
               "→ Gender (MEN/WOMEN) → brand-line — Manyavar (incl. Manthan) / "
               "Twamev Men / Mohey (incl. Mebaz) / Twamev-Women — with MEN/WOMEN, "
               "store, location, region and grand totals. Takeover-anchored; "
               "red = degrowth.")
    v_asof = gd_asof_note(end_d)
    disp, rtypes = L.vfl_gd_report(df_exec, asof=v_asof, gen_date=pd.Timestamp(end_d))
    if disp.empty:
        st.info("No data for the current filters.")
    else:
        st.markdown(
            styled_report_html(disp, money_cols=L.VFL_GD_MONEY, pct_cols=L.VFL_GD_PCT,
                               sign_cols=L.VFL_GD_PCT, row_types=rtypes, compact=True,
                               palette="vfl"),
            unsafe_allow_html=True)

# =========================================================================== #
# VFL GENDER — the workbook "VFL_GENDER" sheet, 1:1 (gender contribution %).
# =========================================================================== #
if nav == "🧾 VFL Gender":
    st.subheader("VFL — Gender Contribution %")
    st.caption("The workbook **VFL_GENDER** sheet, 1:1. Region → Master Location "
               "→ Location → Store → gender, each gender's share within its store; "
               "the store-total row = the store's share of its **location**; region "
               "totals = the region's share of the grand. Below: the Region × "
               "Gender summary.")
    vg_asof = gd_asof_note(end_d)
    main, mrt, summ, srt = L.vfl_gender_report(df_exec, asof=vg_asof)
    if main.empty:
        st.info("No data for the current filters.")
    else:
        st.markdown(
            styled_report_html(main, money_cols=L.VFL_GENDER_MONEY,
                               pct_cols=L.VFL_GENDER_PCT, row_types=mrt, compact=True,
                               palette="vfl"),
            unsafe_allow_html=True)
        st.markdown("##### Region × Gender summary")
        st.markdown(
            styled_report_html(summ, money_cols=L.VFL_GENDER_MONEY,
                               pct_cols=L.VFL_GENDER_PCT, row_types=srt,
                               palette="vfl"),
            unsafe_allow_html=True)

# =========================================================================== #
# REPORT PDF — the two VFL sheets compiled into one shareable file.
# =========================================================================== #
if nav == "📄 Report PDF":
    import vfl_pdf
    st.subheader("📄 VFL report (PDF)")
    st.caption("Compiles the **VFL G/D** and **VFL Gender** sheets into one "
               "shareable, print-clean PDF (honours the current sidebar filters).")
    p_asof = gd_asof_note(end_d)
    p_basis = f"Live to {p_asof:%d %b %Y}"
    if st.button("🧾 Generate PDF", key="vfl_pdf_gen", type="primary",
                 use_container_width=True):
        with st.spinner("Building the VFL report…"):
            try:
                st.session_state["vfl_pdf"] = vfl_pdf.build(
                    df_exec, asof=p_asof, gen_date=pd.Timestamp(end_d), basis_label=p_basis)
                st.session_state["vfl_pdf_name"] = f"peanuts_vfl_{p_asof:%Y%m%d}.pdf"
            except Exception as e:                        # surface, don't crash tab
                st.session_state["vfl_pdf"] = None
                st.error(f"Could not build the PDF: {e}")
    if st.session_state.get("vfl_pdf"):
        st.success("PDF ready.")
        st.download_button(
            "⬇ Download PDF", st.session_state["vfl_pdf"],
            file_name=st.session_state.get("vfl_pdf_name", "vfl_report.pdf"),
            mime="application/pdf", use_container_width=True)

# =========================================================================== #
# GENDER MIX — contribution %  (Region × Gender + store detail)
# =========================================================================== #
if nav == "⚖️ Gender Mix":
    st.subheader("Gender-wise Contribution %")
    st.caption("Each gender's share of sales, MTD & YTD.")
    c1, c2 = st.columns(2)
    with c1:
        view = st.radio("View", ["Store detail", "Region summary"], horizontal=True,
                        key="gender_mix_view", label_visibility="collapsed")
    with c2:
        gd_asof = gd_asof_note(end_d)
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
if nav == "📊 Executive":
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
# DAY TARGETS — per-store last-year day sales (same day / same date)
# =========================================================================== #
if nav == "🎯 Day Targets":
    st.subheader("Day Sales — Last Year reference (for day targets)")
    _day = pd.Timestamp(st.date_input(
        "Day", value=max_d, min_value=min_d, max_value=max_d, key="vfl_dayt_day"))
    _sd = _day - pd.Timedelta(days=364)
    _dt = _day - pd.DateOffset(years=1)
    st.caption(
        f"**{_day:%A %d %b %Y}** · **Same Day LY** = {_sd:%A %d %b %Y} "
        f"(same weekday, −52 weeks) · **Same Date LY** = {_dt:%A %d %b %Y} "
        "(same calendar date). Per-store last-year day sales, for setting day "
        "targets. South uses its retained pre-takeover history.")
    _rep, _rtypes = L.day_sales_ly_report(df_exec, _day)
    if _rep.empty:
        st.info("No stores match the current filters.")
        st.stop()
    st.markdown(
        styled_report_html(_rep, money_cols=["Same Day LY", "Same Date LY"],
                           row_types=_rtypes),
        unsafe_allow_html=True)

# =========================================================================== #
# CITY-WISE G/D — stores grouped by city (LOC_WISE_GD)
# =========================================================================== #
if nav == "🏙️ City-wise G/D":
    st.subheader("City / Location-wise Growth / Degrowth")
    st.caption("Stores grouped by **city**, with per-city subtotals and a grand "
               "total. Same G/D columns as the store report, takeover-anchored. "
               "**Manyavar & Mohey only** (the report's city totals also include "
               "other brands, which aren't in this data feed).")
    cg_asof = gd_asof_note(end_d)
    lg = L.loc_store_gd(df_exec, asof=cg_asof)
    if lg.empty:
        st.info("No data for the current filters.")
    else:
        render_loc_gd(lg, f"city_gd_{cg_asof:%Y%m%d}")

# =========================================================================== #
# MONTHLY CONTRIBUTION — month × sales, contribution %, region split (MW_DATA)
# =========================================================================== #
if nav == "📅 Monthly Contribution":
    st.subheader("Monthly Contribution")
    st.caption(f"Each month of the current fiscal year (as of {end_d:%d %b %Y}): "
               "sales, its **share of the year**, and the **East & NE / South "
               "split** with each region's share of the month. "
               "**Manyavar & Mohey only.**")
    mc = L.monthly_contribution(df_exec, asof=pd.Timestamp(end_d))
    if mc.empty:
        st.info("No data for the current filters.")
    else:
        render_monthly_contrib(mc, f"monthly_contrib_{end_d:%Y%m%d}")

# =========================================================================== #
# STORE PRODUCTIVITY — per sq ft / per day (AVG BRAND WISE / PSFPD)
# =========================================================================== #
if nav == "📐 Store Productivity":
    st.subheader("Store Productivity — SBA / CA, avg sale, PSFPD")
    st.caption("Per-store floor area (**SBA** super-built, **CA** carpet, sq ft), "
               "YTD sales & GD%, operational days, **avg day/month sale** and "
               "**PSFPD** (sales per sq ft per day). Region subtotals recompute "
               "the ratios. **Manyavar & Mohey only.**")
    pr = L.store_productivity(df_exec, asof=pd.Timestamp(end_d))
    if pr.empty or pr["SBA"].fillna(0).eq(0).all():
        st.info("No area data for the current filters.")
    else:
        render_productivity(pr, f"productivity_{end_d:%Y%m%d}")

# =========================================================================== #
# OVERVIEW — selectable KPI cards + trend at chosen granularity
# =========================================================================== #
if nav == "Overview":
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
    granularity = gran_control("ov_gran")
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
if nav == "🏬 Stores":
    st.subheader("Store comparison")
    rank_metric = st.selectbox(
        "Break stores down by", list(L.METRICS.keys()), index=0,
        key="store_rank_metric",
    )
    granularity = gran_control("st_gran")
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
if nav == "🔧 Build your view":
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
if nav == "Trends":
    granularity = gran_control("tr_gran")
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
if nav == "Category mix":
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
if nav == "Salespeople":
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
if nav == "Customers":
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
if nav == "Colors & sizes":
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Best-selling colors")
        draw_view({"metric": "Units", "group_dim": "Color",
                   "chart": "Horizontal bar", "top": 15, "_key": "mz_col"}, height=520)
    with c2:
        st.subheader("Units by size")
        draw_view({"metric": "Units", "group_dim": "Size",
                   "chart": "Horizontal bar", "top": 15, "_key": "mz_size"}, height=520)
