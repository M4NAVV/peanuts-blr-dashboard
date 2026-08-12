"""
Targets — the year's and each month's, per store.

A tab of the same workbook: one row per store per brand line, with a
`YEAR TARGET` column and twelve month columns (Apr … Mar). A store's target sits
on whichever brand line it was entered against and the others are blank, so
figures are SUMMED per store — the same "once per store" pattern as the night
fill's bills and footfall.

Verified against the 09-Aug night SMS, all eight South stores exact on both:
`YEAR TARGET` is that report's YTD TARGET (85,78,75,000 for South) and the month
column is its MTD TARGET (5,94,00,000 for August).

★ THE DAY TARGET IS NOT HERE. It is the one target that moves daily, so it lives
in the night fill beside the day's figures; see `night_fill`.

Only the months that have been filled are returned. A month left blank yields
nothing rather than zero, so a report shows an empty target rather than claiming
a store was asked for nothing.
"""

from __future__ import annotations

import os
import re

import pandas as pd

URL_ENV = "TARGETS_URL"
_GID = "1007333059"
_PORTFOLIO_ENV = "PORTFOLIO_CSV_URL"
_MONTHS = ("Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
           "Jan", "Feb", "Mar")


def _from_secret(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        return st.secrets.get(name)
    except Exception:
        return None


def _url():
    explicit = _from_secret(URL_ENV)
    if explicit:
        return explicit
    base = _from_secret(_PORTFOLIO_ENV)
    if not base:
        return None
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", str(base))
    return (f"https://docs.google.com/spreadsheets/d/{m.group(1)}"
            f"/export?format=csv&gid={_GID}") if m else None


def _num(s):
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.strip()
         .replace({"-": "", "nan": ""}), errors="coerce")


def load(url=None) -> pd.DataFrame | None:
    """One row per store: code, year, and a column per filled month."""
    url = url or _url()
    if not url:
        return None
    try:
        d = pd.read_csv(url, dtype=str)
        d.columns = [str(c).strip() for c in d.columns]
        if "CODE" not in d.columns or "YEAR TARGET" not in d.columns:
            return None
        out = pd.DataFrame({"code": pd.to_numeric(d["CODE"], errors="coerce")})
        out["year"] = _num(d["YEAR TARGET"])
        for m in _MONTHS:
            out[m] = _num(d[m]) if m in d.columns else pd.NA
        out = out[out["code"].notna()]
        if out.empty:
            return None
        out["code"] = out["code"].astype(int)
        # Sum per store: the figure sits on one brand line, the rest are blank.
        return out.groupby("code", as_index=False).sum(min_count=1)
    except Exception:
        return None


def for_month(day) -> dict:
    """-> {code: {"ytd": year target, "mtd": that month's}}. Empty if absent.

    A target of zero is treated as absent: the tab uses blanks and dashes for
    closed stores, and a zero target would make any achievement read as
    infinite rather than as unknown.
    """
    t = load()
    if t is None:
        return {}
    day = pd.Timestamp(day)
    col = _MONTHS[(day.month - 4) % 12]
    out = {}
    for _, r in t.iterrows():
        y = r.get("year")
        m = r.get(col) if col in t.columns else None
        e = {}
        if pd.notna(y) and float(y) > 0:
            e["ytd"] = float(y)
        if m is not None and pd.notna(m) and float(m) > 0:
            e["mtd"] = float(m)
        if e:
            out[int(r["code"])] = e
    return out
