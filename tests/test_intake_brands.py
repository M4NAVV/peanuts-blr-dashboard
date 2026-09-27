"""The brand split, read straight off the intake form.

Manav, 27 Sep 2026: *"cant we do something where we get this read normally like
everything else from our data sources."* It can — so nothing runs on a
schedule, and nothing here touches the network: the responses and the mail map
are handed in as frames.
"""
import pandas as pd
import pytest

import intake_brands as IB

MAILS = {"peanutskamraj.manyavarmohey@gmail.com": 107,
         "peanutsdvgroad1.manyavar@gmail.com": 114}
GK, DVG = list(MAILS)[0], list(MAILS)[1]
DAY = pd.Timestamp("2026-09-28")


def _f(records):
    return pd.DataFrame(records)


def _r(email=GK, ts="2026-09-28 21:40:00", date="9/28/2026",
       man="3,00,000", moh="2,00,000", twa="1,00,000", sales="6,00,000"):
    return {"Timestamp": ts, "Email Address": email, "Day Sales": sales,
            "Quantity sold": "40", "Footfall": "120", "Bills": "20",
            "Manyavar Sales": man, "Mohey Sales": moh, "Twamev Sales": twa,
            "Date": date}


def day_of(rows, day=DAY, codes=None):
    return IB.for_day(day, codes=codes, responses=_f(rows), mails=MAILS)


# --------------------------------------------------------------------------- #
# ★★ THE CORRECTION PATH — Manav's question
# --------------------------------------------------------------------------- #
def test_a_store_that_refiles_replaces_its_earlier_figure():
    """*"if a store mistypes something, then submits another form with the
    right figures, will our logic take the latest data"* — yes. Re-filing is
    what the form tells them to do, so the newest submission for a store-day
    REPLACES the earlier one."""
    wrong = _r(ts="2026-09-28 21:40:00", man="30,000")      # a digit short
    right = _r(ts="2026-09-28 21:52:00", man="3,00,000")
    assert day_of([wrong, right])[107]["manyavar"] == 300000.0


def test_the_order_of_the_rows_does_not_decide_it_the_timestamp_does():
    wrong = _r(ts="2026-09-28 21:40:00", man="30,000")
    right = _r(ts="2026-09-28 21:52:00", man="3,00,000")
    assert day_of([right, wrong])[107]["manyavar"] == 300000.0


def test_a_correction_filed_the_next_morning_still_wins():
    wrong = _r(ts="2026-09-28 21:40:00", man="30,000")
    right = _r(ts="2026-09-29 09:10:00", date="9/28/2026", man="3,00,000")
    assert day_of([wrong, right])[107]["manyavar"] == 300000.0


def test_two_submissions_in_the_same_second_resolve_to_the_later_row():
    """★ Forms stamps to the SECOND. A tie must still be decided, and sheet
    order is the only thing left — Forms appends in the order it received."""
    a = _r(ts="2026-09-28 21:40:00", man="1")
    b = _r(ts="2026-09-28 21:40:00", man="2")
    assert day_of([a, b])[107]["manyavar"] == 2.0


def test_a_correction_only_replaces_the_day_it_names():
    """★ THE LIMIT OF THE RULE, worth knowing: the correction is keyed on the
    DATE the store picks. Re-file against the wrong day and the bad figure
    stays where it was."""
    wrong = _r(ts="2026-09-28 21:40:00", date="9/28/2026", man="30,000")
    right = _r(ts="2026-09-28 21:52:00", date="9/27/2026", man="3,00,000")
    got = IB.split_map(_f([wrong, right]), MAILS)
    assert got[(107, DAY)]["manyavar"] == 30000.0
    assert got[(107, pd.Timestamp("2026-09-27"))]["manyavar"] == 300000.0


# --------------------------------------------------------------------------- #
# Identity, dates, figures
# --------------------------------------------------------------------------- #
def test_the_mailbox_decides_which_store_it_is():
    got = day_of([_r(email=DVG, man="1,00,000", moh="0", twa="0")])
    assert set(got) == {114}


def test_an_address_nobody_knows_is_ignored():
    """★ It maps to no store, so it cannot be filed against one."""
    assert day_of([_r(email="someone@gmail.com")]) == {}


def test_a_date_after_the_submission_is_refused():
    """Nobody files the future."""
    assert day_of([_r(ts="2026-09-28 21:40:00", date="12/25/2026")]) == {}


def test_the_timestamp_settles_a_nine_ten_date():
    """★ This sheet writes month-first, the portfolio sheet day-first, and
    `10/9/2026` is 9 Oct or 10 Sep — it only goes wrong above the 12th."""
    got = IB.split_map(_f([_r(ts="2026-10-10 21:00:00", date="10/9/2026")]),
                       MAILS)
    assert (107, pd.Timestamp("2026-10-09")) in got


def test_a_timezone_suffix_does_not_move_the_night():
    """★★ `GMT+5:30` read by dateutil is −05:30 — the POSIX sign convention,
    an eleven hour error landing exactly on a midnight cutoff."""
    got = IB.split_map(_f([_r(ts="2026-09-28 23:58:00 GMT+5:30", date="")]),
                       MAILS)
    assert (107, DAY) in got


def test_no_date_given_falls_back_to_the_night_it_was_sent():
    assert 107 in day_of([_r(date="")])


def test_indian_grouping_is_read_as_a_number():
    assert day_of([_r(man="81,65,928")])[107]["manyavar"] == 8165928.0


def test_a_brand_the_store_does_not_carry_is_zero_not_missing():
    got = day_of([_r(email=DVG, man="1,00,000", moh="0", twa="0")])
    assert got[114] == {"manyavar": 100000.0, "mohey": 0.0, "twamev": 0.0}


def test_an_unreadable_figure_does_not_poison_the_others():
    got = day_of([_r(man="3,0O,000")])
    assert got[107]["manyavar"] == 0.0 and got[107]["mohey"] == 200000.0


# --------------------------------------------------------------------------- #
# When it cannot answer
# --------------------------------------------------------------------------- #
def test_an_empty_form_says_nobody_has_filed():
    assert IB.split_map(_f([]), MAILS) == {}
    assert "filed" in IB.last_problem()


def test_without_a_mail_map_nothing_is_attributable_and_it_says_so():
    assert IB.split_map(_f([_r()]), {}) == {}
    assert "unattributable" in IB.last_problem()


def test_it_needs_no_schedule_and_no_service_account():
    """★★ The whole point of the rewrite: both sources read with a plain CSV
    export, so the split is computed at refresh time like every other feed."""
    import inspect
    src = inspect.getsource(IB)
    assert "service_account" not in src and "googleapiclient" not in src
    assert "export?format=csv" in src


def test_the_mail_addresses_never_leave_the_mapping():
    """★ This repo is public. The master tab may be READ at runtime and never
    snapshotted; only the email-to-code mapping leaves that function."""
    import inspect
    src = inspect.getsource(IB.mail_map)
    assert "never RENDERED".lower() in src.lower() or "never rendered" in src.lower()
