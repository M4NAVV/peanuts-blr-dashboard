"""The night's figures, from the portfolio sheet or from the fill tab.

Manav, 26 Sep 2026: *"the plan is to stop tinku night fill, and get the data
typed in peanutstotal directly, so that saves a step there."*

Frames are built here, so these run in CI with no sheet and no network —
see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import night_fill as NF

DAY = pd.Timestamp("2026-09-25")


def _pf(day=DAY, rows=None):
    """The portfolio sheet's own shape: ONE row per store per day."""
    rows = rows or [
        {"code": 107, "Total": "6,21,933.00", "BILL": "36", "QTY": "68",
         "FOOTFALL": "48", "Day Target": "900000", "MANUAL SALE": "",
         "CITY": "BENGALURU"},
        {"code": 114, "Total": "1,20,000.00", "BILL": "9", "QTY": "12",
         "FOOTFALL": "", "Day Target": "150000", "MANUAL SALE": "5000",
         "CITY": "BENGALURU"},
    ]
    f = pd.DataFrame(rows)
    f["date"] = day
    return f


# --------------------------------------------------------------------------- #
# Reading the sheet
# --------------------------------------------------------------------------- #
def test_the_sheets_newest_day_comes_back_in_the_tabs_shape():
    t = NF.from_portfolio(_pf())
    assert list(t["code"]) == [107, 114]
    assert float(t.loc[t["code"] == 107, "value"].iloc[0]) == 621933.0
    for c in ("code", "date", "value", "gender", "line", "city", "bills",
              "qty", "footfall", "manual", "day_target"):
        assert c in t.columns, c


def test_commas_and_rupee_text_are_read_as_numbers():
    """★ `81,65,928` read as `81` is the bug that bit the report parser. A
    sheet column arrives as TEXT with blanks."""
    t = NF.from_portfolio(_pf())
    assert float(t.loc[t["code"] == 107, "value"].iloc[0]) == 621933.0
    assert float(t.loc[t["code"] == 107, "day_target"].iloc[0]) == 900000.0


def test_a_blank_is_nothing_typed_not_a_zero():
    """★ A store nobody entered a footfall for must not report 'no footfall'.
    See [[feedback-silent-failure-must-speak]]."""
    t = NF.from_portfolio(_pf())
    dvg = t[t["code"] == 114].iloc[0]
    assert pd.isna(dvg["footfall"])
    assert float(dvg["manual"]) == 5000.0
    gk = t[t["code"] == 107].iloc[0]
    assert pd.isna(gk["manual"])


def test_it_takes_the_newest_day_only():
    old = _pf(DAY - pd.Timedelta(days=1))
    both = pd.concat([old, _pf()], ignore_index=True)
    t = NF.from_portfolio(both)
    assert t["date"].nunique() == 1 and t["date"].iloc[0] == DAY
    assert len(t) == 2


def test_a_day_can_be_pinned():
    both = pd.concat([_pf(DAY - pd.Timedelta(days=1)), _pf()],
                     ignore_index=True)
    t = NF.from_portfolio(both, day=DAY - pd.Timedelta(days=1))
    assert t["date"].iloc[0] == DAY - pd.Timedelta(days=1)


def test_an_empty_sheet_returns_nothing_rather_than_an_empty_frame():
    assert NF.from_portfolio(None) is None
    assert NF.from_portfolio(pd.DataFrame()) is None


def test_brand_columns_are_carried_when_the_sheet_has_them():
    """★ The sheet is ONE ROW PER STORE, so there is no brand LINE to group by.
    If it is given MANYAVAR / MOHEY / TWAMEV columns — exactly what the intake
    form collects — they are read straight off."""
    rows = [{"code": 107, "Total": "600000", "BILL": "30", "QTY": "60",
             "FOOTFALL": "40", "Day Target": "900000", "CITY": "BENGALURU",
             "MANYAVAR": "300000", "MOHEY": "200000", "TWAMEV": "100000"}]
    t = NF.from_portfolio(_pf(rows=rows))
    assert float(t["manyavar"].iloc[0]) == 300000.0
    assert float(t["twamev"].iloc[0]) == 100000.0


def test_without_those_columns_the_brand_split_is_absent_not_zero():
    t = NF.from_portfolio(_pf())
    assert "manyavar" not in t.columns


# --------------------------------------------------------------------------- #
# Which source wins
# --------------------------------------------------------------------------- #
def _tab(day):
    return pd.DataFrame([{"code": 107, "date": day, "value": 500000.0,
                          "gender": "MEN", "line": "MANYAVAR",
                          "city": "BENGALURU"}])


def test_the_sheet_wins_a_tie(monkeypatch):
    """★ The tab is only ever a head start. The moment the figures are typed
    into the sheet it stops being consulted — no switch to throw."""
    monkeypatch.setattr(NF, "load", lambda url=None: _tab(DAY))
    got, src = NF.for_night(_pf())
    assert src == "the portfolio sheet"
    assert float(got.loc[got["code"] == 107, "value"].iloc[0]) == 621933.0


def test_the_tab_wins_while_it_is_ahead(monkeypatch):
    monkeypatch.setattr(NF, "load", lambda url=None: _tab(DAY + pd.Timedelta(days=1)))
    got, src = NF.for_night(_pf())
    assert src == "the night fill tab"


def test_the_sheet_alone_is_enough(monkeypatch):
    """The state the estate is moving to: no tab at all."""
    monkeypatch.setattr(NF, "load", lambda url=None: None)
    got, src = NF.for_night(_pf())
    assert src == "the portfolio sheet" and len(got) == 2


def test_the_tab_alone_still_works(monkeypatch):
    """And the state it is moving FROM."""
    monkeypatch.setattr(NF, "load", lambda url=None: _tab(DAY))
    got, src = NF.for_night(None)
    assert src == "the night fill tab"


def test_neither_source_says_so_plainly(monkeypatch):
    monkeypatch.setattr(NF, "load", lambda url=None: None)
    got, src = NF.for_night(None)
    assert got is None


# --------------------------------------------------------------------------- #
# The report that used to demand the tab
# --------------------------------------------------------------------------- #
def test_the_night_sms_no_longer_requires_the_tab():
    """★ THE ONE HARD BLOCK. `south_night_sms` called `night_fill.load()` and
    RAISED without it, so the night the typing moved to the sheet a live
    report would have died."""
    import inspect

    import report_td as RTD
    src = inspect.getsource(RTD.south_night_sms)
    assert "night_fill.for_night(pf_df)" in src
    assert "it is the only source for the day's figures" not in src


def test_the_night_sms_resolves_the_split_from_the_best_source():
    import inspect

    import report_td as RTD
    src = inspect.getsource(RTD.south_night_sms)
    assert "brand_split(t, codes, day, vfl_df," in src
    assert "tab=" in src                      # the tab is offered too


# --------------------------------------------------------------------------- #
# Backdating — the tab is overwritten, the split has to come from elsewhere
# --------------------------------------------------------------------------- #
def test_the_brand_split_prefers_a_column_the_sheet_was_given():
    import report_td as RTD
    t = pd.DataFrame([{"code": 107, "value": 600000.0, "line": "",
                       "manyavar": 300000.0, "mohey": 200000.0,
                       "twamev": 100000.0}])
    got = RTD.brand_split(t, [107], DAY, vfl_df=pd.DataFrame())
    assert got[107] == {"manyavar": 300000.0, "mohey": 200000.0,
                        "twamev": 100000.0}


def test_the_brand_split_falls_back_to_the_tabs_lines():
    import report_td as RTD
    t = pd.DataFrame([
        {"code": 107, "value": 400000.0, "line": "MANYAVAR"},
        {"code": 107, "value": 200000.0, "line": "MOHEY-SAREE"},
    ])
    got = RTD.brand_split(t, [107], DAY, vfl_df=pd.DataFrame())
    assert got[107]["manyavar"] == 400000.0
    assert got[107]["mohey"] == 200000.0
    assert got[107]["twamev"] == 0.0


def test_a_store_no_source_can_answer_is_absent_not_zero():
    """★ An empty cell says 'not recorded'; a zero says 'sold none'. A Turtle
    store has no Mohey to report at all."""
    import report_td as RTD
    t = pd.DataFrame([{"code": 47, "value": 50000.0, "line": ""}])
    got = RTD.brand_split(t, [47], DAY, vfl_df=pd.DataFrame())
    assert 47 not in got


def test_the_feed_answers_a_day_the_tab_has_written_over():
    """★★ THE FALLBACK THIS EXISTS FOR. The tab holds one night; the bill feed
    carries brand at line level for all history."""
    import loader as L
    import report_td as RTD
    vfl = pd.DataFrame({
        "date": [DAY] * 3,
        L.COL_STORE_LABEL: ["Grand Kamraj Road"] * 3,
        L.COL_DIVISION: ["KURTA SET", "MOHEY-SAREE", "TWAMEV-MEN"],
        L.COL_AMOUNT: [300000.0, 200000.0, 100000.0],
    })
    t = pd.DataFrame([{"code": 107, "value": 600000.0, "line": ""}])
    got = RTD.brand_split(t, [107], DAY, vfl_df=vfl)
    assert got[107]["manyavar"] == 300000.0
    assert got[107]["mohey"] == 200000.0
    assert got[107]["twamev"] == 100000.0


def test_the_report_takes_a_day_and_the_app_offers_one():
    import inspect
    from pathlib import Path

    import report_td as RTD
    assert "day" in inspect.signature(RTD.south_night_sms).parameters
    assert "day" in inspect.signature(RTD.build_night_sms).parameters
    src = Path("app.py").read_text()
    assert 'key="rp_sms_day"' in src and "day=(None if _sms_day is None" in src


def test_the_tab_can_answer_the_split_even_when_the_sheet_won_the_night():
    """★★ FOUND BY RUNNING THE DEPLOYED CODE AGAINST THE LIVE FEEDS. The sheet
    is now a day AHEAD of the tab, and on a night where BOTH hold the day
    "the sheet wins" would have thrown away the only split available — the
    sheet has no brand line and the bill feed has not landed yet.

    Winning the tie decides where the FIGURES come from. It must never decide
    to answer a question with nothing when another source can answer it."""
    import report_td as RTD
    sheet = pd.DataFrame([{"code": 107, "value": 600000.0, "line": ""}])
    tab = pd.DataFrame([
        {"code": 107, "date": DAY, "value": 400000.0, "line": "MANYAVAR"},
        {"code": 107, "date": DAY, "value": 200000.0, "line": "MOHEY-SAREE"},
    ])
    got = RTD.brand_split(sheet, [107], DAY, vfl_df=pd.DataFrame(), tab=tab)
    assert got[107]["manyavar"] == 400000.0 and got[107]["mohey"] == 200000.0


def test_a_tab_from_another_night_is_not_used_for_this_one():
    """★ The tab holds ONE night and is written over. Reading it for a day it
    does not cover would file one night's split against another."""
    import report_td as RTD
    sheet = pd.DataFrame([{"code": 107, "value": 600000.0, "line": ""}])
    tab = pd.DataFrame([{"code": 107, "date": DAY - pd.Timedelta(days=1),
                         "value": 400000.0, "line": "MANYAVAR"}])
    got = RTD.brand_split(sheet, [107], DAY, vfl_df=pd.DataFrame(), tab=tab)
    assert 107 not in got
