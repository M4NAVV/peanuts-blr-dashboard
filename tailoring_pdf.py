"""The alterations & parking pack — one PDF, everything the workbooks hold.

★ FRESHNESS LEADS, MONEY FOLLOWS. A store that stopped typing looks exactly
like a store that stopped selling, and on this data that is not a hypothetical:
several stores have a workbook they have barely opened. The page says when each
store last recorded before it says how much.
"""
from __future__ import annotations

import pandas as pd

import tailoring as T


def _fmt_days(d):
    d = int(d)
    return "today" if d == 0 else ("1 day" if d == 1 else f"{d} days")


def build(frame, folders, notes, asof=None) -> tuple:
    import festive_admin as FADM
    import portfolio_pdf as PP
    import report_td as RT
    import snapshots as SN
    import snapshots_a4 as A4

    asof = pd.Timestamp(asof or pd.Timestamp.today()).normalize()
    names = T.store_names(folders)
    alt = frame[frame["kind"] == "alter"]
    park = frame[frame["kind"] == "parking"]

    _keep = (A4.MARGIN, A4.CONTENT_W, PP.PAD_Y)
    A4.MARGIN = A4.PRINT_MARGIN
    A4.CONTENT_W = A4.PAGE_W - 2 * A4.MARGIN
    try:
        W = A4.CONTENT_W
        sheet = A4._Sheet("Alterations & parking", asof, "", bounded=False,
                          footer=True)
        fr = T.freshness(frame, asof)
        recording = fr["store_code"].nunique()
        stale = int((fr[fr.kind == "alter"]["days_since"] > 7).sum())
        with_file = len({f["store_code"] for f in folders}) if folders else 0

        sheet.put(A4._heading(
            W, "Alterations & parking",
            f"what the store workbooks hold · {len(frame):,} bills · "
            f"{frame['date'].min():%d %b} to {frame['date'].max():%d %b %Y} · "
            f"read {asof:%d %b %Y}"), gap=18)

        sheet.put(SN._cards_image([
            ("Alterations, year to date", "Rs " + FADM.money(alt["total"].sum())),
            ("Parking", "Rs " + FADM.money(park["total"].sum())),
            ("Stores recording", f"{recording} of {with_file}"),
            ("Not recorded in a week", f"{stale}"),
        ], W, label_px=25, value_px=42), gap=16)

        sheet.put(A4._text_block(W, [(
            "Every store keeps its own workbook and types into it as "
            "alterations are booked, so a figure here is only as current as the "
            "last person to open the file. The days column is the point: a "
            "store that has stopped recording reads exactly like a store that "
            "has stopped selling, and only one of those is worth acting on.",
            A4._ft(22)[0], A4.SUB)]), gap=16)

        # ---- freshness, and it leads ------------------------------------- #
        sheet.put(A4._caption(W, "When each store last recorded",
                              "oldest first — the ones to chase"), gap=10)
        rows = []
        for _, r in fr.sort_values("days_since", ascending=False).iterrows():
            rows.append({"store": names.get(r.store_code, str(r.store_code)),
                         "kind": r.kind, "last": f"{r.last_bill:%d %b %Y}",
                         "ago": _fmt_days(r.days_since), "bills": int(r.rows),
                         "total": float(r.total),
                         "_stale": r.days_since > 7})
        spec = [("store", "text", "STORE"), ("kind", "text", "BOOK"),
                ("last", "text", "LAST RECORDED"), ("ago", "text", "AGO"),
                ("bills", "int", "BILLS"), ("total", "money", "COLLECTED")]
        sheet.put(FADM.table_image(rows, spec, W, font_px=24,
                                   neg_row=lambda r: r.get("_stale")), gap=20)

        # ---- month by month ---------------------------------------------- #
        sheet.put(A4._caption(W, "Alterations, month by month",
                              "as recorded, not as billed on the POS"), gap=10)
        m = T.by_month(alt)
        mrows, months = [], list(m.columns)
        for code, row in m.iterrows():
            rec = {"store": names.get(code, str(code))}
            for mo in months:
                rec[str(mo)] = float(row[mo])
            rec["total"] = float(row.sum())
            mrows.append(rec)
        mrows.sort(key=lambda r: -r["total"])
        mspec = ([("store", "text", "STORE")]
                 + [(str(mo), "money", pd.Timestamp(mo).strftime("%b").upper())
                    for mo in months]
                 + [("total", "money", "TOTAL")])
        tot = {"store": "TOTAL"}
        for mo in months:
            tot[str(mo)] = float(m[mo].sum())
        tot["total"] = float(alt["total"].sum())
        sheet.put(FADM.table_image(mrows, mspec, W, font_px=24, total_row=tot),
                  gap=20)

        # ---- how it was paid --------------------------------------------- #
        sheet.put(A4._caption(W, "How alterations were paid",
                              "card share is the tell — an informal book runs "
                              "on cash"), gap=10)
        sp = alt.groupby("store_code")[["cash", "card_upi", "total"]].sum()
        prows = []
        for code, r in sp.iterrows():
            prows.append({"store": names.get(code, str(code)),
                          "cash": float(r.cash), "card": float(r.card_upi),
                          "total": float(r.total),
                          "share": (r.card_upi / r.total * 100) if r.total else None})
        prows.sort(key=lambda r: -r["total"])
        pspec = [("store", "text", "STORE"), ("cash", "money", "CASH"),
                 ("card", "money", "CARD / UPI"), ("total", "money", "TOTAL"),
                 ("share", "pct", "CARD %")]
        ptot = {"store": "TOTAL", "cash": float(sp.cash.sum()),
                "card": float(sp.card_upi.sum()), "total": float(sp.total.sum()),
                "share": (sp.card_upi.sum() / sp.total.sum() * 100
                          if sp.total.sum() else None)}
        sheet.put(FADM.table_image(prows, pspec, W, font_px=24, total_row=ptot),
                  gap=20)

        # ---- what the read itself found ---------------------------------- #
        problems = T.check(frame)
        lines = (problems or
                 ["Every bill satisfies Total = Billed - Due + Due Paid, and "
                  "Cash + Card/Upi = Total. No repeated bill numbers."])
        sheet.put(A4._caption(W, "What the read found",
                              "checked on every row of every file"), gap=10)
        sheet.put(A4._text_block(W, [("  ·  " + "\n  ·  ".join(lines),
                                      A4._ft(22)[0], A4.SUB)]), gap=14)
        if notes:
            sheet.put(A4._caption(W, "Files and folders",
                                  "said out loud rather than quietly skipped"),
                      gap=10)
            sheet.put(A4._text_block(W, [("  ·  " + "\n  ·  ".join(notes),
                                          A4._ft(21)[0], A4.SUB)]), gap=10)

        sheet._footers()
        out = sheet.pdf()
        pages = len(sheet.pages)
    finally:
        A4.MARGIN, A4.CONTENT_W, PP.PAD_Y = _keep
    return f"ALTERATIONS {asof:%d-%m-%Y}.pdf", out, pages
