"""OIDC Discovery + UserInfo + Token Introspection.

มาตรฐานที่อ้างอิง:
  - OpenID Connect Discovery 1.0   https://openid.net/specs/openid-connect-discovery-1_0.html
  - OpenID Connect Core 1.0 §5.3   https://openid.net/specs/openid-connect-core-1_0.html#UserInfo
  - OpenID Connect Core 1.0 §5.4   https://openid.net/specs/openid-connect-core-1_0.html#ScopeClaims
  - RFC 8414  OAuth 2.0 Authorization Server Metadata
  - RFC 7662  OAuth 2.0 Token Introspection

จุดประสงค์:
  ลด DX overhead ของ dev — แค่อ่าน `/.well-known/openid-configuration`
  ก็ได้ทุก endpoint + scope + algorithm → ใช้ library OIDC ของทุกภาษาได้
  (league/oauth2-client PHP, openid-client Node, authlib Python ฯลฯ)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AccessList, Subsystem, User
from app.services.jwt_service import is_revoked, verify_token
from app.services.secret_service import verify_secret

router = APIRouter()


# ============ Scope mapping (OIDC alias → Hub fields) ============
# OIDC Core 1.0 §5.4 กำหนด scope value `profile` รวมหลาย claim พื้นฐาน
# Hub map `profile` → ฟิลด์ profile-related ของ Hub
# `email` map ตรงไปตรงมา · `openid` เป็น marker เฉยๆ (ไม่ map field)
OIDC_PROFILE_SCOPE_EXPANSION = {
    "name",
    "student_id",
    "employee_id",
    "faculty",
    "major",
    "year",
    "position",
}


def expand_oidc_scopes(scope: list[str]) -> set[str]:
    """รับ scope list (อาจมี openid/profile/email + Hub scopes)
    คืน effective Hub scope set ที่ใช้ map → JWT claims.

    `openid` ไม่ map field — แค่ marker (ตาม OIDC spec ต้องมีถ้าใช้ OIDC flow)
    `profile` expand → 7 Hub field
    `email` → email
    Hub scope เดิม (student_id, faculty, ...) คงเดิม — backward compatible
    """
    out: set[str] = set()
    for s in scope or []:
        if s == "openid":
            continue  # marker — no field mapping
        if s == "profile":
            out.update(OIDC_PROFILE_SCOPE_EXPANSION)
            continue
        # email / Hub-specific scopes pass through
        out.add(s)
    return out


# ============ Authentication helper สำหรับ /oauth/userinfo ============


def _user_from_bearer(authorization: Optional[str], db: Session) -> tuple[User, dict]:
    """ตรวจ Authorization: Bearer <jwt> → คืน (user, claims).

    Verify ที่ aud = client_id ที่ระบุใน token (ไม่ใช่ hub.internal)
    เพราะ /oauth/userinfo รับ subsystem token (OIDC Core §5.3.1)
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="missing Authorization: Bearer header",
            headers={"WWW-Authenticate": 'Bearer realm="oauth"'},
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="empty bearer token",
            headers={"WWW-Authenticate": 'Bearer realm="oauth"'},
        )

    # decode (skip aud check first — เราต้องการรู้ aud ใน token เพื่อ verify ทีหลัง)
    import jwt as pyjwt

    try:
        unverified = pyjwt.decode(token, options={"verify_signature": False})
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"bad token: {e}",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    expected_aud = unverified.get("aud")
    if not expected_aud:
        raise HTTPException(
            status_code=401,
            detail="token missing aud claim",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    # verify ครบ — signature, iss, exp, aud ที่อ้าง
    try:
        claims = verify_token(token, audience=expected_aud)
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"token verify failed: {e}",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    # โหลด user
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="token missing sub")
    user = db.query(User).filter(User.id == sub).first()
    if not user:
        raise HTTPException(status_code=401, detail="user not found")

    return user, claims


# ============ Endpoint 1 — OIDC Discovery ============


@router.get("/.well-known/openid-configuration")
def openid_configuration(request: Request):
    """OIDC Discovery document — RFC 8414 + OIDC Discovery 1.0 §3.

    Client OIDC ทุกภาษาใช้ doc นี้ auto-config endpoint, scope, algorithm
    """
    issuer = settings.hub_issuer
    # base URL ของ endpoint — ใช้ hub_base_url (configurable)
    base = settings.hub_base_url.rstrip("/")

    return {
        # Required (OIDC Discovery §3)
        "issuer": issuer,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "jwks_uri": f"{base}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        # Recommended
        "userinfo_endpoint": f"{base}/oauth/userinfo",
        "scopes_supported": [
            "openid",
            "profile",
            "email",
            "name",
            "student_id",
            "employee_id",
            "faculty",
            "major",
            "year",
            "position",
            "phone",
            "address",
        ],
        "claims_supported": [
            "iss",
            "sub",
            "aud",
            "exp",
            "iat",
            "jti",
            "role_in_subsystem",
            "name",
            "email",
            "student_id",
            "employee_id",
            "faculty",
            "major",
            "year",
            "position",
            "phone",
            "address",
        ],
        # OAuth metadata (RFC 8414)
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        # Introspection (RFC 7662)
        "introspection_endpoint": f"{base}/oauth/introspect",
        "introspection_endpoint_auth_methods_supported": ["client_secret_post"],
        # ส่วนเสริม informational
        "service_documentation": f"{base}/docs",
    }


# ============ Endpoint 2 — UserInfo (OIDC Core §5.3) ============


@router.get("/oauth/userinfo")
@router.post("/oauth/userinfo")
def userinfo(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """UserInfo endpoint — รับ subsystem token → คืน claims ของ user
    ตาม scope ที่ token ได้รับ (OIDC Core 1.0 §5.3.2 — Successful Response).

    คืน sub เป็นค่าหลัก + claims อื่นๆ ตาม scope ใน token เดิม
    (Hub ใส่ field เข้า JWT ตาม scope อยู่แล้ว — userinfo จะคืนของที่อยู่ใน token)
    """
    user, claims = _user_from_bearer(authorization, db)

    # ตาม OIDC Core §5.3.2 → ต้องมี `sub` เสมอ
    # field อื่นๆ มาจาก JWT claims ที่ Hub ใส่ไว้ตาม scope
    result = {"sub": str(user.id)}

    # claims ที่อนุญาตให้ส่งกลับ (mirror ของ create_subsystem_token mapping)
    passthrough = {
        "name",
        "email",
        "student_id",
        "employee_id",
        "faculty",
        "major",
        "year",
        "position",
        "phone",
        "address",
        "role_in_subsystem",
        # ใส่ user_type เพิ่ม (ไม่อยู่ใน scope ปัจจุบัน แต่มี value ใช้ใน Hub)
        "user_type",
    }
    for k in passthrough:
        v = claims.get(k)
        if v is not None and v != "":
            result[k] = v

    # ถ้า claims ไม่มี role_in_subsystem (ไม่ปกติ แต่ป้องกัน edge case)
    # ลอง lookup จาก access_list
    if "role_in_subsystem" not in result and claims.get("aud"):
        client_id = claims["aud"]
        sub_obj = db.query(Subsystem).filter(Subsystem.client_id == client_id).first()
        if sub_obj:
            entry = (
                db.query(AccessList)
                .filter(
                    AccessList.subsystem_id == sub_obj.id,
                    AccessList.user_id == user.id,
                    AccessList.revoked_at.is_(None),
                )
                .first()
            )
            if entry and entry.role_in_sub:
                result["role_in_subsystem"] = entry.role_in_sub

    return result


# ============ Endpoint 3 — Token Introspection (RFC 7662) ============


def _verify_client_credentials(
    db: Session, client_id: str, client_secret: str
) -> Subsystem:
    """ตรวจ client_id + secret — ใช้ใน /oauth/introspect"""
    sub = db.query(Subsystem).filter(Subsystem.client_id == client_id).first()
    if not sub:
        raise HTTPException(status_code=401, detail="invalid_client")
    if not sub.client_secret_hash:
        raise HTTPException(status_code=401, detail="client has no secret set")
    if not verify_secret(client_secret, sub.client_secret_hash):
        raise HTTPException(status_code=401, detail="invalid_client")
    if sub.status != "active":
        raise HTTPException(status_code=403, detail=f"client status={sub.status}")
    return sub


@router.post("/oauth/introspect")
def introspect(
    token: str = Form(...),
    token_type_hint: Optional[str] = Form(None),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    db: Session = Depends(get_db),
):
    """Token Introspection — RFC 7662 §2.

    Client ใช้ verify ว่า access_token ยัง active ไหม + ดู metadata
    (สำหรับ stateless verify โดยไม่ต้อง cache JWKS เอง)

    Auth ของ endpoint นี้ = client_id + client_secret (server-to-server เท่านั้น)
    """
    client = _verify_client_credentials(db, client_id, client_secret)

    # decode unverified ก่อน (เพื่อรู้ aud)
    import jwt as pyjwt

    try:
        unverified = pyjwt.decode(token, options={"verify_signature": False})
    except Exception:
        return {"active": False}

    aud = unverified.get("aud")
    # client ห้าม introspect token ของ client อื่น (security)
    if aud and aud != client.client_id:
        return {"active": False}

    # verify เต็มรูปแบบ (signature, iss, exp, aud)
    try:
        claims = verify_token(token, audience=aud)
    except Exception:
        return {"active": False}

    # ตรวจ revocation list ด้วย (verify_token ตรวจอยู่แล้ว แต่ป้องกัน edge case)
    jti = claims.get("jti")
    if jti and is_revoked(jti):
        return {"active": False}

    # response ตาม RFC 7662 §2.2
    return {
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
        # Hub-specific แต่ helpful
        "role_in_subsystem": claims.get("role_in_subsystem"),
    }


def _infer_scope_from_claims(claims: dict) -> list[str]:
    """พยายาม reverse-engineer scope จาก claims ที่อยู่ใน token.

    Hub ไม่ได้เก็บ scope ใน JWT (ไม่อยู่ใน payload) — infer จาก field ที่ปรากฏ
    """
    out: list[str] = []
    field_to_scope = {
        "email": "email",
        "name": "name",
        "student_id": "student_id",
        "employee_id": "employee_id",
        "faculty": "faculty",
        "major": "major",
        "year": "year",
        "position": "position",
        "phone": "phone",
        "address": "address",
    }
    for field, scope_name in field_to_scope.items():
        if claims.get(field) is not None:
            out.append(scope_name)
    return out
