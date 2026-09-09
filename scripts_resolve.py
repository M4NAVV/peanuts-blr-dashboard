#!/usr/bin/env python
"""One-off: match each store to its own Google listing, by its CONFIRMED coordinate.

★ PROXIMITY, NOT NAME. A text search for "Manyavar Kamraj Road" returns the same
listing for two different stores 71 m apart. The store master's own Maps links
give an exact coordinate per store, so the listing is chosen by distance.

★ AND IT REFUSES WHERE IT CANNOT TELL. Two stores whose nearest listing is the
same listing are BOTH left out, because attributing one shop's reviews to
another is worse than having no figure for either.
"""
import math, os, re, sys, urllib.parse, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, requests, google_reviews as G, loader as L

def coords(u):
    if not isinstance(u, str): return (None, None)
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", urllib.parse.unquote(u))
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)

def metres(a, b, c, d):
    return math.dist((a * 111320, b * 111320 * math.cos(math.radians(a))),
                     (c * 111320, d * 111320 * math.cos(math.radians(c))))

def listings(lat, lng, r=250.0):
    resp = requests.post(
        f"{G.BASE}/places:searchNearby",
        headers={"X-Goog-Api-Key": G._key(), "X-Goog-FieldMask": G._FIELDS,
                 "Content-Type": "application/json"},
        json={"maxResultCount": 20, "includedTypes": ["clothing_store"],
              "locationRestriction": {"circle": {
                  "center": {"latitude": lat, "longitude": lng}, "radius": r}}},
        timeout=60)
    resp.raise_for_status()
    return [h for h in resp.json().get("places", [])
            if any(w in (h.get("displayName", {}) or {}).get("text", "").lower()
                   for w in ("manyavar", "mohey"))]

sm = pd.read_excel("/tmp/mv_sheet.xlsx", sheet_name="storemaster")
sm["code"] = sm["STORE CODE"].astype(str).str.strip()
sm["lat"], sm["lng"] = zip(*sm["LOCATION.1"].map(coords))
mine = L.load_store_master(); mine["code"] = mine["code"].astype(str).str.strip()
j = mine.merge(sm[["code", "lat", "lng"]], on="code", how="left")

rows, unresolved = [], []
for _, s in j.iterrows():
    if pd.isna(s.lat):
        unresolved.append((s.tableau_name, "no map link in the store master")); continue
    hits = listings(s.lat, s.lng)
    if not hits:
        unresolved.append((s.tableau_name, "no Manyavar/Mohey listing within 250 m")); continue
    best = min(hits, key=lambda h: metres(s.lat, s.lng,
                                          h["location"]["latitude"], h["location"]["longitude"]))
    rows.append({"store_code": s.code, "store": s.tableau_name,
                 "place_id": best["id"],
                 "google_name": best.get("displayName", {}).get("text"),
                 "distance_m": round(metres(s.lat, s.lng, best["location"]["latitude"],
                                            best["location"]["longitude"])),
                 "reviews_at_match": best.get("userRatingCount"),
                 "lat": s.lat, "lng": s.lng})

d = pd.DataFrame(rows)

# ★ CROSS-CHECK AGAINST THE TEAM'S OWN COUNT. A listing whose ENTIRE review
# history is smaller than the reviews that store is recorded as taking this year
# cannot be that store. Dibrugarh matched a neighbouring "Vastra | Manyavar"
# with 11 reviews total against 172 logged this year — plausible-looking, 80 m
# away, and wrong.
try:
    import reviews as RV
    manual = RV.load(RV.manual_paths())
    if manual is not None and not manual.empty:
        ytd = manual.groupby("store")["day_review"].sum()
        bad = [r.store for r in d.itertuples()
               if r.store in ytd.index
               and pd.notna(r.reviews_at_match)
               and r.reviews_at_match < ytd[r.store]]
        for n in bad:
            got = int(d.loc[d.store == n, "reviews_at_match"].iloc[0])
            unresolved.append(
                (n, f"listing has {got} reviews in total but {int(ytd[n])} were "
                    f"logged this year — cannot be this store"))
        d = d[~d.store.isin(bad)]
except Exception as e:                    # noqa: BLE001 - the check is a bonus
    print(f"(cross-check skipped: {type(e).__name__})")

dup = d[d.duplicated("place_id", keep=False)]
if len(dup):
    for pid, g in dup.groupby("place_id"):
        names = ", ".join(g.store)
        for n in g.store:
            unresolved.append((n, f"shares one Google listing with {names}"))
    d = d[~d.place_id.isin(dup.place_id)]

d.to_csv(G.PLACES_CSV, index=False)
pd.set_option("display.width", 200)
print("RESOLVED — one store, one listing:")
print(d[["store", "google_name", "distance_m", "reviews_at_match"]].to_string(index=False))
print(f"\n{len(d)} of {len(j)} stores resolved")
print("\nNOT RESOLVED — deliberately left out rather than guessed:")
for n, why in unresolved:
    print(f"   {n:20} {why}")
