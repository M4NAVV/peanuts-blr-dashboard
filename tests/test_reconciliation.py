"""Reconciliation: does the dashboard still agree with the figures Manav signed off?

Every other test here pins a RULE on made-up data. This one pins NUMBERS — the
ones Manav validated against his own workbooks (the 31/07/26 Growth-Degrowth
sheet, the 09-Aug night SMS, the VFL G/D) — and computes each through the SAME
code the reports use. Pinned to his figures, not to whatever the code prints
today, so it says "the reports still tie to the sheet he signed off".

★ NO FIGURES LIVE IN THIS FILE. The repo is public and these are real store
sales, so the expected values sit in a private file outside every repo
(`~/Documents/peanuts-recon/golden.json`, or $PEANUTS_RECON). Without that file,
or without the live data, the whole module SKIPS and says why — so CI, which has
neither, stays green, and `./deploy.sh` on Manav's Mac runs it for real.

★ EVERY WINDOW IS CLOSED (a finished month, a finished year, a target), never
the feed's newest day — see [[feedback-settled-window]].

A failure means one of two things, and the message says both:
  1. something broke in the code, or
  2. the SHEET'S history was edited (it has been: four months moved after the
     31 Jul sign-off) or a rule changed on purpose. Then update `expect` in the
     private file, with a note, so the trail records why.
"""
from __future__ import annotations

import json
import os

import pytest

GOLDEN = os.environ.get("PEANUTS_RECON",
                        os.path.expanduser("~/Documents/peanuts-recon/golden.json"))

if not os.path.exists(GOLDEN):
    pytest.skip(f"no reconciliation file on this machine ({GOLDEN}); it runs on "
                f"Manav's Mac at deploy", allow_module_level=True)

CHECKS = json.load(open(GOLDEN))["checks"]


@pytest.fixture(scope="module")
def data():
    import pandas as pd
    import loader as L
    import portfolio_loader as PL
    try:
        v = L.load_data(pf=None)
        pf = PL.load_portfolio()
    except Exception as e:                       # no secrets / offline
        pytest.skip(f"live data unavailable: {type(e).__name__}: {e}")
    if v is None or pf is None or v.empty or pf.empty:
        pytest.skip("live data came back empty")
    return pd, L, PL, v, pf


def _compute(c, pd, L, PL, v, pf, cache={}):
    k = c["kind"]
    if k == "mw":
        if "mw" not in cache:
            cache["mw"] = PL.mw_data(pf, asof=pd.Timestamp("2026-07-31"))
        months = {m["month"]: m for m in cache["mw"][c["fy"]]["months"]}
        return months[c["month"]][c["field"]]
    if k == "pf_sum":
        x = pf[(pf["date"] >= pd.Timestamp(c["start"])) & (pf["date"] <= pd.Timestamp(c["end"]))]
        return x["sales"].sum()
    if k == "vfl_ytd_ty":
        cur, _ = L.report_frames(v, "YTD", asof=pd.Timestamp(c["asof"]))
        return cur[L.COL_AMOUNT].sum()
    if k == "vfl_ly_region":
        m = L.load_store_master()
        names = set(m[m["region"] == c["region"]]["tableau_name"])
        _, prior = L.report_frames(v, "YTD", asof=pd.Timestamp(c["asof"]))
        return prior[prior[L.COL_STORE_LABEL].isin(names)][L.COL_AMOUNT].sum()
    if k == "vfl_ly_full":
        g = L.vfl_gd_report(v, asof=pd.Timestamp(c["asof"]))
        g = g[0] if isinstance(g, tuple) else g
        code = pd.to_numeric(g["STORE CODE"], errors="coerce").ffill()
        col = next(x for x in g.columns if "LY FULL" in x.upper())
        rows = g[(code == c["code"]) & g["STORE NAME"].astype(str).str.strip().ne("")]
        return pd.to_numeric(rows[col], errors="coerce").sum()
    if k == "target":
        import targets as T
        tt = T.load()
        m = L.load_store_master()
        codes = set(pd.to_numeric(m[m["region"] == c["region"]]["code"], errors="coerce").dropna().astype(int))
        return pd.to_numeric(tt[tt["code"].isin(codes)][c["col"]], errors="coerce").sum()
    raise ValueError(f"unknown check kind {k}")


@pytest.mark.parametrize("c", CHECKS, ids=[c["id"] for c in CHECKS])
def test_ties_to_the_signed_off_figure(c, data):
    got = _compute(c, *data)
    want = c["expect"]
    assert round(float(got), 2) == round(float(want), 2), (
        f"{c['id']}: dashboard {got:,.2f}, expected {want:,.2f} "
        f"(difference {got - want:+,.2f}; signed off as {c.get('signed_off')} — {c.get('source')}). "
        f"Either the code broke, or the sheet's history was edited / a rule changed on purpose: "
        f"if so, update 'expect' in {GOLDEN} with a note.")
