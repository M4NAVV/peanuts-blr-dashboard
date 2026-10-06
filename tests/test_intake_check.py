"""Intake vs Tableau — the rules of the comparison, on made-up filings (no live data)."""
import pandas as pd

import intake_check as IC

MAILS = {"jn@x.com": 112, "gk@x.com": 107}


def _form(rows):
    cols = ["Timestamp", "Email Address", "Day Sales", "Quantity sold", "Footfall", "Bills",
            "Manyavar Sales", "Mohey Sales", "Twamev Sales", "TODAYS Date"]
    return pd.DataFrame(rows, columns=cols)


def _tab(rows):
    t = pd.DataFrame(rows, columns=["code", "date", "sales", "manyavar", "mohey", "twamev", "bills", "units"])
    t["date"] = pd.to_datetime(t["date"])
    return t


NAMES = {112: "Jayanagar", 107: "Grand Kamraj Road"}


def test_the_day_sales_column_is_never_read_from_a_brand_column():
    f = IC.filings(_form([["10/5/2026 21:00:00", "jn@x.com", "56743", 8, 10, 6, "10747", "45996", "0", "10/5/2026"]]), MAILS)
    assert f.loc[0, "sales"] == 56743 and f.loc[0, "manyavar"] == 10747


def test_the_latest_filing_for_a_store_day_wins():
    f = IC.filings(_form([
        ["10/5/2026 21:00:00", "jn@x.com", "50000", 8, 10, 6, "10000", "40000", "0", "10/5/2026"],
        ["10/5/2026 22:30:00", "jn@x.com", "56743", 8, 10, 6, "10747", "45996", "0", "10/5/2026"],
    ]), MAILS)
    assert len(f) == 1 and f.loc[0, "sales"] == 56743


def test_rounding_matches_and_a_real_gap_differs():
    fil = IC.filings(_form([
        ["10/5/2026 21:00:00", "jn@x.com", "56743", 8, 10, 6, "10747", "45996", "0", "10/5/2026"],
        ["10/5/2026 21:10:00", "gk@x.com", "690000", 85, 90, 31, "274519", "280289", "135192", "10/5/2026"],
    ]), MAILS)
    tab = _tab([[112, "2026-10-05", 56744, 10747, 45997, 0, 6, 8],
                [107, "2026-10-05", 701818, 274519, 292107, 135192, 31, 85]])
    c = IC.compare("2026-10-05", fil, tab, NAMES).set_index("code")
    assert c.loc[112, "status"] == "Matches"            # ₹1 is rounding
    assert c.loc[107, "status"] == "Differs"
    assert c.loc[107, "sales_diff"] == 690000 - 701818  # typed minus Tableau: under-reported


def test_a_bill_count_off_by_one_is_a_difference():
    fil = IC.filings(_form([["10/5/2026 21:00:00", "jn@x.com", "56744", 8, 10, 7, "10747", "45997", "0", "10/5/2026"]]), MAILS)
    tab = _tab([[112, "2026-10-05", 56744, 10747, 45997, 0, 6, 8]])
    assert IC.compare("2026-10-05", fil, tab, NAMES).loc[0, "status"] == "Differs"


def test_a_wrong_date_is_recognised_from_the_figures():
    """Jayanagar, 3 Oct: 3 October's figures filed under 26 September."""
    fil = IC.filings(_form([["10/3/2026 22:00:40", "jn@x.com", "433253", 51, 47, 31, "220769", "201484", "10999", "9/26/2026"]]), MAILS)
    tab = _tab([[112, "2026-09-26", 507882, 221333, 214554, 71995, 40, 77],
                [112, "2026-10-03", 433254, 220769, 201486, 10999, 31, 51]])
    c = IC.compare("2026-09-26", fil, tab, NAMES)
    assert c.loc[0, "status"] == "Differs" and "03 Oct" in c.loc[0, "hint"]
    assert IC.compare("2026-10-03", fil, tab, NAMES).loc[0, "status"] == "Not filed"


def test_stores_are_expected_only_once_they_have_used_the_form():
    fil = IC.filings(_form([["10/1/2026 21:00:00", "jn@x.com", "1000", 1, 1, 1, "1000", "0", "0", "10/1/2026"]]), MAILS)
    assert IC.expected(fil, "2026-10-05") == {112}
    assert IC.expected(fil, "2026-10-20") == set()       # a fortnight of silence: off the roster


def test_a_filing_ahead_of_tableau_waits_rather_than_differs():
    fil = IC.filings(_form([["10/6/2026 21:00:00", "jn@x.com", "1000", 1, 1, 1, "1000", "0", "0", "10/6/2026"]]), MAILS)
    tab = _tab([[112, "2026-10-05", 56744, 10747, 45997, 0, 6, 8]])
    assert IC.compare("2026-10-06", fil, tab, NAMES).loc[0, "status"] == "Waiting for Tableau"


def test_track_record_counts_only_days_tableau_can_check():
    fil = IC.filings(_form([
        ["10/4/2026 21:00:00", "jn@x.com", "100", 1, 1, 1, "100", "0", "0", "10/4/2026"],
        ["10/5/2026 21:00:00", "jn@x.com", "56743", 8, 10, 6, "10747", "45996", "0", "10/5/2026"],
        ["10/6/2026 21:00:00", "jn@x.com", "9", 1, 1, 1, "9", "0", "0", "10/6/2026"],
    ]), MAILS)
    tab = _tab([[112, "2026-10-04", 200, 200, 0, 0, 1, 1], [112, "2026-10-05", 56744, 10747, 45997, 0, 6, 8]])
    t = IC.track_record(fil, tab, NAMES, "2026-09-07", "2026-10-06").iloc[0]
    assert (t["filings"], t["checked"], t["matched"]) == (3, 2, 1)
