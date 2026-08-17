"""
City growth — the market's movement, supplied rather than derived.

★ THIS IS AN INPUT. Manav, 12 Aug: "the VFL month wise city growth, is the
report of bangalore as a city, what percentage of business did it degrow or grow
by, thats it, you cant find that data anywhere, it will come from me only and
that sheet is the source of truth."

It is the CITY's growth — the whole market — not ours, so no amount of arithmetic
on our sales will reproduce it. Read it; never compute it. (Sales, bills, units,
average ticket and per-store means were all tried against the four filled months
and none of them match, which is the point.)

Its use is comparison: printed beside our own growth, the two answer whether we
are beating the market or losing share. In June the city grew 33.0% and we grew
40.2%; in April the city fell 6.1% and we fell 23.4%. Same direction, and a very
different story each time.

The tab carries `Region` and `City`, so figures are keyed by region and appear
wherever they exist — South today, others the day rows are added, with no code
change. A month with no figure yields nothing rather than zero: a blank must
never read as "the market was flat".
"""

from __future__ import annotations

import os
import re

import pandas as pd

URL_ENV = "CITY_GROWTH_URL"
# The tab's own gid, used to derive a URL from the workbook the portfolio feed
# already points at, so this needs no secret of its own to start working.
_GID = "237308006"

# ★ ADDRESSED BY NAME FIRST, gid SECOND (17 Aug). A gid is what a URL loses when
# it is edited by hand, and what changes if a tab is deleted and recreated — the
# night fill lost its gid once and silently served the workbook's FIRST tab, a
# failure that looked exactly like a working configuration. A name survives both.
# The gid stays as the fallback, so nothing breaks if a tab is renamed instead.
_SHEET = "VFL_Month Wise City Growth"

_PORTFOLIO_ENV = "PORTFOLIO_CSV_URL"


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
    if not m:
        return None
    return (f"https://docs.google.com/spreadsheets/d/{m.group(1)}"
            f"/export?format=csv&gid={_GID}")


def load(url=None):
    """-> {(region, Timestamp(month start)): percent}, or {} if unavailable.

    Tries the tab by name before falling back to its gid — see `_SHEET`.
    """
    for candidate in ([url] if url else _candidates()):
        got = _load_one(candidate)
        if got:
            return got
    return {}


def _load_one(url):
    if not url:
        return {}
    try:
        d = pd.read_csv(url, dtype=str)
        d.columns = [str(c).strip() for c in d.columns]
        need = {"Month", "Growth/Degrowth Percent", "Region"}
        if not need <= set(d.columns):
            return {}
        out = {}
        for _, r in d.iterrows():
            cell = r["Growth/Degrowth Percent"]
            if pd.isna(cell):
                continue                      # not filled in yet — NOT zero
            pct = str(cell).strip().replace("%", "").replace(",", "")
            if not pct or pct.lower() == "nan":
                continue
            try:
                v = float(pct)
            except ValueError:
                continue
            if pd.isna(v):                    # float("nan") parses; reject it
                continue
            # "April-2026" -> the month it starts, so it can be matched to a
            # trajectory month without depending on the date columns' format.
            when = pd.to_datetime(str(r["Month"]).strip(), format="%B-%Y",
                                  errors="coerce")
            if pd.isna(when):
                when = pd.to_datetime(str(r.get("Date from", "")).strip(),
                                      dayfirst=True, errors="coerce")
                if pd.isna(when):
                    continue
                when = when.replace(day=1)
            out[(str(r["Region"]).strip(), pd.Timestamp(when).normalize())] = v
        return out
    except Exception:
        return {}


def for_months(region, months, asof):
    """Percentages lined up with a trajectory's month labels ("Apr", "May" …).

    Returns a list the same length as `months`, with None where the sheet has
    no figure — the renderer prints nothing for those.
    """
    data = load()
    if not data or not region:
        return [None] * len(months)
    asof = pd.Timestamp(asof)
    fy = asof.year if asof.month >= 4 else asof.year - 1
    out = []
    for label in months:
        when = pd.to_datetime(label, format="%b", errors="coerce")
        if pd.isna(when):
            out.append(None); continue
        year = fy if when.month >= 4 else fy + 1
        out.append(data.get((region, pd.Timestamp(year, when.month, 1))))
    return out


def _candidates():
    """Every URL worth trying, best first: an explicit override, then the tab by
    NAME, then by gid. See the note beside `_SHEET`."""
    import urllib.parse
    out = []
    explicit = _from_secret(URL_ENV)
    if explicit:
        out.append(explicit)
    base = _from_secret(_PORTFOLIO_ENV)
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", str(base)) if base else None
    if m:
        wid = m.group(1)
        out.append(f"https://docs.google.com/spreadsheets/d/{wid}"
                   f"/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(_SHEET)}")
        out.append(f"https://docs.google.com/spreadsheets/d/{wid}"
                   f"/export?format=csv&gid={_GID}")
    return [u for i, u in enumerate(out) if u and u not in out[:i]]
