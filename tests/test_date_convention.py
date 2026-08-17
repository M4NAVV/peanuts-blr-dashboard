"""A date column must prove which way round it is written.

The two feeds disagree — the VFL export writes month first, the portfolio sheet
writes day first — and each loader used to declare its own format and hand
anything that failed to flexible inference. Simulated on the live VFL feed, a
source that switched convention gives:

    parsed but WRONG   17,664 of 50,000   (35%)
    failed to parse             0

Nothing fails, because the 13th to the 31st cannot be read the wrong way round
and land correctly. The frame looks healthy and a third of the year sits on the
wrong day. These tests pin the detection that turns that into a refusal.

Runs on synthetic frames — no sheet, no network:

    python tests/test_date_convention.py     (or: python -m pytest tests -q)
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dates as D                      # noqa: E402


def _col(strings):
    return pd.Series(list(strings))


def test_a_column_proves_day_first():
    """13/04 can only be the 13th of April."""
    found, e = D.detect(_col(["13/04/2026", "01/04/2026", "05/06/2026"]))
    assert found == D.DAY_FIRST
    assert e["day"] == 1 and e["month"] == 0 and e["ambiguous"] == 2


def test_a_column_proves_month_first():
    """04/13 can only be April the 13th."""
    found, e = D.detect(_col(["04/13/2026", "04/01/2026", "06/05/2026"]))
    assert found == D.MONTH_FIRST
    assert e["month"] == 1 and e["day"] == 0


def test_an_all_ambiguous_column_proves_nothing():
    found, e = D.detect(_col(["01/04/2026", "05/06/2026"]))
    assert found is None and e["ambiguous"] == 2


def test_a_column_written_both_ways_is_refused():
    """Two conventions in one column can only be guessed at."""
    s = _col(["13/04/2026", "04/13/2026", "01/02/2026"])
    found, e = D.detect(s)
    assert found is None and e["day"] and e["month"]
    D.parse(s, expect=D.DAY_FIRST, label="mixedtest")
    assert any("BOTH ways round" in p for p in D.problems("mixedtest"))


def test_a_feed_that_changed_convention_is_refused_not_absorbed():
    """The whole point: it parses correctly AND says the source changed."""
    s = _col(["13/04/2026", "14/04/2026", "01/04/2026"])   # day-first...
    out = D.parse(s, expect=D.MONTH_FIRST, label="flipped")  # ...expected month
    assert out.iloc[0] == pd.Timestamp(2026, 4, 13), "read the way the data proves"
    assert out.iloc[2] == pd.Timestamp(2026, 4, 1)
    probs = D.problems("flipped")
    assert probs and "writes day first" in probs[0]


def test_the_expected_convention_is_used_when_nothing_proves_otherwise():
    s = _col(["01/04/2026", "02/04/2026"])
    out = D.parse(s, expect=D.DAY_FIRST, label="quiet")
    assert out.iloc[0] == pd.Timestamp(2026, 4, 1), "day-first as declared"
    assert not D.problems("quiet")
    assert any("proves which way" in w for w in D.warnings("quiet"))


def test_a_stray_separator_is_read_on_the_same_convention():
    """One row of the portfolio sheet was once written 11-08-2026 among slashes."""
    out = D.parse(_col(["13/08/2026", "11-08-2026"]), expect=D.DAY_FIRST,
                  label="dashes")
    assert out.iloc[1] == pd.Timestamp(2026, 8, 11)
    assert D.last("dashes")["unreadable"] == 0


def test_iso_dates_parse_and_prove_nothing():
    out = D.parse(_col(["2026-08-13", "2026-08-11"]), expect=D.DAY_FIRST,
                  label="iso")
    assert out.iloc[0] == pd.Timestamp(2026, 8, 13)
    assert D.last("iso")["unreadable"] == 0


def test_unreadable_rows_are_counted_not_swallowed():
    """They are dropped downstream; something has to say how many."""
    D.parse(_col(["13/08/2026"] * 50 + ["banana"] * 5), expect=D.DAY_FIRST,
            label="junk")
    r = D.last("junk")
    assert r["unreadable"] == 5
    assert any("could not be read" in p for p in D.problems("junk"))


def test_blanks_are_not_counted_as_unreadable():
    D.parse(_col(["13/08/2026", "", "nan"]), expect=D.DAY_FIRST, label="blanks")
    r = D.last("blanks")
    assert r["blank"] == 2 and r["unreadable"] == 0
    assert not D.problems("blanks")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
    print("all date-convention tests passed")
