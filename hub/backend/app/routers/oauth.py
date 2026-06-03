"""OAuth router — flow เต็มของการ login ผ่าน Subsystem.

Flow:
  1. Subsystem redirect ผู้ใช้มา  GET /oauth/authorize
       (client_id, redirect_uri, state, code_challenge)
  2. Hub ตรวจ client_id + redirect_uri -> เก็บ request ใน Redis -> ส่งไป Google
  3. Google ส่งกลับ  GET /oauth/callback
       Hub: หา user -> เช็ค access_list -> สร้าง authorization code -> redirect กลับ subsystem
  4. Subsystem เรียก  POST /oauth/token  (server-to-server)
       (code, client_id, client_secret, code_verifier)
       Hub: verify secret + verify PKCE -> ออก JWT (มี audience + ข้อมูลตาม scope)

ตัวช่วยทดสอบ (ใช้เฉพาะตอน dev):
  GET /oauth/pkce-helper   -> สร้างคู่ code_verifier/code_challenge
  GET /oauth/test-callback -> หน้าจำลอง redirect_uri ของ subsystem
"""

import json
import secrets
from datetime import datetime

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip
from app.rate_limiter import limiter
from app.models import AccessList, LoginSession, Subsystem, User
from app.redis_client import redis_client
from app.routers.auth import oauth  # ใช้ Authlib client ตัวเดียวกับ Week 2
from app.services.alert_service import maybe_alert_ml_risk
from app.services.audit_service import log_action
from app.services.identity_challenge import is_user_challenged
from app.services.subsystem_health import get_status as get_health_status
from app.services.feature_extraction import (
    extract_session_features,
    parse_browser,
    parse_device_type,
    parse_os_name,
)
from app.services.geoip import lookup_country
from app.services.ip_blacklist import is_blacklisted
from app.services.hooks import (
    EVT_OAUTH_AUTHORIZED,
    EVT_OAUTH_FAILURE,
    emit,
)
from app.services.jwt_service import create_subsystem_token
from app.services.pkce import generate_pkce_pair, verify_pkce
from app.security.risk_engine import evaluate_login_risk
from app.services.secret_service import verify_secret

router = APIRouter()

AUTH_REQUEST_TTL = 600  # OAuth request เก็บใน Redis 10 นาที
AUTH_CODE_TTL = 60  # authorization code อายุ 60 วินาที


# ============ 1. /oauth/authorize — จุดเริ่มต้น ============


@router.get("/authorize")
@limiter.limit(settings.rate_limit_token)
async def authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str = "",
    db: Session = Depends(get_db),
):
    """Subsystem redirect ผู้ใช้มาที่นี่เพื่อเริ่ม login."""
    # 1. ตรวจ client_id
    subsystem = db.query(Subsystem).filter(Subsystem.client_id == client_id).first()
    if not subsystem:
        raise HTTPException(status_code=400, detail="client_id ไม่ถูกต้อง")
    if subsystem.status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"subsystem ยังเป็น '{subsystem.status}' — รอ admin อนุมัติก่อน",
        )

    # 1b. Pre-flight health check — ถ้า subsystem ล่ม อย่าให้ user เสียเวลาผ่าน Google
    #     แสดงหน้า maintenance HTML แทน redirect ไป Google
    #     (ใช้ cache ของ background ping ที่อ่าน Redis — fast path, ไม่ ping จริง)
    health = get_health_status(str(subsystem.id))
    if health and health.get("status") == "down":
        log_action(
            db,
            actor_id=None,
            action="oauth_preflight_subsystem_down",
            target_type="subsystem",
            target_id=subsystem.id,
            ip=get_client_ip(request),
            metadata={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "health": health,
            },
        )
        db.commit()
        return HTMLResponse(
            content=_maintenance_html(
                subsystem_name=subsystem.name,
                health=health,
            ),
            status_code=503,
        )

    # 2. ตรวจ redirect_uri ต้องตรงกับที่ลงทะเบียน (กัน open redirect)
    if redirect_uri not in subsystem.redirect_uris:
        raise HTTPException(
            status_code=400,
            detail="redirect_uri ไม่ตรงกับที่ลงทะเบียนไว้",
        )

    # 3. เก็บ OAuth request ใน Redis โดยใช้ "state token ของ Hub" เป็น key
    #    (state ที่ subsystem ส่งมาเก็บแยกเป็นข้อมูลภายใน)
    #
    #    การใช้ state token เป็น Redis key ทำให้:
    #    - เปิดหลาย tab พร้อมกันได้ (ไม่ทับกันใน session)
    #    - state ที่ Google ส่งกลับ = key ของ Redis ตรงๆ
    hub_state = secrets.token_urlsafe(24)
    redis_client.setex(
        f"authreq:{hub_state}",
        AUTH_REQUEST_TTL,
        json.dumps(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,  # state ของ subsystem (ส่งกลับตอน redirect)
                "code_challenge": code_challenge,
                "subsystem_id": str(subsystem.id),
                "scope": subsystem.scope,  # ใช้ scope ที่ลงทะเบียนไว้
            }
        ),
    )

    # 4. ส่ง hub_state ของเราไปกับ Google — Authlib จะเก็บใน session
    #    แบบ keyed-by-state (_state_google_{hub_state}_data) ทำให้ multi-tab ใช้ได้
    return await oauth.google.authorize_redirect(
        request, settings.oauth_callback_uri, state=hub_state
    )


# ============ 2. /oauth/callback — Google ส่งกลับ ============


@router.get("/callback")
@limiter.limit(settings.rate_limit_token)
async def oauth_callback(
    request: Request,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """Google ส่งผู้ใช้กลับมาที่นี่ — Hub ตรวจสิทธิ์แล้วออก authorization code.

    state ที่ Google ส่งกลับ = hub_state ที่ใช้เป็น Redis key (ใน /authorize)
    """
    if not state:
        raise HTTPException(status_code=400, detail="ไม่พบ state parameter")

    raw = redis_client.get(f"authreq:{state}")
    if not raw:
        raise HTTPException(status_code=400, detail="OAuth request หมดอายุ — เริ่มใหม่")
    authreq = json.loads(raw)

    # แลก code ของ Google เป็น token
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"Google OAuth ล้มเหลว: {e.error}")

    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="ไม่ได้รับข้อมูลจาก Google")
    email = userinfo["email"]
    client_ip = get_client_ip(request)

    # หา user ใน Hub
    user = db.query(User).filter(User.email == email).first()
    if not user:
        log_action(
            db,
            actor_id=None,
            action="oauth_login_failed_unknown_email",
            target_type="subsystem",
            target_id=authreq["subsystem_id"],
            ip=client_ip,
            metadata={"email": email, "client_id": authreq["client_id"]},
        )
        db.commit()
        await emit(
            EVT_OAUTH_FAILURE,
            {
                "client_id": authreq["client_id"],
                "reason": "unknown_email",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=f"อีเมล {email} ไม่ใช่ผู้ใช้ของมหาวิทยาลัย",
        )
    if user.status != "active":
        log_action(
            db,
            actor_id=user.id,
            action="oauth_login_failed_inactive",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={
                "email": email,
                "status": user.status,
                "subsystem_id": authreq["subsystem_id"],
            },
        )
        db.commit()
        await emit(
            EVT_OAUTH_FAILURE,
            {
                "user_id": str(user.id),
                "client_id": authreq["client_id"],
                "reason": f"inactive_{user.status}",
                "ip": client_ip,
            },
        )
        raise HTTPException(status_code=403, detail=f"บัญชีถูก {user.status}")

    # *** เช็ค Access List — user มีสิทธิ์เข้า subsystem นี้ไหม ***
    access = (
        db.query(AccessList)
        .filter(
            AccessList.subsystem_id == authreq["subsystem_id"],
            AccessList.user_id == user.id,
            AccessList.revoked_at.is_(None),
        )
        .first()
    )
    if not access:
        log_action(
            db,
            actor_id=user.id,
            action="oauth_login_failed_not_in_whitelist",
            target_type="subsystem",
            target_id=authreq["subsystem_id"],
            ip=client_ip,
            metadata={
                "email": email,
                "user_id": str(user.id),
                "client_id": authreq["client_id"],
            },
        )
        db.commit()
        await emit(
            EVT_OAUTH_FAILURE,
            {
                "user_id": str(user.id),
                "client_id": authreq["client_id"],
                "reason": "not_in_whitelist",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=403,
            detail="คุณไม่อยู่ใน whitelist ของระบบย่อยนี้ — ติดต่อ admin",
        )

    # *** เช็ค identity challenge — admin เคย Revoke Level 2 ไหม? ***
    if is_user_challenged(str(user.id)):
        log_action(
            db,
            actor_id=user.id,
            action="oauth_login_blocked_by_identity_challenge",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"email": email, "client_id": authreq["client_id"]},
        )
        db.commit()
        await emit(
            EVT_OAUTH_FAILURE,
            {
                "user_id": str(user.id),
                "client_id": authreq["client_id"],
                "reason": "identity_challenge_pending",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "ระบบกำลังรอคุณยืนยันตัวตน — กรุณาคลิกลิงก์ใน email ที่ส่งให้ก่อน login "
                "(ถ้า email หาย ติดต่อ admin)"
            ),
        )

    # ผูก google_sub ครั้งแรก — ถ้ามีอยู่แล้วต้องตรงกัน (กัน account hijack)
    google_sub = userinfo["sub"]
    if user.google_sub and user.google_sub != google_sub:
        log_action(
            db,
            actor_id=user.id,
            action="oauth_login_failed_google_sub_mismatch",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"email": email, "subsystem_id": authreq["subsystem_id"]},
        )
        db.commit()
        await emit(
            EVT_OAUTH_FAILURE,
            {
                "user_id": str(user.id),
                "client_id": authreq["client_id"],
                "reason": "google_sub_mismatch",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=403,
            detail="Google account นี้ไม่ตรงกับบัญชีที่เคยใช้ login — ติดต่อ admin",
        )
    if not user.google_sub:
        user.google_sub = google_sub

    # ===== Sync profile fields from Google userinfo =====
    # Google's userinfo is the source of truth for display name.
    # We update on every login so users see their real name in subsystems
    # instead of any placeholder set during pre-provisioning.
    google_name = (userinfo.get("name") or "").strip()
    if google_name and google_name != (user.full_name or "").strip():
        old_name = user.full_name
        user.full_name = google_name
        log_action(
            db,
            actor_id=user.id,
            action="profile_synced_from_google",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"field": "full_name", "old": old_name, "new": google_name},
        )

    # ===== Hybrid RBA 4-Layer Risk Scoring =====
    # อ้างอิง: Freeman 2016, Wiefling 2022, F-RBA 2024, NIST SP 800-63B-4
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    # 0) GeoIP lookup — fail-safe (None ถ้า DB หาย / private IP / lookup error)
    geo_country = lookup_country(client_ip)

    # 1) สกัด feature vector จาก session + history (12 features)
    features = extract_session_features(
        db,
        user_id=user.id,
        ip=client_ip,
        user_agent=user_agent,
        geo_country=geo_country,
    )

    # 2) 4-Layer Risk Engine (Rule → Behavior → IForest → Aggregation)
    risk = await evaluate_login_risk(
        features=features,
        user_id=str(user.id),
        ip=client_ip,
        geo_country=geo_country,
        db=db,
        shadow_mode=settings.ml_shadow_mode,
    )
    risk_score = risk["score"]
    actual_decision = risk["decision"]
    risk_reasons = risk["reasons"]
    risk_breakdown = risk["breakdown"]
    anomaly_score = risk_breakdown.get("iforest_raw", 0.0)

    # 2.5) Alert admin ทาง Telegram/email ถ้า score เกิน threshold
    # (fail-safe — ส่ง alert ไม่ได้ห้าม block flow login)
    subsystem_for_alert = (
        db.query(Subsystem).filter(Subsystem.id == authreq["subsystem_id"]).first()
    )
    maybe_alert_ml_risk(
        user_email=user.email,
        user_id=str(user.id),
        risk_score=risk_score,
        decision=actual_decision,
        risk_breakdown=risk_breakdown,
        risk_reasons=risk_reasons,
        ip=client_ip,
        geo_country=geo_country,
        subsystem_name=subsystem_for_alert.name if subsystem_for_alert else None,
    )

    # 3) บันทึก login session พร้อม 4-layer risk data
    db.add(
        LoginSession(
            user_id=user.id,
            subsystem_id=authreq["subsystem_id"],
            ip=client_ip,
            user_agent=user_agent,
            geo_country=geo_country,
            os_name=parse_os_name(user_agent),
            browser=parse_browser(user_agent),
            device_type=parse_device_type(user_agent),
            anomaly_score=anomaly_score,
            risk_score=risk_score,
            risk_breakdown=risk_breakdown,
            risk_reasons=risk_reasons,
            decision=actual_decision,
            is_attack_ip=is_blacklisted(db, client_ip),
        )
    )

    # 4) Block decision → ปฏิเสธ login
    if actual_decision == "block":
        log_action(
            db,
            actor_id=user.id,
            action="login_blocked_by_risk_engine",
            target_type="subsystem",
            target_id=authreq["subsystem_id"],
            ip=client_ip,
            metadata={
                "risk_score": risk_score,
                "breakdown": risk_breakdown,
                "reasons": risk_reasons,
            },
        )
        db.commit()
        await emit(
            EVT_OAUTH_FAILURE,
            {
                "user_id": str(user.id),
                "client_id": authreq["client_id"],
                "reason": "risk_blocked",
                "ip": client_ip,
                "risk_score": risk_score,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=(
                f"การ login ถูกบล็อกโดยระบบตรวจสอบความปลอดภัย "
                f"(risk_score={risk_score:.3f}, reasons={risk_reasons}) "
                f"— ติดต่อ admin หากเป็นเรื่องผิดพลาด"
            ),
        )

    # (challenge decision → Week 9-10 MFA flow — ตอนนี้ปล่อยผ่าน + log)

    # สร้าง authorization code (อายุ 60 วินาที, ใช้ครั้งเดียว)
    auth_code = secrets.token_urlsafe(32)
    redis_client.setex(
        f"authcode:{auth_code}",
        AUTH_CODE_TTL,
        json.dumps(
            {
                "user_id": str(user.id),
                "client_id": authreq["client_id"],
                "subsystem_id": authreq["subsystem_id"],
                "code_challenge": authreq["code_challenge"],
                "scope": authreq["scope"],
                "role_in_sub": access.role_in_sub,
            }
        ),
    )

    log_action(
        db,
        actor_id=user.id,
        action="oauth_authorized",
        target_type="subsystem",
        target_id=authreq["subsystem_id"],
        ip=client_ip,
        metadata={
            "risk_score": risk_score,
            "anomaly_score": anomaly_score,
            "decision": actual_decision,
            "breakdown": risk_breakdown,
            "reasons": risk_reasons,
        },
    )
    db.commit()

    await emit(
        EVT_OAUTH_AUTHORIZED,
        {
            "user_id": str(user.id),
            "client_id": authreq["client_id"],
            "subsystem_id": authreq["subsystem_id"],
            "ip": client_ip,
        },
    )

    # cleanup + redirect กลับ subsystem พร้อม code + state
    redis_client.delete(f"authreq:{state}")

    sep = "&" if "?" in authreq["redirect_uri"] else "?"
    callback_url = (
        f"{authreq['redirect_uri']}{sep}code={auth_code}&state={authreq['state']}"
    )
    return RedirectResponse(url=callback_url)


# ============ 3. /oauth/token — แลก code เป็น JWT (server-to-server) ============


@router.post("/token")
@limiter.limit(settings.rate_limit_token)
def token_exchange(
    request: Request,
    grant_type: str = Form(...),
    code: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    code_verifier: str = Form(...),
    db: Session = Depends(get_db),
):
    """Subsystem เรียก endpoint นี้แบบ server-to-server เพื่อแลก code เป็น JWT."""
    if grant_type != "authorization_code":
        raise HTTPException(
            status_code=400, detail="grant_type ต้องเป็น 'authorization_code'"
        )

    # 1. ดึง authorization code จาก Redis แบบ atomic (get + delete พร้อมกัน)
    #    กัน race: 2 requests ใช้ code เดียวกันแล้วผ่านทั้งคู่
    #    code ที่ผ่าน redis getdel ไปแล้วใช้ซ้ำไม่ได้แน่นอน
    raw = redis_client.getdel(f"authcode:{code}")
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="authorization code ไม่ถูกต้องหรือหมดอายุ (อายุแค่ 60 วินาที)",
        )
    code_data = json.loads(raw)

    # 2. ตรวจ client_id ตรงกับตอนสร้าง code ไหม
    if code_data["client_id"] != client_id:
        raise HTTPException(status_code=400, detail="client_id ไม่ตรงกับ code")

    # 3. ตรวจ client_secret (Argon2id verify) — ลอง primary ก่อน, fallback legacy ในช่วง grace
    subsystem = db.query(Subsystem).filter(Subsystem.client_id == client_id).first()
    if not subsystem:
        raise HTTPException(status_code=401, detail="client_id ไม่พบ")

    primary_ok = verify_secret(subsystem.client_secret_hash, client_secret)
    legacy_ok = False
    if (
        not primary_ok
        and subsystem.previous_client_secret_hash
        and subsystem.previous_secret_expires_at
        and subsystem.previous_secret_expires_at > datetime.utcnow()
    ):
        legacy_ok = verify_secret(subsystem.previous_client_secret_hash, client_secret)

    if not (primary_ok or legacy_ok):
        raise HTTPException(status_code=401, detail="client_secret ไม่ถูกต้อง")

    # 4. ตรวจ PKCE — SHA256(code_verifier) ต้องตรงกับ code_challenge
    if not verify_pkce(code_verifier, code_data["code_challenge"]):
        raise HTTPException(status_code=400, detail="PKCE verification ล้มเหลว")

    # 5. หา user แล้วออก JWT (มี audience + ข้อมูลตาม scope)
    #    (code ถูกลบไปแล้วตอน getdel ที่ขั้น 1)
    user = db.query(User).filter(User.id == code_data["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบ user")

    access_token, token_jti = create_subsystem_token(
        user=user,
        client_id=client_id,
        scope=code_data["scope"],
        role_in_sub=code_data["role_in_sub"],
    )

    # Track jti บน LoginSession ล่าสุดของ (user, subsystem) สำหรับ force-revoke
    latest_session = (
        db.query(LoginSession)
        .filter(
            LoginSession.user_id == user.id,
            LoginSession.subsystem_id == code_data["subsystem_id"],
        )
        .order_by(LoginSession.created_at.desc())
        .first()
    )
    if latest_session and latest_session.jti is None:
        latest_session.jti = token_jti

    log_action(
        db,
        actor_id=user.id,
        action="token_issued",
        target_type="subsystem",
        target_id=code_data["subsystem_id"],
        ip=get_client_ip(request),
        metadata={"jti": token_jti},
    )
    db.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "scope": code_data["scope"],
        "role_in_subsystem": code_data["role_in_sub"],
    }


# ============ 4. /oauth/logout — back-channel logout จาก subsystem ============


@router.post("/logout")
@limiter.limit(settings.rate_limit_token)
def logout(
    request: Request,
    client_id: str = Form(...),
    client_secret: str = Form(...),
    hub_user_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """Subsystem แจ้ง Hub ว่า user logout แล้ว (server-to-server).

    Auth: client_id + client_secret (เหมือน /oauth/token)
    Action: mark logout_at บน LoginSession ล่าสุดของ (user, subsystem) ที่ยัง active
    Fail-safe: ถ้าไม่มี active session ก็คืน 200 (idempotent) — ไม่ใช่ error
    """
    # 1. Verify client credentials (Argon2id)
    subsystem = db.query(Subsystem).filter(Subsystem.client_id == client_id).first()
    if not subsystem or not verify_secret(subsystem.client_secret_hash, client_secret):
        raise HTTPException(status_code=401, detail="client credentials ไม่ถูกต้อง")

    # 2. หา user
    user = db.query(User).filter(User.id == hub_user_id).first()
    if not user:
        # idempotent — user อาจถูกลบไปแล้ว
        return {"status": "noop", "reason": "user not found"}

    # 3. หา LoginSession ล่าสุดที่ active (logout_at IS NULL)
    from datetime import datetime as _dt

    sess = (
        db.query(LoginSession)
        .filter(
            LoginSession.user_id == user.id,
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.logout_at.is_(None),
        )
        .order_by(LoginSession.created_at.desc())
        .first()
    )
    closed = False
    if sess:
        sess.logout_at = _dt.utcnow()
        closed = True

    log_action(
        db,
        actor_id=user.id,
        action="subsystem_logout",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "session_closed": closed,
            "session_id": str(sess.id) if sess else None,
        },
    )
    db.commit()
    return {"status": "ok", "session_closed": closed}


# ============ Maintenance page (Pre-flight Use Case 2) ============


def _maintenance_html(subsystem_name: str, health: dict) -> str:
    """หน้า HTML แสดงตอน subsystem ล่ม (alt. ของ redirect ไป Google)."""
    checked_at = (health.get("checked_at") or "").replace("T", " ")[:19]
    error = health.get("error") or "subsystem ไม่ตอบ health check"
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>{subsystem_name} ปิดปรับปรุง</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: 'Sarabun', system-ui, sans-serif; background: #f8fafc;
          margin: 0; min-height: 100vh; display: grid; place-items: center;
          padding: 40px 16px; color: #0f172a; }}
  .card {{ max-width: 560px; width: 100%; background: #fff; border-radius: 16px;
           overflow: hidden; box-shadow: 0 4px 12px rgba(15,23,42,0.08); }}
  .hero {{ background: linear-gradient(135deg,#dc2626,#7f1d1d); padding: 32px;
           color: #fff; text-align: center; }}
  .icon {{ font-size: 56px; line-height: 1; }}
  .title {{ font-size: 22px; font-weight: 800; margin-top: 12px; }}
  .body {{ padding: 28px 32px; }}
  .reason {{ background: #fef2f2; border: 1px solid #fecaca; border-radius: 10px;
             padding: 12px 14px; margin: 14px 0; font-size: 12px;
             font-family: 'JetBrains Mono', monospace; color: #991b1b;
             word-break: break-word; }}
  .ts {{ font-size: 11px; color: #94a3b8; margin-top: 14px;
         font-family: monospace; }}
  .actions {{ margin-top: 22px; }}
  .btn {{ display: inline-block; padding: 10px 18px; background: #0f172a;
          color: #fff; text-decoration: none; border-radius: 8px;
          font-weight: 600; font-size: 14px; }}
  .footer {{ padding: 14px 32px; font-size: 11px; color: #94a3b8;
             border-top: 1px solid #f1f5f9; }}
</style></head><body>
<div class="card">
  <div class="hero">
    <div class="icon">🔧</div>
    <div class="title">{subsystem_name}<br>ปิดปรับปรุงชั่วคราว</div>
  </div>
  <div class="body">
    <p>ระบบนี้กำลังมีปัญหาทางเทคนิค — ทีมงานได้รับแจ้งและอยู่ระหว่างแก้ไข</p>
    <p>กรุณาลองอีกครั้งในอีก 5 นาที</p>
    <div class="reason">
      <strong>เหตุผล (สำหรับ admin):</strong><br>
      {error}
    </div>
    <div class="ts">Health check ล่าสุด: {checked_at} UTC</div>
    <div class="actions">
      <a href="javascript:history.back()" class="btn">← กลับหน้าก่อน</a>
    </div>
  </div>
  <div class="footer">
    Central Auth Hub · pre-flight check ก่อน OAuth redirect
  </div>
</div>
</body></html>"""


# ============ ตัวช่วยทดสอบ (dev only) ============


@router.get("/pkce-helper")
def pkce_helper():
    """สร้างคู่ code_verifier / code_challenge สำหรับทดสอบ.

    ในระบบจริง subsystem จะสร้างคู่นี้เอง — endpoint นี้มีไว้ช่วยทดสอบ Week 4
    """
    verifier, challenge = generate_pkce_pair()
    return {
        "code_verifier": verifier,
        "code_challenge": challenge,
        "note": "ใช้ code_challenge ตอนเรียก /oauth/authorize และ code_verifier ตอน /oauth/token",
    }


@router.get("/test-callback", response_class=HTMLResponse)
def test_callback(code: str = "", state: str = ""):
    """หน้าจำลอง redirect_uri ของ subsystem — แสดง code + state ที่ Hub ส่งกลับมา.

    ตอนทดสอบ: ลงทะเบียน subsystem ด้วย
        redirect_uri = http://localhost:8000/oauth/test-callback
    """
    html = f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>OAuth Test Callback</title>
<style>
  body {{ font-family: system-ui, "Sarabun", sans-serif; background: #f1f5f9;
          padding: 40px 16px; }}
  .box {{ max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px;
          padding: 28px 32px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  h1 {{ font-size: 20px; color: #16a34a; }}
  .field {{ font-family: monospace; background: #1f2937; color: #86efac;
            padding: 12px 14px; border-radius: 8px; word-break: break-all;
            margin: 8px 0; font-size: 13px; }}
  .label {{ font-size: 12px; color: #64748b; margin-top: 12px; }}
  .step {{ background: #eff6ff; border-left: 4px solid #2563eb; padding: 12px 14px;
           border-radius: 4px; margin-top: 16px; font-size: 13px; }}
</style></head><body>
<div class="box">
  <h1>✓ Hub ส่ง authorization code กลับมาแล้ว</h1>
  <p>นี่คือหน้าจำลอง redirect_uri ของ subsystem — ในระบบจริง subsystem
     จะเอา code นี้ไปแลก token เอง</p>

  <div class="label">authorization code</div>
  <div class="field">{code or "(ไม่มี code)"}</div>

  <div class="label">state (subsystem ต้องเช็คว่าตรงกับที่ส่งไป)</div>
  <div class="field">{state or "(ไม่มี state)"}</div>

  <div class="step">
    <strong>ขั้นต่อไป — แลก code เป็น token:</strong><br>
    ไปที่ <code>/docs</code> -> <code>POST /oauth/token</code> -> ใส่:<br>
    grant_type = <code>authorization_code</code><br>
    code = code ด้านบน<br>
    client_id = client_id ของ subsystem<br>
    client_secret = client_secret ของ subsystem<br>
    code_verifier = code_verifier ที่คู่กับ code_challenge ที่ใช้ตอน authorize
  </div>
</div>
</body></html>"""
    return HTMLResponse(content=html)
