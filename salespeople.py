"""Who sold what, per store — keyed on the salesperson ID, never the name.

★ THE KEY IS THE ID (Manav, 1 Sep). Six people in this feed are typed two ways
— `IRFAN BASHA` and `N IRFAN ALI`, `NAFEESA BANU` and `NAFEESA MARKED NA BANU`,
`SUVAJIT DAS` with a trailing space — and each pair carries ONE id. Keyed on
name, Grand Kamraj Road's best seller appears twice, at Rs 42.4 L and Rs 15.1 L,
and ranks below people he outsold. On a sheet a manager uses to judge their
team, that is the error that gets spotted once and discredits everything else
on the page.

    251 names collapse to 245 ids.

★ THE DISPLAY NAME IS THE ONE MOST USED. Merging on id still leaves a choice of
spelling; the most-frequent one is what the store recognises, and it is decided
by the data rather than by a list somebody has to maintain.

★ `(PROVISIONAL)` IS NOT A PERSON and carries no id at all — it is the night
fill, a day's takings arriving before the bills do. Keyed on id it would simply
vanish, and the rows would stop adding up to the store's day. It is kept, named,
and shown under the people as its own line, so the total still ties.

⚠ ONE NAME GENUINELY SPLITS. `TABASSUM .` holds two ids, 23SVFL0149 (a single
Rs 3,499 bill) and 23SVFL0724 (Rs 20.8 L). Two people, or one whose id was
re-issued — the feed cannot say, so both are shown and flagged rather than
silently merged. That is a question for whoever runs the POS.
"""
from __future__ import annotations

import io

import pandas as pd

COL_ID = "SALESPERSON_NO"
# no sale in this many days -> off the main table, into the block at the foot
ABSENT_DAYS = 30

# ★ THE VISUAL LAYER ON THE DETAILED SHEET (Manav, 6 Sep: *"highlight the top
# sellers, or the salesguy whose abs abv etc is the highest or lowest"*). Row
# tint for the podium, cell ink for the extremes of each habit. Green and red
# are the dashboard's own; nothing is coloured where a direction is ambiguous.
TOP_N = 3
_GOOD = (31, 107, 74)
_BAD = (163, 22, 31)

# ★ THREE PERIOD BLOCKS (Manav, 9 Sep). Fifteen number columns in one flat run
# is where an eye loses which period it is reading; a wash behind each block
# means the boundary never has to be found by counting headers. Kept pale — the
# figures are the content, the tint is only the grouping.
_BAND_DAY = (238, 245, 251)      # blue
_BAND_MTD = (238, 248, 241)      # green
_BAND_YTD = (252, 247, 236)      # amber
# ★ AND TWO ROW STATES. Gold for anyone holding a star, so the name agrees with
# the mark beside it; RED for anyone whose year is zero or negative (Manav,
# 9 Sep) — the whole line, name included, so the row is findable without
# reading a column.
_INK_STAR = (150, 105, 0)
_INK_DEAD = (196, 0, 0)


def _row_palette():
    import portfolio_pdf as PP
    bg = dict(PP._ROW_BG)
    bg["top"] = (PP.HDR_BG, True)       # podium: the header's own pale blue
    return bg
PROVISIONAL = "(PROVISIONAL)"


def _clean_name(s: str) -> str:
    """Trim the punctuation the POS leaves behind — `RENU .`, `MANSOOR -`."""
    return " ".join(str(s).replace(".", " ").replace("-", " ").split()).title() or "—"


def store_table(L, df, asof, store):
    """(rows, row_types, meta) for one store — Day, MTD and YTD, four each.

    ★ THE SAME FUNCTION THE DASHBOARD TAB USES. `loader.salesperson_kpis` does
    the keying, the night-fill exclusion and the last-settled-day rule; this
    only slices to one store and shapes it for the page. A report and a screen
    computing the same figure two ways is how they end up disagreeing.
    """
    asof = pd.Timestamp(asof)
    d = df[df[L.COL_STORE_LABEL] == store]
    k = L.salesperson_kpis(d, asof=asof)
    if k.empty:
        return [], [], {"team": 0, "day": None, "excluded": 0.0}

    # when each person last sold — a zero row is a question, a date is an answer
    sid = "SALESPERSON_NO"
    sold = d[(d[L.COL_AMOUNT] > 0) & d[sid].notna()]
    last = sold.groupby(sid)["date"].max()
    by_id = {str(i): i for i in last.index}

    rows, types = [], []
    for n, (_, r) in enumerate(k.iterrows(), start=1):
        ld = last.get(by_id.get(str(r["ID"]), r["ID"]))
        row = {
            "rank": n, "who": _clean_name(r["Salesperson"]), "id": str(r["ID"]),
            "share": r.get("m_share", 0.0), "days": r.get("m_days", 0.0),
            "perday": r.get("m_perday", float("nan")),
            "move": r.get("m_move", float("nan")),
            "first": r.get("first_sold"),
            "quiet": (float("nan") if pd.isna(ld)
                      else float((asof - pd.Timestamp(ld)).days)),
            "tenure": r.get("tenure_days"),
            "censored": bool(r.get("tenure_censored", False)),
            "last": None if pd.isna(ld) else ld,
        }
        for t in ("d", "m", "q", "y"):
            for msr in ("sales", "units", "abv", "abs", "single", "bills"):
                row[f"{t}_{msr}"] = r.get(f"{t}_{msr}", 0.0)
        rows.append(row)
        types.append("person")

    tot = {"rank": None, "who": "TOTAL", "id": "", "last": None,
           "share": 100.0, "days": float("nan"), "perday": float("nan"),
           "move": float("nan"), "first": None, "tenure": float("nan"),
           "censored": False, "quiet": float("nan"), "flag": ""}
    # ★ THE STORE'S DISTINCT BILLS, NOT THE SUM OF EACH PERSON'S — a bill with
    # two salespeople on it is one bill for the store. See `salesperson_kpis`.
    _sb = k.attrs.get("store_bills") or {}
    for t in ("d", "m", "q", "y"):
        b = float(_sb.get(t) or k[f"{t}_bills"].sum())
        tot[f"{t}_sales"] = float(k[f"{t}_sales"].sum())
        tot[f"{t}_abv"] = tot[f"{t}_sales"] / b if b else 0.0
        tot[f"{t}_abs"] = float((k[f"{t}_abs"] * k[f"{t}_bills"]).sum()) / b if b else 0.0
        tot[f"{t}_single"] = float((k[f"{t}_single"] * k[f"{t}_bills"]).sum()) / b if b else 0.0
    rows.append(tot)
    types.append("subtotal")

    # ----------------------------------------------------------------- #
    #  Flags — the reason a row is worth looking at, in two words          #
    # ----------------------------------------------------------------- #
    # ★★ HABITS ARE JUDGED ON THE QUARTER, EFFORT ON THE DAY AND THE MONTH.
    # This is the correction that mattered most (6 Sep). ABV, ABS and
    # single-bill are RATIOS, and at Jayanagar on the 6th only ONE of 27 people
    # had 20 bills this month — the other 26 carried ratios built on a handful
    # of sales. Over the quarter 13 of 27 clear it. So a habit flag may only
    # fire off the quarter, and only when that person has the bills to support
    # it; the month is for what they DID, not for how they sell.
    MIN_BILLS = 20
    people_rows = rows[:-1]
    ok = [r for r in people_rows if float(r["q_bills"]) >= MIN_BILLS]
    # ★ A RANK MOVE IS ONLY NEWS RELATIVE TO THE TEAM'S SIZE. Five places in a
    # team of five is the whole board; five places in Grand Kamraj Road's
    # thirty-seven is ordinary weekly churn — at a flat ±5 that sheet flagged
    # 23 of 37 people, which is not a shortlist, it is the list. A fifth of the
    # team, floored at three.
    _live = [r for r in people_rows
             if pd.isna(r.get("quiet")) or r["quiet"] < 30]
    MOVE_MIN = max(3, round(0.2 * len(_live)))
    st_single = (sum(r["q_single"] * r["q_bills"] for r in ok)
                 / sum(r["q_bills"] for r in ok)) if ok else None
    st_abs = (sum(r["q_abs"] * r["q_bills"] for r in ok)
              / sum(r["q_bills"] for r in ok)) if ok else None

    for r in people_rows:
        q = r.get("quiet")
        tn, cens = r.get("tenure"), r.get("censored")
        mv = r.get("move")
        enough = float(r["q_bills"]) >= MIN_BILLS
        # ★ ONE FLAG PER ROW, IN THIS ORDER. A column carrying three reasons is
        # a column nobody reads. The order is what a manager acts on first.
        # ★ NOTHING THAT ANOTHER COLUMN ALREADY SAYS. A `NEW 5 d` flag fired on
        # six of this team and duplicated SELLING FOR two columns to its left —
        # a flag column that repeats its neighbour is a flag column nobody
        # scans. And a 30-day absentee gets no flag because the block at the
        # foot IS the flag. What is left is what a manager cannot see anywhere
        # else on the page.
        f = ""
        if q is not None and not pd.isna(q) and 8 <= q < 30:
            f = f"QUIET {int(q)}d"
        elif mv is not None and not pd.isna(mv) and mv <= -MOVE_MIN:
            f = f"DOWN {abs(int(mv))}"
        # ★ SINGLE-PIECE ONLY, NOT BASKET AS WELL. Across five stores the two
        # correlate -0.67 to -0.96 — they are the same fact said twice, and
        # flagging both would count one habit as two.
        #
        # ★★ AND THE OBVIOUS OBJECTION WAS TESTED AND FAILS. "A high single
        # rate just means they sell one expensive sherwani" — if that were so,
        # single% would rise with average bill value. It does the OPPOSITE at
        # every store measured (-0.07 to -0.65): the people letting customers
        # leave with one piece are taking LESS per bill, not more. So it is a
        # habit and it is coachable. See [[feedback-check-the-confound]].
        elif (enough and st_single is not None
              and r["q_single"] >= st_single + 8):
            f = f"SINGLE {r['q_single']:.0f}%"
        # ★ NO "UP" FLAG. The three cards at the top of the page are the
        # recognition; a column a manager scans for problems should not have
        # good news mixed into it. Dropping it took Grand Kamraj Road from 22
        # flags on a 37-person floor to 16, all of them things to act on.
        r["flag"] = f

    dup = [r["who"] for r in rows[:-1]
           if sum(1 for x in rows[:-1] if x["who"] == r["who"]) > 1]

    # ★ THE SHAPE OF THE TEAM, not another ranking. How much of a store rests
    # on how few people is a management question the ranked list implies but
    # never states — and the number that matters is not who is top, it is how
    # far the store would fall if the top three left.
    people = rows[:-1]
    fresh = sum(1 for r in people
                if r.get("tenure") is not None and not pd.isna(r.get("tenure"))
                and r["tenure"] < 90 and not r.get("censored"))
    msorted = sorted((float(r["m_sales"]) for r in people), reverse=True)
    mtot = sum(msorted)
    sellers = [v for v in msorted if v > 0]
    shape = {
        "top3": (sum(msorted[:3]) / mtot * 100) if mtot else None,
        "idle": sum(1 for v in msorted if v <= 0),
        "median": (sellers[len(sellers) // 2] if sellers else None),
        "sellers": len(sellers),
        "fresh": fresh,
    }
    return rows, types, {"team": len(people), "day": k.attrs.get("day"),
                         "store_single": st_single, "store_abs": st_abs,
                         "move_min": MOVE_MIN,
                         "min_bills": MIN_BILLS,
                         "excluded": k.attrs.get("excluded_provisional", 0.0),
                         "quarter": k.attrs.get("quarter"),
                         "prev_month": k.attrs.get("prev_month"),
                         "shape": shape, "duplicates": sorted(set(dup))}


# --------------------------------------------------------------------------- #
#  One A4 page per store                                                       #
# --------------------------------------------------------------------------- #
# ★ THE SAME PAGE FURNITURE AS THE DRIVER SHEET, deliberately: same margins,
# same palette, same fitted type, same one-page contract. A manager should not
# have to learn a second document.
#
# ★ RANKED BY THE MONTH, because that is the question being asked — who is
# doing what NOW. The year sits beside it so a good month by someone usually
# quiet, or a quiet month by someone usually good, is visible in one glance
# rather than needing a second report.
#
# ★ EVERY PERSON, NOT A TOP FIVE. Teams run from three to thirty-nine here, so
# a top-n would be most of one team and a seventh of another — and the person a
# manager most needs to see is rarely in the top five.

# ★ EVERY COLUMN NAMED ONCE, AND EVERY NUMERIC ONE DECLARED. Alignment and
# formatting come entirely from these lists — a column missing from them prints
# as a raw float, left-aligned, which is how `8117.922077922078` reached the
# first draft of this page. Several columns share a measure across periods, so
# the period is in the name rather than repeated as a header group.
#
# ★★ TWO TABLES, NOT ONE WIDER ONE. Four periods x four measures is sixteen
# number columns before a single name, and at that width the page either
# shrinks past reading size or drops what a manager came for. So page one
# answers the question actually being asked — who is selling THIS MONTH, and is
# that a lot for the days they worked — and page two carries every measure on
# every period for anyone who wants to check. Nothing was removed to make room;
# the day, month, quarter and year all still state all four measures.
# ★★ THE DAY AND THE MONTH SAY WHAT THEY DID; THE QUARTER SAYS HOW THEY SELL.
# This split is the whole restructure (Manav, 6 Sep: *"think like a store
# manager, what he looks for every day"*). ABV, ABS and single-bill are RATIOS,
# and on the 6th only ONE of Jayanagar's 27 people had 20 bills this month —
# the other 26 carried ratios built on a handful of sales, printed in the most
# prominent columns on the page. Over the quarter, 13 of 27 clear 20 bills. So
# page one carries effort (sales, days, per-day, movement) and page two carries
# habits, on the quarter, where the sample can bear them.
_MONEY = ["DAY SALES", "MTD SALES", "PER DAY"]
_PCT = ["SHARE"]
_NUM = []
_WHOLE = ["#", "DAYS"]
_SIGN = ["DAY SALES", "MTD SALES", "SHARE", "PER DAY", "MOVE"]
_ORDER = ["#", "SALESPERSON", "FLAG", "SELLING FOR", "DAY SALES",
          "MTD SALES", "SHARE", "DAYS", "PER DAY", "MOVE", "LAST SOLD"]

# ★★ THE ONE-PAGE DETAIL TABLE (Manav, 7 Sep): *"one page with an extensive
# table which covers performance for all employees over day, mtd and ytd."*
# Every person, every period, one sheet — the reference half of the pair, where
# the pointer sheet is the five-minute half.
_PERIODS = (("d", "DAY"), ("m", "MTD"), ("y", "YTD"))
_MEASURES = (("sales", "SALES"), ("units", "UNITS"), ("abv", "ABV"),
             ("abs", "ABS"), ("single", "SINGLE"))
_D_MONEY = [f"{t} {m}" for _, t in _PERIODS for k, m in _MEASURES
            if k in ("sales", "abv")]
_D_PCT = [f"{t} SINGLE" for _, t in _PERIODS]
_D_NUM = [f"{t} ABS" for _, t in _PERIODS]
_D_WHOLE = ["#"] + [f"{t} UNITS" for _, t in _PERIODS]
_D_SIGN = _D_MONEY + _D_PCT
_D_ORDER = (["TOP", "#", "SALESPERSON", "SELLING FOR"]
            + [f"{t} {m}" for _, t in _PERIODS for _, m in _MEASURES])

# the metrics a star can be won on, and which way is best
# ★★ A RATIO STAR NEEDS BILLS BEHIND IT; A TOTAL DOES NOT. Sales and units are
# sums — the biggest is the biggest however few bills made it. ABV, ABS and
# single-piece are RATIOS, and on the first draft "biggest basket this month"
# and "lowest single-piece this month" both went to a Saddam Hussain who had
# written ONE bill: a 5.33-line sale and a 0% single rate, each true and each
# meaningless. Ratio stars therefore carry a floor of bills in that same
# window. (Fourth time this project has been bitten by a ratio on a tiny
# denominator — see [[feedback-aggregate-ratios-in-pairs]].)
STAR_MIN_BILLS = 10

#            column        label                              higher  bills-in
_STAR_ON = (("d_sales", "top day sales", True, None),
            ("m_sales", "top month sales", True, None),
            ("y_sales", "top year sales", True, None),
            ("m_units", "most pieces this month", True, None),
            ("y_units", "most pieces this year", True, None),
            ("m_abv", "biggest bill this month", True, "m_bills"),
            ("m_abs", "biggest basket this month", True, "m_bills"),
            ("m_single", "lowest single-piece this month", False, "m_bills"))

# page three — every measure, every period
_G_MONEY = [f"{t} {m}" for t in ("DAY", "MTD", "QTD", "YTD")
            for m in ("SALES", "ABV")]
_G_PCT = [f"{t} SINGLE" for t in ("DAY", "MTD", "QTD", "YTD")]
_G_NUM = [f"{t} ABS" for t in ("DAY", "MTD", "QTD", "YTD")]
_G_WHOLE = []
_G_SIGN = _G_MONEY + _G_PCT
_G_ORDER = ["SALESPERSON", "FIRST SOLD"] + [f"{t} {m}"
                                            for t in ("DAY", "MTD", "QTD", "YTD")
                                            for m in ("SALES", "ABV", "ABS",
                                                      "SINGLE")]


def _move(v):
    """A rank change, read as a person reads it.

    ★ BLANK, NOT ZERO, WHEN THERE IS NOTHING TO SAY. Somebody who did not sell
    in the same days last month has no rank to have moved from, and printing
    `0` would claim they held their place.
    """
    if v is None or pd.isna(v):
        return "—"
    v = int(v)
    return "—" if v == 0 else (f"+{v}" if v > 0 else str(v))


def _selling_for(days, censored):
    """How long this person has been selling, as a person would say it.

    ★ AND IT NEVER OVERSTATES WHAT THE DATA KNOWS. A `+` means the first sale
    we can see is the first day their store has any data at all — the person
    may have been on the floor for years before the feed begins. Printing a
    bare "17 mo" there would be a claim the data cannot support.
    """
    if days is None or pd.isna(days):
        return "—"
    d = int(days)
    if d < 14:
        out = f"{d} d"
    elif d < 90:
        out = f"{d // 7} wk"
    else:
        out = f"{d // 30} mo"
    return out + (" +" if censored else "")


def _frame(rows):
    """Page one — what the team DID. Effort, not habits."""
    out = []
    for r in rows:
        out.append({
            "#": (r.get("rank") if r.get("rank") else float("nan")),
            "SALESPERSON": r["who"],
            "FLAG": ("" if r["who"] == "TOTAL" else r.get("flag", "")),
            "SELLING FOR": ("" if r["who"] == "TOTAL"
                            else _selling_for(r.get("tenure"),
                                              r.get("censored"))),
            "DAY SALES": r["d_sales"],
            "MTD SALES": r["m_sales"],
            "SHARE": r.get("share", 0.0),
            "DAYS": r.get("days", float("nan")),
            "PER DAY": r.get("perday", float("nan")),
            "MOVE": _move(r.get("move")),
            "LAST SOLD": ("" if r.get("last") is None or pd.isna(r.get("last"))
                          else f"{pd.Timestamp(r['last']):%d %b}"),
        })
    return pd.DataFrame(out)[_ORDER]


def _habit_frame(rows, store_single):
    """Page two — HOW they sell, on the quarter.

    ★ ONLY PEOPLE WITH THE BILLS TO SUPPORT A RATIO. Everyone else is named
    underneath as unjudgeable rather than given a number that is arithmetic on
    four sales. `VS STORE` is the single-piece gap in points, because a rate
    means nothing without the floor it sits on.
    """
    out = []
    for r in rows:
        out.append({
            "SALESPERSON": r["who"],
            "BILLS": r.get("q_bills", 0.0),
            "QTD SALES": r.get("q_sales", 0.0),
            "ABV": r.get("q_abv", 0.0),
            "BASKET": r.get("q_abs", 0.0),
            "SINGLE %": r.get("q_single", 0.0),
            "VS STORE": (float("nan") if store_single is None
                         else r.get("q_single", 0.0) - store_single),
        })
    return pd.DataFrame(out)[_H_ORDER]


def _absent_frame(rows):
    """The people who have not sold in a month — off the main table, not gone."""
    out = []
    for r in rows:
        out.append({
            "SALESPERSON": r["who"],
            "SELLING FOR": _selling_for(r.get("tenure"), r.get("censored")),
            "LAST SOLD": ("never" if r.get("last") is None
                          or pd.isna(r.get("last"))
                          else f"{pd.Timestamp(r['last']):%d %b %y}"),
            "DAYS QUIET": r.get("quiet", float("nan")),
            "YTD SALES": r.get("y_sales", 0.0),
        })
    return pd.DataFrame(out)[_A_ORDER]


def _grid_frame(rows):
    out = []
    for r in rows:
        d = {"SALESPERSON": r["who"],
             "FIRST SOLD": ("" if r.get("first") is None
                            or pd.isna(r.get("first")) else
                            f"{pd.Timestamp(r['first']):%d %b %y}"
                            + (" +" if r.get("censored") else ""))}
        for t, tag in (("d", "DAY"), ("m", "MTD"), ("q", "QTD"), ("y", "YTD")):
            d[f"{tag} SALES"] = r[f"{t}_sales"]
            d[f"{tag} ABV"] = r[f"{t}_abv"]
            d[f"{tag} ABS"] = r[f"{t}_abs"]
            d[f"{tag} SINGLE"] = r[f"{t}_single"]
        out.append(d)
    return pd.DataFrame(out)[_G_ORDER]


# --------------------------------------------------------------------------- #
#  The three cards                                                             #
# --------------------------------------------------------------------------- #
def _top_cards(rows, meta, width):
    """Top of the day, the month and the quarter — Manav, 4 Sep 2026.

    ★ A NAME IS THE ANSWER, SO THE NAME IS THE BIG TYPE. The ranked table below
    already carries the money; what a card adds is that somebody does not have
    to read twenty-seven rows to learn who is winning today.

    ★ EACH CARD CARRIES A SECOND FIGURE THAT IS NOT MORE MONEY. Sales alone
    would say the same thing three times in three sizes. The day's card gives
    what that person got per bill, the month's their share of the store, the
    quarter's the days they have actually sold on — three different reasons a
    person can be top, and they are not the same reason.

    ★ NOBODY TOPS AN EMPTY PERIOD. On a day with no bills yet the card says so
    rather than crowning whoever is first in an all-zero list.
    """
    import snapshots as SN
    import portfolio_pdf as PP
    from PIL import Image, ImageDraw

    people = [r for r in rows if r["who"] != "TOTAL"]
    _qtot = sum(float(r["q_sales"]) for r in people)
    day = meta.get("day")
    q = meta.get("quarter")
    specs = [
        ("d", f"Top of the day  ·  {day:%d %b}" if day is not None else "Top of the day",
         lambda r: (f"Rs {r['d_abv']:,.0f} a bill" if r["d_abv"] else "")),
        ("m", "Top of the month",
         lambda r: (f"{r['share']:.1f}% of the store's month" if r.get("share") else "")),
        # ★ THE QUARTER'S CARD DESCRIBES THE QUARTER. A first draft put "sold
        # on 1 day this month" under the quarter's top seller — a MONTH figure
        # under a QUARTER heading, which is the mismatched-window error this
        # dashboard keeps finding. Share of the quarter is the same idea as the
        # month card's, asked of the window it is actually sitting on.
        ("q", f"Top of the quarter  ·  {q[0]:%b} to {q[1]:%b}" if q else "Top of the quarter",
         lambda r: (f"{r['q_sales'] / _qtot * 100:.1f}% of the store's quarter"
                    if _qtot else "")),
    ]

    lab_f, _ = PP._ft(22)
    _, name_f = PP._ft(38)
    val_f, _ = PP._ft(26)
    sub_f, _ = PP._ft(21)
    lh, nh = SN._h(lab_f) if hasattr(SN, "_h") else lab_f.getmetrics()[0] + lab_f.getmetrics()[1], 0
    lh = lab_f.getmetrics()[0] + lab_f.getmetrics()[1]
    nh = name_f.getmetrics()[0] + name_f.getmetrics()[1]
    vh = val_f.getmetrics()[0] + val_f.getmetrics()[1]
    sh = sub_f.getmetrics()[0] + sub_f.getmetrics()[1]
    ch = SN.CARD_PAD_Y * 2 + lh + 6 + nh + 2 + vh + 2 + sh
    cw = (width - SN.CARD_GAP * (len(specs) - 1)) // len(specs)

    img = Image.new("RGB", (width, ch), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, (tag, label, subfn) in enumerate(specs):
        x = i * (cw + SN.CARD_GAP)
        d.rectangle([x, 0, x + cw - 1, ch - 1], fill=SN.CARD_BG,
                    outline=SN.CARD_EDGE, width=1)
        best = max(people, key=lambda r: float(r[f"{tag}_sales"]), default=None)
        if best is None or float(best[f"{tag}_sales"]) <= 0:
            name, val, sub = "—", "nothing sold yet", ""
        else:
            name = best["who"]
            val = f"Rs {float(best[f'{tag}_sales']):,.0f}"
            sub = subfn(best)
        px, py = SN.CARD_PAD_X, SN.CARD_PAD_Y
        d.text((x + px, py), label, font=lab_f, fill=SN.SUB_INK)
        d.text((x + px, py + lh + 6), name, font=name_f, fill=SN.TITLE_INK)
        d.text((x + px, py + lh + 6 + nh + 2), val, font=val_f, fill=SN.TITLE_INK)
        d.text((x + px, py + lh + 6 + nh + 2 + vh + 2), sub, font=sub_f,
               fill=SN.SUB_INK)
    return img


def _fit_table(disp, money, pct, num, content_w, usable, fixed, whole=(),
               sign=()):
    """Largest type that fits, then the most air that still fits.

    ★ THIS TABLE IS WIDTH-BOUND, NOT HEIGHT-BOUND, and that is the whole reason
    for the second loop. Fifteen columns cap the type long before the rows run
    out of page, so the first draft printed a full-width table down two thirds
    of an A4 and left the last third white. Type size cannot use that space —
    columns are sized by their own text, so a bigger font widens the table
    rather than filling the page (see `portfolio_pdf`'s note on the same
    trap). ROW PADDING can. So: find the largest type that fits the width,
    then open the rows up until the table reaches the bottom of the page.
    """
    import snapshots_a4 as A4
    import portfolio_pdf as PP
    best = None
    for pad in (14, 12, 10, 8, 7, 6, 5, 4, 3, 2):
        PP.PAD_Y = PP._px(pad)
        lo, hi, here = A4.FONT_MIN, A4.FONT_MAX, None
        while lo <= hi:
            mid = (lo + hi) // 2
            m = A4._measure(disp, money, pct, sign, mid, num=num, whole=whole)
            h = m["head_h"] + m["row_h"] * len(disp)
            if m["W"] <= content_w and fixed + h <= usable:
                here, lo = (mid, m), mid + 1
            else:
                hi = mid - 1
        if here and (best is None or here[0] > best[0]):
            best = (here[0], pad, here[1])
    if best is None:
        PP.PAD_Y = PP._px(2)
        return (A4.FONT_MIN, 2,
                A4._measure(disp, money, pct, sign, A4.FONT_MIN, num=num,
                            whole=whole))

    font_px, pad, m = best
    # ★ GROW THE ROWS, NOT THE TYPE. Capped so a three-person team does not
    # print as three bands an inch deep — past a point the air stops helping
    # and starts looking like a mistake.
    for cand in range(pad + 1, 41):
        PP.PAD_Y = PP._px(cand)
        mm = A4._measure(disp, money, pct, sign, font_px, num=num, whole=whole)
        if fixed + mm["head_h"] + mm["row_h"] * len(disp) > usable:
            break
        pad, m = cand, mm
    PP.PAD_Y = PP._px(pad)
    return (font_px, pad, m)


# --------------------------------------------------------------------------- #
#  ONE PAGE. Five minutes. (Manav, 6 Sep 2026)                                 #
# --------------------------------------------------------------------------- #
# *"too many tables, not visually appealing, difficult read. a manager gets
# like 5 mins a day. the entire report should be one page, no more, doesnt
# matter if its a big store or small one."*
#
# ★★ THAT LAST CLAUSE IS THE DESIGN CONSTRAINT, and it rules out a roster. A
# sixty-person floor cannot be listed on the same sheet as a five-person one,
# so this page stops trying to REPORT the team and starts POINTING at it: the
# few who are carrying the month, the few who need a word, the one habit worth
# saying on the floor, and the names that are no longer on it. Everything else
# lives in the Salespeople tab, which is where a manager goes when he has more
# than five minutes.
#
# ★ AND IT IS DRAWN, NOT TABULATED. Bars are read at a glance and a table is
# read a cell at a time; the whole complaint was that the sheet had to be
# worked through rather than seen.
BAR_N = 8                      # names on the bar chart, whatever the team size
WORD_N = 5                     # names in "worth a word"
HABIT_N = 3                    # names on the floor briefing line


def _band(width, title, sub=""):
    """A section heading with a rule under it."""
    import portfolio_pdf as PP
    from PIL import Image, ImageDraw
    _, tb = PP._ft(34)
    sf, _ = PP._ft(23)
    th, sh = _hh(tb), _hh(sf)
    h = th + (sh + 4 if sub else 0) + PP._px(14)
    img = Image.new("RGB", (width, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((0, 0), title, font=tb, fill=PP.INK)
    if sub:
        d.text((0, th + 2), sub, font=sf, fill=(90, 90, 90))
    y = h - PP._px(8)
    d.line([(0, y), (width, y)], fill=PP.GRID, width=2)
    return img


def _hh(f):
    a, b = f.getmetrics()
    return a + b


def _carry_bars(people, total_month, width):
    """Who is carrying the month, as bars."""
    import portfolio_pdf as PP
    from PIL import Image, ImageDraw
    rows = [r for r in people if float(r["m_sales"]) > 0][:BAR_N]
    if not rows:
        return None
    top = max(float(r["m_sales"]) for r in rows) or 1.0
    _, nb = PP._ft(32)
    _, vb = PP._ft(32)
    sf, _ = PP._ft(24)
    row_h = int(_hh(nb) * 2.05)
    name_w, val_w = int(width * 0.27), int(width * 0.15)
    bar_w = width - name_w - val_w - int(width * 0.20) - PP._px(20)
    img = Image.new("RGB", (width, row_h * len(rows)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, r in enumerate(rows):
        y = i * row_h
        cy = y + (row_h - _hh(nb)) // 2
        d.text((0, cy), r["who"], font=nb, fill=PP.INK)
        bx, bh = name_w, int(row_h * 0.50)
        by = y + (row_h - bh) // 2
        d.rectangle([bx, by, bx + bar_w, by + bh], fill=(241, 241, 241))
        w = int(bar_w * float(r["m_sales"]) / top)
        if w > 0:
            d.rectangle([bx, by, bx + w, by + bh], fill=PP.HDR_BG,
                        outline=PP.GRID)
        t = _lakh(float(r["m_sales"]))
        d.text((bx + bar_w + PP._px(14) + val_w - d.textlength(t, font=vb), cy),
               t, font=vb, fill=PP.INK)
        # what the bar cannot say: the share, and how new they are
        extra = f"{r.get('share', 0):.1f}% of the month"
        ten = _selling_for(r.get("tenure"), r.get("censored"))
        if r.get("tenure") is not None and not pd.isna(r.get("tenure")) \
                and r["tenure"] < 90 and not r.get("censored"):
            extra += f"  ·  {ten} in"
        d.text((bx + bar_w + PP._px(28) + val_w, cy + PP._px(3)), extra,
               font=sf, fill=(90, 90, 90))
    return img


def _lakh(v):
    """Rs 2.62 L — a manager reads lakhs, not eight digits."""
    if abs(v) >= 1e7:
        return f"Rs {v / 1e7:,.2f} Cr"
    if abs(v) >= 1e5:
        return f"Rs {v / 1e5:,.2f} L"
    return f"Rs {v:,.0f}"


def _lines(width, items, px=27, gap=8, ink=None):
    """A list of (bold left, plain right) lines."""
    import portfolio_pdf as PP
    from PIL import Image, ImageDraw
    if not items:
        return None
    rf, rb = PP._ft(px)
    lh = _hh(rb)
    left_w = int(width * 0.30)
    img = Image.new("RGB", (width, (lh + gap) * len(items)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, (a, b) in enumerate(items):
        y = i * (lh + gap)
        d.text((0, y), a, font=rb, fill=PP.INK)
        d.text((left_w, y), b, font=rf, fill=ink or (60, 60, 60))
    return img


def pointer_sheet(L, df, asof, store, code=None):
    """MANAGER TEAM POINTER — one store, ONE PAGE, cropped to its content.

    ★ THE FIVE-MINUTE REPORT (Manav, 6 Sep). Read before the doors open: who is
    carrying the month, who needs a word, the one habit to say on the floor,
    and who is no longer on it. It POINTS; it does not report. The detailed
    sheet below is the other half of the pair.
    """
    import snapshots_a4 as A4
    import portfolio_pdf as PP

    asof = pd.Timestamp(asof)
    rows, types, meta = store_table(L, df, asof, store)
    if len(rows) <= 1:
        return None
    people, total = rows[:-1], rows[-1]
    live = [r for r in people
            if pd.isna(r.get("quiet")) or r["quiet"] < ABSENT_DAYS]
    gone = sorted([r for r in people
                   if not pd.isna(r.get("quiet")) and r["quiet"] >= ABSENT_DAYS],
                  key=lambda r: r["quiet"])
    sh = meta.get("shape") or {}
    _day, _q, _pm = meta.get("day"), meta.get("quarter"), meta.get("prev_month")

    _keep = (A4.MARGIN, A4.CONTENT_W, PP.PAD_Y)
    A4.MARGIN = A4.PRINT_MARGIN
    A4.CONTENT_W = A4.PAGE_W - 2 * A4.MARGIN
    try:
        W = A4.CONTENT_W
        blocks = []

        blocks.append((A4._heading(
            W, f"{store} — the floor today",
            f"{len(live)} on the floor  ·  {len(gone)} not sold in a month  ·  "
            f"yesterday = {_day:%d %b}  ·  month to {asof:%d %b %Y}"
            if _day else f"as of {asof:%d %b %Y}"), 20))

        # ---- the month, in four figures ----------------------------------
        import snapshots as SN
        m_tot = float(total["m_sales"])
        d_tot = float(total["d_sales"])
        best_day = max(people, key=lambda r: float(r["d_sales"]), default=None)
        blocks.append((SN._cards_image([
            ("The month so far", _lakh(m_tot)),
            ("Yesterday", _lakh(d_tot)),
            ("Top of the month", (people[0]["who"] if people else "—")),
            ("Top yesterday", (best_day["who"]
                               if best_day and float(best_day["d_sales"]) > 0
                               else "—")),
        ], W, label_px=25, value_px=42), 22))

        # ---- who is carrying it ------------------------------------------
        _n = min(BAR_N, len([r for r in live if float(r["m_sales"]) > 0]))
        blocks.append((_band(
            W, "Who is carrying the month",
            (f"top {_n} of the {sh.get('sellers', 0)} who have sold  ·  "
             f"the top three wrote {sh['top3']:.0f}% of it"
             # ★ with three sellers the top three wrote 100% by definition
             if sh.get("top3") is not None and sh.get("sellers", 0) > 3
             else f"all {sh.get('sellers', 0)} who have sold")), 14))
        bars = _carry_bars(live, m_tot, W)
        if bars is not None:
            blocks.append((bars, 26))

        # ---- worth a word -------------------------------------------------
        flagged = [r for r in live if r.get("flag")][:WORD_N]
        if flagged:
            said = {"QUIET": "no sale in {n} days — still on the roster?",
                    "DOWN": "down {n} places against the same days last month",
                    "SINGLE": "{n}% of their bills leave with one piece"}
            items = []
            for r in flagged:
                k, n = r["flag"].split()[0], r["flag"].split()[-1]
                items.append((r["who"],
                              said.get(k, "{n}").format(n=n.rstrip("d%"))))
            blocks.append((_band(W, "Worth a word today"), 14))
            blocks.append((_lines(W, items), 24))

        # ---- the one habit to push ---------------------------------------
        # ★★ THE FLOOR BRIEFING NAMES PEOPLE WHO ARE ON THE FLOOR. Drawn from
        # the whole team it put Mansoor at 84% and Farzana Banu at 75% in front
        # of a manager at Grand Kamraj Road — both of whom appear in the "not
        # on the floor" block four lines below, one of them 141 days gone. Two
        # figures on one page describing different sets of people, which is the
        # error this dashboard keeps finding. See [[feedback-same-estate]].
        minb = meta.get("min_bills", 20)
        judged = sorted([r for r in live if float(r["q_bills"]) >= minb],
                        key=lambda r: -r["q_single"])
        # ★ ONLY PEOPLE ACTUALLY ABOVE THE STORE'S RATE. "The three furthest
        # above it" listed Sudeep N N at 41% against a 45% store — below it,
        # and named as an offender. If nobody is above, the section does not
        # appear, because there is nothing to push.
        above = ([r for r in judged
                  if r["q_single"] > meta["store_single"]][:HABIT_N]
                 if meta.get("store_single") is not None else [])
        if judged and above:
            worst = above
            blocks.append((_band(
                W, "Push this on the floor",
                f"measured over the quarter, where the bills are enough to "
                f"mean it — {len(judged)} of the {len(live)} on the floor "
                f"qualify"), 14))
            blocks.append((_lines(W, [(
                f"{meta['store_single']:.0f}% single-piece",
                "of this store's bills leave with one piece. "
                + ("The three furthest above it: " if len(worst) > 2
                   else "Above it: ") + " · ".join(
                    f"{r['who']} {r['q_single']:.0f}%" for r in worst))],
                px=27), 24))

        # ---- who is not here ----------------------------------------------
        if gone:
            blocks.append((_band(
                W, f"Not on the floor  ·  {len(gone)} of {len(people)}",
                f"no sale in {ABSENT_DAYS} days or more"), 14))
            blocks.append((A4._text_block(W, [(
                " · ".join(f"{r['who']} {int(r['quiet'])}d" for r in gone),
                A4._ft(25)[0], A4.SUB)]), 20))

        # ---- what the page cannot say -------------------------------------
        notes = []
        if meta.get("excluded"):
            notes.append(f"Rs {meta['excluded']:,.0f} of night-fill sale "
                         f"belongs to nobody yet — it arrives before the bills.")
        if meta["duplicates"]:
            notes.append(", ".join(meta["duplicates"])
                         + " appears under more than one salesperson id.")
        notes.append("Every figure is keyed on the salesperson id, not the "
                     "name. The full team, every measure and every period is "
                     "in the Salespeople tab.")
        blocks.append((A4._text_block(
            W, [(" ".join(notes), A4._ft(21)[0], A4.SUB)]), 0))

        sheet = A4._Sheet(store, asof, "", bounded=False, footer=True)
        for img, gap in blocks:
            if img is not None:
                sheet.put(img, gap=gap)
        sheet._footers()
        buf = io.BytesIO()
        sheet.pages[0].save(buf, "PDF", save_all=True,
                            append_images=sheet.pages[1:],
                            resolution=A4.PAGE_W * 72.0 / A4.PAGE_PT_W)
        out, npages = buf.getvalue(), len(sheet.pages)
    finally:
        A4.MARGIN, A4.CONTENT_W, PP.PAD_Y = _keep

    tag = f"{code}_" if code is not None else ""
    stem = (f"{asof:%Y-%m-%d}_{tag}"
            f"{__import__('snapshots')._slug(store)}_team_pointer")
    return (f"{stem}.pdf", out, 0, npages, meta["team"])


def _stars(people):
    """Who tops each metric -> {row id: [what they top]}.

    ★ A STAR IS EARNED ON ANY ONE MEASURE, not on an overall score. The point
    is that the best seller by money is often not the one moving the most
    pieces, or the one who never lets a customer leave with a single item — a
    manager wants all three names, and a composite score would hide two of
    them.

    ★ AND A ZERO NEVER WINS. On a quiet day, or a measure nobody scored on, the
    maximum is 0 and every idle person would tie for it. A metric with no
    positive value awards no star.
    """
    won = {}
    for key, label, best_high, bills_col in _STAR_ON:
        vals = [(float(r[key]), r) for r in people
                if r.get(key) is not None and not pd.isna(r[key])]
        if bills_col:                      # a ratio: needs a real denominator
            vals = [(v, r) for v, r in vals
                    if float(r.get(bills_col, 0)) >= STAR_MIN_BILLS]
        if best_high:
            # ★ AND A ZERO NEVER WINS. On a quiet day the maximum is 0 and
            # every idle person ties for it.
            vals = [(v, r) for v, r in vals if v > 0]
        if not vals:
            continue
        target = max(v for v, _ in vals) if best_high else min(v for v, _ in vals)
        for v, r in vals:
            if v == target:
                won.setdefault(id(r), []).append(label)
    return won


def _pills(width, items):
    """A row of rounded pills — label above, value below.

    ★ THE THINGS A MANAGER WOULD ASK FIRST, ANSWERED BEFORE THE TABLE. The
    table below can answer all of them, but only by being read; a pill is read
    by being glanced at.
    """
    import portfolio_pdf as PP
    from PIL import Image, ImageDraw
    if not items:
        return None
    lab, _ = PP._ft(22)
    _, val = PP._ft(30)
    lh, vh = _hh(lab), _hh(val)
    pad_x, pad_y, gap = PP._px(18), PP._px(12), PP._px(12)
    h = pad_y * 2 + lh + 2 + vh
    n = len(items)
    w = (width - gap * (n - 1)) // n
    img = Image.new("RGB", (width, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, (l, v) in enumerate(items):
        x = i * (w + gap)
        d.rounded_rectangle([x, 0, x + w - 1, h - 1], radius=PP._px(10),
                            fill=PP.HDR_BG, outline=PP.GRID)
        d.text((x + pad_x, pad_y), str(l), font=lab, fill=(70, 70, 70))
        d.text((x + pad_x, pad_y + lh + 2), str(v), font=val, fill=PP.INK)
    return img


def _draw_stars(img, m, starred, gold=(196, 145, 0)):
    """Draw a real five-pointed star in the first column of each starred row.

    ★★ THE FONT HAS NO STAR. Checked against a known-missing codepoint: this
    pack's face renders `★`, `☆` and `●` as TOFU — and tofu HAS a bounding box,
    which is why a first `getbbox()` test said the glyph was fine and the sheet
    printed a column of little squares. `*` and `•` do render, but they read as
    footnote marks, not as a badge.
    macOS has Apple Symbols, which does carry `★` — and using it would work on
    this laptop and print tofu on the Space, which is the worse failure because
    nobody would see it here. So the star is DRAWN: no font, no dependency, and
    it scales with the row. See [[feedback-test-where-it-runs]].
    """
    from PIL import ImageDraw
    import math
    d = ImageDraw.Draw(img)
    cw, head_h, row_h = m["col_w"][0], m["head_h"], m["row_h"]
    R = min(cw, row_h) * 0.30
    for i, on in enumerate(starred):
        if not on:
            continue
        cx, cy = cw / 2.0, head_h + i * row_h + row_h / 2.0
        pts = []
        for k in range(10):
            ang = math.radians(-90 + k * 36)
            rad = R if k % 2 == 0 else R * 0.382
            pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        d.polygon(pts, fill=gold)
    return img


def _detail_frame(rows, won):
    out = []
    for r in rows:
        d = {"TOP": "",          # drawn, not typed — see `_draw_stars`
             "#": (r.get("rank") if r.get("rank") else float("nan")),
             "SALESPERSON": r["who"],
             "SELLING FOR": ("" if r["who"] == "TOTAL"
                             else _selling_for(r.get("tenure"),
                                               r.get("censored")))}
        for k, tag in _PERIODS:
            for mk, mlabel in _MEASURES:
                d[f"{tag} {mlabel}"] = r.get(f"{k}_{mk}", 0.0)
        out.append(d)
    return pd.DataFrame(out)[_D_ORDER]


def _extremes(rows, col, best_high):
    """(best value, worst value) for a column, for the cell rules.

    ★ ONLY WHERE A DIRECTION EXISTS. Higher ABV and a bigger basket are better;
    a higher single-piece share is worse. A column whose good end is arguable
    gets no colour at all — an ink that means "notable" and not "good" teaches
    a reader to ignore it.
    """
    vals = [float(r[col]) for r in rows if not pd.isna(r[col])]
    if len(vals) < 3:
        return None, None                 # too few to have an extreme
    hi, lo = max(vals), min(vals)
    return (hi, lo) if best_high else (lo, hi)


def detailed_sheet(L, df, asof, store, code=None):
    """MANAGER DETAILED TEAM REPORT — ONE page, every employee, every period.

    ★ ONE PAGE, EXTENSIVE (Manav, 7 Sep): *"one page with an extensive table
    which covers performance for all employees over day, mtd and ytd. and for
    the employees who top on any metric, make a star icon beside them… on the
    top of the table too, add pill tabs which highlight useful info."*

    The other half of the pair. The pointer sheet POINTS — four cards, bars,
    three short lists, read in five minutes. This one REPORTS: everybody, all
    three windows, five measures each, on a single sheet a manager can put on
    the desk and look things up in. Both come from the same `store_table` call,
    so no figure can differ between them.
    """
    import snapshots_a4 as A4
    import portfolio_pdf as PP

    asof = pd.Timestamp(asof)
    rows, types, meta = store_table(L, df, asof, store)
    if len(rows) <= 1:
        return None
    people, total = rows[:-1], rows[-1]
    live = [r for r in people
            if pd.isna(r.get("quiet")) or r["quiet"] < ABSENT_DAYS]
    gone = [r for r in people
            if not pd.isna(r.get("quiet")) and r["quiet"] >= ABSENT_DAYS]
    # ★ THE RANK IS SET BEFORE THE SORT, THE ORDER AFTER IT. `#` stays the
    # month rank — position is what a manager quotes — while the sheet itself
    # is alphabetical so a name can be FOUND (Manav, 9 Sep). Looking somebody up
    # in a fifty-name list ordered by sales means reading every row.
    for n, r in enumerate(people, start=1):
        r["rank"] = n
    won = _stars(people)
    people = sorted(people, key=lambda r: str(r["who"]).upper())
    _day, _pm = meta.get("day"), meta.get("prev_month")

    _keep = (A4.MARGIN, A4.CONTENT_W, PP.PAD_Y)
    A4.MARGIN = A4.PRINT_MARGIN
    A4.CONTENT_W = A4.PAGE_W - 2 * A4.MARGIN
    try:
        W = A4.CONTENT_W
        title = A4._heading(
            W, f"{store} — team detail",
            f"all {len(people)} on the books, A–Z  ·  {len(live)} sold in the "
            f"last "
            f"{ABSENT_DAYS} days  ·  day = {_day:%d %b} (the last day with "
            f"bills)  ·  month and year to {asof:%d %b %Y}  ·  # is the month "
            f"rank" if _day else f"as of {asof:%d %b %Y}")

        # ---- the pills ----------------------------------------------------
        def _who(key, best_high=True):
            v = [(float(r[key]), r["who"]) for r in people
                 if not pd.isna(r.get(key))]
            v = [(a, b) for a, b in v if a > 0]
            if not v:
                return "—"
            return (max(v)[1] if best_high else min(v)[1])

        sh = meta.get("shape") or {}
        pills = [
            ("Top of the month", _who("m_sales")),
            ("Top yesterday", _who("d_sales")),
            ("Most pieces this month", _who("m_units")),
            ("Biggest bill this month", _who("m_abv")),
        ]
        if meta.get("store_single") is not None:
            pills.append(("Store single-piece",
                          f"{meta['store_single']:.0f}%"))
        if sh.get("top3") is not None and sh.get("sellers", 0) > 3:
            pills.append(("Top three wrote", f"{sh['top3']:.0f}% of the month"))
        if gone:
            pills.append((f"Not sold in {ABSENT_DAYS}d+", f"{len(gone)} people"))
        pill_img = _pills(W, pills[:4])
        pill_img2 = _pills(W, pills[4:]) if len(pills) > 4 else None

        cap = A4._caption(
            W, "Everybody, on the day, the month and the year",
            "The star marks whoever TOPS a measure — day, month or year sales, most "
            "pieces, biggest bill, biggest basket, or the lowest single-piece "
            "share. A star is won on ONE measure, not on an overall score, "
            "because the best seller by money is rarely the one moving the "
            "most pieces · SELLING FOR is time since their first sale IN THIS "
            "DATA, and a + means their store's records start there · ABV is "
            "sales per bill · ABS is LINES per bill, not garments · SINGLE is "
            "the share of bills that left with one piece, so lower is better")

        notes = []
        if meta.get("excluded"):
            notes.append(f"Rs {meta['excluded']:,.0f} of night-fill sale is not "
                         f"in this table — it belongs to nobody yet.")
        if meta["duplicates"]:
            notes.append("Check with the POS: " + ", ".join(meta["duplicates"])
                         + " appears under more than one salesperson id.")
        star_note = " · ".join(
            f"{r['who']} — {', '.join(won[id(r)])}" for r in people
            if id(r) in won)
        if star_note:
            notes.append("Stars: " + star_note + ".")
        note = (A4._text_block(W, [(" ".join(notes), A4._ft(21)[0], A4.SUB)])
                if notes else None)

        disp = _detail_frame(people + [total], won)
        ptypes = types
        fixed = (title.height + 20 + pill_img.height + 12
                 + (pill_img2.height + 12 if pill_img2 else 0)
                 + cap.height + 8 + (note.height + 14 if note else 0) + 20)
        # ★ THE FOOTER BAND IS PART OF THE PAGE. Fitting against
        # `PAGE_H - 2*MARGIN` ignored the ~9mm `_Sheet` reserves for the
        # footer, so the table was sized to a page slightly taller than the one
        # it would be drawn on — Jayanagar's 27 rows spilled onto a second
        # sheet while Grand Kamraj Road's 60 happened to fit. A one-page report
        # that is one page only for some stores is not a one-page report.
        _foot = int(round(9 / 25.4 * A4.DPI))
        usable = A4.PAGE_H - 2 * A4.MARGIN - _foot
        font_px, _p, m = _fit_table(disp, _D_MONEY, _D_PCT, _D_NUM, W,
                                    usable, fixed,
                                    whole=_D_WHOLE, sign=_D_SIGN)

        sheet = A4._Sheet(store, asof, "", bounded=True, footer=True)
        sheet.put(title, gap=20)
        sheet.put(pill_img, gap=12)
        if pill_img2 is not None:
            sheet.put(pill_img2, gap=12)
        sheet.put(cap, gap=8)
        if note:
            sheet.put(note, gap=14)
        # ★ THE PERIOD BLOCKS, keyed on where each column actually lands so the
        # bands follow the spec rather than a hard-coded count.
        _band = {"DAY": _BAND_DAY, "MTD": _BAND_MTD, "YTD": _BAND_YTD}
        _colbg = {j: _band[c.split()[0]] for j, c in enumerate(_D_ORDER)
                  if c.split()[0] in _band}

        # ★ AND THE TWO ROW STATES. "Sold nothing" is judged on the YEAR, not
        # the day or the month: somebody who simply did not work yesterday is
        # not idle, and greying them for it would be wrong on most of the team
        # most mornings.
        #
        # ★★ ZERO SALES MEANS ZERO SALES, NOT ZERO ACTIVITY. A first pass also
        # demanded zero BILLS and nobody was marked — Ganesh Chandrakant Palke
        # has one bill for the year and Nilesh Govind Bhai Harijan seven, both
        # totalling nothing. A bill that adds up to zero is exactly the row
        # worth marking, not a reason to skip it.
        #
        # ★ ZERO AND NEGATIVE TOGETHER (Manav, 9 Sep). A year that has gone
        # backwards on returns and a year that never started are both "no sale
        # to show for it", and he wants them read the same way: the FULL line
        # in red, name included. Nayaz P at -5,499 joins the two who are flat.
        _ink = {}
        for i, r in enumerate(people):
            if float(r.get("y_sales") or 0) <= 0:
                _ink[i] = _INK_DEAD
            elif id(r) in won:
                _ink[i] = _INK_STAR

        _wm = A4._widen(m, W)
        _body = PP._render_chunk(_wm, ptypes, list(range(len(disp))),
                                 col_bg=_colbg, row_ink=_ink)
        _draw_stars(_body, _wm, [id(r) in won for r in people] + [False])
        sheet.put(_body, gap=20)
        out = sheet.pdf()
        npages = len(sheet.pages)
    finally:
        A4.MARGIN, A4.CONTENT_W, PP.PAD_Y = _keep

    tag = f"{code}_" if code is not None else ""
    stem = (f"{asof:%Y-%m-%d}_{tag}"
            f"{__import__('snapshots')._slug(store)}_team_detailed")
    return (f"{stem}.pdf", out, font_px, npages, meta["team"])


def store_sheets(L, df, asof, kind="pointer", folder=None):
    """Every open store's sheet, as [(name, PDF bytes), …] + failures.

    ★ TWO REPORTS, ONE SOURCE (Manav, 6 Sep). `kind="pointer"` is the
    five-minute page; `kind="detailed"` is the deep dive. Both come from the
    same `store_table` call, so a figure cannot say one thing on one and
    something else on the other.

    ★ AND EACH LANDS IN ITS OWN FOLDER, so a zip carrying both does not mix
    them — the pointer is what gets forwarded to a manager, the detail is what
    gets read at a desk.
    """
    import snapshots_a4 as A4
    asof = pd.Timestamp(asof)
    build = {"pointer": pointer_sheet, "detailed": detailed_sheet}[kind]
    folder = folder if folder is not None else (
        "team-pointer" if kind == "pointer" else "team-detailed")
    master = L.load_store_master().set_index("tableau_name")
    out, failed = [], []
    for s in A4.open_stores(L, df):
        code = int(master.loc[s, "code"]) if s in master.index else None
        try:
            made = build(L, df, asof, s, code)
        except Exception as e:                  # one store must not sink the run
            failed.append(f"{s}: {e}")
            continue
        if made is None:
            failed.append(f"{s}: nobody sold")
            continue
        # ★ ONE DIRECTORY PER REGION, like the morning snapshots — the same
        # reason: twenty sheets in one folder have to be picked through before
        # anything can be sent.
        region = ""
        if s in master.index:
            r = master.loc[s].get("region")
            region = "" if r is None or pd.isna(r) else str(r).strip()
        parts = [p for p in (folder, region) if p]
        out.append(("/".join(parts + [made[0]]) if parts else made[0], made[1]))
    return out, failed
