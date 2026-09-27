"""A ticked report is built; an unticked one is not.

Manav, 27 Sep 2026: *"when i download google reviews report, its downloading
night sale sms."* Two separate faults in the same block, found by him using it:

  ★★ MINE. My 26 Sep edit dedented `build_night_sms` out of its own `if`, so
     it ran on EVERY generate whatever was ticked.
  ★★ OLDER. The Google-reviews PDF was appended only when `_asof is None` —
     the one case where it must be SKIPPED — so a good day produced no review
     PDF at all, and ticking it gave you whatever else was in the zip.

These are source assertions because the alternative is building real PDFs off
the live feed, which is minutes per run and cannot run in CI. What they pin is
the SHAPE that broke: a builder must sit inside the `if` that chooses it.
"""
import ast
import re
from pathlib import Path

import pytest

SRC = Path("app.py").read_text()
TREE = ast.parse(SRC)


def _guards_of(call_name):
    """Every `if` condition that a call to `call_name` sits inside."""
    found = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_If(self, node):
            self.stack.append(ast.unparse(node.test))
            for n in node.body:
                self.visit(n)
            self.stack.pop()
            for n in node.orelse:
                self.visit(n)

        def visit_Call(self, node):
            name = ast.unparse(node.func)
            if name.endswith(call_name):
                found.append(list(self.stack))
            self.generic_visit(node)

    V().visit(TREE)
    return found


@pytest.mark.parametrize("builder,pick", [
    ("build_night_sms", "night_sms"),
    ("build_south_ltol", "south_ltol"),
    ("build_east_ltol", "east_ltol"),
    ("build_month_wise", "mw"),
    ("build_target_vs_ach", "tva"),
])
def test_a_report_is_only_built_when_it_is_ticked(builder, pick):
    """★ THE SHAPE THAT BROKE. One dedent moved a builder out of its `if` and
    it ran unconditionally — and an unconditional report is invisible, because
    the zip still looks plausible."""
    calls = _guards_of(builder)
    assert calls, f"{builder} is never called"
    for guards in calls:
        assert any(f"'{pick}'" in g or f'"{pick}"' in g for g in guards), (
            f"{builder} runs without checking {pick!r}: {guards}")


def _appends_with_guards():
    """Every `built.append(...)`, with the `if` conditions enclosing it."""
    found = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_If(self, node):
            self.stack.append(ast.unparse(node.test))
            for n in node.body:
                self.visit(n)
            self.stack.pop()
            # an `elif` is an If inside orelse and pushes its own test there
            for n in node.orelse:
                self.visit(n)

        def visit_Call(self, node):
            if ast.unparse(node.func).endswith("built.append"):
                found.append((ast.unparse(node)[:90], list(self.stack)))
            self.generic_visit(node)

    V().visit(TREE)
    return found


def test_the_google_review_pdf_is_built_when_there_IS_a_day():
    """★★ The test was inverted: appended only when `_asof is None`, the one
    case where it must be skipped."""
    got = [(c, g) for c, g in _appends_with_guards() if "google_reviews" in c]
    assert got, "the review PDF is never appended"
    for _call, guards in got:
        assert any("'reviews' in chosen" in g or '"reviews" in chosen' in g
                   for g in guards), guards
        assert not any("_asof is None" in g for g in guards), (
            "the review PDF is built in the branch that skips it")


def test_every_report_append_sits_under_a_chosen_check():
    """A sweep rather than a list, so a report added later is covered too.
    ★ One dedent is all it took, and an unconditional report is invisible —
    the zip still looks plausible."""
    for call, guards in _appends_with_guards():
        if "RTD." not in call and "FADM." not in call and "RV." not in call \
                and "vfl_pdf" not in call and "DISC." not in call:
            continue                      # not a report builder
        assert any("chosen" in g for g in guards), (call, guards)
