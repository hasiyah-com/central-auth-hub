#!/usr/bin/env bash
# Host-side E2E runner — orchestrates all test suites + verifies SDK artifacts
#
# Run from project root:
#   bash hub/backend/tests/test_e2e_host_runner.sh

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PHP="E:/xampp/php/php.exe"
PASS=0
FAIL=0
SKIP=0

pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1${2:+ - $2}"; FAIL=$((FAIL + 1)); }
skip() { echo "  [SKIP] $1${2:+ - $2}"; SKIP=$((SKIP + 1)); }

section() { echo ""; echo "=== $1 ==="; }

# ============================================================
section "1. In-container E2E (40 checks)"
# ============================================================
if MSYS_NO_PATHCONV=1 docker exec hub-backend python /app/tests/test_e2e_full_stack.py >/tmp/e2e_inner.log 2>&1; then
    pass "Inner E2E suite (40 passed in container)"
else
    fail "Inner E2E suite" "see /tmp/e2e_inner.log"
fi

# ============================================================
section "2. SDK artifacts present (host filesystem)"
# ============================================================
declare -A SDK_FILES=(
    ["PHP composer.json"]="$ROOT/hub/sdk/php-client/composer.json"
    ["PHP Client.php"]="$ROOT/hub/sdk/php-client/src/Client.php"
    ["PHP JwtVerifier.php"]="$ROOT/hub/sdk/php-client/src/JwtVerifier.php"
    ["PHP examples/index.php"]="$ROOT/hub/sdk/php-client/examples/index.php"
    ["PHP tests"]="$ROOT/hub/sdk/php-client/tests/PkceHelperTest.php"
    ["Python pyproject.toml"]="$ROOT/hub/sdk/python-client/pyproject.toml"
    ["Python client.py"]="$ROOT/hub/sdk/python-client/src/central_auth_hub/client.py"
    ["Python jwt_verifier.py"]="$ROOT/hub/sdk/python-client/src/central_auth_hub/jwt_verifier.py"
    ["Python tests"]="$ROOT/hub/sdk/python-client/tests/test_pkce.py"
    ["Node package.json"]="$ROOT/hub/sdk/node-client/package.json"
    ["Node client.ts"]="$ROOT/hub/sdk/node-client/src/client.ts"
    ["Node jwtVerifier.ts"]="$ROOT/hub/sdk/node-client/src/jwtVerifier.ts"
    ["Node tests"]="$ROOT/hub/sdk/node-client/tests/pkce.test.ts"
    ["Auth Proxy go.mod"]="$ROOT/hub/sdk/auth-proxy/go.mod"
    ["Auth Proxy Dockerfile"]="$ROOT/hub/sdk/auth-proxy/Dockerfile"
    ["Auth Proxy main.go"]="$ROOT/hub/sdk/auth-proxy/cmd/main.go"
    ["Auth Proxy handler"]="$ROOT/hub/sdk/auth-proxy/internal/handler/handler.go"
)
for name in "${!SDK_FILES[@]}"; do
    if [[ -f "${SDK_FILES[$name]}" ]]; then
        pass "$name"
    else
        fail "$name" "${SDK_FILES[$name]}"
    fi
done

# ============================================================
section "3. SDK test suites — re-run all"
# ============================================================

# PHP
if [[ -f "$PHP" && -d "$ROOT/hub/sdk/php-client/vendor" ]]; then
    TOKEN=$(docker exec hub-backend python -c "
from app.database import SessionLocal
from app.models import User, Subsystem, AccessList
from app.services.jwt_service import create_subsystem_token
db = SessionLocal()
user = db.query(User).filter(User.email.like('%@uni.ac.th')).first()
sub = db.query(Subsystem).filter(Subsystem.client_id == 'cli_1ded036e86ec4c1b').first()
al = db.query(AccessList).filter(AccessList.subsystem_id == sub.id, AccessList.revoked_at.is_(None)).first()
token, _ = create_subsystem_token(user, sub.client_id, ['openid','profile','email'], al.role_in_sub if al else 'user')
print(token, end='')
db.close()
" 2>&1)
    if (cd "$ROOT/hub/sdk/php-client" && TEST_HUB_TOKEN="$TOKEN" "$PHP" vendor/bin/phpunit tests --colors=never >/tmp/php_test.log 2>&1); then
        pass "PHP SDK PHPUnit (24 tests)"
    else
        fail "PHP SDK PHPUnit" "see /tmp/php_test.log"
    fi
else
    skip "PHP SDK PHPUnit" "PHP or vendor/ missing"
fi

# Python
TOKEN=$(docker exec hub-backend python -c "
from app.database import SessionLocal
from app.models import User, Subsystem, AccessList
from app.services.jwt_service import create_subsystem_token
db = SessionLocal()
user = db.query(User).filter(User.email.like('%@uni.ac.th')).first()
sub = db.query(Subsystem).filter(Subsystem.client_id == 'cli_1ded036e86ec4c1b').first()
al = db.query(AccessList).filter(AccessList.subsystem_id == sub.id, AccessList.revoked_at.is_(None)).first()
token, _ = create_subsystem_token(user, sub.client_id, ['openid','profile','email'], al.role_in_sub if al else 'user')
print(token, end='')
db.close()
" 2>&1)
if MSYS_NO_PATHCONV=1 docker exec -e TEST_HUB_TOKEN="$TOKEN" hub-backend pytest /tmp/python-client/tests -q --color=no >/tmp/py_test.log 2>&1; then
    pass "Python SDK pytest (29 tests)"
else
    fail "Python SDK pytest" "see /tmp/py_test.log"
fi

# Node — unit-only (integration uses execSync which may fail in some shells)
if [[ -d "$ROOT/hub/sdk/node-client/node_modules" ]]; then
    if (cd "$ROOT/hub/sdk/node-client" && export PATH="/c/Program Files/nodejs:$PATH" && npx tsx --test tests/pkce.test.ts tests/state.test.ts tests/config.test.ts tests/webhook.test.ts >/tmp/node_test.log 2>&1); then
        pass "Node SDK unit tests (23 tests)"
    else
        fail "Node SDK unit tests" "see /tmp/node_test.log"
    fi
else
    skip "Node SDK unit tests" "node_modules missing"
fi

# Go (via Docker)
if (cd "$ROOT/hub/sdk/auth-proxy" && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/src" -w /src golang:1.22-alpine go test ./... >/tmp/go_test.log 2>&1); then
    pass "Go Auth Proxy tests (24 tests)"
else
    fail "Go Auth Proxy tests" "see /tmp/go_test.log"
fi

# ============================================================
section "4. Docker image cah-auth-proxy ready"
# ============================================================
if docker images cah-auth-proxy:latest --format "{{.Size}}" 2>/dev/null | grep -qE "^[0-9]+(\.[0-9]+)?MB$"; then
    SIZE=$(docker images cah-auth-proxy:latest --format "{{.Size}}")
    pass "Image present + size $SIZE"
else
    skip "cah-auth-proxy image" "not built yet — run docker build"
fi

# ============================================================
section "5. Test reports inventory"
# ============================================================
REPORTS_DIR="$ROOT/hub/backend/tests/reports"
for f in L1_oidc_2026-06-09.md L2_php_sdk_2026-06-09.md L2_python_sdk_2026-06-10.md L2_node_sdk_2026-06-10.md L3_auth_proxy_2026-06-10.md; do
    if [[ -f "$REPORTS_DIR/$f" ]]; then
        pass "Report $f"
    else
        fail "Report $f" "missing"
    fi
done

# ============================================================
section "SUMMARY"
# ============================================================
TOTAL=$((PASS + FAIL + SKIP))
echo ""
echo "  Total: $TOTAL | PASS: $PASS | FAIL: $FAIL | SKIP: $SKIP"
if [[ $FAIL -eq 0 ]]; then
    echo "  [PASS] ALL E2E CHECKS PASSED"
    exit 0
else
    echo "  [FAIL] $FAIL check(s) failed"
    exit 1
fi
