"""The 🧮 Excel Builder tab, rebuilt as a pivot table (13 Oct 2026; engine in `pivotx.py`).

The admin's ask: *"replicate a pivot table as in excel where data can be transformed into whatever format
we need to study in"*, with the sheet's own fields plus financial and regional ones. The screen follows
Excel's PivotTable Fields pane: FILTERS, COLUMNS, ROWS, VALUES; each value can be "shown as" a share or a
change; layout, subtotals, totals, sort and top N sit underneath. The address bar carries the layout, so a
table can be bookmarked or sent to someone and opens exactly as it was.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import pivotx as P

PRESETS = {
    "vfl": {
        "Store growth, FY to date": dict(rows=["Region", "Store"], cols=["Financial Year"],
                                         values=[("Sales (₹)", "Value"), ("Sales (₹)", "% change vs previous column"),
                                                 ("ATV / avg bill value (₹)", "Value")],
                                         period="FY to date · this year and last", grand_cols=False),
        "Month by month, year on year": dict(rows=["Fiscal Month"], cols=["Financial Year"],
                                             values=[("Sales (₹)", "Value"), ("Sales (₹)", "% change vs previous column")],
                                             period="All data", grand_cols=False),
        "Region → state → city, this FY": dict(rows=["Region", "State", "City"], cols=["FY Quarter"],
                                               values=[("Sales (₹)", "Value")], period="This FY"),
        "Brand and gender mix": dict(rows=["Brand", "Men/Women/Child"], cols=[],
                                     values=[("Sales (₹)", "Value"), ("Sales (₹)", "% of grand total"),
                                             ("Units", "Value"), ("ATV / avg bill value (₹)", "Value")], period="This FY"),
        "Price brackets, year on year": dict(rows=["Price bracket"], cols=["Financial Year"],
                                             values=[("Units", "Value"), ("Units", "% change vs previous column")],
                                             period="FY to date · this year and last", grand_cols=False),
        "Division share by region": dict(rows=["Division"], cols=["Region"],
                                         values=[("Sales (₹)", "% of column total")], period="This FY",
                                         sort_by="Sales (₹)"),
        "Top salespeople this month": dict(rows=["Store", "Salesperson"], cols=[],
                                           values=[("Sales (₹)", "Value"), ("Bills", "Value"), ("ATV / avg bill value (₹)", "Value")],
                                           period="This month", sort_by="Sales (₹)", top=5, layout="Compact"),
    },
    "portfolio": {
        "Store growth, FY to date": dict(rows=["Region", "City", "Store"], cols=["Financial Year"],
                                         values=[("Sales (₹)", "Value"), ("Sales (₹)", "% change vs previous column")],
                                         period="FY to date · this year and last", grand_cols=False),
        "Month by month, year on year": dict(rows=["Fiscal Month"], cols=["Financial Year"],
                                             values=[("Sales (₹)", "Value"), ("Sales (₹)", "% change vs previous column")],
                                             period="All data", grand_cols=False),
        "Brand by FY quarter": dict(rows=["Brand"], cols=["FY Quarter"], values=[("Sales (₹)", "Value")],
                                    period="This FY", sort_by="Sales (₹)"),
        "VFL vs other brands by region": dict(rows=["Region"], cols=["Brand group"],
                                              values=[("Sales (₹)", "% of row total")], period="This FY"),
        "City ranking this month": dict(rows=["City"], cols=[], values=[("Sales (₹)", "Value"), ("Active stores", "Value")],
                                        period="This month", sort_by="Sales (₹)"),
    },
}
DEFAULT = {"vfl": "Store growth, FY to date", "portfolio": "Store growth, FY to date"}
SORTS_LABEL = ["Label (A to Z)", "Label (Z to A)"]


def _k(key, name):
    return f"{key}__{name}"


def _apply(key, feed, spec: dict):
    """Put a layout into the widgets (preset, saved layout or the address bar)."""
    ss = st.session_state
    ss[_k(key, "rows")] = list(spec.get("rows", []))
    ss[_k(key, "cols")] = list(spec.get("cols", []))
    vals = [tuple(v) for v in spec.get("values", [])]
    ss[_k(key, "vals")] = list(dict.fromkeys(m for m, _h in vals))
    for m in dict.fromkeys(m for m, _h in vals):        # each value's "show as" list
        ss[_k(key, f"show_{m}_x")] = [h for mm, h in vals if mm == m]
    ss[_k(key, "slots")] = vals
    ss[_k(key, "filters")] = list((spec.get("filters") or {}).keys())
    for f, flt in (spec.get("filters") or {}).items():
        ss[_k(key, f"fi_{f}")] = list(flt.get("items", []))
        ss[_k(key, f"fm_{f}")] = "Exclude" if flt.get("mode") == "exclude" else "Include"
    ss[_k(key, "period")] = spec.get("period") or "FY to date · this year and last"
    ss.setdefault(_k(key, "top"), 0)
    ss[_k(key, "layout")] = spec.get("layout", "Tabular")
    ss[_k(key, "subtotals")] = spec.get("subtotals", True)
    ss[_k(key, "grand_rows")] = spec.get("grand_rows", True)
    ss[_k(key, "grand_cols")] = spec.get("grand_cols", True)
    sb = spec.get("sort_by", "Label")
    ss[_k(key, "sort")] = sb if sb in P.measures(feed) else ("Label (Z to A)" if sb == "Label (Z to A)" else "Label (A to Z)")
    ss[_k(key, "desc")] = spec.get("descending", True)
    ss[_k(key, "top")] = int(spec.get("top", 0) or 0)
    if spec.get("ranges") and spec.get("period") == "Custom":
        ss[_k(key, "from")] = pd.Timestamp(spec["ranges"][0][0]).date()
        ss[_k(key, "to")] = pd.Timestamp(spec["ranges"][0][1]).date()


@st.cache_data(show_spinner=False, max_entries=4)
def _prepared(_df, feed, token):
    return P.prepare(_df, feed)


@st.cache_data(show_spinner=False, max_entries=64)
def _field_items(_w, feed, field, token):
    lab, order = P.labels(_w, feed, field)
    vals = list(pd.unique(lab.dropna()))
    if order:
        pos = {x: i for i, x in enumerate(order)}
        return sorted(vals, key=lambda x: (pos.get(x, 10 ** 9), P._natural(x)))
    return sorted(vals, key=P._natural)


def render(df: pd.DataFrame, *, feed: str, key: str, asof):
    ss = st.session_state
    token = (feed, len(df), str(pd.to_datetime(df["date"]).max()))
    W = _prepared(df, feed, token)
    M = P.measures(feed)
    fields = P.field_names(feed)
    groups = P.field_group(feed)

    # ---- first visit: the address bar's layout, else the default preset
    if not ss.get(_k(key, "init")):
        qp = st.query_params.get(f"pv_{feed}")
        spec0 = None
        if qp:
            try:
                spec0 = P.Spec.from_param(qp).__dict__
            except Exception:
                spec0 = None
        _apply(key, feed, spec0 or PRESETS[feed][DEFAULT[feed]])
        ss[_k(key, "init")] = True

    st.subheader("Pivot table")
    st.caption("Build any table from the sales sheet, the way an Excel pivot works: pick what goes down the "
               "**Rows**, across the **Columns**, which **Values** to show and how, and **Filter** what you "
               "don't need. Download it as a formatted Excel file, or keep the link: the address bar "
               "now carries this exact table.")

    # ---- start from
    names = list(PRESETS[feed]) + list((ss.get(f"pv_saved_{feed}") or {}).keys())
    pick = st.pills("Start from", names, key=_k(key, "preset"), selection_mode="single")
    if pick and pick != ss.get(_k(key, "preset_applied")):
        src = PRESETS[feed].get(pick) or (ss.get(f"pv_saved_{feed}") or {}).get(pick)
        _apply(key, feed, src)
        ss[_k(key, "preset_applied")] = pick
        st.rerun()

    # ---- period
    per = P.periods(asof)
    pnames = list(per) + ["Custom"]
    pc1, pc2, pc3 = st.columns([2.2, 1, 1])
    period = pc1.selectbox("Period", pnames, key=_k(key, "period"),
                           help="The 'this year and last' periods put the SAME dates of both years side by side, "
                                "so a growth column compares equal stretches of time.")
    dmin, dmax = W["date"].min().date(), W["date"].max().date()
    if period == "Custom":
        ss.setdefault(_k(key, "from"), max(dmin, (pd.Timestamp(asof) - pd.Timedelta(days=30)).date()))
        ss.setdefault(_k(key, "to"), dmax)
        f = pc2.date_input("From", min_value=dmin, max_value=dmax, key=_k(key, "from"))
        t = pc3.date_input("To", min_value=dmin, max_value=dmax, key=_k(key, "to"))
        ranges = [[f, t]]
    else:
        ranges = per[period]
        if ranges:
            pc2.caption("Dates used")
            pc3.caption(" + ".join(f"{pd.Timestamp(a):%d %b %y} – {pd.Timestamp(b):%d %b %y}" for a, b in ranges))

    # ---- the four areas
    fmt_field = lambda f: f"{f}  ·  {groups.get(f, '')}"
    with st.container(border=True):
        a1, a2 = st.columns(2)
        with a1:
            st.markdown("**Filters**")
            fsel = st.multiselect("Filters", fields, key=_k(key, "filters"), format_func=fmt_field,
                                  label_visibility="collapsed", placeholder="Add a field to filter on")
            st.markdown("**Columns**")
            cols = st.multiselect("Columns", fields, key=_k(key, "cols"), format_func=fmt_field,
                                  label_visibility="collapsed", placeholder="Fields across the top (optional)")
        with a2:
            st.markdown("**Rows**")
            rows = st.multiselect("Rows", fields, key=_k(key, "rows"), format_func=fmt_field,
                                  label_visibility="collapsed", placeholder="Fields down the side")
            st.markdown("**Values**")
            vsel = st.multiselect("Values", list(M), key=_k(key, "vals"), label_visibility="collapsed",
                                  placeholder="What to measure")
        clash = set(rows) & set(cols)
        if clash:
            st.warning("A field can be in Rows or in Columns, not both: " + ", ".join(sorted(clash)))

        # value settings: one or more "show as" per value
        slots = [s for s in (ss.get(_k(key, "slots")) or []) if s[0] in vsel]
        for m in vsel:
            if not any(s[0] == m for s in slots):
                slots.append((m, "Value"))
        if vsel:
            st.markdown("**Show values as**")
            new_slots = []
            for m in vsel:
                opts = P.show_as_for(feed, m)
                sk = _k(key, f"show_{m}_x")
                ss[sk] = [h for h in (ss.get(sk) or ["Value"]) if h in opts] or ["Value"]
                got = st.multiselect(m, opts, key=sk,
                                     help=None if M[m].additive else
                                     "A ratio or a count of distinct things can't be a share of a total, so only "
                                     "the value and its change are offered.")
                for h in (got or ["Value"]):
                    new_slots.append((m, h))
            slots = new_slots
        ss[_k(key, "slots")] = slots

        filters = {}
        if fsel:
            st.markdown("**Filter settings**")
            for fld in fsel:
                fc1, fc2 = st.columns([4, 1.2])
                items = _field_items(W, feed, fld, token)
                fk = _k(key, f"fi_{fld}")
                ss[fk] = [x for x in (ss.get(fk) or []) if x in set(items)]
                ss.setdefault(_k(key, f"fm_{fld}"), "Include")
                got = fc1.multiselect(fld, items, key=_k(key, f"fi_{fld}"),
                                      placeholder=f"All {len(items)} — pick to narrow")
                mode = fc2.radio("Mode", ["Include", "Exclude"], key=_k(key, f"fm_{fld}"), horizontal=True,
                                 label_visibility="hidden")
                if got:
                    filters[fld] = {"mode": mode.lower(), "items": got}

    with st.expander("Layout, totals and sorting"):
        o1, o2, o3, o4 = st.columns(4)
        layout = o1.radio("Layout", ["Tabular", "Compact"], key=_k(key, "layout"),
                          help="Tabular: one column per row field, a total row under each group (as Excel's "
                               "tabular form). Compact: one indented column, each group's total on its own line.")
        subtotals = o2.toggle("Subtotals", key=_k(key, "subtotals"))
        grand_rows = o2.toggle("Grand total row", key=_k(key, "grand_rows"))
        grand_cols = o2.toggle("Grand total column", key=_k(key, "grand_cols"))
        if ss.get(_k(key, "sort")) not in SORTS_LABEL + list(vsel):
            ss[_k(key, "sort")] = "Label (A to Z)"
        sort = o3.selectbox("Sort rows by", SORTS_LABEL + [m for m in vsel], key=_k(key, "sort"))
        desc = o3.toggle("Largest first", key=_k(key, "desc"), disabled=sort in SORTS_LABEL)
        top = o4.number_input("Top N in each group (0 = all)", 0, 500, step=5, key=_k(key, "top"),
                              help="Keeps the N biggest items of the innermost row field inside each group. "
                                   "Totals still include the rest.")

    if not slots:
        st.info("Add at least one value.")
        return
    if clash:
        return

    spec = P.Spec(rows=rows, cols=cols, values=slots, filters=filters, ranges=[[str(a), str(b)] for a, b in ranges],
                  period=period, layout=layout, subtotals=subtotals, grand_rows=grand_rows, grand_cols=grand_cols,
                  sort_by=("Label (Z to A)" if sort == "Label (Z to A)" else "Label" if sort in SORTS_LABEL else sort),
                  descending=desc, top=int(top))
    try:
        st.query_params[f"pv_{feed}"] = spec.to_param()
    except Exception:
        pass

    try:
        g = P.build(W, feed, spec, prepared=True)
    except P.TooBig as e:
        st.warning(str(e))
        return
    except Exception as e:                                  # surface, never crash the tab
        st.error(f"Could not build that table: {e}")
        return
    if g.get("empty"):
        st.info(g["note"])
        return

    notes = [f"**{sum(r['kind'] == 'item' for r in g['rows']):,} rows × {len(g['leaf'])} value columns**",
             g["span"] if period != "FY to date · this year and last" else period, f"{g['rows_used']:,} source rows"]
    if g["filters"]:
        notes.append(" · ".join(g["filters"]))
    st.caption(" · ".join(notes))
    if g["hidden_items"]:
        st.caption(f"Top {top} kept in each group; {g['hidden_items']:,} smaller items hidden (totals include them).")
    growth = any(h.startswith("% change") or h.startswith("Change") for _m, h in slots)
    finer = {"FY Half", "FY Quarter", "Fiscal Month", "Month", "Quarter", "Week", "Day", "Day of month"}
    if growth and "Financial Year" in cols and period in ("All data", "Custom"):
        if finer & set(rows):
            st.caption(f"The latest period in the rows is only part-way through (data to {pd.Timestamp(asof):%d %b %Y}), "
                       "so its change compares part of it with all of last year's.")
        else:
            st.warning("**This compares a part year with a whole year.** This FY so far is set against all of last "
                       "FY, so the change reads low. Choose *FY to date · this year and last* to compare the same dates.")
    if feed == "vfl" and any(m == "Discount %" for m, _h in slots):
        st.info("Discount % is a flag here, not a depth: since June `Promotion Amount` equals the bill amount "
                "when a promotion is recorded.")
    if any(h.startswith("% change") or h.startswith("Change") for _m, h in slots):
        st.caption("Growth here counts every store in the period, including new and closed ones; the GD sheets "
                   "use like to like.")

    st.markdown(P.to_html(g), unsafe_allow_html=True)
    if len(g["rows"]) > 1500:
        st.caption(f"Showing the first 1,500 of {len(g['rows']):,} rows on screen; the Excel file has them all.")

    # ---- take it away
    st.write("")
    d1, d2, d3 = st.columns([2, 1.4, 1.4])
    title = (f"{'VFL' if feed == 'vfl' else 'Portfolio'} — " + " by ".join(
        [", ".join(rows) or "Total"] + ([", ".join(cols)] if cols else [])))
    with_src = d2.checkbox("Include the source rows", key=_k(key, "src"),
                           help="Adds a sheet with every row behind this table (dates and filters applied, no "
                                "customer mobiles) as an Excel table, so it can be pivoted again in Excel.")
    src = None
    if with_src:
        src = P.source_rows(df, feed, spec)
        if len(src) > 250000:
            d2.caption(f"{len(src):,} rows is too many for one sheet here; narrow the period or filters.")
            src = None
        else:
            d2.caption(f"{len(src):,} source rows")
    about = {
        "Feed": "VFL (one row per bill line)" if feed == "vfl" else "Portfolio (one row per store per day)",
        "Rows": ", ".join(rows) or "(none)", "Columns": ", ".join(cols) or "(none)",
        "Values": "; ".join(m if h == "Value" else f"{m} shown as {h}" for m, h in slots),
        "Period": period + (" — " + " + ".join(f"{pd.Timestamp(a):%d %b %Y} to {pd.Timestamp(b):%d %b %Y}"
                                                for a, b in ranges) if ranges else ""),
        "Filters": "; ".join(g["filters"]) or "(none)",
        "Layout": f"{layout}; subtotals {'on' if subtotals else 'off'}",
        "Source rows used": f"{g['rows_used']:,}",
        "Built": f"{pd.Timestamp.now():%d %b %Y %H:%M}",
        "How totals work": "Every subtotal and total is worked out again from the rows it covers, so a ratio's "
                           "total (ATV, UPT, ASP, conversion) is a true ratio, not the sum or average of the ratios "
                           "above it.",
        "Customer mobiles": "Never included. Customers can be counted, not listed.",
    }
    payload = P.to_excel(g, title=title, about=about, source=src)
    d1.download_button("⬇ Download this table (Excel)", payload, type="primary", use_container_width=True,
                       file_name=f"{title} {pd.Timestamp(asof):%d-%m-%Y}.xlsx".replace("/", "-").replace("→", "-"),
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=_k(key, "dl"))
    with d3.popover("Save this layout", use_container_width=True):
        nm = st.text_input("Name", key=_k(key, "savename"), placeholder="e.g. Monday review")
        if st.button("Save", key=_k(key, "savebtn"), disabled=not nm):
            saved = dict(ss.get(f"pv_saved_{feed}") or {})
            saved[nm] = spec.__dict__ | {"values": list(spec.values)}
            ss[f"pv_saved_{feed}"] = saved
            st.success("Saved for this session. To keep it for good, bookmark the page: the address bar holds "
                       "this exact table.")
