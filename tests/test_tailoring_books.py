"""The collection books — a page a store, for the accounts desk.

Every fixture is built here, so these run in CI with no Drive and no
credentials — see [[feedback-test-where-it-runs]].
"""
import pandas as pd
import pytest

import tailoring_ledger as TL

MONEY = ["billed", "due", "due_paid", "total", "cash", "card_upi"]


def _bill(code, kind, date, bill, billed, cash=0, card=0, due=0, paid=0,
          source="src1"):
    return {"store_code": code, "kind": kind, "date": pd.Timestamp(date),
            "bill_no": str(bill), "billed": float(billed), "due": float(due),
            "due_paid": float(paid), "total": float(billed - due + paid),
            "cash": float(cash), "card_upi": float(card), "done_by": "",
            "source_id": source}


def _frame(rows):
    f = pd.DataFrame(rows)
    if f.empty:
        f = pd.DataFrame(columns=["store_code", "kind", "date", "bill_no",
                                  *MONEY, "done_by", "source_id"])
        f["date"] = pd.to_datetime(f["date"])
    return f


def _source(code=107, kind="alter", sid="src1", region="South", pr="PRGK"):
    return {"store_code": code, "kind": kind, "id": sid, "region": region,
            "pr": pr, "name": f"{kind}_{code}.xlsx", "folder": ""}


def _folder(code=107, folder="107_PRGK_Grand_Kamraj_Blr", region="South"):
    return {"store_code": code, "folder": folder, "region": region, "pr": "PRGK"}


# --------------------------------------------------------------------------- #
# The shape of the page — his workbook's block, re-derived
# --------------------------------------------------------------------------- #
def test_the_year_is_april_to_march_and_all_twelve_months_are_printed():
    """★ INCLUDING THE MONTHS STILL TO COME. The shape of the page is what an
    accounts desk files, and a month that has not happened reads as dashes —
    exactly as it does in the store's own book."""
    rows, _total = TL.summary(_frame([]), "2026-09-24")
    months = [r["period"] for r in rows[2:]]
    assert len(rows) == 14                      # Today + Yesterday + 12 months
    assert months[0] == "Apr-26" and months[-1] == "Mar-27"
    assert len(months) == 12


def test_the_financial_year_turns_in_april_not_in_january():
    assert TL.fy_of("2026-03-31") == 2025
    assert TL.fy_of("2026-04-01") == 2026
    assert TL.fy_label("2026-03-31") == "FY 25-26"
    assert TL.fy_label("2026-04-01") == "FY 26-27"
    assert [f"{m:%b-%y}" for m in TL.fy_months("2026-01-15")][:2] == \
        ["Apr-25", "May-25"]


def test_today_and_yesterday_are_the_report_date_not_the_clock():
    """★ THE WHOLE REASON THIS PAGE EXISTS. The store's own Today cell is a
    live formula: the copy of Grand Kamraj's book on disk says 23 Sep and the
    same file opened the next morning says 24 Sep. An accounts record cannot
    change when you look at it, so these rows are summed from the bills against
    the date the report is run for."""
    f = _frame([_bill(107, "alter", "2026-09-24", 1, 5000, card=5000),
                _bill(107, "alter", "2026-09-23", 2, 3000, cash=3000)])
    rows, _ = TL.summary(f, "2026-09-24")
    assert rows[0]["period"].startswith("Today") and rows[0]["total"] == 5000
    assert rows[1]["period"].startswith("Yesterday") and rows[1]["total"] == 3000
    # the same book, read a day later, moves both rows down by one day
    rows, _ = TL.summary(f, "2026-09-25")
    assert rows[0]["total"] == 0 and rows[1]["total"] == 5000


def test_the_total_is_the_financial_year_and_the_months_add_up_to_it():
    f = _frame([_bill(107, "alter", "2026-05-16", 1, 4500, card=4500),
                _bill(107, "alter", "2026-06-02", 2, 8000, cash=8000, due=1000),
                _bill(107, "alter", "2026-09-23", 3, 2200, card=2200)])
    rows, total = TL.summary(f, "2026-09-24")
    months = rows[2:]
    for c in MONEY + ["bills"]:
        assert total[c] == pytest.approx(sum(r[c] for r in months)), c
    assert total["total"] == pytest.approx(4500 + 7000 + 2200)
    assert total["bills"] == 3


def test_a_bill_from_last_year_is_not_in_this_year_total():
    """The books are not reset in April; a March bill left in the file would
    otherwise inflate the year it is filed under."""
    f = _frame([_bill(107, "alter", "2026-03-30", 1, 9999, cash=9999),
                _bill(107, "alter", "2026-05-16", 2, 4500, card=4500)])
    _rows, total = TL.summary(f, "2026-09-24")
    assert total["total"] == 4500


def test_today_and_yesterday_are_not_added_into_the_total_twice():
    """They are windows onto the same bills the months already carry."""
    f = _frame([_bill(107, "alter", "2026-09-23", 1, 3000, cash=3000)])
    rows, total = TL.summary(f, "2026-09-24")
    assert rows[1]["total"] == 3000                     # yesterday
    assert total["total"] == 3000                       # and the year, once


# --------------------------------------------------------------------------- #
# The ledger under it
# --------------------------------------------------------------------------- #
def test_the_ledger_is_the_last_day_the_book_records_not_the_report_date():
    f = _frame([_bill(107, "alter", "2026-09-20", 1, 1000, cash=1000),
                _bill(107, "alter", "2026-09-23", 2, 4000, card=4000),
                _bill(107, "alter", "2026-09-23", 3, 2200, card=2200)])
    rows, total, day, kept, n = TL.ledger(f, "2026-09-24")
    assert day == pd.Timestamp("2026-09-23")
    assert n == 2 and kept == 2 and len(rows) == 2
    assert total["total"] == 6200
    assert {r["bill_no"] for r in rows} == {"2", "3"}


def test_the_ledger_never_shows_a_day_after_the_report_date():
    """A store typing tomorrow's date by mistake must not become the day the
    accounts desk is asked to reconcile."""
    f = _frame([_bill(107, "alter", "2026-09-20", 1, 1000, cash=1000),
                _bill(107, "alter", "2026-11-30", 2, 4000, card=4000)])
    _rows, _t, day, _k, _n = TL.ledger(f, "2026-09-24")
    assert day == pd.Timestamp("2026-09-20")


def test_a_long_day_is_capped_and_the_total_says_so():
    """★ THE TOTAL LINE IS THE ROWS PRINTED, NOT THE DAY. Grand Kamraj has run
    to 614 bills this year; a capped table whose total quietly covered rows it
    did not show would be a page that cannot be checked."""
    f = _frame([_bill(107, "alter", "2026-09-23", i, 1000, cash=1000)
                for i in range(30)])
    rows, total, _day, kept, n = TL.ledger(f, "2026-09-24", cap=22)
    assert n == 30 and kept == 22 and len(rows) == 22
    assert total["total"] == pytest.approx(sum(r["total"] for r in rows))


def test_an_empty_book_has_no_ledger_and_does_not_raise():
    rows, total, day, kept, n = TL.ledger(_frame([]), "2026-09-24")
    assert rows == [] and total is None and day is None and (kept, n) == (0, 0)


# --------------------------------------------------------------------------- #
# Which books get a page
# --------------------------------------------------------------------------- #
def test_only_the_books_that_recorded_on_the_day_get_a_page():
    """Manav, 24 Sep 2026: *"only show those stores whose last recorded is the
    latest day of sales … for stores which dont have that, there is no point
    for showing those previous records."* Grand Kamraj wrote on the 23rd,
    Commercial St last wrote on the 20th — one page, not two."""
    f = _frame([_bill(107, "alter", "2026-09-23", 1, 4000, card=4000),
                _bill(108, "alter", "2026-09-20", 2, 1000, cash=1000)])
    sources = [_source(107, "alter"), _source(108, "alter", "src2", pr="PRCB")]
    assert TL.latest_day(f, "2026-09-24") == pd.Timestamp("2026-09-23")
    got = TL.on_day(f, sources, TL.latest_day(f, "2026-09-24"))
    assert [(b["store_code"], b["kind"]) for b in got] == [(107, "alter")]
    _name, pdf, pages = TL.build(f, [_folder(), _folder(108, "108_PRCB_Commercial_St")],
                                 sources, asof="2026-09-24")
    assert pages == 2 and pdf                      # index + Grand Kamraj only


def test_the_day_is_the_last_one_written_in_not_the_day_the_pack_was_run():
    """★ Nobody types the morning's bills before the morning. A pack built on
    the 24th before anyone has recorded is a pack of the 23rd, not a pack of
    empty pages — the same reading as the feed's settled day."""
    f = _frame([_bill(107, "alter", "2026-09-23", 1, 4000, card=4000)])
    assert TL.latest_day(f, "2026-09-24") == pd.Timestamp("2026-09-23")
    assert TL.latest_day(f, "2026-09-30") == pd.Timestamp("2026-09-23")


def test_a_historical_date_shows_that_day_and_not_what_came_after():
    """The date picker: asked for the 20th, the pack is the 20th — the store
    that recorded on the 23rd is not in it, and the one that recorded on the
    20th is, even though it has since gone quiet."""
    f = _frame([_bill(107, "alter", "2026-09-23", 1, 4000, card=4000),
                _bill(108, "alter", "2026-09-20", 2, 1000, cash=1000)])
    sources = [_source(107, "alter"), _source(108, "alter", "src2", pr="PRCB")]
    day = TL.latest_day(f, "2026-09-20")
    assert day == pd.Timestamp("2026-09-20")
    got = TL.on_day(f, sources, day)
    assert [(b["store_code"], b["kind"]) for b in got] == [(108, "alter")]
    # and the store page reads as it read that day: nothing after the 20th
    _rows, total = TL.summary(TL._part(f, got[0]), "2026-09-20")
    assert total["total"] == 1000


def test_a_book_with_no_bills_at_all_never_gets_a_page_but_stays_on_page_one():
    """★ Fairfield and Agartala keep a file with a header and nothing under it.
    They cannot have recorded on the day, so they get no page — but dropping
    them from the index too would say those stores have no book, when what is
    true is that the book is empty."""
    f = _frame([_bill(107, "alter", "2026-09-23", 1, 4000, card=4000)])
    sources = [_source(107, "alter"), _source(101, "alter", "src2", "East & NE")]
    folders = [_folder(), _folder(101, "101_MAN_FAIRFIELD", "East & NE")]
    assert len(TL.on_day(f, sources, pd.Timestamp("2026-09-23"))) == 1
    rows, _total = TL.index_rows(f, sources, folders, "2026-09-24")
    assert {r["store"] for r in rows} == {"Grand Kamraj", "Fairfield"}
    _name, _pdf, pages = TL.build(f, folders, sources, asof="2026-09-24")
    assert pages == 2


def test_the_copy_the_tab_ignored_does_not_get_a_page():
    """Jayanagar keeps a `Copy of ALTER_PRJN` beside the live file. The reader
    already picks the one with the later bills; the pack must not then print a
    page built from the other."""
    f = _frame([_bill(112, "alter", "2026-09-20", 1, 4000, card=4000,
                      source="live")])
    sources = [_source(112, "alter", "stale"), _source(112, "alter", "live")]
    got = TL.books(sources, f)
    assert len(got) == 1 and got[0]["id"] == "live"


def test_every_index_line_is_the_same_figure_as_that_books_own_page():
    """★ THE POINT OF AN ACCOUNTS PACK. The index is summed from the same
    windows as each store page, so a line on page one and the page it refers to
    can never disagree — this pins it. (The index covers every book; only the
    books that recorded on the day get a page, so the index TOTAL is the whole
    estate's year, not the sum of the pages printed.)"""
    f = _frame([_bill(107, "alter", "2026-05-16", 1, 4500, card=4500),
                _bill(107, "parking", "2026-06-13", 2, 215, cash=215),
                _bill(110, "alter", "2026-09-23", 3, 5000, card=5000)])
    sources = [_source(107, "alter"), _source(107, "parking", "p1"),
               _source(110, "alter", "m1", pr="PRMG")]
    folders = [_folder(), _folder(110, "110_PRMG_MG_Road")]
    rows, total = TL.index_rows(f, sources, folders, "2026-09-24")
    per_page = []
    for b in TL.books(sources, f):
        _r, t = TL.summary(TL._part(f, b), "2026-09-24")
        per_page.append(t)
    for c in MONEY + ["bills"]:
        assert total[c] == pytest.approx(sum(p[c] for p in per_page)), c
    assert len(rows) == 3 and total["total"] == pytest.approx(4500 + 215 + 5000)


def test_page_one_is_two_tables_one_for_the_month_and_one_for_the_year():
    """Manav, 24 Sep: *"instead of one table for both mtd and ytd, we need 2
    tables."* Same columns, same order, one window each."""
    f = _frame([_bill(107, "alter", "2026-08-20", 1, 9000, cash=9000),
                _bill(107, "alter", "2026-09-10", 2, 4000, card=4000),
                _bill(107, "alter", "2026-09-23", 3, 2200, card=2200)])
    mrows, mtotal = TL.index_rows(f, [_source()], [_folder()], "2026-09-24",
                                  "mtd")
    yrows, ytotal = TL.index_rows(f, [_source()], [_folder()], "2026-09-24",
                                  "ytd")
    assert mrows[0]["total"] == 6200 and mrows[0]["bills"] == 2
    assert yrows[0]["total"] == 15200 and yrows[0]["bills"] == 3
    # ★ each table's own TOTAL line names its window, so a table read on its
    # own still says what it covers
    assert mtotal["book"] == "MTD" and ytotal["book"] == "YTD"
    assert mtotal["total"] == 6200 and ytotal["total"] == 15200


def test_the_month_table_starts_at_the_first_and_stops_at_the_report_date():
    f = _frame([_bill(107, "alter", "2026-08-31", 1, 7000, cash=7000),
                _bill(107, "alter", "2026-09-10", 2, 4000, card=4000),
                _bill(107, "alter", "2026-09-23", 3, 2200, card=2200)])
    rows, _t = TL.index_rows(f, [_source()], [_folder()], "2026-09-15", "mtd")
    assert rows[0]["total"] == 4000


def test_page_one_is_ordered_by_store_code_not_by_size():
    """Manav, 24 Sep: *"can you sort it store code wise, right now its money
    wise."* It is a filing document — the same store must be on the same line
    of both tables, and on the same line as it was last month."""
    f = _frame([_bill(107, "alter", "2026-09-23", 1, 99000, card=99000),
                _bill(92, "alter", "2026-09-23", 2, 1000, cash=1000),
                _bill(110, "alter", "2026-09-23", 3, 5000, card=5000)])
    sources = [_source(107, "alter"), _source(92, "alter", "s2", "East & NE"),
               _source(110, "alter", "s3", pr="PRMG")]
    folders = [_folder(), _folder(92, "92_MAN_MALDA", "East & NE"),
               _folder(110, "110_PRMG_MG_Road")]
    for span in ("mtd", "ytd"):
        rows, _t = TL.index_rows(f, sources, folders, "2026-09-24", span)
        assert [r["code"] for r in rows] == ["92", "107", "110"], span


def test_both_tables_carry_the_same_books_on_the_same_lines():
    """The point of ordering by code: the two tables are read across."""
    f = _frame([_bill(107, "alter", "2026-05-16", 1, 4500, card=4500),
                _bill(107, "parking", "2026-09-23", 2, 215, cash=215)])
    sources = [_source(107, "alter"), _source(107, "parking", "p1")]
    m, _ = TL.index_rows(f, sources, [_folder()], "2026-09-24", "mtd")
    y, _ = TL.index_rows(f, sources, [_folder()], "2026-09-24", "ytd")
    assert [r["key"] for r in m] == [r["key"] for r in y]
    # May's alteration is in the year and not in the month; parking is in both
    assert m[0]["total"] == 0 and y[0]["total"] == 4500
    assert m[1]["total"] == 215 and y[1]["total"] == 215


def test_every_index_column_is_declared_in_a_kind():
    for c, kind, _h in TL.INDEX_SPEC:
        if c in MONEY:
            assert kind == "rupee", c
    assert dict((c, k) for c, k, _h in TL.INDEX_SPEC)["bills"] == "int"
    assert set(TL.SPANS) == {"mtd", "ytd"}


def test_a_pack_dated_in_the_past_never_shows_what_came_after_it():
    """★ THE BUG THIS PINS. The first historical run printed a 20 Sep pack whose
    YTD carried bills from the 23rd and whose LAST RECORDED read 23-09-2026 —
    a date later than the pack's own. Every window ends at the report date."""
    f = _frame([_bill(107, "alter", "2026-09-10", 1, 4000, card=4000),
                _bill(107, "alter", "2026-09-23", 2, 9000, card=9000)])
    for span in ("mtd", "ytd"):
        rows, total = TL.index_rows(f, [_source()], [_folder()], "2026-09-20",
                                    span)
        assert rows[0]["total"] == 4000, span
        assert rows[0]["last"] == "10-09-2026", span
        assert total["total"] == 4000, span
    srows, stotal = TL.summary(f, "2026-09-20")
    sep = next(r for r in srows if r["period"] == "Sep-26")
    assert sep["total"] == 4000 and sep["bills"] == 1
    assert stotal["total"] == 4000


def test_a_month_that_has_not_happened_is_blank_not_a_partial_sum():
    f = _frame([_bill(107, "alter", "2026-09-10", 1, 4000, card=4000)])
    rows, _t = TL.summary(f, "2026-06-15")
    assert next(r for r in rows if r["period"] == "Sep-26")["total"] == 0
    assert next(r for r in rows if r["period"] == "Jun-26")["bills"] == 0


def test_a_book_that_never_recorded_says_never():
    f = _frame([])
    rows, _total = TL.index_rows(f, [_source(101, "alter")], [_folder(101)],
                                 "2026-09-24")
    assert rows[0]["last"] == "never"


def test_the_pack_builds_from_an_empty_estate_without_raising():
    name, pdf, pages = TL.build(_frame([]), [], [], asof="2026-09-24")
    assert pdf and pages == 1 and name.endswith(".pdf")


# --------------------------------------------------------------------------- #
# How the figures print
# --------------------------------------------------------------------------- #
def test_money_prints_in_whole_rupees_not_lakhs():
    """★ A collection book is reconciled against cash in a drawer. `4.38 L` and
    `4,38,300` are not the same statement — see
    [[feedback-declare-numeric-columns]]."""
    import festive_admin as FADM
    img = FADM.table_image([{"a": 438300.0, "b": 0.0}],
                           [("a", "rupee", "BILLED"), ("b", "rupee", "DUE")],
                           1200, font_px=24)
    assert img.width > 0
    # the formatter itself, which is what the cell prints
    import portfolio_pdf as PP
    assert PP._fmt_in(438300.0, 0) == "4,38,300"


def test_every_column_on_every_table_is_declared_in_a_kind():
    """A column in no kind falls through to `str(v)` and prints a raw float,
    left-aligned, sizing its own column. Four instances and counting."""
    known = {"text", "rupee", "int", "money", "pct", "gd", "bar"}
    for spec in (TL.SPEC, TL.LEDGER_SPEC, TL.INDEX_SPEC):
        for _c, kind, _head in spec:
            assert kind in known, (spec, kind)


def test_the_rupee_kind_dashes_a_nil_cell():
    """As the stores' own books do. A column of zeroes hides the months that
    had something in them."""
    import festive_admin as FADM
    import inspect
    src = inspect.getsource(FADM.table_image)
    assert 'if kind == "rupee"' in src and '"-"' in src


# --------------------------------------------------------------------------- #
# Where it is offered
# --------------------------------------------------------------------------- #
def _app():
    from pathlib import Path
    return Path("app.py").read_text()


def test_the_pack_is_offered_on_the_tab_and_in_the_vfl_reports_pack():
    src = _app()
    assert 'picked["books"] = st.checkbox(' in src
    assert '"books" in chosen' in src
    assert 'key="tlr_book"' in src


def test_a_drive_failure_does_not_take_the_whole_pack_down():
    src = _app()
    i = src.index('"books" in chosen')
    block = src[i:i + 900]
    assert "st.warning(" in block and "last_problem()" in block
