"""The store briefing + team detail pack (Manav, 10 Oct 2026).

One PDF per store: the morning A4 first, the team detail behind it. A half that
cannot be built must leave the other half in the zip AND be named.
"""
import pandas as pd
from PIL import Image

import snapshots_a4 as A4
import salespeople as SP


def _page(colour):
    return Image.new("RGB", (A4.PAGE_W, A4.PAGE_H), colour)


def _pdf_pages(b):
    from PIL import PdfParser
    return len(PdfParser.PdfParser(buf=b).pages)


class _Master:
    @staticmethod
    def load_store_master():
        return pd.DataFrame({"tableau_name": ["Grand Kamraj Road", "Dibrugarh"],
                             "code": [107, 120],
                             "region": ["South", "East & NE"]})


def _run(monkeypatch, team, cats=None):
    monkeypatch.setattr(A4, "open_stores", lambda L, df: ["Grand Kamraj Road",
                                                          "Dibrugarh"])
    monkeypatch.setattr(A4, "store_sheet",
                        lambda *a, fmt="pdf", **k: ("x.pdf", [_page("white")],
                                                    0, 1, None))
    monkeypatch.setattr(SP, "detailed_sheet", team)
    # ★ 18 Oct 2026: page two is the category page
    monkeypatch.setattr(A4, "category_sheet_print", cats or (lambda *a, **k: [_page("blue")]))
    # ★ 12 Nov 2026: page two is targets, brand & gender (categories move to three, team to four)
    monkeypatch.setattr(A4, "brand_gender_page", lambda *a, **k: [_page("green")])
    return A4.store_packs(_Master, pd.DataFrame(), "2026-10-09", ff={},
                          targets={})


def test_briefing_then_team_in_one_pdf_per_store(monkeypatch):
    seen = []

    def team(L, df, asof, s, code=None, fmt="pdf", **k):
        seen.append(fmt)
        return ("t.pdf", [_page("red")], 0, 1, 10)
    out, failed = _run(monkeypatch, team)
    assert failed == []
    # ★ the WhatsApp bot's names (Manav, 10 Nov 2026), numbered alphabetically within the region
    assert [n for n, _ in out] == [
        "SOUTH/SOUTH 1 · Store sheet, Grand Kamraj Road · 09-10-2026.pdf",
        "EAST/EAST 1 · Store sheet, Dibrugarh · 09-10-2026.pdf"]
    assert set(seen) == {"pages"}
    assert [_pdf_pages(b) for _, b in out] == [4, 4]   # briefing + brand & gender + categories + team


def test_a_store_where_nobody_sold_keeps_its_briefing_and_is_named(monkeypatch):
    def team(L, df, asof, s, code=None, fmt="pdf", **k):
        return None if s == "Dibrugarh" else ("t.pdf", [_page("red")], 0, 1, 1)
    out, failed = _run(monkeypatch, team)
    assert [_pdf_pages(b) for _, b in out] == [4, 3]   # Dibrugarh: no team page
    assert failed == ["Dibrugarh: no team page — nobody sold"]


def test_a_failed_team_page_does_not_sink_the_store(monkeypatch):
    def team(L, df, asof, s, code=None, fmt="pdf", **k):
        raise ValueError("boom")
    out, failed = _run(monkeypatch, team)
    assert len(out) == 2
    assert all("team detail — boom" in f for f in failed)


def test_pages_pdf_keeps_every_page():
    assert _pdf_pages(A4.pages_pdf([_page("white"), _page("red")])) == 2


def test_the_separate_reports_still_build_alone():
    """Hidden, not deleted — `fmt` defaults to a PDF on both."""
    import inspect
    assert inspect.signature(A4.store_sheet).parameters["fmt"].default == "pdf"
    assert inspect.signature(SP.detailed_sheet).parameters["fmt"].default == "pdf"


def test_the_briefing_page_is_the_one_page_print_layout():
    """★ `fmt="pdf"` is routed to `store_sheet_print` (every Twamev section on
    ONE A4). The first build of this pack let `"pages"` fall through to the
    IMAGE layout and came out three pages, not his two. Both go to print."""
    import inspect
    src = inspect.getsource(A4.store_sheet)
    assert 'if fmt in ("pdf", "pages"):' in src
    assert "fmt=fmt" in src


def test_a_failed_category_page_keeps_the_rest_and_is_named(monkeypatch):
    def team(L, df, asof, s, code=None, fmt="pdf", **k):
        return ("t.pdf", [_page("red")], 0, 1, 1)

    def cats(*a, **k):
        raise ValueError("no rows")
    out, failed = _run(monkeypatch, team, cats)
    assert [_pdf_pages(b) for _, b in out] == [3, 3]   # briefing + brand & gender + team still go
    assert all("categories page — no rows" in f for f in failed)



def test_the_pack_runs_targets_brand_gender_then_categories_then_briefing_then_team(monkeypatch):
    """Manav, 12 Nov 2026: "the sequence should be page 2, 3, 1, 4"."""
    seen = []
    monkeypatch.setattr(A4, "pages_pdf", lambda pages: seen.append([pg.getpixel((0, 0)) for pg in pages]) or b"%PDF")
    def team(L, df, asof, s, code=None, fmt="pdf", **k):
        return ("t.pdf", [_page("red")], 0, 1, 10)
    _run(monkeypatch, team)
    green, blue, white, red = (0, 128, 0), (0, 0, 255), (255, 255, 255), (255, 0, 0)
    assert seen[0] == [green, blue, white, red]
