"""The festive run-up pack, rebuilt for the admin desk (7 Sep 2026).

Manav: *"nothing really changed… give me something fresh, which makes it easier
for us in admin to look and understand this data."* The previous pack was four
dense grids: a 45-row ladder, then 58, 69 and 71 rows of stores, brands and
locations. Every figure was there and none of it could be SEEN — an admin had
to read a number, hold it, read its neighbour, and do the sum.

Three things are different here, and all three are about reading rather than
about content. Nothing has been dropped: every row of every sheet is still
printed.

  1. THE SEASON IS DRAWN BEFORE IT IS TABULATED. A cumulative curve of both
     years answers "are we ahead, and is the gap opening or closing" in one
     look — the question the ladder made you compute forty-five times.

  2. EVERY TABLE CARRIES AN INLINE BAR. The eye ranks bars; it cannot rank
     eight-digit rupee figures without reading each one. The numbers stay
     beside the bar for anyone who needs the exact value.

  3. TABLES ARE ORDERED BY WHAT THEY CONTRIBUTE, biggest first, instead of by
     a NEW/OLD grouping — an admin scanning for where the season is being won
     or lost should not have to look for it.

★ AND THE G/D COLUMN IS COLOURED, NOT JUST SIGNED. Red below zero, green above,
which is the one place in this pack where a direction is unambiguous.
"""
from __future__ import annotations

import math

import pandas as pd
from PIL import Image, ImageDraw

import portfolio_pdf as PP

GOOD = (31, 107, 74)
BAD = (163, 22, 31)
BAR_TY = PP.HDR_BG
# a wash, not a fill: the column has to be findable without shouting over the
# figures printed on it
SHADE = (235, 245, 250)
SHADE_HEAD = (198, 226, 238)
BAR_LY = (226, 226, 226)
RULE = (200, 200, 200)


def _hh(f):
    a, b = f.getmetrics()
    return a + b


def money(v, dp=2):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if abs(v) >= 1e7:
        return f"{v / 1e7:,.{dp}f} Cr"
    if abs(v) >= 1e5:
        return f"{v / 1e5:,.{dp}f} L"
    return f"{v:,.0f}"


def _text(d, xy, s, font, fill=PP.INK, right=None):
    if right is not None:
        xy = (right - d.textlength(str(s), font=font), xy[1])
    d.text(xy, str(s), font=font, fill=fill)


# --------------------------------------------------------------------------- #
#  Charts                                                                      #
# --------------------------------------------------------------------------- #
def cumulative_chart(width, height, w, ty_days, ly_days):
    """Both years' running totals across the run-up.

    ★ THE ONE PICTURE AN ADMIN ACTUALLY NEEDS. Last year's curve is the whole
    season, drawn to its end; this year's stops where the data stops, so the
    space between the two ends IS the gap still to be closed. A ladder of forty
    five rows says the same thing and nobody can see it.
    """
    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    lab, labb = PP._ft(24)
    tick, _ = PP._ft(19)

    n = int(w.tenure)
    ly = [float(ly_days.get(w.ly_start + pd.Timedelta(days=i), 0.0))
          for i in range(n)]
    ty = [float(ty_days.get(w.ty_start + pd.Timedelta(days=i), 0.0))
          for i in range(n)]
    elapsed = int(w.elapsed)

    def run(v, upto):
        out, acc = [], 0.0
        for i in range(upto):
            acc += v[i]
            out.append(acc)
        return out

    ly_run, ty_run = run(ly, n), run(ty, max(elapsed, 1))
    peak = max(max(ly_run or [1]), max(ty_run or [1]), 1.0)

    pad_l, pad_r = PP._px(112), PP._px(20)
    pad_t, pad_b = PP._px(16), PP._px(52)
    x0, x1 = pad_l, width - pad_r
    y0, y1 = pad_t, height - pad_b

    def X(i):
        return x0 + (x1 - x0) * (i / max(n - 1, 1))

    def Y(v):
        return y1 - (y1 - y0) * (v / peak)

    # gridlines with money labels, so the curve can be read off
    for k in range(5):
        v = peak * k / 4
        y = Y(v)
        d.line([(x0, y), (x1, y)], fill=RULE, width=1)
        _text(d, (0, y - _hh(tick) / 2), money(v, 1), tick, (140, 140, 140),
              right=x0 - PP._px(10))

    ly_pts = [(X(i), Y(v)) for i, v in enumerate(ly_run)]
    d.line(ly_pts, fill=(150, 150, 150), width=PP._px(3))
    if len(ty_run) > 1:
        d.line([(X(i), Y(v)) for i, v in enumerate(ty_run)],
               fill=PP.GRID, width=PP._px(5))
    elif ty_run:
        r = PP._px(6)
        d.ellipse([X(0) - r, Y(ty_run[0]) - r, X(0) + r, Y(ty_run[0]) + r],
                  fill=PP.GRID)

    # where this year has reached, and the day it is
    if ty_run:
        xe = X(len(ty_run) - 1)
        d.line([(xe, y0), (xe, y1)], fill=(120, 120, 120), width=1)

    for i in range(0, n, 7):
        dt = w.ty_start + pd.Timedelta(days=i)
        d.line([(X(i), y1), (X(i), y1 + PP._px(6))], fill=RULE, width=1)
        _text(d, (X(i) - PP._px(26), y1 + PP._px(10)), f"{dt:%d %b}", tick,
              (140, 140, 140))
    d.line([(x0, y1), (x1, y1)], fill=PP.GRID, width=2)

    # ★ THE LEGEND NAMES ONLY THE LINES THAT ARE DRAWN.
    if ty_run:
        _text(d, (x0 + PP._px(8), y0), "this year", labb, PP.INK)
        _text(d, (x0 + PP._px(8), y0 + _hh(labb)), "last year", lab,
              (150, 150, 150))
    else:
        _text(d, (x0 + PP._px(8), y0), "last year", labb, (120, 120, 120))
    return img


def daily_chart(width, height, w, ty_days, ly_days):
    """Each day of the run-up, both years, side by side."""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    tick, _ = PP._ft(18)
    n = int(w.tenure)
    ly = [float(ly_days.get(w.ly_start + pd.Timedelta(days=i), 0.0))
          for i in range(n)]
    ty = [float(ty_days.get(w.ty_start + pd.Timedelta(days=i), 0.0))
          for i in range(n)]
    peak = max(max(ly or [1]), max(ty or [1]), 1.0)
    pad_b = PP._px(46)
    base = height - pad_b
    slot = width / n
    bw = max(int(slot * 0.40), 2)
    for i in range(n):
        x = int(i * slot)
        if ly[i] > 0:
            h = int((base) * ly[i] / peak)
            d.rectangle([x, base - h, x + bw, base], fill=BAR_LY)
        if ty[i] > 0:
            h = int((base) * ty[i] / peak)
            d.rectangle([x + bw + 1, base - h, x + 2 * bw + 1, base],
                        fill=BAR_TY, outline=PP.GRID)
        if i % 7 == 0 or i == n - 1:
            dt = w.ty_start + pd.Timedelta(days=i)
            _text(d, (x, base + PP._px(8)), f"{dt:%d %b}", tick, (140, 140, 140))
            _text(d, (x, base + PP._px(8) + _hh(tick)), f"{dt:%a}"[:2], tick,
                  (170, 170, 170))
    d.line([(0, base), (width, base)], fill=PP.GRID, width=2)
    return img


# --------------------------------------------------------------------------- #
#  A table whose rows can be RANKED BY EYE                                     #
# --------------------------------------------------------------------------- #
# ★ THE BAR IS THE POINT. Eight-digit rupee figures cannot be compared without
# reading each one; a bar of the same value is compared without reading at all.
# The exact number stays beside it, so nothing is lost to anyone who needs it.
def table_image(df, spec, width, font_px=26, bar_col=None, bar_label="",
                total_row=None, shade=()):
    """`spec` is [(column, kind, header)] with kind in
    text | money | pct | int | bar.

    `shade` is a set of COLUMN POSITIONS to tint down the whole table — the one
    an admin should land on first. Positions, not column keys, because a key
    can legitimately appear twice (a value and its bar).
    """
    reg, bold = PP._ft(font_px)
    hreg, hbold = PP._ft(max(int(font_px * 0.86), 12))
    pad_x, pad_y = PP._px(10), PP._px(7)
    row_h = _hh(reg) + pad_y * 2
    head_h = _hh(hbold) * 2 + pad_y * 2
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def fmt(kind, v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        if kind == "money":
            return money(v)
        if kind == "pct":
            return f"{v:,.1f}%"
        if kind == "int":
            return f"{int(v):,}"
        return str(v)

    txt = [[fmt(k, r.get(c)) for c, k, _ in spec] for r in df]
    if total_row is not None:
        txt.append([fmt(k, total_row.get(c)) for c, k, _ in spec])

    # width: data drives it, header wraps into it
    widths = []
    for j, (c, k, head) in enumerate(spec):
        if k == "bar":
            widths.append(int(width * 0.16))
            continue
        w_data = max([scratch.textlength(t[j], font=bold) for t in txt] or [0])
        w_head = max(scratch.textlength(p, font=hbold)
                     for p in head.split("\n"))
        widths.append(int(max(w_data, w_head)) + pad_x * 2)
    over = sum(widths) - width
    if over > 0:                      # give it back from the widest text column
        j = max(range(len(spec)),
                key=lambda i: widths[i] if spec[i][1] == "text" else 0)
        widths[j] = max(widths[j] - over, PP._px(120))
    elif over < 0:
        # ★ SPREAD THE SLACK, DO NOT DUMP IT. Giving every spare pixel to the
        # single widest text column made the ladder's date cell enormous, with
        # the date pinned left and the weekday pinned right — two fields that
        # belong together reading as two columns.
        text_cols = [i for i, sp in enumerate(spec) if sp[1] == "text"]
        if text_cols:
            each = (-over) // len(text_cols)
            for i in text_cols:
                widths[i] += each
            widths[text_cols[0]] += (-over) - each * len(text_cols)

    rows_n = len(txt)
    img = Image.new("RGB", (sum(widths), head_h + row_h * rows_n),
                    (255, 255, 255))
    d = ImageDraw.Draw(img)
    W = sum(widths)

    # ★ THE COLUMN AN ADMIN SHOULD LOOK AT FIRST, TINTED DOWN THE WHOLE TABLE
    # (Manav, 7 Sep: *"for this year comparable, shade it a little so its clear
    # where to look"*). Drawn BEFORE the header and again per row, because the
    # zebra banding would otherwise paint over it every other line.
    shade = set(shade)
    xs = []
    _acc = 0
    for wdt in widths:
        xs.append(_acc)
        _acc += wdt
    for j in shade:
        d.rectangle([xs[j], 0, xs[j] + widths[j], head_h + row_h * rows_n],
                    fill=SHADE)

    d.rectangle([0, 0, W, head_h], fill=PP.HDR_BG)
    for j in shade:
        d.rectangle([xs[j], 0, xs[j] + widths[j], head_h], fill=SHADE_HEAD)
    x = 0
    for j, (c, k, head) in enumerate(spec):
        lines = head.split("\n")
        y = head_h - pad_y - len(lines) * _hh(hbold)
        for ln in lines:
            _text(d, (x + widths[j] - pad_x, y), ln, hbold, PP.INK,
                  right=x + widths[j] - pad_x) if k != "text" else \
                _text(d, (x + pad_x, y), ln, hbold, PP.INK)
            y += _hh(hbold)
        x += widths[j]

    peak = 1.0
    if bar_col is not None:
        def _bv(r):
            v = r.get(bar_col)
            # ★ `or 0` DOES NOT CATCH NaN — NaN is truthy, so an unreached day
            # in the ladder came through as NaN and `int()` raised on it.
            return 0.0 if v is None or pd.isna(v) else abs(float(v))

        vals = [_bv(r) for r in df]
        peak = max(vals + [1.0])

    y = head_h
    for i in range(rows_n):
        is_total = total_row is not None and i == rows_n - 1
        if is_total:
            d.rectangle([0, y, W, y + row_h], fill=PP.TOTAL_BG)
        elif i % 2 == 1:
            # ★ A BAND EVERY OTHER ROW. Seventy rows of white with a grid is
            # where an eye loses its place and reads two stores as one.
            d.rectangle([0, y, W, y + row_h], fill=(248, 250, 251))
        for j in shade:
            if not is_total:
                d.rectangle([xs[j], y, xs[j] + widths[j], y + row_h],
                            fill=SHADE)
        x = 0
        src = total_row if is_total else df[i]
        for j, (c, k, _h) in enumerate(spec):
            f = bold if is_total else reg
            if k == "bar" and not is_total:
                _raw = src.get(bar_col)
                v = (0.0 if _raw is None or pd.isna(_raw) else float(_raw))
                bw = int((widths[j] - pad_x * 2) * abs(v) / peak)
                by = y + pad_y + PP._px(2)
                bh = row_h - pad_y * 2 - PP._px(4)
                d.rectangle([x + pad_x, by, x + pad_x + max(bw, 1), by + bh],
                            fill=BAD if v < 0 else BAR_TY)
            elif k != "bar":
                ink = PP.INK
                if k == "pct" and txt[i][j]:
                    val = src.get(c)
                    if val is not None and not pd.isna(val):
                        ink = BAD if val < 0 else (GOOD if val > 0 else PP.INK)
                if k == "text":
                    _text(d, (x + pad_x, y + pad_y), txt[i][j], f, ink)
                else:
                    _text(d, (0, y + pad_y), txt[i][j], f, ink,
                          right=x + widths[j] - pad_x)
            x += widths[j]
        d.line([(0, y), (W, y)], fill=RULE, width=1)
        y += row_h
    d.rectangle([0, 0, W - 1, head_h + row_h * rows_n - 1], outline=PP.GRID)
    return img


# --------------------------------------------------------------------------- #
#  The pack                                                                    #
# --------------------------------------------------------------------------- #
def classify(pf, f, w):
    """Split the estate into a genuine like-for-like set and everything else.

    Manav, 7 Sep: *"for east bifurcate L2L and no L2L seperately for a genuine
    comparision. and for this report, we want south data in the no l2l only.
    make the required adjustments for stores that closed too, because they will
    also skew the data."*

    ★★ MEMBERSHIP IS DECIDED ON `ly_full`, NOT ON `ly`. `ly` is only the days
    ELAPSED of last year's window — on day one of the run-up it is a single
    day, and 36 of these stores had a sale on it against 44 that traded the
    window. Deciding L2L on `ly` would have called eight established stores
    "new" this morning and quietly re-admitted them next week, so the same
    store would move between sections as the season ran and no two days' packs
    would agree. `ly_full` is the whole of last year's window and does not
    move.

    ★ A CLOSED STORE IS NEVER LIKE-FOR-LIKE. It has last year and cannot have
    this year, so it drags the comparison down by exactly its own history —
    four of them here, carrying Rs 36.3 L of last year's run-up between them.
    That figure was also inflating the target: "match last year's Rs 9.87 Cr"
    included shops that no longer exist. The like-for-like target is Rs 9.19 Cr.

    ★ SOUTH FALLS OUT ON ITS OWN, and that is worth saying rather than
    hard-coding. Those eight stores have no history in this feed at all, so
    `ly_full` is zero and they land in the non-comparable set by the same rule
    as any new store. Nothing about the region is special-cased.
    """
    f = f.copy()

    # ★★ THE STORES THAT ARE NOT IN `store_figures` AT ALL. It is built off the
    # active-store list — stores that have traded THIS fiscal year — so ten
    # shops that shut during FY25-26 never appear, and with them Rs 31.87 L of
    # last year's Durga Puja run-up. They traded that run-up; leaving them out
    # does not make the comparison cleaner, it makes the CLOSED column wrong
    # and the three columns stop summing to the estate. They are added back
    # here, with this year at zero, which is the truth about them.
    # (Same family as the Rs 1.30 Cr the active-store filter drops from the
    # year-on-year — see [[project-manyavar-open-items]].)
    win = pf[(pf["date"] >= w.ly_start) & (pf["date"] <= w.ly_end)]
    ly_by = win.groupby("code")["sales"].sum()
    # ★ AND THEIR LAST YEAR OVER THE ELAPSED DAYS TOO. `ly` was hard-set to 0
    # for these, which was fine while nothing added it up — the moment the
    # rollups gained a TOTAL LAST YEAR column it would have silently dropped
    # their share of it.
    cut = pf[(pf["date"] >= w.ly_start) & (pf["date"] <= w.ly_cut)]
    ly_cut_by = cut.groupby("code")["sales"].sum()
    missing = [c for c, v in ly_by.items()
               if c not in set(f["code"]) and v > 0]
    if missing:
        idx = pf.drop_duplicates("code").set_index("code")
        extra = []
        for c in missing:
            r = idx.loc[c]
            extra.append({
                "code": c, "new_old": "", "store": str(r.get("brand") or "—"),
                "location": str(r.get("location") or ""),
                # ★ NAMED, NOT BLANK. These shops predate the active-store list,
                # so the feed carries no parent for them. An empty key rolled
                # them into a "(not recorded)" bucket on the brand sheet, which
                # reads as missing data rather than as the fact it is. The
                # LOCATION is real and is used, so they still roll up properly
                # there.
                "parent": "(closed before this year)",
                "location_tl": str(r.get("city") or ""),
                "closed": "gone", "doo": "",
                "ly": float(ly_cut_by.get(c, 0.0)), "ty": 0.0,
                "ly_full": float(ly_by[c]), "day": 0.0, "projected": 0.0,
                "gd": None})
        f = pd.concat([f, pd.DataFrame(extra)], ignore_index=True)

    reg = pf.drop_duplicates("code").set_index("code")["region"]
    f["region"] = f["code"].map(reg)
    f["shut"] = f["closed"].replace("", pd.NA).notna()
    f["has_ly"] = f["ly_full"] > 0
    f["l2l"] = f["has_ly"] & ~f["shut"]
    f["why"] = ""
    f.loc[~f["has_ly"], "why"] = "no last year"
    f.loc[f["shut"], "why"] = "closed " + f["closed"].astype(str)
    f.loc[f["closed"] == "gone", "why"] = "closed before this year"
    return f


def daily_for(pf, codes, w):
    """(this year, last year) daily takings for a set of stores."""
    d = pf[pf["code"].isin(list(codes))]
    s = d.groupby("date")["sales"].sum()
    return s, s


def figures_for(pf, codes, w):
    """The run-up figures for a subset of the estate."""
    d = pf[pf["code"].isin(list(codes))]
    s = d.groupby("date")["sales"].sum()
    ty = s[(s.index >= w.ty_start) & (s.index <= w.ty_cut)]
    ly_all = s[(s.index >= w.ly_start) & (s.index <= w.ly_end)]
    ly_cut = s[(s.index >= w.ly_start) & (s.index <= w.ly_cut)]
    elapsed = max(int(w.elapsed), 1)
    left = max(int(w.tenure) - elapsed, 0)
    ty_sum, ly_sum, ly_full = float(ty.sum()), float(ly_cut.sum()), float(ly_all.sum())
    return {"ty": ty_sum, "ly": ly_sum, "ly_full": ly_full,
            "elapsed": elapsed, "left": left, "tenure": int(w.tenure),
            "growth": ((ty_sum - ly_sum) / ly_sum * 100) if ly_sum else None,
            "need": ((ly_full - ty_sum) / left) if left else None,
            "run_rate": ty_sum / elapsed,
            "ty_days": ty, "ly_days": ly_all}


def _rows(df, keys):
    return [{k: r[k] for k in keys if k in r} for _, r in df.iterrows()]


def ladder_rows(pf, f, w):
    """The day ladder, each year split three ways.

    Manav, 7 Sep: *"Divide both data in 3 col — L2L / No L2L / closed. Compare
    only l2l."*

    ★★ THE THREE COLUMNS ARE THE ARGUMENT, NOT DECORATION. A closed store has
    last year and cannot have this year, so its column is full on the left and
    empty on the right — the asymmetry is visible on every row, which is
    exactly why it must not be inside the comparison. A South store is the
    mirror image: nothing last year, real money this year. Only the L2L pair
    can be divided one by the other, so the G/D columns read from those and
    from nothing else.
    """
    g = {"l2l": set(f.loc[f["l2l"], "code"]),
         "new": set(f.loc[~f["l2l"] & ~f["shut"], "code"]),
         "shut": set(f.loc[f["shut"], "code"])}
    day = {k: pf[pf["code"].isin(v)].groupby("date")["sales"].sum()
           for k, v in g.items()}

    rows, ly_run, ty_run = [], 0.0, 0.0
    for i in range(int(w.tenure)):
        ld = w.ly_start + pd.Timedelta(days=i)
        td = w.ty_start + pd.Timedelta(days=i)
        reached = w.started and td <= w.ty_cut
        lv = {k: float(day[k].get(ld, 0.0)) for k in g}
        tv = {k: float(day[k].get(td, 0.0)) for k in g} if reached else {}
        ly_run += lv["l2l"]
        if reached:
            ty_run += tv["l2l"]
        ly_tot = lv["l2l"] + lv["new"] + lv["shut"]
        ty_tot = (tv["l2l"] + tv["new"] + tv["shut"]) if reached else None
        rows.append({
            "ly_total": ly_tot, "ty_total": ty_tot,
            "ly_non": (lv["new"] + lv["shut"]) or None,
            "ty_non": ((tv["new"] + tv["shut"]) or None) if reached else None,
            "ly_date": f"{ld:%d-%m-%Y}", "ly_day": f"{ld:%a}",
            "ly_l2l": lv["l2l"], "ly_new": lv["new"] or None,
            "ly_shut": lv["shut"] or None, "ly_run": ly_run,
            "ty_date": f"{td:%d-%m-%Y}" if reached else "",
            "ty_day": f"{td:%a}" if reached else "",
            "ty_l2l": tv.get("l2l") if reached else None,
            "ty_new": (tv.get("new") or None) if reached else None,
            # ★ A CLOSED STORE'S THIS-YEAR CELL IS BLANK, NEVER ZERO. Zero would
            # read as a shop that opened and took nothing.
            "ty_shut": (tv.get("shut") or None) if reached else None,
            "ty_run": ty_run if reached else None,
            "gd": (((tv["l2l"] - lv["l2l"]) / lv["l2l"] * 100)
                   if reached and lv["l2l"] else None),
            "rgd": (((ty_run - ly_run) / ly_run * 100)
                    if reached and ly_run else None),
        })
    return rows


def ladder_spec(rows):
    """The admin's own five, on each side.

    Manav relaying the admin desk, 7 Sep: *"Everywhere — Total, non comparable,
    comparable, running total, GD percentage… simple is better."*

    ★ SO THE COLUMNS ARE THE SAME ON BOTH SIDES. They used to differ by year —
    last year carried CLOSED, this year carried NO L2L — because that is what
    each year can structurally have. True, but it made the two halves of one
    row read as two different tables. Non-comparable is now ONE column on each
    side, and its make-up is on the store and rollup sheets where a name can be
    put to it.

    ★★ RUNNING IS THE COMPARABLE RUNNING, NOT THE RUNNING TOTAL, and that is
    deliberate. The G/D beside it divides comparable by comparable; if the
    running column were the whole estate, a reader dividing the two running
    figures would get a different number from the one printed next to them —
    and this year's total carries South while last year's cannot. Every figure
    on the row now ties to the one beside it.
    """
    return [("ly_date", "text", "LAST YEAR"), ("ly_day", "text", ""),
            ("ly_total", "money", "TOTAL"),
            ("ly_l2l", "money", "COMPARABLE"),
            ("ly_non", "money", "NON\nCOMPARABLE"),
            ("ly_run", "money", "RUNNING\nCOMPARABLE"),
            ("ty_date", "text", "THIS YEAR"), ("ty_day", "text", ""),
            ("ty_total", "money", "TOTAL"),
            ("ty_l2l", "money", "COMPARABLE"),
            ("ty_non", "money", "NON\nCOMPARABLE"),
            ("ty_run", "money", "RUNNING\nCOMPARABLE"),
            ("gd", "pct", "DAY G/D\nCOMPARABLE"),
            ("rgd", "pct", "RUNNING G/D\nCOMPARABLE")]


def rollup_rows(f, group):
    """One row per brand or location, split three ways.

    Manav, 7 Sep: *"now that we have separated the data we can get the south in
    NoL2l. for all the sheets with a no l2l column."*

    ★★ THE ROLLUPS WERE BUILT FROM THE LIKE-FOR-LIKE SET ALONE, so South was in
    the day ladder and in the not-comparable store table and NOWHERE in the
    brand or location sheets — Rs 32.89 L of this year's trade absent from two
    of the six pages. A dimension sheet that quietly covers a different estate
    from the sheet before it is the error this dashboard finds most often.
    Every store is in these now, and which of the three sets it belongs to is a
    COLUMN rather than a reason to leave it out.

    ★ AND ONLY THE L2L PAIR IS DIVIDED. `G/D` reads from L2L this year over L2L
    last year and from nothing else; the other two columns stand on their own
    because neither has a counterpart to be divided by.
    """
    out = {}
    for _, r in f.iterrows():
        k = str(r.get(group) or "").strip() or "(not recorded)"
        d = out.setdefault(k, {"name": k, "l2l_ty": 0.0, "l2l_ly": 0.0,
                               "new_ty": 0.0, "shut_ty": 0.0, "shut_ly": 0.0,
                               "shut_ly_full": 0.0,
                               "total_ty": 0.0, "total_ly": 0.0,
                               "n_l2l": 0, "n_new": 0, "n_shut": 0})
        ty, ly = float(r["ty"] or 0), float(r["ly"] or 0)
        if r["l2l"]:
            d["l2l_ty"] += ty
            d["l2l_ly"] += ly
            d["n_l2l"] += 1
        elif r["shut"]:
            # ★ THE ELAPSED WINDOW, matching `l2l_ly` beside it. `ly_full` is
            # the whole forty-five days and belongs on page one, not in a
            # column that gets added to a comparable one.
            d["shut_ly"] += ly
            d["shut_ly_full"] += float(r["ly_full"] or 0)
            # ★ AND ITS THIS-YEAR TRADE, IF IT HAS ANY. A store that shuts
            # mid-run-up trades part of it, and that money was landing in ALL
            # THIS YEAR and in none of the three split columns — so the split
            # would stop summing to the total the first season it happened.
            d["shut_ty"] += ty
            d["n_shut"] += 1
        else:
            d["new_ty"] += ty
            d["n_new"] += 1
        d["total_ty"] += ty
        d["total_ly"] += ly
    rows = list(out.values())
    for d in rows:
        d["non_ty"] = d["new_ty"] + d["shut_ty"]
        d["non_ly"] = d["shut_ly"]
        d["gd"] = (((d["l2l_ty"] - d["l2l_ly"]) / d["l2l_ly"] * 100)
                   if d["l2l_ly"] else None)
        d["stores"] = d["n_l2l"] + d["n_new"] + d["n_shut"]
    rows.sort(key=lambda d: -d["total_ty"])
    tot = {"name": "TOTAL", "stores": sum(d["stores"] for d in rows)}
    for k in ("l2l_ty", "l2l_ly", "new_ty", "shut_ty", "shut_ly",
              "shut_ly_full", "total_ty", "total_ly", "non_ty", "non_ly"):
        tot[k] = sum(d[k] for d in rows)
    tot["gd"] = (((tot["l2l_ty"] - tot["l2l_ly"]) / tot["l2l_ly"] * 100)
                 if tot["l2l_ly"] else None)
    return rows, tot


def rollup_spec(rows):
    """The ladder's own columns, for a brand / location / region row.

    Manav, 7 Sep: *"the admin format i gave you, apply it to all the tables.
    the region, brand, location. all these tables same format."*

    ★ SO EVERY TABLE IN THE PACK NOW READS THE SAME WAY: each year gives its
    TOTAL, its COMPARABLE and its NON COMPARABLE, and the only G/D is taken
    from the comparable pair. Somebody moving from the day ladder to the region
    sheet should not have to re-learn a layout.

    ★ AND ALL FOUR MONEY COLUMNS ARE ON THE SAME WINDOW — the days elapsed.
    Non-comparable's last year used to carry `ly_full`, the whole forty-five
    days, while comparable's carried the elapsed days; adding them for a total
    would have compared a fortnight against a season. The whole-run-up figure
    still exists, on page one and on the not-comparable store sheet, where it
    is not being added to anything.
    """
    return [("name", "text", "NAME"), ("stores", "int", "STORES"),
            ("total_ly", "money", "LAST YEAR\nTOTAL"),
            ("l2l_ly", "money", "LAST YEAR\nCOMPARABLE"),
            ("non_ly", "money", "LAST YEAR\nNON COMP"),
            ("total_ty", "money", "THIS YEAR\nTOTAL"),
            ("l2l_ty", "money", "THIS YEAR\nCOMPARABLE"),
            ("non_ty", "money", "THIS YEAR\nNON COMP"),
            ("total_ty", "bar", "SHARE"),
            ("gd", "pct", "G/D\nCOMPARABLE")]


def build(pf, w, basis_label="", vfl=False):
    """The whole run-up, as an admin pack. Every row, drawn to be read."""
    import snapshots_a4 as A4
    import snapshots as SN
    import festive as F
    import loader as L

    if vfl:
        f = F.vfl_figures(pf, w)
        sales = pf.groupby("date")[L.COL_AMOUNT].sum()
    else:
        f = F.store_figures(pf, w)
        sales = pf.groupby("date")["sales"].sum()
    f = classify(pf, f, w)
    l2l_codes = set(f.loc[f["l2l"], "code"])
    other_codes = set(f.loc[~f["l2l"], "code"])
    fig = figures_for(pf, l2l_codes, w)          # ★ the honest comparison
    oth = figures_for(pf, other_codes, w)
    asof = w.ty_cut

    _keep = (A4.MARGIN, A4.CONTENT_W, PP.PAD_Y)
    A4.MARGIN = A4.PRINT_MARGIN
    A4.CONTENT_W = A4.PAGE_W - 2 * A4.MARGIN
    try:
        W = A4.CONTENT_W
        pages = []

        # ---------- page 1: the season, drawn -----------------------------
        one = A4._Sheet(w.label, asof, "", bounded=False, footer=True)
        n_l2l = int(f["l2l"].sum())
        n_new = int((~f["has_ly"]).sum())
        n_shut = int(f["shut"].sum())
        # ★★ A RUN-UP THAT HAS NOT OPENED DOES NOT HAVE A DAY ONE. `elapsed` is
        # floored at 1 so the arithmetic never divides by zero, and that floor
        # was reaching the page: Diwali and the 30-day Durga window both printed
        # "day 1 of 30" with "29 days still to trade" for seasons opening in
        # fifteen and nineteen days. The pack is generated for every window in
        # the tab, so this is not an edge case — it is three of the four sheets
        # anyone builds today. A window that has not started says so, shows
        # last year as the plan, and claims no growth.
        started = bool(w.started)
        one.put(A4._heading(
            W, (f"{w.festival} run-up  ·  day {fig['elapsed']} of {fig['tenure']}"
                if started else
                f"{w.festival} run-up  ·  opens {w.ty_start:%d %b %Y}, "
                f"{(w.ty_start - asof).days} days from now"),
            f"{w.ty_start:%d %b} to {w.ty_end:%d %b %Y}  against  "
            f"{w.ly_start:%d %b} to {w.ly_end:%d %b %Y}  ·  "
            f"{basis_label or f'live to {asof:%d %b %Y}'}"), gap=20)
        g = fig["growth"]
        # ★★ THE HEADLINE IS THE LIKE-FOR-LIKE SET, and it says so. Comparing
        # this year's whole estate against last year's would put eight South
        # stores with no history on one side of the sum and nothing on the
        # other — the same-estate error, on the sheet that decides the season.
        one.put(SN._cards_image([
            ("Comparable — this year", "Rs " + money(fig["ty"]) if started
             else "not open yet"),
            ("Comparable — same days last year",
             "Rs " + money(fig["ly"]) if started else "—"),
            ("Growth" + ("  ·  early, weekday mix"
                         if started and fig["elapsed"] < 7 else ""),
             ("—" if g is None else f"{g:+,.1f}%") if started else "—"),
            ("Comparable stores", f"{n_l2l} of {len(f)}"),
        ], W, label_px=25, value_px=42), gap=14)
        one.put(SN._cards_image([
            ("Not comparable — this year", "Rs " + money(oth["ty"])),
            ("South, new and closed", f"{len(f) - n_l2l} stores"),
            ("Last year's run-up, comparable", "Rs " + money(fig["ly_full"])),
            ("Closed stores took", "Rs " + money(oth["ly_full"])),
        ], W, label_px=25, value_px=42), gap=18)
        one.put(A4._text_block(W, [(
            f"The comparison above is {n_l2l} East & NE stores that traded "
            f"both run-ups and are still open. The other {len(f) - n_l2l} are "
            f"held out: {n_new} with no last year at all — the eight South "
            f"stores among them — and {n_shut} closed, which carry "
            f"Rs {money(oth['ly_full'])} of last year that cannot be traded "
            f"again. Left in, those would drag the comparison down by their own "
            f"history and inflate the target by the same amount.",
            A4._ft(22)[0], A4.SUB)]), gap=16)
        one.put(A4._caption(
            W, "The season so far, like for like" if started
               else "Last year's run-up, like for like",
            (f"last year's line runs the whole {fig['tenure']} days; this "
             f"year's stops where the data stops, so the space between the two "
             f"ends is what is still to be closed" if started else
             f"last year's {fig['tenure']} days across the comparable stores — "
             f"there is no line for this year yet")), gap=10)
        one.put(cumulative_chart(W, PP._px(560), w, fig["ty_days"],
                                 fig["ly_days"]), gap=22)
        need = fig["need"] if started else None
        if not started:
            one.put(A4._text_block(W, [(
                f"This run-up has not opened. Everything below is LAST YEAR's "
                f"{fig['tenure']} days — the shape to expect and the figure to "
                f"beat. Across the {n_l2l} comparable stores it took "
                f"Rs {money(fig['ly_full'])}, which is "
                f"Rs {money(fig['ly_full'] / fig['tenure'])} a day.",
                A4._ft(27)[0], A4.INK)]), gap=20)
        if need is not None:
            one.put(A4._text_block(W, [(
                f"To match last year's run-up ACROSS THE COMPARABLE STORES "
                f"you need Rs {money(need)} a day for the remaining "
                f"{fig['left']} days. Those stores are running at "
                f"Rs {money(fig['run_rate'])} a day. The target excludes "
                f"Rs {money(oth['ly_full'])} taken last year by stores that "
                f"have since closed.",
                A4._ft(27)[0], A4.INK)]), gap=20)
        one.put(A4._caption(
            W, "Day by day", "last year pale, this year solid — the days ahead "
                             "are last year's, which is the shape to expect"),
                gap=10)
        one.put(daily_chart(W, PP._px(430), w, fig["ty_days"], fig["ly_days"]),
                gap=20)
        one._footers()
        pages += one.pages

        # ---------- page 2: the day ladder --------------------------------
        two = A4._Sheet(w.label, asof, "", bounded=False, footer=True)
        two.put(A4._heading(
            W, f"{w.festival} — every day of the run-up",
            f"all {fig['tenure']} days  ·  each year split into its total, "
            f"the comparable stores, and everything not comparable  ·  the "
            f"running and growth columns read from COMPARABLE ONLY"), gap=14)
        two.put(A4._text_block(W, [(
            "TOTAL is every store trading that day. COMPARABLE is the stores "
            "that traded both run-ups and are still open. NON COMPARABLE is "
            "everything else — South and new stores on this year's side, "
            "closed stores on last year's. RUNNING and both G/D columns are "
            "COMPARABLE ONLY, so every figure on a row ties to the one beside "
            "it: dividing two whole-estate running totals would compare a this "
            "year that carries South against a last year that cannot.",
            A4._ft(22)[0], A4.SUB)]), gap=14)
        _lrows = ladder_rows(pf, f, w)
        _lspec = ladder_spec(_lrows)
        # ★ BOTH SIDES OF THE COMPARISON ARE SHADED (Manav, 7 Sep). Shading
        # only this year's made the eye land on one half of a pair.
        _lshade = [i for i, (c, _k, h) in enumerate(_lspec)
                   if c in ("ty_l2l", "ly_l2l") and h == "COMPARABLE"]
        two.put(table_image(_lrows, _lspec, W, font_px=23, shade=_lshade),
                gap=20)
        two._footers()
        pages += two.pages

        # ---------- pages 3-5: stores, brands, locations -------------------
        s = f.copy()
        s["delta"] = s["ty"] - s["ly"]
        # ★ A STORE WITH NO TRADE EITHER WAY IS STILL PART OF THE ARITHMETIC IF
        # IT TRADED LAST YEAR'S RUN-UP. Filtering on `ty` or `ly` alone dropped
        # a closed Vega Circle Mall that has neither — and with it Rs 4.44 L of
        # last year — so the card said closed stores took Rs 36.32 L while the
        # table beneath it totalled Rs 31.88 L. Two figures on one page
        # describing different sets of stores, which is the error this
        # dashboard finds most often. See [[feedback-same-estate]].
        s = s[(s["ty"] > 0) | (s["ly"] > 0) | (s["ly_full"] > 0)]

        def sheet(frame, group, title, sub, reason=False):
            rs = []
            for _, r in frame.iterrows():
                rs.append({"name": r[group], "store": r.get("store", ""),
                           "loc": r.get("location", ""),
                           "ly": r["ly"], "ty": r["ty"], "delta": r["delta"],
                           "gd": (None if not r["ly"]
                                  else (r["ty"] - r["ly"]) / r["ly"] * 100),
                           "ly_full": r["ly_full"],
                           "why": r.get("why", ""),
                           "share": (r["ty"] / frame["ty"].sum() * 100
                                     if frame["ty"].sum() else None)})
            rs.sort(key=lambda x: -(x["ty"] or 0))
            tot = {"name": "TOTAL", "store": "", "loc": "", "why": "",
                   "ly": frame["ly"].sum(), "ty": frame["ty"].sum(),
                   "delta": frame["delta"].sum(),
                   "gd": (None if not frame["ly"].sum() else
                          (frame["ty"].sum() - frame["ly"].sum())
                          / frame["ly"].sum() * 100),
                   "ly_full": frame["ly_full"].sum(), "share": 100.0}
            sp = [("store", "text", "STORE"), ("loc", "text", "LOCATION"),
                  ("ty", "money", "THIS YEAR"), ("ty", "bar", "SHARE"),
                  ("share", "pct", "% OF\nSET")]
            if reason:
                sp += [("why", "text", "HELD OUT\nBECAUSE"),
                       ("ly_full", "money", "LY FULL\nRUN-UP")]
            else:
                sp += [("ly", "money", "LAST YEAR"),
                       ("delta", "money", "CHANGE"), ("gd", "pct", "G/D"),
                       ("ly_full", "money", "LY FULL\nRUN-UP")]
            sh = A4._Sheet(w.label, asof, "", bounded=False, footer=True)
            sh.put(A4._heading(W, title, sub), gap=18)
            sh.put(table_image(rs, sp, W, font_px=24, bar_col="ty",
                               total_row=tot), gap=20)
            sh._footers()
            return sh.pages

        # ★ TWO SECTIONS, NEVER ONE LIST. A comparable store and a South store
        # with no last year cannot sit in the same ranking — one has a G/D and
        # the other cannot have one, and a reader scanning the column would
        # take the blanks for zeros.
        s_l2l = s[s["l2l"]]
        s_oth = s[~s["l2l"]].copy()
        if len(s_l2l):
            pages += sheet(s_l2l, "store",
                           f"{w.festival} — comparable stores",
                           f"the {len(s_l2l)} East & NE stores that traded both "
                           f"run-ups and are still open  ·  biggest first  ·  "
                           f"the bar is each store's share of this set")
        if len(s_oth):
            pages += sheet(s_oth, "store",
                           f"{w.festival} — not comparable",
                           f"{len(s_oth)} stores held out of the comparison  ·  "
                           f"South and any store with no last year, plus every "
                           f"store that has closed  ·  a G/D is not shown "
                           f"because there is nothing to compare against",
                           reason=True)
        # ★ THE ROLLUPS COVER THE WHOLE ESTATE, with the three sets as
        # columns. Built from `s` and not from `s_l2l`, so South is present.
        def rollup(group, title, sub):
            rs, tot = rollup_rows(s, group)
            sh = A4._Sheet(w.label, asof, "", bounded=False, footer=True)
            sh.put(A4._heading(W, title, sub), gap=14)
            sh.put(A4._text_block(W, [(
                "Every store is in this table. COMPARABLE traded both "
                "run-ups and is still open — it is the only pair a G/D is "
                "taken from. NON COMPARABLE is everything else: South and any "
                "store with no last year on this year's side, and on last "
                "year's, what stores that have since shut took over THESE SAME "
                "DAYS. Every money column here is the elapsed window, so each "
                "year's total is its comparable plus its non comparable.",
                A4._ft(22)[0], A4.SUB)]), gap=14)
            _rspec = rollup_spec(rs)
            _rshade = [i for i, (c, _k, _h) in enumerate(_rspec)
                       if c in ("l2l_ty", "l2l_ly")]
            sh.put(table_image(rs, _rspec, W, font_px=24, bar_col="total_ty",
                               total_row=tot, shade=_rshade), gap=20)
            sh._footers()
            return sh.pages

        if "parent" in s.columns:
            pages += rollup("parent", f"{w.festival} — brand by brand",
                            "every brand, biggest first, split three ways")
        if "location_tl" in s.columns:
            pages += rollup("location_tl",
                            f"{w.festival} — location by location",
                            "every location, biggest first, split three ways")
        if "region" in s.columns:
            pages += rollup("region", f"{w.festival} — region by region",
                            "East & NE against South, split three ways")

        import io
        buf = io.BytesIO()
        pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:],
                      resolution=A4.PAGE_W * 72.0 / A4.PAGE_PT_W)
        out = buf.getvalue()
    finally:
        A4.MARGIN, A4.CONTENT_W, PP.PAD_Y = _keep
    tag = "VFL " if vfl else ""
    return (f"{tag}{w.festival.upper()} {w.tenure} RUN-UP {asof:%d-%m-%Y}.pdf",
            out)
