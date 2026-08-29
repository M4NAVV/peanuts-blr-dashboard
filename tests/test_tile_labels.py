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
