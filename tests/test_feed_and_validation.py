"""The two guards: a reader that names its failure, and a gate that refuses.

Everything here runs on local files and synthetic frames — no sheet, no secret,
no network — so CI can run it on every push.
"""

import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feed            # noqa: E402
import validation as V  # noqa: E402


# --------------------------------------------------------------------------- #
# feed — reading, and saying why not
# --------------------------------------------------------------------------- #
def _tmp(name, text):
    p = os.path.join(tempfile.mkdtemp(), name)
    with open(p, "w") as f:
        f.write(text)
    return p


def test_a_good_csv_reads():
    p = _tmp("ok.csv", "Bill Date,Bill Amount\n01/04/2026,100\n")
    df = feed.read_csv(p, expect=("Bill Date", "Bill Amount"))
    assert len(df) == 1


def test_a_sign_in_page_is_refused_not_parsed():
    """What a revoked or unpublished sheet actually serves. Parsed, it becomes
    a one-column frame that fails much later as a KeyError."""
    p = _tmp("login.html", "<!DOCTYPE html>\n<html><title>Sign in</title></html>")
    try:
        feed.read_csv(p, what="the sheet")
        assert False, "an HTML page was accepted as data"
    except feed.FeedError as e:
        assert "web page, not a CSV" in str(e), e


def test_a_missing_column_names_what_was_found():
    """The gid-less URL case: the workbook's FIRST tab comes back instead."""
    p = _tmp("wrongtab.csv", "Sr No,SHORT_NAME,Bill Date\n1,X,01/04/2026\n")
    try:
        feed.read_csv(p, expect=("CODE", "Date"), what="the night fill")
        assert False, "the wrong tab was accepted"
    except feed.FeedError as e:
        msg = str(e)
        assert "no CODE, Date column" in msg, msg
        assert "Sr No" in msg and "gid" in msg, msg


def test_an_empty_body_is_refused():
    p = _tmp("empty.csv", "   \n")
    try:
        feed.read_csv(p)
        assert False, "an empty response was accepted"
    except feed.FeedError as e:
        assert "empty" in str(e).lower(), e


def test_the_cause_is_named_in_words():
    class R:
        status_code = 403

    class E(Exception):
        response = R()

    assert "sharing" in feed._why("u", E("403 Client Error"))
    assert "not found" in feed._why("u", Exception("404 Client Error: Not Found"))
    assert "in time" in feed._why("u", Exception("Read timed out"))


# --------------------------------------------------------------------------- #
# validation — refusing, and warning
# --------------------------------------------------------------------------- #
def _frame(rows=1000, stores=20, day="2026-08-13", total_each=100.0):
    return pd.DataFrame({
        "date": [pd.Timestamp(day)] * rows,
        "store": [f"S{i % stores}" for i in range(rows)],
        "sales": [total_each] * rows,
    })


def _fresh_state():
    V._STATE = os.path.join(tempfile.mkdtemp(), "state.json")


def _check(df, **kw):
    return V.validate(df, "test", date_col="date", store_col="store",
                      value_col="sales", today=pd.Timestamp("2026-08-13"), **kw)


def test_a_good_feed_passes_quietly():
    _fresh_state()
    r = _check(_frame())
    assert r.ok and not r.warnings, (r.problems, r.warnings)


def test_an_empty_feed_is_refused():
    _fresh_state()
    r = _check(_frame().iloc[:0])
    assert not r.ok and "empty" in r.problems[0]


def test_a_missing_column_is_refused():
    _fresh_state()
    r = _check(_frame().drop(columns=["sales"]))
    assert not r.ok and "sales" in r.problems[0]


def test_a_date_in_the_future_is_refused():
    """The day/month trap: 12 August read as 8 December once, silently."""
    _fresh_state()
    df = _frame()
    df.loc[df.index[0], "date"] = pd.Timestamp("2026-12-08")
    r = _check(df)
    assert not r.ok and "future" in r.problems[0]


def test_a_truncated_export_is_refused_against_the_last_good_load():
    """The incident that already happened: 265k rows became 143k."""
    _fresh_state()
    assert _check(_frame(rows=1000)).ok
    r = _check(_frame(rows=540))
    assert not r.ok, r.problems
    assert "lost" in r.problems[0] and "540" in r.problems[0]


def test_a_dropped_store_warns_but_still_serves():
    """Stores do close, so this must not block — but it must be said."""
    _fresh_state()
    assert _check(_frame(stores=20)).ok
    r = _check(_frame(stores=17))
    assert r.ok, r.problems
    assert any("stopped appearing" in w for w in r.warnings), r.warnings


def test_fewer_stores_than_the_master_warns():
    _fresh_state()
    r = _check(_frame(stores=19), expect_stores=22)
    assert r.ok
    assert any("store master" in w for w in r.warnings), r.warnings


def test_stale_data_warns():
    _fresh_state()
    r = _check(_frame(day="2026-08-01"))
    assert r.ok
    assert any("days old" in w for w in r.warnings), r.warnings


def test_a_refused_load_does_not_become_the_baseline():
    """Otherwise a bad load silently rebases the check and the next one passes."""
    _fresh_state()
    _check(_frame(rows=1000))
    _check(_frame(rows=200))                     # refused
    r = _check(_frame(rows=300))                 # still measured against 1000
    assert not r.ok, "a refused load was allowed to move the baseline"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                failed += 1
                print(f"  FAIL  {name}: {e}")
    print("all passed" if not failed else f"{failed} failed")
    sys.exit(1 if failed else 0)
