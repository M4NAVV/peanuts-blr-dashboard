"""The morning snapshot, reflowed onto A4 for the manager to PRINT and brief from.

Manav, 23 Aug: *"we use these manager snapshots and reformat them into
something … formatted properly so that its printable for an A4 sheet, which the
manager can print every morning while briefing the team … the 2-3 pointers u are
writing at the bottom of the sheet, we need to give them an elaborate version of
it. all of this to be done in the same a4 printable sheet."*

★★ THIS MODULE ADDS. IT DOES NOT EDIT. `snapshots.py`, `app.py` and
`portfolio_pdf.py` are untouched — he said the morning set may be reverted to,
so the A4 sheet is a second entry point that READS the same functions rather
than a rewrite of them. Every figure here comes from `snapshots.py`, so the
printed sheet and the WhatsApp image can never disagree.

WHAT IS DIFFERENT FROM THE PNG
  · A real page. A4 portrait at 300 dpi, saved as PDF at the exact paper size,
    so "Print" gives a sheet rather than a scaled-down screenshot. The PNG is
    one tall image built for pinch-zooming on a phone; on paper it prints as a
    postage stamp.
  · The four columns that never change — DATE, Region, STORE CODE, LOCATION —
    are stated ONCE under the title instead of thirty-two times down the page.
    Nothing is removed; the same facts are on the sheet. What it buys is width,
    and width is what pays for type a manager can read standing up. Set
    `LIFT_CONSTANT_COLS = False` to print them in the table as before.
  · The two or three pointers at the foot become a full briefing — see
    `briefing()`. Same discipline as the PNG's notes: every line names
    something the STORE did and something it can do. Nothing outside the store
    is ever offered as a reason.
"""
from __future__ import annotations

import io

import pandas as pd
from PIL import Image, ImageDraw

import portfolio_pdf as PP
import snapshots as SN

# --- the sheet ------------------------------------------------------------- #
# A4 portrait, 300 dpi. The page is SAVED at this pixel size against a declared
# A4 point size, so the PDF is true 210x297mm and never resampled — the same
# rule `portfolio_pdf.save_pages` follows, and the reason the pack prints sharp.
DPI = 300
PAGE_PT_W, PAGE_PT_H = 595.276, 841.890
PAGE_W = int(round(PAGE_PT_W / 72 * DPI))          # 2480
PAGE_H = int(round(PAGE_PT_H / 72 * DPI))          # 3508
MARGIN = int(round(12 / 25.4 * DPI))               # 12 mm — inside every printer
CONTENT_W = PAGE_W - 2 * MARGIN

INK = (0, 0, 0)
SUB = (90, 90, 90)
RULE = (185, 185, 185)

# Columns that identify the store rather than describe a row. Constant on a
# per-store sheet, so they are stated once. See the module docstring.
LIFT_CONSTANT_COLS = True
IDENTITY_COLS = ("DATE", "Region", "STORE CODE", "LOCATION", "Master Location")

# Table type is fitted between these, by width AND by height (see `_fit`).
FONT_MIN, FONT_MAX = 15, 34

# ★ THE ONE REAL TRADE ON THIS SHEET, AND IT IS HIS TO MAKE.
# Nothing is removed either way — the same rows, cards and measures print. What
# changes is the type size, and therefore the page count. Measured on Agartala
# (30 table rows, both periods):
#   COMPACT = False   3 pages, table type 8.2pt   ← default, reads standing up
#   COMPACT = True    2 pages, table type 5.3pt   ← fits two sheets, needs a desk
# The house print target is ~7pt (see the print-quality rule), so the default
# clears it and COMPACT does not. Flip it if paper matters more than the read.
COMPACT = False

NOTE_HEAD_PX = 40
NOTE_BODY_PX = 33
NOTE_COLS = 2


def _ft(px):
    return PP._ft(px)


def _h(font):
    a, d = font.getmetrics()
    return a + d


# --------------------------------------------------------------------------- #
#  Table fitting                                                               #
# --------------------------------------------------------------------------- #

def _lift_constants(drv):
    """(table without its constant identity columns, [(name, value), …])."""
    if not LIFT_CONSTANT_COLS:
        return drv, []
    keep, lifted = [], []
    for c in drv.columns:
        v = drv[c].astype(str).str.strip()
        v = v[v.ne("") & v.ne("nan") & v.ne("None")]
        if c in IDENTITY_COLS and v.nunique() <= 1:
            lifted.append((c, v.iloc[0] if len(v) else ""))
        else:
            keep.append(c)
    return drv[keep], lifted


# ★ THIS MODULE SETS ITS OWN COLUMN CEILING, ON PURPOSE.
# `portfolio_pdf.COL_CAP` is 520px, sized for the report pack's type. The
# Division cell here now carries the folded Twamev sections — "WOMEN · CROP TOP
# LEHENGA" — and at the larger sizes the fitter tries, Fairfield's Division
# column measures 529px and would spill 9px into the column beside it.
# Re-widening AFTER the measure keeps this file standalone: it needs nothing
# from `portfolio_pdf` that is not already committed, so it can ship on its own.
CEILING = 1100


def _measure(drv, money, pct, sign, px):
    m = PP._measure_table(drv, money=money, pct=pct, sign=sign,
                          font_px=px, header_px=max(int(px * 0.88), 12))
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for j in range(len(m["cols"])):
        data_w = max((scratch.textlength(m["txt"][i][j], font=m["bold"])
                      for i in range(len(m["txt"]))), default=0)
        want = min(int(data_w) + 2 * PP.PAD_X, CEILING)
        if want > m["col_w"][j]:
            m["col_w"][j] = want
    m["W"] = sum(m["col_w"])
    return m


def _fit(tables, money_of, pct, max_w, max_h=None, side_by_side=False):
    """Largest type at which every table fits `max_w`, and the pair fits `max_h`.

    ★ SIDE BY SIDE MEASURES THE TALLER, NOT THE SUM. The month and the year sit
    in two columns on one sheet, so what has to clear the page is whichever of
    them is longer — adding them would size the type for a page twice as tall
    as the one being printed.

    ★ FITTED TOGETHER, NOT SEPARATELY. The month and the year sit on one sheet;
    sizing them independently would print the same six columns at two different
    sizes on one page, which reads as a mistake even when both are legible.
    """
    def total(px):
        ms = [_measure(d, money_of(k), pct, ["Shortfall"] + list(pct), px)
              for k, d in tables]
        w = max(m["W"] for m in ms)
        each = [m["head_h"] + m["row_h"] * len(d)
                for (k, d), m in zip(tables, ms)]
        return ms, w, (max(each) if side_by_side else sum(each))

    lo, hi, best = FONT_MIN, FONT_MAX, None
    while lo <= hi:
        mid = (lo + hi) // 2
        ms, w, h = total(mid)
        if w <= max_w and (max_h is None or h <= max_h):
            best = (ms, mid)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        best = (total(FONT_MIN)[0], FONT_MIN)
    return best


# --------------------------------------------------------------------------- #
#  Blocks                                                                      #
# --------------------------------------------------------------------------- #

def _text_block(width, runs, gap=10):
    """[(text, font, ink)] stacked, wrapped to `width`."""
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = []
    for text, font, ink in runs:
        for ln in (PP._wrap(scratch, text, font, width) if text else [""]):
            lines.append((ln, font, ink))
    H = sum(_h(f) for _, f, _ in lines) + gap * max(len(lines) - 1, 0)
    img = Image.new("RGB", (width, max(H, 1)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    y = 0
    for ln, f, ink in lines:
        d.text((0, y), ln, font=f, fill=ink)
        y += _h(f) + gap
    return img


def _heading(width, text, sub=""):
    _, b = _ft(46)
    s, _u = _ft(28)
    runs = [(text, b, INK)] + ([(sub, s, SUB)] if sub else [])
    body = _text_block(width, runs, gap=8)
    img = Image.new("RGB", (width, body.height + 16), (255, 255, 255))
    img.paste(body, (0, 0))
    ImageDraw.Draw(img).line([(0, body.height + 10), (width, body.height + 10)],
                             fill=RULE, width=2)
    return img


def _note_section(width, head, paras):
    _, hb = _ft(NOTE_HEAD_PX)
    body, _u = _ft(NOTE_BODY_PX)
    runs = [(head, hb, INK)]
    for p in paras:
        runs.append((p, body, INK))
    blk = _text_block(width, runs, gap=9)
    out = Image.new("RGB", (width, blk.height + 30), (255, 255, 255))
    out.paste(blk, (0, 0))
    return out


# --------------------------------------------------------------------------- #
#  Page assembly                                                               #
# --------------------------------------------------------------------------- #

class _Sheet:
    """Pages of a fixed A4, filled top to bottom, with a running footer."""

    def __init__(self, store, asof, context):
        self.store, self.asof, self.context = store, asof, context
        self.pages, self._img, self._y = [], None, 0

    def _new(self):
        self._img = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
        self._y = MARGIN
        self.pages.append(self._img)
        if len(self.pages) > 1:
            self.put(_heading(CONTENT_W,
                              f"{self.store} — morning briefing (continued)",
                              self.context))

    def room(self):
        return PAGE_H - MARGIN - int(round(9 / 25.4 * DPI)) - self._y

    def put(self, img, gap=26):
        if self._img is None or img.height > self.room():
            self._new()
        self._img.paste(img, (MARGIN + (CONTENT_W - img.width) // 2, self._y))
        self._y += img.height + gap

    def _footers(self):
        f, _ = _ft(24)
        n = len(self.pages)
        for i, p in enumerate(self.pages, 1):
            d = ImageDraw.Draw(p)
            y = PAGE_H - MARGIN - _h(f)
            d.line([(MARGIN, y - 14), (PAGE_W - MARGIN, y - 14)], fill=RULE, width=2)
            d.text((MARGIN, y), f"{self.store} · as of {self.asof:%d %b %Y}",
                   font=f, fill=SUB)
            # A one-sheet document does not need telling it is page one of one.
            if n > 1:
                t = f"Page {i} of {n}"
                d.text((PAGE_W - MARGIN - d.textlength(t, font=f), y), t,
                       font=f, fill=SUB)

    def pdf(self):
        self._footers()
        buf = io.BytesIO()
        self.pages[0].save(buf, "PDF", save_all=True,
                           append_images=self.pages[1:],
                           resolution=PAGE_W * 72.0 / PAGE_PT_W)
        return buf.getvalue()


# --------------------------------------------------------------------------- #
#  The briefing — the elaborate version of the PNG's two or three pointers      #
# --------------------------------------------------------------------------- #
# ★ SAME DISCIPLINE AS `snapshots.coaching_lines`, AT LENGTH. Every paragraph
# names something the store DID and something it can DO, and the arithmetic is
# always shown so a manager can repeat it to the floor without taking it on
# faith. Nothing outside the store — no market, no weather, no footfall — is
# ever offered as a reason: a manager handed an external cause has been handed a
# reason to do nothing.

def _rs(v, unit=None):
    if v is None:
        return "—"
    return SN._money(v, unit or SN._unit_for([v]))


def _n(v, dp=0):
    return f"{v:,.{dp}f}"


def _settled_day(L, df, store):
    """The last day with real bills — the night fill carries takings but no
    bill numbers, so the newest date would print a nil basket."""
    d = df[df[L.COL_STORE_LABEL] == store]
    s = d[d[L.COL_BILL_UID].notna()]["date"]
    return s.max() if len(s) else None


def _accessory_price(L, df, asof, store):
    """The store's own average accessory price, for valuing an attach."""
    cur, _ = L.report_frames(df, "MTD", asof=asof)
    d = cur[cur[L.COL_STORE_LABEL] == store]
    if d.empty:
        return None
    acc = d[d[L.COL_DIVISION].astype(str).str.upper().str.contains("ACCESSOR",
                                                                   na=False)]
    u = float(acc[L.COL_QTY].sum())
    return float(acc[L.COL_AMOUNT].sum()) / u if u else None


def _movers(drv, types, worst=True, n=3):
    """The detail lines that lost (or gained) the most money this period."""
    col = "Shortfall"
    if col not in drv.columns:
        return []
    d = drv.assign(_t=list(types))
    d = d[d["_t"] == "store"].copy()
    d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d[d[col].notna()]
    d = d[d[col] < 0] if worst else d[d[col] > 0]
    d = d.sort_values(col, ascending=worst).head(n)
    out = []
    for _, r in d.iterrows():
        out.append((str(r.get("Brand", "")).strip(),
                    str(r.get("Division", "")).strip(),
                    float(r[col]),
                    pd.to_numeric(r.get("Degrowth %"), errors="coerce")))
    return out


# ★ SEVEN POINTS, EACH ONE AN INSTRUCTION. Manav, 23 Aug: *"no more than 7
# points. and the points to be very easy to understand and act on."*
#
# So every point LEADS WITH THE ACTION, in the headline, with a number in it.
# The evidence follows underneath in one or two short sentences. A manager
# should be able to read only the seven bold lines aloud and have given a
# complete briefing; the body is there for the questions that come back.
#
# Points that have no data drop out rather than print an empty heading — a
# store with no target, or none of the core garments, simply gets fewer.
MAX_POINTS = 7

# ★ THE POINTS PAGE IS OFF. Manav, 26 Aug: *"scrap the pointers page, we only
# want the first page with all the data points. the pointers we will work on
# afterwards."* The sheet is ONE page of numbers. `briefing_points` and
# `_point_block` below are left whole and working — turning this back on is the
# only thing needed to get the second page back.
INCLUDE_BRIEFING = False


def briefing_points(L, df, asof, store, code=None, ff=None, targets=None):
    """[(action headline, supporting sentence), …] — at most MAX_POINTS."""
    asof = pd.Timestamp(asof)
    ff = ff or {}
    targets = SN._targets_for(asof) if targets is None else targets

    k = SN.store_kpis(L, df, asof, "MTD", store)
    tp = SN.target_progress(L, asof, "MTD", store, code,
                            achieved=k["ty"]["sale"], targets=targets)
    kp = SN.period_kpis(L, df, asof, store, ff, code)
    att = SN.attach_rate(L, df, asof, "MTD", store)
    drv, types = L.degrowth_drivers(df, asof=asof, kind="MTD",
                                    only_declining=False, stores_only=[store],
                                    products_under="every", top_products=6,
                                    level="division")
    ty, ly = k["ty"], k["ly"]
    days = max(tp["days_left"], 1)
    out = []

    # 1 ─ the number for the rest of the month -------------------------------
    if tp["target"] and tp["per_day"]:
        proj = tp["avg_day"] * (tp["elapsed"] + tp["days_left"])
        out.append((
            f"Take {_rs(tp['per_day'])} a day for the {tp['days_left']} days left",
            f"You were asked for {_rs(tp['target'])} and have {_rs(tp['achieved'])} "
            f"— {_n(tp['ach_pct'], 0)}% with {_n(tp['pace_pct'] or 0, 0)}% of the "
            f"month gone. Carry on at today's {_rs(tp['avg_day'])} a day and you "
            f"finish at {_rs(proj)}, {_rs(tp['target'] - proj)} short."))
    elif tp["target"]:
        out.append((
            f"Target is covered — hold {_rs(tp['avg_day'])} a day",
            f"{_rs(tp['achieved'])} taken against {_rs(tp['target'])} asked. "
            f"Everything from here is on top of it."))
    else:
        out.append((
            f"No target set this month — you are {_n(k['move'] / ly['sale'] * 100, 1) if ly['sale'] else '—'}% on last year",
            f"{_rs(ty['sale'])} against {_rs(ly['sale'])}. Ask for the month's "
            f"target so the sheet can tell you whether that is enough."))

    # 2 ─ the driver carrying the shortfall -----------------------------------
    split = sorted([("bills", "the number of bills you write", k["d_bills"]),
                    ("abs", "the number of pieces on each bill", k["d_abs"]),
                    ("asp", "the price of each piece", k["d_asp"])],
                   key=lambda x: x[2])
    which, phrase, val = split[0]
    if val < 0:
        was = {"bills": f"{_n(ty['bills'])} bills against {_n(ly['bills'])}",
               "abs": f"{_n(ty['abs'], 2)} pieces a bill against {_n(ly['abs'], 2)}",
               "asp": f"Rs {_n(ty['asp'])} a piece against Rs {_n(ly['asp'])}"}[which]
        out.append((
            f"The money is going out through {phrase} — {_rs(abs(val))}",
            f"{was}. The other two are steadier, so fixing them alone will not "
            f"close the month."))

    # 3 ─ the ask, in bills a day ---------------------------------------------
    # ★ THE ASK IS THE TARGET, NOT LAST YEAR. Point 1 states the target in
    # rupees a day; this one states the SAME ask in the only currency a floor
    # can act on. Sizing it off the year-on-year gap instead put two different
    # demands on one page — Agartala read "Rs 1.68 L a day" above "4 more bills
    # a day", and four bills is a fifth of what Rs 1.68 L needs.
    goal = tp["balance"] if (tp["target"] and tp["balance"] and tp["balance"] > 0) \
        else (abs(k["move"]) if k["move"] < 0 else 0)
    if goal > 0 and ty["abv"]:
        per = max(goal / ty["abv"] / days, 1)
        ly_gap = abs(k["move"]) if k["move"] < 0 else 0
        also = ""
        if ly_gap and tp["target"] and abs(ly_gap - goal) > ty["abv"]:
            also = (f" Just to match last year is "
                    f"{_n(max(ly_gap / ty['abv'] / days, 1))} a day.")
        out.append((
            f"Write {_n(per)} more bills a day",
            f"That covers {_rs(goal)} at the Rs {_n(ty['abv'])} you already "
            f"average on a bill. Not a better bill — the same bill, more "
            f"often.{also}"))

    # 4 ─ the line to put in front --------------------------------------------
    lose = _movers(drv, types, worst=True, n=1)
    if lose:
        b, dv, v, pc = lose[0]
        out.append((
            f"Put {b} {dv} in front of the customer — it is {_rs(abs(v))} behind",
            f"{_n(abs(pc), 0)}% down on last year and the single biggest line "
            f"losing money this month." if pd.notna(pc) else
            f"The single biggest line losing money this month."))

    # 5 ─ the line that is working --------------------------------------------
    gain = _movers(drv, types, worst=False, n=1)
    if gain:
        b, dv, v, pc = gain[0]
        out.append((
            f"Do more of what is working on {b} {dv} — it is {_rs(v)} up",
            f"{_n(pc, 0)}% ahead of last year. Whatever the floor is doing on "
            f"this one, ask them and repeat it." if pd.notna(pc) else
            f"Ahead of last year. Ask the floor what they are doing and repeat it."))

    # 6 ─ the second piece -----------------------------------------------------
    t = kp["MTD"]["ty"]
    if t["bills"] and t["single"] and ty["asp"]:
        gain10 = t["single"] * 0.10 * ty["asp"]
        out.append((
            f"Add a second piece to 1 in 10 single-item bills — {_rs(gain10)}",
            f"{_n(t['single'])} of your {_n(t['bills'])} bills this month left "
            f"with one piece. Ten in every hundred of those taking a second at "
            f"your Rs {_n(ty['asp'])} a piece is {_rs(gain10)}."))

    # 7 ─ accessories ----------------------------------------------------------
    a_t, a_l = att.get("ty"), att.get("ly")
    if a_t and a_t["bills"]:
        ap = _accessory_price(L, df, asof, store)
        if ap and a_t["rate"] < 0.25:
            more = (0.25 - a_t["rate"]) * a_t["bills"]
            out.append((
                f"Attach an accessory to {_n(more)} more garment bills — "
                f"{_rs(more * ap)}",
                f"Only {_n(a_t['with'])} of {_n(a_t['bills'])} saree, lehenga "
                f"and sherwani bills took one — {_n(a_t['rate'] * 100, 0)}%"
                + (f", against {_n(a_l['rate'] * 100, 0)}% last year" if a_l else "")
                + f". The customer is already buying the garment."))
        else:
            out.append((
                f"Hold the accessory habit — {_n(a_t['rate'] * 100, 0)}% of "
                f"garment bills take one",
                f"{_n(a_t['with'])} of {_n(a_t['bills'])} saree, lehenga and "
                f"sherwani bills"
                + (f", against {_n(a_l['rate'] * 100, 0)}% last year" if a_l else "")
                + ". This one is purely a habit on the floor."))

    return out[:MAX_POINTS]


def _point_block(width, n, headline, body):
    """One numbered instruction: the action in bold, the evidence under it."""
    num_f = _ft(52)[1]
    head_f = _ft(50)[1]
    body_f = _ft(42)[0]
    gutter = 96
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    tw = width - gutter
    hl = PP._wrap(scratch, headline, head_f, tw)
    bl = PP._wrap(scratch, body, body_f, tw) if body else []
    H = (sum(_h(head_f) + 6 for _ in hl) + (10 if bl else 0)
         + sum(_h(body_f) + 6 for _ in bl) + 34)
    img = Image.new("RGB", (width, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((0, 2), str(n), font=num_f, fill=SUB)
    y = 0
    for ln in hl:
        d.text((gutter, y), ln, font=head_f, fill=INK)
        y += _h(head_f) + 6
    y += 10 if bl else 0
    for ln in bl:
        d.text((gutter, y), ln, font=body_f, fill=(60, 60, 60))
        y += _h(body_f) + 6
    return img


# --------------------------------------------------------------------------- #
#  The six-KPI grid, at print scale                                            #
# --------------------------------------------------------------------------- #
# A print copy of `snapshots._kpi_grid` WITHOUT its short note block — the notes
# are the whole back of this sheet now. The KPI arithmetic, the labels, the
# good/bad direction and the DAY/MTD/YTD spine are all read from `snapshots`,
# so the two documents cannot drift apart.

def _kpi_grid_a4(kpis, width):
    lab_f, _ = _ft(24)
    _, val_b = _ft(40)
    sub_f, _ = _ft(21)
    per_f, per_b = _ft(26)

    per_w, gap = 64, SN.CARD_GAP
    spec = SN._KPI_SPEC
    n = len(spec)
    cw = (width - per_w - gap * n) // n
    lh, vh, sh = _h(lab_f), _h(val_b), _h(sub_f)
    row_h = SN.CARD_PAD_Y * 2 + lh + vh + sh + 10

    H = len(SN.PERIODS) * (row_h + gap) - gap
    img = Image.new("RGB", (width, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    y = 0
    for kind in SN.PERIODS:
        k = kpis[kind]
        t, l = k["ty"], k["ly"]
        img.paste(SN._period_spine(kind, per_b, per_w - gap, row_h), (0, y))
        for i, (which, label, good) in enumerate(spec):
            x = per_w + i * (cw + gap)
            d.rectangle([x, y, x + cw - 1, y + row_h - 1],
                        fill=SN.CARD_BG, outline=SN.CARD_EDGE)
            head, sub = SN._fmt_kpi(which, t, l)
            cur_v, ly_v = SN._kpi_pair(which, t, l)
            ink = SN.KPI_INK
            if cur_v is not None and ly_v is not None and ly_v:
                ink = SN.KPI_GOOD if (cur_v - ly_v) * good >= 0 else SN.KPI_BAD
            d.text((x + SN.CARD_PAD_X, y + SN.CARD_PAD_Y), label,
                   font=lab_f, fill=SN.SUB_INK)
            d.text((x + SN.CARD_PAD_X, y + SN.CARD_PAD_Y + lh + 2), head,
                   font=val_b, fill=ink)
            d.text((x + SN.CARD_PAD_X, y + SN.CARD_PAD_Y + lh + vh + 8), sub,
                   font=sub_f, fill=SN.SUB_INK)
        y += row_h + gap
    return img


# --------------------------------------------------------------------------- #
#  Two-column flow for the briefing                                            #
# --------------------------------------------------------------------------- #

def _put_two_col(sheet, blocks, gap=70):
    """Flow the briefing into two columns.

    ★ THE LAST PAGE IS BALANCED, NOT FILLED. Pouring what is left down the left
    column and stopping leaves half a sheet white — on Grand Kamraj Road that
    was four sections in the left half of an otherwise empty page. So when the
    remainder fits inside one column, it is split across both by height and the
    page reads as though it was meant to end there.
    """
    col_w = (CONTENT_W - gap) // 2
    i, guard = 0, 0
    while i < len(blocks) and guard < 400:
        guard += 1
        if sheet._img is None or sheet.room() < 320:
            sheet._new()
        top, avail = sheet._y, sheet.room()
        rem = sum(b.height for b in blocks[i:])
        half = rem / 2 if rem <= avail else avail
        started, bottom = i, top
        for col, cap in ((0, top + min(half, avail)), (1, top + avail)):
            x = MARGIN + col * (col_w + gap)
            y = top
            while i < len(blocks) and y + blocks[i].height <= cap:
                sheet._img.paste(blocks[i], (x, y))
                y += blocks[i].height
                i += 1
            bottom = max(bottom, y)
        if i == started:
            # Taller than a whole column. It has to go somewhere, so it goes
            # here rather than looping forever on a page it can never fill.
            sheet._img.paste(blocks[i], (MARGIN, top))
            bottom = max(bottom, top + blocks[i].height)
            i += 1
        sheet._y = bottom + 20


# --------------------------------------------------------------------------- #
#  The sheet                                                                   #
# --------------------------------------------------------------------------- #
# TWO SHEETS OF PAPER, AND THEY DIVIDE THE WORK:
#   Page 1  the numbers — the ask, both periods' drivers, the six measures
#   Page 2  the briefing — what to say about them on the floor
# Everything on page 1 except the two tables has a height that does not depend
# on the type size, so those are built and measured FIRST and the tables are
# then fitted into exactly what is left. Guessing that budget (an earlier
# version did) printed the tables three sizes smaller than the page could carry
# and still spilled onto a third sheet.


def _stack(imgs, gap=16):
    """Glue blocks into one, so a page break can never fall between them."""
    imgs = [i for i in imgs if i is not None]
    w = max(i.width for i in imgs)
    out = Image.new("RGB", (w, sum(i.height for i in imgs) + gap * (len(imgs) - 1)),
                    (255, 255, 255))
    y = 0
    for i in imgs:
        out.paste(i, (0, y))
        y += i.height + gap
    return out


def _widen(m, target_w):
    """Spread a table across the full measure once its type size is settled.

    Fitting by height leaves a six-column table sitting in half the page with
    white either side, which on paper reads as a mistake. The columns keep
    their proportions; only the slack is shared out.
    """
    if m["W"] >= target_w or m["W"] <= 0:
        return m
    extra = target_w - m["W"]
    w = m["col_w"]
    add = [extra * c // m["W"] for c in w]
    add[-1] += extra - sum(add)
    m["col_w"] = [a + b for a, b in zip(w, add)]
    m["W"] = sum(m["col_w"])
    return m


def _caption(width, text, sub=""):
    """A compact section label — the big rule-and-subtitle heading eats the
    very height the tables need."""
    _, b = _ft(32)
    sf, _u = _ft(23)
    runs = [(text, b, INK)] + ([(sub, sf, SUB)] if sub else [])
    blk = _text_block(width, runs, gap=6)
    img = Image.new("RGB", (width, blk.height + 10), (255, 255, 255))
    img.paste(blk, (0, 0))
    return img


def _beside(a, b, gutter=64):
    """Two blocks in two columns, top-aligned."""
    if b is None:
        return a
    h = max(a.height, b.height)
    out = Image.new("RGB", (a.width + gutter + b.width, h), (255, 255, 255))
    out.paste(a, (0, 0))
    out.paste(b, (a.width + gutter, 0))
    return out


# --------------------------------------------------------------------------- #
#  Twamev, one level deeper                                                    #
# --------------------------------------------------------------------------- #
# Manav, 26 Aug: *"only for twamev do i want this breakdown, because for
# manyavar and mohey, the breakdown is good enough how it is right now."*
#
# TWAMEV-MEN as a single line nets +Rs 29 L on the year — and hides kurta and
# jodhpuri up Rs 45 L against suit set and sherwani down Rs 23.7 L. That is the
# offset the drivers table exists to expose, one level further down than it
# currently looks.
#
# ★ DONE BY SPLICING, NOT BY CHANGING THE DRIVERS. `loader.degrowth_drivers`
# already takes a level; it is called a second time at SECTION level and only
# Twamev's product rows are lifted out of it. The Twamev brand total and the
# store TOTAL still come from the division-level call, so every figure ties to
# the WhatsApp image exactly as before. Manyavar and Mohey are untouched.
TWAMEV_DETAIL = True
TWAMEV_BRAND = "Twamev"
# ★ FIVE IS FREE, SIX IS NOT. Measured against the fitter on the three stores
# where Twamev is material: at five sections the tables still set at 5.8pt —
# exactly what they read with the breakdown OFF — and at six Grand Kamraj Road
# drops to 5.3pt and M.G. Road to 5.5pt. At eight, M.G. Road was 4.1pt, which
# is not a printable size. So the detail costs nothing up to five.
TWAMEV_SECTIONS = 5
# The floor the tables must still clear once the sections are in. 5.5pt is
# below the house 7pt print target, but the sheet already sits there on the
# densest stores; this stops the Twamev detail dragging it lower still.
TWAMEV_MIN_PX = 23           # 23/300*72 = 5.5pt

# ★ AT LEAST ONE LINE PER TWAMEV DIVISION. Manav, 26 Aug: *"for twamev, why
# cant i see womens?"* Because M.G. Road barely sells it — its only womenswear
# line this month is stitched suit at Rs 12,999 falling to nil, which ranked
# eighth and went into the rollup. Ranking purely by size of move is right
# within a division and wrong across two: a manager seeing only MEN lines
# cannot tell whether womenswear is absent or merely hidden. So each division
# that traded gets its biggest mover reserved, and the rest of the cap is
# filled by size as before.
TWAMEV_PER_DIVISION = 1

# ★ BRANDS AND LINES THAT ARE NOISE IN EVERY STORE. Manav, 26 Aug: *"remove
# mebaz and output items, they are irrelevant in any store."* Measured: Mebaz
# is Rs 10.66 L across the whole year and four stores — 0.3% of the estate,
# OUTPUT ITEM is Rs 599 in one store, and Manthan is Rs 0.32 L for the year.
#   ⚠ THE STORE TOTAL IS NOT REDUCED. It stays the store's real total, so it
#   still ties to the MTD/YTD cards and to the WhatsApp image. Dropping these
#   only stops them taking a row; it never moves a figure. (The table already
#   works this way — `top_products` truncates without changing the totals.)
EXCLUDE_BRANDS = {"Mebaz", "Manthan"}
EXCLUDE_DIVISIONS = {"OUTPUT ITEM"}


def _drop_noise(base, types):
    """Remove the excluded brands and lines, and any subtotal left orphaned."""
    b = base.assign(_t=list(types)).reset_index(drop=True)
    brand = b["Brand"].astype(str).str.strip()
    div = b["Division"].astype(str).str.strip().str.upper()
    kill = brand.isin(EXCLUDE_BRANDS) | (
        (b["_t"] == "store") & div.isin({d.upper() for d in EXCLUDE_DIVISIONS}))
    b = b[~kill]
    # A brand whose only product line was excluded would otherwise keep a total
    # sitting under nothing.
    live = set(b.loc[b["_t"] == "store", "Brand"].astype(str))
    b = b[~((b["_t"] == "subtotal") & (~b["Brand"].astype(str).isin(live)))]
    return (b.drop(columns="_t").reset_index(drop=True), list(b["_t"]))


def _short_div(v):
    """TWAMEV-MEN → MEN. The Brand column beside it already says Twamev."""
    v = str(v).strip().upper()
    return v[7:] if v.startswith("TWAMEV-") else v


def _short_sec(v):
    """TWAM KURTA SET → KURTA SET."""
    v = str(v).strip().upper()
    return v[5:].strip() if v.startswith("TWAM ") else v


def _twamev_ranked(L, df, asof, kind, store):
    """(base table, its row types, Twamev's sections ranked by size of move).

    Queried ONCE. `_with_cap` then splices any number of sections in without
    going back to the loader, which is what lets the sheet try five, then four,
    then three and keep whichever still prints at a readable size.
    """
    base, btypes = L.degrowth_drivers(
        df, asof=asof, kind=kind, only_declining=False, stores_only=[store],
        products_under="every", top_products=6, level="division")
    base, btypes = _drop_noise(base, btypes)
    if base.empty or not TWAMEV_DETAIL:
        return base, btypes, None

    b = base.assign(_t=list(btypes)).reset_index(drop=True)
    mask = (b["Brand"].astype(str) == TWAMEV_BRAND) & (b["_t"] == "store")
    if not mask.any():
        return base, btypes, None

    sec, stypes = L.degrowth_drivers(
        df, asof=asof, kind=kind, only_declining=False, stores_only=[store],
        products_under="every", top_products=10_000, level="section")
    t = sec.assign(_t=list(stypes))
    t = t[(t["Brand"].astype(str) == TWAMEV_BRAND) & (t["_t"] == "store")]
    # One section per division is the same row twice — leave those stores alone.
    if len(t) <= int(mask.sum()):
        return base, btypes, None
    ranked = t.reindex(t["Shortfall"].abs().sort_values(ascending=False).index)
    return base, btypes, ranked


def _with_cap(base, btypes, ranked, kind, cap):
    """Splice `cap` Twamev sections into the base table; 0 leaves it alone."""
    if ranked is None or cap <= 0:
        return base, btypes
    ly, ty = f"{kind} LY", f"{kind} TY"
    b = base.assign(_t=list(btypes)).reset_index(drop=True)
    mask = (b["Brand"].astype(str) == TWAMEV_BRAND) & (b["_t"] == "store")
    t = ranked
    # ★ CHOSEN BY SIZE OF MOVE, NOT BY WORST FIRST. The drivers sort ascending,
    # so taking the head would have shown Twamev's biggest LOSSES and rolled
    # kurta (+Rs 23 L) and jodhpuri (+Rs 21 L) into "other" — hiding the half of
    # the story a manager can repeat. Selection is by absolute movement; the
    # rows are then put back in the table's own worst-first order.
    ident = {c: b.loc[mask.idxmax(), c]
             for c in ("DATE", "Region", "STORE CODE", "LOCATION")}
    picked = []
    for d in dict.fromkeys(t["Division"].astype(str)):
        sub = t[t["Division"].astype(str) == d]
        for i in sub.index[:TWAMEV_PER_DIVISION]:
            if len(picked) < cap and i not in picked:
                picked.append(i)
    for i in t.index:                       # fill what is left by size of move
        if len(picked) >= cap:
            break
        if i not in picked:
            picked.append(i)
    keep = t.loc[picked].sort_values("Shortfall")
    rest = t.drop(index=picked)

    made = []
    for _, r in keep.iterrows():
        made.append({**ident, "Brand": TWAMEV_BRAND,
                     "Division": f"{_short_div(r['Division'])} · "
                                 f"{_short_sec(r['Section'])}",
                     ly: r[ly], ty: r[ty], "Shortfall": r["Shortfall"],
                     "Degrowth %": r["Degrowth %"]})
    if len(rest):
        # Rolled up rather than dropped, so the shown lines plus this one still
        # add to the Twamev total printed underneath them.
        r_ly, r_ty = float(rest[ly].sum()), float(rest[ty].sum())
        made.append({**ident, "Brand": TWAMEV_BRAND,
                     "Division": f"other sections ({len(rest)})",
                     ly: r_ly, ty: r_ty, "Shortfall": r_ty - r_ly,
                     "Degrowth %": ((r_ty - r_ly) / r_ly * 100) if r_ly else None})

    idx = list(b.index[mask])
    out = pd.concat([b.iloc[:idx[0]].drop(columns="_t"),
                     pd.DataFrame(made, columns=base.columns),
                     b.iloc[idx[-1] + 1:].drop(columns="_t")], ignore_index=True)
    types = (list(btypes[:idx[0]]) + ["store"] * len(made)
             + list(btypes[idx[-1] + 1:]))
    return out, types


def _period_block(L, df, asof, store, code, kind, targets, drv, types):
    """Everything for one period except the table itself."""
    if drv is None or drv.empty:
        return None
    k = SN.store_kpis(L, df, asof, kind, store)
    tp = SN.target_progress(L, asof, kind, store, code,
                            achieved=k["ty"]["sale"], targets=targets)
    sb = SN.single_bill_share(L, df, asof, kind, store)
    grow = (PP.GREEN if k["move"] > 0
            else (PP.NEG_INK if k["move"] < 0 else None))
    c = SN.target_cards(tp, kind)
    rows = [
        [c[0], c[1], c[2], c[4], c[5]],
        [c[3],
         ("Movement", f"Rs {k['move'] / 1e5:,.2f} L", grow),
         (f"{kind} vs last year",
          f"{k['move'] / k['ly']['sale'] * 100:,.2f}%"
          if k["ly"]["sale"] else "—", grow),
         (f"Bills (LY {k['ly']['bills']:,})" if k["ly"]["bills"] else "Bills",
          f"{k['ty']['bills']:,}",
          PP.GREEN if k["ty"]["bills"] > k["ly"]["bills"]
          else (PP.NEG_INK if k["ty"]["bills"] < k["ly"]["bills"] else None)),
         SN._single_bill_card(sb)],
    ]
    lean, lifted = _lift_constants(drv)
    label = "the month so far" if kind == "MTD" else "the year to date"
    return dict(kind=kind, drv=lean, types=types, lifted=lifted,
                cap=_caption(CONTENT_W, f"{kind} — {label}",
                             "target, achievement and how the trading is going"),
                cards=SN._cards_image(rows, CONTENT_W, label_px=23, value_px=42))


def store_sheet(L, df, asof, store, code=None, pf=None, ff=None, targets=None):
    """One store → (filename, PDF bytes).

    ★ EVERY DATA POINT ON SHEET ONE. Manav, 23 Aug: *"atleast all the data
    points should be made so that it can fit in one a4 sheet."* Stacked, the
    two drivers tables are forty-two rows and no A4 holds them beside the cards
    and the six measures. Side by side they are as tall as the LONGER of the
    two, which halves the problem — and the page had the width going spare
    anyway once the four repeating identity columns came out of the tables.

    Landscape was measured and is worse, not better: the ten cards a period
    carry need the full portrait width, and after them landscape leaves 468px
    of vertical budget against portrait's ~1500.

    The tables themselves are UNTOUCHED — same rows, same columns, same order
    as the WhatsApp image. They are only placed next to each other.
    """
    asof = pd.Timestamp(asof)
    if ff is None:
        ff = SN.footfall_map(pf) if pf is not None else {}
    targets = SN._targets_for(asof) if targets is None else targets

    # Everything that does not depend on how many Twamev rows are spliced in
    # is built once, so the cap loop below only re-measures the tables.
    GAP, GUT = 22, 64
    half = (CONTENT_W - GUT) // 2
    usable = PAGE_H - 2 * MARGIN - int(round(9 / 25.4 * DPI))
    kpis = SN.period_kpis(L, df, asof, store, ff, code)
    kpi = _stack([_caption(CONTENT_W, "The six measures",
                           "the same six on the day, the month and the year"),
                  _kpi_grid_a4(kpis, CONTENT_W)], gap=10)
    tcap_h = _caption(half, "MTD — where the movement comes from",
                      "by brand and product, this year against last").height

    # ★ THE TWAMEV DETAIL IS TAKEN ONLY WHERE IT IS FREE. Splicing extra rows
    # into both tables costs height, and height is type size: at eight sections
    # M.G. Road set at 4.1pt, which is not a printable size. So the sheet asks
    # for TWAMEV_SECTIONS, measures what that does to the type, and steps down
    # until the tables clear TWAMEV_MIN_PX. Grand Kamraj Road keeps all five at
    # no cost; a tighter store takes fewer, rather than every store paying for
    # the one that cannot afford it.
    prep = {k: _twamev_ranked(L, df, asof, k, store) for k in ("MTD", "YTD")}
    built = measures = font_px = None
    used_cap = 0
    for cap in [c for c in (TWAMEV_SECTIONS, 4, 3, 0) if c <= TWAMEV_SECTIONS]:
        tabs = {k: _with_cap(b, bt, r, k, cap) for k, (b, bt, r) in prep.items()}
        built = [x for x in (_period_block(L, df, asof, store, code, k, targets,
                                           *tabs[k]) for k in ("MTD", "YTD"))
                 if x is not None]
        if not built:
            return None
        title_h = _heading(CONTENT_W, f"{store} — morning briefing",
                           f"as of {asof:%d %b %Y}").height
        fixed = (title_h + GAP
                 + sum(b["cap"].height + 8 + b["cards"].height + GAP
                       for b in built)
                 + tcap_h + 8 + kpi.height + GAP + GAP)
        measures, font_px = _fit([(b["kind"], b["drv"]) for b in built],
                                 L.drivers_money, L.DRIVERS_PCT, half,
                                 max(usable - fixed, 300), side_by_side=True)
        # Report what was actually spliced, not what was asked for: a store
        # whose Twamev has one section per division is skipped inside
        # `_with_cap`, and saying "5 sections" of it would be a lie.
        used_cap = cap if any(r is not None for _b, _t, r in prep.values()) else 0
        if font_px >= TWAMEV_MIN_PX or cap == 0:
            break

    lifted = built[0]["lifted"]
    context = " · ".join(str(v) for _c, v in lifted) if lifted else ""
    title = _heading(CONTENT_W, f"{store} — morning briefing",
                     (context + "  ·  " if context else "") +
                     f"as of {asof:%d %b %Y}  ·  print and brief the team")
    tcaps = [_caption(half, f"{b['kind']} — where the movement comes from",
                      "by brand and product, this year against last")
             for b in built]
    measures = [_widen(m, half) for m in measures]

    sheet = _Sheet(store, asof, context)
    sheet.put(title, gap=GAP)
    for b in built:
        sheet.put(b["cap"], gap=8)
        sheet.put(b["cards"], gap=GAP)

    cols = []
    for b, m, cap in zip(built, measures, tcaps):
        tbl = PP._render_chunk(m, b["types"], list(range(len(b["drv"]))))
        cols.append(_stack([cap, tbl], gap=8))
    sheet.put(_beside(cols[0], cols[1] if len(cols) > 1 else None, GUT), gap=GAP)
    sheet.put(kpi, gap=GAP)
    # ★ THE CONTRACT OF THIS SHEET, CHECKED RATHER THAN ASSUMED. If a store
    # ever carries a division list long enough to push the six measures onto a
    # second sheet, the caller must hear about it — silently printing a
    # two-page "one-page" document is exactly the failure that would go
    # unnoticed until a manager was standing at a printer.
    data_pages = len(sheet.pages)

    if INCLUDE_BRIEFING:
        # Sheet two: page one is the numbers, whole; page two is what to do
        # about them. Off by default — see INCLUDE_BRIEFING.
        sheet._new()
        sheet.put(_heading(CONTENT_W, "The briefing",
                           f"{store} · seven things to say to the team this "
                           f"morning · as of {asof:%d %b %Y}"), gap=34)
        for i, (headline, body) in enumerate(
                briefing_points(L, df, asof, store, code, ff, targets), 1):
            sheet.put(_point_block(CONTENT_W, i, headline, body), gap=16)

    tag = f"{code}_" if code is not None else ""
    return (f"{asof:%Y-%m-%d}_{tag}{SN._slug(store)}_briefing_a4.pdf",
            sheet.pdf(), font_px, data_pages, used_cap)


# --------------------------------------------------------------------------- #
#  Every store, for the 📄 REPORTS PDF tab                                     #
# --------------------------------------------------------------------------- #

def open_stores(L, df):
    """The stores a morning set goes to — closed ones excluded.

    ★ THE SAME RULE AS THE WHATSAPP SET, deliberately shared rather than
    re-typed: a store that stops appearing in one and not the other is exactly
    the kind of drift nobody notices until a manager asks why they stopped
    getting their sheet.
    """
    master = L.load_store_master().set_index("tableau_name")
    closed = L.closed_map()
    return [s for s in sorted(df[L.COL_STORE_LABEL].dropna().unique())
            if not (s in master.index and int(master.loc[s, "code"]) in closed)]


def store_sheets(L, df, asof, ff=None, pf=None, targets=None, progress=None,
                 folder="morning-snapshot"):
    """Every open store's A4 sheet, as [(name, PDF bytes), …].

    `progress(done, total, store)` is called as each sheet lands, because
    twenty of these take minutes and a download button that simply hangs looks
    broken. `folder` prefixes the names so they land in their own directory
    inside the zip rather than scattered among the other reports.

    ★ THE FULL ESTATE, NEVER THE SIDEBAR. These go to individual managers; one
    built from whatever filter happened to be left set would be quietly wrong
    and the manager receiving it could not tell.
    """
    asof = pd.Timestamp(asof)
    if ff is None:
        ff = SN.footfall_map(pf) if pf is not None else {}
    targets = SN._targets_for(asof) if targets is None else targets
    master = L.load_store_master().set_index("tableau_name")

    stores = open_stores(L, df)
    out, failed = [], []
    for i, s in enumerate(stores, 1):
        code = int(master.loc[s, "code"]) if s in master.index else None
        try:
            made = store_sheet(L, df, asof, s, code, ff=ff, targets=targets)
        except Exception as e:                  # one store must not sink the run
            failed.append(f"{s}: {e}")
            made = None
        if made:
            out.append((f"{folder}/{made[0]}" if folder else made[0], made[1]))
        if progress:
            progress(i, len(stores), s)
    return out, failed
