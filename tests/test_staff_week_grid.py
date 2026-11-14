"""Store pack page 1: the staff week grid (Manav, 13–14 Nov 2026) — on a made-up feed, no live data."""
import pandas as pd

import loader as L
import snapshots_a4 as A


def _feed(n_people=4, store="Test Store"):
    rows = []
    end = pd.Timestamp("2026-11-13")
    for p in range(n_people):
        for k in range(8):                                   # 8 days: the first must fall outside the week
            rows.append({L.COL_STORE_LABEL: store, "date": end - pd.Timedelta(days=k), "SALESPERSON_NO": f"ID{p}",
                         L.COL_SALESPERSON: ("ASIF . SHARIF" if p == 0 else f"PERSON {p}"), L.COL_AMOUNT: 10_000.0 * (p + 1)})
    rows.append({L.COL_STORE_LABEL: store, "date": end + pd.Timedelta(days=1), "SALESPERSON_NO": None,   # night fill
                 L.COL_SALESPERSON: "(PROVISIONAL)", L.COL_AMOUNT: 99_999.0})
    return pd.DataFrame(rows)


def test_grid_lists_everyone_cleans_names_and_uses_the_week_to_the_last_billed_day():
    img, n = A.staff_week_grid(L, _feed(), pd.Timestamp("2026-11-14"), "Test Store", 2300, 5000)
    assert img is not None and n == 4


def test_a_big_team_still_fits_by_splitting_into_two_halves():
    img, n = A.staff_week_grid(L, _feed(28), pd.Timestamp("2026-11-14"), "Test Store", 2300, 1200)
    assert img is not None and n == 28 and img.height <= 1200


def test_too_little_room_returns_none_so_the_page_can_say_so():
    img, n = A.staff_week_grid(L, _feed(28), pd.Timestamp("2026-11-14"), "Test Store", 2300, 150)
    assert img is None and n == 28
