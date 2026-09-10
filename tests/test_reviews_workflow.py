"""The review collector's schedule, checked as data rather than trusted.

★ WHY THIS FILE EXISTS. Moving collection from a laptop to a scheduled runner
changes what a bug costs. The three that would hurt most are all INVISIBLE on
reading, and all silent in production:

  - the reading not committed back, so every run starts from a fresh checkout,
    finds no history, and the app shows a feed that began today
  - the CSV gitignored, which is the same failure wearing a different hat
  - a `pull_request` trigger on a PUBLIC repo, which would hand the API key to
    anyone who opened one

★ AND A MISSED MORNING CANNOT BE RECOVERED. The count is a running LEVEL, not
an event: if a day is not read, the next reading silently covers two days and
the report spreads it. That is why the schedule is asserted at all.
"""
from __future__ import annotations

import os
import subprocess

import yaml

# ★ A PLAIN IMPORT, NOT `importorskip`. The first draft skipped the whole file
# when PyYAML was absent — and a skipped guard reads exactly like a passing
# one in the summary line. If the library is missing, these tests must go RED,
# because the thing they protect is a schedule nobody looks at.

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(HERE, ".github", "workflows", "reviews.yml")


def _wf():
    with open(WF, encoding="utf-8") as fh:
        d = yaml.safe_load(fh)
    # PyYAML reads a bare `on:` as the boolean True (YAML 1.1). GitHub does not.
    d["on"] = d.get("on") or d.get(True)
    return d


def test_the_reading_is_committed_back():
    """A runner starts from a fresh checkout. An uncommitted CSV is not memory,
    it is an empty file that thinks collection began today."""
    body = open(WF, encoding="utf-8").read()
    assert "git add review_snapshots.csv" in body
    assert "git push" in body


def test_the_snapshot_is_not_gitignored():
    r = subprocess.run(["git", "check-ignore", "review_snapshots.csv"],
                       cwd=HERE, capture_output=True, text=True)
    assert r.returncode != 0, "review_snapshots.csv is ignored — it cannot be " \
                              "committed back, so the runner has no history"


def test_a_pull_request_cannot_reach_the_key():
    """This repo is PUBLIC. A `pull_request` trigger would run a fork's code
    with the repository secret in scope."""
    assert "pull_request" not in _wf()["on"]


def test_it_refuses_to_run_from_a_fork():
    assert "github.repository ==" in _wf()["jobs"]["collect"]["if"]


def test_it_may_write_and_only_write():
    assert _wf()["permissions"] == {"contents": "write"}


def test_two_runs_cannot_append_the_same_day_at_once():
    c = _wf()["concurrency"]
    assert c["group"] and c["cancel-in-progress"] is False


def test_it_is_scheduled_off_the_hour_and_more_than_once():
    """★ GitHub never fired the original single `10 2 * * *`. Scheduled runs are
    delayed or dropped under load, worst at the top of the hour — and a missed
    morning cannot be recovered here, because the count is a running level.
    So: fixed minutes well away from :00, and a second attempt that can rescue
    the first."""
    crons = [e["cron"] for e in _wf()["on"]["schedule"]]
    assert len(crons) >= 2, "one slot a day cannot rescue a dropped run"
    for c in crons:
        mins, hrs = c.split()[0], c.split()[1]
        assert "," not in mins and "/" not in mins and "*" not in hrs
        assert 5 <= int(mins) <= 55, f"{c} sits in the congested top-of-hour window"


def test_a_second_run_the_same_day_is_harmless():
    """The safety net is only safe because the job is idempotent: one row per
    store per day, and the commit step exits 0 when nothing changed."""
    body = open(WF, encoding="utf-8").read()
    assert "git diff --cached --quiet" in body
    assert "exit 0" in body


def test_a_missing_key_stops_before_it_writes():
    """A run with no key must say so and fail, not write a short day over a
    good one."""
    body = open(WF, encoding="utf-8").read()
    i = body.index("GOOGLE_MAPS_API_KEY: ${{")
    j = body.index("scripts_collect_reviews.py", i)
    assert 'if [ -z "$GOOGLE_MAPS_API_KEY" ]' in body[i:j]
    assert "exit 1" in body[i:j]


def test_the_commit_does_not_start_a_test_run():
    assert "[skip ci]" in open(WF, encoding="utf-8").read()
