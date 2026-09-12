"""Every numeric column on every PDF sheet must be declared in a bucket.

The failure this guards is now four instances old: a column in none of
money/pct/num/whole falls past every branch of `cell_text` and prints as
`str(v)` — `1106344252.8109756`, left-aligned, sizing its column to eighteen
digits, beside neighbours reading `1,07,25,02,127`.

The fourth (12 Sep) was the nastiest, because nothing in the sheet's own code
was wrong. `vfl_pdf` passed the module constant `VFL_GD_MONEY` while the frame
came from `vfl_gd_cols()`, which swaps PROJECTED YTD + TTM SALES for a single
year-end column under the default-on `YEAR_END_VIEW` flag. The declared names
and the actual names had simply drifted apart.

So these tests compare the sheet's COLUMN LIST against its BUCKETS directly.
No data and no rendering required — which means they also run in CI, where the
feed is absent and a render-based test would skip exactly when it is needed.
"""
import os

import pytest

# Identity columns: text, deliberately in no numeric bucket. Anything NOT
# listed here and not in a bucket is the bug.
VFL_IDENTITY = {"Region", "Master Location", "STORE CODE", "MEN/WOMEN/KIDS",
                "STORE NAME", "LOCATION", "DOO"}


def _undeclared(cols, *buckets):
    declared = set().union(*[set(b) for b in buckets]) | VFL_IDENTITY
    return [c for c in cols if c not in declared]


@pytest.mark.parametrize("year_end", ["1", "0"])
def test_vfl_gd_sheet_declares_every_column(monkeypatch, year_end):
    """Both states of the flag. A feature behind a default-on flag is untested
    in the other direction until something flips it, and `YEAR_END_VIEW=0` is
    the documented one-word revert — it has to stay correct too."""
    monkeypatch.setenv("YEAR_END_VIEW", year_end)
    import importlib

    import loader as L
    import yearend as YE
    importlib.reload(YE)
    importlib.reload(L)

    missing = _undeclared(L.vfl_gd_cols(), L.vfl_gd_money(), L.VFL_GD_PCT)
    assert not missing, (
        f"YEAR_END_VIEW={year_end}: {missing} appear on the VFL G/D sheet but "
        f"in none of money/pct — they will print as raw floats"
    )


@pytest.mark.parametrize("year_end", ["1", "0"])
def test_vfl_pdf_passes_the_resolved_money_list(monkeypatch, year_end):
    """The actual regression: vfl_pdf must use vfl_gd_money(), not the raw
    VFL_GD_MONEY constant. Asserted against the source so it cannot silently
    revert to the constant during a refactor."""
    monkeypatch.setenv("YEAR_END_VIEW", year_end)
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "vfl_pdf.py"
    body = src.read_text()
    assert "money=L.vfl_gd_money()" in body
    assert "money=L.VFL_GD_MONEY" not in body, (
        "vfl_pdf is passing the unswapped module constant again; under "
        "YEAR_END_VIEW the frame carries a column that list does not name"
    )


def test_vfl_gender_sheets_declare_every_column():
    import loader as L
    for name, cols in (("gender", L.VFL_GENDER_COLS), ("summary", L.VFL_GSUM_COLS)):
        missing = _undeclared(cols, L.VFL_GENDER_MONEY, L.VFL_GENDER_PCT)
        assert not missing, f"VFL {name} sheet: {missing} declared in no bucket"


@pytest.mark.parametrize("year_end", ["1", "0"])
def test_portfolio_gd_money_list_covers_the_year_end_column(monkeypatch, year_end):
    """The portfolio side is already safe because its lists name the year-end
    column AND the old pair, then filter to what is present. Pinning that so a
    tidy-up does not remove the belt and leave only the braces."""
    monkeypatch.setenv("YEAR_END_VIEW", year_end)
    import importlib

    import portfolio_pdf as PP
    importlib.reload(PP)

    for bucket in (PP._MONEY, PP._AVG_MONEY):
        assert PP.YE_COL in bucket
        assert "Sum of PROJECTED YTD" in bucket or "Sum of TTM SALES" in bucket


def test_the_undeclared_column_warning_still_fires():
    """The safety net itself. If this stops warning, every test above becomes
    the only thing standing between a new column and a printed raw float."""
    import warnings

    import pandas as pd

    import portfolio_pdf as PP

    df = pd.DataFrame({"Store": ["A"], "Mystery": [1106344252.8109756]})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always", RuntimeWarning)
        m = PP._measure_table(df, money=[], pct=[], font_px=20, header_px=18)
    assert any("Mystery" in str(x.message) for x in w)
    assert m["txt"][0][1] == "1106344252.8109756"  # the exact failure mode


def test_a_declared_money_column_prints_grouped_and_whole():
    """What the fix produces: Indian grouping, no decimals, matching every
    other money column on the sheet."""
    import pandas as pd

    import portfolio_pdf as PP

    df = pd.DataFrame({"Sum of YEAR END PROJECTED/TTM": [1106344252.8109756]})
    m = PP._measure_table(df, money=["Sum of YEAR END PROJECTED/TTM"],
                          money_dp=0, font_px=20, header_px=18)
    assert m["txt"][0][0] == "1,10,63,44,253"


# The drivers sheets feed the morning A4s and the snapshot PNGs. They were
# clean when this was written; the point of pinning them is that they are the
# other family of sheets built from resolved-at-runtime bucket lists.
DRIVERS_IDENTITY = {"DATE", "Region", "STORE CODE", "LOCATION", "Brand",
                    "Division", "Section", "Department"}


@pytest.mark.parametrize("kind", ["DAY", "MTD", "YTD"])
def test_drivers_sheets_declare_every_numeric_column(kind):
    import loader as L
    declared = set(L.drivers_money(kind)) | set(L.DRIVERS_PCT) | DRIVERS_IDENTITY
    missing = [c for c in L.drivers_cols(kind) if c not in declared]
    assert not missing, (
        f"drivers/{kind}: {missing} are in no bucket and not known identity "
        f"columns — they will print as raw floats on the morning sheets"
    )
