"""The collection books, one page a store — the accounts copy.

Manav, 24 Sep 2026: *"the next report we are making is a long format one …
like this, but for every store we have for tailoring and parking. so around
12-13 pages, this is more for accounts keeping purposes."*

What he sent is the head of a store's own workbook: a Today/Yesterday pair, the
twelve months of the financial year, a total, and the bill ledger under it.
This prints that block for EVERY book the Drive holds — one page each, in the
house type, with the figures RE-DERIVED FROM THE BILLS rather than copied from
the store's own summary cells.

★ THE STORE'S SUMMARY BLOCK IS NEVER READ, and that is not fussiness. Its
Today/Yesterday cells are live formulas against the clock of whoever last
opened the file: the copy of Grand Kamraj's book on disk says Today is 23 Sep
while the same file opened this morning says 24 Sep. A figure that changes
when you look at it cannot be an accounts record. Every number on these pages
is summed from the dated bill rows, which is also what makes the page-one
totals reconcile against the per-store pages by construction.

★ A BOOK WITH NO BILLS STILL GETS A PAGE. Fairfield and Agartala keep a file
with a header and nothing under it. Dropping them would make the pack read as
though those stores have no book at all, when what is true is that the book is
empty — see [[feedback-silent-failure-must-speak]].
"""
from __future__ import annotations

import pandas as pd

import tailoring as T

MONEY = ("billed", "due", "due_paid", "total", "cash", "card_upi")

# His workbook's columns, in his order. `BILLS` is ours: a month's bill count
# is the control total that says whether a figure moved because trade moved or
# because somebody typed one line twice.
SPEC = [("period", "text", "PERIOD"),
        ("billed", "rupee", "BILLED\nAMOUNT"),
        ("due", "rupee", "DUE\nAMOUNT"),
        ("due_paid", "rupee", "DUE\nPAID"),
        ("total", "rupee", "TOTAL"),
        ("cash", "rupee", "CASH"),
        ("card_upi", "rupee", "CARD/UPI"),
        ("bills", "int", "BILLS")]

LEDGER_SPEC = [("day", "text", "DATE"), ("bill_no", "text", "BILL NO"),
               ("billed", "rupee", "BILLED\nAMOUNT"),
               ("due", "rupee", "DUE\nAMOUNT"),
               ("due_paid", "rupee", "DUE\nPAID"),
               ("total", "rupee", "TOTAL"),
               ("cash", "rupee", "CASH"),
               ("card_upi", "rupee", "CARD/UPI")]

# ★ ONE TABLE, ONE WINDOW (Manav, 24 Sep: *"instead of one table for both mtd
# and ytd, we need 2 tables"*). The same columns are drawn twice, once for the
# month and once for the year, each under a caption that names its span and
# with the span repeated on its own TOTAL line. Money columns from two
# different windows sharing one grid is how two correct figures come to read as
# one — see [[feedback-same-estate]].
INDEX_SPEC = [("code", "text", "STORE\nCODE"), ("store", "text", "STORE NAME"),
              ("book", "text", "BOOK"),
              ("billed", "rupee", "BILLED\nAMOUNT"),
              ("due", "rupee", "DUE\nAMOUNT"),
              ("due_paid", "rupee", "DUE\nPAID"),
              ("total", "rupee", "TOTAL"),
              ("cash", "rupee", "CASH"),
              ("card_upi", "rupee", "CARD/UPI"),
              ("bills", "int", "BILLS"),
              ("last", "text", "LAST\nRECORDED")]

SPANS = {"mtd": "Month to date", "ytd": "Year to date"}

KIND_LABEL = {"alter": "Tailor", "parking": "Parking"}


def fy_of(asof) -> int:
    """April to March, as everywhere else in this estate."""
    asof = pd.Timestamp(asof)
    return asof.year if asof.month >= 4 else asof.year - 1


def fy_label(asof) -> str:
    fy = fy_of(asof)
    return f"FY {fy % 100}-{(fy + 1) % 100}"


def fy_months(asof):
    fy = fy_of(asof)
    return [pd.Timestamp(fy + (m > 12), ((m - 1) % 12) + 1, 1)
            for m in range(4, 16)]


def window(part, start, end) -> dict:
    """The six money columns and a bill count over an inclusive date span."""
    s = part[(part["date"] >= start) & (part["date"] <= end)] \
        if len(part) else part
    out = {c: float(s[c].sum()) if len(s) else 0.0 for c in MONEY}
    out["bills"] = int(len(s))
    return out


def summary(part, asof) -> tuple:
    """(rows, total) — Today, Yesterday, the twelve months, and the year.

    ★ THE MONTHS ARE ALL TWELVE, including the ones still to come, because the
    shape of the page is what an accounts desk files. A month that has not
    happened reads as dashes, exactly as it does in the store's book.
    """
    asof = pd.Timestamp(asof).normalize()
    rows = []
    for label, d in (("Today", asof), ("Yesterday", asof - pd.Timedelta(days=1))):
        rows.append({"period": f"{label}  ·  {d:%d-%m-%Y}", **window(part, d, d)})
    # ★ EVERY WINDOW ENDS AT THE REPORT DATE. Run for a day in the past, this
    # page must read as it read on that day — a month row that ran to the end
    # of the month would carry bills typed after it, and the pack would show a
    # future the day it is dated did not have. The same cap is why the index's
    # LAST RECORDED cannot print a date later than the pack's own.
    months = fy_months(asof)
    for m in months:
        end = min(m + pd.offsets.MonthEnd(1), asof)
        rows.append({"period": f"{m:%b-%y}", **window(part, m, end)})
    total = {"period": f"TOTAL  ·  {fy_label(asof)}",
             **window(part, months[0], asof)}
    return rows, total


def ledger(part, asof, cap: int = 40) -> tuple:
    """(rows, total, day, kept, all) — the bills of the latest recorded day.

    ★ NOT THE WHOLE BOOK. Grand Kamraj alone has 614 bills this year; printed
    in full this pack would run past a hundred pages and stop being a thing
    anyone files. The day that was last written in is the one an accounts desk
    is reconciling, and the heading names it rather than implying it is today.
    """
    asof = pd.Timestamp(asof).normalize()
    part = part[part["date"] <= asof] if len(part) else part
    if not len(part):
        return [], None, None, 0, 0
    day = part["date"].max()
    s = part[part["date"] == day].sort_values("bill_no")
    rows = [{"day": f"{day:%d-%m-%Y}", "bill_no": str(r.bill_no),
             **{c: float(getattr(r, c)) for c in MONEY}}
            for r in s.itertuples()]
    kept = rows[:cap]
    # ★ THE TOTAL FOOTS THE ROWS PRINTED. A table whose total quietly covered
    # rows it did not show is a page nobody can check — and this page exists to
    # be checked. When the day is longer than the page, the line under it says
    # what the whole day came to.
    total = {"day": "", "bill_no": "TOTAL",
             **{c: float(sum(r[c] for r in kept)) for c in MONEY}}
    return kept, total, day, len(kept), len(rows)


def books(sources, frame) -> list:
    """One entry per (store, book) the Drive holds, deduplicated.

    ★ THE SAME RULE AS THE READER: where a store folder holds two copies of a
    book, the one whose bills reached the frame is the one that is real
    (Jayanagar keeps a `Copy of ALTER_PRJN` beside the live file). The pack
    must not contain a page built from a file the tab ignored.
    """
    live = set(frame["source_id"].unique()) if len(frame) else set()
    cands = {}
    for s in sources:
        cands.setdefault((s["store_code"], s["kind"]), []).append(s)
    out = []
    for (code, kind), group in cands.items():
        s = next((g for g in group if g["id"] in live), group[0])
        out.append({"store_code": code, "kind": kind, "region": s["region"],
                    "pr": s.get("pr", ""), "id": s["id"], "name": s["name"]})
    return out


def index_rows(frame, sources, folders, asof, span="ytd") -> tuple:
    """Page one: every book over one window — `mtd` or `ytd`.

    ★ EVERY BOOK IS HERE, including the ones that get no page behind them. This
    is the page that says WHY a store has no page: its last recorded date. A
    pack that listed only the books it printed would make a store that stopped
    typing disappear from the pack entirely.

    ★ AND IT IS ORDERED BY STORE CODE (Manav, 24 Sep), not by size. This is a
    filing document: the same store is on the same line of the month table and
    the year table, and it is where it was last month.
    """
    names = T.store_names(folders)
    asof = pd.Timestamp(asof).normalize()
    # ★ BOTH WINDOWS END AT THE REPORT DATE, so a pack run for a day in the
    # past reads as it read on that day.
    start = asof.replace(day=1) if span == "mtd" else fy_months(asof)[0]
    rows = []
    for b in sorted(books(sources, frame),
                    key=lambda b: (b["store_code"], b["kind"])):
        part = _part(frame, b)
        seen = part[part["date"] <= asof]["date"] if len(part) else part
        last = seen.max() if len(seen) else None
        rows.append({"code": str(int(b["store_code"])),
                     "store": names.get(b["store_code"], str(b["store_code"])),
                     "book": KIND_LABEL.get(b["kind"], b["kind"]),
                     "last": f"{last:%d-%m-%Y}" if last is not None else "never",
                     "last_dt": last,          # sortable; not on the spec
                     "key": (int(b["store_code"]), b["kind"]),
                     **window(part, start, asof)})
    total = {"code": "", "store": "TOTAL", "book": span.upper(), "last": "",
             "bills": sum(r["bills"] for r in rows),
             **{c: sum(r[c] for r in rows) for c in MONEY}}
    return rows, total


def latest_day(frame, asof):
    """The last day ANY book was written in, on or before the report date.

    ★ THE DAY, NOT THE DATE THE PACK WAS RUN. Nobody types the morning's bills
    before the morning, so a pack built at 10am on the 24th would otherwise be
    a pack of empty days. This is the same reading as the sales feed's settled
    day — see [[feedback-provisional-day]].
    """
    if not len(frame):
        return None
    d = frame[frame["date"] <= pd.Timestamp(asof).normalize()]["date"]
    return d.max() if len(d) else None


def on_day(frame, sources, day) -> list:
    """The books that recorded on `day` — the only ones that get a page.

    Manav, 24 Sep 2026: *"only show those stores whose last recorded is the
    latest day of sales … for stores which dont have that, there is no point
    for showing those previous records."*

    ★ A BOOK'S LAST RECORDED DAY IS ITS OWN. Commercial St last wrote on the
    20th; printing its page in a pack dated the 23rd would put a four-day-old
    book beside a current one under one date, and the two would read as equal.
    Page one still carries every book, with the date each last recorded.
    """
    if day is None:
        return []
    day = pd.Timestamp(day).normalize()
    got = frame[frame["date"] == day] if len(frame) else frame
    live = {(int(c), k) for c, k in
            zip(got["store_code"], got["kind"])} if len(got) else set()
    return [b for b in books(sources, frame)
            if (int(b["store_code"]), b["kind"]) in live]


def _part(frame, b):
    if not len(frame):
        return frame
    return frame[(frame["store_code"] == b["store_code"])
                 & (frame["kind"] == b["kind"])]


def build(frame, folders, sources, asof=None) -> tuple:
    """(filename, pdf bytes, page count)."""
    import festive_admin as FADM
    import portfolio_pdf as PP
    import snapshots_a4 as A4

    asof = pd.Timestamp(asof or pd.Timestamp.today()).normalize()
    if not len(frame):
        frame = pd.DataFrame(columns=["store_code", "kind", "date", "bill_no",
                                      "source_id", *MONEY])
    names = T.store_names(folders)
    _keep = (A4.MARGIN, A4.CONTENT_W, PP.PAD_Y)
    A4.MARGIN = A4.PRINT_MARGIN
    A4.CONTENT_W = A4.PAGE_W - 2 * A4.MARGIN
    try:
        W = A4.CONTENT_W
        pages = []

        day = latest_day(frame, asof)
        printed = on_day(frame, sources, day)
        keys = {(int(b["store_code"]), b["kind"]) for b in printed}

        # ---------- page one: every book, and which ones got a page --------
        rows, _ = index_rows(frame, sources, folders, asof, "ytd")
        one = A4._Sheet("Collection books", asof, "", bounded=False, footer=True)
        one.put(A4._heading(
            W, f"Collection books — {fy_label(asof)}",
            f"every tailoring and parking book in the store-ops Drive  ·  "
            f"{len(rows)} book{'' if len(rows) == 1 else 's'}  ·  "
            f"to {asof:%d %b %Y}"), gap=18)
        one.put(A4._text_block(W, [(
            "Every figure in this pack is summed from the dated bill rows of "
            "the store's own book, not from the summary cells at the top of "
            "it — those are live formulas that change with the clock of "
            "whoever opens the file. Nothing after the date this pack is "
            "dated is in it, in either table below.",
            A4._ft(22)[0], A4.SUB)]), gap=14)
        for span, label, since in (
                ("mtd", SPANS["mtd"], f"1 {asof:%b}"),
                ("ytd", SPANS["ytd"], "1 Apr")):
            srows, stotal = index_rows(frame, sources, folders, asof, span)
            one.put(A4._caption(
                W, label, f"{since} to {asof:%d %b %Y}  ·  by store code"),
                gap=8)
            one.put(FADM.table_image(srows, INDEX_SPEC, W, font_px=23,
                                     total_row=stotal), gap=18)

        # ★ THE PAGES BEHIND THIS ONE ARE A SUBSET, AND IT SAYS SO. A reader
        # who counted pages and found nine stores missing would be right to
        # distrust the whole pack. See [[feedback-silent-failure-must-speak]].
        if day is None:
            one.put(A4._text_block(W, [(
                f"No book has recorded a bill on or before {asof:%d %b %Y}, "
                f"so there are no store pages behind this one.",
                A4._ft(22)[0], A4.SUB)]), gap=10)
        else:
            behind = sorted((r for r in rows if r["key"] not in keys),
                            key=lambda r: (r["last_dt"] is not None,
                                           r["last_dt"] or pd.Timestamp.min),
                            reverse=True)
            said = ", ".join(f"{r['store']} ({r['book'].lower()}, {r['last']})"
                             for r in behind)
            _n1 = f"{len(printed)} book" + ("" if len(printed) == 1 else "s")
            _n2 = f"{len(behind)} book" + ("" if len(behind) == 1 else "s")
            one.put(A4._text_block(W, [(
                f"A page follows for each of the {_n1} that recorded on "
                f"{day:%d %b %Y} — the latest day any book was written in on "
                f"or before {asof:%d %b %Y}. "
                + (f"{_n2} last recorded before that day and get no page: "
                   f"{said}. Their month and year are in the table above."
                   if behind else "Every book recorded that day."),
                A4._ft(22)[0], A4.SUB)]), gap=10)
        one._footers()
        pages += one.pages

        # ---------- a page a book ------------------------------------------
        for b in sorted(printed, key=lambda b: (b["store_code"], b["kind"])):
            part = _part(frame, b)
            store = names.get(b["store_code"], str(b["store_code"]))
            kind = KIND_LABEL.get(b["kind"], b["kind"])
            sh = A4._Sheet(f"{store} — {kind.lower()} book", asof, "",
                           bounded=False, footer=True)
            pr = f"{b['pr']}  ·  " if b.get("pr") else ""
            sh.put(A4._heading(
                W, f"{kind} Collection Summary — {store}",
                f"{pr}store {int(b['store_code'])}  ·  {b['region']}  ·  "
                f"{fy_label(asof)}  ·  as of {asof:%d %b %Y}"), gap=16)

            rows, total = summary(part, asof)
            sh.put(FADM.table_image(rows, SPEC, W, font_px=25,
                                    total_row=total), gap=20)

            lrows, ltotal, bday, kept, n = ledger(part, asof)
            if lrows:
                gap_days = (asof - bday).days
                said = ("today" if gap_days == 0 else
                        "yesterday" if gap_days == 1 else
                        f"{gap_days} days ago")
                bill = "bill" if n == 1 else "bills"
                sh.put(A4._caption(
                    W, f"The bills of {bday:%d %b %Y}",
                    f"the latest day this book records — {said}  ·  "
                    + (f"all {n} {bill}" if kept >= n
                       else f"the first {kept} of {n} {bill}")), gap=8)
                sh.put(FADM.table_image(lrows, LEDGER_SPEC, W, font_px=28,
                                        total_row=ltotal, fill=False), gap=14)
                if kept < n:
                    whole = window(part, bday, bday)
                    sh.put(A4._text_block(W, [(
                        f"The TOTAL line foots the {kept} rows printed here. "
                        f"{n - kept} further bills of {bday:%d %b} are in the "
                        f"store's own book; the whole day came to "
                        f"{PP._fmt_in(whole['total'], 0)} across {n} bills, "
                        f"and it is that figure the month above carries.",
                        A4._ft(21)[0], A4.SUB)]), gap=10)
            else:
                sh.put(A4._text_block(W, [(
                    "This book holds no dated bill rows at all — the file "
                    "exists and has its header, and nothing has been typed "
                    "under it. That is a book nobody has opened, not a store "
                    "that took nothing.", A4._ft(22)[0], A4.SUB)]), gap=10)
            sh._footers()
            pages += sh.pages

        _number(pages, A4)
        import io
        buf = io.BytesIO()
        pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:],
                      resolution=A4.PAGE_W * 72.0 / A4.PAGE_PT_W)
        out = buf.getvalue()
    finally:
        A4.MARGIN, A4.CONTENT_W, PP.PAD_Y = _keep
    return (f"COLLECTION BOOKS {asof:%d-%m-%Y}.pdf", out, len(pages))


def _number(pages, A4):
    """`Page 3 of 13`, bottom right, in the footer's own type.

    ★ THE SHEET CANNOT DO THIS ITSELF. Each page here is its own one-page
    sheet, so `_Sheet._footers` sees a document of one and correctly declines
    to number it. The pack is thirteen pages of near-identical tables and is
    unusable unpaginated.
    """
    from PIL import ImageDraw
    f, _ = A4._ft(24)
    n = len(pages)
    for i, p in enumerate(pages, 1):
        d = ImageDraw.Draw(p)
        t = f"Page {i} of {n}"
        y = p.height - A4.MARGIN - A4._h(f)
        d.text((A4.PAGE_W - A4.MARGIN - d.textlength(t, font=f), y), t,
               font=f, fill=A4.SUB)
