#!/usr/bin/env bash
# eod.sh — End-of-day: pre-commit + diff summary + commit guidance

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "=========================================="
printf "  End of Day  %s\n" "$(date '+%Y-%m-%d %H:%M')"
echo "=========================================="

echo ""
echo "=== Uncommitted Changes ==="
CHANGES=$(git status --short)
if [ -n "$CHANGES" ]; then
  echo "$CHANGES"
  echo "---"
  git diff --stat HEAD 2>/dev/null | tail -8
else
  echo "  (working tree clean)"
fi

echo ""
echo "=== Pre-commit Check ==="
if command -v pre-commit &>/dev/null; then
  if pre-commit run --all-files 2>&1; then
    echo "  All checks passed ✅"
  else
    echo ""
    echo "  Fix the errors above, then commit."
    exit 1
  fi
else
  echo "  (pre-commit not installed — run: pip install pre-commit && pre-commit install)"
fi

echo ""
echo "=== Today's Commits ==="
git log --oneline --since="$(date '+%Y-%m-%d') 00:00" 2>/dev/null || echo "  (none yet)"

echo ""
echo "=== Commit Message Format ==="
echo "  feat:     new feature"
echo "  fix:      bug fix"
echo "  security: security hardening"
echo "  docs:     documentation update"
echo "  refactor: code cleanup (no behavior change)"
echo "  ui:       frontend / template change"
echo ""
echo "  Next: git add <specific files> && git commit -m '...'"
echo "  Then: write docs/daily/$(date '+%Y-%m-%d').md"
echo "=========================================="
