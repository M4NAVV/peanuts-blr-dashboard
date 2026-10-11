"""Price brackets on a ROLLING basis — the sample for the admin (Manav, 11 Oct 2026).

*"Replace MTD and YTD with rolling 7, 30 and 90 days, each against the same days last year …
build this separately as a sample, will get it approved and then go live."* So: a mode the
picker does NOT offer, and the live price / category / brand reports untouched.
"""
from pathlib import Path
from types import SimpleNamespace as NS

import pandas as pd

import category_pdf as C
import loader as L


def _feed(monkeypatch, takeover=None):
    monkeypatch.setattr(L, "takeover_map", lambda: {"Jayanagar": pd.Timestamp(takeover)}
                        if takeover else {})
    monkeypatch.setattr(L, "closure_cutoffs", lambda asof: {})
    days = pd.date_range("2025-04-01", "2026-10-07")
    return pd.DataFrame({"date": days, L.COL_STORE_LABEL: "Jayanagar", L.COL_AMOUNT: 1.0})


def test_each_window_is_n_days_against_the_same_dates_last_year(monkeypatch):
    df = _feed(monkeypatch)
    for n in C.ROLLING:
        ty, ly = C.rolling_frames(df, "2026-10-07", n)
        assert len(ty) == n and len(ly) == n
        assert ty["date"].min() == pd.Timestamp("2026-10-07") - pd.Timedelta(days=n - 1)
        assert ly["date"].max() == pd.Timestamp("2025-10-07")


def test_a_window_never_starts_before_the_takeover(monkeypatch):
    """★ South's year starts 19 Apr — a 90-day window on 1 Jun must not reach back past it."""
    df = _feed(monkeypatch, takeover="2026-04-19")
    ty, ly = C.rolling_frames(df, "2026-06-01", 90)
    assert ty["date"].min() == pd.Timestamp("2026-04-19")
    assert ly["date"].min() == pd.Timestamp("2025-04-19") and len(ty) == len(ly)


def _w(fest, ty, ly):
    return NS(festival=fest, ty_end=pd.Timestamp(ty), ly_end=pd.Timestamp(ly))


def test_a_festival_on_one_side_only_is_named_once():
    ws = [_w("Durga Puja", "2026-10-20", "2025-10-02"), _w("Durga Puja", "2026-10-20", "2025-10-02")]
    notes = C.festival_shifts(pd.Timestamp("2026-10-07"), windows_=ws)
    assert notes == ["Durga Puja (02 Oct 2025 last year, 20 Oct 2026 this year) falls inside "
                     "last year's 7, 30, 90 and 120 days only"]


def test_a_festival_in_both_windows_is_not_a_shift():
    ws = [_w("Independence Day", "2026-08-15", "2025-08-15")]
    assert C.festival_shifts(pd.Timestamp("2026-08-20"), windows_=ws) == []


def test_his_columns_replace_mtd_and_ytd():
    keys = [k for k, _, _ in C._spec(False, "rolling")]
    for n in C.ROLLING:
        assert [f"R{n}_ty", f"R{n}_ly", f"R{n}_gda", f"R{n}_gd"] == keys[keys.index(f"R{n}_ty"):][:4]
    assert not any(k.startswith(("MTD", "YTD", "TTM")) for k in keys)
    assert "share" in keys and "share_chg" in keys
    assert C.ROLLING == (7, 30, 90, 120)
    assert keys.count("cat") == 1          # no repeated name on the right (11 Oct)


def test_it_is_a_sample_not_in_the_picker():
    src = Path("app.py").read_text()
    assert 'mode="rolling"' not in src and "'rolling'" not in src
    assert 'mode="rolling"' in Path("scripts_price_rolling.py").read_text()


def test_the_live_modes_still_read_mtd_and_ytd():
    assert [k for k, _, _ in C._spec(False, "price")][1:3] == ["MTD_ty", "MTD_ly"]
    assert C.windows.__code__.co_varnames[:5] == ("df", "asof", "w", "ttm", "rolling")
