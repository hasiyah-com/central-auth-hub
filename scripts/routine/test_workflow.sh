#!/usr/bin/env bash
# test_workflow.sh — Smoke test all 6 services
# Run BEFORE and AFTER each dev session to catch regressions
# Exit 0 = all pass, Exit 1 = at least one fail

PASS=0
FAIL=0

check() {
  local name="$1" url="$2" expect="$3"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null; true)
  if [ "$code" = "$expect" ] || { [ "$expect" = "2xx" ] && echo "$code" | grep -qE "^2"; }; then
    printf "  ✅ %-25s (%s)\n" "$name" "$code"
    PASS=$((PASS + 1))
  else
    printf "  ❌ %-25s (got %s, expected %s)\n" "$name" "$code" "$expect"
    FAIL=$((FAIL + 1))
  fi
}

echo "=========================================="
printf "  Workflow Test  %s\n" "$(date '+%Y-%m-%d %H:%M')"
echo "=========================================="

check "Hub /health"            "http://localhost:8000/health"                    "200"
check "Hub /health/db"         "http://localhost:8000/health/db"                 "200"
check "Hub JWKS"               "http://localhost:8000/.well-known/jwks.json"     "200"
check "Subsystem A (dorm)"     "http://localhost:8001/"                          "2xx"
check "Subsystem B (library)"  "http://localhost:8002/"                          "2xx"
check "ML /health"             "http://localhost:9000/health"                    "200"

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "  Result: $PASS/$((PASS + FAIL)) PASS — all systems go ✅"
else
  echo "  Result: $PASS PASS  $FAIL FAIL — fix failures before dev ❌"
fi
echo "=========================================="

[ "$FAIL" -eq 0 ]
