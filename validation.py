"""A gate between a loaded feed and the reports that trust it.

The failure this exists for is not a crash. It is a feed that arrives smaller
than it should and renders perfectly: every total ties to itself, every report
draws, the freshness line says today, and the number is wrong. It has happened
here — the sheet dropped from 265k rows to 143k mid-session and was caught by
luck. Simulated on the live feed, three stores missing from an export
understates the year by Rs 2.34 Cr (8.3%) while the date still reads today.

A crash gets reported in minutes; quietly-wrong numbers get put in a deck.

Two tiers, deliberately:

  PROBLEM  the frame is not fit to serve — refuse, and say what was expected
           against what arrived. Kept to things that cannot be a legitimate
           change: no rows at all, a required column gone, a date in the
           future, a collapse in row count against the last good load.

  WARNING  something moved that is usually deliberate but occasionally a
           mistake: a store stopped reporting, the estate no longer matches
           the master, the year's total jumped. Shown, never blocking.

The comparison baseline is the last load that passed, fingerprinted to a small
JSON file beside the process. It is per-container and resets on redeploy: that
is enough to catch the sheet changing under a running app, which is the
incident we have actually had, without pretending we can carry state across
deploys.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field

import pandas as pd

# A collapse, not a fluctuation. Rows only fall when something is wrong — the
# sheets are append-only in practice — so this is deliberately generous: it
# fires on the 54% truncation we have seen, not on a day's ordinary variation.
MIN_ROW_FRACTION = 0.70
# The estate moving by more than this against the last good load is worth a
# look, not a refusal: stores do open and close.
STORE_DROP_WARN = 1
# A year-to-date that moves this much between two loads of the same day is
# either a restatement or a mistake.
TOTAL_SWING_WARN = 0.10

_STATE = os.path.join(tempfile.gettempdir(), "peanuts_feed_state.json")


@dataclass
class Report:
    kind: str
    facts: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    baseline: dict | None = None

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        n = self.facts
        return (f"{n.get('rows', 0):,} rows · {n.get('stores', 0)} stores · "
                f"through {n.get('max_date', '—')}")


def _state() -> dict:
    try:
        with open(_STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(kind: str, facts: dict) -> None:
    s = _state()
    s[kind] = facts
    try:
        with open(_STATE, "w") as f:
            json.dump(s, f)
    except Exception:
        pass                      # a baseline we cannot store is not a failure


def fingerprint(df: pd.DataFrame, *, date_col: str, store_col: str,
                value_col: str) -> dict:
    d = pd.to_datetime(df[date_col], errors="coerce")
    return {
        "rows": int(len(df)),
        "stores": int(df[store_col].nunique()),
        "max_date": None if d.isna().all() else str(d.max().date()),
        "total": float(pd.to_numeric(df[value_col], errors="coerce").sum()),
    }


def validate(df: pd.DataFrame, kind: str, *, date_col: str, store_col: str,
             value_col: str, expect_stores: int | None = None,
             today: pd.Timestamp | None = None) -> Report:
    """Check a cleaned frame against what we know and what we last saw."""
    today = pd.Timestamp.today().normalize() if today is None else pd.Timestamp(today)
    rep = Report(kind=kind)

    if df is None or df.empty:
        rep.problems.append("the feed came back empty — no rows at all")
        return rep
    for col in (date_col, store_col, value_col):
        if col not in df.columns:
            rep.problems.append(f"the feed has no '{col}' column after cleaning")
    if rep.problems:
        return rep

    f = fingerprint(df, date_col=date_col, store_col=store_col, value_col=value_col)
    rep.facts = f
    base = _state().get(kind)
    rep.baseline = base

    if f["max_date"] is None:
        rep.problems.append("not one row carries a readable date")
    elif pd.Timestamp(f["max_date"]) > today:
        rep.problems.append(
            f"the latest date is {f['max_date']}, which is in the future — "
            "the day/month order is probably being read the wrong way round")

    if base and base.get("rows"):
        frac = f["rows"] / base["rows"]
        if frac < MIN_ROW_FRACTION:
            rep.problems.append(
                f"the feed lost {(1 - frac) * 100:,.0f}% of its rows since the "
                f"last good load — {f['rows']:,} now against {base['rows']:,} "
                "before. A truncated export looks exactly like this.")

    # ---- warnings: real, but not always wrong -------------------------------
    if f["max_date"]:
        age = (today - pd.Timestamp(f["max_date"])).days
        if age >= 2:
            rep.warnings.append(
                f"the newest data is {age} days old ({f['max_date']}) — the "
                "sheet may not have been updated")
    if expect_stores is not None and f["stores"] < expect_stores:
        rep.warnings.append(
            f"{f['stores']} stores are reporting, against {expect_stores} open "
            "in the store master — someone may be missing from the export")
    if base:
        lost = (base.get("stores") or 0) - f["stores"]
        if lost >= STORE_DROP_WARN:
            rep.warnings.append(
                f"{lost} store(s) stopped appearing since the last load "
                f"({base['stores']} → {f['stores']})")
        b_tot = base.get("total") or 0
        if b_tot and abs(f["total"] - b_tot) / b_tot > TOTAL_SWING_WARN:
            rep.warnings.append(
                f"the feed's total moved {(f['total'] / b_tot - 1) * 100:+,.1f}% "
                "since the last load")

    if rep.ok:
        _save(kind, f)
    return rep
