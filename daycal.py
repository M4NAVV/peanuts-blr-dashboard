"""Last year's month, day by day, as a calendar.

★ WHY THIS EXISTS. Manav, 22 Aug: *"a tab where i can see the last year month
sales for everyday, like a heatmap … i will be selecting the store i want to
see, and then i will be able to view the entire sales data for last year for
the month we are in."*

The point is to know what is COMING. Halfway through a month, the useful
question is not "how are we doing" — the dashboard answers that everywhere —
but "what did the rest of this month look like last year". A calendar shows it
in the shape a manager already thinks in: which Saturdays were big, where the
dead run was, whether the month ends with a rush.

★ WHY A CALENDAR AND NOT A LINE. Sales here are dominated by day of week —
weekends run about twice a weekday across the estate. On a line chart that
sawtooth drowns everything else. Laid out as a calendar, the weekend column IS
a column, so what is left to see is the part that is not the weekly cycle.
"""

from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def month_window(asof, years_back: int = 1):
    """The same calendar month, `years_back` years earlier: (start, end)."""
    asof = pd.Timestamp(asof)
    y, m = asof.year - years_back, asof.month
    start = pd.Timestamp(y, m, 1)
    end = pd.Timestamp(y, m, calendar.monthrange(y, m)[1])
    return start, end


def daily_series(df, date_col, value_col, start, end, store_col=None, store=None):
    """One row per calendar day in the window, zero-filled.

    ★ ZERO-FILLED ON PURPOSE. A day with no rows is a day the store took
    nothing — a holiday, a closure — and that is exactly what a reader needs to
    see. Left absent it would silently vanish from the grid and the month would
    look like it had 27 days.
    """
    d = df
    if store_col and store and store != "All stores":
        d = d[d[store_col] == store]
    d = d[(d[date_col] >= start) & (d[date_col] <= end)]
    s = d.groupby(d[date_col].dt.normalize())[value_col].sum()
    idx = pd.date_range(start, end, freq="D")
    return s.reindex(idx, fill_value=0.0)


def to_grid(series):
    """Lay a daily series out as weeks x weekdays, the way a wall calendar reads.

    Returns (values, labels) — values for the colour, labels for the text, both
    indexed by week-of-month with Mon..Sun columns. Cells outside the month are
    NaN / blank rather than zero, so an empty corner cannot be read as a day
    that took nothing.
    """
    if series.empty:
        return pd.DataFrame(), pd.DataFrame()
    f = pd.DataFrame({"date": series.index, "val": series.values})
    f["dow"] = f.date.dt.weekday                       # Mon=0
    first = f.date.iloc[0]
    f["week"] = ((f.date - first).dt.days + first.weekday()) // 7

    vals = pd.DataFrame(np.nan, index=sorted(f.week.unique()), columns=WEEKDAYS)
    labs = pd.DataFrame("", index=sorted(f.week.unique()), columns=WEEKDAYS)
    for r in f.itertuples():
        vals.loc[r.week, WEEKDAYS[r.dow]] = r.val
        labs.loc[r.week, WEEKDAYS[r.dow]] = f"{r.date.day}\n{_short(r.val)}"
    vals.index = [f"Week {i+1}" for i in range(len(vals))]
    labs.index = vals.index
    return vals, labs


def _short(v) -> str:
    """Money at a glance. A calendar cell has no room for digit grouping."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if v == 0:
        return "—"
    a = abs(v)
    if a >= 1e7:
        return f"{v/1e7:,.2f} Cr"
    if a >= 1e5:
        return f"{v/1e5:,.2f} L"
    if a >= 1e3:
        return f"{v/1e3:,.0f} K"
    return f"{v:,.0f}"


def summary(series, same_days: int | None = None) -> dict:
    """Totals for the month, and for a like-for-like slice of it.

    `same_days` compares only the first N days, because a part-month measured
    against a whole one is the commonest way to make this year look broken.
    """
    s = series
    out = {
        "total": float(s.sum()),
        "days": int((s > 0).sum()),
        "best_day": s.idxmax() if len(s) and s.max() > 0 else None,
        "best_val": float(s.max()) if len(s) else 0.0,
        "worst_open": None, "worst_val": None,
        "weekend": float(s[s.index.weekday >= 5].sum()),
        "weekday": float(s[s.index.weekday < 5].sum()),
    }
    open_days = s[s > 0]
    if len(open_days):
        out["worst_open"] = open_days.idxmin()
        out["worst_val"] = float(open_days.min())
    if same_days:
        out["same_days_total"] = float(s.iloc[:same_days].sum())
        out["same_days"] = same_days
    return out


# --------------------------------------------------------------------------- #
#  Rendering — an actual calendar, in the house's inline-HTML idiom
# --------------------------------------------------------------------------- #
MAROON = "#7A1F2B"
INK = "#2B2B2B"
INK_RGB = (43, 43, 43)          # the same ink, for the drawn version
MAROON_RGB = (122, 31, 43)
MUTED = "#8A8A8A"
LINE = "#ECE4D6"
GREEN = "#137A3A"
RED = "#C0143C"


def _tint(t: float) -> str:
    """White through to the house maroon. `t` in [0,1].

    Sequential, not diverging: there is no meaningful midpoint in a day's
    takings, only more and less.
    """
    t = 0.0 if t is None or (isinstance(t, float) and np.isnan(t)) else max(0.0, min(1.0, t))
    r = int(255 + (122 - 255) * t)
    g = int(255 + (31 - 255) * t)
    b = int(255 + (43 - 255) * t)
    return f"rgb({r},{g},{b})"


def _ink_on(t: float) -> str:
    """Text has to stay readable as the cell darkens."""
    return "#FFFFFF" if (t or 0) > 0.55 else INK


def calendar_html(series, compare=None, upto=None, cap_pct: float = 0.95) -> str:
    """The month as a wall calendar.

    series   the month being shown, one value per calendar day
    compare  optional same-length series to show as a delta chip
    upto     day-of-month already traded this year; days after it are the ones
             still to come, and are ringed because they are the reason to look
    cap_pct  the colour scale is capped here so one huge day does not flatten
             every other cell to the same pale wash
    """
    if series.empty:
        return "<p>No data.</p>"

    hi = float(np.nanpercentile(series.values, cap_pct * 100)) or 1.0
    first = series.index[0]
    pad = first.weekday()                       # blanks before the 1st

    head = "".join(
        f'<div style="padding:6px 0;text-align:center;font-size:.72rem;'
        f'letter-spacing:.06em;color:{MUTED};font-weight:600;'
        f'background:{"#FAF6EF" if i >= 5 else "transparent"}">{d}</div>'
        for i, d in enumerate(WEEKDAYS))

    cells = ['<div style="border:1px solid transparent"></div>'] * pad
    for day, val in series.items():
        t = min(float(val) / hi, 1.0) if hi else 0.0
        ink = _ink_on(t)
        future = upto is not None and day.day > upto
        ring = f"2px solid {MAROON}" if future else f"1px solid {LINE}"

        chip = ""
        if compare is not None and day in compare.index and not future:
            was = float(compare.loc[day])
            if was > 0:
                pct = (float(val) / was - 1) * 100
                col = GREEN if pct >= 0 else RED
                chip = (f'<div style="font-size:.62rem;font-weight:700;color:{col};'
                        f'margin-top:1px">{pct:+.0f}%</div>')

        body = ("—" if val == 0 else _short(val))
        cells.append(
            f'<div style="border:{ring};border-radius:6px;padding:7px 6px 6px;'
            f'background:{_tint(t)};min-height:64px;display:flex;'
            f'flex-direction:column;justify-content:space-between">'
            f'<div style="font-size:.66rem;color:{ink};opacity:.75;'
            f'font-weight:600">{day.day}</div>'
            f'<div style="font-size:.92rem;font-weight:700;color:{ink};'
            f'font-variant-numeric:tabular-nums;line-height:1.1">{body}</div>'
            f'{chip}</div>')

    return (
        f'<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;'
        f'margin:4px 0 2px">{head}</div>'
        f'<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px">'
        f'{"".join(cells)}</div>')


def stat_row(items) -> str:
    """`items` = [(label, value, sub or None), …] — the house metric card."""
    out = []
    for label, value, sub in items:
        tail = (f'<div style="font-size:.7rem;color:{MUTED};margin-top:2px">{sub}</div>'
                if sub else "")
        out.append(
            f'<div style="border-left:2px solid {LINE};padding:2px 0 2px 10px">'
            f'<div style="font-size:.68rem;color:{MUTED};text-transform:uppercase;'
            f'letter-spacing:.07em">{label}</div>'
            f'<div style="font-size:1.35rem;font-weight:700;color:{INK};'
            f'font-variant-numeric:tabular-nums;line-height:1.2">{value}</div>'
            f'{tail}</div>')
    return (f'<div style="display:grid;grid-template-columns:repeat({len(out)},1fr);'
            f'gap:14px;margin:10px 0 14px">{"".join(out)}</div>')


# --------------------------------------------------------------------------- #
#  Store-wise monthly sales, for download
# --------------------------------------------------------------------------- #
def fiscal_year_of(ts) -> int:
    """The April–March year a date belongs to, named by its opening April."""
    ts = pd.Timestamp(ts)
    return ts.year if ts.month >= 4 else ts.year - 1


def fiscal_label(fy: int) -> str:
    return f"{fy}-{str(fy + 1)[2:]}"


def monthly_matrix(df, date_col, value_col, store_col, *,
                   stores=None, fy=None, asof=None):
    """One row per store, one column per month, summing `value_col`.

    Columns run in the order the month actually happened. With `fy` set that is
    April to March, because this business reports on a fiscal year and a
    January column sitting before its own April would be a different year's.

    ★ THE LAST MONTH IS ALMOST ALWAYS PART-TRADED, and its header says so:
    `Sep 2026 (1–22)`. A part month sitting unlabelled beside a whole one
    invites a comparison that is not one. See [[feedback-provisional-day]].

    ★ A SELECTED STORE WITH NO ROWS STILL GETS A ROW, of zeros. Dropping it
    would quietly answer a different question from the one asked — the user
    picked that store and is owed an answer about it.

    Returns (frame, note). The frame carries a Total column and a TOTAL row;
    `note` says what the figures cover, for printing beside them.
    """
    d = df[[date_col, value_col, store_col]].copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.dropna(subset=[date_col])

    if stores is not None:
        stores = list(stores)
        d = d[d[store_col].isin(stores)]
    if fy is not None:
        d = d[(d[date_col] >= pd.Timestamp(fy, 4, 1))
              & (d[date_col] <= pd.Timestamp(fy + 1, 3, 31))]

    if d.empty and not stores:
        return pd.DataFrame(), "no rows in the period selected"

    d["_m"] = d[date_col].values.astype("datetime64[M]")
    piv = (d.pivot_table(index=store_col, columns="_m", values=value_col,
                         aggfunc="sum", fill_value=0.0)
           if not d.empty else pd.DataFrame())
    if stores:
        piv = piv.reindex(sorted(stores)).fillna(0.0)
    piv = piv.reindex(sorted(piv.columns), axis=1)

    last_day = d[date_col].max() if not d.empty else None
    asof = pd.Timestamp(asof) if asof is not None else last_day

    names, partial = [], None
    for m in piv.columns:
        m = pd.Timestamp(m)
        end = m + pd.offsets.MonthEnd(0)
        if last_day is not None and last_day < end and m <= last_day:
            names.append(f"{m:%b %Y} (1–{last_day.day})")
            partial = f"{m:%B %Y}"
        else:
            names.append(f"{m:%b %Y}")
    piv.columns = names

    piv["Total"] = piv.sum(axis=1)
    piv.index.name = "Store"
    out = piv.reset_index()
    total = {c: (out[c].sum() if c != "Store" else "TOTAL") for c in out.columns}
    out = pd.concat([out, pd.DataFrame([total])], ignore_index=True)

    span = (f"{d[date_col].min():%d %b %Y} to {last_day:%d %b %Y}"
            if last_day is not None else "no dated rows")
    note = f"{len(piv)} stores · {span}"
    if partial:
        note += f" · {partial} is part-traded"
    return out, note


def store_identity(df, id_cols, sep=" — "):
    """One label per STORE, from however many columns it takes to be unique.

    ★ A LOCATION IS NOT A STORE in the portfolio feed. `City Centre` is a mall
    in Siliguri holding ELEVEN brands — Van Heusen, Madame, Manyavar, Turtle
    and the rest — so a grid keyed on location would silently add eleven shops
    into one line. 63 codes sit under 34 locations; only `brand + location`
    separates them. See [[feedback-same-estate]].
    """
    cols = [id_cols] if isinstance(id_cols, str) else list(id_cols)
    out = df[cols[0]].astype(str).str.strip()
    for c in cols[1:]:
        out = out + sep + df[c].astype(str).str.strip()
    return out


def live_labels(labels, code_of, closed, asof):
    """Split store labels into (live, shut) as at `asof`.

    ★ A LABEL MAY CARRY SEVERAL CODES, and is live if ANY of them is. A plain
    `dict(zip(...))` keeps the LAST code per label, which read Rajarhat CC2 as
    shut: its old code 99 closed in Aug 2025 while the live code 90 has traded
    every day since. `code_of` may therefore map a label to one code or to an
    iterable of them.

    A store is live unless the store master gives it a closure date on or
    before that day — the same authority `closed_map` is for every other
    figure here, so a download cannot disagree with the sheets about which
    shops exist.

    ★ A LABEL THE MASTER DOES NOT KNOW IS KEPT, and the caller is told how many
    there are. Dropping it would quietly answer a different question from the
    one asked. See [[feedback-silent-failure-must-speak]].
    """
    asof = pd.Timestamp(asof)
    shut_codes = set()
    for code, when in (closed or {}).items():
        when = pd.to_datetime(when, errors="coerce")
        if pd.notna(when) and when <= asof:
            try:
                shut_codes.add(int(code))
            except (TypeError, ValueError):
                shut_codes.add(code)

    def _norm(c):
        try:
            return int(c)
        except (TypeError, ValueError):
            return c

    live, shut = [], []
    for lab in sorted({str(x) for x in labels if pd.notna(x)}):
        got = (code_of or {}).get(lab)
        if got is None:
            codes = []
        elif isinstance(got, (list, tuple, set, frozenset)):
            codes = [_norm(c) for c in got]
        else:
            codes = [_norm(got)]
        # unknown to the master, or any code still trading -> live
        is_shut = bool(codes) and all(c in shut_codes for c in codes)
        (shut if is_shut else live).append(lab)
    return live, shut


def _ordinal(n: int) -> str:
    """`21st`, not `21th`. The card has read `21th` for as long as it has
    existed. A label, not a key into a sheet, so it is safe to correct —
    see [[feedback-fix-spelling-in-reports]]."""
    n = int(n)
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def month_stats(series, ly, ty, *, upto=None, fmt=str):
    """The four cards above the calendar, as [(label, value, sub), …].

    ★ ONE SOURCE FOR THE SCREEN AND THE PNG. These used to be built inline in
    the tab; a downloaded image whose headline figures were computed by a
    second copy of the arithmetic is exactly how two correct-looking numbers
    come to disagree. See [[feedback-same-estate]].
    """
    if upto:
        done_ly, done_ty = ly.iloc[:upto].sum(), ty.iloc[:upto].sum()
        left_ly = ly.iloc[upto:].sum()
        days_left = len(ly) - upto
        delta = (done_ty / done_ly - 1) * 100 if done_ly else None
        start = ly.index[0]
        return [
            (f"Still to come · {days_left} days", fmt(left_ly),
             f"what last year took after the {_ordinal(upto)}"),
            (f"1–{upto} {start:%b} this year", fmt(done_ty),
             (f"{delta:+.1f}% vs last year" if delta is not None else None)),
            (f"1–{upto} {start:%b} last year", fmt(done_ly), "same days only"),
            (f"All of {start:%b} last year", fmt(ly.sum()),
             f"{int((ly > 0).sum())} trading days"),
        ]
    sm = summary(series)
    return [
        (f"{series.index[0]:%b %Y} total", fmt(sm["total"]), None),
        ("Trading days", f"{sm['days']}", None),
        ("Weekend share",
         f"{sm['weekend']/sm['total']*100:.0f}%" if sm["total"] else "—", "Sat + Sun"),
        ("Best day", f"{sm['best_day']:%a %d}" if sm["best_day"] is not None else "—",
         fmt(sm["best_val"])),
    ]


# --------------------------------------------------------------------------- #
#  The same calendar, as a PNG you can put in a message
# --------------------------------------------------------------------------- #
_PAPER = (251, 247, 241)
_CARD_RULE = (232, 224, 212)


def _rgb(css: str):
    n = css[css.index("(") + 1:css.index(")")].split(",")
    return tuple(int(x) for x in n)


def calendar_png(series, *, stats=(), legend="", compare=None, upto=None,
                 cap_pct: float = 0.95, width: int = 2000, scale: int = 3):
    """The month as a wall calendar, drawn — cards on top, legend underneath.

    The same figures, ramp, ring and cap as `calendar_html`, so the image and
    the screen cannot show different months of the same store.

    ★ `scale` IS THE WHOLE OF THE QUALITY. Layout is fixed in logical units and
    every one of them — padding, cell, corner radius, stroke AND type size — is
    multiplied by it, so the proportions never move and only the pixel density
    changes. Drawn at scale 1 this laid ~34px of type on a 2000px canvas and
    read soft on any screen worth looking at; the packs are sharp because they
    put 486 ppi on a fixed page, not because they are bigger.
    See [[feedback-print-quality-is-pixels-per-page]].
    """
    from PIL import Image, ImageDraw
    import portfolio_pdf as PP

    if series.empty:
        return None

    k = max(1, int(scale))

    def px(n):
        return int(round(n * k))

    def ft(n, bold=False):
        reg, emp = PP._fonts(int(round(n * k)))
        return emp if bold else reg

    lab_f = ft(15)
    val_f = ft(34, bold=True)
    sub_f = ft(14)
    hd_f = ft(15)
    day_v = ft(19, bold=True)
    dnum_f = ft(13)
    chip_f = ft(12, bold=True)
    leg_f = ft(15)

    pad = px(22)
    gap = px(5)
    W = width * k
    inner = W - pad * 2
    col_w = (inner - gap * 6) // 7
    cell_h = px(74)

    first = series.index[0]
    lead = first.weekday()
    n_weeks = (lead + len(series) + 6) // 7

    card_h = px(86) if stats else 0
    head_h = px(30)
    leg_h = px(30) if legend else 0
    H = pad + card_h + head_h + n_weeks * (cell_h + gap) + leg_h + pad

    img = Image.new("RGB", (W, H), _PAPER)
    d = ImageDraw.Draw(img)
    y = pad

    # ---- the cards, evenly across the width, divided by a hairline
    if stats:
        cw = inner // max(len(stats), 1)
        for i, (label, value, sub) in enumerate(stats):
            x = pad + i * cw
            if i:
                d.line([(x - px(10), y + px(6)),
                        (x - px(10), y + card_h - px(14))],
                       fill=_CARD_RULE, width=1)
            d.text((x, y), str(label).upper(), font=lab_f, fill=PP.MUTED)
            d.text((x, y + px(22)), str(value), font=val_f, fill=INK_RGB)
            if sub:
                d.text((x, y + px(62)), str(sub), font=sub_f, fill=PP.MUTED)
        y += card_h

    # ---- weekday header, weekends on their own tint
    # The web version tints the weekend headers against a white page; on this
    # cream paper the block reads as a smudge, so the header stays plain.
    for i, name in enumerate(WEEKDAYS):
        x = pad + i * (col_w + gap)
        tw = d.textlength(name, font=hd_f)
        d.text((x + (col_w - tw) / 2, y + px(7)), name, font=hd_f, fill=PP.MUTED)
    y += head_h

    # ---- the days
    hi = float(np.nanpercentile(series.values, cap_pct * 100)) or 1.0
    slot = lead
    for day, val in series.items():
        r, c = divmod(slot, 7)
        x = pad + c * (col_w + gap)
        yy = y + r * (cell_h + gap)
        t = min(float(val) / hi, 1.0) if hi else 0.0
        future = upto is not None and day.day > upto
        d.rounded_rectangle([x, yy, x + col_w, yy + cell_h], radius=px(6),
                            fill=_rgb(_tint(t)),
                            outline=MAROON_RGB if future else _CARD_RULE,
                            width=px(2) if future else 1)
        ink = (255, 255, 255) if (t or 0) > 0.55 else INK_RGB
        d.text((x + px(8), yy + px(6)), str(day.day), font=dnum_f, fill=ink)
        d.text((x + px(8), yy + cell_h - px(28)),
               "—" if val == 0 else _short(val), font=day_v, fill=ink)
        if compare is not None and day in compare.index and not future:
            was = float(compare.loc[day])
            if was > 0:
                pct = (float(val) / was - 1) * 100
                d.text((x + px(8), yy + cell_h - px(13)), f"{pct:+.0f}%",
                       font=chip_f, fill=(19, 122, 58) if pct >= 0 else (192, 20, 60))
        slot += 1
    y += n_weeks * (cell_h + gap)

    if legend:
        d.text((pad, y + px(6)), legend, font=leg_f, fill=PP.MUTED)
    return img
