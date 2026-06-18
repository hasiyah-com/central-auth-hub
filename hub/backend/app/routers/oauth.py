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
from pydantic import BaseModel, EmailStr, Field
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
from app.services import webauthn_service
from app.services import passkey_recovery
from app.services import risk_challenge

router = APIRouter()

AUTH_REQUEST_TTL = 600  # OAuth request เก็บใน Redis 10 นาที
AUTH_CODE_TTL = 60  # authorization code อายุ 60 วินาที
ENROLL_TTL = 600  # passkey enrollment context (หลัง Google identify) 10 นาที


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

    # 4. แสดงหน้าเลือกวิธี login (A) — Google หรือ Passkey
    #    แทนการ redirect ตรงไป Google (เดิม) — user เลือกเองได้
    #    Google → GET /oauth/authorize/google?hub_state=... (ทำ Authlib redirect)
    #    Passkey → JS WebAuthn → POST /oauth/passkey/{start,finish}
    #    nonce → CSP อนุญาต inline style+script เฉพาะของหน้านี้ (กัน XSS)
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    return HTMLResponse(
        content=_login_chooser_html(
            hub_state=hub_state,
            subsystem_name=subsystem.name,
            nonce=nonce,
        )
    )


@router.get("/authorize/google")
async def authorize_google(
    request: Request,
    hub_state: str,
    db: Session = Depends(get_db),
):
    """ปุ่ม "Continue with Google" จากหน้า chooser → redirect ไป Google จริง.

    Authlib เก็บ state ใน session keyed-by hub_state (multi-tab safe).
    authreq ถูกสร้างไว้แล้วใน /oauth/authorize — ที่นี่แค่ validate ว่ายังอยู่.
    """
    if not redis_client.get(f"authreq:{hub_state}"):
        raise HTTPException(
            status_code=400, detail="OAuth request หมดอายุ — เริ่ม login ใหม่"
        )
    return await oauth.google.authorize_redirect(
        request, settings.oauth_callback_uri, state=hub_state
    )


@router.get("/passkey/recover")
async def passkey_recover_page(request: Request):
    """หน้ากู้บัญชี Passkey (เสิร์ฟจาก Hub — subsystem user ใช้ได้เอง).

    backup code / email OTP → fetch /auth/passkey/recover/* same-origin.
    ไม่พึ่ง admin frontend (subsystem user อยู่บน Hub domain ตลอด).
    """
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    return HTMLResponse(content=_passkey_recover_html(nonce=nonce))


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

    # ===== Passkey enrollment interstitial (subsystem users รวมนักศึกษา) =====
    # ถ้า user ยังไม่มี passkey → เสนอตั้งค่าก่อน redirect กลับ subsystem
    # (นักศึกษาเข้า Hub console ไม่ได้ — นี่คือทางเดียวที่จะลง passkey)
    # pattern เดียวกับ Google/GitHub: "set up a passkey for faster sign-in"
    if webauthn_service.count_active(user.id, db) == 0:
        # persist google_sub binding + profile sync ที่ทำไว้ก่อนหน้า
        db.commit()
        redis_client.setex(
            f"enroll:{state}",
            ENROLL_TTL,
            json.dumps({"user_id": str(user.id), "email": user.email}),
        )
        subsystem = (
            db.query(Subsystem).filter(Subsystem.id == authreq["subsystem_id"]).first()
        )
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        return HTMLResponse(
            content=_passkey_enroll_html(
                hub_state=state,
                subsystem_name=subsystem.name if subsystem else "ระบบ",
                user_email=user.email,
                nonce=nonce,
            )
        )

    # มี passkey แล้ว → login ตามปกติ (shared finalizer: access_list → RBA →
    # authorization code → redirect). Passkey path เรียก helper ตัวเดียวกัน
    callback_url = await _finalize_subsystem_login(
        user=user,
        authreq=authreq,
        hub_state=state,
        request=request,
        db=db,
        provider="google",
    )
    return RedirectResponse(url=callback_url)


# ============ Shared finalizer (Google + Passkey ใช้ร่วมกัน) ============


async def _finalize_subsystem_login(
    *,
    user: User,
    authreq: dict,
    hub_state: str,
    request: Request,
    db: Session,
    provider: str,
    counter_regression: bool = False,
) -> str:
    """Logic หลังยืนยันตัวตนแล้ว (provider-agnostic) → คืน callback_url.

    ทำ: access_list check → identity challenge → 4-Layer RBA → login session →
        block decision → authorization code → audit → cleanup.

    เรียกจาก:
      - oauth_callback (provider="google")
      - oauth_passkey_finish (provider="passkey")

    Raises HTTPException (403) ถ้า: ไม่อยู่ whitelist / identity challenge / risk block.
    Returns: callback URL string (subsystem redirect_uri + code + state).
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

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
                "email": user.email,
                "user_id": str(user.id),
                "client_id": authreq["client_id"],
                "provider": provider,
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
            metadata={
                "email": user.email,
                "client_id": authreq["client_id"],
                "provider": provider,
            },
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

    # ===== Hybrid RBA 4-Layer Risk Scoring =====
    # อ้างอิง: Freeman 2016, Wiefling 2022, F-RBA 2024, NIST SP 800-63B-4
    geo_country = lookup_country(client_ip)
    features = extract_session_features(
        db,
        user_id=user.id,
        ip=client_ip,
        user_agent=user_agent,
        geo_country=geo_country,
        subsystem_id=authreq["subsystem_id"],
    )
    risk = await evaluate_login_risk(
        features=features,
        user_id=str(user.id),
        ip=client_ip,
        geo_country=geo_country,
        db=db,
        shadow_mode=settings.ml_shadow_mode,
        subsystem_id=authreq["subsystem_id"],  # cross-subsystem risk propagation
    )
    risk_score = risk["score"]
    actual_decision = risk["decision"]
    risk_reasons = risk["reasons"]
    risk_breakdown = risk["breakdown"]
    anomaly_score = risk_breakdown.get("iforest_raw", 0.0)
    iforest_explanation = risk.get("iforest_explanation", [])

    # Passkey sign-counter regression (Improvement #10) — boost risk, ไม่ block
    if counter_regression:
        risk_score = min(
            1.0, risk_score + settings.stepup_counter_regression_risk_boost
        )
        risk_reasons = [*risk_reasons, "passkey_counter_regression (+0.20)"]

    if iforest_explanation:
        risk_breakdown = {**risk_breakdown, "iforest_explanation": iforest_explanation}

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

    # ─── Risk-Triggered Decision (Week 9-10) ─────────────────────────────
    # Hard block ที่ finalizer (single source of truth) — ไม่พึ่ง aggregator
    # >= risk_block_hard_threshold (0.85)  → BLOCK 403
    # >= challenge (0.50) แต่ < 0.85       → MFA flow (re-auth / grace / force-enroll)
    # < challenge                          → PASS ปกติ
    # Shadow mode = log only (would_* ไม่ enforce). MFA/block เด้งเฉพาะ enforce mode.
    enforcing = not settings.ml_shadow_mode
    is_hard_block = enforcing and risk_score >= settings.risk_block_hard_threshold
    is_mfa_required = (
        enforcing and not is_hard_block and actual_decision in ("block", "challenge")
    )

    if is_hard_block:
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
                "iforest_explanation": iforest_explanation,
                "provider": provider,
                "hard_block_threshold": settings.risk_block_hard_threshold,
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

    # ─── Risk-Triggered MFA flow (0.50 ≤ score < 0.85) ───────────────────
    grace_banner_remaining_days: int | None = None  # set ถ้า grace branch
    if is_mfa_required:
        has_passkey = webauthn_service.count_active(user.id, db) > 0

        if has_passkey:
            # Branch A: Passkey Re-Auth
            challenge_id = risk_challenge.mint(
                user_id=str(user.id),
                hub_state=hub_state,
                authreq=authreq,
                risk_score=risk_score,
                risk_breakdown=risk_breakdown,
                risk_reasons=risk_reasons,
                provider=provider,
                kind="reauth",
                flow="subsystem",
            )
            log_action(
                db,
                actor_id=user.id,
                action="risk_mfa_required",
                target_type="subsystem",
                target_id=authreq["subsystem_id"],
                ip=client_ip,
                metadata={
                    "kind": "reauth",
                    "challenge_id": challenge_id,
                    "risk_score": risk_score,
                    "reasons": risk_reasons,
                    "provider": provider,
                },
            )
            db.commit()
            return f"/auth/passkey/risk-stepup?challenge={challenge_id}"

        # ไม่มี passkey — ตรวจ grace period
        if webauthn_service.in_grace_period(user, db):
            # Branch C: Grace — Allow Once + Banner
            adoption = webauthn_service.adoption_status(user, db)
            grace_banner_remaining_days = adoption.get("grace_days_remaining")
            log_action(
                db,
                actor_id=user.id,
                action="risk_grace_period_allowed",
                target_type="subsystem",
                target_id=authreq["subsystem_id"],
                ip=client_ip,
                metadata={
                    "risk_score": risk_score,
                    "reasons": risk_reasons,
                    "grace_days_remaining": grace_banner_remaining_days,
                    "days_since_signup": adoption.get("days_since_signup"),
                    "provider": provider,
                },
            )
            # fall through → สร้าง authorization code (พร้อม banner flag)
        else:
            # Branch B: Force Enrollment
            challenge_id = risk_challenge.mint(
                user_id=str(user.id),
                hub_state=hub_state,
                authreq=authreq,
                risk_score=risk_score,
                risk_breakdown=risk_breakdown,
                risk_reasons=risk_reasons,
                provider=provider,
                kind="enroll",
                flow="subsystem",
            )
            log_action(
                db,
                actor_id=user.id,
                action="risk_force_enroll_required",
                target_type="subsystem",
                target_id=authreq["subsystem_id"],
                ip=client_ip,
                metadata={
                    "kind": "enroll",
                    "challenge_id": challenge_id,
                    "risk_score": risk_score,
                    "reasons": risk_reasons,
                    "provider": provider,
                },
            )
            db.commit()
            return f"/auth/passkey/force-enroll?challenge={challenge_id}"

    # สร้าง authorization code (อายุ 60 วินาที, ใช้ครั้งเดียว)
    auth_code = secrets.token_urlsafe(32)
    authcode_payload = {
        "user_id": str(user.id),
        "client_id": authreq["client_id"],
        "subsystem_id": authreq["subsystem_id"],
        "code_challenge": authreq["code_challenge"],
        "scope": authreq["scope"],
        "role_in_sub": access.role_in_sub,
    }
    if grace_banner_remaining_days is not None:
        # Risk-triggered grace period flag — subsystem แสดง banner
        # "ลงทะเบียน Passkey ภายใน N วัน"
        authcode_payload["passkey_grace_remaining_days"] = grace_banner_remaining_days
    redis_client.setex(
        f"authcode:{auth_code}",
        AUTH_CODE_TTL,
        json.dumps(authcode_payload),
    )

    log_action(
        db,
        actor_id=user.id,
        action="oauth_authorized",
        target_type="subsystem",
        target_id=authreq["subsystem_id"],
        ip=client_ip,
        metadata={
            "provider": provider,
            "risk_score": risk_score,
            "anomaly_score": anomaly_score,
            "decision": actual_decision,
            "breakdown": risk_breakdown,
            "reasons": risk_reasons,
            **(
                {"iforest_explanation": iforest_explanation}
                if risk_score >= 0.3 and iforest_explanation
                else {}
            ),
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

    # cleanup + สร้าง redirect URL กลับ subsystem พร้อม code + state
    redis_client.delete(f"authreq:{hub_state}")

    sep = "&" if "?" in authreq["redirect_uri"] else "?"
    return f"{authreq['redirect_uri']}{sep}code={auth_code}&state={authreq['state']}"


# ============ 2b. /oauth/passkey/* — Passkey path สำหรับ subsystem (B) ============
# ทางเลือกแทน Google: user ยืนยันด้วย Passkey แล้วได้ authorization code
# เหมือน Google callback ทุกประการ (ผ่าน _finalize_subsystem_login ตัวเดียวกัน)
#
# Flow:
#   1. หน้า chooser (A) → user กด Passkey → JS POST /oauth/passkey/start {hub_state, email}
#   2. รับ assertion options → navigator.credentials.get() → POST /oauth/passkey/finish
#   3. Hub verify → _finalize_subsystem_login → คืน {redirect_url}
#   4. browser navigate ไป redirect_url (กลับ subsystem พร้อม code+state)


class PasskeyOAuthStartRequest(BaseModel):
    hub_state: str = Field(..., min_length=8, max_length=128)
    email: EmailStr = Field(..., max_length=255)


class PasskeyOAuthFinishRequest(BaseModel):
    hub_state: str = Field(..., min_length=8, max_length=128)
    email: EmailStr = Field(..., max_length=255)
    credential: dict = Field(..., description="WebAuthn assertion")


def _load_authreq(hub_state: str) -> dict:
    """ดึง OAuth request จาก Redis (key = hub_state) — 400 ถ้าหมดอายุ."""
    raw = redis_client.get(f"authreq:{hub_state}")
    if not raw:
        raise HTTPException(
            status_code=400, detail="OAuth request หมดอายุ — เริ่ม login ใหม่"
        )
    return json.loads(raw)


@router.post("/passkey/start")
@limiter.limit(settings.rate_limit_token)
async def oauth_passkey_start(
    request: Request,
    body: PasskeyOAuthStartRequest,
    db: Session = Depends(get_db),
):
    """สร้าง WebAuthn assertion options สำหรับ subsystem login ด้วย Passkey.

    ต้องมี active OAuth request (authreq:{hub_state}) ก่อน — ป้องกันการเรียก
    endpoint นี้นอก flow. คืน options แบบ opaque แม้ email ไม่มี Passkey
    (anti-enumeration — เหมือน /auth/passkey/login/start).
    """
    _load_authreq(body.hub_state)  # validate flow context (400 ถ้าไม่มี)
    return webauthn_service.auth_begin(body.email.strip().lower(), db)


@router.post("/passkey/finish")
@limiter.limit(settings.rate_limit_token)
async def oauth_passkey_finish(
    request: Request,
    body: PasskeyOAuthFinishRequest,
    db: Session = Depends(get_db),
):
    """Verify Passkey assertion → ออก authorization code สำหรับ subsystem.

    ใช้ _finalize_subsystem_login ตัวเดียวกับ Google callback → access_list,
    identity challenge, RBA, block, audit เหมือนกันเป๊ะ.

    คืน {"redirect_url": "..."} — frontend navigate ไป URL นั้น (กลับ subsystem).
    """
    authreq = _load_authreq(body.hub_state)
    email = body.email.strip().lower()
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    # 1. Verify Passkey assertion (opaque error — ไม่ enumerate)
    try:
        result = webauthn_service.auth_complete(
            email, body.credential, db, ip=ip, user_agent=user_agent
        )
    except HTTPException as e:
        code = e.detail.get("code") if isinstance(e.detail, dict) else None
        log_action(
            db,
            actor_id=None,
            action="oauth_passkey_login_failed",
            target_type="subsystem",
            target_id=authreq["subsystem_id"],
            ip=ip,
            metadata={
                "email": email[:120],
                "code": code,
                "client_id": authreq["client_id"],
            },
        )
        db.commit()
        raise

    user = result.user
    if user.status != "active":
        log_action(
            db,
            actor_id=user.id,
            action="oauth_login_failed_inactive",
            target_type="user",
            target_id=user.id,
            ip=ip,
            metadata={
                "email": email,
                "status": user.status,
                "subsystem_id": authreq["subsystem_id"],
                "provider": "passkey",
            },
        )
        db.commit()
        raise HTTPException(status_code=403, detail=f"บัญชีถูก {user.status}")

    # 2. มอบให้ shared finalizer (เหมือน Google) → คืน callback URL
    callback_url = await _finalize_subsystem_login(
        user=user,
        authreq=authreq,
        hub_state=body.hub_state,
        request=request,
        db=db,
        provider="passkey",
        counter_regression=result.counter_regression,
    )
    return {"redirect_url": callback_url}


# ============ 2c. /oauth/passkey/enroll/* + /oauth/continue (E — interstitial) ===
# ลง passkey หลัง Google identify (ไม่ต้อง Hub JWT — ใช้ enroll context)
# ใช้โดย subsystem users รวมนักศึกษาที่เข้า Hub console ไม่ได้


class EnrollStartRequest(BaseModel):
    hub_state: str = Field(..., min_length=8, max_length=128)


class EnrollFinishRequest(BaseModel):
    hub_state: str = Field(..., min_length=8, max_length=128)
    device_name: str = Field(..., min_length=1, max_length=100)
    credential: dict = Field(..., description="WebAuthn attestation")


def _load_enroll_user(hub_state: str, db: Session) -> User:
    """ดึง user จาก enroll context (สร้างหลัง Google identify) — 400 ถ้าหมดอายุ."""
    raw = redis_client.get(f"enroll:{hub_state}")
    if not raw:
        raise HTTPException(status_code=400, detail="session หมดอายุ — เริ่ม login ใหม่")
    enroll = json.loads(raw)
    user = db.query(User).filter(User.id == enroll["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้")
    return user


@router.post("/passkey/enroll/start")
@limiter.limit(settings.rate_limit_token)
async def oauth_passkey_enroll_start(
    request: Request,
    body: EnrollStartRequest,
    db: Session = Depends(get_db),
):
    """สร้าง WebAuthn registration options — ใช้ identity จาก enroll context.

    ปลอดภัย: user_id มาจาก enroll:{hub_state} ที่ server สร้างหลัง Google
    verify identity แล้ว (client ปลอม user ไม่ได้).
    """
    user = _load_enroll_user(body.hub_state, db)
    return webauthn_service.register_begin(user, db)


@router.post("/passkey/enroll/finish")
@limiter.limit(settings.rate_limit_token)
async def oauth_passkey_enroll_finish(
    request: Request,
    body: EnrollFinishRequest,
    db: Session = Depends(get_db),
):
    """Verify attestation + save passkey สำหรับ user ใน enroll context.

    Passkey แรก → generate 10 backup codes (return ครั้งเดียวให้เก็บ).
    คืน {passkey_id, backup_codes?}.
    """
    user = _load_enroll_user(body.hub_state, db)
    ip = get_client_ip(request)

    try:
        row = webauthn_service.register_complete(
            user, body.credential, body.device_name, db
        )
    except HTTPException as e:
        code = e.detail.get("code") if isinstance(e.detail, dict) else None
        log_action(
            db,
            actor_id=user.id,
            action="passkey_register_failed",
            target_type="passkey",
            ip=ip,
            metadata={"phase": "enroll_finish", "code": code},
        )
        db.commit()
        raise

    log_action(
        db,
        actor_id=user.id,
        action="passkey_registered",
        target_type="passkey",
        target_id=row.id,
        ip=ip,
        metadata={
            "device_name": row.device_name,
            "device_type": row.device_type,
            "via": "subsystem_enroll",  # interstitial หลัง Google login
        },
    )

    resp: dict = {"passkey_id": str(row.id), "device_name": row.device_name}
    # Auto-heal: ออก backup codes เมื่อ user ไม่มี usable codes (remaining==0)
    # — ไม่เคยมี → gen 1; ใช้หมดแล้ว → rotate ชุดใหม่ (ปิดช่องติดล็อกหลัง recovery)
    codes = passkey_recovery.ensure_backup_codes(user.id, db)
    if codes:
        log_action(
            db,
            actor_id=user.id,
            action="passkey_backup_codes_generated",
            target_type="user",
            target_id=user.id,
            ip=ip,
            metadata={"count": len(codes), "trigger": "subsystem_enroll"},
        )
        resp["backup_codes"] = codes
    db.commit()
    return resp


@router.get("/continue")
async def oauth_continue(
    request: Request,
    hub_state: str,
    db: Session = Depends(get_db),
):
    """หลัง interstitial (ตั้ง passkey หรือ ข้าม) → ออก authorization code + redirect.

    ใช้ identity จาก enroll context → _finalize_subsystem_login (access_list, RBA,
    block, authcode เหมือน flow ปกติ).
    """
    raw = redis_client.get(f"authreq:{hub_state}")
    if not raw:
        raise HTTPException(
            status_code=400, detail="OAuth request หมดอายุ — เริ่ม login ใหม่"
        )
    authreq = json.loads(raw)
    user = _load_enroll_user(hub_state, db)

    callback_url = await _finalize_subsystem_login(
        user=user,
        authreq=authreq,
        hub_state=hub_state,
        request=request,
        db=db,
        provider="google",
    )
    redis_client.delete(f"enroll:{hub_state}")
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

    response = {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "scope": code_data["scope"],
        "role_in_subsystem": code_data["role_in_sub"],
    }
    # Risk-triggered grace period banner — subsystem แสดง banner ให้ user
    if "passkey_grace_remaining_days" in code_data:
        response["passkey_grace_remaining_days"] = code_data[
            "passkey_grace_remaining_days"
        ]
    return response


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


# ============ Passkey enrollment interstitial (E) ============


def _passkey_enroll_html(
    hub_state: str, subsystem_name: str, user_email: str, nonce: str
) -> str:
    """หน้าเสนอตั้งค่า Passkey หลัง Google login (ก่อน redirect กลับ subsystem).

    รองรับทุก user รวมนักศึกษา (ไม่ต้องเข้า Hub console). มีปุ่ม "ข้ามไปก่อน"
    เสมอ (opt-in — Decision: ไม่บังคับ). Passkey แรก → แสดง backup codes (must save).
    """
    safe_name = (
        subsystem_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    safe_email = (
        user_email.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>ตั้งค่า Passkey · {safe_name}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Kanit:wght@500;600;700&family=IBM+Plex+Sans+Thai:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style nonce="{nonce}">
  :root {{ --bg-0:#070b14; --ink:#e8eef7; --muted:#8a99b5; --mint:#34e8c4;
           --mint-2:#13b89a; --line:rgba(148,178,224,.14); --danger:#ff6b81; --amber:#f5b97a; }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; height:100%; }}
  body {{ font-family:'IBM Plex Sans Thai',system-ui,sans-serif; background:var(--bg-0);
          color:var(--ink); min-height:100vh; display:grid; place-items:center;
          padding:32px 16px; overflow:hidden; position:relative; }}
  body::before {{ content:''; position:fixed; inset:-20%; z-index:0;
    background:radial-gradient(40% 50% at 18% 22%, rgba(52,232,196,.16), transparent 70%),
      radial-gradient(45% 55% at 85% 18%, rgba(82,120,255,.16), transparent 70%),
      radial-gradient(60% 60% at 50% 110%, rgba(120,80,220,.12), transparent 70%);
    filter:blur(20px); animation:drift 18s ease-in-out infinite alternate; }}
  @keyframes drift {{ from{{transform:translateY(0) scale(1)}} to{{transform:translateY(-3%) scale(1.06)}} }}
  .card {{ position:relative; z-index:1; width:100%; max-width:440px;
    background:linear-gradient(180deg, rgba(20,28,48,.86), rgba(11,17,32,.92));
    border:1px solid var(--line); border-radius:22px; backdrop-filter:blur(14px);
    box-shadow:0 30px 80px -20px rgba(0,0,0,.7), 0 0 60px -30px rgba(52,232,196,.5);
    overflow:hidden; animation:rise .7s cubic-bezier(.2,.8,.2,1) both; }}
  @keyframes rise {{ from{{opacity:0; transform:translateY(16px)}} to{{opacity:1; transform:none}} }}
  .top {{ padding:30px 32px 4px; text-align:center; }}
  .key-emblem {{ width:62px; height:62px; margin:0 auto 14px; border-radius:18px;
    background:linear-gradient(135deg, rgba(52,232,196,.2), rgba(52,232,196,.05));
    border:1px solid rgba(52,232,196,.35); display:grid; place-items:center; color:var(--mint); }}
  h1 {{ font-family:'Kanit',sans-serif; font-weight:600; font-size:24px; margin:0 0 6px; }}
  .sub {{ color:var(--muted); font-size:13.5px; margin:0; line-height:1.55; }}
  .who {{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--mint);
          margin-top:10px; word-break:break-all; }}
  .body {{ padding:20px 32px 26px; }}
  .benefits {{ list-style:none; padding:0; margin:0 0 18px; display:grid; gap:9px; }}
  .benefits li {{ display:flex; gap:9px; font-size:13px; color:#c4d0e4; align-items:flex-start; }}
  .benefits i {{ color:var(--mint); flex:none; margin-top:1px; }}
  label.fld {{ font-size:11px; color:var(--muted); font-family:'IBM Plex Mono',monospace;
               display:block; margin-bottom:6px; }}
  input {{ width:100%; padding:13px 14px; border-radius:11px; border:1px solid var(--line);
           background:rgba(7,11,20,.7); color:var(--ink); font-size:14.5px;
           font-family:'IBM Plex Sans Thai',sans-serif; margin-bottom:14px; }}
  input:focus {{ outline:none; border-color:var(--mint-2); box-shadow:0 0 0 3px rgba(52,232,196,.16); }}
  .btn {{ display:flex; align-items:center; justify-content:center; gap:10px; width:100%;
    padding:14px 16px; border-radius:13px; font-family:'Kanit',sans-serif; font-weight:500;
    font-size:15.5px; border:1px solid transparent; cursor:pointer; text-decoration:none;
    transition:transform .15s, box-shadow .25s, background .2s; }}
  .btn-pk {{ color:#04221c; background:linear-gradient(100deg,var(--mint),#5ff0d6);
             box-shadow:0 10px 30px -10px rgba(52,232,196,.6); }}
  .btn-pk:hover {{ transform:translateY(-2px); }}
  .btn-pk[disabled] {{ opacity:.5; cursor:not-allowed; transform:none; }}
  .btn-skip {{ color:var(--muted); background:transparent; border-color:transparent;
               margin-top:8px; font-size:13.5px; }}
  .btn-skip:hover {{ color:var(--ink); }}
  .err {{ display:none; gap:8px; font-size:12.5px; color:var(--danger); margin-bottom:12px;
    background:rgba(255,107,129,.08); border:1px solid rgba(255,107,129,.28);
    padding:10px 12px; border-radius:10px; line-height:1.45; }}
  .err.show {{ display:flex; }}
  .unsupported {{ display:none; font-size:12.5px; color:var(--amber); margin-bottom:12px;
    background:rgba(245,185,122,.08); border:1px solid rgba(245,185,122,.28);
    padding:10px 12px; border-radius:10px; }}
  .unsupported.show {{ display:block; }}
  .spinner {{ width:16px; height:16px; border:2px solid rgba(4,34,28,.35);
    border-top-color:#04221c; border-radius:50%; animation:spin .7s linear infinite; }}
  @keyframes spin {{ to{{transform:rotate(360deg)}} }}
  .foot {{ padding:13px 32px; border-top:1px solid var(--line); text-align:center;
    font-family:'IBM Plex Mono',monospace; font-size:10px; color:#56657f; letter-spacing:.06em; }}
  /* backup codes modal */
  .modal {{ display:none; position:fixed; inset:0; z-index:5; background:rgba(3,6,12,.8);
    backdrop-filter:blur(6px); place-items:center; padding:24px 16px; }}
  .modal.show {{ display:grid; }}
  .modal-card {{ width:100%; max-width:430px; background:linear-gradient(180deg,#141c30,#0b1120);
    border:1px solid var(--line); border-radius:18px; overflow:hidden;
    max-height:92vh; overflow-y:auto; }}
  .modal-h {{ padding:22px 26px 0; }}
  .modal-h h2 {{ font-family:'Kanit',sans-serif; font-size:19px; margin:0 0 4px; }}
  .modal-b {{ padding:16px 26px 22px; }}
  .codes {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:6px 0 16px; }}
  .code {{ font-family:'IBM Plex Mono',monospace; font-size:14px; letter-spacing:.06em;
    background:rgba(7,11,20,.8); border:1px solid var(--line); border-radius:9px;
    padding:9px 11px; color:#cfe; text-align:center; }}
  .warn {{ font-size:12px; color:var(--amber); background:rgba(245,185,122,.08);
    border:1px solid rgba(245,185,122,.25); border-radius:10px; padding:10px 12px; margin-bottom:14px; }}
  .row {{ display:flex; gap:8px; margin-bottom:12px; }}
  .row .btn {{ font-size:13.5px; padding:11px; }}
  .btn-mini {{ background:rgba(255,255,255,.05); border-color:var(--line); color:var(--ink); }}
  .btn-mini.done {{ background:rgba(52,232,196,.14); border-color:rgba(52,232,196,.4); color:var(--mint); }}
  .ack {{ display:flex; gap:9px; align-items:flex-start; font-size:12.5px; color:#c4d0e4;
    padding:10px; border-radius:9px; cursor:pointer; }}
  .ack input {{ width:auto; margin:2px 0 0; }}
</style></head><body>
<div class="card">
  <div class="top">
    <div class="key-emblem">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
    </div>
    <h1>ตั้งค่า Passkey</h1>
    <p class="sub">ครั้งหน้าเข้า {safe_name} ได้เร็วขึ้น<br>ด้วยลายนิ้วมือ/ใบหน้า — ไม่ต้องผ่าน Google</p>
    <div class="who">{safe_email}</div>
  </div>
  <div class="body">
    <ul class="benefits">
      <li><i class="">✓</i><span>ปลอดภัยกว่ารหัสผ่าน — กัน phishing ได้</span></li>
      <li><i class="">✓</i><span>login เร็ว — แตะครั้งเดียว</span></li>
      <li><i class="">✓</i><span>ผูกกับอุปกรณ์นี้ ใช้ที่อื่นไม่ได้</span></li>
    </ul>

    <div class="err" id="err"></div>
    <div class="unsupported" id="unsupported">⚠️ เบราว์เซอร์นี้ไม่รองรับ Passkey — กด "ข้ามไปก่อน" เพื่อเข้าระบบ</div>

    <label class="fld" for="dev">ชื่ออุปกรณ์</label>
    <input type="text" id="dev" value="อุปกรณ์ของฉัน" maxlength="100">

    <button class="btn btn-pk" id="setup">ตั้งค่า Passkey</button>
    <a class="btn btn-skip" id="skip" href="/oauth/continue?hub_state={hub_state}">ข้ามไปก่อน</a>
  </div>
  <div class="foot">WebAuthn · FIDO2 · ปลอดภัยตามมาตรฐาน</div>
</div>

<div class="modal" id="bcModal">
  <div class="modal-card">
    <div class="modal-h"><h2>🔑 Backup Codes</h2>
      <p class="sub">บันทึกไว้กู้บัญชีถ้าทำอุปกรณ์หาย — แสดงครั้งเดียว</p></div>
    <div class="modal-b">
      <div class="warn">⚠️ แต่ละ code ใช้ได้ครั้งเดียว เก็บในที่ปลอดภัย</div>
      <div class="codes" id="codes"></div>
      <div class="row">
        <button class="btn btn-mini" id="copyBtn">📋 คัดลอก</button>
        <button class="btn btn-mini" id="dlBtn">💾 ดาวน์โหลด</button>
      </div>
      <label class="ack"><input type="checkbox" id="ackChk"><span>ฉันบันทึก backup codes ไว้แล้ว</span></label>
      <button class="btn btn-pk" id="bcContinue" disabled style="margin-top:10px">เข้าสู่ระบบต่อ</button>
    </div>
  </div>
</div>

<script nonce="{nonce}">
const HUB_STATE = {json.dumps(hub_state)};
const CONTINUE_URL = '/oauth/continue?hub_state=' + encodeURIComponent(HUB_STATE);

function b64urlToBuf(s) {{ const p=s.replace(/-/g,'+').replace(/_/g,'/');
  const pad=p.length%4===0?'':'='.repeat(4-(p.length%4)); const bin=atob(p+pad);
  const a=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i); return a.buffer; }}
function bufToB64url(buf) {{ const a=new Uint8Array(buf); let b='';
  for(let i=0;i<a.length;i++)b+=String.fromCharCode(a[i]);
  return btoa(b).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,''); }}
function pkSupported() {{ return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.create); }}

const setup=document.getElementById('setup'), devEl=document.getElementById('dev');
const errEl=document.getElementById('err');
function showErr(m){{ errEl.textContent=m; errEl.classList.add('show'); }}

if(!pkSupported()){{
  document.getElementById('unsupported').classList.add('show');
  setup.disabled=true;
}}

async function doSetup(){{
  errEl.classList.remove('show');
  const dev=(devEl.value||'').trim()||'อุปกรณ์ของฉัน';
  setup.disabled=true; setup.innerHTML='<span class="spinner"></span> กำลังตั้งค่า…';
  try {{
    const s=await fetch('/oauth/passkey/enroll/start',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{hub_state:HUB_STATE}})}});
    if(!s.ok){{ const e=await s.json().catch(()=>({{}})); throw new Error(typeof e.detail==='string'?e.detail:'เริ่มไม่สำเร็จ'); }}
    const opts=await s.json();
    opts.challenge=b64urlToBuf(opts.challenge);
    opts.user.id=b64urlToBuf(opts.user.id);
    (opts.excludeCredentials||[]).forEach(c=>c.id=b64urlToBuf(c.id));
    let cred;
    try {{ cred=await navigator.credentials.create({{publicKey:opts}}); }}
    catch(ce){{ throw new Error('การตั้งค่าถูกยกเลิก หรืออุปกรณ์ไม่รองรับ'); }}
    if(!cred) throw new Error('ไม่ได้รับข้อมูลจากอุปกรณ์');
    const resp=cred.response;
    const payload={{ id:cred.id, rawId:bufToB64url(cred.rawId), type:cred.type,
      authenticatorAttachment:cred.authenticatorAttachment,
      response:{{ attestationObject:bufToB64url(resp.attestationObject),
        clientDataJSON:bufToB64url(resp.clientDataJSON),
        transports:resp.getTransports?resp.getTransports():[] }},
      clientExtensionResults:cred.getClientExtensionResults?cred.getClientExtensionResults():{{}} }};
    const f=await fetch('/oauth/passkey/enroll/finish',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{hub_state:HUB_STATE,device_name:dev,credential:payload}})}});
    if(!f.ok){{ const e=await f.json().catch(()=>({{}})); const d=e.detail;
      throw new Error(typeof d==='string'?d:(d&&d.code?d.code:'ตั้งค่าไม่สำเร็จ')); }}
    const data=await f.json();
    if(data.backup_codes && data.backup_codes.length){{ showBackupCodes(data.backup_codes); }}
    else {{ window.location.href=CONTINUE_URL; }}
  }} catch(err){{ showErr(err.message||'ตั้งค่าไม่สำเร็จ'); setup.disabled=false; setup.textContent='ตั้งค่า Passkey'; }}
}}
setup.addEventListener('click', doSetup);

function showBackupCodes(codes){{
  const wrap=document.getElementById('codes');
  wrap.innerHTML=codes.map(c=>'<div class="code">'+c+'</div>').join('');
  document.getElementById('bcModal').classList.add('show');
  const txt=codes.join('\\n');
  let saved=false;
  const chk=document.getElementById('ackChk'), cont=document.getElementById('bcContinue');
  const copyBtn=document.getElementById('copyBtn'), dlBtn=document.getElementById('dlBtn');
  function refresh(){{ cont.disabled=!(saved && chk.checked); }}
  copyBtn.addEventListener('click', async()=>{{ try{{ await navigator.clipboard.writeText(txt); }}catch(e){{}}
    copyBtn.classList.add('done'); copyBtn.textContent='✓ คัดลอกแล้ว'; saved=true; refresh(); }});
  dlBtn.addEventListener('click', ()=>{{ const b=new Blob(['Central Auth Hub — Backup Codes\\n\\n'+txt+'\\n'],{{type:'text/plain'}});
    const u=URL.createObjectURL(b); const a=document.createElement('a'); a.href=u;
    a.download='passkey-backup-codes.txt'; a.click(); URL.revokeObjectURL(u);
    dlBtn.classList.add('done'); dlBtn.textContent='✓ ดาวน์โหลดแล้ว'; saved=true; refresh(); }});
  chk.addEventListener('change', refresh);
  cont.addEventListener('click', ()=>{{ window.location.href=CONTINUE_URL; }});
}}
</script>
</body></html>"""


# ============ Passkey recovery page (Hub-served) ============


def _passkey_recover_html(nonce: str) -> str:
    """หน้ากู้บัญชี Passkey — backup code / email OTP. เสิร์ฟจาก Hub.

    fetch /auth/passkey/recover/* same-origin (localhost:8000). subsystem user
    ใช้ได้โดยไม่ต้องเข้า admin frontend.
    """
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>กู้บัญชี Passkey · Central Auth Hub</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Kanit:wght@500;600&family=IBM+Plex+Sans+Thai:wght@400;500&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<style nonce="{nonce}">
  :root {{ --bg-0:#070b14; --ink:#e8eef7; --muted:#8a99b5; --mint:#34e8c4;
           --mint-2:#13b89a; --line:rgba(148,178,224,.14); --danger:#ff6b81; }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; height:100%; }}
  body {{ font-family:'IBM Plex Sans Thai',system-ui,sans-serif; background:var(--bg-0);
          color:var(--ink); min-height:100vh; display:grid; place-items:center;
          padding:32px 16px; position:relative; overflow:hidden; }}
  body::before {{ content:''; position:fixed; inset:-20%; z-index:0;
    background:radial-gradient(40% 50% at 20% 20%, rgba(52,232,196,.14), transparent 70%),
      radial-gradient(45% 55% at 85% 20%, rgba(82,120,255,.14), transparent 70%);
    filter:blur(20px); }}
  .card {{ position:relative; z-index:1; width:100%; max-width:404px;
    background:linear-gradient(180deg, rgba(20,28,48,.86), rgba(11,17,32,.92));
    border:1px solid var(--line); border-radius:22px; backdrop-filter:blur(14px);
    box-shadow:0 30px 80px -20px rgba(0,0,0,.7); overflow:hidden; }}
  .top {{ padding:28px 30px 4px; }}
  h1 {{ font-family:'Kanit',sans-serif; font-weight:600; font-size:22px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); font-size:13px; margin:0; line-height:1.5; }}
  .body {{ padding:18px 30px 24px; }}
  .tabs {{ display:flex; gap:6px; background:rgba(7,11,20,.6); border-radius:11px;
           padding:4px; margin-bottom:16px; }}
  .tab {{ flex:1; padding:9px; border:none; border-radius:8px; background:transparent;
          color:var(--muted); font-family:'IBM Plex Sans Thai',sans-serif; font-size:13px;
          cursor:pointer; font-weight:500; }}
  .tab.active {{ background:rgba(52,232,196,.14); color:var(--mint); }}
  label.fld {{ font-size:11px; color:var(--muted); font-family:'IBM Plex Mono',monospace;
               display:block; margin:0 0 6px; }}
  input {{ width:100%; padding:12px 13px; border-radius:10px; border:1px solid var(--line);
           background:rgba(7,11,20,.7); color:var(--ink); font-size:14px;
           font-family:'IBM Plex Sans Thai',sans-serif; margin-bottom:12px; }}
  input.mono {{ font-family:'IBM Plex Mono',monospace; letter-spacing:.1em; text-align:center; }}
  input:focus {{ outline:none; border-color:var(--mint-2); box-shadow:0 0 0 3px rgba(52,232,196,.16); }}
  .btn {{ width:100%; padding:13px; border-radius:12px; border:none; cursor:pointer;
          font-family:'Kanit',sans-serif; font-weight:500; font-size:15px;
          color:#04221c; background:linear-gradient(100deg,var(--mint),#5ff0d6); }}
  .btn[disabled] {{ opacity:.5; cursor:not-allowed; }}
  .msg {{ font-size:12.5px; padding:10px 12px; border-radius:10px; margin-bottom:12px;
          line-height:1.45; display:none; }}
  .msg.show {{ display:block; }}
  .msg.err {{ color:var(--danger); background:rgba(255,107,129,.08); border:1px solid rgba(255,107,129,.28); }}
  .msg.ok {{ color:var(--mint); background:rgba(52,232,196,.08); border:1px solid rgba(52,232,196,.3); }}
  .back {{ display:block; text-align:center; margin-top:14px; font-size:12px;
           color:var(--muted); text-decoration:none; }}
  .back:hover {{ color:var(--ink); }}
  .hide {{ display:none; }}
  .foot {{ padding:13px 30px; border-top:1px solid var(--line); text-align:center;
           font-family:'IBM Plex Mono',monospace; font-size:10px; color:#56657f; }}

  /* Codes display — premium ack UX (เทียบ admin BackupCodesModal) */
  .codes-head {{ display:flex; gap:11px; align-items:flex-start; padding:14px 14px 12px;
                 border-radius:13px; background:linear-gradient(180deg,rgba(52,232,196,.08),rgba(52,232,196,.02));
                 border:1px solid rgba(52,232,196,.22); margin-bottom:14px; }}
  .codes-head-icon {{ font-size:22px; line-height:1; flex:none; }}
  .codes-head-body {{ flex:1; min-width:0; }}
  .codes-head-title {{ font-family:'Kanit',sans-serif; font-weight:600; font-size:14.5px;
                       color:var(--mint); margin:0 0 2px; letter-spacing:-.01em; }}
  .codes-head-sub {{ font-size:11.5px; color:var(--muted); line-height:1.5; }}
  .warn-band {{ display:flex; gap:8px; align-items:flex-start; font-size:11.5px;
                color:#f5b97a; background:rgba(245,185,122,.06);
                border:1px solid rgba(245,185,122,.25); border-radius:10px;
                padding:9px 11px; margin-bottom:12px; line-height:1.45; }}
  .codes-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px;
                 background:rgba(7,11,20,.5); border:1px solid var(--line);
                 border-radius:13px; padding:11px; margin-bottom:14px; }}
  .code-cell {{ display:flex; align-items:center; gap:7px; padding:7px 9px;
                background:rgba(7,11,20,.85); border:1px solid var(--line);
                border-radius:8px; }}
  .code-num {{ font-family:'IBM Plex Mono',monospace; font-size:9.5px; color:#56657f;
               letter-spacing:.04em; flex:none; }}
  .code-val {{ font-family:'IBM Plex Mono',monospace; font-size:12.5px; color:#9ff5dc;
               letter-spacing:.08em; font-weight:500; }}
  .actions-row {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:12px; }}
  .act-btn {{ display:flex; align-items:center; justify-content:center; gap:7px;
              padding:11px 12px; border-radius:11px; cursor:pointer;
              font-family:'Kanit',sans-serif; font-weight:500; font-size:13.5px;
              border:1px solid var(--line); background:rgba(255,255,255,.04);
              color:var(--ink); transition:all .15s ease; }}
  .act-btn:hover {{ background:rgba(255,255,255,.08); border-color:rgba(148,178,224,.3); }}
  .act-btn.done {{ background:rgba(52,232,196,.12); border-color:rgba(52,232,196,.4);
                   color:var(--mint); }}
  .ack-box {{ display:flex; gap:10px; align-items:flex-start; padding:11px 12px;
              background:rgba(255,255,255,.03); border:1px solid var(--line);
              border-radius:10px; cursor:pointer; margin-bottom:12px;
              transition:all .15s ease; }}
  .ack-box:hover {{ background:rgba(255,255,255,.06); }}
  .ack-box.armed {{ background:rgba(52,232,196,.05); border-color:rgba(52,232,196,.3); }}
  .ack-box input {{ width:auto; margin:2px 0 0; flex:none; accent-color:var(--mint-2); }}
  .ack-box-text {{ font-size:12px; color:#c4d0e4; line-height:1.5; }}
</style></head><body>
<div class="card">
  <div class="top">
    <h1>กู้บัญชี Passkey</h1>
    <p class="sub">ทำอุปกรณ์หาย? ใช้ backup code หรือ email OTP เพื่อลบ Passkey เก่า แล้วตั้งค่าใหม่</p>
  </div>
  <div class="body">
    <div id="result" class="msg ok"></div>
    <div id="form">
      <div class="tabs">
        <button class="tab active" id="tabBackup">Backup Code</button>
        <button class="tab" id="tabOtp">กู้ OTP</button>
        <button class="tab" id="tabRegen">ขอ codes ใหม่</button>
      </div>
      <div id="err" class="msg err"></div>
      <label class="fld" for="email">อีเมล</label>
      <input type="email" id="email" placeholder="you@uni.ac.th">

      <div id="paneBackup">
        <label class="fld" for="code">Backup Code</label>
        <input type="text" id="code" class="mono" placeholder="AB3D-7K9P" maxlength="20">
        <button class="btn" id="btnBackup">กู้บัญชีด้วย Backup Code</button>
      </div>

      <div id="paneOtp" class="hide">
        <div id="otpStep1">
          <button class="btn" id="btnOtpSend">ส่ง OTP ทาง Email</button>
        </div>
        <div id="otpStep2" class="hide">
          <label class="fld" for="otp">OTP 6 หลัก</label>
          <input type="text" id="otp" class="mono" placeholder="••••••" maxlength="6">
          <button class="btn" id="btnOtpVerify">ยืนยัน OTP</button>
        </div>
      </div>
      <a class="back" href="javascript:history.back()">← กลับ</a>
    </div>
  </div>
  <div class="foot">WebAuthn Recovery · Argon2id · HMAC OTP</div>
</div>

<script nonce="{nonce}">
const $ = id => document.getElementById(id);
const errEl = $('err'), resultEl = $('result'), formEl = $('form');
function showErr(m) {{ errEl.textContent = m; errEl.classList.add('show'); }}
function clearErr() {{ errEl.classList.remove('show'); }}
function done(m, codes) {{
  formEl.classList.add('hide');
  if (!codes || !codes.length) {{
    resultEl.innerHTML = '<div style="padding:14px;border-radius:11px;background:rgba(52,232,196,.08);border:1px solid rgba(52,232,196,.3);color:var(--mint);font-size:13px;line-height:1.5">✓ ' + m + '</div>';
    resultEl.classList.add('show');
    return;
  }}
  const txt = codes.join('\\n');
  const pad = n => String(n).padStart(2,'0');
  // Premium ack UX — เหมือน admin BackupCodesModal
  let html =
    '<div class="codes-head">' +
      '<div class="codes-head-icon">🔑</div>' +
      '<div class="codes-head-body">' +
        '<div class="codes-head-title">Backup Codes ของคุณ</div>' +
        '<div class="codes-head-sub">' + m + '</div>' +
      '</div>' +
    '</div>' +
    '<div class="warn-band">⚠️ ใช้กรณีฉุกเฉินเท่านั้น: ถ้า Passkey หาย ใช้ codes เหล่านี้กู้บัญชีได้. แต่ละ code ใช้ได้ครั้งเดียว.</div>' +
    '<div class="codes-grid">' +
      codes.map((c,i) =>
        '<div class="code-cell">' +
          '<span class="code-num">' + pad(i+1) + '.</span>' +
          '<span class="code-val">' + c + '</span>' +
        '</div>'
      ).join('') +
    '</div>' +
    '<div class="actions-row">' +
      '<button class="act-btn" id="cpBtn">📋 คัดลอก</button>' +
      '<button class="act-btn" id="dlBtn">💾 ดาวน์โหลด</button>' +
    '</div>' +
    '<label class="ack-box" id="ackBox">' +
      '<input type="checkbox" id="ackChk">' +
      '<span class="ack-box-text">ฉันได้บันทึก backup codes ไว้ในที่ปลอดภัยแล้ว และเข้าใจว่าหากทำหาย อาจเข้าสู่ระบบไม่ได้</span>' +
    '</label>' +
    '<button id="okBtn" class="btn" disabled>ยืนยันว่าบันทึกแล้ว</button>';
  resultEl.innerHTML = html;
  resultEl.classList.add('show');

  let saved = false;
  const chk = document.getElementById('ackChk'),
        ok = document.getElementById('okBtn'),
        ackBox = document.getElementById('ackBox'),
        cpBtn = document.getElementById('cpBtn'),
        dlBtn = document.getElementById('dlBtn');
  function refresh() {{
    const ready = saved && chk.checked;
    ok.disabled = !ready;
    ackBox.classList.toggle('armed', chk.checked);
  }}
  cpBtn.addEventListener('click', async () => {{
    try {{ await navigator.clipboard.writeText(txt); }} catch(x) {{}}
    cpBtn.innerHTML = '✓ คัดลอกแล้ว';
    cpBtn.classList.add('done');
    saved = true; refresh();
  }});
  dlBtn.addEventListener('click', () => {{
    const b = new Blob(
      ['Central Auth Hub — Backup Codes\\n' +
       new Date().toISOString() + '\\n\\n' + txt + '\\n'],
      {{type:'text/plain'}}
    );
    const u = URL.createObjectURL(b); const a = document.createElement('a');
    a.href = u; a.download = 'passkey-backup-codes.txt'; a.click();
    URL.revokeObjectURL(u);
    dlBtn.innerHTML = '✓ ดาวน์โหลดแล้ว';
    dlBtn.classList.add('done');
    saved = true; refresh();
  }});
  chk.addEventListener('change', refresh);
  ok.addEventListener('click', () => {{
    resultEl.innerHTML =
      '<div style="padding:18px;border-radius:13px;background:rgba(52,232,196,.08);border:1px solid rgba(52,232,196,.3);text-align:center">' +
        '<div style="font-size:28px;margin-bottom:6px">✓</div>' +
        '<div style="font-family:\\'Kanit\\',sans-serif;font-weight:500;color:var(--mint);font-size:15px;margin-bottom:4px">เก็บ backup codes เรียบร้อย</div>' +
        '<div style="font-size:12px;color:var(--muted);line-height:1.5">กลับไป login ที่ระบบของคุณได้เลย</div>' +
      '</div>';
  }});
}}

let regenMode = false;
function setTab(active, regen) {{
  ['tabBackup','tabOtp','tabRegen'].forEach(t => document.getElementById(t).classList.toggle('active', t===active));
  $('paneBackup').classList.toggle('hide', active!=='tabBackup');
  $('paneOtp').classList.toggle('hide', active==='tabBackup');
  $('otpStep1').classList.remove('hide'); $('otpStep2').classList.add('hide');
  regenMode = regen; clearErr();
}}
$('tabBackup').addEventListener('click', () => setTab('tabBackup', false));
$('tabOtp').addEventListener('click', () => setTab('tabOtp', false));
$('tabRegen').addEventListener('click', () => setTab('tabRegen', true));

async function post(url, body) {{
  const r = await fetch(url, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(body)}});
  const data = await r.json().catch(()=>({{}}));
  return {{ok:r.ok, data}};
}}
function emailVal() {{ return ($('email').value||'').trim(); }}
function pickMsg(data, fallback) {{
  const d = data.detail;
  if (typeof d === 'string') return d;
  if (d && d.message) return d.message;
  if (Array.isArray(d)) return 'รูปแบบอีเมลไม่ถูกต้อง';
  return fallback;
}}

$('btnBackup').addEventListener('click', async () => {{
  clearErr();
  if (!emailVal()) return showErr('กรุณากรอกอีเมล');
  if (!$('code').value.trim()) return showErr('กรุณากรอก backup code');
  $('btnBackup').disabled = true; $('btnBackup').textContent = 'กำลังตรวจสอบ…';
  const {{ok, data}} = await post('/auth/passkey/recover/backup-code', {{email:emailVal(), code:$('code').value.trim()}});
  if (ok) done(data.message);
  else {{ showErr(pickMsg(data, 'กู้บัญชีไม่สำเร็จ')); $('btnBackup').disabled=false; $('btnBackup').textContent='กู้บัญชีด้วย Backup Code'; }}
}});

$('btnOtpSend').addEventListener('click', async () => {{
  clearErr();
  if (!emailVal()) return showErr('กรุณากรอกอีเมล');
  $('btnOtpSend').disabled = true; $('btnOtpSend').textContent = 'กำลังส่ง…';
  const url = regenMode ? '/auth/passkey/backup-codes/regen-otp/start' : '/auth/passkey/recover/email-otp/start';
  const {{ok, data}} = await post(url, {{email:emailVal()}});
  if (ok) {{ $('otpStep1').classList.add('hide'); $('otpStep2').classList.remove('hide'); }}
  else showErr(pickMsg(data, 'ส่ง OTP ไม่สำเร็จ'));
  $('btnOtpSend').disabled = false; $('btnOtpSend').textContent = 'ส่ง OTP ทาง Email';
}});

$('btnOtpVerify').addEventListener('click', async () => {{
  clearErr();
  if (!$('otp').value.trim()) return showErr('กรอก OTP');
  $('btnOtpVerify').disabled = true; $('btnOtpVerify').textContent = 'กำลังตรวจสอบ…';
  const url = regenMode ? '/auth/passkey/backup-codes/regen-otp/verify' : '/auth/passkey/recover/email-otp/verify';
  const {{ok, data}} = await post(url, {{email:emailVal(), otp:$('otp').value.trim()}});
  if (ok) done(data.message, data.backup_codes);
  else {{ showErr(pickMsg(data, 'OTP ไม่ถูกต้อง')); $('btnOtpVerify').disabled=false; $('btnOtpVerify').textContent='ยืนยัน OTP'; }}
}});
</script>
</body></html>"""


# ============ Login chooser page (A) — Google / Passkey ============


def _login_chooser_html(hub_state: str, subsystem_name: str, nonce: str) -> str:
    """หน้าเลือกวิธี login — Google (redirect) หรือ Passkey (WebAuthn JS).

    Aesthetic: "Secure Vault" — dark glassmorphism, gradient mesh, Thai display
    typography (Kanit + IBM Plex Sans Thai), mint-cyan accent, staggered reveal.

    Same-origin: เสิร์ฟจาก Hub → fetch /oauth/passkey/* ตรง ไม่ผ่าน proxy.
    inline style+script ใช้ CSP nonce (กัน XSS — middleware ตั้ง nonce-{nonce}).
    """
    # esc ชื่อ subsystem (กัน HTML injection — ชื่อมาจาก DB)
    safe_name = (
        subsystem_name.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>เข้าสู่ระบบ · {safe_name}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Kanit:wght@500;600;700&family=IBM+Plex+Sans+Thai:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style nonce="{nonce}">
  :root {{
    --bg-0:#070b14; --bg-1:#0d1424; --ink:#e8eef7; --muted:#8a99b5;
    --mint:#34e8c4; --mint-2:#13b89a; --line:rgba(148,178,224,.14);
    --danger:#ff6b81;
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; height:100%; }}
  body {{
    font-family:'IBM Plex Sans Thai',system-ui,sans-serif;
    background:var(--bg-0); color:var(--ink);
    min-height:100vh; display:grid; place-items:center; padding:32px 16px;
    overflow:hidden; position:relative;
  }}
  /* gradient mesh + glow orbs */
  body::before {{
    content:''; position:fixed; inset:-20%; z-index:0;
    background:
      radial-gradient(40% 50% at 18% 22%, rgba(52,232,196,.16), transparent 70%),
      radial-gradient(45% 55% at 85% 18%, rgba(82,120,255,.16), transparent 70%),
      radial-gradient(60% 60% at 50% 110%, rgba(120,80,220,.12), transparent 70%);
    filter:blur(20px); animation:drift 18s ease-in-out infinite alternate;
  }}
  /* fine grain overlay */
  body::after {{
    content:''; position:fixed; inset:0; z-index:0; pointer-events:none; opacity:.05;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  }}
  @keyframes drift {{ from{{transform:translate3d(0,0,0) scale(1)}} to{{transform:translate3d(0,-3%,0) scale(1.06)}} }}

  .card {{
    position:relative; z-index:1; width:100%; max-width:404px;
    background:linear-gradient(180deg, rgba(20,28,48,.86), rgba(11,17,32,.92));
    border:1px solid var(--line); border-radius:22px;
    box-shadow:0 1px 0 rgba(255,255,255,.04) inset, 0 30px 80px -20px rgba(0,0,0,.7),
               0 0 60px -30px rgba(52,232,196,.5);
    backdrop-filter:blur(14px); overflow:hidden;
    animation:rise .7s cubic-bezier(.2,.8,.2,1) both;
  }}
  @keyframes rise {{ from{{opacity:0; transform:translateY(16px) scale(.985)}} to{{opacity:1; transform:none}} }}

  .top {{ padding:30px 32px 6px; }}
  .badge {{
    display:inline-flex; align-items:center; gap:7px; font-family:'IBM Plex Mono',monospace;
    font-size:10px; letter-spacing:.18em; text-transform:uppercase; color:var(--mint);
    border:1px solid rgba(52,232,196,.3); border-radius:999px; padding:5px 11px;
    background:rgba(52,232,196,.06);
  }}
  .dot {{ width:6px; height:6px; border-radius:50%; background:var(--mint);
          box-shadow:0 0 8px var(--mint); animation:pulse 2s infinite; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.35}} }}
  h1 {{
    font-family:'Kanit',sans-serif; font-weight:600; font-size:27px; line-height:1.18;
    margin:16px 0 4px; letter-spacing:-.01em;
  }}
  h1 .accent {{ color:transparent; background:linear-gradient(92deg,var(--mint),#7ad6ff);
                -webkit-background-clip:text; background-clip:text; }}
  .sub {{ color:var(--muted); font-size:13.5px; margin:0; }}

  .body {{ padding:22px 32px 26px; }}
  .stagger {{ opacity:0; animation:fade .6s ease forwards; }}
  .s1{{animation-delay:.12s}} .s2{{animation-delay:.20s}} .s3{{animation-delay:.28s}} .s4{{animation-delay:.36s}}
  @keyframes fade {{ from{{opacity:0; transform:translateY(8px)}} to{{opacity:1; transform:none}} }}

  .btn {{
    display:flex; align-items:center; justify-content:center; gap:11px; width:100%;
    padding:14px 16px; border-radius:13px; font-family:'Kanit',sans-serif; font-weight:500;
    font-size:15.5px; text-decoration:none; border:1px solid transparent; cursor:pointer;
    transition:transform .15s ease, box-shadow .25s ease, background .2s ease; position:relative;
    overflow:hidden;
  }}
  .btn:active {{ transform:translateY(1px) scale(.995); }}
  .btn-pk {{
    color:#04221c; background:linear-gradient(100deg,var(--mint),#5ff0d6);
    box-shadow:0 10px 30px -10px rgba(52,232,196,.6);
  }}
  .btn-pk:hover {{ transform:translateY(-2px); box-shadow:0 16px 40px -12px rgba(52,232,196,.7); }}
  .btn-pk::after {{ /* shine sweep */
    content:''; position:absolute; top:0; left:-60%; width:40%; height:100%;
    background:linear-gradient(100deg,transparent,rgba(255,255,255,.55),transparent);
    transform:skewX(-18deg); transition:left .5s ease;
  }}
  .btn-pk:hover::after {{ left:130%; }}
  .btn-ghost {{
    color:var(--ink); background:rgba(255,255,255,.04); border-color:var(--line);
  }}
  .btn-ghost:hover {{ background:rgba(255,255,255,.08); border-color:rgba(148,178,224,.3); }}
  .btn[disabled] {{ opacity:.5; cursor:not-allowed; transform:none; box-shadow:none; }}

  .pk-form {{ display:grid; gap:11px; margin-bottom:4px; overflow:hidden;
              max-height:0; opacity:0; transition:max-height .4s ease, opacity .3s ease; }}
  .pk-form.open {{ max-height:280px; opacity:1; margin-bottom:14px; }}
  label.fld {{ font-size:11px; color:var(--muted); letter-spacing:.04em;
               margin-bottom:-4px; font-family:'IBM Plex Mono',monospace; }}
  input[type=email] {{
    width:100%; padding:13px 14px; border-radius:11px; border:1px solid var(--line);
    background:rgba(7,11,20,.7); color:var(--ink); font-size:14.5px;
    font-family:'IBM Plex Sans Thai',sans-serif; transition:border .2s,box-shadow .2s;
  }}
  input[type=email]::placeholder {{ color:#52617e; }}
  input[type=email]:focus {{ outline:none; border-color:var(--mint-2);
                             box-shadow:0 0 0 3px rgba(52,232,196,.16); }}

  .err {{ display:none; align-items:flex-start; gap:8px; font-size:12.5px; color:var(--danger);
          background:rgba(255,107,129,.08); border:1px solid rgba(255,107,129,.28);
          padding:10px 12px; border-radius:10px; line-height:1.45; }}
  .err.show {{ display:flex; animation:shake .35s; }}
  @keyframes shake {{ 0%,100%{{transform:translateX(0)}} 25%{{transform:translateX(-4px)}} 75%{{transform:translateX(4px)}} }}
  .hint {{ font-size:11.5px; color:var(--muted); }}

  .divider {{ display:flex; align-items:center; gap:12px; margin:18px 0;
              color:var(--muted); font-size:11px; font-family:'IBM Plex Mono',monospace; }}
  .divider::before, .divider::after {{ content:''; flex:1; height:1px;
              background:linear-gradient(90deg,transparent,var(--line),transparent); }}

  .spinner {{ width:16px; height:16px; border:2px solid rgba(4,34,28,.35);
              border-top-color:#04221c; border-radius:50%; animation:spin .7s linear infinite; }}
  @keyframes spin {{ to{{transform:rotate(360deg)}} }}

  .foot {{ padding:14px 32px; border-top:1px solid var(--line); text-align:center;
           font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.08em;
           color:#56657f; }}
  .gicon {{ width:18px; height:18px; flex:none; }}
  .recover-link {{ display:block; text-align:center; margin-top:14px; font-size:12.5px;
                   color:var(--mint-2); text-decoration:none; }}
  .recover-link:hover {{ color:var(--mint); text-decoration:underline; }}
</style></head><body>
<div class="card">
  <div class="top">
    <span class="badge"><span class="dot"></span>CENTRAL AUTH HUB</span>
    <h1>เข้าสู่ <span class="accent">{safe_name}</span></h1>
    <p class="sub">เลือกวิธียืนยันตัวตนเพื่อดำเนินการต่อ</p>
  </div>
  <div class="body">
    <button class="btn btn-pk stagger s1" id="pkToggle">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
      ดำเนินการด้วย Passkey
    </button>

    <div class="pk-form stagger s2" id="pkForm" aria-hidden="true">
      <div class="err" id="pkErr"></div>
      <label class="fld" for="pkEmail">อีเมลของคุณ</label>
      <input type="email" id="pkEmail" placeholder="you@uni.ac.th" autocomplete="username webauthn" inputmode="email">
      <button class="btn btn-pk" id="pkSubmit">ยืนยันตัวตน</button>
      <p class="hint" id="pkHint">ระบบจะขอ biometric หรือ security key ของอุปกรณ์นี้</p>
    </div>

    <div class="divider stagger s3">หรือ</div>

    <a class="btn btn-ghost stagger s4" href="/oauth/authorize/google?hub_state={hub_state}">
      <svg class="gicon" viewBox="0 0 24 24"><path d="M21.6 12.227c0-.709-.064-1.39-.182-2.045H12v3.868h5.382a4.6 4.6 0 0 1-1.996 3.018v2.51h3.232c1.891-1.742 2.982-4.305 2.982-7.35Z" fill="#4285F4"/><path d="M12 22c2.7 0 4.964-.895 6.618-2.423l-3.232-2.509c-.895.6-2.04.955-3.386.955-2.605 0-4.81-1.76-5.595-4.123H3.064v2.59A9.996 9.996 0 0 0 12 22Z" fill="#34A853"/><path d="M6.405 13.9a6.003 6.003 0 0 1 0-3.8V7.51H3.064a9.996 9.996 0 0 0 0 8.98l3.341-2.59Z" fill="#FBBC05"/><path d="M12 5.977c1.468 0 2.786.505 3.823 1.496l2.868-2.868C16.96 2.99 14.695 2 12 2A9.996 9.996 0 0 0 3.064 7.51l3.341 2.59C7.19 7.736 9.395 5.977 12 5.977Z" fill="#EA4335"/></svg>
      ดำเนินการด้วย Google
    </a>
    <a class="recover-link" href="/oauth/passkey/recover">ทำ Passkey หาย? กู้บัญชี</a>
  </div>
  <div class="foot">OAuth 2.0 · PKCE · WebAuthn · JWT RS256</div>
</div>

<script nonce="{nonce}">
const HUB_STATE = {json.dumps(hub_state)};

function b64urlToBuf(s) {{
  const p = s.replace(/-/g,'+').replace(/_/g,'/');
  const pad = p.length % 4 === 0 ? '' : '='.repeat(4 - (p.length % 4));
  const bin = atob(p + pad); const a = new Uint8Array(bin.length);
  for (let i=0;i<bin.length;i++) a[i]=bin.charCodeAt(i); return a.buffer;
}}
function bufToB64url(buf) {{
  const a = new Uint8Array(buf); let bin='';
  for (let i=0;i<a.length;i++) bin+=String.fromCharCode(a[i]);
  return btoa(bin).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');
}}
function pkSupported() {{
  return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.get);
}}

const toggle = document.getElementById('pkToggle');
const form = document.getElementById('pkForm');
const emailEl = document.getElementById('pkEmail');
const submit = document.getElementById('pkSubmit');
const errEl = document.getElementById('pkErr');
const hintEl = document.getElementById('pkHint');

toggle.addEventListener('click', () => {{
  toggle.style.display = 'none';
  form.classList.add('open');
  form.setAttribute('aria-hidden','false');
  if (!pkSupported()) {{
    submit.disabled = true;
    hintEl.textContent = '⚠️ เบราว์เซอร์นี้ไม่รองรับ Passkey — กรุณาใช้ Google';
    hintEl.style.color = '#f5b97a';
  }} else {{ emailEl.focus(); }}
}});

function showErr(m) {{ errEl.textContent = m; errEl.classList.add('show'); }}
function clearErr() {{ errEl.classList.remove('show'); }}

function setLoading(on) {{
  if (on) {{ submit.disabled = true; submit.innerHTML = '<span class="spinner"></span> กำลังยืนยัน…'; }}
  else {{ submit.disabled = false; submit.textContent = 'ยืนยันตัวตน'; }}
}}

async function doPasskey() {{
  clearErr();
  const email = (emailEl.value || '').trim();
  if (!email) {{ showErr('กรุณากรอกอีเมล'); emailEl.focus(); return; }}
  setLoading(true);
  try {{
    const startRes = await fetch('/oauth/passkey/start', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{hub_state: HUB_STATE, email}})
    }});
    if (!startRes.ok) {{
      const e = await startRes.json().catch(()=>({{}}));
      const msg = typeof e.detail==='string' ? e.detail
        : (Array.isArray(e.detail) ? 'รูปแบบอีเมลไม่ถูกต้อง' : 'เริ่ม Passkey ไม่สำเร็จ');
      throw new Error(msg);
    }}
    const opts = await startRes.json();
    const hasCreds = (opts.allowCredentials||[]).length > 0;
    opts.challenge = b64urlToBuf(opts.challenge);
    (opts.allowCredentials||[]).forEach(c => c.id = b64urlToBuf(c.id));

    let cred;
    try {{
      cred = await navigator.credentials.get({{publicKey: opts}});
    }} catch (ceErr) {{
      // ไม่มี Passkey สำหรับอีเมลนี้ หรือ user ยกเลิก — ข้อความเดียว (anti-enumeration)
      throw new Error('ไม่พบ Passkey สำหรับอีเมลนี้ หรือการยืนยันถูกยกเลิก — ลองใช้ Google หรือลงทะเบียน Passkey ที่ Hub ก่อน');
    }}
    if (!cred) throw new Error('ไม่ได้รับข้อมูลจากอุปกรณ์');

    const payload = {{
      id: cred.id, rawId: bufToB64url(cred.rawId), type: cred.type,
      authenticatorAttachment: cred.authenticatorAttachment,
      response: {{
        authenticatorData: bufToB64url(cred.response.authenticatorData),
        clientDataJSON: bufToB64url(cred.response.clientDataJSON),
        signature: bufToB64url(cred.response.signature),
        userHandle: cred.response.userHandle ? bufToB64url(cred.response.userHandle) : null
      }},
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {{}}
    }};
    const finRes = await fetch('/oauth/passkey/finish', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{hub_state: HUB_STATE, email, credential: payload}})
    }});
    if (!finRes.ok) {{
      const e = await finRes.json().catch(()=>({{}}));
      const d = e.detail;
      let msg = 'Passkey login ไม่สำเร็จ';
      if (typeof d === 'string') msg = d;
      else if (d && d.code === 'invalid_credential') msg = 'ไม่พบ Passkey ที่ใช้ได้กับอีเมลนี้';
      else if (d && d.code) msg = d.code;
      throw new Error(msg);
    }}
    const data = await finRes.json();
    submit.innerHTML = '<span class="spinner"></span> สำเร็จ · กำลังเปลี่ยนหน้า…';
    window.location.href = data.redirect_url;
  }} catch (err) {{
    showErr(err.message || 'Passkey login ไม่สำเร็จ');
    setLoading(false);
  }}
}}
submit.addEventListener('click', doPasskey);
emailEl.addEventListener('keydown', e => {{ if (e.key==='Enter') doPasskey(); }});
emailEl.addEventListener('input', clearErr);
</script>
</body></html>"""


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
