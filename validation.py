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
JSON file beside the process. It is per-container and resets on redeploy.

★ WHICH IS WHY IT CANNOT BE THE ONLY REFERENCE (16 Aug). An audit found the file
absent — so the row-collapse refusal, the check written for the 265k→143k
incident, could not fire at all. Worse, the first load after a restart became the
baseline whatever it contained: a truncated feed would be accepted AND adopted as
the reference, so the next healthy load read as a jump rather than a recovery.
The Space restarts often, so "the first load after a restart" is the common case,
not the rare one.

Two things close that gap, neither of which needs state to survive a deploy:

  A FLOOR THAT IS ALWAYS THERE. The committed snapshot in the repo is a known
  good shape of the same feed, so it can stand in when nothing is remembered.
  These sheets are append-only in practice, so a live feed materially smaller
  than a snapshot taken weeks ago is not a feed we should serve.

  A CHECK THAT NEEDS NO MEMORY AT ALL. Ask the frame about itself: a store that
  reported all month and has reported nothing for a week has either closed —
  which the master would say — or fallen out of the export. That is the incident
  the row count cannot see, because three stores missing from fifty-three is a
  5% change in rows and every tolerance has to be wider than that.
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

# A committed snapshot of the same feed, used as the reference when nothing is
# remembered. Only the portfolio feed has one; the VFL feed says so rather than
# pretending it is covered.
_FLOORS = {"portfolio": "portfolio_snapshot.csv"}
# How long a store may be absent before it is worth mentioning. Seven days is
# comfortably past a quiet week for the smallest VFL store: measured over a year
# of both feeds, this fires on nothing but stores that had genuinely stopped.
STOPPED_DAYS = 7


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


def _floor(kind: str) -> dict | None:
    """The committed snapshot's shape — a reference that survives a redeploy.

    Counted by lines rather than parsed: this runs on every load, the file is a
    megabyte, and the only figure wanted is how many rows a healthy feed had.
    """
    name = _FLOORS.get(kind)
    if not name:
        return None
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            rows = sum(1 for _ in f) - 1          # less the header
    except Exception:
        return None
    return {"rows": rows, "source": name} if rows > 0 else None


def _closed_codes() -> set:
    """Stores the master says have shut, so they are not reported as missing.

    Read defensively: this is a courtesy to the message, not a check of its own,
    and a master that cannot be reached must not stop the feed being validated.
    """
    try:
        import master_lookup
        return {str(c) for c in master_lookup.closed()}
    except Exception:
        return set()


def _has_history(df: pd.DataFrame, date_col: str,
                 days: int = STOPPED_DAYS + 28) -> bool:
    """Enough of a span for the per-store checks to mean anything."""
    if df is None or df.empty or date_col not in df:
        return False
    d = pd.to_datetime(df[date_col], errors="coerce").dropna()
    return not d.empty and (d.max() - d.min()).days >= days


def _open_codes() -> set:
    """Stores the master says are trading — as a SET, not a count.

    A count cannot answer this question. The portfolio sheet keeps zero-rows for
    a shut store indefinitely, so 53 codes appear in the feed against 50 open in
    the master, and three open stores could vanish from the export without the
    total ever dropping below the expected number. Only naming them works.
    """
    try:
        import master_lookup
        m = master_lookup._read()
        if m is None or "_code" not in m:
            return set()
        codes = {int(c) for c in m["_code"] if str(c).strip().isdigit()}
        return codes - {int(c) for c in master_lookup.closed()} \
            - set(master_lookup.NON_STORE_CODES)
    except Exception:
        return set()


def missing_open_stores(df: pd.DataFrame, *, date_col: str, store_col: str,
                        days: int = STOPPED_DAYS) -> list:
    """Stores the master calls open that are absent from the recent window.

    Catches the shape `stopped_reporting` cannot: a store dropped from the
    export ENTIRELY, history and all, which leaves no trace inside the frame to
    compare against. Only meaningful for a code-keyed feed, so it stands down
    when the store column plainly is not codes.
    """
    want = _open_codes()
    if not want or df is None or df.empty or store_col not in df:
        return []
    have_all = set(pd.to_numeric(df[store_col], errors="coerce").dropna().astype(int))
    if not (have_all & want):
        return []                      # not a code-keyed feed — nothing to say
    d = pd.to_datetime(df[date_col], errors="coerce")
    end = d.max()
    if pd.isna(end):
        return []
    recent = df[d > end - pd.Timedelta(days=days)]
    have = set(pd.to_numeric(recent[store_col], errors="coerce").dropna().astype(int))
    return sorted(want - have)


def stopped_reporting(df: pd.DataFrame, *, date_col: str, store_col: str,
                      days: int = STOPPED_DAYS) -> list:
    """Stores that were reporting a month ago and have reported nothing since.

    Needs no baseline and no memory: the comparison is between two windows of
    the frame in front of it, which is what makes it work on the first load
    after a restart — the case the remembered baseline cannot cover.

    Stores with a recorded closure are excluded. Run against a year of history
    this fires on nothing else: its one hit was April, and it was right — ten
    stores had genuinely stopped, every one of them since dated in the master.
    """
    if df is None or df.empty or date_col not in df or store_col not in df:
        return []
    d = pd.to_datetime(df[date_col], errors="coerce")
    end = d.max()
    if pd.isna(end):
        return []
    recent = df[d > end - pd.Timedelta(days=days)]
    prior = df[(d <= end - pd.Timedelta(days=days))
               & (d > end - pd.Timedelta(days=days + 28))]
    if prior.empty:
        return []
    gone = set(prior[store_col].astype(str)) - set(recent[store_col].astype(str))
    return sorted(gone - _closed_codes())


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

    # The collapse check runs against the last good load when there is one, and
    # against the committed snapshot when there is not — so a fresh container is
    # no longer unguarded. Both are named in the message: "smaller than the
    # snapshot in the repo" and "smaller than an hour ago" mean different things.
    floor = _floor(kind)
    ref, ref_name = ((base, "the last good load") if base and base.get("rows")
                     else (floor, f"the committed {floor['source']}") if floor
                     else (None, None))
    if ref and ref.get("rows"):
        frac = f["rows"] / ref["rows"]
        if frac < MIN_ROW_FRACTION:
            rep.problems.append(
                f"the feed lost {(1 - frac) * 100:,.0f}% of its rows against "
                f"{ref_name} — {f['rows']:,} now against {ref['rows']:,}. "
                "A truncated export looks exactly like this.")
    elif not ref and not _has_history(df, date_col):
        # Never silently skip every check. Said only when nothing could run: with
        # no reference AND too little history for the per-store comparison, this
        # frame is genuinely unverified, and that must not look like a clean bill
        # of health. A feed carrying its own history is covered by the checks
        # below and stays quiet — the VFL feed has no committed snapshot and
        # needs no banner every time the container restarts.
        rep.warnings.append(
            f"nothing could verify this load: no earlier load in this container, "
            f"no committed snapshot for the {kind} feed, and too little history "
            "in the frame itself to compare one week against the last month")

    # ---- warnings: real, but not always wrong -------------------------------
    if f["max_date"]:
        age = (today - pd.Timestamp(f["max_date"])).days
        if age >= 2:
            rep.warnings.append(
                f"the newest data is {age} days old ({f['max_date']}) — the "
                "sheet may not have been updated")
    # The check that needs no memory, and the one that catches the shape the row
    # count cannot: a handful of stores missing from an export.
    stopped = stopped_reporting(df, date_col=date_col, store_col=store_col)
    if stopped:
        shown = ", ".join(str(s) for s in stopped[:6])
        more = f" and {len(stopped) - 6} more" if len(stopped) > 6 else ""
        rep.warnings.append(
            f"{len(stopped)} store(s) reported through last month and nothing in "
            f"the last {STOPPED_DAYS} days — {shown}{more}. Either they have "
            "closed and the master does not say so, or they have fallen out of "
            "the export.")
    missing = missing_open_stores(df, date_col=date_col, store_col=store_col)
    if missing:
        shown = ", ".join(str(s) for s in missing[:8])
        more = f" and {len(missing) - 8} more" if len(missing) > 8 else ""
        rep.warnings.append(
            f"{len(missing)} store(s) the master calls OPEN sent nothing in the "
            f"last {STOPPED_DAYS} days — {shown}{more}. A store missing from the "
            "export looks exactly like this.")
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
