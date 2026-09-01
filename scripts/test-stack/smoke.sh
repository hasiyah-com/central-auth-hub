#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE=".env.test"
if [ ! -f "$ENV_FILE" ]; then
  ENV_FILE=".env.test.example"
fi

# Read only known numeric port keys; never source the env file as shell code.
read_port() {
  local key="$1" fallback="$2" value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1 | tr -d '[:space:]')"
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$fallback"
  fi
}

FRONTEND_PORT="$(read_port TEST_FRONTEND_PORT 13000)"
HUB_PORT="$(read_port TEST_HUB_PORT 18000)"
DORM_PORT="$(read_port TEST_DORM_PORT 18001)"
LIBRARY_PORT="$(read_port TEST_LIBRARY_PORT 18002)"
ML_PORT="$(read_port TEST_ML_PORT 19000)"

PASS=0
FAIL=0

check() {
  local name="$1" url="$2" expected="$3"
  local code="000"

  for _ in $(seq 1 30); do
    code="$(curl -sS -L -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || true)"
    if [ "$code" = "$expected" ] || { [ "$expected" = "2xx" ] && [[ "$code" =~ ^2|^3 ]]; }; then
      printf "  PASS  %-24s (%s)\n" "$name" "$code"
      PASS=$((PASS + 1))
      return
    fi
    sleep 2
  done

  printf "  FAIL  %-24s (got %s, expected %s)\n" "$name" "$code" "$expected"
  FAIL=$((FAIL + 1))
}

echo "Isolated test stack smoke checks"
check "Hub /health" "http://localhost:${HUB_PORT}/health" "200"
check "Hub /health/db" "http://localhost:${HUB_PORT}/health/db" "200"
check "Hub JWKS" "http://localhost:${HUB_PORT}/.well-known/jwks.json" "200"
check "Admin frontend" "http://localhost:${FRONTEND_PORT}/" "2xx"
check "ML /health" "http://localhost:${ML_PORT}/health" "200"

COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.test.yml --profile subsystems)
if [ -n "$("${COMPOSE[@]}" ps -q subsystem-dorm-test 2>/dev/null)" ]; then
  check "Dorm subsystem" "http://localhost:${DORM_PORT}/" "2xx"
fi
if [ -n "$("${COMPOSE[@]}" ps -q subsystem-library-test 2>/dev/null)" ]; then
  check "Library subsystem" "http://localhost:${LIBRARY_PORT}/" "2xx"
fi

echo
echo "Result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
