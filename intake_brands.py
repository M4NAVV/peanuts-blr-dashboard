"""The brand split, read straight off the intake form — like any other source.

Manav, 27 Sep 2026: *"cant we do something where we get this read normally like
everything else from our data sources … so we dont need the actions or the mac
launch."*

He was right and my first version was wrong. I had routed this through the
intake pipeline's results sheet, which meant something had to RUN on a
schedule before the dashboard could see tonight's split. Nothing here needs
that: the form's responses sheet and the store-mail map both read with no
credentials at all, exactly like every other feed, so the split is computed at
refresh time and is never staler than the page.

★★ THE PIPELINE STILL MATTERS, IT IS JUST NOT IN THIS PATH. `run.py` does the
quarantine, the coverage list and — eventually — the replacement of the typed
sales figure. Peanuts total remains the source of truth for the money. This
reads three brand figures and nothing else.

★ SO THE VALIDATION HERE IS DELIBERATELY THIN, and these are the three rules
that actually matter for a split:

    an email not in the store master  ->  ignored, it maps to no store
    a date later than the submission  ->  ignored, nobody files the future
    two submissions for one store-day ->  THE LATEST WINS

★★ THE LAST ONE IS THE CORRECTION PATH. Re-filing is how a store fixes a
figure it mistyped — it is what the form's own instructions tell them to do —
so the newest submission for a store-day must replace the earlier one, never
be averaged with it or lose to it.
"""
from __future__ import annotations

import os
import re

import pandas as pd

RESPONSES_ENV = "INTAKE_RESPONSES_URL"
DIRECTORY_ENV = "STORE_DIRECTORY_URL"
BRANDS = ("manyavar", "mohey", "twamev")
_BRAND_COLS = {"manyavar": ("MANYAVAR SALES", "MANYAVAR"),
               "mohey": ("MOHEY SALES", "MOHEY"),
               "twamev": ("TWAMEV SALES", "TWAMEV")}
# ★ `GMT+5:30` READ BY dateutil IS −05:30 — the POSIX sign convention, an
# ELEVEN HOUR error landing exactly on a midnight cutoff. Stripped, not parsed.
_TZ_SUFFIX = re.compile(r"\s*GMT[+-]\d{1,2}:?\d{2}\s*$", re.I)
_NUM_JUNK = re.compile(r"[₹,\s]")

_LAST_PROBLEM = None


def last_problem():
    """Why no split was read, or None — surfaced so a dead source is visible."""
    return _LAST_PROBLEM


def _secret(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        return st.secrets.get(name)
    except Exception:
        return None


def _csv_url(raw):
    """A sheet id, a normal URL or an /export URL — all end up as an export."""
    if not raw:
        return None
    raw = str(raw).strip()
    if "/export" in raw:
        return raw
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", raw)
    fid = m.group(1) if m else raw
    g = re.search(r"[#&?]gid=(\d+)", raw)
    gid = g.group(1) if g else "0"
    return (f"https://docs.google.com/spreadsheets/d/{fid}"
            f"/export?format=csv&gid={gid}")


def _num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = _NUM_JUNK.sub("", str(v)).strip()
    if s in ("", "-", "NA", "na", "N/A", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _find(cols, names):
    low = {str(c).strip().upper(): c for c in cols}
    for n in names:
        if n.upper() in low:
            return low[n.upper()]
    for n in names:
        for k, c in low.items():
            if n.upper() in k:
                return c
    return None


def mail_map(url=None) -> dict:
    """{email: store code} from the store master — the sole authority on who
    a submission belongs to, exactly as the intake pipeline treats it.

    ★ THE ADDRESSES ARE READ AND NEVER RENDERED OR WRITTEN DOWN. This repo is
    public; the master tab holds mail ids, phone numbers and GST numbers, and
    the rule has always been that it may be READ at runtime and never
    snapshotted. Only the email-to-code mapping leaves this function.
    """
    src = _csv_url(url or _secret(DIRECTORY_ENV))
    if not src:
        return {}
    d = pd.read_csv(src)
    mail_c = _find(d.columns, ("STORE MAIL ID", "MAIL", "EMAIL"))
    code_c = _find(d.columns, ("STORE CODE", "CODE"))
    if mail_c is None or code_c is None:
        return {}
    out = {}
    for m, c in zip(d[mail_c], d[code_c]):
        m = str(m).strip().lower()
        c = pd.to_numeric(c, errors="coerce")
        if "@" in m and not pd.isna(c):
            out[m] = int(c)
    return out


def read_responses(url=None) -> pd.DataFrame:
    src = _csv_url(url or _secret(RESPONSES_ENV))
    if not src:
        raise ValueError(f"${RESPONSES_ENV} is not set")
    return pd.read_csv(src)


def split_map(responses=None, mails=None) -> dict:
    """{(store code, date): {manyavar, mohey, twamev}} — latest filing wins."""
    global _LAST_PROBLEM
    _LAST_PROBLEM = None
    try:
        df = read_responses() if responses is None else responses
        mails = mail_map() if mails is None else mails
    except Exception as e:
        _LAST_PROBLEM = f"could not read the intake form ({type(e).__name__})"
        return {}
    if df is None or not len(df):
        _LAST_PROBLEM = "no store has filed the form yet"
        return {}
    if not mails:
        _LAST_PROBLEM = "no store-mail map — every submission is unattributable"
        return {}

    ts_c = _find(df.columns, ("TIMESTAMP",)) or df.columns[0]
    em_c = _find(df.columns, ("EMAIL ADDRESS", "EMAIL"))
    dt_c = _find(df.columns, ("DATE",))
    got = {k: _find(df.columns, v) for k, v in _BRAND_COLS.items()}
    if em_c is None or not any(got.values()):
        _LAST_PROBLEM = (f"the form has no email and/or brand columns — "
                         f"found {list(df.columns)}")
        return {}

    d = df.copy()
    d["_ts"] = pd.to_datetime(
        d[ts_c].astype(str).str.replace(_TZ_SUFFIX, "", regex=True),
        errors="coerce")
    d["_code"] = (d[em_c].astype(str).str.strip().str.lower().map(mails))
    d["_date"] = d.apply(lambda r: _read_date(r.get(dt_c), r["_ts"]), axis=1)
    d = d[d["_code"].notna() & d["_date"].notna()]
    if not len(d):
        _LAST_PROBLEM = "no submission could be attributed to a store"
        return {}

    # ★★ THE LATEST FILING WINS — the correction path. Re-filing is what the
    # form tells a store to do when it mistypes, so the newest submission for a
    # store-day REPLACES the earlier one. Ordered by the submission time, then
    # by sheet order, because Forms stamps to the second and appends in order:
    # two submissions in the same second are still resolved deterministically.
    d["_row"] = range(len(d))
    d = d.sort_values(["_ts", "_row"], na_position="first")
    d = d.drop_duplicates(subset=["_code", "_date"], keep="last")

    out = {}
    for _, r in d.iterrows():
        vals = {b: _num(r[c]) for b, c in got.items() if c is not None}
        if not any(v is not None for v in vals.values()):
            continue
        out[(int(r["_code"]), pd.Timestamp(r["_date"]).normalize())] = {
            b: float(vals.get(b) or 0.0) for b in BRANDS}
    if not out:
        _LAST_PROBLEM = "no submission carried a brand figure"
    return out


def _read_date(value, submitted):
    """The day a submission is about. Blank falls back to the day it was sent.

    ★ MONTH-FIRST AND DAY-FIRST ARE BOTH TRIED and the reading that can be true
    is kept — this sheet writes its own Timestamp month-first while the
    portfolio sheet is day-first, so `10/9/2026` is 9 Oct or 10 Sep and it only
    goes wrong above the 12th. Nobody files the future, so a date after the
    submission is refused. The twin of `formdata.read_date` in StoreIntake.
    """
    if pd.isna(submitted):
        return pd.NaT
    day = pd.Timestamp(submitted).normalize()
    txt = "" if value is None else str(value).strip()
    if not txt or txt.lower() == "nan":
        return day
    cand = []
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            cand.append(pd.Timestamp(pd.to_datetime(txt, format=fmt)).normalize())
        except (ValueError, TypeError):
            continue
    if not cand:
        loose = pd.to_datetime(txt, errors="coerce")
        if pd.isna(loose):
            return pd.NaT
        cand = [pd.Timestamp(loose).normalize()]
    fits = [c for c in cand if 0 <= (day - c).days <= 2]
    if fits:
        return fits[0]
    past = sorted([c for c in cand if c <= day], reverse=True)
    return past[0] if past else pd.NaT


def for_day(day, codes=None, responses=None, mails=None) -> dict:
    """{code: {manyavar, mohey, twamev}} for one night."""
    day = pd.Timestamp(day).normalize()
    m = split_map(responses, mails)
    want = None if codes is None else {int(c) for c in codes}
    return {c: v for (c, d), v in m.items()
            if d == day and (want is None or c in want)}
