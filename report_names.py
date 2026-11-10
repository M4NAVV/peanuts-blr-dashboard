"""One naming convention for every file this dashboard hands out — the WhatsApp report bot's.

Manav, 10 Nov 2026: *"all the reports we download, we want it to be the same naming convention as the whatsapp
report bot. the buckets we made and all that, so its consistent."*

The bot (private repo peanuts-whatsapp-sender, `reports.py`) gives every director report a FIXED code inside a
bucket, and names the file it sends

    <CODE> · <Name> · DD-MM-YYYY.<ext>          e.g.  VFL 2 · Graph analysis VFL · 09-11-2026.pdf

  OVR 1–9      the Overall PDFs          VFL IMG 1–5   the VFL morning images
  VFL 1–9      the VFL PDFs              EAST n / SOUTH n   the store sheets, alphabetical in the region

A report with several files that day takes letters (OVR 7a, 7b … for the festive run-ups, OVR 8a/8b for Google
reviews by region). The date is the DATA day the report is built to, never the clock.

★ THIS TABLE MUST MATCH THE BOT'S. The bot imports this module in its tests and fails if a code or a name differs —
two lists that are meant to agree drift unless something checks them.

A download the bot never sends (a CSV export, the Excel Builder, the day calendars) carries no code but the same
shape: `<Name> · DD-MM-YYYY.<ext>`.
"""
from __future__ import annotations

import re
from pathlib import PurePath

import pandas as pd

# report id (the bot's) -> (code, name). Name = the bot's label before " · ".
CATALOGUE = {
    "portfolio_pack": ("OVR 1", "Portfolio report"),
    "target_vs_ach": ("OVR 2", "Target vs achievement"),
    "night_sms": ("OVR 3", "Night sale SMS"),
    "month_wise": ("OVR 4", "Month-wise total sale"),
    "south_ltol": ("OVR 5", "South L-to-L"),
    "east_ltol": ("OVR 6", "East & NE L-to-L"),
    "festive": ("OVR 7", "Festive run-up"),
    "reviews": ("OVR 8", "Google reviews"),
    "weekday_weekend": ("OVR 9", "Weekday vs weekend"),
    "vfl_images": ("VFL IMG", "VFL morning images"),
    "vfl_pack": ("VFL 1", "VFL report"),
    "graph": ("VFL 2", "Graph analysis VFL"),
    "category": ("VFL 3", "Category analysis VFL"),
    "category_brand": ("VFL 4", "Category analysis by brand VFL"),
    "price": ("VFL 5", "Price bracket analysis VFL"),
    "db_report": ("VFL 6", "Women's discount"),
    "festive_vfl": ("VFL 7", "Festive run-up VFL"),
    "alterations": ("VFL 8", "Parking and alteration charges"),
    "books": ("VFL 9", "Collection books"),
    "stores_east": ("EAST", "Store sheet"),
    "stores_south": ("SOUTH", "Store sheet"),
}

# The buckets (the bot's BLOCKS), for a zip of several reports.
BUCKETS = {
    "overall": ("OVR", "Overall reports"),
    "vfl_images": ("VFL IMG", "VFL morning images"),
    "vfl_pdf": ("VFL", "VFL reports"),
    "stores_east": ("EAST", "Store sheets, East & NE"),
    "stores_south": ("SOUTH", "Store sheets, South"),
}

# The five morning images, in the bot's order and words.
IMAGES = {
    1: "Degrowth watchlist, South YTD",
    2: "Degrowth watchlist, South MTD",
    3: "Degrowth watchlist, East & NE YTD",
    4: "Degrowth watchlist, East & NE MTD",
    5: "Store-wise MTD / YTD",
}
# A region variant, spelled as the house spells it (the bot's _REGION_NAMES; the review report's tags).
REGION = {"east-ne": "East & NE", "south": "South"}

IMAGE_NO = {("YTD", "South"): 1, ("MTD", "South"): 2, ("YTD", "East & NE"): 3, ("MTD", "East & NE"): 4}


def _ext(name_or_ext: str) -> str:
    s = str(name_or_ext)
    return (s if s.startswith(".") else (PurePath(s).suffix or "")).lower()    # ".PDF" from one builder → ".pdf"


def file_name(words: str, day, ext: str) -> str:
    """`<words> · DD-MM-YYYY<ext>` — no slashes (it is a file name), the bot's exact shape."""
    words = re.sub(r"\s+", " ", str(words).replace("/", "-")).strip()
    return f"{words} · {pd.Timestamp(day):%d-%m-%Y}{_ext(ext)}"


def name(rid: str, day, ext: str, *, label: str = "", letter: str = "", n: int | None = None,
         store: str = "") -> str:
    """The bot's name for report `rid`.

    label   a variant in brackets: "Festive run-up (Diwali 18)", "Google reviews (South)"
    letter  the variant's letter inside the code: OVR 7a
    n       a numbered file: VFL IMG 3, EAST 4
    store   a store sheet: "EAST 4 · Store sheet, Malda"
    """
    code, base = CATALOGUE[rid]
    if n is not None:
        code = f"{code} {n}"
    elif letter:
        code = f"{code}{letter}"
    words = base
    if rid == "vfl_images" and n in IMAGES:
        words = IMAGES[n]
    elif store:
        words = f"{base}, {store}"
    elif label:
        words = f"{base} ({label})"
    return file_name(f"{code} · {words}", day, ext)


def named(rid: str, item, day, **kw):
    """(file name, bytes, …) as a builder returned it -> the same with the bot's name. Extension kept."""
    if item is None:
        return None
    return (name(rid, day, item[0], **kw), *item[1:])


def letters(n: int) -> list[str]:
    return [chr(97 + i) for i in range(n)]


def festive_order(windows) -> list:
    """The bot's lettering order: festivals in the order the tab lists them, longest run-up first inside each."""
    first: dict = {}
    for i, w in enumerate(windows):
        first.setdefault(w.festival, i)
    return sorted(windows, key=lambda w: (first[w.festival], -int(w.tenure)))


def bucket_zip(bucket: str, day) -> str:
    code, words = BUCKETS[bucket]
    return file_name(f"{code} · {words}", day, ".zip")


# The dashboard's CSV keys ("gender_gd_store_20261109") in words.
KEY_WORDS = {
    "gender_gd_store": "Gender G-D by store", "gender_gd": "Gender G-D", "brand_gd": "Brand-wise G-D",
    "store_brand_gd": "Store and brand G-D", "gender_mix_store": "Gender mix by store", "city_gd": "City-wise G-D",
    "monthly_contrib": "Monthly contribution", "productivity": "Productivity",
}


def from_key(key: str, ext: str) -> str:
    """A table's key with its date on the end -> the house name: `Gender G-D by store · 09-11-2026.csv`."""
    m = re.match(r"(.*?)_(\d{8})$", str(key))
    stem, day = (m.group(1), pd.Timestamp(m.group(2))) if m else (str(key), pd.Timestamp.today().normalize())
    return plain(KEY_WORDS.get(stem, stem.replace("_", " ").capitalize()), day, ext)


def plain(words: str, day, ext: str) -> str:
    """A download the bot never sends: same shape, no code."""
    return file_name(words, day, ext)
