"""The festive admin pack, and the VFL feed running through it.

Frames are built inside the test so CI verifies the rules without the
feed — see [[feedback-test-where-it-runs]].
"""
import pandas as pd

# --------------------------------------------------------------------------- #
# The VFL feed through the admin pack (16 Sep 2026). It was portfolio-only
# because `classify`/`daily_for`/`figures_for` read date/code/sales/region off
# the RAW frame, and the VFL feed carries a store LABEL and `net_amount`.
# --------------------------------------------------------------------------- #
def _vfl_frame():
    """Two known stores plus one the master will not know."""
    import loader as L
    rows = []
    for d in pd.date_range("2025-08-19", "2026-09-15"):
        rows += [{"date": d, L.COL_STORE_LABEL: "Agartala",
                  L.COL_AMOUNT: 100.0, "region": "East & NE"},
                 {"date": d, L.COL_STORE_LABEL: "Jayanagar",
                  L.COL_AMOUNT: 200.0, "region": "South"}]
    rows.append({"date": pd.Timestamp("2026-09-15"),
                 L.COL_STORE_LABEL: "Not In The Master At All",
                 L.COL_AMOUNT: 999.0, "region": "East & NE"})
    return pd.DataFrame(rows)


def test_the_vfl_frame_gains_the_columns_the_pack_reads():
    import festive_admin as FADM
    out = FADM._vfl_as_portfolio(_vfl_frame())
    for c in ("date", "code", "sales", "region"):
        assert c in out.columns, c
    assert out["code"].dtype.kind == "i"
    assert out["sales"].sum() > 0


def test_a_store_the_master_does_not_know_is_named_not_dropped_silently():
    """It cannot be classified or rolled up by region, so it must not land in
    a total unannounced. See [[feedback-silent-failure-must-speak]]."""
    import warnings
    import festive_admin as FADM
    with warnings.catch_warnings(record=True) as ws:
        warnings.simplefilter("always", RuntimeWarning)
        out = FADM._vfl_as_portfolio(_vfl_frame())
    assert any("not in the store master" in str(x.message) for x in ws)
    assert "Not In The Master At All" in " ".join(str(x.message) for x in ws)
    assert len(out) < len(_vfl_frame())


def test_the_portfolio_path_is_untouched_by_the_adapter():
    """The pack read every morning must not change by a character."""
    import inspect
    import festive_admin as FADM
    src = inspect.getsource(FADM.build)
    assert "_vfl_as_portfolio(pf)" in src
    # the translation happens ONLY inside the vfl branch
    head = src.split("else:")[0]
    assert "_vfl_as_portfolio" in head


# ---- the copy must describe the data, not assert an estate ---------------- #
def test_region_phrase_names_what_is_actually_there():
    import festive_admin as FADM
    both = pd.DataFrame({"region": ["East & NE", "South", "East & NE"]})
    east = pd.DataFrame({"region": ["East & NE", "East & NE"]})
    assert FADM.regions_phrase(both) == "East & NE and South"
    assert FADM.regions_phrase(east) == "East & NE"
    assert FADM.regions_phrase(pd.DataFrame({"region": []})) == "all"


def test_held_out_phrase_counts_south_instead_of_assuming_eight():
    """The page said 'the eight South stores among them' as a literal. True of
    the portfolio pack; false on the VFL feed, where South is INSIDE the
    comparison — it described 19 stores as East & NE while 8 were Bengaluru."""
    import festive_admin as FADM
    oth = pd.DataFrame({"region": ["South", "South", "East & NE"]})
    got = FADM.heldout_phrase(oth, n_new=3, n_shut=2)
    assert "3 with no last year at all" in got
    assert "2 of them South" in got
    assert "2 closed" in got

    none_south = pd.DataFrame({"region": ["East & NE"]})
    assert "South" not in FADM.heldout_phrase(none_south, n_new=1, n_shut=0)


def test_the_narrative_is_built_from_the_helpers_not_from_literals():
    """A literal that states what the data happens to be today is a caption
    that goes wrong silently. Asserted on BEHAVIOUR, not by grepping the file —
    the docstrings deliberately quote the old wording to explain the bug."""
    import festive_admin as FADM

    # the phrase never hard-codes a count or a region it was not given
    east_only = pd.DataFrame({"region": ["East & NE", "East & NE"]})
    assert "South" not in FADM.regions_phrase(east_only)
    assert "South" not in FADM.heldout_phrase(east_only, n_new=2, n_shut=0)

    # and it does name South when South really is held out
    with_south = pd.DataFrame({"region": ["South", "East & NE"]})
    assert "South" in FADM.heldout_phrase(with_south, n_new=2, n_shut=0)

    # the page-1 narrative calls them rather than asserting an estate
    import inspect
    src = inspect.getsource(FADM.build)
    assert "regions_phrase(" in src and "heldout_phrase(" in src
