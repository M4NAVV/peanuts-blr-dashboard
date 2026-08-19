"""
Targets — the year's and each month's, per store.

The `Targets New` tab of the same workbook — HIS SOURCE OF TRUTH since 18 Aug
2026 — with one row per store per brand line, a `YEAR TARGET` column and twelve
month columns (APR … MAR). A store's target sits on whichever brand line it was
entered against and the others are blank, so figures are SUMMED per store — the
same "once per store" pattern as the night fill's bills and footfall.

Verified against the 09-Aug night SMS, all eight South stores exact on both:
`YEAR TARGET` is that report's YTD TARGET (85,78,75,000 for South) and the month
column is its MTD TARGET (5,94,00,000 for August).

⚠️ Column names are matched WITHOUT CASE. They were not until 18 Aug, and the
mismatch (APR in the tab, Apr in this file) emptied every month target silently
while the year target kept loading — see the note in `_load_one`.

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

# ★★ THE SOURCE OF TRUTH IS THE `Targets New` TAB (Manav, 18 Aug: "i have added
# a new targets new sheet which is the source of truth now for all target
# related calculations"). The older `Targets` tab (gid 1007333059) is NO LONGER
# READ AT ALL — not even as a fallback. Today the two agree to the rupee, so the
# switch moves no number; the moment they diverge, a silent fall-back to the
# superseded tab would be worse than showing nothing, which is why it is gone.
#
# ADDRESSED BY NAME, because a gid is what a URL loses when it is edited by hand
# and what changes if a tab is deleted and recreated. A wrong NAME is safe here:
# gviz answers it with the workbook's FIRST tab, whose columns are transactions,
# and `_load_one` rejects anything without CODE and YEAR TARGET.
_SHEET = "Targets New"

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
    c = _candidates()
    return c[0] if c else None


_PROBLEM = None


def last_problem():
    """Why the last load gave less than it should have, in his words, or None.

    A target that quietly fails to arrive is indistinguishable from a target
    nobody set — and that is exactly how twelve month columns went missing
    unnoticed. The reports ask this and print it.
    """
    return _PROBLEM


def _num(s):
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.strip()
         .replace({"-": "", "nan": ""}), errors="coerce")


def load(url=None) -> pd.DataFrame | None:
    """One row per store: code, year, and a column per filled month.

    Tries the tab by name before falling back to its gid — a wrong gid serves
    the workbook's first tab, which reads as a configuration that works.
    """
    global _PROBLEM
    _PROBLEM = None
    for candidate in ([url] if url else _candidates()):
        got = _load_one(candidate)
        if got is not None:
            return got
    if _PROBLEM is None:
        _PROBLEM = (f"the '{_SHEET}' tab could not be read — every target "
                    f"column is blank until it can be")
    return None


def _load_one(url) -> pd.DataFrame | None:
    global _PROBLEM
    if not url:
        return None
    try:
        d = pd.read_csv(url, dtype=str)
        d.columns = [str(c).strip() for c in d.columns]
        # ★ HEADERS ARE MATCHED WITHOUT REGARD TO CASE (18 Aug). The tab writes
        # APR..MAR in capitals and this module named them Apr..Mar, so `m in
        # d.columns` was False twelve times over and EVERY MONTH TARGET CAME
        # BACK EMPTY — the night SMS and target-vs-achievement printed no MTD or
        # YTD target at all, while the year target loaded fine and made the feed
        # look healthy. The columns this module returns keep their title case,
        # so nothing downstream changes.
        by_upper = {c.upper(): c for c in d.columns}

        def col(name):
            return by_upper.get(name.upper())

        if not col("CODE") or not col("YEAR TARGET"):
            return None
        out = pd.DataFrame({"code": pd.to_numeric(d[col("CODE")],
                                                  errors="coerce")})
        out["year"] = _num(d[col("YEAR TARGET")])
        missing = [m for m in _MONTHS if not col(m)]
        for m in _MONTHS:
            src = col(m)
            out[m] = _num(d[src]) if src else pd.NA
        if len(missing) == len(_MONTHS):
            _PROBLEM = (f"the '{_SHEET}' tab has no month columns "
                        f"(Apr…Mar) — only the year target could be read")
        elif missing:
            _PROBLEM = (f"the '{_SHEET}' tab is missing "
                        f"{', '.join(missing)} — those months read as no target")
        out = out[out["code"].notna()]
        if out.empty:
            return None
        out["code"] = out["code"].astype(int)
        # Sum per store: the figure sits on one brand line, the rest are blank.
        return out.groupby("code", as_index=False).sum(min_count=1)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# ★★ WHICH YEAR ARE THESE TARGETS FOR? THE TAB DOES NOT SAY. (19 Aug 2026)
#
# It holds `YEAR TARGET` and twelve month columns and nothing that names a
# fiscal year, so `for_month(2027-04-15)` cheerfully returned FY26-27's targets
# — 53 stores, unlabelled, indistinguishable from a tab someone had updated.
# On 1 April 2027 every achievement figure would have been measured against
# last year's ask, with no error anywhere.
#
# Nothing in the data can be derived from, so the check is the same one the
# validation gate uses for its row floor: a COMMITTED reference. `targets_fy.json`
# records the fiscal year these figures were last seen changing in, plus a
# fingerprint of the numbers. If the year rolls over and the numbers have not
# moved, the tab was never rolled forward, and the reports say so instead of
# quoting last year's ask as this year's.
#
# When the team does paste new targets the fingerprint changes, the warning
# stops by itself, and the file is refreshed on the next push.
# --------------------------------------------------------------------------- #
_MARKER = "targets_fy.json"


def _fingerprint(t) -> str:
    import hashlib
    cols = ["code", "year"] + list(_MONTHS)
    have = [c for c in cols if c in t.columns]
    body = t[have].sort_values("code").round(2).to_csv(index=False)
    return hashlib.sha1(body.encode()).hexdigest()[:16]


def _marker_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _MARKER)


def _read_marker():
    import json
    try:
        with open(_marker_path()) as f:
            m = json.load(f)
        return int(m["fy"]), str(m["fingerprint"])
    except Exception:
        return None, None


def fiscal_year_problem(t, day):
    """The tab's year against the day's, or None. See the block above."""
    fy = day.year if day.month >= 4 else day.year - 1
    seen_fy, seen_fp = _read_marker()
    if seen_fy is None or t is None or t.empty:
        return None                       # no reference yet: say nothing
    if fy <= seen_fy:
        return None                       # the year these targets are known for
    if _fingerprint(t) == seen_fp:
        return (f"the '{_SHEET}' tab has not changed since FY{seen_fy}-"
                f"{str(seen_fy + 1)[-2:]} — these are LAST YEAR'S targets, not "
                f"FY{fy}-{str(fy + 1)[-2:]}'s")
    return None                           # numbers moved: taken as rolled forward


def for_month(day) -> dict:
    """-> {code: {"ytd": year target, "mtd": that month's}}. Empty if absent.

    A target of zero is treated as absent: the tab uses blanks and dashes for
    closed stores, and a zero target would make any achievement read as
    infinite rather than as unknown.
    """
    global _PROBLEM
    t = load()
    if t is None:
        return {}
    day = pd.Timestamp(day)
    stale = fiscal_year_problem(t, day)
    if stale:                             # a wrong YEAR is worse than no target
        _PROBLEM = stale
        return {}
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


def _candidates():
    """Every URL worth trying, best first: an explicit override, then the tab by
    NAME. There is deliberately no gid fallback — see the note beside `_SHEET`."""
    import urllib.parse
    out = []
    explicit = _from_secret(URL_ENV)
    if explicit:
        out.append(explicit)
    base = _from_secret(_PORTFOLIO_ENV)
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", str(base)) if base else None
    if m:
        out.append(f"https://docs.google.com/spreadsheets/d/{m.group(1)}"
                   f"/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(_SHEET)}")
    return [u for i, u in enumerate(out) if u and u not in out[:i]]
