"""Targets come from the `Targets New` tab, and month columns survive their case.

Manav, 18 Aug 2026: "i have added a new targets new sheet which is the source of
truth now for all target related calculations".

The bug these pin: the tab writes APR…MAR in capitals, this module named them
Apr…Mar, and `m in d.columns` was False twelve times over. Every month target
came back empty — the night SMS and target-vs-achievement printed no MTD or YTD
target at all — while `YEAR TARGET` matched exactly and kept the feed looking
healthy. Nothing raised, nothing was logged.
"""

import pandas as pd
import pytest

import targets as TG


def _tab(**over):
    """A targets tab shaped like the real one: capitals, blanks, brand lines."""
    row = {"CODE": "107", "VFL NAME": "GRAND", "YEAR TARGET": "1,00,00,000",
           "APR": "10,00,000", "MAY": "12,00,000", "JUN": "", "JUL": "-",
           "AUG": "15,00,000", "SEP": "", "OCT": "", "NOV": "", "DEC": "",
           "JAN": "", "FEB": "", "MAR": ""}
    row.update(over)
    return pd.DataFrame([row])


def _write(tmp_path, df, name="t.csv"):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return str(p)


def test_month_columns_load_though_the_tab_shouts_them(tmp_path):
    got = TG.load(_write(tmp_path, _tab()))
    assert got is not None
    assert float(got.loc[0, "Apr"]) == 1_000_000
    assert float(got.loc[0, "Aug"]) == 1_500_000
    assert float(got.loc[0, "year"]) == 10_000_000


def test_title_case_headers_still_work(tmp_path):
    """The case fix must not swap one exclusive spelling for another."""
    d = _tab().rename(columns={"APR": "Apr", "AUG": "Aug"})
    got = TG.load(_write(tmp_path, d))
    assert float(got.loc[0, "Apr"]) == 1_000_000
    assert float(got.loc[0, "Aug"]) == 1_500_000


def test_blank_and_dash_are_absent_not_zero(tmp_path):
    """A month left blank must yield nothing, never a target of zero — a zero
    target makes achievement read as infinite rather than as unknown."""
    got = TG.load(_write(tmp_path, _tab()))
    assert pd.isna(got.loc[0, "Jun"])       # blank
    assert pd.isna(got.loc[0, "Jul"])       # a dash


def test_a_tab_with_no_month_columns_says_so(tmp_path):
    """The exact failure that went unnoticed: year target fine, months gone."""
    d = _tab()[["CODE", "VFL NAME", "YEAR TARGET"]]
    got = TG.load(_write(tmp_path, d))
    assert got is not None                       # the year target still loads
    assert all(pd.isna(got.loc[0, m]) for m in
               ("Apr", "May", "Jun", "Jul", "Aug"))
    assert TG.last_problem(), "a silent month-less tab must name itself"
    assert "month" in TG.last_problem().lower()


def test_one_missing_month_is_named(tmp_path):
    d = _tab().drop(columns=["AUG"])
    TG.load(_write(tmp_path, d))
    assert "Aug" in (TG.last_problem() or "")


def test_a_tab_that_is_not_targets_is_refused(tmp_path):
    """gviz answers a wrong sheet name with the workbook's FIRST tab, which is
    transactions. Refusing on missing CODE / YEAR TARGET is what stops that
    becoming a configuration that looks like it works."""
    d = pd.DataFrame([{"Bill No": "1", "Division": "MOHEY", "Sales": "100"}])
    assert TG.load(_write(tmp_path, d)) is None
    assert TG.last_problem()


def test_targets_are_summed_once_per_store(tmp_path):
    """The figure sits on one brand line and the others are blank."""
    d = pd.concat([_tab(), _tab(**{"YEAR TARGET": "", "APR": "", "MAY": "",
                                   "AUG": "5,00,000"})], ignore_index=True)
    got = TG.load(_write(tmp_path, d))
    assert len(got) == 1
    assert float(got.loc[0, "Aug"]) == 2_000_000
    assert float(got.loc[0, "year"]) == 10_000_000


def test_the_superseded_tab_is_never_addressed():
    """`Targets New` is the source of truth; the old `Targets` gid must not
    survive as a fallback, or a divergence would be served silently."""
    import inspect
    assert TG._SHEET == "Targets New"
    assert not hasattr(TG, "_GID")
    assert "1007333059" not in inspect.getsource(TG._candidates)
