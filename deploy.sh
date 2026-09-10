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
