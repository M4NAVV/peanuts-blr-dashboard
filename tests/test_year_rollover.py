"""The two things that were going to break on 1 April 2027, silently.

Both were on the fragility audit's "dated time bombs" list: no error, no code
change, just wrong figures on a date that has not arrived yet. Neither could be
noticed by looking at the screen, which is why they are pinned here instead.

  1. `targets.for_month(2027-04-15)` returned FY26-27's targets — 53 stores,
     unlabelled — so every achievement would have been measured against last
     year's ask.
  2. `festive.festive_windows(2027-08-19)` returned the 2026 festivals, with
     Durga Puja reading "day 45 of 45", complete, and `last_problem()` None.

Both now refuse and say why. These tests build their own inputs, so CI runs
them without the feed — see the note in test_vfl_l2l_split.py.
"""

import json

import pandas as pd
import pytest

import festive as F
import targets as TG


# --------------------------------------------------------------------------- #
# Targets — the tab carries no year, so a committed marker supplies one
# --------------------------------------------------------------------------- #

def _targets(codes=(107, 112), bump=0.0):
    return pd.DataFrame([
        {"code": c, "year": 10_000_000 + bump,
         **{m: (1_000_000 + bump if m in ("Apr", "May") else float("nan"))
            for m in TG._MONTHS}}
        for c in codes])


def _marker(tmp_path, monkeypatch, fy, fingerprint):
    p = tmp_path / "targets_fy.json"
    p.write_text(json.dumps({"fy": fy, "fingerprint": fingerprint}))
    monkeypatch.setattr(TG, "_marker_path", lambda: str(p))


def test_targets_inside_their_own_year_are_fine(tmp_path, monkeypatch):
    t = _targets()
    _marker(tmp_path, monkeypatch, 2026, TG._fingerprint(t))
    assert TG.fiscal_year_problem(t, pd.Timestamp("2026-08-19")) is None
    # A January date is still FY2026-27 — the fiscal year, not the calendar one.
    assert TG.fiscal_year_problem(t, pd.Timestamp("2027-01-15")) is None


def test_unchanged_targets_are_refused_once_the_year_rolls(tmp_path, monkeypatch):
    """★ The bomb itself: same numbers, new fiscal year."""
    t = _targets()
    _marker(tmp_path, monkeypatch, 2026, TG._fingerprint(t))
    why = TG.fiscal_year_problem(t, pd.Timestamp("2027-04-15"))
    assert why and "LAST YEAR" in why and "2027-28" in why


def test_targets_that_were_updated_are_accepted(tmp_path, monkeypatch):
    """When the team does paste new figures the warning must stop by itself,
    or it becomes noise everyone learns to ignore."""
    _marker(tmp_path, monkeypatch, 2026, TG._fingerprint(_targets()))
    assert TG.fiscal_year_problem(_targets(bump=1.0),
                                  pd.Timestamp("2027-04-15")) is None


def test_no_marker_means_no_claim(tmp_path, monkeypatch):
    """Absent a reference, say nothing — a guess is worse than silence here."""
    monkeypatch.setattr(TG, "_marker_path", lambda: str(tmp_path / "absent.json"))
    assert TG.fiscal_year_problem(_targets(), pd.Timestamp("2027-04-15")) is None


# --------------------------------------------------------------------------- #
# Festive — the dates carry their own year, so the tab can be asked
# --------------------------------------------------------------------------- #

def _festive_tab(tmp_path, year=2026):
    p = tmp_path / "festive.csv"
    p.write_text(
        "This year,x,Last year,Tenure1,Tenure2\n"
        f'"Durga Puja: Tuesday, October 20, {year}",,'
        f'"Durga Puja: Thursday, October 2, {year - 1}",45 days,30 days\n')
    return str(p)


def test_this_season_is_served(tmp_path):
    ws = F.festive_windows(pd.Timestamp(f"{2026}-08-19"),
                           url=_festive_tab(tmp_path, 2026))
    assert len(ws) == 2 and F.last_problem() is None
    assert {w.tenure for w in ws} == {30, 45}


def test_a_finished_season_is_refused_and_named(tmp_path):
    """★ The bomb: read a year later it used to return the old windows as
    complete. Nothing may be returned, and the tab must be named."""
    ws = F.festive_windows(pd.Timestamp("2027-08-19"),
                           url=_festive_tab(tmp_path, 2026))
    assert ws == []
    why = F.last_problem()
    assert why and "2026" in why and "rolled forward" in why


def test_the_new_season_is_served_once_the_tab_is_rolled(tmp_path):
    ws = F.festive_windows(pd.Timestamp("2027-08-19"),
                           url=_festive_tab(tmp_path, 2027))
    assert len(ws) == 2 and F.last_problem() is None


def test_the_fiscal_year_boundary_is_1_april(tmp_path):
    """A February date still belongs to the season that opened in October."""
    ws = F.festive_windows(pd.Timestamp("2027-02-10"),
                           url=_festive_tab(tmp_path, 2026))
    assert len(ws) == 2, "October 2026 is inside FY2026-27"
