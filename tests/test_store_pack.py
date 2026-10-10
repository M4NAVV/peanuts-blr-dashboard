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


def _run(monkeypatch, team):
    monkeypatch.setattr(A4, "open_stores", lambda L, df: ["Grand Kamraj Road",
                                                          "Dibrugarh"])
    monkeypatch.setattr(A4, "store_sheet",
                        lambda *a, fmt="pdf", **k: ("x.pdf", [_page("white")],
                                                    0, 1, None))
    monkeypatch.setattr(SP, "detailed_sheet", team)
    return A4.store_packs(_Master, pd.DataFrame(), "2026-10-09", ff={},
                          targets={})


def test_briefing_then_team_in_one_pdf_per_store(monkeypatch):
    seen = []

    def team(L, df, asof, s, code=None, fmt="pdf", **k):
        seen.append(fmt)
        return ("t.pdf", [_page("red")], 0, 1, 10)
    out, failed = _run(monkeypatch, team)
    assert failed == []
    assert [n for n, _ in out] == [
        "store-briefing/South/2026-10-09_107_"
        f"{A4.SN._slug('Grand Kamraj Road')}_briefing_team.pdf",
        "store-briefing/East & NE/2026-10-09_120_"
        f"{A4.SN._slug('Dibrugarh')}_briefing_team.pdf"]
    assert set(seen) == {"pages"}
    assert [_pdf_pages(b) for _, b in out] == [2, 2]   # briefing + team


def test_a_store_where_nobody_sold_keeps_its_briefing_and_is_named(monkeypatch):
    def team(L, df, asof, s, code=None, fmt="pdf", **k):
        return None if s == "Dibrugarh" else ("t.pdf", [_page("red")], 0, 1, 1)
    out, failed = _run(monkeypatch, team)
    assert [_pdf_pages(b) for _, b in out] == [2, 1]   # Dibrugarh: page one
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
