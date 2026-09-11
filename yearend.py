"""
YEAR END VIEW — one column that answers "where does this year finish".

★★ LIVE SINCE 11 SEP 2026 — APPROVED, AND STILL REVERSIBLE IN ONE WORD.
Manav inspected the trial pack and said *"the new thing we did with ttm is also
approved, so wire that change in to the live too"*. It was off by default from
10-11 Sep while he read it.

`enabled()` is still the only switch, now defaulting ON: setting
**`YEAR_END_VIEW=0`** in the environment puts every sheet back exactly as it
was, with no code change and no deploy. The off path is still exercised by the
tests, so it stays a real escape hatch rather than a dead branch.

The rule, his words:

    "i need a new column which basically answers how the year ends. if a store
     has a ttm, then use that, and for stores that dont, what u do is use the
     projected calculation until the ttm naturally arrives which is 12 months
     after the business starts."

So:

    YEAR END = TTM              where the store has twelve months behind it
             = Projected YTD    until it does, and no longer

A store therefore MOVES from one basis to the other on its first anniversary,
by itself, with no list to maintain. Every row says which basis it is on, and
the reports print that — a projection and a measured year in the same column
are not the same kind of number and the reader has to be told which they hold.

★★ SOUTH HAS A TTM, AND IT LIVES IN THE OTHER FEED (Manav, 10 Sep: "technically
we do have ttm, because we have the last year data from the previous
operator"). The portfolio feed starts the eight Bangalore stores on 19 Apr 2026
— the day Peanuts took over — so read there alone they look five months old and
`portfolio_loader.ttm_by_store` correctly returns 0 for them. Their earlier
trading is in the VFL feed, which reaches back to 1 Apr 2025. `stitched_ttm`
puts the two together: VFL before the takeover, portfolio after it, never both
for the same day. Measured 10 Sep: South's twelve months are Rs 71.47 Cr, of
which Rs 47.69 Cr is pre-takeover and would otherwise read as zero.

★ THE SEAM IS THE TAKEOVER DATE, NOT A GUESS. Each store's `takeover_date` is
carried in the portfolio frame. Rows are taken from the VFL feed strictly
BEFORE it and from the portfolio feed on and after it, so no day can be counted
twice and none can fall down the gap.

★ MTD IS UNTOUCHED. "for the mtd column, keep as is" — this is a year-end
question and a month has no trailing-twelve-month analogue. PROJECTED MTD stays
exactly as it is on every sheet.
"""

from __future__ import annotations

import os

import pandas as pd

import projections as PROJ

# What a row is standing on, printed beside the figure so the two kinds of
# number are never mistaken for each other.
BASIS_TTM = "TTM"
BASIS_PROJ = "PROJ"

# The eight Bangalore stores whose history predates the portfolio feed. Keyed
# portfolio code -> VFL store label. Written out rather than fuzzy-matched:
# "Cmh Road" and "CMH Road" differ by case and "M.G. Road" by punctuation, and
# a near-miss here would silently drop a store's whole first year.
SOUTH_VFL_LABEL = {
    107: "Grand Kamraj Road",
    108: "Commercial Street",
    109: "Kamraj Road",
    110: "M.G. Road",
    111: "Orion Mall",
    112: "Jayanagar",
    113: "CMH Road",
    114: "DVG Road",
}


# Anything here turns it OFF. Spelled out rather than inverted from the "on"
# list, because a typo in an env var must never silently mean the opposite of
# what was intended — an unrecognised value leaves the sheets as they are now.
_OFF = {"0", "false", "no", "off"}


def enabled() -> bool:
    """True unless explicitly switched off. Default ON — see the header."""
    return os.environ.get("YEAR_END_VIEW", "").strip().lower() not in _OFF


def window(asof) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The trailing twelve months ending `asof`, inclusive at both ends."""
    asof = pd.Timestamp(asof)
    return asof - pd.DateOffset(years=1) + pd.Timedelta(days=1), asof


def has_full_year(first_trade, asof) -> bool:
    """Has this store traded for the whole trailing twelve months?

    `first_trade` is the earliest day the store appears in the data we can see,
    STITCHED where a stitch applies — which is the whole point for South, whose
    portfolio rows begin at the takeover and whose real trading does not.
    """
    if first_trade is None or pd.isna(first_trade):
        return False
    start, _ = window(asof)
    return pd.Timestamp(first_trade) <= start


def stitched_ttm(pf: pd.DataFrame, vfl: pd.DataFrame | None, asof) -> pd.Series:
    """Trailing twelve months per portfolio code, reaching across both feeds.

    Returns a Series indexed by `code`. A store with no twelve months gets no
    entry at all rather than a zero — a part year dressed as a whole one is the
    error this guards against, and an absent entry makes the caller decide,
    which is `year_end`'s job.
    """
    start, end = window(asof)
    out: dict = {}

    win = pf[(pf["date"] >= start) & (pf["date"] <= end)]
    by_code = win.groupby("code")["sales"].sum()
    first_pf = pf.groupby("code")["date"].min()

    # takeover per code, for the seam
    tko = (pf.groupby("code")["takeover_date"].first()
           if "takeover_date" in pf.columns else pd.Series(dtype="datetime64[ns]"))

    import loader as L

    for code, first in first_pf.items():
        label = SOUTH_VFL_LABEL.get(_as_int(code))
        seam = tko.get(code)
        if label is not None and vfl is not None and pd.notna(seam):
            seam = pd.Timestamp(seam)
            # VFL strictly BEFORE the takeover, portfolio on and after it.
            v = vfl[(vfl[L.COL_STORE_LABEL] == label)
                    & (vfl["date"] >= start) & (vfl["date"] < seam)]
            p = win[(win["code"] == code) & (win["date"] >= seam)]
            if len(v):
                v_first = vfl[vfl[L.COL_STORE_LABEL] == label]["date"].min()
                if has_full_year(v_first, asof):
                    out[code] = float(v[L.COL_AMOUNT].sum()) + float(p["sales"].sum())
                    continue
        if has_full_year(first, asof):
            out[code] = float(by_code.get(code, 0.0))

    return pd.Series(out, dtype=float)


def first_trade_map(pf: pd.DataFrame, vfl: pd.DataFrame | None) -> pd.Series:
    """Earliest day each portfolio code traded, reaching into the VFL feed for
    the South stores whose portfolio history starts at the takeover."""
    import loader as L

    first = pf.groupby("code")["date"].min()
    if vfl is None:
        return first
    v_first = vfl.groupby(L.COL_STORE_LABEL)["date"].min()
    out = first.copy()
    for code in first.index:
        label = SOUTH_VFL_LABEL.get(_as_int(code))
        if label is not None and label in v_first.index:
            out[code] = min(first[code], v_first[label])
    return out


def year_end(achieved_ytd: float, ttm, first_trade, fy_start, doo, asof,
             closed=None) -> tuple[float, str]:
    """The year-end figure and the basis it stands on.

    TTM once the store has twelve months; the shared projection until then.
    Returns `(value, BASIS_TTM | BASIS_PROJ)` — never a bare number, because
    the caller has to be able to label it.
    """
    if has_full_year(first_trade, asof) and ttm is not None and pd.notna(ttm) \
            and float(ttm) > 0:
        return float(ttm), BASIS_TTM
    return (PROJ.project_ytd(float(achieved_ytd), fy_start, doo, asof, closed),
            BASIS_PROJ)


def column_label(basis_mix: set[str] | None = None) -> str:
    """What to head the column with.

    One basis across every row names itself; a mixture says so, because a
    column holding both a measured year and a run-rate must not read as one
    thing. See [[feedback-silent-failure-must-speak]] — the sheet says why.
    """
    if basis_mix == {BASIS_TTM}:
        return "TTM SALES"
    if basis_mix == {BASIS_PROJ}:
        return "PROJECTED YTD"
    return "YEAR END (TTM/PROJ)"


def _as_int(code):
    """Codes arrive as 107, '107' or 107.0 depending on the feed's mood."""
    try:
        return int(float(str(code).strip()))
    except (TypeError, ValueError):
        return None


# ── Wiring ──────────────────────────────────────────────────────────────────
# Everything below exists so the call sites stay one line each. A trial has to
# be removable, and a one-line call is removable; a rewritten row builder is
# not.

# ★ THE HEADER NAMES BOTH BASES (Manav, 11 Sep). The column holds a measured
# year for most rows and a run-rate for the young ones; a header saying only
# "YEAR END" invites the reader to treat them as one kind of number. The
# projected cells are also shaded — see `projected_codes`.
COL_PF = "Sum of YEAR END PROJECTED/TTM"    # portfolio sheets' naming
COL_VFL = "Year End Projected/TTM"          # VFL sheets' naming
_PAIR_PF = ("Sum of PROJECTED YTD", "Sum of TTM SALES")
_PAIR_VFL = ("Projected YTD", "TTM Sales")


def swap_cols(cols, vfl: bool = False):
    """Replace the PROJECTED YTD / TTM SALES pair with ONE year-end column.

    Manav: "only make one column to the sheets". Both GD sheets already carried
    a projection AND a trailing year side by side, which is two answers to one
    question. The new column sits where the projection sat, so the sheet's
    shape and reading order are unchanged.

    Off → the list is returned untouched, so this is safe to leave in place.
    """
    if not enabled():
        return cols
    proj, ttm = _PAIR_VFL if vfl else _PAIR_PF
    new = COL_VFL if vfl else COL_PF
    out = []
    for c in cols:
        if c == proj:
            out.append(new)
        elif c == ttm:
            continue                      # folded into the one column
        else:
            out.append(c)
    return out


def swap_row(row: dict, value: float, vfl: bool = False) -> dict:
    """Same swap, on a built row. Leaves the row alone when the trial is off."""
    if not enabled():
        return row
    proj, ttm = _PAIR_VFL if vfl else _PAIR_PF
    new = COL_VFL if vfl else COL_PF
    out = {}
    for k, v in row.items():
        if k == proj:
            out[new] = value
        elif k == ttm:
            continue
        else:
            out[k] = v
    return out


def note(basis_mix: set[str] | None) -> str:
    """The line a report prints under the table saying what the column holds.

    ★ A MEASURED YEAR AND A RUN-RATE IN ONE COLUMN MUST SAY SO. Without this
    the reader cannot tell Jayanagar's real twelve months from Dibrugarh's
    annualised five, and they are not the same kind of number.
    """
    if not basis_mix:
        return ""
    if basis_mix == {BASIS_TTM}:
        return "YEAR END = trailing twelve months, every store."
    if basis_mix == {BASIS_PROJ}:
        return ("YEAR END = run-rate x 365. No store here has twelve months "
                "behind it yet.")
    return ("YEAR END = the trailing twelve months where a store has them, "
            "and the run-rate x 365 until it does (marked P).")


def stitched_ly_full(pf: pd.DataFrame, vfl: pd.DataFrame | None, asof) -> pd.Series:
    """LAST FULL YEAR per code, reaching across the seam exactly as the TTM does.

    ★★ WITHOUT THIS THE TRIAL LIES BY 108 PERCENTAGE POINTS. The exec tile
    divides the year-end figure by last full year. Stitch only the numerator
    and South brings Rs 71.49 Cr to the top of that fraction and nothing to the
    bottom, because the portfolio feed holds no South before 19 Apr 2026 — the
    tile read "+108.0%" where the same estate on both sides is +0.5%.

    A subset can never exceed its parent, and two figures side by side must
    describe the same estate. If the year-end column reaches into the VFL feed
    then so must everything it is compared against.
    """
    import loader as L

    fy_year = pd.Timestamp(asof).year if pd.Timestamp(asof).month >= 4 \
        else pd.Timestamp(asof).year - 1
    lo, hi = pd.Timestamp(fy_year - 1, 4, 1), pd.Timestamp(fy_year, 3, 31)

    win = pf[(pf["date"] >= lo) & (pf["date"] <= hi)]
    out = win.groupby("code")["sales"].sum().to_dict()
    tko = (pf.groupby("code")["takeover_date"].first()
           if "takeover_date" in pf.columns else pd.Series(dtype="datetime64[ns]"))

    if vfl is not None:
        for code in pf["code"].unique():
            label = SOUTH_VFL_LABEL.get(_as_int(code))
            seam = tko.get(code)
            if label is None or pd.isna(seam):
                continue
            seam = pd.Timestamp(seam)
            v = vfl[(vfl[L.COL_STORE_LABEL] == label)
                    & (vfl["date"] >= lo) & (vfl["date"] <= hi)
                    & (vfl["date"] < seam)]
            p = win[(win["code"] == code) & (win["date"] >= seam)]
            if len(v):
                out[code] = float(v[L.COL_AMOUNT].sum()) + float(p["sales"].sum())

    return pd.Series(out, dtype=float)


def projected_codes(pf: pd.DataFrame, vfl, asof) -> set:
    """Store codes standing on a PROJECTION rather than a measured year.

    These are the cells the sheets shade. Today it is one store — Dibrugarh,
    which opened 18 Jan 2026 and reaches twelve months on 17 Jan 2027 — but the
    set is derived every run, so a store leaves it on its own anniversary and
    a newly opened store joins it without anyone editing a list.
    """
    ttm = stitched_ttm(pf, vfl, asof)
    first = first_trade_map(pf, vfl)
    out = set()
    for code in pf["code"].unique():
        v = ttm.get(code)
        if not (has_full_year(first.get(code), asof) and v is not None
                and pd.notna(v) and float(v) > 0):
            out.add(_as_int(code))
    return {c for c in out if c is not None}
