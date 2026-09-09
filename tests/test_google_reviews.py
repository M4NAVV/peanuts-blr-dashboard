"""Reviews read from Google, not typed.

★ WHAT THESE PIN. The count is DERIVED — a running total's day-on-day change —
so three things must hold or the numbers are quietly wrong: the first reading
must not become a day's count, a missed day must not be attributed to one day,
and a store that cannot be told apart from its neighbour must be left out
rather than guessed.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import google_reviews as G


def _snap(tmp_path, rows):
    p = tmp_path / "snap.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return str(p)


def test_the_first_reading_is_a_level_not_a_days_reviews():
    """It is the store's whole history. Counted as one day it would credit the
    largest store with over twenty thousand reviews in an afternoon."""
    p = _snap(pytest.importorskip("pathlib") and Path("/tmp"), [
        {"date": "2026-08-22", "store": "A", "total_reviews": 20783},
    ])
    d = G.daily_reviews(p)
    assert d.empty


def test_a_days_reviews_is_the_change_between_readings(tmp_path):
    p = _snap(tmp_path, [
        {"date": "2026-08-22", "store": "A", "total_reviews": 100},
        {"date": "2026-08-23", "store": "A", "total_reviews": 107},
    ])
    d = G.daily_reviews(p)
    assert len(d) == 1
    assert d.iloc[0]["reviews"] == 7
    assert d.iloc[0]["days_covered"] == 1


def test_a_missed_day_records_the_span_it_actually_covers(tmp_path):
    """Three days' reviews must not read as one enormous day."""
    p = _snap(tmp_path, [
        {"date": "2026-08-20", "store": "A", "total_reviews": 100},
        {"date": "2026-08-23", "store": "A", "total_reviews": 112},
    ])
    d = G.daily_reviews(p)
    # ★ THE TEST'S OWN INTENT, NOW ACTUALLY ENFORCED. It used to assert that the
    # whole 12 landed on 23 Aug with `days_covered=3` beside it — which IS three
    # days reading as one enormous day, the thing the docstring forbids, and
    # nothing downstream ever looked at `days_covered`. The gain is now spread
    # across the days it covers and flagged as estimated. The total is unchanged.
    assert len(d) == 3
    assert sorted(f"{x:%d}" for x in d["date"]) == ["21", "22", "23"]
    assert d["reviews"].sum() == 12
    assert (d["reviews"] == 4).all()
    assert d["estimated"].all()
    # The span is now carried as three ROWS, so each one covers a single day.
    # A downstream window can pair each against that day's bills; a
    # `days_covered=3` on one row could not be paired with anything.
    assert (d["days_covered"] == 1).all()


def test_a_deleted_review_reads_as_zero_gained_not_as_minus_one(tmp_path):
    """A count can fall only by deletion. Negative reviews are not a thing a
    manager can act on, and would net off a real day elsewhere."""
    p = _snap(tmp_path, [
        {"date": "2026-08-22", "store": "A", "total_reviews": 100},
        {"date": "2026-08-23", "store": "A", "total_reviews": 98},
    ])
    assert G.daily_reviews(p).iloc[0]["reviews"] == 0


def test_each_store_is_differenced_against_its_own_history(tmp_path):
    p = _snap(tmp_path, [
        {"date": "2026-08-22", "store": "A", "total_reviews": 100},
        {"date": "2026-08-22", "store": "B", "total_reviews": 900},
        {"date": "2026-08-23", "store": "A", "total_reviews": 105},
        {"date": "2026-08-23", "store": "B", "total_reviews": 902},
    ])
    d = G.daily_reviews(p).set_index("store")
    assert d.loc["A", "reviews"] == 5
    assert d.loc["B", "reviews"] == 2


def test_a_repeated_reading_on_one_day_keeps_the_last(tmp_path):
    p = tmp_path / "s.csv"
    G.append_snapshot(pd.DataFrame([
        {"date": "2026-08-22", "store": "A", "total_reviews": 100}]), str(p))
    G.append_snapshot(pd.DataFrame([
        {"date": "2026-08-22", "store": "A", "total_reviews": 101}]), str(p))
    d = pd.read_csv(p)
    assert len(d) == 1 and d.iloc[0]["total_reviews"] == 101


def test_no_key_refuses_rather_than_returning_zero(monkeypatch):
    """A zero would read as 'nobody reviewed today' on every store at once, so
    a missing key must raise rather than return."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    class _NoSecrets:
        @staticmethod
        def get(_k):
            return None

    import types
    fake = types.SimpleNamespace(secrets=_NoSecrets())
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    with pytest.raises(G.NoKey, match="gitignored"):
        G._key()


def test_the_resolved_store_list_has_no_shared_listing():
    """Two stores on one listing would credit one shop's reviews to another.
    Kamraj Road and Grand Kamraj Road are 71 m apart and Google carries a single
    listing for them, so both are deliberately absent."""
    p = G.load_places()
    if p.empty:
        pytest.skip("no resolved stores on this machine")
    assert p["place_id"].is_unique
