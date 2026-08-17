"""The gate must still work on the first load after a restart.

Its strongest check compared against the last good load, remembered in a file
under the system temp directory — per container, wiped on every redeploy. An
audit found no such file, so the row-collapse refusal could not fire at all, and
the Space restarts often enough that "the first load after a restart" is the
common case. Worse, a truncated feed loaded with no baseline passed AND became
the baseline, so the next healthy load read as a jump.

Two references now cover that: the committed snapshot in the repo, which
survives a redeploy, and two per-store checks that need no memory whatever.

Runs on synthetic frames with the state file redirected — no sheet, no network:

    python tests/test_gate_baseline.py        (or: python -m pytest tests -q)
"""

import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import validation as V                 # noqa: E402

KW = dict(date_col="date", store_col="code", value_col="sales",
          today=pd.Timestamp(2026, 8, 14))   # the frames end here
END = pd.Timestamp(2026, 8, 14)


def _fresh_container():
    """No remembered baseline, and a state file this test owns."""
    V._STATE = os.path.join(tempfile.mkdtemp(), "state.json")


def _frame(codes=range(9201, 9211), start="2026-01-01", end=END):
    rows = [{"date": d, "code": c, "sales": 1_000.0}
            for c in codes for d in pd.date_range(start, end, freq="D")]
    return pd.DataFrame(rows)


def test_a_truncated_feed_is_refused_with_no_baseline_at_all():
    """The case that used to be served: nothing remembered, half the rows gone."""
    _fresh_container()
    full = _frame()
    # Stand a floor in for the committed snapshot, as the repo does for portfolio.
    V._floor_original = V._floor
    V._floor = lambda kind: {"rows": len(full), "source": "committed snapshot"}
    try:
        rep = V.validate(full.sample(frac=0.4, random_state=1), "synthetic", **KW)
        assert rep.problems, "a 60% loss must be refused even with no last load"
        assert "committed snapshot" in rep.problems[0]
    finally:
        V._floor = V._floor_original


def test_a_feed_nothing_could_verify_says_so_rather_than_passing_quietly():
    """No reference AND too little history for the per-store checks."""
    _fresh_container()
    V._floor_original = V._floor
    V._floor = lambda kind: None
    try:
        one_day = _frame(start=END, end=END)
        rep = V.validate(one_day, "synthetic", **KW)
        assert not rep.problems
        assert any("nothing could verify" in w for w in rep.warnings), \
            "a load that nothing could check must not look like a clean one"
    finally:
        V._floor = V._floor_original


def test_a_feed_carrying_its_own_history_stays_quiet_without_a_reference():
    """The VFL feed's case: no committed snapshot, but the per-store checks run,
    so a restart must not put a banner on the page every time."""
    _fresh_container()
    V._floor_original = V._floor
    V._floor = lambda kind: None
    try:
        rep = V.validate(_frame(), "synthetic", **KW)
        assert not rep.problems and not rep.warnings, rep.warnings
    finally:
        V._floor = V._floor_original


def test_a_store_that_stops_appearing_is_named():
    """Needs no baseline: two windows of the same frame."""
    _fresh_container()
    df = _frame()
    gone = 9201
    df = df[~((df["code"] == gone) & (df["date"] > END - pd.Timedelta(days=10)))]
    stopped = V.stopped_reporting(df, date_col="date", store_col="code")
    assert str(gone) in stopped


def test_a_store_quiet_for_only_two_days_is_not_named():
    """The check must survive an ordinary quiet weekend."""
    _fresh_container()
    df = _frame()
    df = df[~((df["code"] == 9201) & (df["date"] > END - pd.Timedelta(days=2)))]
    assert V.stopped_reporting(df, date_col="date", store_col="code") == []


def test_a_healthy_feed_raises_nothing():
    _fresh_container()
    V._floor_original = V._floor
    V._floor = lambda kind: {"rows": 10, "source": "committed snapshot"}
    try:
        rep = V.validate(_frame(), "synthetic", **KW)
        assert not rep.problems
        assert not any("stopped" in w or "OPEN" in w for w in rep.warnings)
    finally:
        V._floor = V._floor_original


def test_the_repo_snapshot_is_a_usable_floor():
    """The portfolio feed's restart-proof reference actually resolves."""
    f = V._floor("portfolio")
    assert f and f["rows"] > 1000, "the committed snapshot should be readable"
    assert V._floor("vfl") is None, "and the VFL feed has none, which it says"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all gate-baseline tests passed")
