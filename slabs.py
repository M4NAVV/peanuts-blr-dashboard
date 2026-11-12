"""Target slabs — SUPER A / A / B / C for each store and month, from the `Target Slabs` tab.

Manav, 12 Nov 2026: the CON NOV26 slabs go into the sheets ("go with the formulas in the file, create it"), and the
manager morning report plots all four ("Targets all 4 to be plotted super a/a/b/c. All comparisons to follow B").

The tab (created 12 Nov 2026) is long format — MONTH | STORE CODE | BRAND LINE | … | C | B | A | SUPER A — with B
pulled from `Targets new` and the other three by formula from B (multipliers in M2:M4). A store kept on two brand
lines (Sevok Road, Agartala, Malda …) has two rows; the STORE's slab is their sum, which is what a store manager is
measured on.

Read by NAME through the workbook the portfolio feed already names (the same derivation `targets.py` uses), so no
secret of its own. A month with no rows returns {} and the report falls back to B alone and says so.
"""
from __future__ import annotations

import re
import time

import pandas as pd

_SHEET = "Target Slabs"
SLABS = ("SUPER A", "A", "B", "C")          # top first — the order the report draws them
_MEMO: dict = {}
_TTL = 600


def _url():
    import urllib.parse
    import targets as TG
    base = TG._from_secret(TG._PORTFOLIO_ENV)
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", str(base)) if base else None
    if not m:
        return None
    return (f"https://docs.google.com/spreadsheets/d/{m.group(1)}"
            f"/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(_SHEET)}")


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def load() -> pd.DataFrame:
    """Every row of the tab: month (first of month), code, line, C, B, A, SUPER A. Empty when unreadable."""
    url = _url()
    if not url:
        return pd.DataFrame()
    hit = _MEMO.get(url)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1].copy()
    try:
        d = pd.read_csv(url, dtype=str)
    except Exception:
        return pd.DataFrame()
    d.columns = [str(c).strip().upper() for c in d.columns]
    need = {"MONTH", "STORE CODE", "C", "B", "A", "SUPER A"}
    if not need <= set(d.columns):
        return pd.DataFrame()
    out = pd.DataFrame({
        # ★ the tab shows "Nov-26" (mmm-yy); read as month-year first — "mixed" read it as day 26 of Nov, year 1
        "month": pd.to_datetime(d["MONTH"], format="%b-%y", errors="coerce")
                   .fillna(pd.to_datetime(d["MONTH"], format="mixed", dayfirst=True, errors="coerce"))
                   .dt.to_period("M"),
        "code": pd.to_numeric(d["STORE CODE"], errors="coerce"),
        "line": d.get("BRAND LINE", pd.Series("", index=d.index)).fillna(""),
        **{s: _num(d[s]) for s in SLABS},
    }).dropna(subset=["month", "code"])
    out["code"] = out["code"].astype(int)
    _MEMO[url] = (time.monotonic(), out)
    return out.copy()


def for_store(code, asof) -> dict:
    """{"SUPER A": …, "A": …, "B": …, "C": …} for the store's month — its brand lines summed — or {}."""
    if code is None:
        return {}
    d = load()
    if d.empty:
        return {}
    d = d[(d["code"] == int(code)) & (d["month"] == pd.Timestamp(asof).to_period("M"))]
    if d.empty or d["B"].fillna(0).sum() <= 0:
        return {}
    return {s: float(d[s].fillna(0).sum()) for s in SLABS}
