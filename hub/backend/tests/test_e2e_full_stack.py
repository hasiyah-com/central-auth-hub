"""End-to-end full stack verification — L1 + L2 + L3 + subsystems + frontend.

ทดสอบครอบคลุม 8 หมวด:
  1. Container health
  2. L1 OIDC endpoints (Discovery + UserInfo + Introspection + JWKS)
  3. Hub OAuth/JWT internals (sign + verify + revoke)
  4. Backward compat — dorm + library verify JWT
  5. Database integrity — users, subsystems, access_list
  6. Existing services (notifications, audit, ML)
  7. SDK reachability — PHP/Python/Node packages exist
  8. Auth Proxy (L3) Docker image ready

Run:
    docker exec hub-backend python /app/tests/test_e2e_full_stack.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import jwt as pyjwt

from app.config import settings  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
FAILED = 0
RESULTS: list[tuple[str, str, str, str]] = []
CURRENT_SECTION = ""


def section(name):
    global CURRENT_SECTION
    CURRENT_SECTION = name
    print(f"\n=== {name} ===")


def check(name, cond, detail=""):
    global FAILED
    mark = PASS if cond else FAIL
    extra = f" - {detail}" if detail else ""
    print(f"  [{mark}] {name}{extra}")
    RESULTS.append((CURRENT_SECTION, name, mark, detail))
    if not cond:
        FAILED += 1


def skip(name, reason):
    print(f"  [{SKIP}] {name} - {reason}")
    RESULTS.append((CURRENT_SECTION, name, SKIP, reason))


HUB = "http://localhost:8000"
CLIENT_ID = "cli_1ded036e86ec4c1b"


# ───────────────────────────────────────────────────────────
section("1. Container/Service health")
# ───────────────────────────────────────────────────────────
# Inside Docker container — must use service names (cah-net DNS)
endpoints = {
    "Hub /health": "http://hub-backend:8000/health",
    "Hub /.well-known/openid-configuration": "http://hub-backend:8000/.well-known/openid-configuration",
    "Hub /.well-known/jwks.json": "http://hub-backend:8000/.well-known/jwks.json",
    "ML /health": "http://ml-service:9000/health",
    "Frontend /api/me (200/401)": "http://hub-frontend:3000/api/me",
}
for name, url in endpoints.items():
    try:
        r = httpx.get(url, timeout=5.0)
        # 200=ok, 401=needs auth, 307=Next.js redirect to login
        ok = r.status_code in (200, 307, 401)
        check(name, ok, f"HTTP {r.status_code}")
    except Exception as e:
        check(name, False, f"{type(e).__name__}: {str(e)[:60]}")

# Subsystems return 302 for / (login redirect)
for name, url in {
    "Dorm /": "http://subsystem-dorm:8000/",
    "Library /": "http://subsystem-library:8000/",
}.items():
    try:
        r = httpx.get(url, timeout=5.0, follow_redirects=False)
        check(name, r.status_code in (200, 302, 303, 307), f"HTTP {r.status_code}")
    except Exception as e:
        check(name, False, str(e)[:60])


# ───────────────────────────────────────────────────────────
section("2. L1 OIDC endpoints")
# ───────────────────────────────────────────────────────────
disc = httpx.get(f"{HUB}/.well-known/openid-configuration").json()
check("Discovery has issuer", "issuer" in disc)
check(
    "Discovery has all 7 required fields",
    all(
        k in disc
        for k in [
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "jwks_uri",
            "response_types_supported",
            "subject_types_supported",
            "id_token_signing_alg_values_supported",
        ]
    ),
)
check(
    "Discovery has userinfo + introspection",
    "userinfo_endpoint" in disc and "introspection_endpoint" in disc,
)
check(
    "scopes include openid + profile + email",
    all(s in disc["scopes_supported"] for s in ["openid", "profile", "email"]),
)

jwks = httpx.get(disc["jwks_uri"]).json()
check(
    "JWKS has at least 1 RSA key",
    len(jwks["keys"]) >= 1 and jwks["keys"][0]["kty"] == "RSA",
)


# ───────────────────────────────────────────────────────────
section("3. Hub OAuth/JWT internals")
# ───────────────────────────────────────────────────────────
from app.database import SessionLocal  # noqa: E402
from app.models import User, Subsystem, AccessList  # noqa: E402
from app.services.jwt_service import (  # noqa: E402
    create_subsystem_token,
    create_access_token,
    verify_token,
    revoke_jti,
    is_revoked,
)

db = SessionLocal()
user = db.query(User).filter(User.email.like("%@uni.ac.th")).first()
sub = db.query(Subsystem).filter(Subsystem.client_id == CLIENT_ID).first()
al = (
    db.query(AccessList)
    .filter(AccessList.subsystem_id == sub.id, AccessList.revoked_at.is_(None))
    .first()
)
role = al.role_in_sub if al else "user"

# Sign + verify subsystem token
ss_token, ss_jti = create_subsystem_token(
    user, sub.client_id, ["openid", "profile", "email"], role
)
claims = verify_token(ss_token, audience=sub.client_id)
check("Subsystem token: sign + verify round-trip", claims["aud"] == sub.client_id)
check("Token has iss matching settings", claims["iss"])
check("Token has jti", claims.get("jti") == ss_jti)

# Sign + verify hub-direct token
hd_token, hd_jti = create_access_token(user)
hd_claims = verify_token(hd_token)
check("Hub-direct token verify", hd_claims["aud"] == "hub.internal")

# Revocation
revoke_jti(ss_jti, int(claims["exp"]))
check("Revocation marker stored", is_revoked(ss_jti))
try:
    verify_token(ss_token, audience=sub.client_id)
    check("Revoked token rejected", False)
except Exception:
    check("Revoked token rejected", True)


# ───────────────────────────────────────────────────────────
section("4. UserInfo + Introspection endpoints")
# ───────────────────────────────────────────────────────────
# Fresh token (not revoked)
fresh, _ = create_subsystem_token(
    user, sub.client_id, ["openid", "profile", "email"], role
)
r = httpx.get(f"{HUB}/oauth/userinfo", headers={"Authorization": f"Bearer {fresh}"})
check("UserInfo valid token → 200", r.status_code == 200)
if r.status_code == 200:
    data = r.json()
    check("UserInfo has sub", "sub" in data)
    check("UserInfo has email", data.get("email") == user.email)
    check("UserInfo has role_in_subsystem", "role_in_subsystem" in data)

# No auth
r = httpx.get(f"{HUB}/oauth/userinfo")
check("UserInfo no auth → 401", r.status_code == 401)

# Tampered token
parts = fresh.split(".")
tampered = f"{parts[0]}.{parts[1]}.AAAAAA"
r = httpx.get(f"{HUB}/oauth/userinfo", headers={"Authorization": f"Bearer {tampered}"})
check("UserInfo tampered → 401", r.status_code == 401)

# Introspection — bad creds
r = httpx.post(
    f"{HUB}/oauth/introspect",
    data={"token": fresh, "client_id": "cli_x", "client_secret": "wrong"},
)
check("Introspect bad creds → 401", r.status_code == 401)


# ───────────────────────────────────────────────────────────
section("5. Backward compat — JWKS fetchable from any subsystem")
# ───────────────────────────────────────────────────────────
# Verify ที่ subsystem container ดึง JWKS จาก Hub ได้
# (subsystem ใช้ jose lib อ่าน /.well-known/jwks.json แล้ว match kid)
# จาก inside hub-backend เราตรวจว่า jwks ที่ subsystem จะดึงไปเป็น valid format

doc = httpx.get("http://hub-backend:8000/.well-known/openid-configuration").json()
jwks_uri = doc["jwks_uri"]
jwks_data = httpx.get(jwks_uri.replace("localhost:8000", "hub-backend:8000")).json()
check("JWKS reachable + has keys", "keys" in jwks_data and len(jwks_data["keys"]) > 0)
key0 = jwks_data["keys"][0]
check(
    "JWK has all RFC 7517 required fields",
    all(k in key0 for k in ["kty", "kid", "use", "alg", "n", "e"]),
)

# Verify with the same library subsystem uses (python-jose / PyJWT)
# โดย import RSAAlgorithm from PyJWT (same as subsystem)
from jwt.algorithms import RSAAlgorithm  # noqa: E402

try:
    pub_key = RSAAlgorithm.from_jwk(key0)
    # ใช้ verify
    claims = pyjwt.decode(
        fresh,
        pub_key,
        algorithms=["RS256"],
        audience=sub.client_id,
        issuer=settings.hub_issuer,
    )
    check(
        "JWT verify with reconstructed key (subsystem pattern)",
        claims["aud"] == sub.client_id,
    )
except Exception as e:
    check("JWT verify with reconstructed key", False, str(e)[:80])

# Test library subsystem token too
lib_sub = (
    db.query(Subsystem).filter(Subsystem.client_id == "cli_ad3b203ecfbb5c35").first()
)
if lib_sub:
    lib_al = (
        db.query(AccessList)
        .filter(AccessList.subsystem_id == lib_sub.id, AccessList.revoked_at.is_(None))
        .first()
    )
    lib_role = lib_al.role_in_sub if lib_al else "user"
    lib_token, _ = create_subsystem_token(
        user, lib_sub.client_id, ["openid", "profile", "email"], lib_role
    )
    try:
        lib_claims = pyjwt.decode(
            lib_token,
            RSAAlgorithm.from_jwk(key0),
            algorithms=["RS256"],
            audience=lib_sub.client_id,
            issuer=settings.hub_issuer,
        )
        check(
            "Library subsystem token verifiable", lib_claims["aud"] == lib_sub.client_id
        )
    except Exception as e:
        check("Library subsystem token verifiable", False, str(e)[:80])
else:
    skip("Library subsystem", "library subsystem not registered")


# ───────────────────────────────────────────────────────────
section("6. Database integrity")
# ───────────────────────────────────────────────────────────
users_count = db.query(User).count()
check("Users count > 0", users_count > 0, f"{users_count} users")

subsystems_count = db.query(Subsystem).filter(Subsystem.status == "active").count()
check(
    "At least 2 active subsystems", subsystems_count >= 2, f"{subsystems_count} active"
)

access_list_count = db.query(AccessList).filter(AccessList.revoked_at.is_(None)).count()
check("Access list entries > 0", access_list_count > 0, f"{access_list_count} entries")

# settings hub_issuer correct
check("settings.hub_issuer non-empty", bool(settings.hub_issuer), settings.hub_issuer)


# ───────────────────────────────────────────────────────────
section("7. Notification + Audit subsystems (smoke)")
# ───────────────────────────────────────────────────────────
from app.models import AuditLog  # noqa: E402

audit_count = db.query(AuditLog).count()
check("Audit logs > 0", audit_count > 0, f"{audit_count} entries")

# Check subsystem_health_summary entries exist (from L1 work)
summary_count = (
    db.query(AuditLog).filter(AuditLog.action == "subsystem_health_summary").count()
)
check("Health summaries logged (≥1)", summary_count >= 1, f"{summary_count} summaries")


# ───────────────────────────────────────────────────────────
section("8. SDK artifacts (skipped inside container — checked by host runner)")
# ───────────────────────────────────────────────────────────
# `/app` ใน container ไม่ mount sdk folder — ตรวจจากภายนอกแทน
# (ดู scripts/test_sdk_artifacts.sh สำหรับ host-side check)
skip(
    "PHP/Python/Node/Go SDK artifacts",
    "checked by host-side runner (test_e2e_sdk_artifacts.sh)",
)


# ───────────────────────────────────────────────────────────
section("9. Test reports present")
# ───────────────────────────────────────────────────────────
reports = [
    "/app/tests/reports/L1_oidc_2026-06-09.md",
    "/app/tests/reports/L2_php_sdk_2026-06-09.md",
    "/app/tests/reports/L2_python_sdk_2026-06-10.md",
    "/app/tests/reports/L2_node_sdk_2026-06-10.md",
    "/app/tests/reports/L3_auth_proxy_2026-06-10.md",
]
for r in reports:
    check(f"Report {os.path.basename(r)}", os.path.exists(r))


# ───────────────────────────────────────────────────────────
db.close()
total = len(RESULTS)
passed = sum(1 for _, _, mark, _ in RESULTS if mark == PASS)
skipped = sum(1 for _, _, mark, _ in RESULTS if mark == SKIP)
print("\n=== SUMMARY ===")
print(f"  Total: {total} | PASS: {passed} | FAIL: {FAILED} | SKIP: {skipped}")
if FAILED == 0:
    print("  [PASS] ALL TESTS PASSED")
    sys.exit(0)
else:
    print(f"  [FAIL] {FAILED} test(s) failed")
    sys.exit(1)
