"""Build every report with the YEAR END trial on, as one zip for a director.

    venv/bin/python scripts_yearend_pack.py

★ IT SETS THE FLAG ITSELF, so the pack cannot be built from the live rules by
accident, and running it changes nothing about the app — the flag lives in this
process only. Both a TRIAL and a CURRENT copy of each sheet go in, so the
director can put them side by side rather than take the new column on trust.

★ THE PACK SAYS WHAT IT IS. A README goes in beside the PDFs: the rule in
Manav's words, which stores are on which basis, and the one store still on a
projection. A sheet that has quietly changed its meaning is worse than no
sheet.
"""

from __future__ import annotations

import io
import os
import sys
import zipfile

import pandas as pd


def _build(tag: str, pin=None) -> list[tuple[str, bytes]]:
    """Every PDF this pack carries, built under whatever flag is set."""
    # imported INSIDE, after the flag is set — module-level column lists in
    # loader.py read the flag at import time
    for m in [k for k in list(sys.modules) if k.split(".")[0] in {
            "loader", "portfolio_loader", "portfolio_pdf", "report_td",
            "exec_snapshot", "yearend", "festive", "festive_admin"}]:
        del sys.modules[m]

    import loader as L
    import portfolio_loader as PL
    import portfolio_pdf as PP
    import report_td as RTD

    out: list[tuple[str, bytes]] = []
    pf = PL.load_portfolio()
    vdf = L.load_data()
    # ★★ THE AS-OF DATE IS PINNED AND PASSED IN. Built without it, the two
    # halves of this pack came out on DIFFERENT DAYS — trial 9 Sep, current
    # 10 Sep — because the feed advanced between the two builds. A director
    # comparing them would have been reading two different days as though the
    # only difference were the column. Same trap as any two figures side by
    # side describing different spans.
    asof = pd.Timestamp(pin) if pin is not None else PL.as_of(pf)
    basis = f"As of {asof:%d %b %Y}"

    def add(name, fn):
        try:
            r = fn()
        except Exception as e:                     # one report must not sink the pack
            print(f"    ! {name}: {type(e).__name__}: {e}")
            return
        if r is None:
            return
        data = r[1] if isinstance(r, tuple) else r
        out.append((f"{tag}/{name}", data))
        print(f"    + {name}  ({len(data)/1e6:.2f} MB)")

    print(f"  {tag}:")
    # The portfolio pack is the big one — it carries the GD sheet, which is
    # where the year-end column actually lives.
    add(f"peanuts_portfolio_{asof:%Y%m%d}.pdf",
        lambda: PP.build(pf, pf, asof, basis, vfl_df=vdf))
    add(f"south_ltol_{asof:%Y%m%d}.pdf",
        lambda: RTD.build_south_ltol(vdf, asof, basis))
    add(f"east_ltol_{asof:%Y%m%d}.pdf",
        lambda: RTD.build_east_ltol(pf, asof, basis))
    add(f"month_wise_{asof:%Y%m%d}.pdf",
        lambda: RTD.build_month_wise(pf, vdf, asof, basis))
    add(f"target_vs_achieved_{asof:%Y%m%d}.pdf",
        lambda: RTD.build_target_vs_ach(pf, asof, basis))
    return out


def _readme(asof, rows) -> bytes:
    ttm = [r for r in rows if r[2] == "TTM"]
    proj = [r for r in rows if r[2] != "TTM"]
    lines = [
        "YEAR END — a trial, for inspection",
        "=" * 60,
        f"Built {asof:%d %b %Y}.  NOT live: the dashboard is unchanged.",
        "",
        "WHAT CHANGED",
        "-" * 60,
        "Every sheet's PROJECTED YTD and TTM SALES columns are replaced by ONE",
        "column, YEAR END, which answers where the year finishes:",
        "",
        "    a store with twelve months behind it  ->  its trailing twelve months",
        "    a store without them yet              ->  the run-rate x 365,",
        "                                              until its first anniversary",
        "",
        "PROJECTED MTD is untouched on every sheet.",
        "",
        "SOUTH",
        "-" * 60,
        "The portfolio feed starts the eight Bangalore stores on 19 Apr 2026, the",
        "day of the takeover, so read there alone they look five months old. Their",
        "earlier trading is taken from the VFL feed, which reaches back to",
        "1 Apr 2025 — the previous operator's year. VFL before the takeover,",
        "portfolio after it, so no day is counted twice.",
        "",
        f"WHERE EACH STORE STANDS  ({len(ttm)} measured, {len(proj)} still projected)",
        "-" * 60,
    ]
    for code, name, basis, val in sorted(proj, key=lambda r: -r[3]):
        lines.append(f"  PROJECTED  {str(code):<6} {str(name)[:28]:<30} "
                     f"Rs {val/1e7:>8.2f} Cr   (no twelve months yet)")
    lines += ["", "  every other store is on its measured trailing twelve months.", ""]
    lines += [
        "READING IT",
        "-" * 60,
        "The pack holds both a TRIAL and a CURRENT copy of each sheet. Same data,",
        "same day — only the year-end column differs. Compare them directly.",
        "",
        "TO REVERT",
        "-" * 60,
        "Nothing to revert: the trial is off unless YEAR_END_VIEW=1 is set, and it",
        "has never been set on the live app.",
    ]
    return "\n".join(lines).encode()


def main() -> int:
    os.environ["YEAR_END_VIEW"] = "1"
    print("YEAR END trial pack")

    import portfolio_loader as PL
    pin = PL.as_of(PL.load_portfolio())     # one day, for BOTH halves
    print(f"  pinned to {pin:%d %b %Y}")

    trial = _build("TRIAL — year end", pin)

    # which stores are on which basis, for the README
    pf = PL.load_portfolio()
    asof = pin
    mets = PL._gd_store_metrics(pf, asof)
    attrs = PL.gd_store_attrs_dyn(pf, asof).set_index("code")
    rows = [(c, attrs.loc[c, "location_main"] if c in attrs.index else "",
             m.get("year_basis", "PROJ"), m.get("year_end", 0.0))
            for c, m in mets.items()]

    os.environ.pop("YEAR_END_VIEW", None)
    current = _build("CURRENT — as the app is today", pin)

    name = f"YEAR END TRIAL {asof:%d-%m-%Y}.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("READ ME FIRST.txt", _readme(asof, rows))
        for n, d in trial + current:
            z.writestr(n, d)
    with open(name, "wb") as fh:
        fh.write(buf.getvalue())
    print(f"\n  {name}  ({len(buf.getvalue())/1e6:.2f} MB, "
          f"{len(trial) + len(current)} PDFs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
