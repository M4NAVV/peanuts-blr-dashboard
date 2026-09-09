"""Each store's Google review count, read once a day, with no typing.

★ WHY A RUNNING TOTAL AND NOT A LIST OF REVIEWS. Google has no way to ask "how
many reviews did this store get on 15 August". The API returns a running total
and, at most, the five newest reviews with vague stamps like "2 weeks ago".
Nobody can pull a dated review history.

So the count is DERIVED: record each store's running total once a day, and the
difference against the previous reading is that day's reviews. That is the same
figure the team has been typing by hand, obtained without anyone typing it.

★ WHAT THIS GIVES UP, stated because it will not be obvious from the numbers:

  · NET, NOT GROSS. A day that gained three reviews and lost one reads as +2.
    Google publishes no deletion feed, so there is no way around it.
  · NO STAFF NAME. The team's workbook records who prompted each review, for
    the incentive scheme. Google will never say. Manav accepted this on 22 Aug.
  · GAPS SPAN. If a reading is missed the next delta covers both days, so the
    per-day figure is stored against the elapsed days it actually represents
    rather than being silently attributed to one.

★ AND WHAT IT ADDS: the eight Bengaluru stores, which the hand-kept workbook
does not cover at all.
"""

from __future__ import annotations

import os
import time
from datetime import date

import pandas as pd
import requests

BASE = "https://places.googleapis.com/v1"
PLACES_CSV = os.path.join(os.path.dirname(__file__), "review_places.csv")
SNAPSHOT_CSV = os.path.join(os.path.dirname(__file__), "review_snapshots.csv")

# The minimum that carries the signal. Every extra field risks a dearer SKU.
_FIELDS = "places.id,places.displayName,places.location,places.userRatingCount,places.rating"
_DETAIL_FIELDS = "id,displayName,userRatingCount,rating,businessStatus"


class NoKey(RuntimeError):
    """Refuse rather than return a zero that reads like 'no reviews today'."""


def _key() -> str:
    k = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not k:
        try:
            import streamlit as st
            k = st.secrets.get("GOOGLE_MAPS_API_KEY")
        except Exception:
            k = None
    if not k:
        raise NoKey(
            "GOOGLE_MAPS_API_KEY is not set, so review counts cannot be read. "
            "Set it as an environment variable, or in Streamlit Cloud "
            "Settings -> Secrets, or in the Hugging Face Space's Settings -> "
            "Variables and secrets. Locally it goes in .streamlit/secrets.toml, "
            "which is gitignored BECAUSE THIS REPO IS PUBLIC — never commit it."
        )
    return k


# --------------------------------------------------------------------------- #
#  One-off: which Google listing is which store
# --------------------------------------------------------------------------- #
def find_place(lat, lng, name_hint="Manyavar", radius_m=150.0) -> dict | None:
    """The store's own Google listing, found by its CONFIRMED coordinate.

    ★ PROXIMITY, NOT NAME. A text search for "Manyavar Kamraj Road" returns the
    same listing for Kamraj Road and Grand Kamraj Road — they are 71 m apart and
    Google cannot tell them apart from the words. Searching a tight radius round
    each store's own coordinate and taking the NEAREST match does.
    """
    r = requests.post(
        f"{BASE}/places:searchNearby",
        headers={"X-Goog-Api-Key": _key(), "X-Goog-FieldMask": _FIELDS,
                 "Content-Type": "application/json"},
        json={"maxResultCount": 20, "includedTypes": ["clothing_store"],
              "locationRestriction": {"circle": {
                  "center": {"latitude": float(lat), "longitude": float(lng)},
                  "radius": float(radius_m)}}},
        timeout=60,
    )
    r.raise_for_status()
    hits = r.json().get("places", [])
    want = name_hint.split()[0].lower()
    named = [h for h in hits
             if want in (h.get("displayName", {}) or {}).get("text", "").lower()]
    if not named:
        return None

    def dist(h):
        loc = h.get("location", {})
        return ((loc.get("latitude", 0) - float(lat)) ** 2
                + (loc.get("longitude", 0) - float(lng)) ** 2)

    best = min(named, key=dist)
    return {"place_id": best["id"],
            "google_name": best.get("displayName", {}).get("text"),
            "reviews": best.get("userRatingCount"),
            "rating": best.get("rating")}


def load_places() -> pd.DataFrame:
    if os.path.exists(PLACES_CSV):
        return pd.read_csv(PLACES_CSV, dtype={"store_code": str})
    return pd.DataFrame(columns=["store_code", "store", "place_id",
                                 "google_name", "lat", "lng"])


# --------------------------------------------------------------------------- #
#  Daily: read the running total
# --------------------------------------------------------------------------- #
def fetch_counts(places: pd.DataFrame) -> pd.DataFrame:
    """One row per store: today's running review total."""
    key = _key()
    rows, failed = [], []
    for _, p in places.iterrows():
        # ★★ A STORE THAT FAILS IS RETRIED, THEN NAMED — NEVER JUST SKIPPED.
        # This used to be a bare `except Exception: continue`. On 6 Sep 2026
        # Jayanagar simply was not in the file: one transient blip, no error, no
        # mention, and the day gone for good — a running total cannot be
        # backfilled, so a missed reading is permanent. The script printed
        # "read 19 stores" and nobody could tell it should have said 20.
        # Every other store answered fine the same minute, which is exactly why
        # a silent skip is the wrong behaviour: the fault was worth one retry.
        d = None
        for attempt in range(3):
            try:
                r = requests.get(
                    f"{BASE}/places/{p['place_id']}",
                    headers={"X-Goog-Api-Key": key,
                             "X-Goog-FieldMask": _DETAIL_FIELDS},
                    params={"languageCode": "en"}, timeout=60)
                r.raise_for_status()
                d = r.json()
                break
            except Exception as e:        # noqa: BLE001
                why = f"{type(e).__name__}: {e}"
                if attempt == 2:
                    failed.append(f"{p['store']} — {why}")
                else:
                    time.sleep(2 ** attempt)
        if d is None:
            continue
        rows.append({"date": date.today(), "store": p["store"],
                     "place_id": p["place_id"],
                     "total_reviews": d.get("userRatingCount"),
                     "rating": d.get("rating")})
    out = pd.DataFrame(rows)
    # carried on the frame so the caller can print it and a scheduled run can
    # fail loudly rather than write a quietly short day
    out.attrs["failed"] = failed
    out.attrs["expected"] = len(places)
    return out


def append_snapshot(new: pd.DataFrame, path=None) -> str:
    """Append today's reading, keeping one row per store per day."""
    path = path or SNAPSHOT_CSV
    old = (pd.read_csv(path, parse_dates=["date"]) if os.path.exists(path)
           else pd.DataFrame())
    new = new.copy()
    new["date"] = pd.to_datetime(new["date"])
    both = pd.concat([old, new], ignore_index=True) if len(old) else new
    both = (both.dropna(subset=["total_reviews"])
                .drop_duplicates(["store", "date"], keep="last")
                .sort_values(["store", "date"]))
    both.to_csv(path, index=False)
    return path


def daily_reviews(path=None) -> pd.DataFrame:
    """Running totals -> reviews per day.

    ★ THE FIRST READING FOR A STORE YIELDS NO DAILY FIGURE. It is a level, not a
    change, and treating it as a day's reviews would credit one store with its
    entire history in a single day — the largest is over twenty thousand.
    """
    path = path or SNAPSHOT_CSV
    if not os.path.exists(path):
        return pd.DataFrame(columns=["date", "store", "reviews", "days_covered"])
    d = pd.read_csv(path, parse_dates=["date"]).sort_values(["store", "date"])
    out = []
    for store, g in d.groupby("store"):
        g = g.sort_values("date")
        prev_n, prev_d = None, None
        for _, r in g.iterrows():
            if prev_n is not None:
                gained = float(r.total_reviews) - prev_n
                span = max((r.date - prev_d).days, 1)
                # ★★ A READING THAT SPANS A GAP IS SPREAD ACROSS THE DAYS IT
                # COVERS, not dumped on its end date. The collector missed
                # 24-25 Aug and 4 Sep, so the 26 Aug reading held THREE days of
                # reviews and 5 Sep held two — 86 of 206 collected. Dumped on
                # one date they made that day read three times too high and the
                # skipped days read zero, and no window could pair them
                # honestly. Spread evenly, every window's numerator and
                # denominator cover the same calendar.
                #
                # Even spreading is an ASSUMPTION and it is flagged as one
                # (`estimated`), because it is the only defensible split: a
                # running total carries no information about which day inside
                # the gap a review arrived. The totals stay exact either way.
                if span > 1:
                    for k in range(span):
                        out.append({
                            "date": r.date - pd.Timedelta(days=k),
                            "store": store,
                            "reviews": max(gained, 0.0) / span,
                            "removed": max(-gained, 0.0) / span,
                            "days_covered": 1,
                            "estimated": True,
                            "total_reviews": float(r.total_reviews)})
                    prev_n, prev_d = float(r.total_reviews), r.date
                    continue
                out.append({"date": r.date, "store": store,
                            # A count cannot fall except by deletion, so a
                            # negative is zero GAINED — but it is not nothing,
                            # and it used to vanish here.
                            "reviews": max(gained, 0.0),
                            # ★★ REMOVALS ARE CARRIED, NOT SWALLOWED (5 Sep
                            # 2026). Manav asked why Jayanagar showed almost no
                            # reviews when he knew it had some. It gained 2 in
                            # twelve days and LOST 3, and the report could not
                            # say so because the loss was clipped to zero here
                            # and never reached the page. Across the estate that
                            # was 18 removals invisible. A store whose reviews
                            # are being taken down as fast as they arrive is the
                            # most useful thing this whole feed can tell him,
                            # and it was the one thing it threw away.
                            "removed": max(-gained, 0.0),
                            "days_covered": span,
                            "estimated": False,
                            "total_reviews": float(r.total_reviews)})
            prev_n, prev_d = float(r.total_reviews), r.date
    return pd.DataFrame(out)
