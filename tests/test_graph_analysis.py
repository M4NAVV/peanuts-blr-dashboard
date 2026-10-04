"""Graph analysis VFL — the rules that decide its dates and its target line.

Frames and tabs are built here, so these run in CI with no feed —
see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import graph_analysis as GA


def _tab(rows):
    cols = ["FY 2026-2027", "u1", "FY 2025-2026", "u3", "Tenure1", "Tenure2", "Region",
            "Seen in last year's sales"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows], columns=cols, dtype=object)


DRAFT = _tab([
    ["Durga Puja / Dussehra (Vijayadashami): Tuesday, October 20, 2026", None,
     "Durga Puja / Dussehra (Vijayadashami): Thu, October 02, 2025", None, "45 days", "30 Days", "All", "East 2.2x"],
    ["Ganesh Chaturthi: Monday, September 14, 2026", None,
     "Ganesh Chaturthi: Wednesday, August 27, 2025", None, None, None, "South", "South 1.8x"],
    ["Akshaya Tritiya: Monday, April 20, 2026", None,
     "Akshaya Tritiya: Wednesday, April 30, 2025", None, None, None, "All", "South 2.2x"],
])


def _festivals(monkeypatch, live):
    monkeypatch.setattr(GA.os.path, "exists", lambda p: True)
    monkeypatch.setattr(GA.F, "_url", lambda: "live")
    monkeypatch.setattr(GA.pd, "read_csv", lambda src, dtype=None: live if src == "live" else DRAFT)
    return {f["name"].split()[0]: f for f in GA.festivals()}


def test_the_live_sheet_wins_where_it_has_both_years(monkeypatch):
    """Pasting confirmed dates into the sheet must take effect with no code change."""
    live = _tab([["Akshaya Tritiya: Sunday, April 19, 2026", None,
                  "Akshaya Tritiya: Wednesday, April 30, 2025", None, None, None, None, None]])
    f = _festivals(monkeypatch, live)
    assert f["Akshaya"]["ty"] == pd.Timestamp("2026-04-19")        # the sheet's date, not the draft's 20th
    assert f["Akshaya"]["region"] == "All"                          # region still from the draft
    assert f["Ganesh"]["ty"] == pd.Timestamp("2026-09-14")          # untouched rows keep the draft


def test_a_live_row_with_one_year_does_not_override(monkeypatch):
    live = _tab([["Ganesh Chaturthi: Tuesday, September 15, 2026", None, None, None, None, None, None, None]])
    f = _festivals(monkeypatch, live)
    assert f["Ganesh"]["ty"] == pd.Timestamp("2026-09-14")


def test_the_shift_is_measured_on_this_years_calendar(monkeypatch):
    f = _festivals(monkeypatch, _tab([]))
    assert f["Durga"]["shift"] == 18                                # 2 Oct 2025 -> 20 Oct 2026
    assert f["Akshaya"]["shift"] == -10


def test_a_takeover_months_target_is_spread_only_over_the_days_after_it(monkeypatch):
    """South's April target covers 19-30 April, not all thirty days."""
    monkeypatch.setattr(GA, "FY0", pd.Timestamp("2026-04-01"))
    monkeypatch.setattr(GA, "FY1", pd.Timestamp("2027-03-31"))
    monkeypatch.setattr(GA, "MONTHLY", {112: [120000.0, 310000.0] + [None] * 10})
    s = GA.daily_target([112], [pd.Timestamp("2026-04-19")])
    assert s[pd.Timestamp("2026-04-10")] == 0                       # before the takeover: nothing due
    assert s[pd.Timestamp("2026-04-19")] == pytest.approx(120000 / 12)
    assert s[pd.Timestamp("2026-05-10")] == pytest.approx(310000 / 31)
    assert pd.isna(s[pd.Timestamp("2026-06-10")])                   # a blank month stays blank


def test_one_stores_blank_month_blanks_the_total(monkeypatch):
    monkeypatch.setattr(GA, "FY0", pd.Timestamp("2026-04-01"))
    monkeypatch.setattr(GA, "FY1", pd.Timestamp("2027-03-31"))
    monkeypatch.setattr(GA, "MONTHLY", {1: [30000.0] * 12, 2: [30000.0] + [None] * 11})
    s = GA.daily_target([1, 2], [pd.Timestamp("2026-04-01")] * 2)
    assert s[pd.Timestamp("2026-04-15")] == pytest.approx(2000)
    assert pd.isna(s[pd.Timestamp("2026-05-15")])                   # never an understated total
