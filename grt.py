"""GRT — goods returned to VFL, every store, from the stores' own nightly POS export (Manav, 19 Nov 2026).

★ THE ASK: "Store Name | Store Code | GST Doc No | Qty | Value … downloadable … in excel just like VFL sheet or
peanutstotal sheet … daily data to be automatically updated based on the updated reports in the drive folders".
Dashboard tab only (no workbook tab); Value = the GRT invoice total INCLUDING GST.

★ THE SOURCE is `<code>_<PR>_GoodsReturn_FY_01-04-<yyyy>_to_<dd-mm-yyyy>.csv`, which every store's POS writes into its
`DAILY REPORT_<code>/…/<MM>/<DD>/` folder each night: one row per GRT for the financial year so far
(DocDate, GSTDOCno, DocNo, ReturnQty, TaxAmt, GrossAmt, CGST/SGST/IGST). Each night's file REPLACES the year, so
only each store's NEWEST file is read, and a GRT is keyed on its GST doc no. — never counted twice. The GRT PDFs
(item, ship-to store) are uploaded by only a few stores, so they are not the source. GrossAmt = the invoice's Grand
Total (GRT-426, Fairfield: ₹1,150.42).

★ READ-ONLY. Same `store-intake@` service account as the alterations tab (tailoring.drive / creds_path).

★ A STORE WHOSE NEWEST FILE IS OLD IS NAMED, never silently short: `status()` gives each store's newest export date.
"""
from __future__ import annotations

import datetime as dt
import io
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
COLS = ["Store Name", "Store Code", "Region", "Date", "GST Doc No", "GRT No", "Qty", "Value"]
_LAST_PROBLEM = ""


def last_problem() -> str:
    return _LAST_PROBLEM


def _date(s) -> dt.date | None:
    s = str(s or "").strip().split(" ")[0]
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%b-%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _num(x) -> float:
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return 0.0


def stores() -> dict:
    """{code: (name, region)} from store_master.csv, the same names as every other tab."""
    m = pd.read_csv(HERE / "store_master.csv", dtype={"code": str})
    out = {}
    for _, r in m.iterrows():
        loc, city = str(r["location"]), str(r["city"]).title()
        out[int(r["code"])] = (loc if loc.lower() == city.lower() else f"{loc}, {city}", r["region"])
    dup = {n for n, _ in out.values() if sum(1 for x, _ in out.values() if x == n) > 1}
    return {c: ((f"{n} ({c})" if n in dup else n), reg) for c, (n, reg) in out.items()}


def parse(text: str) -> pd.DataFrame:
    import csv
    rows = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        d = _date(r.get("DocDate"))
        doc = (r.get("GSTDOCno") or "").strip()
        if d is None or not doc:
            continue
        rows.append({"Date": d, "GST Doc No": doc, "GRT No": (r.get("DocNo") or "").strip(),
                     "Qty": _num(r.get("ReturnQty")), "Value": _num(r.get("GrossAmt"))})
    return pd.DataFrame(rows, columns=["Date", "GST Doc No", "GRT No", "Qty", "Value"])


def newest_files(svc) -> dict:
    """{code: (modifiedTime, id, name, export_date)} — each store's newest GoodsReturn_FY file on the shared drives."""
    out, tok = {}, None
    while True:
        r = svc.files().list(q="name contains 'GoodsReturn_FY_' and trashed = false", corpora="allDrives",
                             includeItemsFromAllDrives=True, supportsAllDrives=True, pageSize=1000, pageToken=tok,
                             fields="nextPageToken, files(id,name,modifiedTime)").execute()
        for f in r.get("files", []):
            m = re.match(r"^(\d+)_.*GoodsReturn_FY_.*_to_(\d{2}-\d{2}-\d{4})\.csv$", f["name"])
            if not m:
                continue
            code, upto = int(m.group(1)), dt.datetime.strptime(m.group(2), "%d-%m-%Y").date()
            if code not in out or (upto, f["modifiedTime"]) > (out[code][3], out[code][0]):
                out[code] = (f["modifiedTime"], f["id"], f["name"], upto)
        tok = r.get("nextPageToken")
        if not tok:
            return out


def load(local: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(grt rows, per-store status). `local` = the Mac's 'Shared drives' folder, for testing without the API."""
    global _LAST_PROBLEM
    _LAST_PROBLEM = ""
    names = stores()
    texts, meta = {}, {}
    try:
        if local:
            import glob, os
            for p in glob.glob(f"{local}/*/*/DAILY*/*/*/*/*GoodsReturn_FY_*_to_*.csv"):
                m = re.match(r"^(\d+)_.*_to_(\d{2}-\d{2}-\d{4})\.csv$", os.path.basename(p))
                if m:
                    code, upto = int(m.group(1)), dt.datetime.strptime(m.group(2), "%d-%m-%Y").date()
                    if code not in meta or upto > meta[code]:
                        meta[code], texts[code] = upto, p
            texts = {c: Path(p).read_text(encoding="utf-8-sig", errors="replace") for c, p in texts.items()}
        else:
            import tailoring as TLR
            svc = TLR.drive(TLR.creds_path())
            for code, (_, fid, _, upto) in newest_files(svc).items():
                texts[code] = svc.files().get_media(fileId=fid, supportsAllDrives=True).execute().decode("utf-8-sig", "replace")
                meta[code] = upto
    except Exception as e:
        _LAST_PROBLEM = f"could not read the shared drives: {type(e).__name__}: {e}"
        return pd.DataFrame(columns=COLS), pd.DataFrame()
    frames = []
    for code, text in texts.items():
        f = parse(text)
        name, region = names.get(code, (f"Store {code}", ""))
        f.insert(0, "Region", region)
        f.insert(0, "Store Code", code)
        f.insert(0, "Store Name", name)
        frames.append(f)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLS)
    df = df.drop_duplicates(subset=["GST Doc No"], keep="last")[COLS]          # ★ one GRT, counted once
    df = df.sort_values(["Date", "Store Code", "GRT No"], ascending=[False, True, True]).reset_index(drop=True)
    st = pd.DataFrame([{"Store Code": c, "Store Name": names.get(c, (f"Store {c}", ""))[0],
                        "Region": names.get(c, ("", ""))[1], "Export up to": meta[c]} for c in meta])
    missing = [c for c in names if c not in meta]
    if missing:
        st = pd.concat([st, pd.DataFrame([{"Store Code": c, "Store Name": names[c][0], "Region": names[c][1],
                                           "Export up to": None} for c in missing])], ignore_index=True)
    return df, st


def by_store(df: pd.DataFrame) -> pd.DataFrame:
    """Store-wise totals for a filtered frame, region subtotals and an OVERALL row (house vocabulary)."""
    out = []
    for reg in [r for r in ("East & NE", "South") if r in set(df["Region"])] + \
               [r for r in sorted(set(df["Region"])) if r not in ("East & NE", "South")]:
        g = df[df["Region"] == reg].groupby(["Store Name", "Store Code"], as_index=False).agg(
            GRTs=("GST Doc No", "nunique"), Qty=("Qty", "sum"), Value=("Value", "sum")).sort_values("Value", ascending=False)
        out.append(g.assign(Region=reg))
        out.append(pd.DataFrame([{"Store Name": f"{reg.upper()} TOTAL", "Store Code": "", "Region": reg,
                                  "GRTs": g["GRTs"].sum(), "Qty": g["Qty"].sum(), "Value": g["Value"].sum()}]))
    out.append(pd.DataFrame([{"Store Name": "OVERALL", "Store Code": "", "Region": "", "GRTs": df["GST Doc No"].nunique(),
                              "Qty": df["Qty"].sum(), "Value": df["Value"].sum()}]))
    return pd.concat(out, ignore_index=True)[["Store Name", "Store Code", "Region", "GRTs", "Qty", "Value"]]


def to_excel(detail: pd.DataFrame, summary: pd.DataFrame, title: str) -> bytes:
    """Two sheets — GRT (one row per GRT, the asked-for columns) and Store totals — numbers as numbers."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        d = detail.copy()
        d["Date"] = pd.to_datetime(d["Date"])
        d.to_excel(xl, index=False, sheet_name="GRT")
        summary.to_excel(xl, index=False, sheet_name="Store totals")
        for name, frame in (("GRT", d), ("Store totals", summary)):
            ws = xl.sheets[name]
            ws.freeze_panes = "A2"
            for i, c in enumerate(frame.columns, 1):
                ws.column_dimensions[ws.cell(1, i).column_letter].width = max(10, min(36, len(str(c)) + 4,
                    max((len(str(v)) for v in frame[c].head(300)), default=8) + 3))
                if c == "Value":
                    for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                        row[0].number_format = '#,##,##0.00'
                if c == "Date":
                    for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                        row[0].number_format = 'dd-mm-yyyy'
    return buf.getvalue()


if __name__ == "__main__":                     # python grt.py  — a quick read from the Mac's Drive sync
    import os, sys
    loc = os.path.expanduser("~/Library/CloudStorage/") + next(p for p in os.listdir(os.path.expanduser("~/Library/CloudStorage"))
                                                              if p.startswith("GoogleDrive")) + "/Shared drives"
    df, st = load(local=loc if "--api" not in sys.argv else None)
    print(df.head(8).to_string()); print(len(df), "GRTs ·", df["Value"].sum()); print(st.to_string())
