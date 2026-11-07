"""MW Data, VFL only (7 Nov 2026) — portfolio_loader.mw_data_vfl, drawn into the VFL pack."""
import pandas as pd

import portfolio_loader as PL


def _feed():
    days = pd.date_range("2025-04-01", "2026-11-06", freq="D")
    rows = []
    for d in days:
        rows.append({"date": d, "Region": "East & NE", "Sales": 1000.0})
        rows.append({"date": d, "Region": "South", "Sales": 500.0})
    return pd.DataFrame(rows)


def test_vfl_grid_has_the_portfolio_shape_and_only_years_it_can_answer():
    mw = PL.mw_data_vfl(_feed(), "2026-11-06")
    assert list(mw)[:3] == ["2024-25", "2025-26", "2026-27"]       # the portfolio grid's order
    assert all(b["type"] == "region" and b["vfl"] is None for b in mw.values())
    cur = mw["2026-27"]
    assert cur["grand"]["total"] == cur["grand"]["ene"] + cur["grand"]["south"]
    assert abs(sum(m["cont"] for m in cur["months"]) - 100) < 1e-6
    assert cur["months"][0]["total"] == 30 * 1500                    # April 2026 from the feed
    assert mw["2024-25"]["grand"]["south"] == 0                      # history years: East & NE was the estate
    assert "2015-16" not in mw                                       # no data → left out, never zeroes


def test_vfl_grid_east_matches_the_portfolio_sheets_vfl_rows():
    """The VFL figure under the portfolio's 2025-26 block and this sheet's East & NE must be the same money."""
    feed = _feed()
    mine = PL.mw_data_vfl(feed, "2026-11-06")["2025-26"]["grand"]["ene"]
    pers = PL._fy_periods(2025)
    vh = pd.read_csv(PL.os.path.join(PL._DIR, "vfl_history_monthly.csv"))
    vh["fy"] = vh["fy"].astype(str)
    theirs = PL._vfl_slice("2025-26", pers, feed, vh, regions=["East & NE"])["grand"]["ene"]
    assert mine == theirs
