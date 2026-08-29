"""Every figure on the executive snapshot must say what it is.

★ WHY THIS FILE EXISTS. Manav, 29 Aug, on the VFL pack's South page: *"instead
of showing 5 down 3 up, it showed the opposite. i cant even imagine errors like
this are still possible."*

Both numbers were in fact correct — South was 5 up / 3 down for the month and
3 up / 5 down for the year. What was wrong was that the year's two halves were
split across two zones of the tile: "3 up" on its row, and "5 down" ALONE under
the ruled key, where every other tile prints a LABELLED conclusion. An
unlabelled figure under that rule reads as the tile's bottom line, so a reader
sees "5 up" at the top and "5 down" at the bottom and concludes the thing is
inverted.

A number nobody can attribute is not a smaller problem than a wrong number — on
a sheet that goes to directors it is the same problem. So this checks the
STRUCTURE of every tile in the module, by reading the source rather than by
rendering, which means it needs no sheet, no network and no data and runs
everywhere:

    every tile's ruled key carries a label
    every tile's rows carry labels

It cannot check that a label is a GOOD one. It can check that a figure is never
published anonymously, which is the mistake that was actually made.
"""
from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "exec_snapshot.py")


def _tile_dicts():
    """Every dict literal in exec_snapshot that looks like a tile spec."""
    tree = ast.parse(open(_SRC, encoding="utf-8").read())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if "label" in keys and "value" in keys:
            out.append((node, dict(zip(keys, node.values))))
    return out


def _first_element_is_a_nonempty_string(node) -> bool:
    """The label slot of a ('label', value) pair."""
    if not isinstance(node, ast.Tuple) or not node.elts:
        return True                       # not a literal pair; nothing to judge
    first = node.elts[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return bool(first.value.strip())
    return True                           # computed label — cannot judge here


def test_the_module_has_tiles_to_check():
    """If the shape ever changes, this file must fail rather than pass vacuously."""
    assert len(_tile_dicts()) >= 8


def test_no_tile_publishes_an_unlabelled_key():
    """★ THE BUG. `"key": ("", f"{n} down")` printed a bare number under the rule."""
    bad = []
    for node, spec in _tile_dicts():
        key = spec.get("key")
        if key is not None and not _first_element_is_a_nonempty_string(key):
            bad.append(f"exec_snapshot.py line {node.lineno}")
    assert not bad, ("a tile's ruled key has no label, so its figure reads as "
                     "the tile's conclusion: " + "; ".join(bad))


def test_no_tile_publishes_an_unlabelled_row():
    bad = []
    for node, spec in _tile_dicts():
        rows = spec.get("rows")
        if not isinstance(rows, ast.List):
            continue
        for el in rows.elts:
            if not _first_element_is_a_nonempty_string(el):
                bad.append(f"exec_snapshot.py line {getattr(el, 'lineno', node.lineno)}")
    assert not bad, "a tile row has no label: " + "; ".join(bad)


if __name__ == "__main__":
    test_the_module_has_tiles_to_check()
    test_no_tile_publishes_an_unlabelled_key()
    test_no_tile_publishes_an_unlabelled_row()
    print("tile labels OK")


# --------------------------------------------------------------------------- #
#  A stated total must be the total of the parts stated beside it              #
# --------------------------------------------------------------------------- #
# ★ THE SECOND FAULT, FOUND WHILE FIXING THE FIRST. The Breadth tile's key was
# changed to read "Like to like — 21 stores" beside a headline of "9 up 11 dn".
# Nine and eleven make twenty. The month has 20 comparable stores and the year
# 21 (Roodraksh Mall closed, so it is inside the year's window and outside this
# month's), and the key was quoting the YEAR's base next to the MONTH's pair.
#
# Same fault as the original: a reader does the arithmetic, it does not work,
# and they stop trusting the sheet. So the invariant is checked on the real
# tiles, not on the source — this one cannot be seen without the numbers.
#
# Skips when there is no data, like the other live-data tests, and runs for
# real on this machine and anywhere the feed is reachable.

def _breadth(metrics):
    return [t for t in metrics["tiles"] if t["label"].startswith("Breadth")][0]


def _pair(text):
    """'9 up  11 dn' -> (9, 11). None if it is a dash or anything else."""
    parts = text.replace(" up", "").replace(" dn", "").split()
    return tuple(int(p) for p in parts) if len(parts) == 2 and all(
        p.isdigit() for p in parts) else None


def _bases(key_value):
    """'20 month · 21 year' -> (20, 21)."""
    return tuple(int(p.split()[0]) for p in key_value.split(" · "))


def _check(metrics, who):
    t = _breadth(metrics)
    if t["value"] == "—":
        return
    month, year = _pair(t["value"]), _pair(t["rows"][0][1])
    b_month, b_year = _bases(t["key"][1])
    assert sum(month) == b_month, (
        f"{who}: the month says {month[0]} up and {month[1]} dn, which is "
        f"{sum(month)}, against a stated base of {b_month}")
    if year:
        assert sum(year) == b_year, (
            f"{who}: the year says {year[0]} up and {year[1]} dn, which is "
            f"{sum(year)}, against a stated base of {b_year}")


def test_breadth_counts_add_up_to_their_own_stated_base():
    import pandas as pd
    try:
        import loader as L
        import portfolio_loader as PL
        import exec_snapshot as ES
        df = L.load_data()
        pf = PL.load_portfolio()
    except Exception as e:                      # no sheet, no secrets — CI
        import pytest
        pytest.skip(f"needs live data: {e}")
    asof = pd.Timestamp(df["date"].max())
    _check(ES.vfl_metrics(df, asof, asof), "VFL")
    _check(ES.vfl_metrics(df, asof, asof, region="South"), "VFL South")
    _check(ES.portfolio_metrics(pf, PL.as_of(pf)), "portfolio")
