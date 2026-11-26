"""Stores page — is every store's PC sending its files? (Manav, 23 Nov 2026: the Store Data Agent's head-office view.)

For every store in store_master.csv, read from the shared drives (store-intake@, read-only):
  · HOURLY: today's `<code>_..._Sales_Items_Day_<dd-mm-yyyy>.csv` — when it was last written.
  · CLOSE: the newest `<code>_..._DrawerSummary_<date>.csv` — which day was last exported at close, and when.
  · AGENT: `_agent/status.json` (or `AGENTTEST_status.json` while piloting) written by the Store Data Agent —
    version, last check-in, database / Drive reachable, last error. Absent = the store still runs GDE v6 only.
Works today for every store (the v6 files), and fills in the agent columns as stores move to the agent.
Files whose names do not start with a store number (the pilot's AGENTTEST_ files) are never counted as v6 files.
"""
from __future__ import annotations

import datetime as dt
import json
import re

import pandas as pd

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _list(svc, q: str, fields: str = "files(id,name,modifiedTime)") -> list[dict]:
    out, tok = [], None
    while True:
        r = svc.files().list(q=q, corpora="allDrives", includeItemsFromAllDrives=True, supportsAllDrives=True,
                             pageSize=1000, pageToken=tok, fields=f"nextPageToken, {fields}").execute()
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            return out


def _ist(t: str) -> dt.datetime:
    return dt.datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(IST)


def load(now: dt.datetime | None = None) -> tuple[pd.DataFrame, str]:
    """(one row per store, problem text or '')."""
    import grt as G
    import tailoring as TLR
    now = now or dt.datetime.now(IST)
    today, yday = now.date(), now.date() - dt.timedelta(days=1)
    names = G.stores()
    try:
        svc = TLR.drive(TLR.creds_path())
        hourly = _list(svc, f"name contains 'Sales_Items_Day_{today:%d-%m-%Y}' and trashed = false")
        since = (now - dt.timedelta(days=10)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        close = _list(svc, f"name contains 'DrawerSummary_' and modifiedTime > '{since}' and trashed = false")
        status = _list(svc, "name contains 'status.json' and trashed = false")
    except Exception as e:                                           # the page must say why, never go blank
        return pd.DataFrame(), f"could not read the shared drives: {type(e).__name__}: {e}"

    h = {}
    for f in hourly:
        m = re.match(r"^(\d+)_", f["name"])
        if m:
            c, t = int(m.group(1)), _ist(f["modifiedTime"])
            h[c] = max(h.get(c, t), t)
    cl = {}
    for f in close:
        m = re.match(r"^(\d+)_.*_DrawerSummary_(\d{2}-\d{2}-\d{4})\.csv$", f["name"])
        if m:
            c, d, t = int(m.group(1)), dt.datetime.strptime(m.group(2), "%d-%m-%Y").date(), _ist(f["modifiedTime"])
            if c not in cl or (d, t) > cl[c]:
                cl[c] = (d, t)
    ag = {}
    for f in status:
        if not re.match(r"^(AGENTTEST_)?status\.json$", f["name"]):
            continue
        try:
            s = json.loads(svc.files().get_media(fileId=f["id"], supportsAllDrives=True).execute())
            c = int(str(s.get("store", "")).split("_")[0])
            s["_pilot_file"] = f["name"].startswith("AGENTTEST_")
            if c not in ag or s.get("at", "") > ag[c].get("at", ""):
                ag[c] = s
        except Exception:
            continue

    try:                                     # the storemaster's closure dates, as the hourly WhatsApp uses them
        import portfolio_loader as PL
        shut = {int(c): d for c, d in PL.closed_map().items() if str(c).isdigit()}
    except Exception:
        shut = {}
    rows = []
    for code, (name, region) in names.items():
        sd = shut.get(code)
        if sd is not None and pd.Timestamp(sd).date() <= today:
            rows.append({"Store": name, "Code": code, "Region": region, "Exports by": "—", "Hourly file today": "—",
                         "Last close exported": "—", "Agent check-in": "", "Agent last error": "",
                         "Status": f"closed {pd.Timestamp(sd):%d %b %Y} (storemaster)"})
            continue
        last_h = h.get(code)
        last_c = cl.get(code)
        a = ag.get(code)
        issues = []
        if 12 <= now.hour <= 23:
            if not last_h:
                issues.append("no hourly file yet today (no bill yet, or the export is not running)")
            elif now - last_h > dt.timedelta(minutes=80):
                issues.append(f"hourly file {int((now - last_h).total_seconds() // 60)} min old")
        if now.hour >= 10 and (not last_c or last_c[0] < yday):
            issues.append("yesterday's close not exported")
        if a:
            at = dt.datetime.fromisoformat(a["at"]).astimezone(IST)
            if 11 <= now.hour <= 21 and now - at > dt.timedelta(minutes=20):   # store PCs sleep after close
                issues.append(f"agent silent {int((now - at).total_seconds() // 60)} min")
            if not a.get("db_ok"):
                issues.append("agent cannot read the POS")
            if not a.get("drive_ok"):
                issues.append("agent cannot reach Drive")
        rows.append({
            "Store": name, "Code": code, "Region": region,
            "Exports by": (f"Agent {a.get('version')}" + (" (pilot)" if a.get("pilot") else "")) if a else "GDE v6",
            "Hourly file today": last_h.strftime("%H:%M") if last_h else "—",
            "Last close exported": f"{last_c[0]:%d %b} at {last_c[1]:%H:%M}" if last_c else "—",
            "Agent check-in": dt.datetime.fromisoformat(a["at"]).astimezone(IST).strftime("%d %b %H:%M") if a else "",
            "Agent last error": (a.get("last_error") or "") if a else "",
            "Status": "OK" if not issues else "; ".join(issues),
        })
    df = pd.DataFrame(rows)
    df["_bad"] = ~df["Status"].str.startswith(("OK", "closed"))
    df = df.sort_values(["_bad", "Region", "Store"], ascending=[False, True, True]).drop(columns="_bad")
    return df.reset_index(drop=True), ""


if __name__ == "__main__":
    d, p = load()
    print(p or d.to_string())
