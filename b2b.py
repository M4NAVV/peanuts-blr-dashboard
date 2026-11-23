"""B2B — every sale billed to a customer's GST number, every store (Manav, 23 Nov 2026).

★ THE ASK: "make one b2b also, sales data which has a gst number in the customer GST col". Built like the GRT tab:
one row per BILL (his OK), returns kept as negative rows so totals are net (his OK), HSN-line detail in a second
sheet of the Excel download.

★ THE SOURCE is `<code>_<PR>_Tax_BillWise_FY_01-04-<yyyy>_to_<dd-mm-yyyy>.csv` in each store's DAILY REPORT folder:
one row per bill × HSN code for the financial year so far (BillDate, BillNo, GSTDOCno, CustomerGSTIN, HSNSACCode,
rates, Qty, RtQty, GrossAmt, NetAmt, TaxableAmt, TaxAmt, CGST/SGST/IGST/CESS). Each file REPLACES the year, so only
each store's NEWEST file is read, and a bill is keyed on (store, GST doc no.) — never counted twice. NetAmt =
TaxableAmt + TaxAmt (checked: Grand Kamraj 1 Apr–22 Nov, 66 B2B bills, ₹18,94,217 = ₹16,23,420 + ₹2,70,797).
The file carries NO customer name — only the GSTIN; its first two digits give the buyer's state.

★ READ-ONLY, the same `store-intake@` account as GRT and the alterations tab. A store whose newest file is old or
missing is NAMED on the tab, never silently short.
"""
from __future__ import annotations

import csv
import io

import pandas as pd

import grt as G

COLS = ["Store Name", "Store Code", "Region", "Date", "Bill No", "GST Doc No", "Customer GSTIN", "Customer State",
        "Qty", "Taxable", "CGST", "SGST", "IGST", "Total incl. GST"]
HSN_COLS = ["Store Name", "Store Code", "Date", "Bill No", "GST Doc No", "Customer GSTIN", "HSN", "Tax", "Qty",
            "Taxable", "CGST", "SGST", "IGST", "Total incl. GST"]
MONEY = ["Taxable", "CGST", "SGST", "IGST", "Total incl. GST"]
KIND = "Tax_BillWise_FY"

# GST state codes (the first two digits of a GSTIN) — the states a buyer at our stores is likely to come from.
STATES = {"01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
          "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
          "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
          "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
          "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", "27": "Maharashtra", "29": "Karnataka",
          "30": "Goa", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "36": "Telangana",
          "37": "Andhra Pradesh"}
_LAST_PROBLEM = ""


def last_problem() -> str:
    return _LAST_PROBLEM


def parse(text: str) -> pd.DataFrame:
    """The HSN lines of bills that carry a customer GSTIN."""
    rows = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        gstin = (r.get("CustomerGSTIN") or "").strip().upper()
        d = G._date(r.get("BillDate"))
        if not gstin or d is None:
            continue
        rows.append({"Date": d, "Bill No": (r.get("BillNo") or "").strip(), "GST Doc No": (r.get("GSTDOCno") or "").strip(),
                     "Customer GSTIN": gstin, "HSN": (r.get("HSNSACCode") or "").strip(),
                     "Tax": (r.get("TaxDescription") or "").strip(),
                     "Qty": G._num(r.get("Qty")) - G._num(r.get("RtQty")),
                     "Taxable": G._num(r.get("TaxableAmt")), "CGST": G._num(r.get("CGSTAmt")),
                     "SGST": G._num(r.get("SGSTAmt")), "IGST": G._num(r.get("IGSTAmt")) + G._num(r.get("CESSAmt")),
                     "Total incl. GST": G._num(r.get("NetAmt"))})
    return pd.DataFrame(rows, columns=["Date", "Bill No", "GST Doc No", "Customer GSTIN", "HSN", "Tax", "Qty"] + MONEY)


def _texts(local: str | None):
    """{code: csv text}, {code: export date} — each store's newest Tax_BillWise_FY file."""
    import datetime as dt
    import re
    from pathlib import Path
    texts, meta = {}, {}
    if local:
        import glob
        import os
        paths = {}
        for p in glob.glob(f"{local}/*/*/DAILY*/*/*/*/*{KIND}_*_to_*.csv"):
            m = re.match(r"^(\d+)_.*_to_(\d{2}-\d{2}-\d{4})\.csv$", os.path.basename(p))
            if m:
                code, upto = int(m.group(1)), dt.datetime.strptime(m.group(2), "%d-%m-%Y").date()
                if code not in meta or upto > meta[code]:
                    meta[code], paths[code] = upto, p
        texts = {c: Path(p).read_text(encoding="utf-8-sig", errors="replace") for c, p in paths.items()}
    else:
        import tailoring as TLR
        svc = TLR.drive(TLR.creds_path())
        for code, (_, fid, _, upto) in G.newest_files(svc, KIND).items():
            texts[code] = svc.files().get_media(fileId=fid, supportsAllDrives=True).execute().decode("utf-8-sig", "replace")
            meta[code] = upto
    return texts, meta


def load(local: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(one row per B2B bill, the HSN lines behind them, per-store status)."""
    global _LAST_PROBLEM
    _LAST_PROBLEM = ""
    names = G.stores()
    try:
        texts, meta = _texts(local)
    except Exception as e:
        _LAST_PROBLEM = f"could not read the shared drives: {type(e).__name__}: {e}"
        return pd.DataFrame(columns=COLS), pd.DataFrame(columns=HSN_COLS), pd.DataFrame()
    frames = []
    for code, text in texts.items():
        f = parse(text)
        name, region = names.get(code, (f"Store {code}", ""))
        f.insert(0, "Region", region)
        f.insert(0, "Store Code", code)
        f.insert(0, "Store Name", name)
        frames.append(f)
    lines = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["Store Name", "Store Code", "Region"] + list(parse("").columns))
    keys = ["Store Name", "Store Code", "Region", "Date", "Bill No", "GST Doc No", "Customer GSTIN"]
    bills = lines.groupby(keys, as_index=False, dropna=False)[["Qty"] + MONEY].sum()
    bills = bills.drop_duplicates(subset=["Store Code", "GST Doc No"], keep="last")      # ★ one bill, counted once
    bills["Customer State"] = bills["Customer GSTIN"].str[:2].map(STATES).fillna("")
    bills = bills[COLS].sort_values(["Date", "Store Code", "Bill No"], ascending=[False, True, True]).reset_index(drop=True)
    lines = lines[HSN_COLS].sort_values(["Date", "Store Code", "Bill No", "HSN"],
                                                           ascending=[False, True, True, True]).reset_index(drop=True)
    st = pd.DataFrame([{"Store Code": c, "Store Name": names.get(c, (f"Store {c}", ""))[0],
                        "Region": names.get(c, ("", ""))[1], "Export up to": meta[c]} for c in meta])
    missing = [c for c in names if c not in meta]
    if missing:
        st = pd.concat([st, pd.DataFrame([{"Store Code": c, "Store Name": names[c][0], "Region": names[c][1],
                                           "Export up to": None} for c in missing])], ignore_index=True)
    return bills, lines, st


def by_store(df: pd.DataFrame) -> pd.DataFrame:
    """Store-wise totals, region subtotals and an OVERALL row (house vocabulary)."""
    agg = dict(Bills=("GST Doc No", "nunique"), Customers=("Customer GSTIN", "nunique"), Qty=("Qty", "sum"),
               **{c: (c, "sum") for c in MONEY})
    out = []
    regions = [r for r in ("East & NE", "South") if r in set(df["Region"])] + \
              [r for r in sorted(set(df["Region"])) if r not in ("East & NE", "South")]
    for reg in regions:
        part = df[df["Region"] == reg]
        g = part.groupby(["Store Name", "Store Code"], as_index=False).agg(**agg).sort_values("Total incl. GST", ascending=False)
        out.append(g)
        out.append(pd.DataFrame([{"Store Name": f"{reg.upper()} TOTAL", "Store Code": "", "Bills": part["GST Doc No"].nunique(),
                                  "Customers": part["Customer GSTIN"].nunique(), "Qty": part["Qty"].sum(),
                                  **{c: part[c].sum() for c in MONEY}}]))
    out.append(pd.DataFrame([{"Store Name": "OVERALL", "Store Code": "", "Bills": len(df), "Customers": df["Customer GSTIN"].nunique(),
                              "Qty": df["Qty"].sum(), **{c: df[c].sum() for c in MONEY}}]))
    res = pd.concat(out, ignore_index=True)[["Store Name", "Store Code", "Bills", "Customers", "Qty"] + MONEY]
    res["Store Code"] = res["Store Code"].astype(str)          # total rows carry "" — keep the column one type
    return res


def to_excel(bills: pd.DataFrame, lines: pd.DataFrame, summary: pd.DataFrame) -> bytes:
    """Three sheets — B2B bills (one row a bill), HSN lines, Store totals — numbers as numbers, Indian grouping."""
    buf = io.BytesIO()
    sheets = (("B2B bills", bills.drop(columns=["Region"])), ("HSN lines", lines), ("Store totals", summary))
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        for name, frame in sheets:
            f = frame.copy()
            if "Date" in f:
                f["Date"] = pd.to_datetime(f["Date"])
            f.to_excel(xl, index=False, sheet_name=name)
            ws = xl.sheets[name]
            ws.freeze_panes = "A2"
            for i, c in enumerate(f.columns, 1):
                ws.column_dimensions[ws.cell(1, i).column_letter].width = max(10, min(36, max(len(str(c)) + 4,
                    max((len(str(v)) for v in f[c].head(300)), default=8) + 3)))
                fmt = '#,##,##0.00' if c in MONEY else 'dd-mm-yyyy' if c == "Date" else None
                if fmt:
                    for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                        row[0].number_format = fmt
    return buf.getvalue()


if __name__ == "__main__":                     # python b2b.py — a quick read from the Mac's Drive sync (--api for Drive)
    import os
    import sys
    cs = os.path.expanduser("~/Library/CloudStorage")
    loc = f"{cs}/" + next(p for p in os.listdir(cs) if p.startswith("GoogleDrive")) + "/Shared drives"
    b, l, s = load(local=loc if "--api" not in sys.argv else None)
    print(b.head(8).to_string()); print(len(b), "bills ·", round(b["Total incl. GST"].sum(), 2)); print(s.to_string())
