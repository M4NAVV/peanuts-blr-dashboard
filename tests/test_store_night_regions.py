"""The night report to the directors (Manav, 10 Nov 2026): one PDF per region, a page per open VFL store, in the
store sheets' alphabetical order, named ASM EAST / ASM SOUTH."""
import pandas as pd
from PIL import Image

import snapshots_a4 as A4
import store_night as SNI


class _L:
    @staticmethod
    def load_store_master():
        return pd.DataFrame({"tableau_name": ["Silchar", "Agartala", "Orion Mall"], "code": [105, 91, 111],
                             "region": ["East & NE", "East & NE", "South"]})


def test_one_pdf_per_region_a_page_per_store_in_order(monkeypatch):
    seen = []
    monkeypatch.setattr(SNI, "L", _L)
    monkeypatch.setattr(A4, "open_stores", lambda L, df: ["Agartala", "Orion Mall", "Silchar"])
    monkeypatch.setattr(SNI, "build", lambda df, pf, s, asof, code, fmt="pdf":
                        seen.append(s) or ("x", [Image.new("RGB", (20, 20), "white")], 1))
    out, failed = SNI.region_pdfs(pd.DataFrame(), pd.DataFrame(), "2026-11-09")
    assert failed == [] and seen == ["Agartala", "Silchar", "Orion Mall"]
    assert [(n, t) for n, _b, t in out] == [("ASM EAST · Night report · 09-11-2026.pdf", "east-ne"),
                                            ("ASM SOUTH · Night report · 09-11-2026.pdf", "south")]


def test_a_store_that_fails_is_named_and_the_rest_still_go(monkeypatch):
    monkeypatch.setattr(SNI, "L", _L)
    monkeypatch.setattr(A4, "open_stores", lambda L, df: ["Agartala", "Orion Mall", "Silchar"])

    def build(df, pf, s, asof, code, fmt="pdf"):
        if s == "Silchar":
            raise ValueError("no bills")
        return ("x", [Image.new("RGB", (20, 20), "white")], 1)
    monkeypatch.setattr(SNI, "build", build)
    out, failed = SNI.region_pdfs(pd.DataFrame(), pd.DataFrame(), "2026-11-09")
    assert len(out) == 2 and failed == ["Silchar: ValueError: no bills"]
