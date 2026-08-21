"""The target block on the morning snapshot.

These pin the arithmetic a manager is measured on, and the three ways it could
quietly mislead: a missing target reading as zero, today being counted twice in
the days left, and a store that is ahead being handed a daily demand anyway.
"""

import calendar
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import snapshots as SN


class _L:
    """Just the one loader method target_progress reaches for."""

    def __init__(self, takeover=None):
        self._t = takeover or {}

    def takeover_map(self):
        return self._t


ASOF = pd.Timestamp("2026-08-20")


def _vals(cards):
    """{label: value}. Cards carry an optional third element, their ink."""
    return {c[0]: c[1] for c in cards}


def _tp(kind, achieved, target=None, takeover=None, code=1):
    targets = {code: ({"mtd": target} if kind == "MTD" else {"ytd": target})} \
        if target else {}
    return SN.target_progress(_L(takeover or {}), ASOF, kind, "S", code,
                              achieved=achieved, targets=targets)


# ----------------------------------------------------------------- the maths

def test_achieved_percent_and_balance():
    tp = _tp("MTD", achieved=60_00_000, target=100_00_000)
    assert tp["ach_pct"] == pytest.approx(60.0)
    assert tp["balance"] == pytest.approx(40_00_000)


def test_days_left_excludes_today():
    # Today's takings are already inside the achieved figure. Counting today
    # again would ask the store to earn them twice and understate the rate.
    tp = _tp("MTD", achieved=1, target=2)
    assert tp["days_left"] == calendar.monthrange(2026, 8)[1] - 20 == 11


def test_per_day_required_is_balance_over_days_left():
    tp = _tp("MTD", achieved=60_00_000, target=100_00_000)
    assert tp["per_day"] == pytest.approx(40_00_000 / 11)


def test_average_day_sales_counts_from_the_first_of_the_month():
    tp = _tp("MTD", achieved=20_00_000, target=None)
    assert tp["avg_day"] == pytest.approx(20_00_000 / 20)   # 1 Aug - 20 Aug


def test_year_average_is_takeover_anchored_not_fiscal_year_anchored():
    # South was taken over on 19 April. Measuring its year from 1 April would
    # add a fortnight it never traded under us and understate the daily average.
    south = _tp("YTD", achieved=1_00_00_000,
                takeover={"S": pd.Timestamp("2026-04-19")})
    east = _tp("YTD", achieved=1_00_00_000,
               takeover={"S": pd.Timestamp("2025-04-01")})
    assert south["from"] == pd.Timestamp("2026-04-19")
    assert east["from"] == pd.Timestamp("2026-04-01")
    assert south["avg_day"] > east["avg_day"]


# ----------------------------------------------------- the ways it could lie

def test_a_missing_target_is_a_dash_not_a_zero():
    # A store with no target entered must not read as having been asked for
    # nothing and having beaten it.
    tp = _tp("MTD", achieved=50_00_000, target=None)
    assert tp["target"] is None
    assert tp["ach_pct"] is None
    assert tp["balance"] is None
    cards = _vals(SN.target_cards(tp, "MTD"))
    assert cards["MTD target"] == "—"
    assert cards["Achieved %"] == "—"      # no target -> no pace in the label


def test_a_store_ahead_of_target_is_not_handed_a_daily_demand():
    tp = _tp("MTD", achieved=120_00_000, target=100_00_000)
    assert tp["balance"] < 0
    assert tp["per_day"] is None
    assert _vals(SN.target_cards(tp, "MTD"))["Per day reqd (11d)"] == "on track"


def test_the_month_is_measured_against_the_whole_months_target():
    # Not the elapsed part of it. The night SMS does the same, and the two
    # reports must not disagree about what "balance" means.
    tp = _tp("MTD", achieved=50_00_000, target=100_00_000)
    assert tp["target"] == 100_00_000
    assert tp["balance"] == pytest.approx(50_00_000)


def test_ytd_uses_the_year_target_and_mtd_the_month_target():
    both = {7: {"mtd": 50_00_000, "ytd": 600_00_000}}
    m = SN.target_progress(_L(), ASOF, "MTD", "S", 7, 10_00_000, both)
    y = SN.target_progress(_L(), ASOF, "YTD", "S", 7, 10_00_000, both)
    assert m["target"] == 50_00_000
    assert y["target"] == 600_00_000


# ----------------------------------------------------------------- the cards

def test_six_cards_in_the_order_he_listed_them():
    tp = _tp("MTD", achieved=60_00_000, target=100_00_000)
    labels = [c[0] for c in SN.target_cards(tp, "MTD")]
    assert labels[0] == "MTD target"
    assert labels[1] == "MTD achieved"
    assert labels[2].startswith("Achieved %")
    assert labels[3] == "Avg day sales"
    assert labels[4] == "Balance target"
    assert labels[5].startswith("Per day reqd")


def test_cards_wrap_onto_a_second_row_rather_than_squeezing():
    # Nine cards on one line put the value text through the card edge on a
    # phone, which is where these are read.
    one = SN._cards_image([("a", "1")] * 5, 1200)
    two = SN._cards_image([("a", "1")] * 9, 1200)
    assert two.height > one.height
    assert two.width == one.width == 1200


# ------------------------------------------------------------------- units

def test_a_year_target_switches_to_crore_so_it_fits_the_card():
    # "Rs 1,601.25 L" already touches the card edge; a flagship's year target
    # would run straight through it.
    tp = _tp("YTD", achieved=3_91_31_000, target=16_01_25_000)
    cards = _vals(SN.target_cards(tp, "YTD"))
    assert cards["YTD target"].endswith("Cr")
    assert cards["YTD target"] == "Rs 16.01 Cr"


def test_target_achieved_and_balance_always_share_one_unit():
    # Switching each card on its own would print a crore target beside a lakh
    # achievement, and a manager comparing them would convert in their head.
    tp = _tp("MTD", achieved=82_77_000, target=1_00_00_000)
    cards = _vals(SN.target_cards(tp, "MTD"))
    units = {cards["MTD target"].split()[-1],
             cards["MTD achieved"].split()[-1],
             cards["Balance target"].split()[-1]}
    assert len(units) == 1


def test_daily_rates_keep_their_own_unit():
    # A per-day figure in crore is all zeros.
    tp = _tp("YTD", achieved=3_91_31_000, target=16_01_25_000)
    cards = _vals(SN.target_cards(tp, "YTD"))
    assert cards["Avg day sales"].endswith("L")
    assert cards["YTD target"].endswith("Cr")


# ------------------------------------------------------------------ colour

import portfolio_pdf as PP


def _ink(cards, prefix):
    for c in cards:
        if c[0].startswith(prefix):
            return c[2] if len(c) > 2 else None
    raise AssertionError(f"no card starting {prefix!r}")


def test_a_store_that_beat_its_target_is_not_shown_in_red():
    # The card strip used to redden anything beginning with a minus. A beaten
    # target has a NEGATIVE balance, so success was printed as failure.
    tp = _tp("MTD", achieved=120_00_000, target=100_00_000)
    cards = SN.target_cards(tp, "MTD")
    assert _ink(cards, "Balance") == PP.GREEN
    assert "ahead" in _vals(cards)["Balance target"]
    assert not _vals(cards)["Balance target"].startswith("Rs -")


def test_achievement_is_judged_against_pace_not_against_100():
    # On the 20th of a 31-day month a store should be about 65% of the way
    # there. Judging against 100 would print every store red for thirty days
    # and green on the thirty-first, which is not information.
    ahead = _tp("MTD", achieved=82_77_000, target=1_00_00_000)   # 82.8% vs 65%
    behind = _tp("MTD", achieved=40_00_000, target=1_00_00_000)  # 40.0% vs 65%
    assert _ink(SN.target_cards(ahead, "MTD"), "Achieved") == PP.GREEN
    assert _ink(SN.target_cards(behind, "MTD"), "Achieved") == PP.NEG_INK


def test_the_expected_pace_is_printed_so_the_colour_is_not_magic():
    tp = _tp("MTD", achieved=82_77_000, target=1_00_00_000)
    label = [c[0] for c in SN.target_cards(tp, "MTD") if c[0].startswith("Achieved")][0]
    assert "pace 65%" in label


def test_balance_left_to_sell_is_not_a_failure():
    # Mid-period there is obviously balance. Only the pace card judges.
    tp = _tp("MTD", achieved=82_77_000, target=1_00_00_000)
    assert _ink(SN.target_cards(tp, "MTD"), "Balance") is None


def test_no_target_means_no_colour_anywhere():
    tp = _tp("MTD", achieved=50_00_000, target=None)
    assert all((len(c) < 3 or c[2] is None) for c in SN.target_cards(tp, "MTD"))


# ------------------------------------------------------- single-piece bills

def test_single_bill_card_inverts_the_colour_because_lower_is_better():
    # Every other card is good when it rises. A single-piece share that CLIMBS
    # means more customers leaving with one item — reusing the growth colour
    # would paint an improving store red exactly when it had fixed the problem.
    better = SN._single_bill_card({"ty": 0.40, "ly": 0.55})
    worse = SN._single_bill_card({"ty": 0.55, "ly": 0.40})
    assert better[2] == PP.GREEN
    assert worse[2] == PP.NEG_INK


def test_single_bill_card_carries_last_year_at_the_same_precision():
    # 44.8 rounded to "45" beside a 45.6 reads as a bigger move than it is.
    label = SN._single_bill_card({"ty": 0.4561, "ly": 0.4482})[0]
    assert "44.8%" in label


def test_single_bill_card_with_no_history_still_shows_this_year():
    lab, val, *rest = SN._single_bill_card({"ty": 0.5, "ly": None})
    assert val == "50.0%"
    assert "LY" not in lab
    assert not rest or rest[0] is None


def test_single_bill_card_with_no_data_is_a_dash():
    assert SN._single_bill_card({"ty": None, "ly": None})[1] == "—"


def test_a_bill_of_one_piece_is_single_and_two_pieces_is_not():
    import loader as L

    rows = []
    for uid, qtys in [("b1", [1]), ("b2", [2]), ("b3", [1, 1]), ("b4", [1])]:
        for q in qtys:
            rows.append({L.COL_STORE_LABEL: "S", L.COL_BILL_UID: uid,
                         L.COL_QTY: q, "date": pd.Timestamp("2026-08-10")})
    frame = pd.DataFrame(rows)

    class _FakeL:
        COL_STORE_LABEL = L.COL_STORE_LABEL
        COL_BILL_UID = L.COL_BILL_UID
        COL_QTY = L.COL_QTY

        @staticmethod
        def report_frames(df, kind, asof=None):
            return frame, frame.iloc[0:0]

    sb = SN.single_bill_share(_FakeL, frame, pd.Timestamp("2026-08-20"), "MTD", "S")
    # b1 and b4 are one piece; b2 is two pieces; b3 is two pieces on two lines.
    assert sb["ty"] == pytest.approx(0.5)
    assert sb["ly"] is None
