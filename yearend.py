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


# ★ The stitch is a pure function of (portfolio, vfl, asof) and is asked for by
# EVERY report on the page — gd_sheet, brand-wise, loc-wise, average and the
# exec tiles all go through `_gd_store_metrics`. Recomputing it each time cost
# ~13s on a portfolio pack. Keyed on a cheap fingerprint of the frame rather
# than its identity, so a re-read of the same day reuses it and a genuinely
# new day does not.
_MEMO: dict = {}
_MEMO_MAX = 8


def _key(pf, asof, tag, vfl=None):
    """A CHEAP fingerprint. The first version summed a column and counted
    distinct codes on every lookup, which cost more than the work it was
    guarding — the build got SLOWER. Row count plus the as-of date separates
    every frame this app actually builds from.

    ★ THE VFL FRAME IS PART OF THE KEY. Without it a call WITH the feed and one
    WITHOUT collided, and the second silently got the first's answer — so a
    caller that could not see South's history was handed a stitched figure
    anyway. Caught by the test that asserts the no-feed path leaves those
    stores out.
    """
    try:
        return (tag, str(pd.Timestamp(asof).date()) if asof else "-", len(pf),
                -1 if vfl is None else len(vfl))
    except Exception:
        return None


def _memo(key, build):
    if key is None:
        return build()
    if key not in _MEMO:
        if len(_MEMO) >= _MEMO_MAX:
            _MEMO.clear()
        _MEMO[key] = build()
    return _MEMO[key]


def stitched_ttm(pf: pd.DataFrame, vfl: pd.DataFrame | None, asof) -> pd.Series:
    """Trailing twelve months per portfolio code, reaching across both feeds.

    Returns a Series indexed by `code`. A store with no twelve months gets no
    entry at all rather than a zero — a part year dressed as a whole one is the
    error this guards against, and an absent entry makes the caller decide,
    which is `year_end`'s job.
    """
    return _memo(_key(pf, asof, "ttm", vfl), lambda: _stitched_ttm(pf, vfl, asof))


def _stitched_ttm(pf, vfl, asof) -> pd.Series:
    start, end = window(asof)
    out: dict = {}

    win = pf[(pf["date"] >= start) & (pf["date"] <= end)]
    by_code = win.groupby("code")["sales"].sum()
    first_pf = pf.groupby("code")["date"].min()

    # takeover per code, for the seam
    tko = (pf.groupby("code")["takeover_date"].first()
           if "takeover_date" in pf.columns else pd.Series(dtype="datetime64[ns]"))

    import loader as L

    # ★★ THE VFL FRAME IS SLICED ONCE, NOT ONCE PER STORE (11 Sep). This used
    # to filter all ~292k VFL rows twice for each of the eight South codes —
    # sixteen full-frame scans per call, on a report that asks for this five
    # times a page. On the Space's 2-vCPU box that is the difference between a
    # report and a hang. One groupby replaces the lot.
    v_sum: dict = {}
    v_first: dict = {}
    if vfl is not None and len(vfl):
        want = set(SOUTH_VFL_LABEL.values())
        vv = vfl[vfl[L.COL_STORE_LABEL].isin(want)]
        if len(vv):
            v_first = vv.groupby(L.COL_STORE_LABEL)["date"].min().to_dict()
            vw = vv[(vv["date"] >= start) & (vv["date"] <= end)]
            # (label, date) kept so each store's own seam can be applied below
            v_sum = {lbl: g for lbl, g in vw.groupby(L.COL_STORE_LABEL)}

    # the portfolio side, grouped once as well
    p_by_code = {c: g for c, g in win.groupby("code")} if len(win) else {}

    for code, first in first_pf.items():
        label = SOUTH_VFL_LABEL.get(_as_int(code))
        seam = tko.get(code)
        if label is not None and label in v_sum and pd.notna(seam):
            seam = pd.Timestamp(seam)
            g = v_sum[label]
            before = g[g["date"] < seam]
            if len(before) and has_full_year(v_first.get(label), asof):
                pg = p_by_code.get(code)
                after = 0.0 if pg is None else float(
                    pg.loc[pg["date"] >= seam, "sales"].sum())
                out[code] = float(before[L.COL_AMOUNT].sum()) + after
                continue
        if has_full_year(first, asof):
            out[code] = float(by_code.get(code, 0.0))

    return pd.Series(out, dtype=float)


def first_trade_map(pf: pd.DataFrame, vfl: pd.DataFrame | None) -> pd.Series:
    """Earliest day each portfolio code traded, reaching into the VFL feed for
    the South stores whose portfolio history starts at the takeover."""
    return _memo(_key(pf, None, "first", vfl),
                 lambda: _first_trade_map(pf, vfl))


def _first_trade_map(pf, vfl) -> pd.Series:
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


def is_closed(closed, asof) -> bool:
    """Has this store shut on or before the as-of date?

    One definition, used by every surface that has to decide whether a figure
    is still moving. A closure DATED in the future is not a closure yet — the
    store is still trading and its year is still running.
    """
    if closed is None:
        return False
    c = pd.to_datetime(closed, errors="coerce")
    if pd.isna(c):
        return False
    return c <= pd.Timestamp(asof)


def year_end(achieved_ytd: float, ttm, first_trade, fy_start, doo, asof,
             closed=None) -> tuple[float, str]:
    """The year-end figure and the basis it stands on.

    TTM once the store has twelve months; the shared projection until then.
    Returns `(value, BASIS_TTM | BASIS_PROJ)` — never a bare number, because
    the caller has to be able to label it.
    """
    # ★ A CLOSED STORE IS NEITHER PROJECTED NOR TRAILING — IT IS FINISHED.
    # Manav, 12 Sep: *"for all stores which have closed, the ttm/projected
    # metric should be the total sales for the year, because once the store
    # closes, the ttm becomes irrelevant."*
    #
    # This check has to come FIRST. `project_ytd` already freezes a closed
    # store at what it actually took (his call, 7 Aug — Planet Fashion was
    # projecting 972,668 against 338,435), but that rule never reached here:
    # the TTM branch was tested first and never looked at `closed`, so any
    # closed store with twelve months of history reported a rolling window
    # that mostly PREDATED its own closure. Planet Fashion read 6,590,928
    # against 338,435 actually taken — 19.5x, and worse than the projection
    # bug that was fixed in August.
    if is_closed(closed, asof):
        return float(achieved_ytd), BASIS_PROJ

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


def closed_codes(asof) -> set:
    """Store codes shut on or before `asof`.

    One source for both PDFs, so the grey shading and the frozen figure can
    never disagree about which stores are dead. Reads `loader.closed_map`,
    which takes the STORE MASTER as the authority rather than the committed
    snapshot — the snapshot knew three closures while the master knew
    fourteen, and a sheet that greys three of ten shut stores is worse than
    one that greys none, because it reads as a complete answer.
    """
    import loader as L
    out = set()
    for code, when in L.closed_map().items():
        if is_closed(when, asof):
            c = _as_int(code)
            if c is not None:
                out.add(c)
    return out


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


# ── the VFL feed, fetched once ──────────────────────────────────────────────
_FEED: dict = {"at": 0.0, "df": None}
_FEED_TTL = 600.0        # seconds


def vfl_feed(explicit=None):
    """The VFL frame for stitching South's pre-takeover history.

    ★★ THIS EXISTS BECAUSE THE PORTFOLIO PACK STOPPED GENERATING (11 Sep).
    `_gd_store_metrics` called `loader.load_data()` twice, and the GD, brand-wise
    and loc-wise reports each call it — so building the pack **downloaded the
    whole VFL sheet 16 times: 207 seconds of a 256-second build.** Locally that
    is slow; on the Space it is a report that never appears.

    `loader.load_data()` has no cache of its own — the app caches it at the
    Streamlit layer, which a report builder does not go through.

    Pass `explicit` when the caller already holds the frame (the report tab
    does). Otherwise it is fetched once and reused for `_FEED_TTL` seconds,
    which collapses one build's calls into one download while keeping the
    figure fresh between runs. The slice actually used is South's trading
    BEFORE 19 Apr 2026, which cannot change.
    """
    if explicit is not None:
        return explicit
    import time
    now = time.time()
    if _FEED["df"] is None or now - _FEED["at"] > _FEED_TTL:
        try:
            import loader as L
            _FEED["df"] = L.load_data()
            _FEED["at"] = now
        except Exception:
            # Never fatal: without it South falls back to the projection, which
            # is the honest answer when the history cannot be read.
            return None
    return _FEED["df"]


def prime_feed(df) -> None:
    """Hand `vfl_feed` a frame the caller already holds.

    ★ The report tab loads the VFL frame anyway and passes it to
    `portfolio_pdf.build`. Without this the stitch fetched its OWN second copy
    — a whole extra download of the sheet on every pack, ~20s of a build that
    was already the slowest thing on the page.
    """
    if df is None or not len(df):
        return
    import time
    _FEED["df"] = df
    _FEED["at"] = time.time()
