"""Alteration and parking collections, read out of the store-ops Drive.

Twelve-odd stores keep a workbook each, typed by hand as alterations are
booked. This turns them into one table the dashboard can total.

★ COLUMNS ARE FOUND BY NAME, NEVER BY POSITION. M.G. Road carries an extra
`InHouse or Suhail` column between `Due Paid` and `Total` — one store tracking
whether a job went to an outside tailor. A positional reader would have shifted
every figure after it one column to the left and reported confident nonsense.

★ THE USED RANGE LIES. Both sample files claim 5,063 rows and hold ~610. Rows
are kept only where the date parses.

★ THE `DAY TOTAL` TABS ARE IGNORED. They are human working areas — the
tailoring one interleaves dates with bill numbers and has unrelated credit-note
figures pasted into columns H-L. The detail table is the only source.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from pathlib import Path

import pandas as pd

# The names we insist on, lower-cased and stripped for matching.
NEEDED = ("date", "bill no", "billed amount", "total")
# label in the file -> our column name
KNOWN = {
    "date": "date", "month": "month_no", "bill no": "bill_no",
    "billed amount": "billed", "due amount": "due", "due paid": "due_paid",
    "total": "total", "cash": "cash", "card/upi": "card_upi",
    "inhouse or suhail": "done_by",
}


def _key(v) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


def find_header(ws, limit: int = 60):
    """(row index, {column index: our name}) for the detail table's header.

    Scanned for, not assumed: the summary block above it is twelve months plus
    a Today/Yesterday pair today, and one inserted line would silently move it.
    """
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=limit,
                                         values_only=True), 1):
        keys = {_key(c) for c in row if c is not None}
        if all(n in keys for n in NEEDED):
            cols, unknown = {}, []
            for j, c in enumerate(row):
                k = _key(c)
                if not k:
                    continue
                if k in KNOWN:
                    cols[j] = KNOWN[k]
                else:
                    unknown.append(str(c).strip())
            return i, cols, unknown
    return None, {}, []


def read_workbook(path, store_code, kind, source_id=""):
    """(frame, notes). Every surprise is a note, never an exception."""
    import openpyxl
    notes = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        # The store sheet is whichever one carries the detail header.
        for ws in wb.worksheets:
            hdr, cols, unknown = find_header(ws)
            if hdr:
                break
        else:
            return pd.DataFrame(), [f"{store_code}/{kind}: no detail header found"]
        if unknown:
            notes.append(f"{store_code}/{kind}: extra column(s) {unknown}")
        missing = [n for n in ("cash", "card_upi", "due", "due_paid")
                   if n not in cols.values()]
        if missing:
            notes.append(f"{store_code}/{kind}: no {', '.join(missing)} column")

        out = []
        for row in ws.iter_rows(min_row=hdr + 1, values_only=True):
            rec = {name: row[j] if j < len(row) else None
                   for j, name in cols.items()}
            d = rec.get("date")
            if isinstance(d, str):
                d = pd.to_datetime(d, errors="coerce", dayfirst=False)
            if not isinstance(d, (_dt.datetime, _dt.date, pd.Timestamp)) or pd.isna(d):
                continue                     # summary rows, blanks, stray notes
            rec["date"] = pd.Timestamp(d).normalize()
            out.append(rec)
    finally:
        wb.close()

    f = pd.DataFrame(out)
    if f.empty:
        return f, notes + [f"{store_code}/{kind}: header found but no dated rows"]
    # ★ A COLUMN A STORE DOES NOT KEEP BECOMES ZERO, NOT A CRASH. Silchar's
    # book has no Due columns at all; `f.get(c)` on a missing column returns
    # None, and to_numeric(None) is a bare float with no .fillna.
    for c in ("billed", "due", "due_paid", "total", "cash", "card_upi"):
        f[c] = (pd.to_numeric(f[c], errors="coerce").fillna(0.0)
                if c in f.columns else 0.0)
    f["bill_no"] = (f["bill_no"].astype(str).str.strip()
                    if "bill_no" in f.columns else "")
    f["store_code"] = store_code
    f["kind"] = kind
    f["source_id"] = source_id
    if "done_by" in f.columns:
        f["done_by"] = f["done_by"].astype(str).str.strip().replace("None", "")
    else:
        f["done_by"] = ""
    keep = ["store_code", "kind", "date", "bill_no", "billed", "due", "due_paid",
            "total", "cash", "card_upi", "done_by", "source_id"]
    return f[keep], notes


def check(f: pd.DataFrame) -> list:
    """The identities that hold today. When one breaks, something real happened.

    They are reported, never corrected — a reader who silently repairs a file is
    a reader nobody can reconcile against.
    """
    problems = []
    for (store, kind), part in f.groupby(["store_code", "kind"]):
        tag = f"{store}/{kind}"
        bad = (part["billed"] - part["due"] + part["due_paid"] - part["total"]).abs() > 0.5
        if bad.any():
            problems.append(f"{tag}: {int(bad.sum())} row(s) where "
                            f"Total != Billed - Due + Due Paid")
        split = (part["cash"] + part["card_upi"] - part["total"]).abs() > 0.5
        if split.any():
            problems.append(f"{tag}: {int(split.sum())} row(s) where "
                            f"Cash + Card/Upi != Total")
        dup = part["bill_no"].value_counts()
        dup = dup[(dup > 1) & (dup.index != "")]
        if len(dup):
            problems.append(f"{tag}: {len(dup)} repeated bill number(s), "
                            f"e.g. {list(dup.index[:3])}")
    return problems


def freshness(f: pd.DataFrame, asof=None) -> pd.DataFrame:
    """Per store: when it last recorded anything. The first thing to read —
    a store that stopped typing looks exactly like a store that stopped selling.
    """
    asof = pd.Timestamp(asof or pd.Timestamp.today()).normalize()
    g = (f.groupby(["store_code", "kind"])
           .agg(last_bill=("date", "max"), rows=("date", "size"),
                total=("total", "sum")).reset_index())
    g["days_since"] = (asof - g["last_bill"]).dt.days
    return g.sort_values("days_since")


def by_month(f: pd.DataFrame) -> pd.DataFrame:
    m = f.copy()
    m["month"] = m["date"].values.astype("datetime64[M]")
    return (m.pivot_table(index="store_code", columns="month", values="total",
                          aggfunc="sum", fill_value=0.0))


# --------------------------------------------------------------------------- #
#  Drive — the registry is DERIVED from the folder tree, never typed
# --------------------------------------------------------------------------- #
KEY = os.path.expanduser(os.environ.get(
    "TAILORING_CREDS", "~/.config/store-intake/service-account.json"))
DRIVES = {"0AJeUruqtPn-cUk9PVA": "South", "0ACrnzXaZF1VgUk9PVA": "East & NE"}
OUT = Path("data/tailoring")
FOLDER_MIME = "application/vnd.google-apps.folder"
# `107_PRGK_Grand_Kamraj_Blr` -> code 107, pr PRGK
FOLDER_RE = re.compile(r"^(\d+)[_-]([A-Z]{2,6})?[_-]?(.*)$")
WANTED = ("alter", "tailor", "parking")


def drive(key=None):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        key or KEY, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def children(svc, fid):
    out, tok = [], None
    while True:
        r = svc.files().list(q=f"'{fid}' in parents and trashed = false",
                             includeItemsFromAllDrives=True, supportsAllDrives=True,
                             pageSize=1000, pageToken=tok,
                             fields="nextPageToken, files(id,name,mimeType,modifiedTime)"
                             ).execute()
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            return out


def discover(svc):
    """(sources, loose, folders) — everything the tree says, nothing inferred."""
    sources, loose, folders = [], [], []
    for root, region in DRIVES.items():
        for entry in children(svc, root):
            if entry["mimeType"] != FOLDER_MIME:
                if any(k in entry["name"].lower() for k in WANTED):
                    loose.append({"region": region, **entry})
                continue
            m = FOLDER_RE.match(entry["name"])
            if not m or not m.group(1).isdigit():
                continue                       # `ab_OLD CN from_140626` and friends
            code, pr = int(m.group(1)), (m.group(2) or "")
            folders.append({"region": region, "store_code": code, "pr": pr,
                            "folder": entry["name"]})
            for f in children(svc, entry["id"]):
                low = f["name"].lower()
                if f["mimeType"] == FOLDER_MIME or not any(k in low for k in WANTED):
                    continue
                sources.append({
                    "region": region, "store_code": code, "pr": pr,
                    "folder": entry["name"], "name": f["name"], "id": f["id"],
                    "kind": "parking" if "parking" in low else "alter",
                    "modified": f["modifiedTime"][:10]})
    return sources, loose, folders


def fetch(svc, fid, dest: Path):
    from googleapiclient.http import MediaIoBaseDownload
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = svc.files().get_media(fileId=fid, supportsAllDrives=True)
    with open(dest, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            _status, done = dl.next_chunk()
    return dest




def creds_path() -> str:
    """The service account, from a secret on the Space or a file on his Mac.

    ★ READ-ONLY BY DESIGN. `store-intake@` holds `drive.readonly` and nothing
    else, so this job cannot damage a store's workbook even if it is wrong.
    """
    inline = os.environ.get("TAILORING_CREDS_JSON")
    if inline:
        import tempfile
        p = Path(tempfile.gettempdir()) / "tailoring-sa.json"
        if not p.exists():
            p.write_text(inline)
            p.chmod(0o600)
        return str(p)
    try:
        import streamlit as st
        got = st.secrets.get("TAILORING_CREDS_JSON")
        if got:
            import tempfile
            p = Path(tempfile.gettempdir()) / "tailoring-sa.json"
            p.write_text(got)
            p.chmod(0o600)
            return str(p)
    except Exception:
        pass
    return KEY


_LAST_PROBLEM = ""


def last_problem() -> str:
    return _LAST_PROBLEM


def load(cache_dir="data/tailoring/cache"):
    """(frame, notes, folders, sources). Everything, from Drive, parsed.

    ★ IT NEVER RAISES INTO THE PAGE. A missing key, an unreachable Drive or a
    store that renamed a sheet all come back as a note the tab prints, because
    a report that vanishes teaches nobody anything.
    See [[feedback-silent-failure-must-speak]].
    """
    global _LAST_PROBLEM
    _LAST_PROBLEM = ""
    key = creds_path()
    if not Path(key).exists():
        _LAST_PROBLEM = (f"no Drive credentials — set TAILORING_CREDS_JSON, "
                         f"or put the service-account key at {key}")
        return pd.DataFrame(), [_LAST_PROBLEM], [], []
    try:
        svc = drive(key)
        sources, loose, folders = discover(svc)
    except Exception as e:                       # network, auth, API
        _LAST_PROBLEM = f"could not read Drive ({type(e).__name__}: {e})"
        return pd.DataFrame(), [_LAST_PROBLEM], [], []

    cache = Path(cache_dir)
    notes, parsed = [], {}
    for s in sources:
        local = cache / f"{s['store_code']}_{s['kind']}_{s['id'][:8]}.xlsx"
        try:
            fetch(svc, s["id"], local)
        except Exception as e:
            notes.append(f"{s['store_code']}/{s['kind']}: download failed ({e})")
            continue
        f, n = read_workbook(local, s["store_code"], s["kind"], s["id"])
        notes += n
        parsed.setdefault((s["store_code"], s["kind"]), []).append((s, f))

    frames = []
    for (code, kind), cands in parsed.items():
        if len(cands) > 1:
            # ★ LATEST DATA WINS, NOT LATEST TIMESTAMP (Manav, 23 Sep). Opening
            # a file to look at it updates its mtime; only the bills inside say
            # which copy a store is actually working in.
            cands.sort(key=lambda c: (c[1]["date"].max() if not c[1].empty
                                      else pd.Timestamp.min), reverse=True)
            kept = cands[0]
            when = (f"{kept[1]['date'].max():%d %b}" if not kept[1].empty else "no bills")
            notes.append(f"{code}/{kind}: {len(cands)} candidate files — kept "
                         f"'{kept[0]['name']}' (latest bill {when}), ignored "
                         + ", ".join(f"'{d[0]['name']}'" for d in cands[1:]))
            cands = [kept]
        if not cands[0][1].empty:
            frames.append(cands[0][1])

    for l in loose:
        notes.append(f"'{l['name']}' sits loose at the {l['region']} drive root, "
                     f"outside any store folder — not read")

    data = (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
    return data, notes, folders, sources


def store_names(folders) -> dict:
    """`107_PRGK_Grand_Kamraj_Blr` -> `Grand Kamraj`. The folder is the master."""
    out = {}
    for f in folders:
        parts = str(f["folder"]).split("_")
        label = " ".join(parts[2:]) if len(parts) > 2 else f["folder"]
        label = re.sub(r"\s*(Blr|KOL|SLG|GHY)\s*$", "", label, flags=re.I).strip()
        out[f["store_code"]] = label.replace("_", " ") or str(f["store_code"])
    return out
