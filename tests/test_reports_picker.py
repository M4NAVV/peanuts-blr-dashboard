"""The VFL reports tab: one pack, one master tick, two reports withdrawn.

Manav, 27 Sep 2026: *"everything goes under one header, THE VFL PACK … make a
checkbox button that is universal for the whole pack … [the team pointer] just
remove it from the live dash, keep the code stored, might be handy."*

Source assertions, as elsewhere in this repo — they run in CI with no data and
no browser, which is where a tab's wiring actually breaks.
"""
from pathlib import Path

import pytest

SRC = Path("app.py").read_text()
# ★ TWO TABS SHARE THIS NAME — the portfolio view has its own picker, with its
# own `rp_` keys and its own three headings, and it must not be disturbed. The
# VFL one is the top-level `if`; the portfolio one is an indented `elif`.
VFL = SRC[SRC.index('\nif nav == "📄 REPORTS PDF":'):]
PORTFOLIO = SRC[SRC.index('    elif nav == "📄 REPORTS PDF":'):
                SRC.index('\nif nav == "📄 REPORTS PDF":')]


def test_the_pack_has_one_header():
    assert '"**THE VFL PACK**"' in VFL
    for gone in ('st.markdown("**The pack**")',
                 'st.markdown("**DB Reports**")',
                 'st.markdown("**Manager morning snapshot**")'):
        assert gone not in VFL, gone


def test_festive_keeps_its_own_heading():
    """★ It stays separate on purpose — a different question, and usually
    wanted one run-up at a time rather than all four."""
    assert 'st.markdown("**Festive run-ups**")' in VFL


def test_a_master_tick_sets_every_report_in_the_pack():
    assert 'key="vrp_all"' in VFL
    for k in ("vrp_pack", "vrp_store_pack", "vrp_alter", "vrp_books"):
        assert k in VFL, k
    assert "_VRP_KEYS" in VFL and "st.session_state[_k] = True" in VFL


def test_the_master_sets_the_boxes_rather_than_overriding_them():
    """★★ A master that quietly built reports whose boxes read unticked would
    make the page lie about its own state. It writes the boxes instead, so what
    is ticked is always what will be built."""
    assert "or _pack_all" not in VFL          # the override shape
    assert "_vrp_all_was" in VFL              # fires on the tick, not every run


def test_the_pack_default_is_seeded_not_passed_as_a_default():
    """★ Streamlit objects when a widget is given `value=` AND has its state
    written before it is drawn — which is exactly what a master tick does."""
    assert 'st.session_state.setdefault("vrp_pack", True)' in VFL
    i = VFL.index('key="vrp_pack"')
    assert "value=True" not in VFL[max(0, i - 200):i]


# --------------------------------------------------------------------------- #
# Withdrawn from the tab, kept in the code
# --------------------------------------------------------------------------- #
def test_only_the_team_pointer_was_withdrawn():
    """★ I over-read the ask first time and hid the women's discount too.
    Manav: *"i didnot ask u to remove womens discount, just include that in the
    VFL PACK itself. only the header was to be removed for DB reports."* The
    report stays — it is the HEADING that went."""
    assert 'picked["sp_pointer"] = False' in VFL
    assert 'key="vrp_sp_pointer"' not in VFL
    assert 'key="vrp_db"' in VFL
    assert "Women's discount" in VFL


def test_the_womens_discount_is_inside_the_pack_and_the_master_tick():
    assert '"vrp_db"' in VFL[VFL.index("_VRP_KEYS"):VFL.index("_VRP_KEYS") + 200]


def test_the_team_pointer_can_still_be_built():
    """★ HIDDEN, NOT DELETED. He said to keep the code — 'might be handy'."""
    assert '"sp_pointer"' in VFL and "pointer" in VFL
    assert 'if "db" in chosen:' in VFL and "DISC.build_pdf(" in VFL


def test_the_reports_that_stayed_are_all_still_offered():
    for label in ("VFL report", "Women's discount",
                  "Store briefing + team detail",
                  "Parking & alteration charges", "Collection books"):
        assert label in VFL, label


def test_the_briefing_and_team_detail_are_one_report():
    """Manav, 10 Oct: *"combine 2 reports into one"* — the morning A4 and the
    team detail, one PDF per store. ★ He chose REPLACE: the two separate boxes
    are hidden, not deleted, and their build code stays."""
    assert 'picked["morning"] = False' in VFL
    assert 'picked["sp_detail"] = False' in VFL
    assert 'key="vrp_morning"' not in VFL and 'key="vrp_sp_detail"' not in VFL
    assert 'if "store_pack" in chosen:' in VFL and "A4.store_packs(" in VFL
    assert 'if "morning" in chosen:' in VFL           # kept, one flag away
    assert '"vrp_store_pack"' in VFL[VFL.index("_VRP_KEYS"):][:200]


# --------------------------------------------------------------------------- #
# The portfolio picker — the same treatment, asked for separately
# --------------------------------------------------------------------------- #
def test_the_portfolio_pack_also_has_one_header():
    """Manav, 27 Sep: *"for the portfolio tab, reports pdf, same stuff … the
    header reports td goes."*"""
    assert '"**THE PORTFOLIO PACK**"' in PORTFOLIO
    for gone in ('st.markdown("**The pack**")', 'st.markdown("**Report TD**")'):
        assert gone not in PORTFOLIO, gone
    assert 'st.markdown("**Festive run-ups**")' in PORTFOLIO


def test_the_portfolio_master_tick_covers_every_report():
    assert 'key="rp_all"' in PORTFOLIO
    for k in ("rp_pack", "rp_sl", "rp_el", "rp_mw", "rp_ns", "rp_tva", "rp_rv"):
        assert f'"{k}"' in PORTFOLIO, k
    assert "_RP_KEYS" in PORTFOLIO


def test_the_two_pickers_keep_their_own_keys():
    """★ Two tabs share the name '📄 REPORTS PDF'. Their widget keys are all
    that keep them apart, and a key used in both would have one tab's tick
    silently move the other's."""
    assert "vrp_" not in PORTFOLIO
    assert '"rp_pack"' not in VFL and '"rp_all"' not in VFL


def test_neither_master_uses_a_default_and_a_written_state_together():
    for blk, key in ((VFL, "vrp_pack"), (PORTFOLIO, "rp_pack")):
        assert f'st.session_state.setdefault("{key}", True)' in blk
        i = blk.index(f'key="{key}"')
        assert "value=True" not in blk[max(0, i - 200):i]


# --------------------------------------------------------------------------- #
# Reports images — the morning set
# --------------------------------------------------------------------------- #
IMAGES = SRC[SRC.index('"Morning snapshots"'):][:4000]


def test_per_store_drivers_is_not_offered():
    """Manav, 27 Sep: *"we dont need the per store drivers, hide that,
    everything else stays as is."*"""
    assert 'checkbox(\n        "Per-store drivers"' not in SRC
    assert '"Per-store drivers", value=True' not in SRC
    assert "want_drivers = False" in SRC


def test_the_other_two_are_untouched():
    assert '"Store-wise MTD / YTD", value=True' in SRC
    assert '"Degrowth by region", value=True' in SRC


def test_the_builder_is_kept():
    """★ Withdrawn, not deleted — it is the slow, twenty-two-image half of the
    ZIP, and restoring it is a checkbox."""
    assert "if want_drivers:" in SRC or "want_drivers" in SRC


def test_the_caption_does_not_promise_a_folder_that_will_not_be_there():
    """★ With the per-store sheets gone there is no `by-store/` folder, and
    naming one sends somebody looking for it."""
    i = SRC.index("image(s)** — `shared/`")
    assert "if want_drivers" in SRC[i:i + 260]
