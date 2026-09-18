"""Restore a snapshot taken by `scripts_backup.py`.

A backup that has never been restored is a hope, not a backup. This is the
other half, and `test_backup.py` exercises it, so the path is proven by the
suite rather than discovered during an outage.

★ THERE ARE TWO RESTORES, AND THE FIRST DRAFT GOT THIS WRONG.
It printed `export SHEET_CSV_URL=/path/to/file.csv`, which does not work:
`feed.read_csv` fetches with `requests`, so those secrets take a URL and only a
URL. The app told me so the first time it was tried — which is the whole
argument for testing a restore.

What actually works:

  1. REBUILD THE WORKBOOK (the real disaster case). Every source is written as
     a CSV here; upload each back into a Google Sheet, re-point the secrets,
     and the app is whole. This is the path if the workbook is lost.

  2. RUN OFFLINE RIGHT NOW (the outage case). `loader` and `portfolio_loader`
     each have a DOCUMENTED local fallback used when their URL is unset —
     `data/fulldata.xlsx` and `portfolio_snapshot.csv`. `--install` writes
     those two, so the core dashboard runs with no network at all.
     The small tabs (targets, festive dates, city growth, store master) have no
     file fallback; they stay missing, and the app already says so rather than
     inventing them.

    python scripts_restore.py --snapshot backup/2026-W38 --into restored/
    python scripts_restore.py --snapshot backup/2026-W38 --into restored/ --install
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

# source -> where the app looks for it when no URL is configured
LOCAL_FALLBACK = {
    "vfl": HERE / "data" / "fulldata.xlsx",
    "portfolio": HERE / "portfolio_snapshot.csv",
}
NO_FALLBACK = ["targets", "festive_dates", "city_growth", "storemaster",
               "night_fill"]


def restore(snapshot: Path, into: Path, *, install: bool = False) -> dict:
    man = json.loads((snapshot / "manifest.json").read_text())
    into.mkdir(parents=True, exist_ok=True)
    written, installed = {}, {}

    for e in man["entries"]:
        name = e["source"]
        src = snapshot / f"{name}.parquet"
        if not src.exists():
            continue
        df = pd.read_parquet(src)
        # The manifest is the contract. A snapshot whose rows no longer match
        # what was recorded is corrupt and must refuse, not restore quietly.
        if len(df) != e["rows"]:
            raise SystemExit(
                f"{name}: snapshot holds {len(df):,} rows, manifest says "
                f"{e['rows']:,} — corrupt, do not restore it")
        dest = into / f"{name}.csv"
        df.to_csv(dest, index=False)
        written[name] = dest

        if install and name in LOCAL_FALLBACK:
            target = LOCAL_FALLBACK[name]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                bak = target.with_suffix(target.suffix + ".pre-restore")
                shutil.copy2(target, bak)        # never overwrite blind
            if target.suffix == ".xlsx":
                df.to_excel(target, index=False)
            else:
                df.to_csv(target, index=False)
            installed[name] = target

    return {"manifest": man, "written": written, "installed": installed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--into", required=True)
    ap.add_argument("--install", action="store_true",
                    help="also write the app's local fallbacks so it runs offline")
    a = ap.parse_args()

    r = restore(Path(a.snapshot), Path(a.into), install=a.install)
    m = r["manifest"]
    print(f"restored {len(r['written'])} of {m['sources_expected']} sources "
          f"from {m['week']} (taken {m['taken_at']})")

    mode = m.get("pii_mode")
    if mode == "hashed":
        print("NOTE: customer mobile is a STABLE HASH, not the number. Distinct"
              "-customer and repeat-customer measures still work; the actual "
              "numbers are not in the backup and cannot be recovered from it.")
    elif mode == "dropped-no-salt":
        print("WARNING: taken with no BACKUP_PII_SALT, so identity columns were "
              "DROPPED. Customer counts will be wrong and the app may not load. "
              "Set the salt and take a fresh snapshot.")

    for f in m.get("failures", []):
        print(f"  ! {f['source']} was never saved: {f['error']}")

    if r["installed"]:
        print("\ninstalled the app's local fallbacks (previous files kept as "
              "*.pre-restore):")
        for n, p in r["installed"].items():
            print(f"  {n:12s} -> {p}")
        print("\nUnset SHEET_CSV_URL and PORTFOLIO_CSV_URL to make the app use "
              "them.")
        print("Still missing (no file fallback exists; the app will say so): "
              + ", ".join(n for n in NO_FALLBACK if n in r["written"]))
    else:
        print("\nCSVs written to " + str(Path(a.into).resolve())
              + " — upload each back into the workbook and re-point the secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
