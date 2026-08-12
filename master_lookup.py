"""Store-attribute lookups for the Report T.D. vertical.

Only the columns the reports need. The full store master is a whole operations
sheet — GST numbers, phone numbers, addresses, store mail IDs — and THIS REPO IS
PUBLIC, so the master itself is never committed here. Two sources, in order:

  1. `STORE_MASTER_URL` (env var or Streamlit secret) — the live master tab, read
     through its CSV /export endpoint, the same mechanism the dashboard uses for
     its data. Set this and new stores appear without a code change.
  2. `store_attrs.csv` — a committed extract of `code, carpet_sqft, opened,
     closed`, which carries nothing sensitive and keeps the reports working
     before the secret is configured. Regenerate it whenever the master gains a
     store, an opening date or a closure.

If neither is available the carpet and throughput columns come out blank rather
than wrong.
"""
from __future__ import annotations

import os

import pandas as pd

MASTER_URL_ENV = "STORE_MASTER_URL"

# ★ HEAD OFFICE IS NOT A STORE (Manav, 11 Aug): "this should not be counted when
# doing any sort of analytics. this is our office." It is a row in the master —
# code 1001, name "HO", first bill date "X", 2,600 sqft — so it has to be
# excluded explicitly wherever the master is read, or its floor space lands in
# the carpet total and quietly deflates every throughput figure.
# The store-intake pipeline carries the same exclusion for the same reason.
NON_STORE_CODES = {1001}
_EXTRACT = os.path.join(os.path.dirname(__file__), "store_attrs.csv")


def _master_url():
    if os.environ.get(MASTER_URL_ENV):
        return os.environ[MASTER_URL_ENV]
    try:
        import streamlit as st
        return st.secrets.get(MASTER_URL_ENV)
    except Exception:
        return None


def carpet() -> dict:
    """store code -> carpet sqft."""
    url = _master_url()
    if url:
        try:
            m = pd.read_csv(url, dtype=str)
            m.columns = [str(c).strip() for c in m.columns]
            code = pd.to_numeric(m.get("STORE CODE"), errors="coerce")
            area = pd.to_numeric(m.get("CARPET"), errors="coerce")
            got = {int(c): float(a) for c, a in zip(code, area)
                   if pd.notna(c) and pd.notna(a)
                   and int(c) not in NON_STORE_CODES}
            if got:
                return got
        except Exception:
            pass                     # fall through to the committed extract
    if not os.path.exists(_EXTRACT):
        return {}
    m = pd.read_csv(_EXTRACT)
    return {int(c): float(a) for c, a in zip(m["code"], m["carpet_sqft"])
            if pd.notna(c) and pd.notna(a) and int(c) not in NON_STORE_CODES}


def _read():
    """The live master as a frame, or None when it is not configured."""
    url = _master_url()
    if not url:
        return None
    try:
        m = pd.read_csv(url, dtype=str)
        m.columns = [str(c).strip() for c in m.columns]
        m["_code"] = pd.to_numeric(m.get("STORE CODE"), errors="coerce")
        return m[m["_code"].notna()]
    except Exception:
        return None


def _dates(column, fallback) -> dict:
    """store code -> date, from the live master or the committed extract.

    Falling back matters: an empty map would silently mean "no store is new and
    none has closed", which is a wrong answer rather than a missing one.
    """
    m = _read()
    if m is None or column not in m.columns:
        return _extract_dates(fallback)
    out = {}
    for c, v in zip(m["_code"], m[column]):
        v = str(v).strip()
        if not v or v.upper() == "X":       # "X" means not applicable (head office)
            continue
        d = pd.to_datetime(v, dayfirst=True, errors="coerce")
        if pd.notna(d) and int(c) not in NON_STORE_CODES:
            out[int(c)] = d
    return out or _extract_dates(fallback)


def _extract_dates(column) -> dict:
    if not os.path.exists(_EXTRACT):
        return {}
    m = pd.read_csv(_EXTRACT)
    if column not in m.columns:
        return {}
    d = pd.to_datetime(m[column], errors="coerce")
    return {int(c): v for c, v in zip(m["code"], d)
            if pd.notna(c) and pd.notna(v) and int(c) not in NON_STORE_CODES}


def opened() -> dict:
    """store code -> opening date (the master's FIRST BILL DATE).

    The sales feeds cannot supply this: the portfolio sheet begins on
    1 Apr 2025, so a store that opened in 2024 and one that opened that very
    morning both look like they started that day. Using the feed classified
    every store as new in April.
    """
    return _dates("FIRST BILL DATE", "opened")


def closed() -> dict:
    """store code -> closure date, the LAST month still counted (Manav, 7 Aug)."""
    return _dates("CLOSURE DATE", "closed")
