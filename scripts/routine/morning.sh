#!/usr/bin/env bash
# morning.sh — Daily startup: docker health + git status + recent errors + roadmap

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "=========================================="
printf "  Hub Morning Check  %s\n" "$(date '+%Y-%m-%d %H:%M')"
echo "=========================================="

echo ""
echo "=== Docker Services ==="
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null \
  || echo "  (services not running — run: docker compose up -d)"

echo ""
echo "=== Git Status ==="
git log --oneline -5
echo "---"
git status --short || echo "  (working tree clean)"

echo ""
echo "=== Recent Hub Errors ==="
ERRORS=$(docker compose logs --tail=60 hub-backend 2>/dev/null \
  | grep -E "ERROR|WARN|Exception|Traceback" | tail -8)
if [ -n "$ERRORS" ]; then
  echo "$ERRORS"
else
  echo "  (none)"
fi

echo ""
echo "=== Roadmap Reminder ==="
echo "  ✅ Weeks 1-7 done"
echo "  🔄 Week 8: Admin Dashboard (Next.js) — current"
echo "  ⏳ Week 9-10: MFA + token revocation"
echo "  ⏳ Week 11-12: Security hardening + pentest"
echo ""
echo "  Ports: Hub=8000  Dorm=8001  Lib=8002  ML=9000"
echo "  PG:    Hub=5432  Dorm=5433  Lib=5434  Redis=6379"
echo "=========================================="
