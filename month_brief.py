"""The month-brief card — two panels, PRPL East and PRPL South, as a PNG.

Reproduces the workbook block Manav shared on 1 Sep, line for line, and it is
built to update itself every day rather than be retyped.

★ THE TWO PANELS COME FROM DIFFERENT FEEDS, AND THEY HAVE TO. South has no
history in the portfolio sheet — it opened this April — so its last year exists
only in the VFL feed. East & NE is read from the portfolio. Reconciled against
the workbook on 31 Aug 2026:

    East & NE   Aug-25  4,52,93,320  vs ours 4,52,82,824    Rs 10,496 apart
                Aug-26  3,99,86,460  vs ours 3,99,86,459    Rs 1 apart
    South       Aug-26  5,71,22,940  vs ours 5,71,22,940    exact
                31 Aug  1,052,319    vs ours 1,052,319      exact

★ AND THE TWO G/D LINES ARE NOT PLAIN YEAR-ON-YEAR — that was the trap. South's
+9.33% only appears when the year is counted from the 19 April takeover, not
from 1 April.

★★ EAST'S TWO G/D LINES ARE LIKE TO LIKE, ON BOTH MTD AND YTD (Manav, 4 Sep
2026). They were the GD sheet's `2526FY` subtotal until then — the stores that
traded a FULL year on both sides, which is how the card first reconciled to the
workbook (-5.87% / +1.83% on 31 Aug). It no longer ties to that column and is
not meant to: `2526FY` drops a store that opened mid-last-year whole, both
years of it, while like to like compares each store over the span it HAS both
years. On 2 Sep the change reads -16.64/+1.61 to -20.14/+0.63.
`_gd_from_sheet` is kept below but is no longer wired to anything.

    python3 -c "import month_brief; month_brief.write()"
"""
from __future__ import annotations

import io

import pandas as pd
from PIL import Image, ImageDraw

import portfolio_pdf as PP
import snapshots_a4 as A4

# ★ THE WORKBOOK'S OWN FORMATTING (Manav, 3 Sep, with two screenshots): a
# green title bar spanning both columns, a black grid on every cell, centred
# text, and fills that carry meaning rather than decoration —
#
#   BLUE    the two figures read straight off the feed: the month so far, and
#           yesterday. The inputs.
#   YELLOW  everything DERIVED from them — the daily average, the trend, the
#           run-rate a shortfall implies. In his sheet these are the cells that
#           read #DIV/0! at month end, because they divide by days left.
#   ORANGE  the target block, kept together so it reads as one question.
#   RED INK days left, and yesterday's sale.
#
# The #DIV/0! cells are NOT reproduced. They are Excel dividing by a zero day
# count on the last of the month; we print "month complete", which is the same
# fact without the error. Figures keep Indian comma grouping rather than the
# sheet's raw floats.
W, PAD, GAP = 1680, 34, 30
INK, SUB = (0, 0, 0), (90, 96, 106)
GRID = (0, 0, 0)
GREEN, BLUE, YELLOW, ORANGE, WHITE = ("#92D050", "#B4C6E7", "#FFFF00",
                                      "#F0A94A", "#FFFFFF")
RED, BAND = "#C00000", "#1F3864"

# fill for the value cell, whether the LABEL is filled too, and the ink
_ROW_STYLE = {
    "achieved":  (WHITE,  False, INK),
    "tilldate":  (BLUE,   False, INK),
    "derived":   (YELLOW, False, INK),
    "plain":     (WHITE,  False, INK),
    "days":      (WHITE,  False, RED),
    "yesterday": (BLUE,   False, RED),
    "target":    (ORANGE, True,  INK),
}


def _money(v):
    return "—" if v is None or pd.isna(v) else f"{v:,.0f}"


def _pct(v):
    return "—" if v is None or pd.isna(v) else f"{v:,.2f}"


def _gd_from_sheet(disp, types, region, group="2526FY"):
    """The GD sheet's own subtotal for a region — the workbook's basis."""
    for i, t in enumerate(types):
        r = disp.iloc[i]
        if t == "subtotal" and str(r.get("Region", "")) == region \
                and str(r.get("NEW/OLD", "")).startswith(group):
            return (float(r["Sum of GD_MTD_%"]) * 100,
                    float(r["Sum of GD_YTD_%"]) * 100)
    return (None, None)


def _gd_l2l(PL, pf, region, asof):
    """A region's G/D on the LIKE TO LIKE basis — Manav, 4 Sep 2026.

    ★ WHY THIS REPLACED THE GD SHEET'S `2526FY` SUBTOTAL. Both answer "how is
    the region doing against last year", but they exclude differently, and one
    of them throws real trade away:

      `2526FY`  keeps only stores that traded a FULL year on BOTH sides. A store
                that opened last June is dropped whole — both years of it — so
                the months it CAN be compared over are lost with the months it
                cannot.
      like to like  compares each store over the span it has both years. Silchar
                contributes its comparable months instead of contributing none.

    The property that makes it the right basis here is the one `l2l_bounds`
    states: last year's like to like total comes out at the estate's whole
    last-year turnover, to the rupee. Nothing real is discarded; only THIS
    year's sales with no counterpart are held out.

    ★ BOTH LINES MOVE TOGETHER, deliberately. MTD and YTD on different bases
    would put two numbers in one card that cannot be reasoned about as a pair —
    see [[feedback-same-estate]]. The spans are per store and identical for
    both; only the window they are cut against differs.

    Computed from `_window_frames`, so the takeover anchoring and the closure
    caps underneath are the report's, not a second set written here.
    """
    import exec_snapshot as ES
    pf = pf[pf["region"] == region]
    if pf.empty:
        return (None, None)
    bounds = ES.l2l_bounds(pf, "code", "sales", PL.closed_map(), asof,
                           opened=PL.opened_map(pf, asof))

    def rate(kind):
        cur, pri = PL._window_frames(pf, kind, asof)
        if cur.empty and pri.empty:
            return None
        c, p = ES.l2l_frames(cur, pri, bounds, "code")
        ty, ly = c["sales"].sum(), p["sales"].sum()
        return ((ty - ly) / ly * 100) if ly else None

    return (rate("MTD"), rate("YTD"))


def panel(L, name, d, amt, asof, gd_mtd, gd_ytd, target=None):
    """Every line of one block as (label, value, style), in the sheet's order."""
    asof = pd.Timestamp(asof)
    m0 = asof.replace(day=1)
    days_in = pd.Period(asof, "M").days_in_month
    elapsed, left = asof.day, days_in - asof.day
    prev = m0 - pd.DateOffset(years=1)

    ly = d[(d["date"] >= prev)
           & (d["date"] <= prev + pd.offsets.MonthEnd(0))][amt].sum()
    mtd = d[(d["date"] >= m0) & (d["date"] <= asof)][amt].sum()
    avg = mtd / elapsed if elapsed else 0.0
    trend = mtd + avg * left
    yest = d[d["date"] == asof][amt].sum()
    short_ly = ly - mtd
    done = "month complete"

    rows = [
        (f"{prev:%B %Y} Achieved", _money(ly), "achieved"),
        (f"{m0:%B %Y} Till Date", _money(mtd), "tilldate"),
        (f"{m0:%B %Y} Till Date Avg", _money(avg), "derived"),
        ("Mtd Trending", _money(trend), "derived"),
        (f"Shortfall Vs {prev:%B %Y}", _money(short_ly), "plain"),
        ("No of days left", f"{left}", "days"),
        ("Average Req. Daily",
         _money(short_ly / left) if left > 0 else done, "derived"),
        ("Yesterday Total Sale", _money(yest), "yesterday"),
        ("Mtd G/D", _pct(gd_mtd), "plain"),
        ("Ytd G/D", _pct(gd_ytd), "plain"),
    ]
    if target:
        short_t = target - mtd
        rows += [
            (f"{m0:%B} Tgt B", _money(target), "target"),
            ("Shortfall Vs Tgt", _money(short_t), "target"),
            ("Average Req Vs Tgt",
             _money(short_t / left) if left > 0 else done, "target"),
        ]
    return name, rows


def _draw(panels, asof, title=None, subtitle=None):
    """Two Excel-style tables side by side: green title bar, black grid,
    centred text, meaning-carrying fills.

    `title`/`subtitle` default to the month brief's own heading, so the festive
    card can reuse every pixel of this layout without either card drifting from
    the other."""
    tt, ttb = A4._ft(44)
    sml, _ = A4._ft(24)
    hd, hdb = A4._ft(31)

    rows = max(len(p[1]) for p in panels)
    n = len(panels)
    # one panel keeps a panel's width rather than stretching to the pair's
    page_w = W if n > 1 else (W - GAP) // 2 + PAD
    pw = (page_w - PAD * 2 - GAP) // 2 if n > 1 else page_w - PAD * 2

    # ★ THE LABEL COLUMN FITS ITS LONGEST LABEL, it is not a fixed share of the
    # panel. At 47% the August wording fitted and September did not — "September
    # 2026 Till Date Avg" ran straight through the cell border into the number
    # beside it. A month name is not a constant, so the width cannot be one:
    # the type steps down until the longest label fits, and the column is then
    # sized to it.
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    longest = max((t for _, ls in panels for t, _v, _s in ls), key=len)
    for px in range(30, 17, -1):
        lab, labb = A4._ft(px)
        if scratch.textlength(longest, font=lab) <= pw * 0.56 - 24:
            break
    lw = int(min(pw * 0.56, scratch.textlength(longest, font=lab) + 30))

    row_h = A4._h(lab) + 24
    head_h = A4._h(ttb) + A4._h(sml) + 26
    title_h = A4._h(hdb) + 20
    panel_h = title_h + rows * row_h
    H = head_h + panel_h + PAD * 2 + 4

    img = Image.new("RGB", (page_w, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((PAD, PAD), title or f"Month brief  ·  {asof:%B %Y}", font=ttb, fill=BAND)
    d.text((PAD, PAD + A4._h(ttb) + 6),
           subtitle or (f"as of {asof:%d %b %Y}  ·  yesterday = {asof:%d %b}  ·  "
                        f"updates every day"), font=sml, fill=SUB)

    def centre(x0, x1, y, h, text, font, ink):
        w = d.textlength(text, font=font)
        d.text((x0 + (x1 - x0 - w) / 2, y + (h - A4._h(font)) / 2 - 1),
               text, font=font, fill=ink)

    y0 = PAD + head_h
    for i, (name, lines) in enumerate(panels):
        x0 = PAD + i * (pw + GAP)
        x1, x2 = x0 + lw, x0 + pw
        # the green bar spans both columns, like the sheet's merged title cell
        d.rectangle([x0, y0, x2, y0 + title_h], fill=GREEN, outline=GRID, width=2)
        centre(x0, x2, y0, title_h, name.upper(), hdb, INK)
        y = y0 + title_h
        for text, value, style in lines:
            fill, fill_label, ink = _ROW_STYLE[style]
            d.rectangle([x0, y, x1, y + row_h],
                        fill=(fill if fill_label else WHITE), outline=GRID, width=2)
            d.rectangle([x1, y, x2, y + row_h], fill=fill, outline=GRID, width=2)
            centre(x0, x1, y, row_h, text, lab, INK)
            centre(x1, x2, y, row_h, value, labb, ink)
            y += row_h
    return img


def build(L, PL, df, pf, asof=None, only=None):
    """(filename, PNG bytes) for the day.

    `only` draws a single panel — "East" or "South" — so each region can be
    downloaded on its own. Both are computed either way: the figures come from
    the same call, so a single-region card can never disagree with the pair.
    """
    asof = pd.Timestamp(PL.as_of(pf) if asof is None else asof)
    # ★ EAST'S G/D IS LIKE TO LIKE ON BOTH LINES (Manav, 4 Sep 2026): *"the
    # east growth degrowth needs to be L2L ... for both mtd and ytd"*. It was
    # the GD sheet's `2526FY` subtotal until then — see `_gd_l2l` for what
    # changed and why the two differ.
    e_m, e_y = _gd_l2l(PL, pf, "East & NE", asof)

    east = pf[pf["region"] == "East & NE"]
    south = df[df[L.COL_REGION] == "South"]

    # South's year is counted from the TAKEOVER, not from 1 April — that is
    # what makes its YTD tie to the workbook (9.33%, not 9.05%).
    tk = pd.Timestamp(2026, 4, 19)
    fy = asof.year if asof.month >= 4 else asof.year - 1
    start = max(pd.Timestamp(fy, 4, 1), tk)
    s_y_cur = south[(south["date"] >= start) & (south["date"] <= asof)][L.COL_AMOUNT].sum()
    s_y_pri = south[(south["date"] >= start - pd.DateOffset(years=1))
                    & (south["date"] <= asof - pd.DateOffset(years=1))][L.COL_AMOUNT].sum()
    # ★★ MTD IS COMPARED AGAINST THE SAME DAYS, NOT THE WHOLE OF LAST MONTH
    # (Manav, 3 Sep). This ran two days of September 2026 against all thirty of
    # September 2025 and printed South at -94.87% — a store group that is
    # actually UP 14.13% on the same two days. Not a rounding error: the sign
    # was wrong. It stayed invisible through August because the month was
    # complete, so the two windows happened to be the same length. The East
    # panel never had the fault; its figure comes from the GD sheet, whose MTD
    # window has always been like-for-like.
    s_m_cur = south[(south["date"] >= asof.replace(day=1))
                    & (south["date"] <= asof)][L.COL_AMOUNT].sum()
    _lm = asof.replace(day=1) - pd.DateOffset(years=1)
    s_m_pri = south[(south["date"] >= _lm)
                    & (south["date"] <= asof - pd.DateOffset(years=1))][L.COL_AMOUNT].sum()
    g = lambda a, b: ((a - b) / b * 100) if b else None

    import targets as TG
    tgt = TG.load()
    def _tgt(codes):
        if tgt is None or tgt.empty:
            return None
        col = f"{asof:%b}".upper()
        c = next((c for c in tgt.columns if str(c).upper().startswith(col)), None)
        if c is None:
            return None
        t = tgt[tgt["code"].isin(codes)][c]
        return float(pd.to_numeric(t, errors="coerce").sum()) or None

    # ★★ THE TARGET MUST COVER THE SAME ESTATE AS THE SALES BESIDE IT (Manav,
    # 2 Sep: "in the target new tab, the east target reconciles, so why dont
    # you have that"). It did reconcile — the tab was right and the store list
    # was mine. The East panel reads the PORTFOLIO feed, 55 stores of every
    # brand, and I was picking codes from the VFL master, which knows only the
    # 22 Manyavar/Mohey ones. Fourteen stores' targets against fifty-five
    # stores' sales: Rs 2.41 Cr where the workbook says Rs 5.24 Cr, and East
    # read as Rs 1.58 Cr AHEAD of a target it was Rs 1.24 Cr behind.
    #
    # South is eight stores in both masters, so it tied either way and hid the
    # fault — which is exactly why the panel's own feed now chooses the list.
    import os
    _pm = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "portfolio_store_master.csv")
    master = pd.read_csv(_pm)
    master["code"] = pd.to_numeric(master["code"], errors="coerce")
    _codes = lambda r: set(master[master["region"] == r]["code"].dropna().astype(int))
    e_codes, s_codes = _codes("East & NE"), _codes("South")

    panels = [
        panel(L, "PRPL East", east, "sales", asof, e_m, e_y, _tgt(e_codes)),
        panel(L, "PRPL South", south, L.COL_AMOUNT, asof,
              g(s_m_cur, s_m_pri), g(s_y_cur, s_y_pri), _tgt(s_codes)),
    ]
    if only:
        want = "PRPL East" if str(only).lower().startswith("e") else "PRPL South"
        panels = [p for p in panels if p[0] == want]
        stem = f"month_brief_{want.split()[1].lower()}_{asof:%Y-%m-%d}"
    else:
        stem = f"month_brief_{asof:%Y-%m-%d}"
    img = _draw(panels, asof)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return (f"{stem}.png", buf.getvalue())


# --------------------------------------------------------------------------- #
# The festive run-up card — the same block, counted over a festival window
# instead of a calendar month (Manav, 12 Sep 2026, with the Puja 45 screenshot).
#
# Every line is the month card's line with the month swapped for the window, so
# the two cards are the same object read over two different spans:
#
#   month  : 1 Sep -> today,  against the whole of Sep last year
#   festive: window start -> today, against the SAME elapsed days last year
#
# ★ THE COMPARISON IS LIKE TO LIKE, and it has to be. `Window.ly_cut` is last
# year's window truncated to the days this year has actually traded. Comparing
# day 7 of 45 against last year's full 45 is the same fault that printed South
# at -94.87% when it was up 14.13% (see `build` below) — a whole window as the
# denominator makes every run-up read as a collapse until the last day.
#
# ★ `Puja Trending` extrapolates the daily average across the FULL tenure, which
# is what the workbook does. `Shortfall` is measured against last year's whole
# window, because that is the number the season is trying to beat.
# --------------------------------------------------------------------------- #
def festive_panel(L, name, d, amt, w, asof, gd_ytd, gd=None):
    """One festive block as (name, rows), in the workbook's order.

    `gd` arrives computed, exactly as `panel` receives `gd_mtd`/`gd_ytd`. It is
    a LIKE TO LIKE rate and cannot be worked out from `d` alone — it needs each
    store's comparable span — so the caller owns it and this function only
    lays it out. See `gd_l2l_window`.
    """
    asof = pd.Timestamp(asof)
    elapsed = max(int(w.elapsed), 0)
    left = max(int(w.tenure) - elapsed, 0)

    ly_full = d[(d["date"] >= w.ly_start) & (d["date"] <= w.ly_end)][amt].sum()
    ty_td = d[(d["date"] >= w.ty_start) & (d["date"] <= w.ty_cut)][amt].sum()

    avg = ty_td / elapsed if elapsed else 0.0
    trending = avg * w.tenure
    short_ly = ly_full - ty_td
    yest = d[d["date"] == asof][amt].sum()
    done = "window complete"

    fest = w.festival
    ly_yr, ty_yr = w.ly_end.year, w.ty_end.year
    return name, [
        (f"{fest} {w.tenure} Days {ly_yr} Achieved", _money(ly_full), "achieved"),
        (f"{fest} {ty_yr} Till Date", _money(ty_td), "tilldate"),
        (f"{fest} {ty_yr} Till Date Avg", _money(avg), "derived"),
        (f"{fest} Trending", _money(trending), "derived"),
        (f"Shortfall Vs {fest} {ly_yr}", _money(short_ly), "plain"),
        ("No of days left", f"{left}", "days"),
        ("Average Req. Daily",
         _money(short_ly / left) if left > 0 else done, "derived"),
        ("Yesterday Total Sale", _money(yest), "yesterday"),
        ("G/D", _pct(gd), "plain"),
        ("Ytd G/D", _pct(gd_ytd), "plain"),
    ]


def gd_l2l_window(frame, key, amt, bounds, w):
    """A festive window's G/D on the LIKE TO LIKE basis (Manav, 13 Sep 2026).

    ★ SAME DAYS WAS NOT ENOUGH. The first cut compared this year's elapsed days
    against the same elapsed days of last year's window across EVERY store —
    which is like to like on the calendar but not on the estate. A store that
    opened since last Puja put its whole run-up into this year with nothing
    behind it; a store that has closed put last year's run-up in with nothing
    in front. Neither is growth, and both move the number.

    Comparable stores means the same rule the rest of the report already uses:
    `l2l_bounds` gives each store the span it has BOTH years, and `l2l_frames`
    clips each side to it. Nothing is dropped wholesale — a store contributes
    the part of the window it can be compared over.

    `bounds` are in this year's dates and the prior side is shifted back a year,
    which is why this works even though a festival MOVES: last year's Puja
    window sits ~18 days earlier than this year's minus a year, but a store's
    comparable span is a span, not a window, so the clip lands correctly on
    either.
    """
    import exec_snapshot as ES
    cur = frame[(frame["date"] >= w.ty_start) & (frame["date"] <= w.ty_cut)]
    pri = frame[(frame["date"] >= w.ly_start) & (frame["date"] <= w.ly_cut)]
    if cur.empty and pri.empty:
        return None
    c, p = ES.l2l_frames(cur, pri, bounds, key)
    ty, ly = c[amt].sum(), p[amt].sum()
    return ((ty - ly) / ly * 100) if ly else None


# How long a finished run-up stays on the tab. Its final card is the season's
# result and is most wanted the morning after it closes — but `started` alone
# is true forever, so without a cut-off Durga Puja would still be on screen in
# February, beside Diwali, both claiming to be current.
FINISHED_GRACE_DAYS = 7


def festive_windows_started(asof, windows=None, grace=FINISHED_GRACE_DAYS):
    """The run-ups worth drawing on `asof`, soonest to finish first.

    Included when the window has OPENED and has not been closed longer than
    `grace` days.

    ★ NOT SIMPLY `w.started`. That is `elapsed > 0`, which stays true for the
    rest of the season once a window opens, so a finished festival never left
    the tab — measured: on 21 Oct, the day after Durga Puja ends, all four
    cards were still shown as though both festivals were running.

    ★ ORDER IS BY END DATE, not by tenure. The run-up closing soonest is the
    one there is still time to act on; sorting by length put Diwali 45 above a
    Durga Puja that had eight days left. Within a festival the 45 leads its 30,
    which is how the workbook reads them.
    """
    import festive as F
    ws = F.festive_windows(asof=asof) if windows is None else windows
    asof = pd.Timestamp(asof)
    keep = [w for w in ws
            if w.started and (asof - pd.Timestamp(w.ty_end)).days <= grace]
    return sorted(keep, key=lambda w: (pd.Timestamp(w.ty_end), -w.tenure))


def build_festive(L, PL, df, pf, asof=None, only=None, window=None):
    """(filename, PNG bytes) for the festive run-up card, or None if no window
    is open. Same estates as the month card: East reads the portfolio, South
    reads the VFL feed."""
    asof = pd.Timestamp(PL.as_of(pf) if asof is None else asof)
    w = window
    if w is None:
        started = festive_windows_started(asof)
        if not started:
            return None
        w = started[0]

    # The YTD lines are the month card's, computed the same way from the same
    # call, so the two cards can never print different years.
    e_m, e_y = _gd_l2l(PL, pf, "East & NE", asof)
    east = pf[pf["region"] == "East & NE"]
    south = df[df[L.COL_REGION] == "South"]

    tk = pd.Timestamp(2026, 4, 19)
    fy = asof.year if asof.month >= 4 else asof.year - 1
    start = max(pd.Timestamp(fy, 4, 1), tk)
    s_cur = south[(south["date"] >= start) & (south["date"] <= asof)][L.COL_AMOUNT].sum()
    s_pri = south[(south["date"] >= start - pd.DateOffset(years=1))
                  & (south["date"] <= asof - pd.DateOffset(years=1))][L.COL_AMOUNT].sum()
    s_y = ((s_cur - s_pri) / s_pri * 100) if s_pri else None

    # ★ THE WINDOW G/D IS LIKE TO LIKE, ON BOTH PANELS (Manav, 13 Sep 2026).
    # Each side uses its OWN feed's spans — the portfolio is keyed by code, the
    # VFL feed by store label — via the same two helpers the rest of the report
    # compares over, so there is one definition of "comparable" here and not a
    # third written for this card. See [[feedback-same-estate]].
    import exec_snapshot as ES
    e_bounds = ES.l2l_bounds(east, "code", "sales", PL.closed_map(), asof,
                             opened=PL.opened_map(east, asof))
    e_gd = gd_l2l_window(east, "code", "sales", e_bounds, w)
    try:
        s_bounds = L._l2l_spans_vfl(south, asof)
        s_gd = gd_l2l_window(south, L.COL_STORE_LABEL, L.COL_AMOUNT, s_bounds, w)
    except Exception:
        # The VFL spans raise loudly when no store matches the master rather
        # than silently spanning everything. A card that cannot state a
        # comparable rate must print a dash, not an incomparable number.
        s_gd = None

    panels = [
        festive_panel(L, "PRPL East", east, "sales", w, asof, e_y, gd=e_gd),
        festive_panel(L, "PRPL South", south, L.COL_AMOUNT, w, asof, s_y, gd=s_gd),
    ]
    slug = w.festival.lower().replace(" ", "-")
    if only:
        want = "PRPL East" if str(only).lower().startswith("e") else "PRPL South"
        panels = [p for p in panels if p[0] == want]
        stem = f"{slug}{w.tenure}_{want.split()[1].lower()}_{asof:%Y-%m-%d}"
    else:
        stem = f"{slug}{w.tenure}_{asof:%Y-%m-%d}"

    img = _draw(panels, asof,
                title=f"{w.festival} run-up  ·  {w.tenure} days",
                # `Window.basis()` writes an arrow the card font has no glyph
                # for, and a missing glyph draws as a tofu box — the sheet
                # would ship with a blank square in the middle of its own date
                # range. Swapped here rather than in `festive`, whose caption
                # is HTML on the reports tab and renders the arrow correctly.
                subtitle=(f"{w.basis().replace(chr(0x2192), '->')}"
                          f"  ·  as of {asof:%d %b %Y}  ·  "
                          f"yesterday = {asof:%d %b}"))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return (f"{stem}.png", buf.getvalue())


def write(out="out_a4"):
    import loader as L, portfolio_loader as PL, os
    df, pf = L.load_data(), PL.load_portfolio()
    name, data = build(L, PL, df, pf)
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, name)
    open(p, "wb").write(data)
    return p
