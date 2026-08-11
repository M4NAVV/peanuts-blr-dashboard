"""Store-attribute lookups for the Report T.D. vertical.

Only the columns the reports need. The full store master is a whole operations
sheet — GST numbers, phone numbers, addresses, store mail IDs — and THIS REPO IS
PUBLIC, so the master itself is never committed here. Two sources, in order:

  1. `STORE_MASTER_URL` (env var or Streamlit secret) — the live master tab, read
     through its CSV /export endpoint, the same mechanism the dashboard uses for
     its data. Set this and new stores appear without a code change.
  2. `store_carpet.csv` — a committed extract of just `code, carpet_sqft`, which
     carries nothing sensitive and keeps the reports working before the secret is
     configured.

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
_EXTRACT = os.path.join(os.path.dirname(__file__), "store_carpet.csv")


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
