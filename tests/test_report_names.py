"""Every download is named the WhatsApp bot's way (Manav, 10 Nov 2026: "same naming convention as the whatsapp
report bot. the buckets we made and all that, so its consistent")."""
import re
from pathlib import Path
from types import SimpleNamespace as W

import pandas as pd

import report_names as RN

DAY = pd.Timestamp("2026-11-09")


def test_the_bots_shape_code_name_date():
    assert RN.name("graph", DAY, ".pdf") == "VFL 2 · Graph analysis VFL · 09-11-2026.pdf"
    assert RN.name("portfolio_pack", DAY, "x.pdf") == "OVR 1 · Portfolio report · 09-11-2026.pdf"
    assert RN.name("db_report", DAY, "womens_discount.PDF").endswith(".pdf")


def test_variants_take_a_letter_and_a_bracket():
    assert RN.name("festive", DAY, ".pdf", letter="a", label="Diwali 45") == \
        "OVR 7a · Festive run-up (Diwali 45) · 09-11-2026.pdf"
    assert RN.name("reviews", DAY, ".pdf", letter="b", label="South") == \
        "OVR 8b · Google reviews (South) · 09-11-2026.pdf"


def test_images_and_store_sheets_are_numbered():
    assert RN.name("vfl_images", DAY, ".png", n=3) == \
        "VFL IMG 3 · Degrowth watchlist, East & NE YTD · 09-11-2026.png"
    assert RN.name("stores_east", DAY, ".pdf", n=4, store="Malda") == \
        "EAST 4 · Store sheet, Malda · 09-11-2026.pdf"


def test_a_name_never_carries_a_slash():
    assert "/" not in RN.name("vfl_images", DAY, ".png", n=5)          # "Store-wise MTD / YTD"


def test_buckets_and_plain_downloads():
    assert RN.bucket_zip("vfl_pdf", DAY) == "VFL · VFL reports · 09-11-2026.zip"
    assert RN.plain("Gender mix", DAY, ".csv") == "Gender mix · 09-11-2026.csv"
    assert RN.from_key("gender_gd_store_20261109", ".csv") == "Gender G-D by store · 09-11-2026.csv"


def test_festive_letters_follow_the_bot():
    """Festivals in the tab's order, the longest run-up first inside each."""
    ws = [W(festival="Durga Puja", tenure=30), W(festival="Durga Puja", tenure=45), W(festival="Diwali", tenure=45)]
    assert [(w.festival, w.tenure) for w in RN.festive_order(ws)] == \
        [("Durga Puja", 45), ("Durga Puja", 30), ("Diwali", 45)]


def test_no_download_keeps_an_old_style_name():
    src = Path("app.py").read_text()
    for old in ("peanuts_portfolio_", "peanuts_vfl_", "PORTFOLIO REPORTS", "VFL REPORTS {", "snapshots_{",
                "peanuts_mtd_ytd", "peanuts_degrowth_", 'file_name=f"{key}.csv"', "MANAGER IMAGES"):
        assert old not in src, old
