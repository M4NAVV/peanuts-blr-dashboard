"""Weekly backup of every external source this dashboard depends on.

Everything the app knows comes from eight Google Sheet tabs. If one is deleted,
renamed, or quietly stops being populated, there is no second copy — so this
takes one.

★ IT BACKS UP THE RAW SOURCE, NOT THE APP'S READING OF IT. `loader.load_data()`
returns a parsed, renamed, derived frame; restoring that would restore this
version of the code's opinion of the data. The bytes each URL actually served
are what can be restored into any future version, so that is what is kept.

★ THE MANIFEST IS THE POINT, NOT JUST THE ROWS. The likeliest failure here is
not a sheet vanishing — it is a tab or a column being renamed, or the upstream
export quietly stopping. Rows alone cannot show that. Every snapshot records
each source's columns, row count, date range and checksum, so a rename is
visible the morning it happens rather than when a report comes out wrong.

★ AND IT IS AN AUDIT TRAIL. This feed RESTATES CLOSED HISTORY: South's
Oct-Mar total moved +Rs 93,97,936 (+2.4%) in a single day, every month up
(see [[feedback-settled-window]]). Dated snapshots make that diffable instead
of something you notice by accident after quoting the old number.

⚠️ PERSONAL DATA. The bill feed carries CUSTOMER_MOBILE, mobile_clean and
salesperson names. A backup MULTIPLIES copies of those, and the dashboard repo
is public — so the columns in `REDACT` are dropped before anything is written,
and the destination must be a PRIVATE store. Set `BACKUP_KEEP_PII=1` only if a
restore genuinely needs them, and only into somewhere private.

Usage:
    python scripts_backup.py --out backup/            # real pull
    python scripts_backup.py --out /tmp/x --offline   # no network, for tests
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

# ★★ HOW A SOURCE IS ADDRESSED, AND WHY IT IS NOT A FLAT LIST OF SECRETS.
# The first draft mapped one env var per source and saved 3 of 8 — because five
# of these tabs have NO secret of their own. They live in the PORTFOLIO
# workbook and are addressed by TAB NAME through gviz, derived from
# PORTFOLIO_CSV_URL, exactly as `targets._candidates()` does. An explicit
# `<NAME>_URL` secret still wins where one is set.
#
# The tab names are re-derived here rather than imported, so a backup run needs
# neither Streamlit nor the app's module graph on the runner. That duplication
# is the risk, so `test_backup.py` asserts these names still equal the modules'
# own `_SHEET` constants — drift is caught by the suite, not in six months by a
# missing snapshot.
DIRECT = {                      # source -> its own secret
    "vfl":        "SHEET_CSV_URL",
    "portfolio":  "PORTFOLIO_CSV_URL",
    "night_fill": "NIGHT_FILL_URL",
}
TABS = {                        # source -> tab name in the portfolio workbook
    "targets":       "Targets New",
    "festive_dates": "ImpFestiveDates",
    "city_growth":   "VFL_Month Wise City Growth",
    "storemaster":   "storemaster",
}
OVERRIDE = {                    # source -> secret that wins if it is set
    "targets":       "TARGETS_URL",
    "festive_dates": "FESTIVE_DATES_URL",
    "city_growth":   "CITY_GROWTH_URL",
    "storemaster":   "STORE_MASTER_URL",
}
SOURCES = list(DIRECT) + list(TABS)

# Committed to the dashboard repo, so git already versions them. Listed in the
# manifest for completeness — a restore needs to know they exist — but not
# copied, because a second copy of a tracked file is not a backup.
IN_GIT = ["store_master.csv", "review_places.csv", "review_snapshots.csv",
          "gd_store_attrs.csv", "portfolio_snapshot.csv",
          "portfolio_store_master.csv", "mw_data_historical.csv"]

# ★★ PSEUDONYMISED, NOT DROPPED — AND THE RESTORE TEST IS WHY.
# The first cut DROPPED these columns. The snapshot then could not be restored
# at all: `loader.clean()` requires CUSTOMER_MOBILE and died with a KeyError.
# Worse, the column is an IDENTITY KEY, not a display field — distinct-customer
# counts and the whole repeat-customer history group by it. Dropping it silently
# destroys those measures even where the app does load.
#
# So they are HASHED with a salt held outside the backup. Same customer hashes
# the same way every week, so `nunique`, `groupby` and first-seen dates all keep
# working, while the actual numbers are not in the snapshot. The salt must be
# STABLE or week-to-week history stops joining, and it must be SECRET — a
# ten-digit phone space is small enough to brute-force if the salt leaks with
# the data, which is exactly why it is not stored beside it.
HASH_COLS = {"customer_mobile", "mobile_clean", "mobile", "phone"}
# No analytic use, so these are simply dropped.
DROP_COLS = {"name (dm salesperson)", "customer_name", "email"}
SALT_ENV = "BACKUP_PII_SALT"

SCHEMA_VERSION = 1


def _secret(env: str) -> str | None:
    v = os.environ.get(env)
    if v:
        return v
    try:
        import streamlit as st
        return st.secrets.get(env)          # type: ignore[no-any-return]
    except Exception:
        return None


def source_url(name: str) -> str | None:
    """Where this source is read from, resolved the way the app resolves it."""
    if name in DIRECT:
        return _secret(DIRECT[name])
    explicit = _secret(OVERRIDE.get(name, ""))
    if explicit:
        return explicit
    base = _secret("PORTFOLIO_CSV_URL")
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", str(base)) if base else None
    if not m:
        return None
    return (f"https://docs.google.com/spreadsheets/d/{m.group(1)}"
            f"/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(TABS[name])}")


def redact(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Hash identity columns, drop the rest. Returns (frame, what was done)."""
    if os.environ.get("BACKUP_KEEP_PII", "").strip() in {"1", "true", "yes"}:
        return df, {"hashed": [], "dropped": [], "mode": "kept-in-full"}

    salt = _secret(SALT_ENV)
    hashed, dropped = [], []
    out = df

    for c in list(out.columns):
        low = str(c).strip().lower()
        if low in DROP_COLS:
            out = out.drop(columns=[c]); dropped.append(str(c))
        elif low in HASH_COLS:
            if salt:
                # str() on every value, not `.astype(str)` on the column:
                # a float NaN slipped through and blew up mid-run.
                def _h(v):
                    v = "" if v is None else str(v).strip()
                    if v in ("", "nan", "NaN", "None", "<NA>"):
                        return ""
                    return hashlib.sha256((salt + v).encode()).hexdigest()[:16]
                out = out.assign(**{c: [_h(v) for v in out[c].tolist()]})
                hashed.append(str(c))
            else:
                # No salt: the column would have to be dropped, which breaks
                # both the restore and every customer measure. Say so in the
                # manifest rather than producing a snapshot that looks whole.
                out = out.drop(columns=[c]); dropped.append(str(c))
    mode = ("hashed" if salt else "dropped-no-salt")
    return out, {"hashed": hashed, "dropped": dropped, "mode": mode}


def describe(name: str, raw: bytes, df: pd.DataFrame, pii: dict) -> dict:
    """What this source looked like — enough to spot a rename or a stall."""
    dates = None
    for c in df.columns:
        if str(c).strip().lower() in {"date", "bill date", "billdate"}:
            # dayfirst: these sheets write 17-09-2026, and guessing per
            # value would read 01-02 as 1 Feb on one row and 2 Jan on the next.
            s = pd.to_datetime(df[c], errors="coerce", dayfirst=True).dropna()
            if len(s):
                dates = {"column": str(c), "min": str(s.min().date()),
                         "max": str(s.max().date()), "days": int(s.dt.date.nunique())}
            break
    return {
        "source": name,
        "rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "n_columns": int(len(df.columns)),
        "pii": pii,
        "restorable": pii["mode"] != "dropped-no-salt",
        "date_span": dates,
        "sha256_raw": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
    }


def fetch(name: str, *, offline: bool) -> tuple[bytes | None, str | None]:
    """(raw csv bytes, error). Never raises — one dead source must not stop the
    other seven from being saved."""
    if offline:
        return b"date,sales\n2026-01-01,1\n", None
    url = source_url(name)
    if not url:
        want = DIRECT.get(name) or OVERRIDE.get(name, "PORTFOLIO_CSV_URL")
        return None, f"no URL — set {want} (or PORTFOLIO_CSV_URL)"
    try:
        import requests
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        if not r.content.strip():
            return None, "served an empty body"
        return r.content, None
    except Exception as e:                       # noqa: BLE001 - network surface
        return None, f"{type(e).__name__}: {e}"


def run(out_dir: Path, *, offline: bool = False, stamp: date | None = None) -> dict:
    stamp = stamp or datetime.now(timezone.utc).date()
    iso_year, iso_week, _ = stamp.isocalendar()
    week = f"{iso_year}-W{iso_week:02d}"
    dest = out_dir / week
    dest.mkdir(parents=True, exist_ok=True)

    entries, failures = [], []
    for name in SOURCES:
        raw, err = fetch(name, offline=offline)
        if raw is None:
            failures.append({"source": name, "error": err})
            print(f"  FAILED  {name:14s} {err}")
            continue
        try:
            df = pd.read_csv(io.BytesIO(raw), dtype=str, low_memory=False)
        except Exception as e:                   # noqa: BLE001
            failures.append({"source": name,
                             "error": f"unparseable CSV: {type(e).__name__}"})
            print(f"  FAILED  {name:14s} unparseable CSV")
            continue
        df, pii = redact(df)
        df.to_parquet(dest / f"{name}.parquet", compression="zstd", index=False)
        entry = describe(name, raw, df, pii)
        entries.append(entry)
        note = ("  (" + ", ".join(
            ([f"{len(pii['hashed'])} hashed"] if pii["hashed"] else [])
            + ([f"{len(pii['dropped'])} dropped"] if pii["dropped"] else [])) + ")"
        ) if (pii["hashed"] or pii["dropped"]) else ""
        print(f"  ok      {name:14s} {entry['rows']:>8,} rows  "
              f"{entry['n_columns']:>3} cols{note}")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "week": week,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources_expected": len(SOURCES),
        "also_versioned_in_git": IN_GIT,
        "sources_saved": len(entries),
        "pii_mode": ("kept-in-full" if os.environ.get("BACKUP_KEEP_PII")
                     else ("hashed" if _secret(SALT_ENV) else "dropped-no-salt")),
        "entries": entries,
        "failures": failures,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def diff_against(prev: Path, cur: dict) -> list[str]:
    """What changed since the previous snapshot — the part worth reading.

    A column appearing or disappearing is the failure this backup exists to
    catch early; a row count that went DOWN, or a date span that stopped
    advancing, is the upstream export having quietly stalled.
    """
    if not prev.exists():
        return []
    old = {e["source"]: e for e in json.loads(prev.read_text()).get("entries", [])}
    out = []
    for e in cur["entries"]:
        o = old.get(e["source"])
        if not o:
            out.append(f"{e['source']}: NEW source in this snapshot")
            continue
        gone = [c for c in o["columns"] if c not in e["columns"]]
        added = [c for c in e["columns"] if c not in o["columns"]]
        if gone:
            out.append(f"{e['source']}: COLUMNS REMOVED {gone}")
        if added:
            out.append(f"{e['source']}: columns added {added}")
        if e["rows"] < o["rows"]:
            out.append(f"{e['source']}: ROWS FELL {o['rows']:,} -> {e['rows']:,}")
        a, b = o.get("date_span"), e.get("date_span")
        if a and b and b["max"] == a["max"]:
            out.append(f"{e['source']}: date span did NOT advance (still {b['max']})")
    for f in cur["failures"]:
        out.append(f"{f['source']}: NOT SAVED — {f['error']}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--stamp", default=None, help="YYYY-MM-DD, for tests")
    a = ap.parse_args()

    out = Path(a.out)
    stamp = date.fromisoformat(a.stamp) if a.stamp else None
    prev = sorted(p for p in out.glob("*/manifest.json"))
    print(f"backup -> {out}")
    m = run(out, offline=a.offline, stamp=stamp)

    changes = diff_against(prev[-1], m) if prev else []
    print(f"\nsaved {m['sources_saved']} of {m['sources_expected']} sources "
          f"into {m['week']}")
    if changes:
        print("\nCHANGED SINCE THE LAST SNAPSHOT:")
        for c in changes:
            print(f"  ! {c}")
    # A partial backup must be loud. It still keeps what it got — seven saved
    # sources beat none — but it must not exit 0 and read as a clean run.
    return 1 if m["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
