"""Build the A4 morning briefing for every open store, as printable PDFs.

    venv/bin/python scripts_a4_briefing.py            # every store
    venv/bin/python scripts_a4_briefing.py Agartala   # just one

Local only. Writes into `out_a4/` (gitignored) — nothing is pushed, and no
module the morning WhatsApp set uses is touched. See `snapshots_a4.py`.
"""
from __future__ import annotations

import os
import sys
import time

import pandas as pd

import loader as L
import snapshots as SN
import snapshots_a4 as A4

OUT = "out_a4"


def main(argv):
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    df = L.load_data()
    asof = pd.Timestamp(df["date"].max())

    master = L.load_store_master().set_index("tableau_name")
    closed = L.closed_map()
    stores = [s for s in sorted(df[L.COL_STORE_LABEL].dropna().unique())
              if not (s in master.index and int(master.loc[s, "code"]) in closed)]
    if argv:
        want = {a.lower() for a in argv}
        stores = [s for s in stores if s.lower() in want]
        if not stores:
            sys.exit(f"No open store matched {argv}. Have: {', '.join(stores)}")

    try:
        pf = __import__("portfolio_loader").load_portfolio()
        ff = SN.footfall_map(pf)
    except Exception as e:
        print(f"  (footfall unavailable — conversion will read blank: {e})")
        ff = {}

    targets = SN._targets_for(asof)
    print(f"as of {asof:%d %b %Y} · {len(stores)} store(s)")
    ok, failed = 0, []
    for s in stores:
        code = int(master.loc[s, "code"]) if s in master.index else None
        try:
            made = A4.store_sheet(L, df, asof, s, code, ff=ff, targets=targets)
        except Exception as e:
            failed.append(f"{s}: {e}")
            continue
        if made is None:
            failed.append(f"{s}: no rows")
            continue
        with open(os.path.join(OUT, made[0]), "wb") as fh:
            fh.write(made[1])
        # The table type size is worth printing: it is the one thing that
        # varies by store, and it is what decides whether the sheet reads.
        pt = made[2] / A4.DPI * 72
        spill = "" if made[3] == 1 else f"  ⚠ DATA SPILLED OVER {made[3]} SHEETS"
        if made[3] != 1:
            failed.append(f"{s}: data needed {made[3]} sheets, not one")
        tw = f", twamev {made[4]} sections" if made[4] else ""
        print(f"  {made[0]}  ({len(made[1]) / 1e6:.2f} MB, "
              f"tables {pt:.1f}pt{tw}){spill}")
        ok += 1
    print(f"{ok} sheet(s) into {OUT}/ in {time.time() - t0:.0f}s")
    for f in failed:
        print(f"  FAILED  {f}")


if __name__ == "__main__":
    main(sys.argv[1:])
