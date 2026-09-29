"""Festive packs follow the date picker.

Manav, 29 Sep 2026: *"the festive sheets we make are not working with the date
picker, so if i choose a previous day, it doesnt show data only until then."*

The windows were built once, for TODAY, so a back-dated pack still ran to
today. `festive.at` re-dates a window; these pin what that has to mean.
Frames are built here — see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import festive as F
import festive_admin as FADM

TY_END = pd.Timestamp("2026-10-20")
LY_END = pd.Timestamp("2025-10-02")
TENURE = 45
TY_START = TY_END - pd.Timedelta(days=TENURE - 1)       # 6 Sep 2026
LY_START = LY_END - pd.Timedelta(days=TENURE - 1)       # 19 Aug 2025


def _today_window():
    """What the cached tab gives: dated for 'today', 29 Sep."""
    return F.Window(festival="Durga Puja", tenure=TENURE,
                    ty_start=TY_START, ty_end=TY_END,
                    ly_start=LY_START, ly_end=LY_END,
                    elapsed=24, asof=pd.Timestamp("2026-09-29"))


def _pf():
    """One store selling Rs 1,000 every day of both years' windows."""
    days = (list(pd.date_range(LY_START, LY_END))
            + list(pd.date_range(TY_START, pd.Timestamp("2026-09-29"))))
    return pd.DataFrame({"code": 112, "date": days, "sales": 1000.0})


def test_a_picked_day_moves_the_whole_window():
    w = F.at(_today_window(), "2026-09-20")
    assert w.asof == pd.Timestamp("2026-09-20")
    assert w.elapsed == 15                                # 6 → 20 Sep
    assert w.ty_cut == pd.Timestamp("2026-09-20")
    assert w.ly_cut == LY_START + pd.Timedelta(days=14)   # same 15 days last year


def test_the_figures_stop_at_the_picked_day():
    """★ The bug itself: a pack dated 20 Sep carried sales up to the 29th."""
    today = FADM.figures_for(_pf(), [112], _today_window())
    back = FADM.figures_for(_pf(), [112], F.at(_today_window(), "2026-09-20"))
    assert today["ty"] == 24000
    assert back["ty"] == 15000
    assert back["ly"] == 15000                            # like-for-like follows
    assert back["ly_full"] == today["ly_full"] == 45000   # last year's whole run
    assert back["ty_days"].index.max() == pd.Timestamp("2026-09-20")


def test_a_day_before_the_run_up_opens_is_not_started():
    w = F.at(_today_window(), "2026-09-01")
    assert w.elapsed == 0 and not w.started


def test_a_day_after_it_closes_is_the_whole_window():
    w = F.at(_today_window(), "2026-11-05")
    assert w.elapsed == TENURE and w.ty_cut == TY_END


def test_re_dating_does_not_change_the_festival():
    a, b = _today_window(), F.at(_today_window(), "2026-09-20")
    for k in ("festival", "tenure", "ty_start", "ty_end", "ly_start", "ly_end"):
        assert getattr(a, k) == getattr(b, k)
