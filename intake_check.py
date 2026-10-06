"""Intake vs Tableau: what the store managers typed at night, against the till.

Manav, 6 Oct 2026: *"when we update the vfl tableau sheet, i want a simple tab in vfl
comparing the sales intake given by the managers and the sales from tableau to see if
there is a difference, this will help us compare and correct managers."*

★ TABLEAU IS THE SOURCE OF TRUTH. The VFL feed's bill lines for the day (its own
`Bill Amount`, distinct bills, `_units`, and the brand split read exactly as the night
SMS reads it). A difference is always reported as typed minus Tableau, so a positive
number means the manager over-reported.

★ ONLY SETTLED DAYS. A provisional row is built from Peanuts Total, not from Tableau,
and comparing a store against a figure derived from its own report proves nothing.
Those rows are left out; a day with no Tableau bills yet says so.

★ THE LATEST FILING WINS, as everywhere else the form is read: re-filing is how a
manager corrects a mistake, so the newest submission for a store-day is the one held
to account.

★ A WRONG DATE IS CAUGHT, NOT JUST COUNTED. Jayanagar's first filing (3 Oct) carried
3 October's figures under the date 26 September. When a filing does not match Tableau
on its own date, every other day within ten days is tried; an exact match on another
day is reported as "probably meant <date>", which is the correction the manager needs.
"""
from __future__ import annotations

import pandas as pd

import intake_brands as IB

FIELDS = [  # key, form column names, label
    ("sales", ("DAY SALES", "TOTAL SALES", "SALES"), "Day sales"),
    ("manyavar", ("MANYAVAR SALES", "MANYAVAR"), "Manyavar"),
    ("mohey", ("MOHEY SALES", "MOHEY"), "Mohey"),
    ("twamev", ("TWAMEV SALES", "TWAMEV"), "Twamev"),
    ("bills", ("BILLS", "BILL COUNT", "NO OF BILLS"), "Bills"),
    ("units", ("QUANTITY SOLD", "QUANTITY", "QTY", "PIECES"), "Pieces"),
]
MONEY = ("sales", "manyavar", "mohey", "twamev")
TOLERANCE = {"sales": 5.0, "manyavar": 5.0, "mohey": 5.0, "twamev": 5.0, "bills": 0.0, "units": 0.0}
TYPO_WINDOW = 10   # days either side of the filing to look for the day it really describes


def filings(responses: pd.DataFrame, mails: dict) -> pd.DataFrame:
    """One row per store-day: the latest filing, every figure it carries."""
    if responses is None or not len(responses) or not mails:
        return pd.DataFrame()
    d = responses.copy()
    ts_c = IB._find(d.columns, ("TIMESTAMP",)) or d.columns[0]
    em_c = IB._find(d.columns, ("EMAIL ADDRESS", "EMAIL"))
    dt_c = IB._find(d.columns, ("DATE",))
    if em_c is None:
        return pd.DataFrame()
    d["filed_at"] = pd.to_datetime(d[ts_c].astype(str).str.replace(IB._TZ_SUFFIX, "", regex=True),
                                   errors="coerce")
    d["code"] = d[em_c].astype(str).str.strip().str.lower().map(mails)
    d["date"] = d.apply(lambda r: IB._read_date(r.get(dt_c), r["filed_at"]), axis=1)
    d["typed_date"] = d[dt_c].astype(str) if dt_c else ""
    d = d[d["code"].notna() & d["date"].notna()].copy()
    if not len(d):
        return pd.DataFrame()
    for key, names, _ in FIELDS:
        col = IB._find(responses.columns, names)
        # `_find` matches by substring too, so "MANYAVAR SALES" must not be read as "SALES"
        if key == "sales" and col is not None and any(b in str(col).upper() for b in ("MANYAVAR", "MOHEY", "TWAMEV")):
            col = next((c for c in responses.columns if str(c).strip().upper() in names), None)
        d[key] = d[col].map(IB._num) if col is not None else None
    d["_row"] = range(len(d))
    d = d.sort_values(["filed_at", "_row"], na_position="first")
    d = d.drop_duplicates(subset=["code", "date"], keep="last")
    d["code"] = d["code"].astype(int)
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    return d[["code", "date", "filed_at", "typed_date"] + [k for k, _, _ in FIELDS]].reset_index(drop=True)


def tableau(vfl: pd.DataFrame, L) -> pd.DataFrame:
    """One row per store-day from the settled VFL feed: the same six figures."""
    if vfl is None or not len(vfl):
        return pd.DataFrame()
    f = vfl
    if "_provisional" in f.columns:
        f = f[~f["_provisional"].astype(bool)]
    f = f.copy()
    f["_b"] = L.brand_line_vfl(f).map({"MANYAVAR": "manyavar", "MOHEY": "mohey",
                                        "TWAMEV MEN": "twamev", "TWAMEV-WOMEN": "twamev"})
    master = L.load_store_master()[["tableau_name", "code"]].dropna()
    master["code"] = pd.to_numeric(master["code"], errors="coerce")
    f = f.merge(master.dropna(), left_on=L.COL_STORE_LABEL, right_on="tableau_name", how="left")
    f = f[f["code"].notna()]
    f["code"] = f["code"].astype(int)
    g = f.groupby(["code", "date"])
    out = pd.DataFrame({
        "sales": g[L.COL_AMOUNT].sum(),
        "bills": g[L.COL_BILL_UID].nunique(),
        "units": g[L.COL_UNITS].sum() if L.COL_UNITS in f.columns else g[L.COL_QTY].sum(),
    })
    br = f.pivot_table(index=["code", "date"], columns="_b", values=L.COL_AMOUNT, aggfunc="sum")
    for b in ("manyavar", "mohey", "twamev"):
        out[b] = br[b] if b in br.columns else 0.0
    out = out.fillna(0.0).reset_index()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    return out


def _status(diffs: dict) -> str:
    bad = [k for k, v in diffs.items() if v is not None and abs(v) > TOLERANCE[k]]
    return "Matches" if not bad else "Differs"


def compare(day, fil: pd.DataFrame, tab: pd.DataFrame, names: dict) -> pd.DataFrame:
    """One row per store for `day`: typed, Tableau, difference, and a verdict.

    Stores with Tableau sales but no filing are listed as "Not filed"; a filing for a day
    Tableau has not reached yet is "Waiting for Tableau".
    """
    day = pd.Timestamp(day).normalize()
    t_day = tab[tab["date"] == day].set_index("code") if len(tab) else pd.DataFrame()
    f_day = fil[fil["date"] == day].set_index("code") if len(fil) else pd.DataFrame()
    codes = sorted(set(t_day.index) | set(f_day.index))
    rows = []
    for c in codes:
        r = {"code": int(c), "store": names.get(int(c), str(c))}
        has_t = c in t_day.index and t_day.loc[c, "sales"] != 0
        has_f = c in f_day.index
        if has_f:
            r["filed_at"] = f_day.loc[c, "filed_at"]
        for key, _, _ in FIELDS:
            typed = f_day.loc[c, key] if has_f else None
            truth = float(t_day.loc[c, key]) if c in t_day.index else None
            r[f"{key}_typed"] = None if typed is None or pd.isna(typed) else float(typed)
            r[f"{key}_tableau"] = truth
            r[f"{key}_diff"] = (r[f"{key}_typed"] - truth
                                if r[f"{key}_typed"] is not None and truth is not None else None)
        if has_f and not has_t:
            r["status"] = "Waiting for Tableau"
        elif not has_f:
            r["status"] = "Not filed"
        else:
            r["status"] = _status({k: r[f"{k}_diff"] for k, _, _ in FIELDS})
        r["hint"] = ""
        if r["status"] == "Differs" and r.get("sales_typed"):
            r["hint"] = typo_hint(c, day, r["sales_typed"], tab)
        rows.append(r)
    order = {"Differs": 0, "Not filed": 1, "Waiting for Tableau": 2, "Matches": 3}
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(["status", "code"], key=lambda s: s.map(order) if s.name == "status" else s)
    return out.reset_index(drop=True)


def typo_hint(code, day, typed_sales, tab) -> str:
    """'probably meant 3 Oct' when the typed total is Tableau's for another nearby day."""
    if typed_sales is None or not len(tab):
        return ""
    mine = tab[(tab["code"] == code) & (tab["date"] != day)
               & ((tab["date"] - day).abs() <= pd.Timedelta(days=TYPO_WINDOW))]
    hit = mine[(mine["sales"] - typed_sales).abs() <= TOLERANCE["sales"]]
    if len(hit):
        return f"These figures are Tableau's for {hit['date'].iloc[0]:%d %b}: date probably typed wrong"
    return ""


def track_record(fil: pd.DataFrame, tab: pd.DataFrame, names: dict, since, until) -> pd.DataFrame:
    """Per store over a window: filings, how many matched, and the typical sales gap."""
    since, until = pd.Timestamp(since).normalize(), pd.Timestamp(until).normalize()
    if not len(fil):
        return pd.DataFrame()
    f = fil[(fil["date"] >= since) & (fil["date"] <= until)]
    t = tab.set_index(["code", "date"]) if len(tab) else pd.DataFrame()
    rows = []
    for c, part in f.groupby("code"):
        checked = matched = 0
        gaps = []
        for _, r in part.iterrows():
            if (c, r["date"]) not in t.index:
                continue
            truth = t.loc[(c, r["date"])]
            diffs = {k: (r[k] - truth[k]) if r[k] is not None and not pd.isna(r[k]) else None
                     for k, _, _ in FIELDS}
            checked += 1
            matched += _status(diffs) == "Matches"
            if diffs["sales"] is not None:
                gaps.append(abs(diffs["sales"]))
        rows.append({"code": int(c), "store": names.get(int(c), str(c)), "filings": len(part),
                     "checked": checked, "matched": matched,
                     "match_rate": (matched / checked * 100) if checked else None,
                     "typical_gap": (pd.Series(gaps).median() if gaps else None)})
    return pd.DataFrame(rows).sort_values("store").reset_index(drop=True) if rows else pd.DataFrame()


EXPECT_DAYS = 14   # a store that has filed within this many days is expected to file every night


def expected(fil: pd.DataFrame, day) -> set:
    """Stores on the form: filed at least once in the EXPECT_DAYS before `day` (or on it)."""
    day = pd.Timestamp(day).normalize()
    if not len(fil):
        return set()
    w = fil[(fil["date"] <= day) & (fil["date"] > day - pd.Timedelta(days=EXPECT_DAYS))]
    return set(int(c) for c in w["code"])
