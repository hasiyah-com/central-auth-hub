"""Authentication router — Google OAuth flow + JWT issuance.

Flow (Week 2 — Hub <-> Google เท่านั้น ยังไม่รวม subsystem):
  1. GET /auth/google/login    -> redirect ผู้ใช้ไป Google
  2. GET /auth/google/callback -> Google ส่งกลับ -> หา user ใน DB -> ออก JWT
  3. GET /auth/me              -> ทดสอบ token (ต้องแนบ Bearer token)
  4. GET /.well-known/jwks.json -> public key สำหรับ verify
"""

import json
import secrets

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from fastapi.security import HTTPAuthorizationCredentials

from app.deps import bearer_scheme, get_client_ip, get_current_user
from app.rate_limiter import limiter
from app.models import LoginSession, User
from app.services.audit_service import log_action
from app.services.feature_extraction import (
    extract_session_features,
    parse_browser,
    parse_device_type,
    parse_os_name,
)
from app.services.geoip import lookup_geo
from app.services.hooks import (
    EVT_LOGIN_FAILURE,
    EVT_LOGIN_PRE,
    EVT_LOGIN_SUCCESS,
    emit,
)
from app.services.jwt_service import create_access_token
from app.services import refresh_token_service
from app.services.auth_policy import get_auth_policy
from app.services.ip_blacklist import is_blacklisted
from app.services.alert_service import maybe_alert_ml_risk
from app.services.identity_challenge import is_user_challenged
from app.security.risk_engine import evaluate_login_risk
from app.services import webauthn_service
from app.services import risk_challenge
from app.services import mfa_policy
from app.redis_client import redis_client

router = APIRouter()

# ============ Frontend login code exchange (กัน token-in-URL) ============
# แทนที่จะ redirect `/auth/callback?token=...&refresh_token=...` (token รั่วผ่าน
# browser history / Referer / proxy/access log) → เก็บ token คู่ใน Redis ใต้ code
# สุ่ม one-time แล้ว redirect พกเฉพาะ `?code=...` · frontend แลก code ผ่าน
# POST /auth/frontend/exchange (getdel atomic single-use ตาม B9) → ได้ token คืน
# code หมดค่าทันทีหลังใช้ + อายุสั้น → หลุดไปก็ใช้ไม่ได้
FRONTEND_LOGIN_CODE_PREFIX = "frontend_login_code:"
FRONTEND_LOGIN_CODE_TTL_SECONDS = 60


def mint_frontend_login_code(*, access_token: str, refresh_token: str | None) -> str:
    """เก็บ token คู่ใน Redis ใต้ code สุ่ม → คืน code (ไม่ใส่ token ใน URL)."""
    code = secrets.token_urlsafe(32)  # 43 อักขระ url-safe
    payload = json.dumps(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": settings.jwt_access_token_expire_minutes * 60,
            "refresh_expires_in": settings.jwt_refresh_token_expire_days * 86400,
        }
    )
    redis_client.setex(
        f"{FRONTEND_LOGIN_CODE_PREFIX}{code}",
        FRONTEND_LOGIN_CODE_TTL_SECONDS,
        payload,
    )
    return code


class FrontendExchangeBody(BaseModel):
    code: str = Field(..., min_length=1, max_length=128)


@router.post("/frontend/exchange")
def frontend_exchange(body: FrontendExchangeBody, response: Response):
    """แลก one-time login code → token คู่ (ย้าย token ออกจาก URL).

    - getdel = atomic single-use → replay/ไม่รู้จัก/หมดอายุ = 400
    - payload เสีย = 400
    - redis ล่ม = 503 (fail closed — ไม่ปล่อยผ่านโดยไม่มี token)
    """
    key = f"{FRONTEND_LOGIN_CODE_PREFIX}{body.code}"
    try:
        raw = redis_client.getdel(key)
    except Exception:
        raise HTTPException(status_code=503, detail="ระบบไม่พร้อมชั่วคราว กรุณาลองใหม่")
    if not raw:
        raise HTTPException(status_code=400, detail="โค้ดเข้าสู่ระบบถูกใช้แล้วหรือหมดอายุ")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="โค้ดเข้าสู่ระบบไม่ถูกต้อง")
    response.headers["Cache-Control"] = "no-store"
    return data


# ============ ตั้งค่า OAuth client (Authlib) ============
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

oauth.register(
    name="line",
    client_id=settings.line_client_id,
    client_secret=settings.line_client_secret,
    server_metadata_url=("https://access.line.me/.well-known/openid-configuration"),
    client_kwargs={"scope": "openid email profile"},
)

# ============ 0. Public: อ่าน auth-policy (วิธี login ที่เปิดใช้) ============


@router.get("/policy")
def auth_policy_public(db: Session = Depends(get_db)):
    """Public — หน้า login (admin console + subsystem) เรียกดูว่าเปิดวิธีไหนบ้าง.

    ไม่มีข้อมูล sensitive — แค่บอกว่า Google/Passkey เปิดไหม → frontend ซ่อนปุ่ม.
    """
    return get_auth_policy(db)


# ============ 1. เริ่ม login — redirect ไป Google ============


@router.get("/google/login")
@limiter.limit(settings.rate_limit_login)
async def google_login(request: Request, db: Session = Depends(get_db)):
    """พาผู้ใช้ไปหน้า login ของ Google. (rate-limited per-IP)

    เคารพ global auth-policy — ถ้า admin ปิด Google login จะปฏิเสธ (403).
    """
    if not get_auth_policy(db)["google"]:
        raise HTTPException(
            status_code=403,
            detail="Google login ถูกปิดใช้งานโดยผู้ดูแลระบบ — ใช้ Passkey แทน",
        )
    await emit(
        EVT_LOGIN_PRE,
        {
            "ip": get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
        },
    )
    redirect_uri = settings.google_redirect_uri
    # prompt=select_account → Google บังคับให้เลือก account ทุกครั้ง
    # (ไม่ auto-login ด้วย session เดิม) — จำเป็นสำหรับ multi-account
    # + การเทส (register passkey หลายอีเมลบนเครื่องเดียว)
    return await oauth.google.authorize_redirect(
        request, redirect_uri, prompt="select_account"
    )


@router.get("/credentials/setup")
@limiter.limit(settings.rate_limit_login)
async def credentials_setup_start(request: Request, db: Session = Depends(get_db)):
    """ปุ่ม "เพิ่มการยืนยันตัวตน" — login Google แล้วไปหน้าตั้ง credential โดยตรง.

    ใช้ได้ **ทุก role รวมนักศึกษา** เพราะ callback ที่ intent นี้จะไม่ออก Hub JWT
    และไม่ผ่าน student block (ตั้ง passkey/TOTP อย่างเดียว ไม่เข้า console).
    reuse redirect URI เดิม → ไม่ต้องเพิ่มอะไรใน Google Console.
    """
    if not get_auth_policy(db)["google"]:
        raise HTTPException(
            status_code=403,
            detail="Google login ถูกปิดใช้งานโดยผู้ดูแลระบบ",
        )
    request.session["cred_setup"] = True
    return await oauth.google.authorize_redirect(
        request, settings.google_redirect_uri, prompt="select_account"
    )


# ============line================
# LINE Login: build authorize URL เอง ไม่พึ่ง Authlib's authorize_redirect
# เพราะ Authlib + LINE OIDC discovery ตีกัน — scope "email" ถูกตัดออก
# (LINE metadata อาจ override หรือ Authlib normalize scope ไม่ตรง)
# Manual approach: เราคุม scope string เอง 100%
@router.get("/line/login")
@limiter.limit(settings.rate_limit_login)
async def line_login(request: Request):
    """พาผู้ใช้ไปหน้า login ของ LINE. (rate-limited per-IP)"""
    import secrets
    from urllib.parse import urlencode

    await emit(
        EVT_LOGIN_PRE,
        {
            "ip": get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
            "provider": "line",
        },
    )

    # state + nonce สำหรับ CSRF protection — เก็บใน session ให้ /line/callback ตรวจ
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    request.session["_line_state"] = state
    request.session["_line_nonce"] = nonce

    params = {
        "response_type": "code",
        "client_id": settings.line_client_id,
        "redirect_uri": settings.line_redirect_uri,
        "state": state,
        # ลำดับ scope ตาม LINE official docs — space separated, email มาก่อนเสมอ
        # ดู: https://developers.line.biz/en/docs/line-login/integrate-line-login/#making-an-authorization-request
        "scope": "openid profile email",
        "nonce": nonce,
        # bot_prompt: ไม่เปิด LINE Bot integration → "normal"
        "bot_prompt": "normal",
    }
    authorize_url = "https://access.line.me/oauth2/v2.1/authorize?" + urlencode(params)
    return RedirectResponse(authorize_url, status_code=302)


# ============ 2. Google callback — ออก JWT ============


@router.get("/google/callback")
@limiter.limit(settings.rate_limit_login)
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """Google ส่งผู้ใช้กลับมาที่นี่พร้อม authorization code. (rate-limited per-IP)"""
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"OAuth ล้มเหลว: {e.error}")

    # ข้อมูล user จาก Google
    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="ไม่ได้รับข้อมูลจาก Google")

    email = userinfo["email"]
    google_sub = userinfo["sub"]

    client_ip = get_client_ip(request)

    # intent=setup — มาจากปุ่ม "เพิ่มการยืนยันตัวตน" (ตั้ง credential อย่างเดียว)
    # ไม่ออก Hub JWT + ไม่ติด student block → นักศึกษาใช้ได้โดยไม่ต้องแก้ RBAC
    setup_intent = bool(request.session.pop("cred_setup", False))

    # หา user ใน DB (จาก 100 คนที่ seed)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        log_action(
            db,
            actor_id=None,
            action="hub_login_failed_unknown_email",
            target_type="email",
            target_id=None,
            ip=client_ip,
            metadata={"email": email, "google_sub": google_sub},
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
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
            action="hub_login_failed_inactive",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"email": email, "status": user.status},
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": f"inactive_{user.status}",
                "ip": client_ip,
            },
        )
        raise HTTPException(status_code=403, detail=f"บัญชีถูก {user.status}")

    # *** นโยบาย: นักศึกษาเข้าระบบกลางโดยตรงไม่ได้ ***
    # (ยกเว้น setup_intent — ตั้ง credential อย่างเดียว ไม่ได้ JWT/console)
    if user.user_type == "student" and not setup_intent:
        log_action(
            db,
            actor_id=user.id,
            action="hub_login_blocked_student",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"email": email, "user_type": "student"},
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": "student_blocked",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "นักศึกษาไม่สามารถเข้าระบบกลางโดยตรงได้ — " "กรุณาเข้าใช้ผ่านระบบย่อยที่ได้รับสิทธิ์ "
            ),
        )

    # *** เช็ค identity challenge — admin เคย Revoke Level 2 ไหม ***
    if is_user_challenged(str(user.id)):
        log_action(
            db,
            actor_id=user.id,
            action="hub_login_blocked_by_identity_challenge",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"email": email},
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": "identity_challenge_pending",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "ระบบกำลังรอคุณยืนยันตัวตน — กรุณาคลิกลิงก์ใน email ที่ส่งให้ก่อน login "
                "(ถ้าไม่ได้รับ email ติดต่อ admin)"
            ),
        )

    # ผูก google_sub ครั้งแรกที่ login (ถ้ายังไม่มี)
    # ถ้ามีอยู่แล้วต้องตรงกัน — กัน account hijack ผ่านการเปลี่ยน Google account
    # ที่ใช้อีเมลเดียวกัน (เช่น เปิด workspace ใหม่ที่ alias ทับ)
    if user.google_sub and user.google_sub != google_sub:
        log_action(
            db,
            actor_id=user.id,
            action="hub_login_failed_google_sub_mismatch",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={
                "email": email,
                "stored_sub_prefix": user.google_sub[:8],
                "received_sub_prefix": google_sub[:8],
            },
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
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

    # ── intent=setup → หน้าตั้ง credential อย่างเดียว (ไม่ออก JWT ไม่แตะ RBA) ──
    # identity ผ่านการตรวจครบแล้ว (email/status/identity-challenge/google_sub guard)
    # reuse หน้า + endpoints ของ OAuth interstitial ผ่าน enroll context เดียวกัน
    if setup_intent:
        db.commit()
        setup_state = "cs_" + secrets.token_urlsafe(24)
        redis_client.setex(
            f"enroll:{setup_state}",
            600,
            json.dumps({"user_id": str(user.id), "email": user.email}),
        )
        log_action(
            db,
            actor_id=user.id,
            action="credential_setup_opened",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"user_type": user.user_type},
        )
        db.commit()
        from app.routers.oauth import _passkey_enroll_html  # lazy — เลี่ยง circular
        from app.services import totp_service

        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        # ส่งสถานะปัจจุบันไปด้วย — ถ้ามี factor แล้วจะขึ้นขั้น "จัดการ"
        # (เปิด Always-2FA ได้เลย ไม่ต้องถูกบังคับเพิ่ม passkey ซ้ำ)
        return HTMLResponse(
            content=_passkey_enroll_html(
                hub_state=setup_state,
                subsystem_name="บัญชีของคุณ",
                user_email=user.email,
                nonce=nonce,
                has_passkey=webauthn_service.count_active(user.id, db) > 0,
                has_totp=totp_service.is_enabled(user.id, db),
                mfa_always=user.effective_mfa_always,
            )
        )

    # Sync display name from Google (source of truth) on every login.
    # Keeps the Hub user's full_name up to date with whatever the user shows
    # in their Google account.
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
    db.commit()

    # ===== Hybrid 4-Layer Risk Scoring (Hub-direct) =====
    # Admin / teacher / staff = high-value target — ตรวจเข้มกว่า user ปกติ
    # ใช้ engine เดียวกับ subsystem OAuth flow → session ทุกแบบมี
    # risk_score / risk_breakdown / risk_reasons ครบใน UI
    user_agent = request.headers.get("user-agent")
    geo_country, geo_city = lookup_geo(client_ip)

    # 1) สกัด features จาก session + history (12 features)
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
        user_agent=user_agent,
    )
    risk_score = risk["score"]
    actual_decision = risk["decision"]
    risk_reasons = risk["reasons"]
    risk_breakdown = risk["breakdown"]
    anomaly_score = risk_breakdown.get("iforest_raw", 0.0)

    # 2.5) Alert admin — Hub-direct login = subsystem_name=None
    maybe_alert_ml_risk(
        user_email=user.email,
        user_id=str(user.id),
        risk_score=risk_score,
        decision=actual_decision,
        risk_breakdown=risk_breakdown,
        risk_reasons=risk_reasons,
        ip=client_ip,
        geo_country=geo_country,
        subsystem_name=None,
    )

    # 3) บันทึก login_session (subsystem_id=None = Hub-direct)
    login_session = LoginSession(
        user_id=user.id,
        subsystem_id=None,
        ip=client_ip,
        user_agent=user_agent,
        geo_country=geo_country,
        geo_city=geo_city,
        os_name=parse_os_name(user_agent),
        browser=parse_browser(user_agent),
        device_type=parse_device_type(user_agent),
        anomaly_score=anomaly_score,
        risk_score=risk_score,
        risk_breakdown=risk_breakdown,
        risk_reasons=risk_reasons,
        decision=actual_decision,
        is_attack_ip=is_blacklisted(db, client_ip),
        login_method="google",
    )
    db.add(login_session)
    db.flush()  # ต้องการ login_session.id สำหรับ MFA challenge

    # ─── Risk-Triggered Decision (Hub direct, Week 9-10) ─────────────────
    # >= 0.85 hard threshold      → BLOCK 403
    # 0.50 ≤ score < 0.85         → MFA flow (Passkey re-auth / grace / force-enroll)
    # Shadow mode = log only (would_* ไม่ enforce). MFA/block เด้งเฉพาะ enforce mode.
    enforcing = not settings.ml_shadow_mode
    is_hard_block = enforcing and risk_score >= settings.risk_block_hard_threshold
    # รวม risk-based MFA + Always-2FA (user pref / admin) เป็น gate เดียว (mfa_policy)
    # — always-on ทำงานแม้ shadow mode; ยืนยันครั้งเดียว ไม่ซ้อนกับ risk
    is_mfa_required = mfa_policy.is_second_factor_required(
        user,
        actual_decision=actual_decision,
        enforcing=enforcing,
        is_hard_block=is_hard_block,
    )

    if is_hard_block:
        log_action(
            db,
            actor_id=user.id,
            action="hub_login_blocked_by_ml",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={
                "score": anomaly_score,
                "risk_score": risk_score,
                "reasons": risk_reasons,
                "features": features,
                "hard_block_threshold": settings.risk_block_hard_threshold,
            },
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": "ml_blocked",
                "ip": client_ip,
                "anomaly_score": anomaly_score,
                "risk_score": risk_score,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=(
                f"การ login ถูกบล็อกโดยระบบตรวจสอบความปลอดภัย "
                f"(risk_score={risk_score:.3f}) — ติดต่อ admin หากเป็นเรื่องผิดพลาด"
            ),
        )

    if is_mfa_required:
        # มี factor ที่สอง (passkey หรือ TOTP) → risk-stepup (รับได้ทั้งคู่);
        # ไม่มีเลย → grace / force-enroll passkey (ต้องตั้งอย่างน้อย 1)
        has_passkey = mfa_policy.has_second_factor(user, db)
        if has_passkey:
            challenge_id = risk_challenge.mint(
                user_id=str(user.id),
                hub_state="",
                authreq=None,
                risk_score=risk_score,
                risk_breakdown=risk_breakdown,
                risk_reasons=risk_reasons,
                provider="hub_direct",
                kind="reauth",
                flow="hub_direct",
            )
            log_action(
                db,
                actor_id=user.id,
                action="risk_mfa_required",
                target_type="user",
                target_id=user.id,
                ip=client_ip,
                metadata={
                    "kind": "reauth",
                    "challenge_id": challenge_id,
                    "risk_score": risk_score,
                },
            )
            db.commit()
            return RedirectResponse(
                f"/auth/passkey/risk-stepup?challenge={challenge_id}",
                status_code=302,
            )

        if webauthn_service.in_grace_period(user, db):
            adoption = webauthn_service.adoption_status(user, db)
            log_action(
                db,
                actor_id=user.id,
                action="risk_grace_period_allowed",
                target_type="user",
                target_id=user.id,
                ip=client_ip,
                metadata={
                    "risk_score": risk_score,
                    "grace_days_remaining": adoption.get("grace_days_remaining"),
                    "days_since_signup": adoption.get("days_since_signup"),
                },
            )
            # fall through → ออก JWT ปกติ
        else:
            challenge_id = risk_challenge.mint(
                user_id=str(user.id),
                hub_state="",
                authreq=None,
                risk_score=risk_score,
                risk_breakdown=risk_breakdown,
                risk_reasons=risk_reasons,
                provider="hub_direct",
                kind="enroll",
                flow="hub_direct",
            )
            log_action(
                db,
                actor_id=user.id,
                action="risk_force_enroll_required",
                target_type="user",
                target_id=user.id,
                ip=client_ip,
                metadata={
                    "kind": "enroll",
                    "challenge_id": challenge_id,
                    "risk_score": risk_score,
                },
            )
            db.commit()
            return RedirectResponse(
                f"/auth/passkey/force-enroll?challenge={challenge_id}",
                status_code=302,
            )

    # log การ login สำเร็จ
    log_action(
        db,
        actor_id=user.id,
        action="hub_login_success",
        target_type="user",
        target_id=user.id,
        ip=client_ip,
        metadata={
            "email": email,
            "user_type": user.user_type,
            "anomaly_score": anomaly_score,
            "decision": actual_decision,
        },
    )
    db.commit()

    # ออก JWT + เก็บ jti กลับไป LoginSession (สำหรับ force-revoke ภายหลัง)
    access_token, token_jti = create_access_token(user)
    login_session.jti = token_jti
    # ออก refresh token คู่กัน (short-lived access + rotating refresh — ดู B-refresh)
    refresh_token, refresh_id = refresh_token_service.issue(
        user_id=str(user.id), session_id=str(login_session.id)
    )
    login_session.refresh_id = refresh_id
    db.commit()

    await emit(
        EVT_LOGIN_SUCCESS,
        {
            "user_id": str(user.id),
            "email": user.email,
            "user_type": user.user_type,
            "ip": client_ip,
        },
    )

    # Redirect ไป Next.js frontend สำหรับทุก non-student
    # (student ถูก block ที่ check ก่อนหน้านี้แล้ว — ไม่ถึงตรงนี้)
    # - admin → middleware ส่งต่อไป /dashboard (Admin Console)
    # - teacher/staff → middleware ส่งต่อไป /developer/subsystems (Developer Portal)
    # ใช้ query ?api=1 ถ้าต้องการ JSON response สำหรับ API client / curl test
    wants_json = request.query_params.get("api") == "1"
    if settings.admin_frontend_url and not wants_json:
        code = mint_frontend_login_code(
            access_token=access_token, refresh_token=refresh_token
        )
        return RedirectResponse(
            f"{settings.admin_frontend_url}/auth/callback?code={code}",
            status_code=302,
        )

    return JSONResponse(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.jwt_access_token_expire_minutes * 60,
            "refresh_expires_in": settings.jwt_refresh_token_expire_days * 86400,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "user_type": user.user_type,
                "faculty": user.faculty,
            },
        }
    )


# =============2.1 line callback==============
# LINE Login quirk: ID token ถูก sign ด้วย HS256 (HMAC + channel secret)
# Authlib's authorize_access_token() พยายาม parse ID token ด้วย RS256 ก่อน
# → ขึ้น UnsupportedAlgorithmError (ดู B42 ใน docs/bugs-encountered.md)
# Workaround: exchange code + ดึง userinfo จาก LINE REST API โดยตรง
# (state validation ยังใช้ session ที่ Authlib เก็บไว้ตอน /line/login)
@router.get("/line/callback")
@limiter.limit(settings.rate_limit_login)
async def line_callback(request: Request, db: Session = Depends(get_db)):
    """LINE ส่งผู้ใช้กลับมาที่นี่พร้อม authorization code. (rate-limited per-IP)"""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"LINE ปฏิเสธ: {error} — {request.query_params.get('error_description', '')}",
        )
    if not code:
        raise HTTPException(
            status_code=400, detail="LINE ไม่ส่ง authorization code กลับมา"
        )

    # 1) Verify state ที่ /line/login เก็บใน session เอง (ไม่ใช่ Authlib)
    stored_state = request.session.pop("_line_state", None)
    if not stored_state or stored_state != state:
        raise HTTPException(
            status_code=400, detail="OAuth state ไม่ถูกต้อง (CSRF protection)"
        )

    # 2) Exchange code → access_token (ผ่าน LINE token endpoint)
    async with httpx.AsyncClient(timeout=10) as http:
        token_resp = await http.post(
            "https://api.line.me/oauth2/v2.1/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.line_redirect_uri,
                "client_id": settings.line_client_id,
                "client_secret": settings.line_client_secret,
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"LINE token exchange ล้มเหลว: {token_resp.text[:200]}",
            )
        token = token_resp.json()

        # 3) ดึง userinfo (OIDC standard endpoint — รับ access_token ไม่ใช่ ID token)
        userinfo_resp = await http.get(
            "https://api.line.me/oauth2/v2.1/userinfo",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"LINE userinfo ดึงไม่สำเร็จ: {userinfo_resp.text[:200]}",
            )
        userinfo = userinfo_resp.json()

    # DEBUG (ลบทีหลัง): log keys ที่ LINE ส่งกลับมา — ช่วยระบุว่า email หายไปทำไม
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "[LINE_DEBUG] userinfo keys=%s, has_email=%s, scope_in_token=%s",
        list(userinfo.keys()),
        "email" in userinfo,
        token.get("scope"),
    )

    if not userinfo:
        raise HTTPException(status_code=400, detail="ไม่ได้รับข้อมูลจาก LINE")

    # LINE ส่ง email มาเฉพาะเมื่อเปิด "Email permission" ใน Console + user อนุญาต
    # ไม่มี fallback แบบ Microsoft's preferred_username — LINE ไม่ส่ง field นั้น
    email = userinfo.get("email")
    if not email:
        raise HTTPException(
            status_code=400,
            detail=(
                "LINE ไม่ส่ง email มาให้ — กรุณา verify email ใน LINE app ก่อน "
                "หรือ revoke permission แล้ว login ใหม่ (ดู docs/guides/add-line-login.md)"
            ),
        )

    # LINE userId = sub claim (รูปแบบ "Uxxxxxxxxxxx..." 33 chars)
    line_sub = userinfo["sub"]

    client_ip = get_client_ip(request)

    # หา user ใน DB (จาก 100 คนที่ seed)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        log_action(
            db,
            actor_id=None,
            action="hub_login_failed_unknown_email_line",
            target_type="email",
            target_id=None,
            ip=client_ip,
            metadata={"email": email, "line_sub": line_sub, "provider": "line"},
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
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
            action="hub_login_failed_inactive",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"email": email, "status": user.status},
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": f"inactive_{user.status}",
                "ip": client_ip,
            },
        )
        raise HTTPException(status_code=403, detail=f"บัญชีถูก {user.status}")

    # *** นโยบาย: นักศึกษาเข้าระบบกลางโดยตรงไม่ได้ ***
    if user.user_type == "student":
        log_action(
            db,
            actor_id=user.id,
            action="hub_login_blocked_student_line",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"email": email, "user_type": "student"},
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": "student_blocked",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "นักศึกษาไม่สามารถเข้าระบบกลางโดยตรงได้ — " "กรุณาเข้าใช้ผ่านระบบย่อยที่ได้รับสิทธิ์ "
            ),
        )

    # *** เช็ค identity challenge — admin เคย Revoke Level 2 ไหม ***
    if is_user_challenged(str(user.id)):
        log_action(
            db,
            actor_id=user.id,
            action="hub_login_blocked_by_identity_challenge",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"email": email},
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": "identity_challenge_pending",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "ระบบกำลังรอคุณยืนยันตัวตน — กรุณาคลิกลิงก์ใน email ที่ส่งให้ก่อน login "
                "(ถ้าไม่ได้รับ email ติดต่อ admin)"
            ),
        )

    # ผูก line_sub ครั้งแรกที่ login (ถ้ายังไม่มี)
    # ถ้ามีอยู่แล้วต้องตรงกัน — กัน account hijack ผ่านการเปลี่ยน LINE account
    # ที่ใช้อีเมลเดียวกัน (user เปลี่ยน LINE account แต่ใช้ Gmail เดิม)
    if user.line_sub and user.line_sub != line_sub:
        log_action(
            db,
            actor_id=user.id,
            action="hub_login_failed_line_sub_mismatch",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={
                "email": email,
                "stored_sub_prefix": user.line_sub[:8],
                "received_sub_prefix": line_sub[:8],
            },
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": "line_sub_mismatch",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=403,
            detail="LINE account นี้ไม่ตรงกับบัญชีที่เคยใช้ login — ติดต่อ admin",
        )
    if not user.line_sub:
        user.line_sub = line_sub

    # Sync display name from LINE (source of truth) on every login.
    # Keeps the Hub user's full_name in sync with the LINE display name.
    line_name = (userinfo.get("name") or "").strip()
    if line_name and line_name != (user.full_name or "").strip():
        old_name = user.full_name
        user.full_name = line_name
        log_action(
            db,
            actor_id=user.id,
            action="profile_synced_from_line",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"field": "full_name", "old": old_name, "new": line_name},
        )
    db.commit()

    # ===== Hybrid 4-Layer Risk Scoring (Hub-direct) =====
    # Admin / teacher / staff = high-value target — ตรวจเข้มกว่า user ปกติ
    # ใช้ engine เดียวกับ subsystem OAuth flow → session ทุกแบบมี
    # risk_score / risk_breakdown / risk_reasons ครบใน UI
    user_agent = request.headers.get("user-agent")
    geo_country, geo_city = lookup_geo(client_ip)

    # 1) สกัด features จาก session + history (12 features)
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
        user_agent=user_agent,
    )
    risk_score = risk["score"]
    actual_decision = risk["decision"]
    risk_reasons = risk["reasons"]
    risk_breakdown = risk["breakdown"]
    anomaly_score = risk_breakdown.get("iforest_raw", 0.0)

    # 2.5) Alert admin — Hub-direct login = subsystem_name=None
    maybe_alert_ml_risk(
        user_email=user.email,
        user_id=str(user.id),
        risk_score=risk_score,
        decision=actual_decision,
        risk_breakdown=risk_breakdown,
        risk_reasons=risk_reasons,
        ip=client_ip,
        geo_country=geo_country,
        subsystem_name=None,
    )

    # 3) บันทึก login_session (subsystem_id=None = Hub-direct)
    login_session = LoginSession(
        user_id=user.id,
        subsystem_id=None,
        ip=client_ip,
        user_agent=user_agent,
        geo_country=geo_country,
        geo_city=geo_city,
        os_name=parse_os_name(user_agent),
        browser=parse_browser(user_agent),
        device_type=parse_device_type(user_agent),
        anomaly_score=anomaly_score,
        risk_score=risk_score,
        risk_breakdown=risk_breakdown,
        risk_reasons=risk_reasons,
        decision=actual_decision,
        is_attack_ip=is_blacklisted(db, client_ip),
        login_method="line",
    )
    db.add(login_session)
    db.flush()  # ต้องการ login_session.id สำหรับ MFA challenge

    # ─── Risk-Triggered Decision (Hub direct, Week 9-10) ─────────────────
    # >= 0.85 hard threshold      → BLOCK 403
    # 0.50 ≤ score < 0.85         → MFA flow (Passkey re-auth / grace / force-enroll)
    # Shadow mode = log only (would_* ไม่ enforce). MFA/block เด้งเฉพาะ enforce mode.
    enforcing = not settings.ml_shadow_mode
    is_hard_block = enforcing and risk_score >= settings.risk_block_hard_threshold
    # รวม risk-based MFA + Always-2FA (user pref / admin) เป็น gate เดียว (mfa_policy)
    # — always-on ทำงานแม้ shadow mode; ยืนยันครั้งเดียว ไม่ซ้อนกับ risk
    is_mfa_required = mfa_policy.is_second_factor_required(
        user,
        actual_decision=actual_decision,
        enforcing=enforcing,
        is_hard_block=is_hard_block,
    )

    if is_hard_block:
        log_action(
            db,
            actor_id=user.id,
            action="hub_login_blocked_by_ml",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={
                "score": anomaly_score,
                "risk_score": risk_score,
                "reasons": risk_reasons,
                "features": features,
                "hard_block_threshold": settings.risk_block_hard_threshold,
            },
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": "ml_blocked",
                "ip": client_ip,
                "anomaly_score": anomaly_score,
                "risk_score": risk_score,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=(
                f"การ login ถูกบล็อกโดยระบบตรวจสอบความปลอดภัย "
                f"(risk_score={risk_score:.3f}) — ติดต่อ admin หากเป็นเรื่องผิดพลาด"
            ),
        )

    if is_mfa_required:
        # มี factor ที่สอง (passkey หรือ TOTP) → risk-stepup (รับได้ทั้งคู่);
        # ไม่มีเลย → grace / force-enroll passkey (ต้องตั้งอย่างน้อย 1)
        has_passkey = mfa_policy.has_second_factor(user, db)
        if has_passkey:
            challenge_id = risk_challenge.mint(
                user_id=str(user.id),
                hub_state="",
                authreq=None,
                risk_score=risk_score,
                risk_breakdown=risk_breakdown,
                risk_reasons=risk_reasons,
                provider="hub_direct",
                kind="reauth",
                flow="hub_direct",
            )
            log_action(
                db,
                actor_id=user.id,
                action="risk_mfa_required",
                target_type="user",
                target_id=user.id,
                ip=client_ip,
                metadata={
                    "kind": "reauth",
                    "challenge_id": challenge_id,
                    "risk_score": risk_score,
                },
            )
            db.commit()
            return RedirectResponse(
                f"/auth/passkey/risk-stepup?challenge={challenge_id}",
                status_code=302,
            )

        if webauthn_service.in_grace_period(user, db):
            adoption = webauthn_service.adoption_status(user, db)
            log_action(
                db,
                actor_id=user.id,
                action="risk_grace_period_allowed",
                target_type="user",
                target_id=user.id,
                ip=client_ip,
                metadata={
                    "risk_score": risk_score,
                    "grace_days_remaining": adoption.get("grace_days_remaining"),
                    "days_since_signup": adoption.get("days_since_signup"),
                },
            )
            # fall through → ออก JWT ปกติ
        else:
            challenge_id = risk_challenge.mint(
                user_id=str(user.id),
                hub_state="",
                authreq=None,
                risk_score=risk_score,
                risk_breakdown=risk_breakdown,
                risk_reasons=risk_reasons,
                provider="hub_direct",
                kind="enroll",
                flow="hub_direct",
            )
            log_action(
                db,
                actor_id=user.id,
                action="risk_force_enroll_required",
                target_type="user",
                target_id=user.id,
                ip=client_ip,
                metadata={
                    "kind": "enroll",
                    "challenge_id": challenge_id,
                    "risk_score": risk_score,
                },
            )
            db.commit()
            return RedirectResponse(
                f"/auth/passkey/force-enroll?challenge={challenge_id}",
                status_code=302,
            )

    # log การ login สำเร็จ
    log_action(
        db,
        actor_id=user.id,
        action="hub_login_success",
        target_type="user",
        target_id=user.id,
        ip=client_ip,
        metadata={
            "email": email,
            "user_type": user.user_type,
            "anomaly_score": anomaly_score,
            "decision": actual_decision,
            "provider": "line",
        },
    )
    db.commit()

    # ออก JWT + เก็บ jti กลับไป LoginSession (สำหรับ force-revoke ภายหลัง)
    access_token, token_jti = create_access_token(user)
    login_session.jti = token_jti
    # ออก refresh token คู่กัน (short-lived access + rotating refresh — ดู B-refresh)
    refresh_token, refresh_id = refresh_token_service.issue(
        user_id=str(user.id), session_id=str(login_session.id)
    )
    login_session.refresh_id = refresh_id
    db.commit()

    await emit(
        EVT_LOGIN_SUCCESS,
        {
            "user_id": str(user.id),
            "email": user.email,
            "user_type": user.user_type,
            "ip": client_ip,
        },
    )

    # Redirect ไป Next.js frontend สำหรับทุก non-student
    # (student ถูก block ที่ check ก่อนหน้านี้แล้ว — ไม่ถึงตรงนี้)
    # - admin → middleware ส่งต่อไป /dashboard (Admin Console)
    # - teacher/staff → middleware ส่งต่อไป /developer/subsystems (Developer Portal)
    # ใช้ query ?api=1 ถ้าต้องการ JSON response สำหรับ API client / curl test
    wants_json = request.query_params.get("api") == "1"
    if settings.admin_frontend_url and not wants_json:
        code = mint_frontend_login_code(
            access_token=access_token, refresh_token=refresh_token
        )
        return RedirectResponse(
            f"{settings.admin_frontend_url}/auth/callback?code={code}",
            status_code=302,
        )

    return JSONResponse(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.jwt_access_token_expire_minutes * 60,
            "refresh_expires_in": settings.jwt_refresh_token_expire_days * 86400,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "user_type": user.user_type,
                "faculty": user.faculty,
            },
        }
    )


# ============ 3. ทดสอบ token ============


@router.get("/confirm-identity", response_class=HTMLResponse)
def confirm_identity(token: str = "", db: Session = Depends(get_db)):
    """One-time identity confirmation จาก link ใน email.

    Flow:
      - user คลิก link จาก email
      - verify token (HMAC-SHA256 ตรวจกับ Redis)
      - ลบ challenge → user login ใหม่ได้
      - แสดงหน้า success / error HTML
    """
    from app.services.identity_challenge import verify_and_clear

    if not token:
        return HTMLResponse(
            content=_confirm_html(
                ok=False,
                title="ลิงก์ไม่ถูกต้อง",
                msg="ไม่พบ token ใน URL — กรุณาเปิดลิงก์จาก email อีกครั้ง",
            ),
            status_code=400,
        )

    user_id = verify_and_clear(token)
    if not user_id:
        return HTMLResponse(
            content=_confirm_html(
                ok=False,
                title="ลิงก์หมดอายุหรือถูกใช้ไปแล้ว",
                msg=(
                    "ลิงก์นี้ใช้ได้ครั้งเดียวและหมดอายุภายใน 15 นาที — "
                    "ถ้ายังต้องการ login ต่อ ติดต่อ admin เพื่อขอลิงก์ใหม่"
                ),
            ),
            status_code=400,
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        log_action(
            db,
            actor_id=user.id,
            action="identity_challenge_confirmed",
            target_type="user",
            target_id=user.id,
            ip=None,
            metadata={"email": user.email},
        )
        db.commit()

    return HTMLResponse(
        content=_confirm_html(
            ok=True,
            title="✅ ยืนยันตัวตนสำเร็จ",
            msg=(
                "คุณสามารถ login เข้าระบบได้ตามปกติแล้ว — "
                "กลับไปหน้า login ของระบบย่อยที่คุณใช้งาน"
            ),
        )
    )


def _confirm_html(ok: bool, title: str, msg: str) -> str:
    """Render หน้า HTML สำหรับ identity confirm (success/error)."""
    accent = "#15803d" if ok else "#b91c1c"
    bg = "#dcfce7" if ok else "#fee2e2"
    icon = "✓" if ok else "✕"
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ font-family: 'Sarabun', system-ui, sans-serif; background: #f8fafc;
          min-height: 100vh; margin: 0; display: grid; place-items: center;
          padding: 40px 16px; color: #0f172a; }}
  .card {{ max-width: 520px; background: #fff; border-radius: 16px; overflow: hidden;
           box-shadow: 0 4px 12px rgba(15,23,42,0.08); }}
  .hero {{ background: {bg}; padding: 32px; text-align: center; }}
  .icon {{ width: 72px; height: 72px; border-radius: 50%; background: {accent};
           color: #fff; font-size: 36px; font-weight: 800; line-height: 72px;
           margin: 0 auto 14px; }}
  .title {{ font-size: 22px; font-weight: 800; color: {accent}; }}
  .body {{ padding: 24px 32px 28px; }}
  .msg {{ font-size: 14px; line-height: 1.6; color: #334155; }}
  .footer {{ font-size: 11px; color: #94a3b8; border-top: 1px solid #f1f5f9;
             padding: 14px 32px; }}
</style></head><body>
<div class="card">
  <div class="hero">
    <div class="icon">{icon}</div>
    <div class="title">{title}</div>
  </div>
  <div class="body"><p class="msg">{msg}</p></div>
  <div class="footer">Central Auth Hub · One-time identity verification</div>
</div>
</body></html>"""


class RefreshBody(BaseModel):
    refresh_token: str = Field(..., min_length=10, max_length=200)


async def _refresh_risk_gate(
    request: Request,
    user: User,
    rotate_result: dict,
    db: Session,
) -> JSONResponse | None:
    """รัน 4-Layer RBA ซ้ำตอน refresh — จับ session-hijack (refresh token ถูกขโมย
    ไปใช้จาก IP/ประเทศ/device อื่น) ที่ตอน login ปกติมองไม่เห็น เพราะ RBA รันแค่
    ครั้งแรกตอน login. อัปเดต risk snapshot ของ session เดิมให้เห็นใน admin ด้วย.

    Return:
      None                 → risk ปกติ (refresh จากที่เดิม) → caller ออก token ต่อ
      JSONResponse(stepup) → risk สูง + มี passkey → บังคับ Passkey re-auth ก่อน
      raise HTTPException   → hard block หรือ risk สูงแต่ไม่มี passkey → 401 login ใหม่

    Shadow mode (default) — รันเช็ค + อัปเดต risk snapshot ของ session แต่ไม่
    enforce (ออก token ต่อปกติ) — log `risk_refresh_would_stepup` ใน audit_logs
    ไว้เป็นหลักฐาน (audit_logs = append-only ทุกเหตุการณ์ความปลอดภัย, ต่างจาก
    LoginSession ที่เป็นแค่ current-state เขียนทับได้).
    """
    from datetime import datetime as _dt, timedelta as _td

    from app.services.jwt_service import revoke_jti as _revoke_jti

    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    geo_country, geo_city = lookup_geo(client_ip)

    features = extract_session_features(
        db,
        user_id=user.id,
        ip=client_ip,
        user_agent=user_agent,
        geo_country=geo_country,
    )
    risk = await evaluate_login_risk(
        features=features,
        user_id=str(user.id),
        ip=client_ip,
        geo_country=geo_country,
        db=db,
        shadow_mode=settings.ml_shadow_mode,
        user_agent=user_agent,
    )
    risk_score = risk["score"]
    decision = risk["decision"]
    reasons = risk["reasons"]
    breakdown = risk["breakdown"]

    # อัปเดต risk snapshot ล่าสุดของ session (admin เห็นใน Activity/detail)
    sess = (
        db.query(LoginSession)
        .filter(LoginSession.id == rotate_result["session_id"])
        .first()
    )
    if sess:
        sess.risk_score = risk_score
        sess.risk_breakdown = breakdown
        sess.risk_reasons = reasons

    enforcing = not settings.ml_shadow_mode

    # Shadow mode — log เข้า audit_logs ถ้า risk elevated (append-only, เก็บ
    # ประวัติไว้เทียบตอนพิจารณาเปิด enforce จริง) แต่ไม่ block (ออก token ต่อปกติ)
    if not enforcing:
        # would_challenge (ไม่ใช่ would_mfa) — aggregator emit "challenge" แล้วเติม
        # prefix would_ ใน shadow mode. เดิมเช็ค would_mfa ที่ไม่มีใครผลิตแล้ว → shadow
        # mode ไม่เคย log risk_refresh_would_stepup เลย (เงียบสนิท) — B58
        if decision in ("block", "challenge", "would_block", "would_challenge"):
            log_action(
                db,
                actor_id=user.id,
                action="risk_refresh_would_stepup",
                target_type="user",
                target_id=user.id,
                ip=client_ip,
                metadata={
                    "risk_score": risk_score,
                    "decision": decision,
                    "reasons": reasons,
                    "shadow": True,
                },
            )
            db.commit()
        return None

    is_hard_block = risk_score >= settings.risk_block_hard_threshold
    is_mfa = (not is_hard_block) and decision in ("block", "challenge")
    if not is_hard_block and not is_mfa:
        return None  # risk ปกติ

    has_passkey = webauthn_service.count_active(user.id, db) > 0

    # refresh token คู่ใหม่ที่ rotate() เพิ่งออก จะไม่ถูกส่งกลับใน 2 เคสนี้ → revoke ทิ้ง
    refresh_token_service.revoke(rotate_result["refresh_id"])

    if is_mfa and has_passkey:
        challenge_id = risk_challenge.mint(
            user_id=str(user.id),
            hub_state="",
            authreq=None,
            risk_score=risk_score,
            risk_breakdown=breakdown,
            risk_reasons=reasons,
            provider="refresh",
            kind="reauth",
            flow="hub_direct",
        )
        if sess:
            sess.decision = "challenge"
        log_action(
            db,
            actor_id=user.id,
            action="risk_refresh_stepup_required",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={
                "challenge_id": challenge_id,
                "risk_score": risk_score,
                "reasons": reasons,
            },
        )
        db.commit()
        return JSONResponse(
            status_code=200,
            content={
                "stepup_required": True,
                "challenge_id": challenge_id,
                "stepup_url": (
                    f"{settings.hub_base_url}/auth/passkey/risk-stepup"
                    f"?challenge={challenge_id}"
                ),
            },
        )

    # hard block หรือ (risk สูง + ไม่มี passkey) → ตัด session, บังคับ login ใหม่เต็ม
    # (login flow จัดการ grace period / force-enroll ให้เอง ที่ refresh ทำไม่ได้)
    if sess:
        sess.decision = "block" if is_hard_block else "challenge"
        sess.logout_at = _dt.utcnow()
        if sess.jti:
            exp_unix = int(
                (
                    sess.created_at
                    + _td(minutes=settings.jwt_access_token_expire_minutes)
                ).timestamp()
            )
            _revoke_jti(sess.jti, exp_unix)
    log_action(
        db,
        actor_id=user.id,
        action="risk_refresh_blocked",
        target_type="user",
        target_id=user.id,
        ip=client_ip,
        metadata={
            "risk_score": risk_score,
            "decision": decision,
            "reasons": reasons,
            "hard_block": is_hard_block,
            "has_passkey": has_passkey,
        },
    )
    db.commit()
    raise HTTPException(
        status_code=401,
        detail="ตรวจพบความเสี่ยงสูงระหว่างต่ออายุ session — กรุณา login ใหม่",
    )


@router.post("/refresh")
async def refresh_access_token(
    body: RefreshBody, request: Request, db: Session = Depends(get_db)
):
    """ต่ออายุ session ด้วย refresh token — ออก access+refresh token คู่ใหม่ (rotation).

    refresh token เดิมถูก consume ทันที (single-use, atomic ผ่าน
    refresh_token_service.rotate) — ใช้ซ้ำ (replay) ไม่ได้อีก แม้ request จะ
    concurrent กัน. jti/refresh_id ใหม่เขียนกลับ LoginSession เดิม เพื่อให้
    force-revoke (เช่น logout จาก tab อื่น) ยังตามทัน session ล่าสุดเสมอ.

    Re-run RBA (session-hijack detection) — ดู `_refresh_risk_gate`:
      risk สูง + passkey → 200 {stepup_required} · hard block/no-passkey → 401.
    """
    result = refresh_token_service.rotate(body.refresh_token)
    if result is None:
        raise HTTPException(status_code=401, detail="refresh token ไม่ถูกต้องหรือหมดอายุ")

    user = (
        db.query(User)
        .filter(User.id == result["user_id"], User.status == "active")
        .first()
    )
    if not user:
        # user ถูกลบ/ระงับไปแล้ว — refresh token ถูก consume แล้วด้วย (ปลอดภัย)
        raise HTTPException(status_code=401, detail="refresh token ไม่ถูกต้องหรือหมดอายุ")

    # 4-Layer RBA ซ้ำ — stepup/block ถ้า risk สูง (raise หรือ return JSONResponse)
    gate = await _refresh_risk_gate(request, user, result, db)
    if gate is not None:
        return gate

    access_token, token_jti = create_access_token(user)

    sess = (
        db.query(LoginSession).filter(LoginSession.id == result["session_id"]).first()
    )
    # session ถูก force-logout ไปแล้ว → ห้ามชุบชีวิตด้วย refresh (audit run-2 #1).
    # refresh ตัวใหม่ที่ rotate เพิ่งออก ต้อง revoke ทิ้ง (ไม่งั้น orphan ค้างใน Redis)
    if sess is not None and sess.logout_at is not None:
        refresh_token_service.revoke(result["refresh_id"])
        raise HTTPException(status_code=401, detail="session terminated")
    if sess:
        from datetime import datetime as _dt

        sess.jti = token_jti
        sess.refresh_id = result["refresh_id"]
        # refresh = สัญญาณ presence จริง (user ยัง active) → bump online heartbeat
        sess.last_seen_at = _dt.utcnow()
        db.commit()

    return {
        "access_token": access_token,
        "refresh_token": result["raw_token"],
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "refresh_expires_in": settings.jwt_refresh_token_expire_days * 86400,
    }


class LogoutBody(BaseModel):
    # optional — frontend ส่ง refresh token มาด้วยเพื่อ revoke พร้อมกัน (กัน
    # attacker ที่ขโมย refresh cookie ไปมิ้นท์ access token ใหม่ได้หลัง "logout")
    refresh_token: str | None = Field(None, max_length=200)


@router.post("/logout")
def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    body: LogoutBody | None = None,
    db: Session = Depends(get_db),
):
    """User logout ตัวเอง — revoke JWT + refresh token ปัจจุบัน (Token Revocation).

    decode token → revoke jti (Redis blacklist จนถึง exp) + mark LoginSession.logout_at
    → token ใช้ต่อไม่ได้ทันที (verify_token เช็ค is_revoked). idempotent.

    ถ้าส่ง refresh_token มาด้วย → revoke ทันที (ไม่ต้องรอ 30 วัน TTL หมดเอง)
    — ไม่งั้น "logout" จะเหลือแค่ลบ cookie ฝั่ง client, server ยังมิ้นท์ access
    token ใหม่ให้ผ่าน /auth/refresh ได้อยู่ ถ้า refresh token หลุดไปก่อนหน้า
    """
    from datetime import datetime as _dt

    from app.services import refresh_token_service
    from app.services.jwt_service import revoke_jti, verify_token

    if body and body.refresh_token:
        refresh_token_service.revoke_raw(body.refresh_token)

    try:
        payload = verify_token(credentials.credentials)
    except Exception:
        # token เสีย/หมดอายุ/revoke แล้ว → ถือว่า logout สำเร็จ (idempotent)
        return {"status": "ok", "token_revoked": False}

    jti = payload.get("jti")
    revoked = revoke_jti(jti, int(payload["exp"])) if jti else False

    # mark active hub-direct session ของ user นี้ + revoke refresh_id ที่ผูกไว้
    # (เผื่อ client ไม่ได้ส่ง refresh_token มาใน body แต่ session รู้จักมันอยู่)
    user_id = payload.get("sub")
    if user_id:
        sess = (
            db.query(LoginSession)
            .filter(
                LoginSession.user_id == user_id,
                LoginSession.subsystem_id.is_(None),
                LoginSession.logout_at.is_(None),
            )
            .order_by(LoginSession.created_at.desc())
            .first()
        )
        if sess:
            sess.logout_at = _dt.utcnow()
            if sess.refresh_id:
                refresh_token_service.revoke(sess.refresh_id)
        log_action(
            db,
            actor_id=user_id,
            action="hub_logout",
            target_type="user",
            target_id=user_id,
            ip=get_client_ip(request),
            metadata={"token_revoked": revoked},
        )
        db.commit()
    return {"status": "ok", "token_revoked": revoked}


@router.post("/heartbeat")
def heartbeat(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Presence ping — bump last_seen_at ของ session ปัจจุบัน (online detection).

    frontend console เรียกเป็นระยะ (~60 วิ) ระหว่างเปิดหน้าอยู่ → Hub รู้ว่า user
    ยัง active จริง (ไม่ใช่แค่ล็อกอินค้างไว้). throttle: เขียนเฉพาะเมื่อ last_seen
    เก่ากว่า 20 วิ (กัน write ถี่เกิน). idempotent — token เสีย/หมดอายุ = 200 ok:false
    """
    from datetime import datetime as _dt, timedelta as _td
    from app.services.jwt_service import verify_token

    try:
        payload = verify_token(credentials.credentials)
    except Exception:
        return {"ok": False}

    jti = payload.get("jti")
    if not jti:
        return {"ok": False}

    now = _dt.utcnow()
    # bump เฉพาะ session ที่ยังเปิด + last_seen เก่ากว่า 20 วิ (throttle write)
    updated = (
        db.query(LoginSession)
        .filter(
            LoginSession.jti == jti,
            LoginSession.logout_at.is_(None),
            or_(
                LoginSession.last_seen_at.is_(None),
                LoginSession.last_seen_at < now - _td(seconds=20),
            ),
        )
        .update({LoginSession.last_seen_at: now}, synchronize_session=False)
    )
    if updated:
        db.commit()
    return {"ok": True}


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    """คืนข้อมูลของผู้ใช้ที่ login อยู่ — ใช้ทดสอบว่า JWT ทำงาน.

    วิธีทดสอบใน Swagger UI:
      1. เรียก /auth/google/callback ก่อน -> copy access_token
      2. กดปุ่ม Authorize มุมขวาบน -> paste token
      3. เรียก /auth/me
    """
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "user_type": user.user_type,
        "faculty": user.faculty,
        "is_hub_admin": user.is_hub_admin,
    }


# หมายเหตุ: JWKS endpoint ย้ายไปที่ /.well-known/jwks.json ที่ root (main.py)
# เพื่อให้ตรงกับ OIDC discovery standard (RFC 8414)
