"""The VFL provisional day, typed into Peanuts Total at night.

Manav, 28 Sep 2026: *"yes, make a provisional thing"* — after being told that
typing peanuts total at night moved no VFL report, because the only VFL night
path was the Tinku tab, retired on 27 Sep.

Frames are built here, so these run in CI with no sheet and no network —
see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import loader as L
import night_fill as NF

VFL_LAST = pd.Timestamp("2026-09-26")
NIGHT = pd.Timestamp("2026-09-27")


@pytest.fixture(autouse=True)
def _master(monkeypatch):
    """112 and 107 are VFL stores; 900 is a portfolio-only store."""
    m = pd.DataFrame({"code": [112, 107, 900],
                      "tableau_name": ["Jayanagar", "Grand Kamraj", None]})
    monkeypatch.setattr(L, "load_store_master", lambda: m)


def _raw(last=VFL_LAST):
    """The VFL sheet as read: strings, month-first, product-level divisions,
    and store names WITH the "Peanuts - " prefix the master does not carry."""
    rows = []
    for back in range(10):
        d = (last - pd.Timedelta(days=back)).strftime("%m/%d/%Y")
        rows += [
            {L.COL_STORE: "Peanuts - Jayanagar", L.COL_DATE: d,
             L.COL_AMOUNT: "7,000", L.COL_DIVISION: "KURTA SET"},
            {L.COL_STORE: "Peanuts - Jayanagar", L.COL_DATE: d,
             L.COL_AMOUNT: "2,000", L.COL_DIVISION: "MOHEY-SAREE"},
            {L.COL_STORE: "Peanuts - Jayanagar", L.COL_DATE: d,
             L.COL_AMOUNT: "1,000", L.COL_DIVISION: "TWAMEV-MEN"},
            {L.COL_STORE: "Peanuts - Grand Kamraj", L.COL_DATE: d,
             L.COL_AMOUNT: "5,000", L.COL_DIVISION: "KURTA SET"},
        ]
    return pd.DataFrame(rows)


def _pf(days=(NIGHT,), totals=None):
    totals = totals or {112: "1,00,000.00", 107: "50,000.00", 900: "9,999.00"}
    rows = []
    for d in days:
        for code, tot in totals.items():
            rows.append({"code": code, "Total": tot, "QTY": "20", "date": d})
    return pd.DataFrame(rows)


def _by(out, store):
    s = out[out[L.COL_STORE] == store]
    return s.groupby(L.brand_line_vfl(s))[L.COL_AMOUNT].sum().to_dict()


# --------------------------------------------------------------------------- #
# When it adds anything at all
# --------------------------------------------------------------------------- #
def test_a_night_newer_than_the_vfl_sheet_is_added():
    out, _ = NF.vfl_rows_from_portfolio(_raw(), _pf(), splits={})
    assert out is not None
    assert set(out[L.COL_DATE]) == {"09/27/2026"}      # month-first, like the sheet
    assert out[NF._PROVISIONAL_COL].all()
    assert out[L.COL_BILL].isna().all()                # no invented bills
    assert (out[L.COL_SALESPERSON] == "(PROVISIONAL)").all()


def test_a_day_the_vfl_sheet_already_has_is_left_alone():
    """★ Forward-only: the moment Tableau lands a day, this stands aside."""
    out, est = NF.vfl_rows_from_portfolio(_raw(last=NIGHT), _pf(), splits={})
    assert out is None and est == []


def test_every_missing_day_is_added_not_just_the_newest():
    """A VFL sheet two days behind would otherwise lose the middle day from
    MTD without a word."""
    out, _ = NF.vfl_rows_from_portfolio(
        _raw(last=pd.Timestamp("2026-09-25")),
        _pf(days=(pd.Timestamp("2026-09-26"), NIGHT)), splits={})
    assert set(out[L.COL_DATE]) == {"09/26/2026", "09/27/2026"}


def test_only_vfl_stores_and_only_typed_ones():
    pf = _pf(totals={112: "1,00,000.00", 107: "", 900: "9,999.00"})
    out, _ = NF.vfl_rows_from_portfolio(_raw(), pf, splits={})
    assert set(out[L.COL_STORE]) == {"Jayanagar"}      # 107 blank, 900 not VFL


# --------------------------------------------------------------------------- #
# The money: peanuts total, to the rupee
# --------------------------------------------------------------------------- #
def test_each_store_ties_to_peanuts_total():
    out, _ = NF.vfl_rows_from_portfolio(_raw(), _pf(), splits={})
    got = out.groupby(L.COL_STORE)[L.COL_AMOUNT].sum()
    assert got["Jayanagar"] == pytest.approx(100000)
    assert got["Grand Kamraj"] == pytest.approx(50000)


def test_pieces_tie_to_the_typed_qty():
    out, _ = NF.vfl_rows_from_portfolio(_raw(), _pf(), splits={})
    got = out.groupby(L.COL_STORE)[L.COL_QTY].sum()
    assert got["Jayanagar"] == pytest.approx(20)


# --------------------------------------------------------------------------- #
# The brand split: the form if filed, else the store's own recent mix
# --------------------------------------------------------------------------- #
def test_a_filed_split_is_used_and_scaled_to_the_total():
    """The form said 60/30/10 thousand but peanuts total says 1,00,000 — the
    shares come from the form, the money from peanuts total."""
    splits = {(112, NIGHT): {"manyavar": 60000, "mohey": 30000, "twamev": 10000}}
    pf = _pf(totals={112: "1,20,000.00"})
    out, est = NF.vfl_rows_from_portfolio(_raw(), pf, splits=splits)
    b = _by(out, "Jayanagar")
    assert b["MANYAVAR"] == pytest.approx(72000)
    assert b["MOHEY"] == pytest.approx(36000)
    assert b["TWAMEV MEN"] == pytest.approx(12000)     # store's twamev is all men
    assert 112 not in est


def test_unfiled_falls_back_to_the_stores_own_mix_and_says_so():
    out, est = NF.vfl_rows_from_portfolio(_raw(), _pf(), splits={})
    b = _by(out, "Jayanagar")                          # history is 70/20/10
    assert b["MANYAVAR"] == pytest.approx(70000)
    assert b["MOHEY"] == pytest.approx(20000)
    assert b["TWAMEV MEN"] == pytest.approx(10000)
    assert est == [107, 112]


def test_provisional_divisions_read_as_the_right_brand_everywhere():
    """The division labels must fold into the right brand in BOTH readers, and
    must not land on a real product division — "MANYAVAR" alone is aliased to
    MANYAVAR ACCESSORIES and would inflate it."""
    out, _ = NF.vfl_rows_from_portfolio(_raw(), _pf(), splits={})
    for div in out[L.COL_DIVISION]:
        assert "PROVISIONAL" in div
        assert div not in L.DIVISION_ALIASES
    brands = {L._brand_of(d) for d in NF._PROV_DIVISION.values()}
    assert brands == {"Manyavar", "Mohey", "Twamev"}


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #
def test_load_data_uses_peanuts_total_and_can_be_switched_off(monkeypatch):
    seen = {}

    def fake(raw, pf, splits=None):
        seen["pf"] = pf
        return None, []
    monkeypatch.setattr(L, "_read_raw", lambda: _raw())
    monkeypatch.setattr(NF, "vfl_rows_if_newer", lambda raw, url=None: None)
    monkeypatch.setattr(NF, "vfl_rows_from_portfolio", fake)
    monkeypatch.setattr(L, "clean", lambda raw: raw.assign(date=VFL_LAST))
    monkeypatch.setattr(L, "_apply_takeover_filter", lambda d: d)
    monkeypatch.setattr(L, "_enrich", lambda d: d)
    pf = _pf()
    df = L.load_data(pf=pf)
    assert seen["pf"] is pf and df.attrs["provisional_date"] is None
    seen.clear()
    L.load_data(pf=None)
    assert "pf" not in seen                            # None means off
