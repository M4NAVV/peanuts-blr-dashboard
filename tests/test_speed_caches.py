"""The 30 Oct 2026 speed-up must make the dashboard faster and nothing else.

Three short-lived memories were added: the store master tab (10 minutes), the data check (per load), and the bill
sheet fetched alongside the portfolio sheet. These pin the rules that keep them from making anything fragile:
a failure is never remembered, a memory expires, a caller cannot spoil the shared copy, and a different load is
always checked afresh.
"""
import pandas as pd
import pytest

import master_lookup as ML
import validation as V


@pytest.fixture(autouse=True)
def _fresh():
    ML.clear_cache(); V.clear_cache()
    yield
    ML.clear_cache(); V.clear_cache()


def _master():
    return pd.DataFrame({"STORE CODE": ["107", "108"], "CARPET": ["22363", "7870"], "CLOSURE DATE": ["", ""]})


def test_master_is_downloaded_once_then_remembered(monkeypatch):
    calls = []
    monkeypatch.setattr(ML.pd, "read_csv", lambda url, dtype=None: calls.append(url) or _master())
    ML._fetch("u"); ML._fetch("u"); ML._fetch("u")
    assert calls == ["u"]


def test_a_failed_download_is_never_remembered(monkeypatch):
    state = {"n": 0}

    def flaky(url, dtype=None):
        state["n"] += 1
        if state["n"] == 1:
            raise ConnectionError("Google did not answer")
        return _master()
    monkeypatch.setattr(ML.pd, "read_csv", flaky)
    with pytest.raises(ConnectionError):
        ML._fetch("u")
    assert len(ML._fetch("u")) == 2          # the next call simply tries again
    assert state["n"] == 2


def test_the_memory_expires(monkeypatch):
    calls = []
    monkeypatch.setattr(ML.pd, "read_csv", lambda url, dtype=None: calls.append(url) or _master())
    now = [1000.0]
    monkeypatch.setattr(ML._time, "monotonic", lambda: now[0])
    ML._fetch("u")
    now[0] += ML._TTL - 1
    ML._fetch("u")
    now[0] += 2                                # past ten minutes: read again
    ML._fetch("u")
    assert len(calls) == 2


def test_a_caller_cannot_spoil_the_shared_copy(monkeypatch):
    monkeypatch.setattr(ML.pd, "read_csv", lambda url, dtype=None: _master())
    a = ML._fetch("u")
    a["STORE CODE"] = "999"; a.drop(columns=["CARPET"], inplace=True)
    b = ML._fetch("u")
    assert list(b["STORE CODE"]) == ["107", "108"] and "CARPET" in b.columns


def test_read_one_still_reports_why_it_failed(monkeypatch):
    def boom(url, dtype=None):
        raise TimeoutError("slow")
    monkeypatch.setattr(ML.pd, "read_csv", boom)
    assert ML._read_one("u") is None
    assert "could not read the master tab" in ML.last_problem()


def _feed(n=40, total=100.0):
    d = pd.date_range("2026-09-01", periods=n, freq="D")
    return pd.DataFrame({"date": d, "store": ["A", "B"] * (n // 2), "sales": [total / n] * n})


def test_the_check_is_remembered_for_the_same_data(monkeypatch):
    calls = []
    real = V.validate
    monkeypatch.setattr(V, "validate", lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(V, "_save", lambda *a, **k: None)
    df = _feed()
    r1 = V.validate_cached(df, "t", date_col="date", store_col="store", value_col="sales")
    r2 = V.validate_cached(df.copy(), "t", date_col="date", store_col="store", value_col="sales")
    assert r1 is r2 and len(calls) == 1


def test_a_different_load_is_checked_afresh(monkeypatch):
    calls = []
    real = V.validate
    monkeypatch.setattr(V, "validate", lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(V, "_save", lambda *a, **k: None)
    V.validate_cached(_feed(), "t", date_col="date", store_col="store", value_col="sales")
    V.validate_cached(_feed(total=250.0), "t", date_col="date", store_col="store", value_col="sales")   # new total
    V.validate_cached(_feed(n=42), "t", date_col="date", store_col="store", value_col="sales")          # new rows
    assert len(calls) == 3


def test_an_empty_or_broken_feed_is_never_keyed(monkeypatch):
    calls = []
    real = V.validate
    monkeypatch.setattr(V, "validate", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(2):
        rep = V.validate_cached(pd.DataFrame(), "t", date_col="date", store_col="store", value_col="sales")
        assert rep.problems
    assert len(calls) == 2


def test_load_data_uses_a_sheet_it_is_handed(monkeypatch):
    """The app hands over the bill sheet it fetched alongside the portfolio; load_data must not fetch it again."""
    import loader as L
    monkeypatch.setattr(L, "_read_raw", lambda: (_ for _ in ()).throw(AssertionError("fetched twice")))
    import inspect
    assert "raw" in inspect.signature(L.load_data).parameters
    src = inspect.getsource(L.load_data)
    assert "_read_raw() if raw is None else raw" in src
