"""The team detail sheet splits into who is selling and who has stopped.

Manav, 26 Sep 2026: *"if the staff MTD sales or YTD sales is 0, then u can move
them to another table … meaning that they are probably not working for us
anymore … u can A to Z sort both tables. there will be 2 subtotals, and then a
grand total."*
"""
import pandas as pd
import pytest

import loader as L
import salespeople as SP

STORE = "Jayanagar"
ASOF = pd.Timestamp("2026-09-25")


def _feed(rows):
    f = pd.DataFrame([{"date": pd.Timestamp(d), L.COL_STORE_LABEL: STORE,
                       "SALESPERSON_NO": who, L.COL_SALESPERSON: who,
                       L.COL_BILL_UID: bill, L.COL_AMOUNT: float(amt),
                       "Bill Quantity": 1.0} for d, who, bill, amt in rows])
    f["date"] = pd.to_datetime(f["date"])
    return f


def _table(f, asof=ASOF):
    rows, types, meta = SP.store_table(L, f, asof, STORE)
    people = [r for r, t in zip(rows, types) if t == "person"]
    return people, rows[types.index("subtotal")]


# --------------------------------------------------------------------------- #
# The rule
# --------------------------------------------------------------------------- #
def test_no_month_or_no_year_moves_a_person_to_the_second_table():
    """His rule as he gave it: a month OR a year at zero."""
    rows = [("2026-09-24", "WORKING", "b1", 500),      # month and year
            ("2026-05-02", "LEFTINMAY", "b2", 900),    # year only, no month
            ("2026-09-24", "BOTH", "b3", 100), ("2026-04-02", "BOTH", "b4", 100)]
    people, _t = _table(_feed(rows))
    selling, gone = SP.split_team(people)
    assert {r["who"].upper() for r in selling} == {"WORKING", "BOTH"}
    assert {r["who"].upper() for r in gone} == {"LEFTINMAY"}


def test_a_year_of_nothing_but_returns_counts_as_nothing():
    """★ ZERO MEANS "NO SALE TO SHOW", SO NEGATIVE GOES WITH IT — the same
    reading the red rows on this sheet already use (Manav, 9 Sep). Shoaib
    Akther at −9,998 would otherwise sit in the working table on a
    technicality."""
    people, _t = _table(_feed([("2026-09-24", "RETURNS", "b1", -9998),
                               ("2026-09-24", "REAL", "b2", 500)]))
    selling, gone = SP.split_team(people)
    assert [r["who"].upper() for r in gone] == ["RETURNS"]
    assert [r["who"].upper() for r in selling] == ["REAL"]


def test_the_standard_order_is_biggest_month_first():
    """Manav, 26 Sep: *"MTD sorting becomes the standard."* He asked for A–Z
    when the split was built, saw both, and chose this — on a sheet whose first
    column is the month RANK, alphabetical order was the one thing fighting
    it."""
    rows = [("2026-09-24", "SMALL", "b1", 100), ("2026-09-24", "BIG", "b2", 900),
            ("2026-09-24", "MID", "b3", 500)]
    people, _t = _table(_feed(rows))
    selling, _gone = SP.split_team(people)            # no order argument
    assert [r["who"].upper() for r in selling] == ["BIG", "MID", "SMALL"]
    import inspect
    assert inspect.signature(SP.detailed_sheet).parameters["order"].default == "mtd"
    assert inspect.signature(SP.split_team).parameters["order"].default == "mtd"


def test_a_month_of_returns_sorts_below_a_month_of_nothing():
    """A month that went backwards is worse than a month that never started,
    and it belongs where the eye lands last."""
    rows = [("2026-05-02", "ZEROED", "b1", 700),
            ("2026-09-24", "RETURNS", "b2", -5000),
            ("2026-05-02", "RETURNS", "b3", 6000)]
    people, _t = _table(_feed(rows))
    _selling, gone = SP.split_team(people)
    assert [r["who"].upper() for r in gone] == ["ZEROED", "RETURNS"]


def test_ties_are_broken_alphabetically_so_the_sheet_does_not_shuffle():
    """★ In the gone table almost everyone is on zero. Without a tie-break they
    swap places between one run and the next, and a sheet printed every morning
    must not move for no reason."""
    rows = [("2026-05-02", w, f"b{i}", 500)
            for i, w in enumerate(["ZARA", "AMIT", "MOHAN"])]
    people, _t = _table(_feed(rows))
    _selling, gone = SP.split_team(people)
    assert [r["who"].upper() for r in gone] == ["AMIT", "MOHAN", "ZARA"]


def test_a_to_z_is_still_available_for_looking_somebody_up():
    rows = [("2026-09-24", w, f"b{i}", 500)
            for i, w in enumerate(["ZARA", "AMIT", "MOHAN"])]
    rows += [("2026-05-02", w, f"c{i}", 500)
             for i, w in enumerate(["ZEBA", "ANIL", "MANOJ"])]
    people, _t = _table(_feed(rows))
    selling, gone = SP.split_team(people, order="az")
    assert [r["who"].upper() for r in selling] == ["AMIT", "MOHAN", "ZARA"]
    assert [r["who"].upper() for r in gone] == ["ANIL", "MANOJ", "ZEBA"]


def test_everybody_lands_in_exactly_one_table():
    people, _t = _table(_feed([("2026-09-24", "A", "b1", 500),
                               ("2026-05-02", "B", "b2", 500),
                               ("2026-09-24", "C", "b3", 0)]))
    selling, gone = SP.split_team(people)
    assert len(selling) + len(gone) == len(people)
    assert not ({id(r) for r in selling} & {id(r) for r in gone})


# --------------------------------------------------------------------------- #
# The three totals
# --------------------------------------------------------------------------- #
def test_the_two_subtotals_add_up_to_the_grand_total():
    """★ THE FIRST THING HE WILL CHECK. Sales and pieces are attributed line by
    line, so the two groups must close on the store."""
    f = _feed([("2026-09-24", "A", "b1", 5000), ("2026-09-20", "A", "b2", 3000),
               ("2026-05-02", "B", "b3", 900), ("2026-09-24", "C", "b4", 100)])
    people, grand = _table(f)
    selling, gone = SP.split_team(people)
    settled = f["date"].max()
    a = SP.group_total(L, f, ASOF, STORE, [r["id"] for r in selling], "A",
                       settled=settled)
    b = SP.group_total(L, f, ASOF, STORE, [r["id"] for r in gone], "B",
                       settled=settled)
    for t in ("w", "m", "y"):
        assert (a[f"{t}_sales"] + b[f"{t}_sales"]
                == pytest.approx(grand[f"{t}_sales"])), t
        assert (a[f"{t}_units"] + b[f"{t}_units"]
                == pytest.approx(grand[f"{t}_units"])), t


def test_a_groups_ratios_use_that_groups_distinct_bills():
    """★ NOT A SUM OF THE ROWS ABOVE IT. Two salespeople on one bill is ONE
    bill, so an ABV summed from their rows divides by two and halves itself —
    the 19-against-18 error this sheet has already been bitten by."""
    f = _feed([("2026-09-24", "A", "shared", 600),
               ("2026-09-24", "B", "shared", 400)])
    people, _g = _table(f)
    selling, _gone = SP.split_team(people)
    got = SP.group_total(L, f, ASOF, STORE, [r["id"] for r in selling], "A")
    assert got["w_sales"] == 1000.0
    assert got["w_abv"] == pytest.approx(1000.0)      # one bill, not two


def test_a_group_nobody_is_in_has_no_subtotal_rather_than_a_row_of_zeros():
    f = _feed([("2026-09-24", "A", "b1", 500)])
    people, _g = _table(f)
    _selling, gone = SP.split_team(people)
    assert gone == []
    assert SP.group_total(L, f, ASOF, STORE, [], "B") is None


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #
def test_the_sheet_stays_one_page_with_two_headers():
    """★ THE REGRESSION THIS COST. `_fit_table` sized the type against ONE
    column header while the page draws two — and a one-page report quietly
    became two. Both loops in it must count the headers the page will draw."""
    import inspect
    src = inspect.getsource(SP._fit_table)
    assert src.count("1 + extra_headers") == 2
    assert "extra_headers=1 if left_over else 0" in \
        inspect.getsource(SP.detailed_sheet)


def test_a_star_is_never_given_to_somebody_in_the_gone_table():
    """Two statements about one person that cannot both be acted on."""
    import inspect
    src = inspect.getsource(SP.detailed_sheet)
    assert "won = _stars(selling)" in src
    assert "_stars(people)" not in src


def test_the_page_says_the_second_table_is_a_signal_not_a_record():
    """★ Nothing in this feed knows who is EMPLOYED — it knows who BILLED.
    Somebody on leave lands there too, and the page has to say so.
    See [[feedback-silent-failure-must-speak]]."""
    import inspect
    src = inspect.getsource(SP.detailed_sheet)
    assert "SIGNAL, not a record" in src
    assert "who BILLED, not who is employed" in src


def test_the_split_renders_on_the_real_feed_as_one_page():
    try:
        df = L.load_data()
    except Exception as e:
        pytest.skip(f"live data unavailable: {type(e).__name__}")
    asof = L.as_of(df)
    for name in df[L.COL_STORE_LABEL].dropna().unique()[:6]:
        out = SP.detailed_sheet(L, df, asof, name, code=None)
        if out is None:
            continue
        _f, _pdf, _font, pages, _team = out
        assert pages == 1, f"{name} spilled to {pages} pages"
