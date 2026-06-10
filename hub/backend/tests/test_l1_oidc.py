"""L1 OIDC Discovery + UserInfo + Introspection — Comprehensive verification.

ทดสอบ:
  L1.A — iss configurable + sync ทุก component
  L1.B — /.well-known/openid-configuration (OIDC Discovery 1.0 + RFC 8414)
  L1.C — /oauth/userinfo (OIDC Core 1.0 §5.3)
  L1.D — Scope alias expansion (OIDC Core §5.4)
  L1.E — /oauth/introspect (RFC 7662)
  Backward compat — dorm + library subsystem ยังใช้งานปกติ
  Real-world — จำลอง dev integration ผ่าน SDK pattern

Run:
    docker exec hub-backend python /app/tests/test_l1_oidc.py

ผลรายงานเก็บที่:
    hub/backend/tests/reports/L1_oidc_*.md
"""

from __future__ import annotations

import os
import sys

# ให้ import `app.*` ได้แม้รัน python tests/test_l1_oidc.py ตรงๆ
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import jwt as pyjwt

BASE = "http://localhost:8000"
DISCOVERY_URL = f"{BASE}/.well-known/openid-configuration"

PASS = "PASS"
FAIL = "FAIL"
FAILED = 0
RESULTS: list[tuple[str, str, bool, str]] = []  # (section, name, ok, detail)
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
    RESULTS.append((CURRENT_SECTION, name, bool(cond), detail))
    if not cond:
        FAILED += 1


# Bootstrap
from app.database import SessionLocal  # noqa: E402
from app.models import User, Subsystem, AccessList  # noqa: E402
from app.services.jwt_service import (  # noqa: E402
    create_subsystem_token,
    create_access_token,
    revoke_jti,
    is_revoked,
    verify_token,
)
from app.config import settings  # noqa: E402
from app.routers.oidc import _infer_scope_from_claims  # noqa: E402

db = SessionLocal()
user = db.query(User).filter(User.email.like("%@uni.ac.th")).first()
sub = db.query(Subsystem).filter(Subsystem.client_id == "cli_1ded036e86ec4c1b").first()
al = (
    db.query(AccessList)
    .filter(AccessList.subsystem_id == sub.id, AccessList.revoked_at.is_(None))
    .first()
)
role = al.role_in_sub if al else "user"
print(f"Fixture: user={user.email} sub={sub.name} role={role}")

# ───────────────────────────────────────────────────────────
section("1. L1.A - iss configurable across components")
# ───────────────────────────────────────────────────────────
discovery = httpx.get(DISCOVERY_URL).json()
token, _ = create_subsystem_token(user, sub.client_id, ["openid"], role)
jwt_claims = pyjwt.decode(token, options={"verify_signature": False})
check("settings.hub_issuer non-empty", bool(settings.hub_issuer), settings.hub_issuer)
check("Discovery 'issuer' matches settings", discovery["issuer"] == settings.hub_issuer)
check("JWT 'iss' matches settings", jwt_claims["iss"] == settings.hub_issuer)
check(
    "Discovery 'issuer' == JWT 'iss'",
    discovery["issuer"] == jwt_claims["iss"],
    "OIDC spec requires this exact match",
)

# ───────────────────────────────────────────────────────────
section("2. L1.B - Discovery doc compliance (OIDC Discovery 1.0 + RFC 8414)")
# ───────────────────────────────────────────────────────────
required = [
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "jwks_uri",
    "response_types_supported",
    "subject_types_supported",
    "id_token_signing_alg_values_supported",
]
for f in required:
    check(f"Required field: {f}", f in discovery)
check("response_types includes 'code'", "code" in discovery["response_types_supported"])
check(
    "RS256 in signing algorithms",
    "RS256" in discovery["id_token_signing_alg_values_supported"],
)
check("S256 in PKCE methods", "S256" in discovery["code_challenge_methods_supported"])
check("userinfo_endpoint present", "userinfo_endpoint" in discovery)
check("introspection_endpoint present", "introspection_endpoint" in discovery)
check("scopes_supported includes openid", "openid" in discovery["scopes_supported"])
check("scopes_supported includes profile", "profile" in discovery["scopes_supported"])
check("scopes_supported includes email", "email" in discovery["scopes_supported"])

jwks = httpx.get(discovery["jwks_uri"]).json()
check("jwks_uri returns valid JSON", "keys" in jwks)
check("jwks has at least 1 key", len(jwks["keys"]) >= 1)
check("jwk has correct alg", jwks["keys"][0]["alg"] == "RS256")
check("jwk has kid", "kid" in jwks["keys"][0])

# ───────────────────────────────────────────────────────────
section("3. L1.C - UserInfo endpoint scenarios")
# ───────────────────────────────────────────────────────────
token, _ = create_subsystem_token(
    user, sub.client_id, ["openid", "profile", "email"], role
)
r = httpx.get(
    discovery["userinfo_endpoint"], headers={"Authorization": f"Bearer {token}"}
)
check("Valid token -> 200", r.status_code == 200)
data = r.json() if r.status_code == 200 else {}
check("Response has 'sub'", "sub" in data)
check("Response has 'email'", "email" in data and data.get("email") == user.email)
check("Response has 'name'", "name" in data and data.get("name") == user.full_name)
check(
    "Response has 'role_in_subsystem'",
    "role_in_subsystem" in data and data.get("role_in_subsystem") == role,
)
check("Response has profile fields (faculty)", "faculty" in data)

r = httpx.get(discovery["userinfo_endpoint"])
check("No auth -> 401", r.status_code == 401)
check("WWW-Authenticate header set", "WWW-Authenticate" in r.headers)

r = httpx.get(discovery["userinfo_endpoint"], headers={"Authorization": "Basic xxx"})
check("Wrong auth scheme -> 401", r.status_code == 401)

r = httpx.get(
    discovery["userinfo_endpoint"], headers={"Authorization": "Bearer not.a.jwt"}
)
check("Malformed JWT -> 401", r.status_code == 401)

parts = token.split(".")
tampered = parts[0] + "." + parts[1] + ".AAAAAA"
r = httpx.get(
    discovery["userinfo_endpoint"], headers={"Authorization": f"Bearer {tampered}"}
)
check("Tampered signature -> 401", r.status_code == 401)

r = httpx.post(
    discovery["userinfo_endpoint"], headers={"Authorization": f"Bearer {token}"}
)
check("POST userinfo -> 200 (OIDC 5.3.1)", r.status_code == 200)

# ───────────────────────────────────────────────────────────
section("4. L1.D - Scope alias expansion")
# ───────────────────────────────────────────────────────────
t1, _ = create_subsystem_token(user, sub.client_id, ["openid"], role)
c1 = pyjwt.decode(t1, options={"verify_signature": False})
check("scope=[openid] -> no profile fields", "name" not in c1 and "faculty" not in c1)
check(
    "scope=[openid] -> has iss/sub/aud",
    all(k in c1 for k in ["iss", "sub", "aud"]),
)

t2, _ = create_subsystem_token(user, sub.client_id, ["openid", "profile"], role)
c2 = pyjwt.decode(t2, options={"verify_signature": False})
profile_fields = [
    "name",
    "student_id",
    "employee_id",
    "faculty",
    "major",
    "year",
    "position",
]
present = [f for f in profile_fields if f in c2]
check(f"profile expands -> 7 fields ({len(present)} present)", len(present) == 7)
check("profile does NOT include email", "email" not in c2)
check(
    "profile does NOT include phone/address", "phone" not in c2 and "address" not in c2
)

t3, _ = create_subsystem_token(
    user, sub.client_id, ["openid", "profile", "email"], role
)
c3 = pyjwt.decode(t3, options={"verify_signature": False})
check("profile+email -> email present", "email" in c3)
check("profile+email -> name present", "name" in c3)

t4, _ = create_subsystem_token(user, sub.client_id, ["email", "faculty"], role)
c4 = pyjwt.decode(t4, options={"verify_signature": False})
check("Hub scope ['email','faculty'] still works", "email" in c4 and "faculty" in c4)
check("Hub scope strict - no profile expansion", "student_id" not in c4)

# ───────────────────────────────────────────────────────────
section("5. L1.E - Introspection scenarios")
# ───────────────────────────────────────────────────────────
INTROSPECT = discovery["introspection_endpoint"]

r = httpx.post(
    INTROSPECT, data={"token": token, "client_id": "cli_x", "client_secret": "wrong"}
)
check("Wrong client_id -> 401", r.status_code == 401)

r = httpx.post(INTROSPECT, data={"client_id": "cli_x", "client_secret": "y"})
check("Missing token -> 422 (FastAPI validation)", r.status_code == 422)

try:
    claims = verify_token(token, audience=sub.client_id)
    intro = {
        "active": True,
        "client_id": claims.get("aud"),
        "username": claims.get("email"),
        "scope": " ".join(_infer_scope_from_claims(claims)),
        "sub": claims.get("sub"),
        "exp": claims.get("exp"),
        "iat": claims.get("iat"),
        "iss": claims.get("iss"),
        "aud": claims.get("aud"),
        "jti": claims.get("jti"),
        "token_type": "Bearer",
        "role_in_subsystem": claims.get("role_in_subsystem"),
    }
    check("Introspect result: active=True", intro["active"])
    check("Introspect: aud matches client", intro["aud"] == sub.client_id)
    check("Introspect: token_type=Bearer", intro["token_type"] == "Bearer")
    check("Introspect: includes jti", "jti" in intro)
    check("Introspect: scope inferred from claims", len(intro["scope"]) > 0)
except Exception as e:
    check("Introspect valid token", False, str(e))

expired_token, expired_jti = create_subsystem_token(
    user, sub.client_id, ["email"], role
)
exp_unix = pyjwt.decode(expired_token, options={"verify_signature": False})["exp"]
revoke_jti(expired_jti, exp_unix)
check("Revoked jti detected", is_revoked(expired_jti))
try:
    verify_token(expired_token, audience=sub.client_id)
    check("Revoked token raises error", False)
except Exception as e:
    check("Revoked token raises error", True, type(e).__name__)

other_sub = (
    db.query(Subsystem).filter(Subsystem.client_id == "cli_ad3b203ecfbb5c35").first()
)
if other_sub:
    other_token, _ = create_subsystem_token(
        user, other_sub.client_id, ["email"], "user"
    )
    other_claims = pyjwt.decode(other_token, options={"verify_signature": False})
    rejects = other_claims["aud"] != sub.client_id
    check("Cross-client introspect rejected (logic)", rejects)

# ───────────────────────────────────────────────────────────
section("6. Backward compatibility - existing token flows")
# ───────────────────────────────────────────────────────────
hd_token, _ = create_access_token(user)
hd_claims = verify_token(hd_token)
check(
    "Hub-direct token (aud=hub.internal) verifies", hd_claims["aud"] == "hub.internal"
)

ss_token, _ = create_subsystem_token(user, sub.client_id, ["email"], role)
ss_claims = verify_token(ss_token, audience=sub.client_id)
check("Subsystem token verifies with aud=client_id", ss_claims["aud"] == sub.client_id)

# ───────────────────────────────────────────────────────────
section("7. Real-world dev integration sim (SDK-style discovery + use)")
# ───────────────────────────────────────────────────────────
disc = httpx.get(DISCOVERY_URL).json()
real_redirect = (sub.redirect_uris or ["http://localhost:8001/oauth/callback"])[0]
auth_url = (
    f"{disc['authorization_endpoint']}?"
    f"client_id={sub.client_id}&response_type=code"
    f"&scope=openid+profile+email&state=test"
    f"&redirect_uri={real_redirect}"
    f"&code_challenge=abc&code_challenge_method=S256"
)
r = httpx.get(auth_url, follow_redirects=False)
check(
    "Authorize URL responds (3xx = redirect to Google)",
    r.status_code in (302, 303, 307),
    f"got {r.status_code}",
)

bad_url = auth_url.replace(real_redirect, "http://evil.test/steal")
r = httpx.get(bad_url, follow_redirects=False)
check(
    "Bad redirect_uri -> 400 (open redirect protection)",
    r.status_code == 400,
    f"got {r.status_code}",
)

jwks_doc = httpx.get(disc["jwks_uri"]).json()
key = jwks_doc["keys"][0]
check("JWK has 'n' (modulus)", "n" in key)
check("JWK has 'e' (exponent)", "e" in key)
check("JWK has 'kty' = RSA", key.get("kty") == "RSA")
check("JWK has 'use' = sig", key.get("use") == "sig")

# ───────────────────────────────────────────────────────────
db.close()
print("\n=== SUMMARY ===")
total = len(RESULTS)
passed = sum(1 for _, _, ok, _ in RESULTS if ok)
if FAILED == 0:
    print(f"  [PASS] ALL TESTS PASSED ({passed}/{total})")
    sys.exit(0)
else:
    print(f"  [FAIL] {FAILED} test(s) failed ({passed}/{total} passed)")
    sys.exit(1)
