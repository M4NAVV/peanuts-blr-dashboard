#!/usr/bin/env python
"""Read every resolved store's running Google review count. Run daily."""
import os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, google_reviews as G

places = G.load_places()
if places.empty:
    print("No resolved stores. Run scripts_resolve.py first.")
    raise SystemExit(2)
try:
    got = G.fetch_counts(places)
except G.NoKey as e:
    print(f"NOT COLLECTED: {e}")
    raise SystemExit(2)
if got.empty:
    print("Nothing came back — not writing an empty reading.")
    raise SystemExit(1)

# ★ SAY WHAT DID NOT COME BACK, BEFORE SAYING WHAT DID. A missed store cannot
# be recovered later — the reading is a running level, not an event — so a short
# day has to be visible on the morning it happens.
_failed = got.attrs.get("failed") or []
_expected = got.attrs.get("expected", len(places))
if _failed:
    print(f"MISSED {len(_failed)} of {_expected} store(s) after 3 tries:")
    for f in _failed:
        print(f"   {f}")

path = G.append_snapshot(got)
d = G.daily_reviews()
print(f"read {len(got)} of {_expected} stores -> {os.path.basename(path)}")
print(f"readings on file: {pd.read_csv(path)['date'].nunique()} day(s)")
if d.empty:
    print("\nFirst reading. It is a LEVEL, not a change — daily counts begin "
          "with tomorrow's reading.")
else:
    latest = d[d.date == d.date.max()]
    print(f"\nreviews on {d.date.max():%d %b}: {latest.reviews.sum():,.0f} "
          f"across {len(latest)} stores")
