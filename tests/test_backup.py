"""The weekly backup and, just as importantly, the restore.

A backup that has never been restored is a hope. Every test here runs offline
on frames built in the test, so CI verifies the rules without the feed — see
[[feedback-test-where-it-runs]].
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def snap(tmp_path, monkeypatch):
    import scripts_backup as B
    monkeypatch.setenv("BACKUP_PII_SALT", "test-salt")
    monkeypatch.delenv("BACKUP_KEEP_PII", raising=False)
    m = B.run(tmp_path, offline=True, stamp=pd.Timestamp("2026-09-18").date())
    return tmp_path, m


# ---- the sources are addressed the way the APP addresses them -------------- #
def test_tab_names_match_the_modules_that_read_them():
    """The backup re-derives these tab names instead of importing the modules,
    so a run needs no Streamlit on the runner. That duplication is the risk —
    this is what catches it drifting, rather than a missing snapshot in six
    months. The first draft saved 3 of 8 because it assumed one secret per
    source; five of these tabs have no secret at all."""
    import scripts_backup as B
    import targets, festive, city_growth, master_lookup
    assert B.TABS["targets"] == targets._SHEET
    assert B.TABS["festive_dates"] == festive._SHEET
    assert B.TABS["city_growth"] == city_growth._SHEET
    assert B.TABS["storemaster"] == master_lookup._SHEET


def _fake_secrets(monkeypatch, mapping):
    """Stub `_secret` rather than the environment.

    ★ `monkeypatch.setenv` IS NOT ENOUGH HERE. The first `_secret` call imports
    Streamlit, and Streamlit loads `.streamlit/secrets.toml` and writes its
    top-level string values INTO `os.environ` — clobbering the test's value
    half way through the call. Measured: `_secret("PORTFOLIO_CSV_URL")` returned
    the test's URL, and `source_url()` then built one from the real workbook id.
    """
    import scripts_backup as B
    monkeypatch.setattr(B, "_secret", lambda k: mapping.get(k))


def test_a_tab_is_derived_from_the_portfolio_workbook(monkeypatch):
    import scripts_backup as B
    _fake_secrets(monkeypatch, {
        "PORTFOLIO_CSV_URL":
            "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv"})
    url = B.source_url("targets")
    assert "/spreadsheets/d/ABC123/" in url and "Targets%20New" in url


def test_an_explicit_secret_beats_the_derived_url(monkeypatch):
    import scripts_backup as B
    _fake_secrets(monkeypatch, {
        "PORTFOLIO_CSV_URL":
            "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv",
        "TARGETS_URL": "https://example.invalid/mine.csv"})
    assert B.source_url("targets") == "https://example.invalid/mine.csv"


def test_a_source_with_no_url_says_which_secret_is_missing(monkeypatch):
    import scripts_backup as B
    _fake_secrets(monkeypatch, {})
    raw, err = B.fetch("targets", offline=False)
    assert raw is None and "PORTFOLIO_CSV_URL" in err


# ---- personal data --------------------------------------------------------- #
def test_mobile_is_hashed_not_dropped(monkeypatch):
    """Dropping it broke the restore outright — `loader.clean` needs the column
    — and silently destroyed every distinct-customer measure, because it is an
    identity key and not a display field."""
    import scripts_backup as B
    monkeypatch.setenv("BACKUP_PII_SALT", "s")
    df = pd.DataFrame({"CUSTOMER_MOBILE": ["9876543210", "9876543210", "9000000001"],
                       "Name (Dm Salesperson)": ["A", "B", "C"], "sales": [1, 2, 3]})
    out, pii = B.redact(df)
    assert "CUSTOMER_MOBILE" in out.columns          # column survives
    assert "9876543210" not in set(out["CUSTOMER_MOBILE"])
    assert out["CUSTOMER_MOBILE"].nunique() == 2     # identity preserved
    assert out["CUSTOMER_MOBILE"][0] == out["CUSTOMER_MOBILE"][1]
    assert "Name (Dm Salesperson)" not in out.columns
    assert pii["mode"] == "hashed"


def test_the_same_number_hashes_the_same_way_every_week(monkeypatch):
    """Or week-to-week history stops joining and repeat-customer counts break."""
    import scripts_backup as B
    df = pd.DataFrame({"CUSTOMER_MOBILE": ["9876543210"]})
    monkeypatch.setenv("BACKUP_PII_SALT", "stable")
    a, _ = B.redact(df)
    b, _ = B.redact(df)
    assert a["CUSTOMER_MOBILE"][0] == b["CUSTOMER_MOBILE"][0]
    monkeypatch.setenv("BACKUP_PII_SALT", "different")
    c, _ = B.redact(df)
    assert c["CUSTOMER_MOBILE"][0] != a["CUSTOMER_MOBILE"][0]


def test_a_missing_salt_is_recorded_not_hidden(monkeypatch):
    """Without a salt the column must go, which makes the snapshot
    unrestorable — so the manifest has to say so rather than look complete."""
    import scripts_backup as B
    monkeypatch.delenv("BACKUP_PII_SALT", raising=False)
    out, pii = B.redact(pd.DataFrame({"CUSTOMER_MOBILE": ["9876543210"]}))
    assert "CUSTOMER_MOBILE" not in out.columns
    assert pii["mode"] == "dropped-no-salt"


def test_hashing_survives_a_blank_or_nan_mobile(monkeypatch):
    """A float NaN blew this up mid-run against the real feed."""
    import scripts_backup as B
    monkeypatch.setenv("BACKUP_PII_SALT", "s")
    out, _ = B.redact(pd.DataFrame({"CUSTOMER_MOBILE": [float("nan"), "", "98765"]}))
    assert list(out["CUSTOMER_MOBILE"])[:2] == ["", ""]
    assert out["CUSTOMER_MOBILE"][2] not in ("", "98765")


# ---- the manifest is the point --------------------------------------------- #
def test_the_manifest_records_every_source(snap):
    d, m = snap
    assert m["sources_saved"] == m["sources_expected"] == len(
        __import__("scripts_backup").SOURCES)
    assert (d / m["week"] / "manifest.json").exists()
    for e in m["entries"]:
        assert (d / m["week"] / f"{e['source']}.parquet").exists()
        assert e["columns"] and e["sha256_raw"]


def test_a_renamed_column_is_reported(snap):
    """The likeliest failure is not a sheet vanishing — it is a rename."""
    import scripts_backup as B
    d, m = snap
    prev = d / m["week"] / "manifest.json"
    cur = json.loads(json.dumps(m))
    cur["entries"][0]["columns"] = ["date", "RENAMED"]
    out = B.diff_against(prev, cur)
    assert any("COLUMNS REMOVED" in c for c in out)
    assert any("columns added" in c for c in out)


def test_a_stalled_export_is_reported(snap):
    import scripts_backup as B
    d, m = snap
    cur = json.loads(json.dumps(m))
    e = cur["entries"][0]
    e["rows"] = 0
    out = B.diff_against(d / m["week"] / "manifest.json", cur)
    assert any("ROWS FELL" in c for c in out)


def test_a_partial_backup_exits_nonzero(tmp_path, monkeypatch):
    """Seven saved sources beat none — but it must not read as a clean run."""
    # cwd must be somewhere WITHOUT .streamlit/secrets.toml, or Streamlit
    # finds the real secrets and the run succeeds — see `_fake_secrets`.
    env = {k: v for k, v in os.environ.items()
           if not k.endswith("_URL") and k != "BACKUP_PII_SALT"}
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts_backup.py"), "--out", str(tmp_path)],
        capture_output=True, text=True, cwd=str(tmp_path), env=env)
    assert r.returncode != 0, r.stdout
    assert "no URL" in r.stdout


# ---- the restore ----------------------------------------------------------- #
def test_the_snapshot_restores(snap, tmp_path):
    import scripts_restore as R
    d, m = snap
    out = R.restore(d / m["week"], tmp_path / "out")
    assert len(out["written"]) == m["sources_saved"]
    for p in out["written"].values():
        assert pd.read_csv(p).shape[0] >= 1


def test_a_corrupt_snapshot_refuses_to_restore(snap, tmp_path):
    """The manifest is the contract."""
    import scripts_restore as R
    d, m = snap
    week = d / m["week"]
    man = json.loads((week / "manifest.json").read_text())
    man["entries"][0]["rows"] = 999999
    (week / "manifest.json").write_text(json.dumps(man))
    with pytest.raises(SystemExit, match="corrupt"):
        R.restore(week, tmp_path / "out")


def test_install_never_overwrites_without_a_copy(snap, tmp_path, monkeypatch):
    import scripts_restore as R
    d, m = snap
    target = tmp_path / "portfolio_snapshot.csv"
    target.write_text("i was here first\n")
    monkeypatch.setitem(R.LOCAL_FALLBACK, "portfolio", target)
    monkeypatch.setitem(R.LOCAL_FALLBACK, "vfl", tmp_path / "data" / "fulldata.xlsx")
    R.restore(d / m["week"], tmp_path / "out", install=True)
    assert (tmp_path / "portfolio_snapshot.csv.pre-restore").read_text() == \
        "i was here first\n"
