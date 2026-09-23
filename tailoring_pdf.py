"""The alterations & parking pack — two tables, nothing else.

Manav, 23 Sep: *"keep this simple — Parking / Alteration Chgs, each Store Code
· Store Name · Day · MTD · YTD."*

★ A ZERO IN `DAY` MEANS NOTHING WAS RECORDED, WHICH IS NOT THE SAME AS NOTHING
WAS TAKEN. These books are typed by hand and several stores go weeks between
entries, so one line under the tables names anyone who has not recorded in over
a week. Without it a stalled book reads as a quiet store.
See [[feedback-silent-failure-must-speak]].
"""
from __future__ import annotations

import pandas as pd

import tailoring as T


def _windows(asof: pd.Timestamp):
    """(day, month start, fiscal-year start) — April to March, as everywhere."""
    fy = asof.year if asof.month >= 4 else asof.year - 1
    return asof, asof.replace(day=1), pd.Timestamp(fy, 4, 1)


def table(frame, folders, kind, asof):
    """One row per store that keeps this book, plus a total."""
    names = T.store_names(folders)
    day, mstart, ystart = _windows(asof)
    part = frame[frame["kind"] == kind]
    rows = []
    for code in sorted({f["store_code"] for f in folders}
                       & set(part["store_code"].unique())):
        s = part[part["store_code"] == code]
        rows.append({
            # ★ TEXT, NOT A NUMBER. Sevoke Road is store 10005 and an int
            # column would print it as "10,005" — a code is an identifier,
            # never a quantity. See [[feedback-declare-numeric-columns]].
            "code": str(int(code)),
            "store": names.get(code, str(code)),
            "day": float(s[s["date"] == day]["total"].sum()),
            "mtd": float(s[(s["date"] >= mstart) & (s["date"] <= day)]["total"].sum()),
            "ytd": float(s[(s["date"] >= ystart) & (s["date"] <= day)]["total"].sum()),
        })
    rows.sort(key=lambda r: -r["ytd"])
    total = {"code": "", "store": "TOTAL",
             "day": sum(r["day"] for r in rows),
             "mtd": sum(r["mtd"] for r in rows),
             "ytd": sum(r["ytd"] for r in rows)}
    return rows, total


REGION_SPEC = [("region", "text", "REGION"), ("book", "text", "BOOK"),
               ("day", "money", "DAY"), ("mtd", "money", "MTD"),
               ("ytd", "money", "YTD")]

SPEC = [("code", "text", "STORE CODE"), ("store", "text", "STORE NAME"),
        ("day", "money", "DAY"), ("mtd", "money", "MTD"), ("ytd", "money", "YTD")]


def region_table(frame, folders, asof):
    """The same three windows, split South against East & NE.

    ★ REGION COMES FROM THE DRIVE FOLDER THE FILE WAS FOUND IN, and that was
    checked against the dashboard's own store master — all fourteen stores
    agree, so this needs no feed and cannot drift from the estate's definition
    without the disagreement showing up here first.
    """
    day, mstart, ystart = _windows(asof)
    region_of = {f["store_code"]: f["region"] for f in folders}
    rows = []
    for region in sorted({r for r in region_of.values()}):
        codes = [c for c, r in region_of.items() if r == region]
        for kind, label in (("parking", "Parking"), ("alter", "Alteration Chgs")):
            s = frame[(frame["kind"] == kind) & (frame["store_code"].isin(codes))]
            if s.empty:
                continue            # a region that keeps no such book is silent
            rows.append({
                "region": region, "book": label,
                "day": float(s[s["date"] == day]["total"].sum()),
                "mtd": float(s[(s["date"] >= mstart) & (s["date"] <= day)]["total"].sum()),
                "ytd": float(s[(s["date"] >= ystart) & (s["date"] <= day)]["total"].sum()),
            })
    total = {"region": "TOTAL", "book": "",
             "day": sum(r["day"] for r in rows),
             "mtd": sum(r["mtd"] for r in rows),
             "ytd": sum(r["ytd"] for r in rows)}
    return rows, total


def build(frame, folders, notes=(), asof=None) -> tuple:
    import festive_admin as FADM
    import portfolio_pdf as PP
    import snapshots_a4 as A4

    asof = pd.Timestamp(asof or pd.Timestamp.today()).normalize()
    _keep = (A4.MARGIN, A4.CONTENT_W, PP.PAD_Y)
    A4.MARGIN = A4.PRINT_MARGIN
    A4.CONTENT_W = A4.PAGE_W - 2 * A4.MARGIN
    try:
        W = A4.CONTENT_W
        sheet = A4._Sheet("Alterations & parking", asof, "", bounded=False,
                          footer=True)
        _day, _mstart, _ystart = _windows(asof)
        sheet.put(A4._heading(
            W, "Parking & alteration charges",
            f"as recorded in the store books · "
            f"day {asof:%d %b %Y} · MTD from {_mstart:%d %b} · "
            f"YTD from {_ystart:%d %b %Y}"), gap=18)

        for kind, title in (("parking", "Parking"),
                            ("alter", "Alteration Chgs")):
            rows, total = table(frame, folders, kind, asof)
            sheet.put(A4._caption(W, title, ""), gap=8)
            if rows:
                sheet.put(FADM.table_image(rows, SPEC, W, font_px=25,
                                           total_row=total), gap=22)
            else:
                sheet.put(A4._text_block(
                    W, [("No store keeps this book.", A4._ft(22)[0], A4.SUB)]),
                    gap=22)

        rrows, rtotal = region_table(frame, folders, asof)
        if rrows:
            sheet.put(A4._caption(W, "By region", ""), gap=8)
            sheet.put(FADM.table_image(rrows, REGION_SPEC, W, font_px=25,
                                       total_row=rtotal), gap=22)

        stale = T.freshness(frame, asof)
        stale = stale[stale["days_since"] > 7]
        if len(stale):
            names = T.store_names(folders)
            said = ", ".join(
                f"{names.get(r.store_code, r.store_code)} "
                f"({r.kind}, {int(r.days_since)} days)"
                for _, r in stale.sort_values("days_since", ascending=False).iterrows())
            sheet.put(A4._text_block(W, [(
                "These books have not been written in for over a week, so a "
                "zero above is a book nobody opened rather than a day nobody "
                "took money: " + said + ".", A4._ft(21)[0], A4.SUB)]), gap=10)

        sheet._footers()
        out = sheet.pdf()
        pages = len(sheet.pages)
    finally:
        A4.MARGIN, A4.CONTENT_W, PP.PAD_Y = _keep
    return f"PARKING & ALTERATIONS {asof:%d-%m-%Y}.pdf", out, pages
