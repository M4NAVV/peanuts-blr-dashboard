"""Size and colour arrive fragmented, and two live charts read them.

★ WHAT THIS PINS. The export writes the same size under two labels — "L" and
" L", "XL" and " XL" — so the "Units by size" chart drew every core size twice
and a buyer reading a size curve off it would under-order by about 4%. And
CATEGORY2 carries a range-code prefix, so cream arrived as 302-Cream,
402-CREAM, 102-CREAM and a bare CREAM: together 38,877 units and the single
best-selling colour in the estate, shown as four separate smaller bars.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import loader as L


def _frame(rows):
    base = {"SHORT_NAME": "Peanuts-X", "Bill Date": "4/1/2025", "Bill No": "PM/1/Apr-25",
            "CUSTOMER_MOBILE": "9000000001", "Division": "KURTA SET",
            "Bill Amount": 1000, "Bill Quantity": 1, "Promotion Amount": 0,
            "CATEGORY1": "S1", "CATEGORY2": "302-Cream", "Size": "L"}
    return pd.DataFrame([{**base, **r} for r in rows])


# ------------------------------------------------------------------- size

def test_the_same_size_under_two_labels_becomes_one():
    out = L.clean(_frame([{"Size": "L"}, {"Size": " L"}, {"Size": "  l"}]))
    assert set(out[L.COL_SIZE]) == {"L"}


def test_a_genuinely_different_size_stays_separate():
    out = L.clean(_frame([{"Size": "L"}, {"Size": "XL"}, {"Size": "XXL"}]))
    assert set(out[L.COL_SIZE]) == {"L", "XL", "XXL"}


def test_no_size_is_labelled_not_left_blank():
    # 58,399 units carry no size — sarees, accessories. Real data, but an
    # unlabelled bar taller than every actual size makes the chart unreadable.
    out = L.clean(_frame([{"Size": ""}, {"Size": "   "}, {"Size": "L"}]))
    assert (out[L.COL_SIZE] == "(no size)").sum() == 2
    assert "" not in set(out[L.COL_SIZE])


# ------------------------------------------------------------------ colour

def test_one_colour_across_several_range_codes_folds_to_one_name():
    out = L.clean(_frame([{"CATEGORY2": "302-Cream"}, {"CATEGORY2": "402-CREAM"},
                          {"CATEGORY2": "102-CREAM"}, {"CATEGORY2": "CREAM"}]))
    assert set(out[L.COL_COLOR_NAME]) == {"CREAM"}


def test_the_raw_code_is_kept_because_a_range_may_matter_to_a_buyer():
    out = L.clean(_frame([{"CATEGORY2": "302-Cream"}, {"CATEGORY2": "402-CREAM"}]))
    assert set(out[L.COL_COLOR]) == {"302-Cream", "402-CREAM"}


def test_different_colours_are_not_merged():
    out = L.clean(_frame([{"CATEGORY2": "302-Cream"}, {"CATEGORY2": "310-Black"}]))
    assert set(out[L.COL_COLOR_NAME]) == {"CREAM", "BLACK"}


def test_a_colour_name_containing_digits_is_not_mangled():
    # Only a LEADING range code is stripped; anything else is the name.
    out = L.clean(_frame([{"CATEGORY2": "2 TONE BLUE"}]))
    assert set(out[L.COL_COLOR_NAME]) == {"2 TONE BLUE"}


def test_the_reports_point_at_the_folded_colour():
    assert L.CAT_DIMS["Color"] == L.COL_COLOR_NAME
    assert L.CAT_DIMS["Color (with range code)"] == L.COL_COLOR


def test_folding_changes_no_money():
    out = L.clean(_frame([{"Size": " L", "CATEGORY2": "402-CREAM", "Bill Amount": 500},
                          {"Size": "L", "CATEGORY2": "302-Cream", "Bill Amount": 700}]))
    assert out[L.COL_AMOUNT].sum() == 1200
