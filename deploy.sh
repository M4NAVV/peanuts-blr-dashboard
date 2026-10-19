#!/usr/bin/env bash
# Deploy the dashboard. THE LIVE APP IS THE HUGGING FACE SPACE.
#
# ★ 10 Sep 2026: a change was pushed to GitHub alone, CI went green, and it was
#   reported as live. The Space was still on the previous commit and Manav spent
#   the morning looking at unchanged figures. `origin` is code and CI; `hf` is
#   what people actually open. This script exists so that cannot happen again.
#
#   Usage:  ./deploy.sh          (pushes main to both, then PROVES both match)
set -euo pipefail
BRANCH="${1:-main}"

# ★ 19 Oct 2026: the reviews collector commits `review_snapshots.csv` to origin every day, so a deploy made
# after it was REJECTED ("fetch first"). Its commits are taken in automatically — but ONLY those: anything
# else new on origin is somebody's work and stops the deploy for a person to look at.
git fetch -q origin "$BRANCH"
NEW=$(git rev-list "$BRANCH..origin/$BRANCH")
if [ -n "$NEW" ]; then
    OTHER=$(git diff --name-only "$BRANCH...origin/$BRANCH" | grep -vx 'review_snapshots.csv' || true)
    if [ -n "$OTHER" ]; then
        echo "✗ NOT DEPLOYED — origin has commits that are not the daily review counts:"
        git log --oneline "$BRANCH..origin/$BRANCH" | sed 's/^/    /'
        echo "  Look at them, then: git pull --rebase origin $BRANCH"
        exit 1
    fi
    echo "→ taking in $(echo "$NEW" | wc -l | tr -d ' ') review-count commit(s) from origin"
    git rebase -q --autostash "origin/$BRANCH" || {
        git rebase --abort 2>/dev/null || true
        echo "✗ NOT DEPLOYED — the rebase onto origin's review counts did not apply cleanly."; exit 1; }
    echo
fi
LOCAL=$(git rev-parse "$BRANCH")

# A warning, not a gate. Only committed work is pushed, so uncommitted files
# cannot reach the Space — but they CAN be work you meant to include. The
# reviews collector rewrites review_snapshots.csv daily, so blocking here
# would make this script something you learn to skip.
DIRTY=$(git status --porcelain --untracked-files=no || true)
if [ -n "$DIRTY" ]; then
    echo "! uncommitted, and therefore NOT being deployed:"
    echo "$DIRTY" | sed 's/^/    /'
    echo
fi

# ★ RECONCILIATION GATE (5 Oct 2026). Before anything goes live, the reports
# must still reproduce the figures Manav signed off against his own workbooks.
# The figures are private (~/Documents/peanuts-recon/golden.json) and never in
# this public repo. A SKIP is treated as a failure here — "could not check" is
# not "checked" (see feedback-silent-failure-must-speak). Override, with a
# reason, only for an emergency:  SKIP_RECON=1 ./deploy.sh
GOLDEN="${PEANUTS_RECON:-$HOME/Documents/peanuts-recon/golden.json}"
if [ "${SKIP_RECON:-0}" = "1" ]; then
    echo "! reconciliation SKIPPED by SKIP_RECON=1 — say why in the commit or the log"
elif [ -f "$GOLDEN" ]; then
    echo "→ reconciling against the signed-off figures"
    PY=./venv/bin/python; [ -x "$PY" ] || PY=python3
    OUT=$("$PY" -m pytest tests/test_reconciliation.py -q -rs -p no:cacheprovider 2>&1) && RC=0 || RC=$?
    LAST=$(echo "$OUT" | tail -1)
    if [ "$RC" -ne 0 ] || echo "$LAST" | grep -q "skipped"; then
        # ★ 18 Oct 2026: `|| true` — with pipefail, a failure whose lines match none of these (a PermissionError
        # reading the golden file) made grep exit 1 and the script die SILENTLY after "reconciling…".
        { echo "$OUT" | grep -E "^E +|^FAILED|SKIPPED" || true; } | sed 's/^/    /' | head -20
        echo "    $LAST"
        echo
        echo "✗ NOT DEPLOYED — a signed-off figure no longer ties (or could not be checked)."
        echo "  Either the change broke a report, or the sheet's history was edited / a rule"
        echo "  changed on purpose — then update 'expect' in $GOLDEN with a note."
        exit 1
    fi
    echo "  ✓ $LAST"
    echo
else
    echo "! no reconciliation file at $GOLDEN — deploying without the figure check"
fi

for r in origin hf; do
    echo "→ pushing $BRANCH to $r"
    git push "$r" "$BRANCH"
done

echo
FAIL=0
for r in origin hf; do
    REMOTE=$(git ls-remote "$r" "$BRANCH" | cut -f1)
    if [ "$REMOTE" = "$LOCAL" ]; then
        printf '  ✓ %-7s %s\n' "$r" "${REMOTE:0:7}"
    else
        printf '  ✗ %-7s %s  EXPECTED %s\n' "$r" "${REMOTE:0:7}" "${LOCAL:0:7}"; FAIL=1
    fi
done

[ "$FAIL" -eq 0 ] || { echo; echo "✗ NOT DEPLOYED — the remotes disagree."; exit 1; }
echo
echo "✓ deployed — the Space rebuilds itself in ~30s (Restarting -> Running)"
echo "  https://huggingface.co/spaces/Manavv4/peanuts_dashboard"
