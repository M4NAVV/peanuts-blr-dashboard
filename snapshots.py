"""Report → PNG, for the morning WhatsApp send.

Each snapshot is self-contained: a title saying what it is and as of when, the
summary cards, then the table. Someone reading it in a group chat has no
sidebar and no context, so anything they need to interpret the numbers has to
be inside the image.

Rendering reuses the report-PDF engine rather than a second implementation, so
a snapshot, its dashboard tab and its printed page are the same table in the
same palette. Crucially it also inherits that engine's rule: text is rasterised
ONCE at final size and the image is never resampled. Downscaling is what makes
a table look soft, and these are read by pinch-zooming on a phone, where
softness is exactly what hurts.
"""
from __future__ import annotations

import io

import pandas as pd
from PIL import Image, ImageDraw

import portfolio_pdf as PP

# Same fills as the tables, so the cards belong to the sheet rather than
# sitting on top of it.
CARD_BG = (255, 255, 255)
CARD_EDGE = PP.GRID
TITLE_INK = (0, 0, 0)
SUB_INK = (90, 90, 90)

PAD = 26                 # outer margin
CARD_GAP = 16
CARD_PAD_X, CARD_PAD_Y = 22, 18


# Above this many cards in a row the value text starts colliding with the card
# edge on a phone. Nine cards therefore run as two rows, not one squeezed line.
MAX_CARDS_PER_ROW = 5


def _cards_image(cards, width, label_px=22, value_px=44):
    """Lay out cards across `width`.

    `cards` is either a flat [(label, value), …] or a LIST OF ROWS,
    [[(label, value), …], [(label, value), …]].

    ★ ROWS ARE GROUPED BY MEANING, NOT BY WHAT FITS. Nine cards split 5-and-4
    reads as one arbitrary run that happened to wrap. Split 6-and-3 it reads as
    two statements: what the target is and where the store stands against it,
    then what moved. A caller that knows the grouping passes rows; anything else
    wraps at `MAX_CARDS_PER_ROW`.
    """
    if not cards:
        return None
    lab_f, _ = PP._ft(label_px)
    _, val_f = PP._ft(value_px)

    if cards and isinstance(cards[0], (list, tuple)) and cards[0] and \
            isinstance(cards[0][0], (list, tuple)):
        rows = [r for r in cards if r]
    else:
        n = len(cards)
        per_row = min(n, MAX_CARDS_PER_ROW)
        rows = [cards[i:i + per_row] for i in range(0, n, per_row)]

    # One column width across every row, so cards line up down the page even
    # when the rows hold different numbers of them.
    per_row = max(len(r) for r in rows)
    cw = (width - CARD_GAP * (per_row - 1)) // per_row
    lab_h = lab_f.getmetrics()[0] + lab_f.getmetrics()[1]
    val_h = val_f.getmetrics()[0] + val_f.getmetrics()[1]
    ch = CARD_PAD_Y * 2 + lab_h + 8 + val_h

    img = Image.new("RGB", (width, ch * len(rows) + CARD_GAP * (len(rows) - 1)),
                    (255, 255, 255))
    d = ImageDraw.Draw(img)
    for ri, row in enumerate(rows):
        y0 = ri * (ch + CARD_GAP)
        x = 0
        for card in row:
            label, value = card[0], card[1]
            ink = card[2] if len(card) > 2 else None
            d.rectangle([x, y0, x + cw - 1, y0 + ch - 1], fill=CARD_BG,
                        outline=CARD_EDGE, width=1)
            d.text((x + CARD_PAD_X, y0 + CARD_PAD_Y), str(label), font=lab_f,
                   fill=SUB_INK)
            # A card may state its own ink. Otherwise the old rule stands:
            # negative figures pick up the same red the tables use.
            col = ink or (PP.NEG_INK if str(value).lstrip("₹Rs ").startswith("-")
                          else TITLE_INK)
            d.text((x + CARD_PAD_X, y0 + CARD_PAD_Y + lab_h + 8), str(value),
                   font=val_f, fill=col)
            x += cw + CARD_GAP
        x += cw + CARD_GAP
    return img


def render(df, *, title, subtitle="", cards=(), money=(), pct=(), sign=(),
           row_types=None, row_bg=None, cell_rules=(), money_dp=0,
           font_px=32, header_px=28) -> bytes:
    """One report → PNG bytes."""
    m = PP._measure_table(df, money=money, pct=pct, sign=sign, money_dp=money_dp,
                          font_px=font_px, header_px=header_px)
    table = PP._render_chunk(m, row_types or ["store"] * len(df),
                             list(range(len(df))), row_bg=row_bg,
                             cell_rules=cell_rules)

    title_f, title_b = PP._ft(40)
    sub_f, _ = PP._ft(24)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    inner = max(table.width, 900)
    cards_img = _cards_image(cards, inner) if cards else None

    th = title_b.getmetrics()[0] + title_b.getmetrics()[1]
    sh = (sub_f.getmetrics()[0] + sub_f.getmetrics()[1] + 8) if subtitle else 0
    ch = (cards_img.height + 22) if cards_img is not None else 0
    H = PAD + th + 10 + sh + ch + table.height + PAD
    W = inner + PAD * 2

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    y = PAD
    d.text((PAD, y), title, font=title_b, fill=TITLE_INK)
    y += th + 10
    if subtitle:
        d.text((PAD, y), subtitle, font=sub_f, fill=SUB_INK)
        y += sh
    if cards_img is not None:
        img.paste(cards_img, (PAD, y))
        y += cards_img.height + 22
    img.paste(table, (PAD + (inner - table.width) // 2, y))

    buf = io.BytesIO()
    # No resampling anywhere in this path — see the module docstring.
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# The morning set
# --------------------------------------------------------------------------- #
# Filenames are date-first so a folder sorts chronologically, and carry the
# store code before the name so a manager's files group together.
def _slug(text):
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def store_wise(L, df, asof):
    """Store-wise MTD / YTD, year on year — both periods in one table."""
    rep, rtypes = L.region_store_report(df, asof=asof)
    money = [c for c in ("MTD LY", "MTD TY", "GD MTD Value", "Day Sales",
                         "YTD LY", "YTD TY", "GD YTD Value") if c in rep.columns]
    pct = [c for c in ("GD MTD %", "GD YTD %") if c in rep.columns]
    png = render(rep, title="VFL — Store-wise MTD / YTD, year on year",
                 subtitle=f"As of {asof:%d %b %Y} · all stores, unfiltered",
                 money=money, pct=pct,
                 sign=pct + [c for c in ("GD MTD Value", "GD YTD Value")
                             if c in rep.columns],
                 row_types=rtypes)
    return f"{asof:%Y-%m-%d}_vfl_store-wise-mtd-ytd.png", png


def degrowth_region(L, df, asof, kind, region):
    """The degrowth watchlist for one region and one period."""
    dg = L.degrowth_report(df, asof=asof, kind=kind)
    dg = dg[dg["region"] == region]
    if dg.empty:
        return None
    tot, ly = dg["shortfall"].sum(), dg["prior"].sum()
    disp = dg.copy()
    disp.insert(0, "DATE", f"{asof:%d-%m-%Y}")
    disp = disp.rename(columns={
        "region": "Region", "code": "STORE CODE", "location": "LOCATION",
        "prior": f"{kind} LY", "cur": f"{kind} TY",
        "shortfall": "Shortfall", "growth": "Degrowth %"})
    disp["STORE CODE"] = disp["STORE CODE"].astype(int)
    png = render(
        disp, title=f"VFL — Degrowth watchlist · {region} · {kind}",
        subtitle=f"Stores where {kind} this year < last year · "
                 f"as of {asof:%d %b %Y} · unfiltered",
        cards=[("Stores degrowing", f"{len(dg)}"),
               ("Total shortfall", f"₹{tot / 1e5:,.2f} L"),
               ("Degrowth %", f"{tot / ly * 100:,.2f}%" if ly else "—")],
        money=[f"{kind} LY", f"{kind} TY", "Shortfall"], pct=["Degrowth %"],
        sign=["Shortfall", "Degrowth %"])
    return f"{asof:%Y-%m-%d}_vfl_degrowth_{_slug(region)}_{kind}.png", png


def drivers_store(L, df, asof, kind, store, code=None):
    """One store's full brand-and-product breakdown — sent to that manager.

    Every store gets one, not just the declining, so a good month reads as a
    good month rather than the manager receiving nothing.
    """
    drv, types = L.degrowth_drivers(
        df, asof=asof, kind=kind, only_declining=False, stores_only=[store],
        products_under="every", top_products=6, level="division")
    if drv.empty:
        return None
    tot = float(drv.loc[[t == "block" for t in types], "Shortfall"].sum())
    ly = float(drv.loc[[t == "block" for t in types], f"{kind} LY"].sum())
    png = render(
        drv, title=f"{store} — {kind} performance drivers",
        subtitle=f"Where the movement comes from, by brand and product · "
                 f"as of {asof:%d %b %Y}",
        cards=[("Movement", f"₹{tot / 1e5:,.2f} L"),
               (f"{kind} vs last year", f"{tot / ly * 100:,.2f}%" if ly else "—"),
               ("Lines shown", f"{sum(1 for t in types if t == 'store')}")],
        money=L.drivers_money(kind), pct=L.DRIVERS_PCT,
        sign=["Shortfall"] + L.DRIVERS_PCT, row_types=types)
    tag = f"{code}_" if code is not None else ""
    return f"{asof:%Y-%m-%d}_{tag}{_slug(store)}_drivers_{kind}.png", png


# --------------------------------------------------------------------------- #
# The coaching block — what a manager can do something about
# --------------------------------------------------------------------------- #
# ★ IT NEVER BLAMES ANYTHING OUTSIDE THE STORE (Manav, 17 Aug). No footfall, no
# market, no catchment, no weather — a manager handed an external cause has been
# handed a reason to do nothing. Every line names something the store did and
# something it can do: bills WRITTEN, pieces PER BILL, price PER PIECE, and
# accessories ATTACHED. The arithmetic is the same either way; the wording is
# what decides whether the page is useful on a Monday morning.
KPI_INK = (0, 0, 0)
KPI_SUB = (90, 90, 90)
KPI_GOOD = (31, 107, 74)
KPI_BAD = (163, 22, 31)


def store_kpis(L, df, asof, kind, store):
    """Sale = bills x pieces-per-bill x price-per-piece, and what moved it.

    The three multiply to the sale, so the movement splits between them exactly
    — which is what lets the block say where a shortfall actually sits instead
    of restating that there is one.
    """
    cur, pri = L.report_frames(df, kind, asof=asof)

    def one(f):
        d = f[f[L.COL_STORE_LABEL] == store]
        sale = float(d[L.COL_AMOUNT].sum())
        bills = L.bill_count(d)          # distinct bill numbers — see loader
        units = float(d[L.COL_QTY].sum())
        return {"sale": sale, "bills": bills, "units": units,
                "abv": sale / bills if bills else 0.0,
                "abs": units / bills if bills else 0.0,
                "asp": sale / units if units else 0.0}

    t, l = one(cur), one(pri)
    # Each driver held at last year's level except the one being measured.
    d_bills = (t["bills"] - l["bills"]) * l["abv"]
    d_abs = t["bills"] * (t["abs"] - l["abs"]) * l["asp"]
    d_asp = t["bills"] * t["abs"] * (t["asp"] - l["asp"])
    return {"ty": t, "ly": l, "move": t["sale"] - l["sale"],
            "d_bills": d_bills, "d_abs": d_abs, "d_asp": d_asp,
            "asof": pd.Timestamp(asof)}


# --------------------------------------------------------------------------- #
#  Target progress — the six figures a manager is actually measured on          #
# --------------------------------------------------------------------------- #

def _unit_for(values):
    """Crore or lakh, chosen from the LARGEST figure a group has to show.

    ★ ONE UNIT PER GROUP OF COMPARABLE FIGURES. A year target of Rs 1,601.25 L
    runs into the edge of its card, and a flagship's would overflow it — but
    switching each card independently would print a target in crore beside an
    achievement in lakh, and a manager comparing them would have to convert in
    their head. So the target, the achievement and the balance share one unit,
    chosen from whichever is biggest; the two per-day rates share their own,
    because a daily figure in crore is all zeros.
    """
    big = max((abs(v) for v in values if v is not None), default=0.0)
    return ("Cr", 1e7) if big >= 1e7 else ("L", 1e5)


def _money(v, unit=("L", 1e5)):
    """Money in the given unit, or an em dash when there is none.

    A missing target must never print as zero: a store with no target entered
    would read as having been asked for nothing and having beaten it.
    """
    if v is None:
        return "—"
    suffix, div = unit
    return f"Rs {v / div:,.2f} {suffix}"


def _lakh(v):
    """Back-compat shim for callers that want lakhs regardless."""
    return _money(v, ("L", 1e5))


def target_progress(L, asof, kind, store, code=None, achieved=0.0, targets=None):
    """Target · Achieved · Ach % · Avg day sales · Balance · Per day required.

    Manav, 21 Aug: *"Target, Achieved, Ach %, Avg Sales perday, Balance target,
    Avg required perday … for both Mtd and ytd level."*

    ★ THE RULES ARE LIFTED FROM THE NIGHT SMS (`report_td.tva_exec_rows`), not
    re-derived, so the morning picture and the night report cannot disagree
    about what "balance" or "per day required" mean:

      · Measured against the WHOLE period's target — the month's for the month,
        the YEAR's for the year — not the part of it elapsed.
      · Balance days EXCLUDE today. Today's takings are already inside the
        achieved figure, so counting today again would understate the rate.
      · Average day sales is the store's own turnover over the days IT has been
        trading, takeover-anchored: South counts from 19 April, East from
        1 April, and a store that opened mid-month counts from its opening.
      · A store AHEAD of its target gets no per-day figure. Printing one would
        read as a demand where none exists.
    """
    import calendar

    asof = pd.Timestamp(asof)
    kind = kind.upper()

    if targets is None:
        try:
            import targets as TG
            targets = TG.for_month(asof)
        except Exception:
            targets = {}

    entry = targets.get(int(code)) if code is not None else None
    tgt = (entry or {}).get("mtd" if kind == "MTD" else "ytd")

    fy = asof.year if asof.month >= 4 else asof.year - 1
    fy_start = pd.Timestamp(fy, 4, 1)
    period_start = asof.replace(day=1) if kind == "MTD" else fy_start

    # Each store keeps its own year start, exactly as every other figure in the
    # pack does.
    try:
        tk = L.takeover_map().get(store)
    except Exception:
        tk = None
    if tk is not None and pd.notna(tk):
        period_start = max(period_start, pd.Timestamp(tk))

    elapsed = max((asof - period_start).days + 1, 1)
    if kind == "MTD":
        days_left = calendar.monthrange(asof.year, asof.month)[1] - asof.day
    else:
        fy_end = pd.Timestamp(fy + 1, 3, 31)
        days_left = max((fy_end - asof).days, 0)

    bal = (tgt - achieved) if tgt else None
    # ★ HOW FAR THROUGH THE PERIOD WE ARE. Without this, "82.8% achieved" looks
    # like failure on the 20th of a 31-day month, when the store is in fact well
    # ahead — you would only expect 65% by then. Every store would show red for
    # thirty days and green on the thirty-first, which is not information.
    total_days = elapsed + days_left
    pace_pct = (elapsed / total_days * 100) if total_days else None

    return {
        "target": tgt,
        "achieved": achieved,
        "ach_pct": (achieved / tgt * 100) if tgt else None,
        "avg_day": achieved / elapsed,
        "balance": bal,
        "days_left": days_left,
        "elapsed": elapsed,
        "pace_pct": pace_pct,
        "per_day": (bal / days_left) if (bal and bal > 0 and days_left > 0) else None,
        "from": period_start,
    }


def target_cards(tp, kind):
    """The six as card tuples, in the order he listed them.

    ★ COLOUR SAYS GOOD OR BAD, NOT POSITIVE OR NEGATIVE. The card strip used to
    redden anything whose text began with a minus, which is right for movement
    and exactly backwards for a balance: a store that has BEATEN its target has
    a negative balance, and printing that in red tells a manager they have
    failed at the moment they have succeeded.

    So a beaten target is shown as what it is — "Rs 0.20 Cr ahead", in the same
    green the night report uses at 100% — and the balance only reddens when
    there is genuinely something still to find.
    """
    pct = tp["ach_pct"]
    # Comparable figures share a unit; the daily rates get their own.
    big = _unit_for([tp["target"], tp["achieved"], tp["balance"]])
    rate = _unit_for([tp["avg_day"], tp["per_day"]])

    # ★ COLOURED AGAINST PACE, NOT AGAINST 100. On the 20th of a 31-day month a
    # store should be around 65% of the way to its target; 82.8% is comfortably
    # ahead and must not read as a failure. The label carries the expected
    # figure so the colour is never magic.
    pace = tp.get("pace_pct")
    if pct is None:
        pct_txt, pct_ink, pct_lab = "—", None, "Achieved %"
    else:
        pct_txt = f"{pct:,.1f}%"
        pct_ink = None if pace is None else (PP.GREEN if pct >= pace else PP.NEG_INK)
        pct_lab = ("Achieved %" if pace is None
                   else f"Achieved % (pace {pace:,.0f}%)")

    # ★ ONE CARD CARRIES THE VERDICT, THE REST ARE FACTS. Balance is simply what
    # is left to sell; on the 20th of the month there is obviously some, and
    # reddening it says "you are failing" to a store that is ahead of pace.
    # Achieved-vs-pace above already answers whether they are winning, so the
    # balance only takes a colour when the target has actually been beaten.
    bal = tp["balance"]
    if bal is None:
        bal_txt, bal_ink = "—", None
    elif bal <= 0:
        bal_txt, bal_ink = f"{_money(-bal, big)} ahead", PP.GREEN
    else:
        bal_txt, bal_ink = _money(bal, big), None

    return [
        (f"{kind} target", _money(tp["target"], big)),
        (f"{kind} achieved", _money(tp["achieved"], big)),
        (pct_lab, pct_txt, pct_ink),
        ("Avg day sales", _money(tp["avg_day"], rate)),
        ("Balance target", bal_txt, bal_ink),
        (f"Per day reqd ({tp['days_left']}d)",
         _money(tp["per_day"], rate) if tp["per_day"] is not None
         else ("on track" if tp["target"] else "—"),
         PP.GREEN if (tp["target"] and tp["per_day"] is None) else None),
    ]


def single_bill_share(L, df, asof, kind, store):
    """Share of bills that took exactly ONE piece, this year and last.

    ★ WHAT COUNTS AS SINGLE: one PIECE on the bill, not one line. The two are
    close on this estate — Jayanagar reads 45.6% by pieces against 43.6% by
    lines this month — but "a customer who bought one thing" is what a manager
    means, and it is the figure that pairs with pieces-per-bill.

    ★★ THE THRESHOLD IS `<= 1`, MATCHING `_one_kpi` EXACTLY. The KPI panel at
    the foot of the same document has counted single-piece bills since 18 Aug,
    and it uses `<= 1` so that a return or exchange netting to zero or less
    still counts as one. Using `== 1` here instead differed on ten bills across
    five stores — a fraction of a percent, and enough to print two different
    numbers for the same thing on one page. Any change to one of these two must
    change the other.

    ★ LOWER IS BETTER, which is why this needs its own colour rule. Every other
    card on the strip is good when it rises; a single-bill share that climbs
    means more customers leaving with one item, and that is the shortfall the
    coaching notes exist to attack.
    """
    cur, pri = L.report_frames(df, kind, asof=asof)

    def one(f):
        d = f[f[L.COL_STORE_LABEL] == store]
        d = d[d[L.COL_BILL_UID].notna()]
        if d.empty:
            return None
        qty = d.groupby(L.COL_BILL_UID)[L.COL_QTY].sum()
        if not len(qty):
            return None
        return float((qty <= 1).mean())

    return {"ty": one(cur), "ly": one(pri)}


def attach_rate(L, df, asof, kind, store):
    """Of bills carrying a saree, lehenga or sherwani, how many took an
    accessory too. The one number on the page that is purely a staff habit."""
    cur, pri = L.report_frames(df, kind, asof=asof)
    CORE = ("SAREE", "LEHENGA", "SHERWANI")

    def one(f):
        d = f[f[L.COL_STORE_LABEL] == store]
        if d.empty:
            return None
        by = d.groupby(L.COL_BILL_UID)[L.COL_DIVISION].apply(
            lambda s: set(str(x).upper() for x in s))
        core = by[by.apply(lambda s: any(c in x for x in s for c in CORE))]
        if not len(core):
            return None
        got = core.apply(lambda s: any("ACCESSOR" in x for x in s))
        return {"bills": int(len(core)), "with": int(got.sum()),
                "rate": float(got.mean())}

    return {"ty": one(cur), "ly": one(pri)}


def coaching_lines(k, att, kind) -> list:
    """(heading, body) — plain sentences, every one about the store's own doing.

    The biggest mover names itself first, so the manager reads the thing worth
    acting on rather than the thing that happens to be first alphabetically.

    ★ AND THE FRAMING FOLLOWS THE SITUATION. A store that is level overall but
    writing fewer bills is not failing, and telling it "you are Rs 2.22 L down on
    bills" beside "2 more bills closes it" reads as nonsense — Siliguri lost
    Rs 2.22 L of bills and its basket put nearly all of it back. So a store that
    is holding is told what held, and where the room still is.
    """
    ty, ly = k["ty"], k["ly"]
    period = "month" if kind.upper() == "MTD" else "year"
    parts = [("bills you wrote", k["d_bills"]),
             ("pieces per bill", k["d_abs"]),
             ("price per piece", k["d_asp"])]
    parts.sort(key=lambda p: p[1])
    worst, worst_v = parts[0]
    best, best_v = parts[-1]
    out = []

    def bills_sentence():
        gap = ly["bills"] - ty["bills"]
        return (f"You wrote {ty['bills']:,} bills against {ly['bills']:,} — "
                f"{gap:,} fewer, worth Rs {abs(k['d_bills']) / 1e5:,.2f} L.")

    def asp_sentence():
        return (f"Your pieces went out at Rs {ty['asp']:,.0f} against "
                f"Rs {ly['asp']:,.0f} — Rs {abs(k['d_asp']) / 1e5:,.2f} L.")

    def abs_sentence():
        return (f"Bills left with {ty['abs']:,.2f} pieces against "
                f"{ly['abs']:,.2f} — Rs {abs(k['d_abs']) / 1e5:,.2f} L.")

    say = {"bills you wrote": bills_sentence, "price per piece": asp_sentence,
           "pieces per bill": abs_sentence}

    # Within a few per cent of last year is level, not behind: Siliguri is
    # 1.5% down and its basket has already covered nearly all of the bills it
    # lost, so the shortfall framing would read as nonsense beside a target of
    # two bills.
    level = k["move"] >= 0 or abs(k["move"]) / max(ly["sale"], 1) < 0.03
    if not level and worst_v < 0:
        # Behind, and one driver is carrying the shortfall.
        out.append(("Where it sits", say[worst]()))
        if worst == "bills you wrote" and ty["abv"]:
            need = int(round(abs(k["move"]) / ty["abv"]))
            per = max(need // max(k["asof"].day, 1), 1)
            out.append(("To close it",
                        f"{need:,} more bills at the Rs {ty['abv']:,.0f} you are "
                        f"already averaging — {per:,} a day."))
        elif worst == "price per piece" and ty["units"]:
            out.append(("To close it",
                        f"Rs {abs(k['move']) / ty['units']:,.0f} more on every "
                        f"piece you are already selling, or the same money made "
                        f"by showing the higher-value merchandise first."))
        elif ty["asp"]:
            out.append(("To close it",
                        f"One more piece on "
                        f"{int(round(abs(k['move']) / ty['asp'])):,} bills, at "
                        f"the Rs {ty['asp']:,.0f} you already achieve."))
    elif worst_v < 0:
        # Level or ahead overall, but one driver is still giving ground.
        out.append(("What held", f"{say[best]().replace('—', 'and worth')} "
                                 f"You are level on the {period}."
                    if best_v > 0 else
                    f"You are level on the {period}."))
        out.append(("Where the room is",
                    say[worst]() + f" Recover that at the "
                    f"Rs {ty['abv']:,.0f} you now average and it is on top."))
    else:
        out.append(("Where it sits",
                    f"{ty['bills']:,} bills at Rs {ty['abv']:,.0f}, "
                    f"{ty['abs']:,.2f} pieces each. All three drivers are at or "
                    f"above last year — hold them."))

    a_ty, a_ly = att["ty"], att["ly"]
    if a_ty:
        if a_ty["with"] == 0:
            was = (f", against {a_ly['with']} of {a_ly['bills']} last year"
                   if a_ly and a_ly["with"] else "")
            out.append(("Accessories",
                        f"{a_ty['bills']} bills carried a saree, lehenga or "
                        f"sherwani this {period}. None of them left with "
                        f"an accessory{was}."))
        else:
            was = (f" (last year {a_ly['rate'] * 100:,.0f}%)"
                   if a_ly else "")
            out.append(("Accessories",
                        f"{a_ty['with']} of {a_ty['bills']} saree, lehenga and "
                        f"sherwani bills took an accessory — "
                        f"{a_ty['rate'] * 100:,.0f}%{was}."))
    return out


def _kpi_panel(k, lines, width, kind):
    """The strip under the table: three drivers, then what to do about them."""
    lab_f, _ = PP._ft(22)
    _, val_b = PP._ft(38)
    sub_f, _ = PP._ft(21)
    head_f, head_b = PP._ft(24)
    body_f, _ = PP._ft(25)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    ty, ly = k["ty"], k["ly"]

    drivers = [
        ("Bills written", f"{ty['bills']:,}", f"was {ly['bills']:,}", k["d_bills"]),
        ("Pieces per bill", f"{ty['abs']:,.2f}", f"was {ly['abs']:,.2f}", k["d_abs"]),
        ("Price per piece", f"Rs {ty['asp']:,.0f}",
         f"was Rs {ly['asp']:,.0f}", k["d_asp"]),
    ]
    n = len(drivers)
    cw = (width - CARD_GAP * (n - 1)) // n
    lh = lab_f.getmetrics()[0] + lab_f.getmetrics()[1]
    vh = val_b.getmetrics()[0] + val_b.getmetrics()[1]
    sh = sub_f.getmetrics()[0] + sub_f.getmetrics()[1]
    card_h = CARD_PAD_Y * 2 + lh + vh + sh + 10

    bh = body_f.getmetrics()[0] + body_f.getmetrics()[1]
    # The gutter is measured off the widest heading, not guessed: "Where the
    # room is" is half again as wide as "To close it" and ran straight into its
    # own sentence at a fixed 200px.
    gutter = int(max(scratch.textlength(h, font=head_b)
                     for h, _ in lines) + 28)
    wrapped = []
    for head, body in lines:
        words, cur_line = body.split(), ""
        avail = width - CARD_PAD_X * 2 - gutter
        for w in words:
            trial = (cur_line + " " + w).strip()
            if scratch.textlength(trial, font=body_f) <= avail:
                cur_line = trial
            else:
                wrapped.append((head if not wrapped or wrapped[-1][0] != head
                                else "", cur_line))
                head, cur_line = "", w
        wrapped.append((head, cur_line))
    text_h = len(wrapped) * (bh + 6) + CARD_PAD_Y * 2

    img = Image.new("RGB", (width, card_h + 18 + text_h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, (lab, val, was, delta) in enumerate(drivers):
        x = i * (cw + CARD_GAP)
        d.rectangle([x, 0, x + cw - 1, card_h - 1], fill=CARD_BG, outline=CARD_EDGE)
        d.text((x + CARD_PAD_X, CARD_PAD_Y), lab, font=lab_f, fill=SUB_INK)
        ink = KPI_GOOD if delta >= 0 else KPI_BAD
        d.text((x + CARD_PAD_X, CARD_PAD_Y + lh + 2), val, font=val_b, fill=ink)
        d.text((x + CARD_PAD_X, CARD_PAD_Y + lh + vh + 6),
               f"{was}   {'+' if delta >= 0 else '-'}Rs "
               f"{abs(delta) / 1e5:,.2f} L", font=sub_f, fill=SUB_INK)

    y = card_h + 18
    d.rectangle([0, y, width - 1, y + text_h - 1], fill=CARD_BG, outline=CARD_EDGE)
    y += CARD_PAD_Y
    for head, body in wrapped:
        if head:
            d.text((CARD_PAD_X, y), head, font=head_b, fill=KPI_INK)
        d.text((CARD_PAD_X + gutter, y), body, font=body_f, fill=KPI_INK)
        y += bh + 6
    return img


def drivers_store_coached(L, df, asof, kind, store, code=None):
    """The drivers table with the coaching strip under it."""
    drv, types = L.degrowth_drivers(
        df, asof=asof, kind=kind, only_declining=False, stores_only=[store],
        products_under="every", top_products=6, level="division")
    if drv.empty:
        return None
    k = store_kpis(L, df, asof, kind, store)
    lines = coaching_lines(k, attach_rate(L, df, asof, kind, store), kind)

    table_png = render(
        drv, title=f"{store} — {kind} performance drivers",
        subtitle=f"Where the movement comes from, by brand and product · "
                 f"as of {asof:%d %b %Y}",
        cards=[("Movement", f"Rs {k['move'] / 1e5:,.2f} L"),
               (f"{kind} vs last year",
                f"{k['move'] / k['ly']['sale'] * 100:,.2f}%"
                if k["ly"]["sale"] else "—"),
               ("Bills", f"{k['ty']['bills']:,}")],
        money=L.drivers_money(kind), pct=L.DRIVERS_PCT,
        sign=["Shortfall"] + L.DRIVERS_PCT, row_types=types)

    top = Image.open(io.BytesIO(table_png))
    panel = _kpi_panel(k, lines, top.width - PAD * 2, kind)
    out = Image.new("RGB", (top.width, top.height + panel.height + PAD),
                    (255, 255, 255))
    out.paste(top, (0, 0))
    out.paste(panel, (PAD, top.height))
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    tag = f"{code}_" if code is not None else ""
    return f"{asof:%Y-%m-%d}_{tag}{_slug(store)}_drivers_{kind}.png", buf.getvalue()


# --------------------------------------------------------------------------- #
# v2 of the coaching block — five KPIs, three periods
# --------------------------------------------------------------------------- #
# Kept ALONGSIDE v1 rather than replacing it. Manav, 18 Aug: "we might be
# reverting back to a previous version or change things around so plan for
# that." So `drivers_store_coached` (three cards, one period) is untouched, this
# is a second entry point, and the tab picks between them with PANEL.
PERIODS = ("DAY", "MTD", "YTD")


def footfall_map(pf) -> dict:
    """{(store code, date): footfall} from the portfolio feed's own column.

    It is only filled from 12 August — 167 rows — so most days have none, and a
    conversion that divided a month of bills by five days of footfall would be
    nonsense. Every use of this pairs the two over the SAME days.
    """
    if pf is None or "FOOTFALL" not in getattr(pf, "columns", []):
        return {}
    f = pd.to_numeric(pf["FOOTFALL"], errors="coerce")
    ok = f.notna() & (f > 0)
    return {(int(c), pd.Timestamp(d)): float(v)
            for c, d, v in zip(pf.loc[ok, "code"], pf.loc[ok, "date"], f[ok])}


def _slice(L, df, asof, kind, store):
    """(this year, last year) for one store over DAY, MTD or YTD.

    MTD and YTD come off `report_frames`, so they are the same takeover-anchored,
    closure-capped windows the table above uses. DAY is the as-of against the
    same WEEKDAY a year back — a single date a year ago falls on a different day
    of the week and its year-on-year is mostly noise.
    """
    if kind == "DAY":
        # ★ THE LAST SETTLED DAY, NOT THE AS-OF. The newest day in the frame is
        # usually the night fill, which carries takings but no bill numbers —
        # inventing them would be fabricating transactions — so a DAY block on
        # the as-of would print every store at nil bills and a nil basket. This
        # is the same distinction `window_yoy_takeover` draws with `bills_to`.
        d = df[df[L.COL_STORE_LABEL] == store]
        settled = d[d[L.COL_BILL_UID].notna()]["date"]
        day = settled.max() if len(settled) else asof
        return (d[d["date"] == day],
                d[d["date"] == day - pd.Timedelta(days=364)])
    cur, pri = L.report_frames(df, kind, asof=asof)
    return (cur[cur[L.COL_STORE_LABEL] == store],
            pri[pri[L.COL_STORE_LABEL] == store])


def _one_kpi(L, d, ff, code, days):
    """Every figure the panel prints, for one slice."""
    sale = float(d[L.COL_AMOUNT].sum())
    units = float(d[L.COL_QTY].sum())
    bills = L.bill_count(d)              # distinct bill numbers — see loader
    out = {"sale": sale, "units": units, "bills": bills,
           "abv": sale / bills if bills else 0.0,
           "abs": units / bills if bills else 0.0,
           "asp": sale / units if units else 0.0,
           "single": 0, "single_units": 0.0, "single_val": 0.0,
           "conv": None, "conv_days": 0, "ff": 0.0, "conv_bills": 0}
    if bills:
        per = d.groupby(L.COL_BILL_UID).agg(q=(L.COL_QTY, "sum"),
                                            v=(L.COL_AMOUNT, "sum"))
        one = per[per["q"] <= 1]
        out["single"] = int(len(one))
        out["single_units"] = float(one["q"].sum())
        out["single_val"] = float(one["v"].sum())
    # ★ Conversion is paired day for day: bills on the days footfall was
    # counted, over the footfall counted on those same days. Never a month of
    # bills over a week of footfall.
    if ff and code is not None and len(d):
        have = sorted({pd.Timestamp(x) for x in d["date"].unique()
                       if (code, pd.Timestamp(x)) in ff})
        if have:
            got = d[d["date"].isin(have)]
            f_tot = sum(ff[(code, x)] for x in have)
            out.update(conv_days=len(have), ff=f_tot,
                       conv_bills=int(got[L.COL_BILL_UID].nunique()),
                       conv=(got[L.COL_BILL_UID].nunique() / f_tot * 100)
                       if f_tot else None)
    out["days"] = days
    return out


def period_kpis(L, df, asof, store, ff=None, code=None) -> dict:
    """DAY, MTD and YTD, each this year against last."""
    asof = pd.Timestamp(asof)
    ff = ff or {}
    out = {}
    for kind in PERIODS:
        cur, pri = _slice(L, df, asof, kind, store)
        t = _one_kpi(L, cur, ff, code, cur["date"].nunique() if len(cur) else 0)
        l = _one_kpi(L, pri, ff, code, pri["date"].nunique() if len(pri) else 0)
        d_bills = (t["bills"] - l["bills"]) * l["abv"]
        d_abs = t["bills"] * (t["abs"] - l["abs"]) * l["asp"]
        d_asp = t["bills"] * t["abs"] * (t["asp"] - l["asp"])
        out[kind] = {"ty": t, "ly": l, "move": t["sale"] - l["sale"],
                     "d_bills": d_bills, "d_abs": d_abs, "d_asp": d_asp,
                     "asof": asof}
    return out


def _fmt_kpi(which, t, l):
    """(headline, the line under it) for one KPI of one period."""
    if which == "bills":
        return f"{t['bills']:,}", f"was {l['bills']:,}"
    if which == "abv":
        return f"Rs {t['abv']:,.0f}", f"was Rs {l['abv']:,.0f}"
    if which == "abs":
        return f"{t['abs']:,.2f}", f"was {l['abs']:,.2f}"
    if which == "asp":
        return f"Rs {t['asp']:,.0f}", f"was Rs {l['asp']:,.0f}"
    if which == "single":
        pc = t["single"] / t["bills"] * 100 if t["bills"] else 0
        was = l["single"] / l["bills"] * 100 if l["bills"] else None
        val = t["single_val"] / t["sale"] * 100 if t["sale"] else 0
        return (f"{pc:,.0f}%",
                f"{val:,.0f}% of value" + (f" · was {was:,.0f}%" if was is not None else ""))
    # conversion
    if t["conv"] is None:
        return "—", "footfall not counted"
    return (f"{t['conv']:,.0f}%",
            f"{t['conv_bills']:,} bills / {t['ff']:,.0f} in, "
            f"{t['conv_days']} day{'s' if t['conv_days'] != 1 else ''}")


# Which way is good, per KPI: a single-piece bill going UP is not an improvement.
_KPI_SPEC = (("bills", "Bills written", +1),
             ("abv", "ABV · per bill", +1),
             ("abs", "Pieces per bill", +1),
             ("asp", "Price per piece", +1),
             ("single", "Single-piece bills", -1),
             ("conv", "Conversion", +1))


def _period_spine(text, font, w, h):
    """The DAY / MTD / YTD label as a boxed spine, reading bottom to top.

    Manav, 18 Aug: "for the day mtd ytd you are writing on the side, write it
    vertically, and box it so it looks neat." Sideways text costs a fraction of
    the width a horizontal label needs, which is what pays for the sixth KPI.
    """
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tw = int(scratch.textlength(text, font=font))
    th = font.getmetrics()[0] + font.getmetrics()[1]
    strip = Image.new("RGB", (tw + 6, th), CARD_BG)
    ImageDraw.Draw(strip).text((3, 0), text, font=font, fill=KPI_INK)
    strip = strip.rotate(90, expand=True)          # bottom-to-top, like a book

    box = Image.new("RGB", (w, h), CARD_BG)
    ImageDraw.Draw(box).rectangle([0, 0, w - 1, h - 1], outline=CARD_EDGE)
    box.paste(strip, ((w - strip.width) // 2, (h - strip.height) // 2))
    ImageDraw.Draw(box).rectangle([0, 0, w - 1, h - 1], outline=CARD_EDGE)
    return box


def _kpi_grid(kpis, lines, width):
    """Six KPIs across, one row per period, then the coaching lines."""
    lab_f, _ = PP._ft(20)
    _, val_b = PP._ft(34)
    sub_f, _ = PP._ft(18)
    per_f, per_b = PP._ft(22)
    head_f, head_b = PP._ft(24)
    body_f, _ = PP._ft(25)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    per_w = 52                                   # the DAY / MTD / YTD spine
    n = len(_KPI_SPEC)
    cw = (width - per_w - CARD_GAP * n) // n
    lh = lab_f.getmetrics()[0] + lab_f.getmetrics()[1]
    vh = val_b.getmetrics()[0] + val_b.getmetrics()[1]
    sh = sub_f.getmetrics()[0] + sub_f.getmetrics()[1]
    row_h = CARD_PAD_Y * 2 + lh + vh + sh + 8

    bh = body_f.getmetrics()[0] + body_f.getmetrics()[1]
    gutter = int(max(scratch.textlength(h, font=head_b) for h, _ in lines) + 28)
    wrapped = []
    for head, body in lines:
        words, cur = body.split(), ""
        avail = width - CARD_PAD_X * 2 - gutter
        for w in words:
            trial = (cur + " " + w).strip()
            if scratch.textlength(trial, font=body_f) <= avail:
                cur = trial
            else:
                wrapped.append((head, cur)); head, cur = "", w
        wrapped.append((head, cur))
    text_h = len(wrapped) * (bh + 6) + CARD_PAD_Y * 2

    H = len(PERIODS) * (row_h + CARD_GAP) + 14 + text_h
    img = Image.new("RGB", (width, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    y = 0
    for kind in PERIODS:
        k = kpis[kind]
        t, l = k["ty"], k["ly"]
        img.paste(_period_spine(kind, per_b, per_w - CARD_GAP, row_h), (0, y))
        for i, (which, label, good) in enumerate(_KPI_SPEC):
            x = per_w + i * (cw + CARD_GAP)
            d.rectangle([x, y, x + cw - 1, y + row_h - 1],
                        fill=CARD_BG, outline=CARD_EDGE)
            head, sub = _fmt_kpi(which, t, l)
            # Colour says better or worse than last year, in the KPI's own
            # direction — more single-piece bills is not an improvement.
            cur_v, ly_v = _kpi_pair(which, t, l)
            ink = KPI_INK
            if cur_v is not None and ly_v is not None and ly_v:
                ink = KPI_GOOD if (cur_v - ly_v) * good >= 0 else KPI_BAD
            d.text((x + CARD_PAD_X, y + CARD_PAD_Y), label, font=lab_f,
                   fill=SUB_INK)
            d.text((x + CARD_PAD_X, y + CARD_PAD_Y + lh + 2), head,
                   font=val_b, fill=ink)
            d.text((x + CARD_PAD_X, y + CARD_PAD_Y + lh + vh + 6), sub,
                   font=sub_f, fill=SUB_INK)
        y += row_h + CARD_GAP

    y += 14 - CARD_GAP
    d.rectangle([0, y, width - 1, y + text_h - 1], fill=CARD_BG,
                outline=CARD_EDGE)
    y += CARD_PAD_Y
    for head, body in wrapped:
        if head:
            d.text((CARD_PAD_X, y), head, font=head_b, fill=KPI_INK)
        d.text((CARD_PAD_X + gutter, y), body, font=body_f, fill=KPI_INK)
        y += bh + 6
    return img


def _kpi_pair(which, t, l):
    if which == "bills":
        return t["bills"], l["bills"]
    if which == "abv":
        return t["abv"], l["abv"]
    if which == "abs":
        return t["abs"], l["abs"]
    if which == "asp":
        return t["asp"], l["asp"]
    if which == "single":
        return (t["single"] / t["bills"] if t["bills"] else None,
                l["single"] / l["bills"] if l["bills"] else None)
    return t["conv"], l["conv"]


def _single_bill_card(sb):
    """Single-bill share, with LAST YEAR in the label and the colour inverted.

    Falling is good here. Reusing the growth colour would paint an improving
    store red at the exact moment its managers had fixed the thing the coaching
    notes told them to fix.
    """
    ty, ly = sb.get("ty"), sb.get("ly")
    if ty is None:
        return ("Single-piece bills", "—")
    # Same precision on both, or a 45.4 shown as "45" beside a 45.6 reads as a
    # bigger move than it is.
    label = ("Single-piece bills" if ly is None
             else f"Single-piece bills (LY {ly * 100:,.1f}%)")
    ink = None
    if ly is not None:
        ink = PP.GREEN if ty < ly else (PP.NEG_INK if ty > ly else None)
    return (label, f"{ty * 100:,.1f}%", ink)


def _drivers_table(L, df, asof, kind, store, code=None, targets=None):
    """One period's drivers table, with the target block above it.

    ★ THE CARD STRIP NOW LEADS WITH THE TARGET (Manav, 21 Aug). A manager opens
    this to find out whether they are going to make the number, so the number
    comes first: what was asked, what has been taken, where that leaves them,
    and what it costs a day to close the gap. The three movement cards that used
    to be alone stay, on the second row — they explain the same period.
    """
    drv, types = L.degrowth_drivers(
        df, asof=asof, kind=kind, only_declining=False, stores_only=[store],
        products_under="every", top_products=6, level="division")
    if drv.empty:
        return None, None
    k = store_kpis(L, df, asof, kind, store)
    tp = target_progress(L, asof, kind, store, code,
                         achieved=k["ty"]["sale"], targets=targets)
    sb = single_bill_share(L, df, asof, kind, store)
    grow = (PP.GREEN if k["move"] > 0
            else (PP.NEG_INK if k["move"] < 0 else None))

    # ★ FIVE TO A LINE (Manav, 21 Aug), split by what each line is for: the ask
    # and where the store stands against it, then how the trading is going.
    tgt = target_cards(tp, kind)
    cards = [
        # target · achieved · achieved% · balance · per day required
        [tgt[0], tgt[1], tgt[2], tgt[4], tgt[5]],
        [tgt[3],                                   # avg day sales
         ("Movement", f"Rs {k['move'] / 1e5:,.2f} L", grow),
         (f"{kind} vs last year",
          f"{k['move'] / k['ly']['sale'] * 100:,.2f}%" if k["ly"]["sale"] else "—",
          grow),
         # Last year goes in the LABEL, not the value: "660 vs 473 LY" ran
         # through the right-hand edge of its card.
         (f"Bills (LY {k['ly']['bills']:,})" if k["ly"]["bills"] else "Bills",
          f"{k['ty']['bills']:,}",
          PP.GREEN if k["ty"]["bills"] > k["ly"]["bills"]
          else (PP.NEG_INK if k["ty"]["bills"] < k["ly"]["bills"] else None)),
         _single_bill_card(sb)],
    ]
    png = render(
        drv, title=f"{store} — {kind} performance drivers",
        subtitle=f"Where the movement comes from, by brand and product · "
                 f"as of {asof:%d %b %Y}",
        cards=cards,
        money=L.drivers_money(kind), pct=L.DRIVERS_PCT,
        sign=["Shortfall"] + L.DRIVERS_PCT, row_types=types)
    return Image.open(io.BytesIO(png)), k


def _panel_heading(width, asof):
    """The one line that says what the strip below it is, and what it reads."""
    f_b = PP._ft(26)[1]
    sub = PP._ft(19)[0]
    h1 = f_b.getmetrics()[0] + f_b.getmetrics()[1]
    h2 = sub.getmetrics()[0] + sub.getmetrics()[1]
    img = Image.new("RGB", (width, h1 + h2 + 10), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((0, 0), "What to work on", font=f_b, fill=KPI_INK)
    d.text((0, h1 + 6),
           f"The same six measures on the day, the month and the year · "
           f"the notes below read the MONTH, which is the one still in play",
           font=sub, fill=SUB_INK)
    return img


_TARGETS_CACHE = {}


def _targets_for(asof):
    """The month's targets, fetched once per run rather than once per image."""
    key = pd.Timestamp(asof).strftime("%Y-%m")
    if key not in _TARGETS_CACHE:
        try:
            import targets as TG
            _TARGETS_CACHE[key] = TG.for_month(asof)
        except Exception:
            _TARGETS_CACHE[key] = {}
    return _TARGETS_CACHE[key]


def drivers_store_all(L, df, asof, store, code=None, pf=None, ff=None):
    """★ ONE DOCUMENT PER STORE: the month, then the year, then the KPIs.

    Manav, 18 Aug: "you see how there are 2 reports, one is ytd and one is mtd,
    we want to consolidate it, so its a consolidated doc that tells the manager
    the mtd, ytd and then the kpis to be worked out."

    So a manager opens ONE picture, not two. The two drivers tables are drawn
    exactly as before — neither is edited — and the KPI strip, which always
    covered DAY / MTD / YTD, now appears ONCE at the foot instead of being
    repeated identically under each table.

    The coaching notes read the MONTH. The year to date is history a manager
    cannot go back and sell; the month is the one still open.
    """
    if ff is None:
        ff = footfall_map(pf) if pf is not None else {}
    # Loaded once and handed to both periods: the morning set builds one of
    # these per store, and re-fetching the targets tab per image would be 22
    # identical downloads.
    targets = _targets_for(asof)
    mtd, k_m = _drivers_table(L, df, asof, "MTD", store, code, targets)
    ytd, _ = _drivers_table(L, df, asof, "YTD", store, code, targets)
    if mtd is None and ytd is None:
        return None
    tables = [t for t in (mtd, ytd) if t is not None]

    kpis = period_kpis(L, df, asof, store, ff, code)
    base = k_m if k_m is not None else store_kpis(L, df, asof, "YTD", store)
    lines = coaching_lines(base, attach_rate(L, df, asof, "MTD", store), "MTD")

    W = max(t.width for t in tables)
    head = _panel_heading(W - PAD * 2, asof)
    panel = _kpi_grid(kpis, lines, W - PAD * 2)
    H = (sum(t.height for t in tables) + PAD * len(tables)
         + head.height + 10 + panel.height + PAD)
    out = Image.new("RGB", (W, H), (255, 255, 255))
    y = 0
    for t in tables:
        out.paste(t, (0, y))
        y += t.height + PAD
    out.paste(head, (PAD, y)); y += head.height + 10
    out.paste(panel, (PAD, y))

    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    tag = f"{code}_" if code is not None else ""
    return f"{asof:%Y-%m-%d}_{tag}{_slug(store)}_drivers.png", buf.getvalue()


def drivers_store_coached_v2(L, df, asof, kind, store, code=None, pf=None,
                             ff=None):
    """The drivers table with the six-KPI, three-period strip beneath it.

    Nothing above the strip changes — Manav, 18 Aug: "dont change anything in
    the blocks above the kpi, those are perfect."
    """
    drv, types = L.degrowth_drivers(
        df, asof=asof, kind=kind, only_declining=False, stores_only=[store],
        products_under="every", top_products=6, level="division")
    if drv.empty:
        return None
    if ff is None:
        ff = footfall_map(pf) if pf is not None else {}
    kpis = period_kpis(L, df, asof, store, ff, code)
    k = store_kpis(L, df, asof, kind, store)
    lines = coaching_lines(k, attach_rate(L, df, asof, kind, store), kind)

    table_png = render(
        drv, title=f"{store} — {kind} performance drivers",
        subtitle=f"Where the movement comes from, by brand and product · "
                 f"as of {asof:%d %b %Y}",
        cards=[("Movement", f"Rs {k['move'] / 1e5:,.2f} L"),
               (f"{kind} vs last year",
                f"{k['move'] / k['ly']['sale'] * 100:,.2f}%"
                if k["ly"]["sale"] else "—"),
               ("Bills", f"{k['ty']['bills']:,}")],
        money=L.drivers_money(kind), pct=L.DRIVERS_PCT,
        sign=["Shortfall"] + L.DRIVERS_PCT, row_types=types)

    top = Image.open(io.BytesIO(table_png))
    panel = _kpi_grid(kpis, lines, top.width - PAD * 2)
    out = Image.new("RGB", (top.width, top.height + panel.height + PAD),
                    (255, 255, 255))
    out.paste(top, (0, 0))
    out.paste(panel, (PAD, top.height))
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    tag = f"{code}_" if code is not None else ""
    return f"{asof:%Y-%m-%d}_{tag}{_slug(store)}_drivers_{kind}.png", buf.getvalue()


# --------------------------------------------------------------------------- #
# Which panel the morning set uses. Manav, 18 Aug: "we might be reverting back
# to a previous version or change things around so plan for that."
#   "one"  ★ ONE document per store: MTD table, YTD table, KPIs once at the foot
#   "v2"   six KPIs across DAY / MTD / YTD under EACH period's table (two files)
#   "v1"   three KPIs for the reported period, then the coaching lines
#   "none" the table alone, exactly as it shipped on 9 August
# Changing this one word changes every image the ZIP builds.
PANEL = "one"


def is_consolidated() -> bool:
    """True when one call covers every period, so a caller must not loop.

    The morning set loops `for kind in ("MTD", "YTD")`. Under "one" that loop
    would build the same document twice, so the caller asks this first.
    """
    return PANEL == "one"


def drivers(L, df, asof, kind, store, code=None, pf=None, ff=None):
    """The morning image for one store — whichever panel `PANEL` selects.

    Under "one", `kind` is ignored: the document carries both periods.
    """
    if PANEL == "one":
        return drivers_store_all(L, df, asof, store, code, pf=pf, ff=ff)
    if PANEL == "v2":
        return drivers_store_coached_v2(L, df, asof, kind, store, code,
                                        pf=pf, ff=ff)
    if PANEL == "v1":
        return drivers_store_coached(L, df, asof, kind, store, code)
    return drivers_store(L, df, asof, kind, store, code)
