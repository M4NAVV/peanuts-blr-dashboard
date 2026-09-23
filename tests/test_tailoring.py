"""Reading the store-kept alteration workbooks.

Workbooks are built inside the test, so CI verifies the rules with no Drive and
no credentials — see [[feedback-test-where-it-runs]].
"""
import datetime as dt

import pandas as pd
import pytest

import tailoring as T

HDR = ["Date", "Month", "Bill No", "Billed Amount", "Due Amount", "Due Paid",
       "Total", "Cash", "Card/Upi"]
HDR_MG = HDR[:6] + ["InHouse or Suhail"] + HDR[6:]      # M.G. Road's variant


def _book(tmp_path, header, rows, preamble=12, name="PRGK"):
    """A workbook shaped like the real ones: a summary block, then the table."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = name
    ws.append(["Tailor Collection"])
    for i in range(preamble):                    # Today/Yesterday + 12 months
        ws.append([dt.datetime(2026, 4, 1), None, None, 0, 0, 0, 0, 0, 0])
    ws.append(header)
    for r in rows:
        ws.append(r)
    ws.append(["Some note someone typed", None, None, None])   # trailing junk
    p = tmp_path / f"{name}.xlsx"
    wb.save(p)
    return p


def _row(day, bill, billed, cash, card, due=0, paid=0, extra=None):
    total = billed - due + paid
    base = [dt.datetime(2026, 9, day), 9, bill, billed, due, paid]
    tail = [total, cash, card]
    return base + ([extra] + tail if extra is not None else tail)


# --------------------------------------------------------------------------- #
# Finding the table
# --------------------------------------------------------------------------- #
def test_the_header_is_found_by_content_not_by_row_number(tmp_path):
    """★ It sits at row 20 today, under a twelve-month block. One inserted line
    and a positional reader silently reads the summary as data."""
    for preamble in (4, 12, 30):
        sub = tmp_path / f"p{preamble}"
        sub.mkdir()
        p = _book(sub, HDR,
                  [_row(1, "1", 1000, 0, 1000)], preamble=preamble)
        f, _ = T.read_workbook(p, 107, "alter")
        assert len(f) == 1, preamble
        assert float(f["total"].iloc[0]) == 1000.0


def test_rows_without_a_date_are_dropped(tmp_path):
    """★ THE USED RANGE LIES. The real files claim 5,063 rows and hold ~610;
    the rest are empty pre-numbered bill slots."""
    import openpyxl
    p = _book(tmp_path, HDR, [_row(1, "1", 1000, 0, 1000)])
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    for n in range(2, 60):
        ws.append([None, None, n, None, 0, 0, 0, 0, 0])
    wb.save(p)
    f, _ = T.read_workbook(p, 107, "alter")
    assert len(f) == 1


def test_an_empty_template_reads_as_empty_and_says_so(tmp_path):
    """Fairfield and Agartala have the workbook and have never used it."""
    p = _book(tmp_path, HDR, [])
    f, notes = T.read_workbook(p, 101, "alter")
    assert f.empty
    assert any("no dated rows" in n for n in notes)


# --------------------------------------------------------------------------- #
# The column that moves
# --------------------------------------------------------------------------- #
def test_an_extra_column_shifts_nothing(tmp_path):
    """★ M.G. Road carries `InHouse or Suhail` between Due Paid and Total. Read
    positionally, every figure after it lands one column to the left."""
    p = _book(tmp_path, HDR_MG, [_row(2, "9", 4000, 1000, 3000, extra="Suhail")],
              name="PRMG")
    f, notes = T.read_workbook(p, 110, "alter")
    r = f.iloc[0]
    assert float(r.billed) == 4000.0 and float(r.total) == 4000.0
    assert float(r.cash) == 1000.0 and float(r.card_upi) == 3000.0
    assert r.done_by == "Suhail"


def test_a_column_nobody_expected_is_reported_not_dropped(tmp_path):
    p = _book(tmp_path, HDR + ["Remarks"],
              [_row(2, "9", 4000, 4000, 0) + ["torn hem"]])
    _f, notes = T.read_workbook(p, 107, "alter")
    assert any("Remarks" in n for n in notes)


def test_a_missing_column_is_named(tmp_path):
    thin = ["Date", "Bill No", "Billed Amount", "Total"]
    p = _book(tmp_path, thin, [[dt.datetime(2026, 9, 3), "7", 900, 900]])
    f, notes = T.read_workbook(p, 107, "alter")
    assert len(f) == 1 and float(f["cash"].iloc[0]) == 0.0
    assert any("no cash" in n for n in notes)


# --------------------------------------------------------------------------- #
# The identities — reported, never repaired
# --------------------------------------------------------------------------- #
def _frame(rows):
    f = pd.DataFrame(rows)
    f["date"] = pd.to_datetime(f["date"])
    return f


def test_a_broken_total_is_reported(tmp_path):
    f = _frame([{"store_code": 107, "kind": "alter", "date": "2026-09-01",
                 "bill_no": "1", "billed": 1000, "due": 0, "due_paid": 0,
                 "total": 900, "cash": 900, "card_upi": 0}])
    assert any("Total != Billed" in p for p in T.check(f))


def test_a_broken_payment_split_is_reported():
    f = _frame([{"store_code": 107, "kind": "alter", "date": "2026-09-01",
                 "bill_no": "1", "billed": 1000, "due": 0, "due_paid": 0,
                 "total": 1000, "cash": 500, "card_upi": 400}])
    assert any("Cash + Card/Upi" in p for p in T.check(f))


def test_a_repeated_bill_number_is_reported():
    rows = [{"store_code": 107, "kind": "alter", "date": "2026-09-01",
             "bill_no": "7", "billed": 100, "due": 0, "due_paid": 0,
             "total": 100, "cash": 100, "card_upi": 0} for _ in range(2)]
    assert any("repeated bill number" in p for p in T.check(_frame(rows)))


def test_a_clean_file_reports_nothing():
    f = _frame([{"store_code": 107, "kind": "alter", "date": "2026-09-01",
                 "bill_no": str(i), "billed": 100, "due": 0, "due_paid": 0,
                 "total": 100, "cash": 0, "card_upi": 100} for i in range(3)])
    assert T.check(f) == []


# --------------------------------------------------------------------------- #
# Freshness, which is the point
# --------------------------------------------------------------------------- #
def test_freshness_counts_days_since_the_last_bill():
    f = _frame([{"store_code": 97, "kind": "alter", "date": "2026-09-05",
                 "bill_no": "1", "billed": 1000, "due": 0, "due_paid": 0,
                 "total": 1000, "cash": 1000, "card_upi": 0}])
    fr = T.freshness(f, asof="2026-09-23")
    assert int(fr["days_since"].iloc[0]) == 18


def test_the_folder_name_is_the_store_master():
    """`107_PRGK_Grand_Kamraj_Blr` — the code is in the folder, so nothing is
    hand-mapped and a new store needs no edit."""
    got = T.store_names([
        {"store_code": 107, "folder": "107_PRGK_Grand_Kamraj_Blr"},
        {"store_code": 91, "folder": "91_MAN+MOHEY_AGARTALA"},
    ])
    assert got[107] == "Grand Kamraj"
    assert "AGARTALA" in got[91].upper()
