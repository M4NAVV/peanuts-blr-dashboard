"""Fetch every store's alteration/parking workbook and build one table.

★ THE REGISTRY IS DERIVED FROM THE FOLDER TREE, NOT TYPED. Store folders are
named `107_PRGK_Grand_Kamraj_Blr` — the store code is right there, and it
matches the dashboard's own master. A store added tomorrow is picked up with no
edit here; a file renamed changes nothing, because files are read by Drive ID.

★ FILES LOOSE AT A DRIVE ROOT ARE REPORTED, NEVER GUESSED AT. Two sit outside
any store folder today (a stray `Alter_PRFF` in the SOUTH drive, and
`Alter_PRSG` never filed). Including them would invent an attribution; dropping
them silently would hide a store.

Run:  ./venv/bin/python scripts_tailoring.py      (needs google-api-python-client)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd

import tailoring as T

KEY = os.path.expanduser(os.environ.get(
    "TAILORING_CREDS", "~/.config/store-intake/service-account.json"))
DRIVES = {"0AJeUruqtPn-cUk9PVA": "South", "0ACrnzXaZF1VgUk9PVA": "East & NE"}
OUT = Path("data/tailoring")
FOLDER_MIME = "application/vnd.google-apps.folder"
# `107_PRGK_Grand_Kamraj_Blr` -> code 107, pr PRGK
FOLDER_RE = re.compile(r"^(\d+)[_-]([A-Z]{2,6})?[_-]?(.*)$")
WANTED = ("alter", "tailor", "parking")


def drive():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        KEY, scopes=["https://www.googleapis.com/auth/drive.readonly"])
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


def main():
    svc = drive()
    sources, loose, folders = discover(svc)
    OUT.mkdir(parents=True, exist_ok=True)

    frames, notes = [], []
    # ★ A STORE WITH TWO CANDIDATE FILES KEEPS THE ONE WITH THE LATEST DATA,
    # not the newest timestamp (Manav, 23 Sep). Jayanagar has both
    # `ALTER_PRJN JN` and `Copy of ALTER_PRJN`, modified the same day — opening
    # a file to look at it changes its timestamp, so mtime cannot decide this.
    parsed = {}
    for s in sources:
        local = OUT / "cache" / f"{s['store_code']}_{s['kind']}_{s['id'][:8]}.xlsx"
        fetch(svc, s["id"], local)
        f, n = T.read_workbook(local, s["store_code"], s["kind"], s["id"])
        notes += n
        parsed.setdefault((s["store_code"], s["kind"]), []).append((s, f))

    for (code, kind), cands in parsed.items():
        if len(cands) > 1:
            cands.sort(key=lambda c: (c[1]["date"].max() if not c[1].empty
                                      else pd.Timestamp.min), reverse=True)
            kept, dropped = cands[0], cands[1:]
            notes.append(
                f"{code}/{kind}: {len(cands)} candidate files — kept "
                f"'{kept[0]['name']}' (latest bill "
                f"{kept[1]['date'].max():%d %b}), ignored "
                + ", ".join(f"'{d[0]['name']}'" for d in dropped))
            cands = [kept]
        frames.append(cands[0][1])

    if loose:
        for l in loose:
            notes.append(f"LOOSE at the {l['region']} drive root, not in any "
                         f"store folder: '{l['name']}' — not read")

    data = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    data.to_csv(OUT / "tailoring_lines.csv", index=False)
    pd.DataFrame(folders).to_csv(OUT / "store_folders.csv", index=False)
    return data, notes, folders, sources


if __name__ == "__main__":
    data, notes, folders, sources = main()
    print(f"{len(sources)} files across {len(folders)} store folders -> "
          f"{len(data):,} rows\n")
    for n in notes:
        print("  ·", n)
