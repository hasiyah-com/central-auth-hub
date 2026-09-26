import html
import json
import secrets
from datetime import datetime
from urllib.parse import urlparse

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip
from app.rate_limiter import limiter
from app.models import LoginSession, Subsystem, User
from app.redis_client import redis_client
from app.routers.auth import oauth  # ใช้ Authlib client ตัวเดียวกับ Week 2
from app.services.alert_service import maybe_alert_ml_risk
from app.services.audit_service import log_action
from app.services.auth_policy import get_auth_policy
from app.services.access_policy import evaluate_access_policy
from app.services.identity_challenge import is_user_challenged
from app.services.subsystem_health import get_status as get_health_status
from app.services.feature_extraction import (
    extract_session_features,
    parse_browser,
    parse_device_type,
    parse_os_name,
)
from app.services.geoip import lookup_geo
from app.services.ip_blacklist import is_blacklisted
from app.services.hooks import (
    EVT_OAUTH_AUTHORIZED,
    EVT_OAUTH_FAILURE,
    emit,
)
from app.services.jwt_service import create_subsystem_token, revoke_jti
from app.services.pkce import generate_pkce_pair, verify_pkce
from app.security.risk_engine import evaluate_login_risk
from app.services.secret_service import verify_secret
from app.services import webauthn_service
from app.services import passkey_recovery
from app.services import risk_challenge
from app.services import mfa_policy
from app.services import totp_service

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
    if subsystem.status == "suspended":
        # ระงับใช้งานชั่วคราว → 503 Service Unavailable + หน้า HTML
        log_action(
            db,
            actor_id=None,
            action="oauth_authorize_blocked_suspended",
            target_type="subsystem",
            target_id=subsystem.id,
            ip=get_client_ip(request),
            metadata={"client_id": client_id, "redirect_uri": redirect_uri},
        )
        db.commit()
        return HTMLResponse(
            content=_suspended_html(subsystem_name=subsystem.name),
            status_code=503,
        )
    if subsystem.status != "active":
        # pending — 403 (ยังไม่ได้รับอนุมัติ ≠ ระงับ)
        raise HTTPException(
            status_code=403,
            detail=(
                f"subsystem '{subsystem.name}' ยังไม่ได้รับอนุมัติจาก admin "
                f"(status: {subsystem.status})"
            ),
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
    policy = get_auth_policy(db)
    return HTMLResponse(
        content=_login_chooser_html(
            hub_state=hub_state,
            subsystem_name=subsystem.name,
            nonce=nonce,
            allow_google=policy["google"],
            allow_passkey=policy["passkey"],
        ),
        # หน้านี้ผูกกับ hub_state ที่ใช้ได้ครั้งเดียว (ลบจาก Redis หลัง consume) —
        # ถ้า browser/proxy cache ไว้แล้วเปิดซ้ำ (back button ฯลฯ) จะได้ state ตาย
        # ที่ error "หมดอายุ" เสมอไม่ว่าจะรีเฟรชเร็วแค่ไหน
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
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
    if not get_auth_policy(db)["google"]:
        raise HTTPException(
            status_code=403,
            detail="Google login ถูกปิดใช้งานโดยผู้ดูแลระบบ — ใช้ Passkey แทน",
        )
    return await oauth.google.authorize_redirect(
        request, settings.oauth_callback_uri, state=hub_state
    )


def _allowed_subsystem_origins(db: Session) -> set[str]:
    """origin (scheme://netloc) ของ subsystem ที่ active ทุกตัว — ใช้เป็น allowlist
    ของ return_to (login page ของ subsystem อยู่ origin เดียวกับ redirect_uri)."""
    origins: set[str] = set()
    rows = db.query(Subsystem.redirect_uris).filter(Subsystem.status == "active").all()
    for (uris,) in rows:
        for u in uris or []:
            try:
                p = urlparse(u)
            except Exception:
                continue
            if p.scheme and p.netloc:
                origins.add(f"{p.scheme}://{p.netloc}")
    return origins


def _safe_return_to(raw: str | None, allowed_origins: set[str] | None = None) -> str:
    """กัน open-redirect ของ return_to.

    - relative path (`/...` แต่ไม่ใช่ `//`) → อนุญาต (Hub-local)
    - absolute http(s) → อนุญาต **เฉพาะ origin ที่อยู่ใน allowed_origins**
      (origin ของ subsystem ที่ลงทะเบียน) เพื่อกันใช้โดเมน Hub เป็นจุดเด้ง phishing
    - อื่นๆ (javascript:, data:, //, origin นอก allowlist) → ทิ้ง (คืน "")

    หมายเหตุ: ถ้าไม่ส่ง allowed_origins (None) จะ fallback ตรวจแค่ scheme
    (backward-compat) — call site ควรส่ง allowlist เสมอ
    """
    if not raw:
        return ""
    raw = raw.strip()
    if raw.startswith("/") and not raw.startswith("//"):
        return raw
    if raw.startswith("http://") or raw.startswith("https://"):
        if allowed_origins is None:
            return raw  # backward-compat (ไม่มี allowlist)
        try:
            p = urlparse(raw)
            origin = f"{p.scheme}://{p.netloc}"
        except Exception:
            return ""
        return raw if origin in allowed_origins else ""
    return ""


@router.get("/passkey/recover")
async def passkey_recover_page(
    request: Request,
    return_to: str | None = None,
    db: Session = Depends(get_db),
):
    """หน้ากู้บัญชี Passkey (เสิร์ฟจาก Hub — subsystem user ใช้ได้เอง).

    backup code / email OTP → fetch /auth/passkey/recover/* same-origin.
    ไม่พึ่ง admin frontend (subsystem user อยู่บน Hub domain ตลอด).

    return_to: URL กลับไปหลังกู้สำเร็จ (ปกติคือ login page ของ subsystem)
    """
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    safe_return = _safe_return_to(return_to, _allowed_subsystem_origins(db))
    return HTMLResponse(
        content=_passkey_recover_html(nonce=nonce, return_to=safe_return)
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

    # *** เช็คสิทธิ์เข้าระบบย่อยนี้ก่อน — กันเสียเวลาตั้ง passkey ทั้งที่เข้าไม่ได้อยู่ดี ***
    # (เดิมเช็ค passkey ก่อน access_policy → user ที่ไม่มีสิทธิ์ถูกพาไปตั้ง passkey
    # เต็มขั้นตอนก่อน ถึงจะมาเจอ 403 ตอน finalize — สลับลำดับให้เช็คสิทธิ์ก่อนเสมอ)
    await _check_access_policy_or_raise(
        user=user, authreq=authreq, request=request, db=db, provider="google"
    )

    # ===== Credential setup interstitial (subsystem users รวมนักศึกษา) =====
    # ยังไม่มี factor เลย (passkey หรือ TOTP) → เสนอตั้งค่าก่อน redirect กลับ subsystem
    # (นักศึกษาเข้า Hub console ไม่ได้ — นี่คือทางเดียวที่จะตั้ง credential)
    # เคารพ "ข้ามไปก่อน" (snooze 7 วัน) + "ไม่ต้องถามอีก" (ถาวร) — ไม่บล็อกการเข้าใช้งาน
    if mfa_policy.should_prompt_setup(user, db):
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


async def _check_access_policy_or_raise(
    *,
    user: User,
    authreq: dict,
    request: Request,
    db: Session,
    provider: str,
) -> None:
    """เช็ค Access Policy — user มีสิทธิ์เข้า subsystem นี้ไหม (explicit/all/role/
    attribute + deny-list, Week 11). Raises HTTPException(403) ถ้าไม่มีสิทธิ์.

    เรียกก่อนเสมอ — ทั้งก่อนโชว์ passkey enrollment interstitial (กันเสีย
    เวลาตั้ง passkey ทั้งที่เข้าระบบย่อยนี้ไม่ได้อยู่ดี) และใน
    ``_finalize_subsystem_login`` (กัน race — สิทธิ์อาจถูกถอนระหว่างที่ user
    ตั้ง passkey อยู่).
    """
    client_ip = get_client_ip(request)
    subsystem_obj = (
        db.query(Subsystem).filter(Subsystem.id == authreq["subsystem_id"]).first()
    )
    allowed, policy_reason = evaluate_access_policy(db, user, subsystem_obj)
    if allowed:
        return
    log_action(
        db,
        actor_id=user.id,
        action="oauth_login_failed_access_policy",
        target_type="subsystem",
        target_id=authreq["subsystem_id"],
        ip=client_ip,
        metadata={
            "email": user.email,
            "user_id": str(user.id),
            "client_id": authreq["client_id"],
            "provider": provider,
            "policy": subsystem_obj.access_policy if subsystem_obj else None,
            "reason": policy_reason,
        },
    )
    db.commit()
    await emit(
        EVT_OAUTH_FAILURE,
        {
            "user_id": str(user.id),
            "client_id": authreq["client_id"],
            "reason": f"access_policy:{policy_reason}",
            "ip": client_ip,
        },
    )
    raise HTTPException(
        status_code=403,
        detail="คุณไม่มีสิทธิ์เข้าใช้งานระบบย่อยนี้ — ติดต่อ admin",
    )


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

    await _check_access_policy_or_raise(
        user=user, authreq=authreq, request=request, db=db, provider=provider
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
    geo_country, geo_city = lookup_geo(client_ip)
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
        user_agent=user_agent,
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
            login_method=provider,
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
    # รวม risk-based MFA + Always-2FA (user pref / admin) เป็น gate เดียว (mfa_policy)
    is_mfa_required = mfa_policy.is_second_factor_required(
        user,
        actual_decision=actual_decision,
        enforcing=enforcing,
        is_hard_block=is_hard_block,
        login_method=provider,
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
        # มี factor ที่สอง (passkey หรือ TOTP) → risk-stepup (รับได้ทั้งคู่);
        # ไม่มีเลย → grace / force-enroll passkey (ต้องตั้งอย่างน้อย 1)
        has_passkey = mfa_policy.has_second_factor(user, db)

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
    if not get_auth_policy(db)["passkey"]:
        raise HTTPException(
            status_code=403,
            detail="Passkey login ถูกปิดใช้งานโดยผู้ดูแลระบบ — ใช้ Google แทน",
        )
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
    mfa_always: bool = Field(
        default=False, description="ติ๊ก 'ขอยืนยันทุกครั้งที่ล็อกอิน' ในหน้า enroll"
    )


def _apply_mfa_always(user: User, enabled: bool, request: Request, db: Session) -> None:
    """เปิด Always-2FA จากหน้า enroll (ทางเดียวที่นักศึกษาตั้งค่าได้ — เข้า /account ไม่ได้).

    เปิดได้อย่างเดียว (ไม่ปิด) — การปิดต้องทำที่ /account ซึ่งต้องผ่าน step-up
    กัน attacker ที่ยึด enroll context ไปปิดการป้องกันของเหยื่อ
    """
    if not enabled or user.mfa_always:
        return
    user.mfa_always = True
    log_action(
        db,
        actor_id=user.id,
        action="account_security_updated",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"changed_by": "SELF", "mfa_always": True, "at": "interstitial"},
    )


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
    _apply_mfa_always(user, body.mfa_always, request, db)
    db.commit()
    return resp


def _credential_setup_done_html(
    *, user_email: str, has_factor: bool, nonce: str
) -> str:
    """หน้าสรุปหลังตั้ง credential แบบ standalone (ปุ่ม "เพิ่มการยืนยันตัวตน")."""
    safe_email = (
        user_email.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    icon = "✅" if has_factor else "ℹ️"
    title = "ตั้งค่าเรียบร้อย" if has_factor else "ยังไม่ได้ตั้งค่า"
    msg = (
        "บัญชีของคุณมีการยืนยันตัวตนแล้ว — ใช้เข้าระบบและกู้บัญชีได้"
        if has_factor
        else "คุณข้ามขั้นตอนนี้ไป กลับมาตั้งค่าได้ทุกเมื่อจากปุ่ม “เพิ่มการยืนยันตัวตน”"
    )
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>{title} · Central Auth Hub</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style nonce="{nonce}">
  body {{ font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:#070b14;
    color:#e8eef7; min-height:100vh; margin:0; display:grid; place-items:center; padding:32px 16px; }}
  .card {{ width:100%; max-width:420px; background:linear-gradient(180deg,#141c30,#0b1120);
    border:1px solid rgba(148,178,224,.14); border-radius:20px; padding:34px 30px; text-align:center; }}
  .ic {{ font-size:44px; margin-bottom:10px; }}
  h1 {{ font-size:21px; margin:0 0 8px; font-weight:600; }}
  p {{ color:#8a99b5; font-size:14px; line-height:1.65; margin:0 0 6px; }}
  .who {{ font-family:ui-monospace,monospace; font-size:11px; color:#34e8c4; margin-top:14px;
    word-break:break-all; }}
</style></head><body>
  <div class="card">
    <div class="ic">{icon}</div>
    <h1>{title}</h1>
    <p>{msg}</p>
    <p>ปิดหน้านี้แล้วกลับไปเข้าใช้งานระบบได้เลย</p>
    <div class="who">{safe_email}</div>
  </div>
</body></html>"""


class AlwaysMfaRequest(BaseModel):
    hub_state: str = Field(..., min_length=8, max_length=128)


@router.post("/security/always-2fa")
@limiter.limit(settings.rate_limit_token)
async def oauth_enable_always_2fa(
    request: Request,
    body: AlwaysMfaRequest,
    db: Session = Depends(get_db),
):
    """เปิด Always-2FA จากหน้า enroll โดยไม่ต้อง enroll factor ใหม่.

    ใช้เมื่อ user มี factor อยู่แล้ว (จะได้ไม่ถูกบังคับเพิ่ม passkey ซ้ำ) หรือกด
    "เปิด" ใน popup หลังตั้งค่าเสร็จ. **เปิดได้อย่างเดียว ปิดไม่ได้** (ดู
    `_apply_mfa_always`) — ต้องมี factor อยู่แล้วถึงเปิดได้ ไม่งั้นจะล็อกตัวเองออก
    """
    user = _load_enroll_user(body.hub_state, db)
    if not mfa_policy.has_second_factor(user, db):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "no_factor",
                "message": "ต้องตั้ง Passkey หรือ Authenticator อย่างน้อย 1 อย่างก่อน",
            },
        )
    _apply_mfa_always(user, True, request, db)
    db.commit()
    return {"mfa_always": True}


class EnrollTotpVerifyRequest(BaseModel):
    hub_state: str = Field(..., min_length=8, max_length=128)
    code: str = Field(..., min_length=6, max_length=8)
    mfa_always: bool = Field(
        default=False, description="ติ๊ก 'ขอยืนยันทุกครั้งที่ล็อกอิน' ในหน้า enroll"
    )


@router.post("/totp/enroll/start")
@limiter.limit(settings.rate_limit_token)
async def oauth_totp_enroll_start(
    request: Request,
    body: EnrollStartRequest,
    db: Session = Depends(get_db),
):
    """สร้าง TOTP secret + otpauth URI — ใช้ identity จาก enroll context (ไม่ต้อง JWT).

    สำหรับ subsystem users รวมนักศึกษาที่เข้า Hub console ไม่ได้ (mirror passkey enroll).
    row ถูกสร้างเป็น REGISTERED — ต้อง verify code ก่อนถึงเป็น ACTIVE.
    """
    user = _load_enroll_user(body.hub_state, db)
    secret, uri = totp_service.start_enroll(user.id, db)
    db.commit()
    # qr_svg render ฝั่ง server — หน้านี้ Hub-served + CSP บล็อก CDN (fail-safe → "")
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": totp_service.qr_svg(uri)}


@router.post("/totp/enroll/verify")
@limiter.limit(settings.rate_limit_token)
async def oauth_totp_enroll_verify(
    request: Request,
    body: EnrollTotpVerifyRequest,
    db: Session = Depends(get_db),
):
    """ยืนยัน code → TOTP ACTIVE (identity จาก enroll context)."""
    user = _load_enroll_user(body.hub_state, db)
    if not totp_service.confirm_enroll(user.id, body.code, db):
        log_action(
            db,
            actor_id=user.id,
            action="totp_enroll_failed",
            target_type="user",
            target_id=user.id,
            ip=get_client_ip(request),
            metadata={"at": "interstitial"},
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail={"code": "totp_invalid", "message": "รหัสไม่ถูกต้อง"},
        )
    log_action(
        db,
        actor_id=user.id,
        action="totp_enabled",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"at": "interstitial"},
    )
    _apply_mfa_always(user, body.mfa_always, request, db)
    db.commit()
    return {"enabled": True, "status": "ACTIVE"}


@router.get("/continue")
async def oauth_continue(
    request: Request,
    hub_state: str,
    action: str | None = None,
    db: Session = Depends(get_db),
):
    """หลัง interstitial (ตั้ง credential / ข้าม / ไม่ถามอีก) → authorization code + redirect.

    `action`:
      - `skip`  → snooze 7 วัน (เตือนใหม่รอบหน้า)
      - `never` → ไม่ถามอีกถาวร (`security_onboarding_dismissed`)
      - อื่นๆ/ไม่ส่ง → ตั้งค่าสำเร็จแล้ว ไม่ต้องแตะ flag

    ใช้ identity จาก enroll context → _finalize_subsystem_login (access_list, RBA,
    block, authcode เหมือน flow ปกติ).
    """
    raw = redis_client.get(f"authreq:{hub_state}")
    user = _load_enroll_user(hub_state, db)
    # standalone setup (ปุ่ม "เพิ่มการยืนยันตัวตน") — ไม่มี authreq เพราะไม่ได้มาจาก
    # subsystem OAuth flow → จบที่หน้า "เสร็จแล้ว" แทน redirect กลับ subsystem
    standalone = raw is None
    authreq = json.loads(raw) if raw else None

    if action == "skip":
        mfa_policy.snooze_onboarding(user)
        log_action(
            db,
            actor_id=user.id,
            action="security_onboarding_snoozed",
            target_type="user",
            target_id=user.id,
            ip=get_client_ip(request),
            metadata={"days": mfa_policy.ONBOARDING_SNOOZE_DAYS, "at": "interstitial"},
        )
        db.commit()
    elif action == "never":
        user.security_onboarding_dismissed = True
        log_action(
            db,
            actor_id=user.id,
            action="security_onboarding_dismissed",
            target_type="user",
            target_id=user.id,
            ip=get_client_ip(request),
            metadata={"at": "interstitial"},
        )
        db.commit()

    if standalone:
        # ไม่มี OAuth request ค้าง — จบที่หน้าสรุปผล (ไม่ออก JWT / ไม่แตะ session)
        has_factor = mfa_policy.has_second_factor(user, db)
        redis_client.delete(f"enroll:{hub_state}")
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        return HTMLResponse(
            content=_credential_setup_done_html(
                user_email=user.email, has_factor=has_factor, nonce=nonce
            )
        )

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
        "user_type": user.user_type,
        "role_in_subsystem": user.user_type,  # transition alias
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

    # 3. ปิด *ทุก* LoginSession ที่ยัง active (logout_at IS NULL)
    # subsystem มี session cookie ได้ทีละหนึ่ง — logout ครั้งเดียวต้องล้าง zombie
    # ที่เกิดจาก re-auth (OAuth ทำ session ใหม่ทุกครั้งโดยไม่ปิดอันเก่า)
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz

    sessions = (
        db.query(LoginSession)
        .filter(
            LoginSession.user_id == user.id,
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.logout_at.is_(None),
        )
        .order_by(LoginSession.created_at.desc())
        .all()
    )
    closed_ids: list[str] = []
    revoked_jti_count = 0
    now = _dt.utcnow()
    for sess in sessions:
        sess.logout_at = now
        closed_ids.append(str(sess.id))
        if sess.jti:
            exp_unix = int(
                (
                    sess.created_at.replace(tzinfo=_tz.utc)
                    + _td(minutes=settings.jwt_access_token_expire_minutes)
                ).timestamp()
            )
            if revoke_jti(sess.jti, exp_unix):
                revoked_jti_count += 1

    log_action(
        db,
        actor_id=user.id,
        action="subsystem_logout",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "sessions_closed": len(closed_ids),
            "session_ids": closed_ids,
            "jti_revoked": revoked_jti_count,
        },
    )
    db.commit()
    return {
        "status": "ok",
        "sessions_closed": len(closed_ids),
        "jti_revoked": revoked_jti_count,
    }


# ============ Passkey enrollment interstitial (E) ============


def _passkey_enroll_html(
    hub_state: str,
    subsystem_name: str,
    user_email: str,
    nonce: str,
    has_passkey: bool = False,
    has_totp: bool = False,
    mfa_always: bool = False,
) -> str:
    """หน้า "เพิ่มการยืนยันตัวตน" หลัง Google login.

    ขั้นตอน:
      - **มี factor อยู่แล้ว** → ขั้น "จัดการ" (เห็นสถานะ + เปิด Always-2FA ได้ทันที
        โดยไม่ต้องเพิ่ม factor ซ้ำ + เลือกเพิ่มอีกวิธีได้)
      - **ยังไม่มี factor** → ขั้น "เลือกวิธี" → ขั้น "ตั้งค่า"
        ตั้งเสร็จแล้วถ้ายังไม่ได้ติ๊ก Always-2FA → **popup ถามอีกครั้ง**

    รองรับทุก user รวมนักศึกษา (เข้า Hub console ไม่ได้ — นี่คือทางเดียว).
    "ข้ามไปก่อน" (snooze 7 วัน) + "ไม่ต้องถามอีก" (ถาวร) — ไม่บังคับ (opt-in).
    Passkey แรก → แสดง backup codes (must save).
    """
    safe_name = (
        subsystem_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    safe_email = (
        user_email.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    has_factor = has_passkey or has_totp
    first_step = "stepManage" if has_factor else "stepChoose"
    pk_state = "✓ ตั้งค่าแล้ว" if has_passkey else "ยังไม่ได้ตั้ง"
    totp_state = "✓ ตั้งค่าแล้ว" if has_totp else "ยังไม่ได้ตั้ง"
    always_row = (
        '<div class="done-row">✓ เปิด "ขอยืนยันทุกครั้งที่ล็อกอิน" อยู่แล้ว</div>'
        if mfa_always
        else """<button class="btn btn-go" id="enableAlways">
        เปิด "ขอยืนยันทุกครั้งที่ล็อกอิน"</button>"""
    )
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>เพิ่มการยืนยันตัวตน · {safe_name}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style nonce="{nonce}">
  :root {{ --navy:#0b1420; --ink:#132033; --muted:#68788d; --line:#d7e0e7; --paper:#fff;
           --canvas:#f1f5f7; --teal:#18b99c; --teal-dark:#087a68; --danger:#a2163a; --amber:#8a5a0a; }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; }}
  body {{ font-family:'Sarabun',system-ui,sans-serif; background:var(--canvas); color:var(--ink);
    min-height:100svh; display:flex; flex-direction:column; }}
  strong,b {{ font-weight:600; }} h1,h2,h3 {{ font-weight:700; }}

  .topbar {{ min-height:54px; flex:none; display:flex; align-items:center; justify-content:space-between;
    gap:24px; padding:0 clamp(16px,3vw,40px); background:var(--navy); color:#fff; border-bottom:1px solid #263547; }}
  .brand {{ display:inline-flex; align-items:center; gap:12px; color:inherit; text-decoration:none; }}
  .brand > .logo {{ width:36px; height:36px; display:grid; place-items:center; border:1px solid #2ac7aa;
    background:#0d2a2b; color:#43dfc2; font:500 15px 'IBM Plex Mono',monospace; }}
  .brand strong {{ display:block; font:600 15px 'Sarabun',sans-serif; }}
  .brand small {{ display:block; margin-top:2px; color:#7f91a7; font:500 10px 'IBM Plex Mono',monospace; letter-spacing:.15em; }}
  .secure {{ display:flex; align-items:center; gap:8px; color:#9fb0c3; font:500 11px 'IBM Plex Mono',monospace; letter-spacing:.08em; }}
  .secure i {{ width:8px; height:8px; border-radius:50%; background:#38d7b9; box-shadow:0 0 0 4px rgba(56,215,185,.12); }}

  .shell {{ width:min(1180px,calc(100% - 36px)); flex:1; min-height:0; display:grid;
    grid-template-columns:minmax(300px,.72fr) minmax(520px,1.5fr); margin:14px auto;
    border:1px solid #cfd9e1; background:var(--paper); box-shadow:0 18px 50px rgba(16,31,48,.08); overflow:hidden; }}

  .context {{ min-width:0; display:flex; flex-direction:column; padding:clamp(20px,2.4vw,36px);
    border-top:3px solid var(--teal); color:#f3f7fa;
    background:radial-gradient(circle at 90% 10%,rgba(26,182,157,.14),transparent 35%),linear-gradient(160deg,var(--navy) 0%,#111d2b 70%,#0c2528 100%); }}
  .eyebrow {{ display:block; color:#6f849b; font:500 11px/1.4 'IBM Plex Mono',monospace; letter-spacing:.16em; }}
  .context h1 {{ max-width:520px; margin:10px 0 8px; font:800 clamp(22px,1.9vw,32px)/1.22 'Sarabun',sans-serif; letter-spacing:-.025em; }}
  .lead {{ max-width:510px; margin:0; color:#9bacc0; font-size:13px; line-height:1.6; }}
  .who {{ margin-top:12px; font:500 12px 'IBM Plex Mono',monospace; color:#43dfc2; word-break:break-all; }}
  .steps {{ list-style:none; margin:auto 0; padding:20px 0; }}
  .steps li {{ position:relative; min-height:58px; display:grid; grid-template-columns:38px 1fr; align-items:start; gap:16px; color:#65798f; }}
  .steps li:not(:last-child)::after {{ content:""; position:absolute; left:15px; top:34px; width:1px; height:22px; background:#2b3b4e; }}
  .steps li > span {{ width:30px; height:30px; display:grid; place-items:center; border:1px solid #324356; color:#7d90a6; font:500 11px 'IBM Plex Mono',monospace; }}
  .steps strong {{ display:block; margin-top:2px; font-size:13.5px; }}
  .steps small {{ display:block; margin-top:2px; font-size:11.5px; }}
  .steps li.on {{ color:#f4f8fb; }}
  .steps li.on > span {{ border-color:var(--teal); background:rgba(24,185,156,.13); color:#42dfc2; }}
  .note-box {{ display:flex; align-items:flex-start; gap:10px; padding-top:14px; border-top:1px solid #29394b; }}
  .note-box > span {{ width:24px; height:24px; flex:none; display:grid; place-items:center; border:1px solid #3f566c; border-radius:50%; color:#83a0b9; font:500 12px 'IBM Plex Mono',monospace; }}
  .note-box p {{ margin:0; color:#73879c; font-size:12.5px; line-height:1.55; }}
  .note-box strong {{ display:block; margin-bottom:2px; color:#a8b7c6; font-size:13px; }}

  .workspace {{ min-width:0; display:flex; flex-direction:column; background:#fff; }}
  .ws-head {{ min-height:72px; flex:none; display:flex; align-items:center; justify-content:space-between; gap:24px; padding:14px clamp(20px,2.4vw,34px); border-bottom:1px solid var(--line); }}
  .ws-head h2 {{ margin:3px 0 0; font:800 clamp(18px,1.5vw,23px)/1.25 'Sarabun',sans-serif; }}
  .ws-badge {{ flex:none; padding:8px 10px; border:1px solid #a8ded4; background:#effaf7; color:var(--teal-dark); font:500 11px 'IBM Plex Mono',monospace; letter-spacing:.08em; }}
  .ws-body {{ flex:1; min-height:0; overflow-y:auto; padding:clamp(20px,2.4vw,32px); }}
  .ws-body-inner {{ width:100%; max-width:560px; margin:0 auto; }}

  .err {{ display:none; align-items:flex-start; gap:10px; margin-bottom:14px; padding:9px 12px; border:1px solid #efb6c4; background:#fff2f5; color:var(--danger); font-size:13px; line-height:1.5; }}
  .err.show {{ display:flex; }}
  .note {{ display:none; margin-bottom:14px; padding:9px 12px; border-left:3px solid var(--amber); background:#fff8ec; color:#7c5312; font-size:12.5px; line-height:1.55; }}
  .note.show {{ display:block; }}

  .opt {{ width:100%; display:grid; grid-template-columns:34px 1fr auto; align-items:center; gap:13px; text-align:left;
    padding:14px 15px; margin-bottom:10px; cursor:pointer; background:#f6f8fa; border:1px solid var(--line); color:var(--ink); font-family:inherit; transition:border-color .15s,background .15s; }}
  .opt:hover {{ border-color:#8cd7c9; background:#eefaf6; }}
  .opt .ic {{ width:34px; height:34px; display:grid; place-items:center; border:1px solid #cbd6df; background:#fff; color:var(--teal-dark); }}
  .opt .ic svg {{ width:20px; height:20px; }}
  .opt .t {{ font:600 14.5px 'Sarabun',sans-serif; display:flex; align-items:center; gap:8px; margin-bottom:2px; }}
  .opt .d {{ font-size:12px; color:var(--muted); line-height:1.5; }}
  .opt .arrow {{ color:#9fb0c3; font:500 18px 'IBM Plex Mono',monospace; }}
  .tag {{ font:500 9.5px 'IBM Plex Mono',monospace; letter-spacing:.04em; padding:2px 7px; background:#eaf9f5; color:var(--teal-dark); border:1px solid #a8ded4; }}

  .status {{ border:1px solid var(--line); margin-bottom:14px; }}
  .st-row {{ display:flex; justify-content:space-between; align-items:center; padding:12px 14px; font-size:13.5px; }}
  .st-row + .st-row {{ border-top:1px solid var(--line); }}
  .st-row b {{ font:500 11.5px 'IBM Plex Mono',monospace; color:var(--teal-dark); }}
  .done-row {{ padding:13px 14px; margin-bottom:12px; font-size:13px; background:#f0faf7; border:1px solid #b8ddd5; color:var(--teal-dark); }}
  .opt-sm {{ margin-top:2px; }}

  .always {{ display:flex; gap:11px; align-items:flex-start; margin-top:14px; padding:13px 14px; cursor:pointer; background:#f6f8fa; border:1px solid var(--line); }}
  .always:hover {{ border-color:#c2ccd5; }}
  .always input {{ width:17px; height:17px; margin:1px 0 0; accent-color:var(--teal-dark); flex:none; cursor:pointer; }}
  .always b {{ display:block; font:600 13.5px 'Sarabun',sans-serif; margin-bottom:2px; }}
  .always .d {{ display:block; font-size:12px; color:var(--muted); line-height:1.5; }}

  .skips {{ display:flex; gap:10px; margin-top:16px; padding-top:16px; border-top:1px solid var(--line); }}
  .skips a {{ flex:1; text-align:center; padding:11px 8px; font-size:13px; text-decoration:none; color:var(--muted); border:1px solid var(--line); transition:color .15s,border-color .15s; }}
  .skips a:hover {{ color:var(--ink); border-color:#b6c1cc; }}

  .step {{ display:none; }}
  .step.on {{ display:block; }}
  .back {{ display:inline-flex; align-items:center; gap:6px; background:none; border:none; color:var(--muted); font-family:inherit; font-size:13px; cursor:pointer; padding:0; margin-bottom:16px; }}
  .back:hover {{ color:var(--ink); }}
  .fld {{ display:block; font-size:12.5px; color:#405168; font-weight:500; margin-bottom:7px; }}
  input[type=text] {{ width:100%; min-height:44px; padding:10px 13px; margin-bottom:14px; background:#fff; border:1px solid #c8d3dc; color:var(--ink); font-family:inherit; font-size:14.5px; outline:none; }}
  input[type=text]:focus {{ border-color:var(--teal); box-shadow:0 0 0 3px rgba(24,185,156,.1); }}
  .btn {{ display:flex; align-items:center; justify-content:center; gap:9px; width:100%; min-height:46px; padding:0 16px; font:500 15px 'Sarabun',sans-serif; border:1px solid transparent; cursor:pointer; text-decoration:none; }}
  .btn-go {{ color:#061c18; background:var(--teal); border-color:#07907a; }}
  .btn-go:hover {{ background:#38d0b4; }}
  .btn-go[disabled] {{ background:#e5e9ed; border-color:#d8dee4; color:#94a0ad; cursor:not-allowed; }}

  .qr {{ background:#fff; padding:11px; margin:4px auto 12px; width:186px; height:186px; border:1px solid var(--line); }}
  .qr svg {{ display:block; width:100%; height:100%; }}
  .hint {{ font-size:12.5px; color:var(--muted); text-align:center; line-height:1.6; margin:0 0 6px; }}
  .secret {{ font:500 11.5px 'IBM Plex Mono',monospace; color:var(--teal-dark); word-break:break-all; text-align:center; display:block; margin-bottom:14px; }}
  #totpCode {{ font-family:'IBM Plex Mono',monospace; font-size:20px; letter-spacing:.42em; text-align:center; }}
  .spinner {{ width:15px; height:15px; border:2px solid rgba(6,28,24,.3); border-top-color:#061c18; border-radius:50%; animation:spin .7s linear infinite; }}
  @keyframes spin {{ to{{transform:rotate(360deg)}} }}

  .pagefoot {{ min-height:34px; flex:none; display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:20px; padding:0 clamp(16px,3vw,40px); border-top:1px solid #d8e0e6; color:#79889a; font:500 10px 'IBM Plex Mono',monospace; letter-spacing:.05em; }}
  .pagefoot span:last-child {{ text-align:right; }}

  .modal {{ display:none; position:fixed; inset:0; z-index:5; background:rgba(9,17,28,.55); backdrop-filter:blur(4px); place-items:center; padding:24px 16px; }}
  .modal.show {{ display:grid; }}
  .modal-card {{ width:100%; max-width:430px; background:#fff; border:1px solid var(--line); overflow:hidden; max-height:92vh; overflow-y:auto; box-shadow:0 24px 60px rgba(16,31,48,.25); }}
  .modal-h {{ padding:22px 26px 0; }}
  .modal-h h2 {{ font:800 18px 'Sarabun',sans-serif; margin:0 0 4px; }}
  .modal-b {{ padding:14px 26px 22px; }}
  .codes {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:6px 0 14px; }}
  .code {{ font:500 13.5px 'IBM Plex Mono',monospace; letter-spacing:.05em; background:#f7f9fa; border:1px solid #cdd7df; padding:9px 10px; color:var(--ink); text-align:center; }}
  .warn {{ font-size:12px; color:#7c5312; background:#fff8ec; border:1px solid #ecd9b0; padding:10px 12px; margin-bottom:12px; }}
  .row {{ display:flex; gap:8px; margin-bottom:12px; }}
  .row .btn {{ font-size:13px; min-height:42px; }}
  .btn-mini {{ background:#172436; border-color:#27384b; color:#fff; }}
  .btn-mini:hover {{ background:#23344a; }}
  .btn-mini.done {{ background:#eaf9f5; border-color:#70c9b8; color:var(--teal-dark); }}
  .ack {{ display:flex; gap:9px; align-items:flex-start; font-size:12.5px; color:#31475b; padding:8px 0; cursor:pointer; }}
  .ack input {{ width:auto; margin:2px 0 0; accent-color:var(--teal-dark); }}
  .sub {{ color:var(--muted); font-size:13px; line-height:1.55; }}

  @media (max-width:900px) {{
    .shell {{ grid-template-columns:1fr; width:100%; margin:0; border:0; box-shadow:none; }}
    .steps,.note-box {{ display:none; }}
    .pagefoot {{ display:none; }}
  }}
</style></head><body>
<header class="topbar">
  <a class="brand" href="/">
    <span class="logo">H</span>
    <span><strong>Central Auth Hub</strong><small>IDENTITY CONTROL</small></span>
  </a>
  <div class="secure"><i></i> SECURE SETUP SESSION</div>
</header>
<div class="shell">
  <aside class="context">
    <div>
      <span class="eyebrow">ACCOUNT SECURITY</span>
      <h1>เพิ่มความปลอดภัย<br>ให้บัญชี</h1>
      <p class="lead">เลือกวิธียืนยันตัวตนอีกชั้นเมื่อเข้าใช้ {safe_name} — ป้องกันบัญชีแม้รหัส Google หลุด ตั้งครั้งเดียว ใช้ได้ตลอด</p>
      <div class="who">{safe_email}</div>
    </div>
    <ol class="steps">
      <li class="on"><span>01</span><div><strong>เลือกวิธียืนยัน</strong><small>Passkey หรือ Authenticator</small></div></li>
      <li><span>02</span><div><strong>ตั้งค่าอุปกรณ์</strong><small>ยืนยันด้วยอุปกรณ์นี้</small></div></li>
      <li><span>03</span><div><strong>เสร็จสิ้น</strong><small>เข้าใช้งานต่อได้ทันที</small></div></li>
    </ol>
    <div class="note-box"><span>i</span><p><strong>ไม่มีรหัสผ่านถูกจัดเก็บในหน้านี้</strong>ใช้อุปกรณ์ของคุณยืนยันตัวตนโดยตรง (WebAuthn / TOTP)</p></div>
  </aside>
  <section class="workspace">
    <header class="ws-head">
      <div><span class="eyebrow">PASSKEY / TOTP SETUP</span><h2>เพิ่มการยืนยันตัวตน</h2></div>
      <span class="ws-badge">SETUP · ACTIVE</span>
    </header>
    <div class="ws-body"><div class="ws-body-inner">
      <div class="err" id="err"></div>

      <div class="step" id="stepManage">
        <div class="status">
          <div class="st-row"><span>Passkey</span><b>{pk_state}</b></div>
          <div class="st-row"><span>Authenticator</span><b>{totp_state}</b></div>
        </div>
        {always_row}
        <button class="opt opt-sm" id="addMore">
          <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5v14"/></svg></span>
          <span><span class="t">เพิ่มอีกวิธี</span><span class="d">มีหลายวิธีสำรองไว้ ปลอดภัยกว่า</span></span>
          <span class="arrow">›</span>
        </button>
        <div class="skips"><a href="/oauth/continue?hub_state={hub_state}">เสร็จแล้ว</a></div>
      </div>

      <div class="step" id="stepChoose">
        <button class="opt" id="pickPasskey">
          <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 8.3-8.3"/><path d="m17 5 3 3"/><path d="m14 8 3 3"/></svg></span>
          <span><span class="t">Passkey <span class="tag">แนะนำ</span></span>
          <span class="d">ลายนิ้วมือ / ใบหน้า / PIN ของเครื่องนี้ — ปลอดภัยที่สุด</span></span>
          <span class="arrow">›</span>
        </button>
        <button class="opt" id="pickTotp">
          <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20"/><path d="M11 18h2"/></svg></span>
          <span><span class="t">แอป Authenticator</span>
          <span class="d">รหัส 6 หลักจากแอป — ใช้ได้ทุกอุปกรณ์ แม้เครื่องไม่รองรับ Passkey</span></span>
          <span class="arrow">›</span>
        </button>
        <div class="note" id="unsupported">เบราว์เซอร์นี้ไม่รองรับ Passkey — แนะนำให้ใช้ <b>แอป Authenticator</b></div>
        <label class="always" for="alwaysChk">
          <input type="checkbox" id="alwaysChk">
          <span><b>ขอยืนยันตัวตนทุกครั้งที่ล็อกอิน</b><span class="d">ปลอดภัยขึ้น — ปกติระบบจะขอเฉพาะตอนพบความเสี่ยง</span></span>
        </label>
        <div class="skips">
          <a href="/oauth/continue?hub_state={hub_state}&amp;action=skip">ข้ามไปก่อน</a>
          <a href="/oauth/continue?hub_state={hub_state}&amp;action=never">ไม่ต้องถามอีก</a>
        </div>
      </div>

      <div class="step" id="stepPasskey">
        <button class="back" data-back>‹ เลือกวิธีอื่น</button>
        <label class="fld" for="dev">ตั้งชื่ออุปกรณ์นี้</label>
        <input type="text" id="dev" value="อุปกรณ์ของฉัน" maxlength="100">
        <button class="btn btn-go" id="setup">ตั้งค่า Passkey</button>
      </div>

      <div class="step" id="stepTotp">
        <button class="back" data-back>‹ เลือกวิธีอื่น</button>
        <div class="qr" id="qr"></div>
        <p class="hint">สแกน QR ด้วยแอป Authenticator<br>(Google Authenticator, Microsoft Authenticator ฯลฯ)</p>
        <code class="secret" id="secretTxt"></code>
        <label class="fld" for="totpCode">กรอกรหัส 6 หลักจากแอป</label>
        <input type="text" id="totpCode" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="000000">
        <button class="btn btn-go" id="totpVerify">ยืนยันรหัส</button>
      </div>
    </div></div>
  </section>
</div>
<footer class="pagefoot"><span>Central Auth Hub</span><span>WebAuthn · FIDO2 · TOTP RFC 6238</span><span>{safe_name}</span></footer>

<div class="modal" id="alwaysModal">
  <div class="modal-card">
    <div class="modal-h">
      <h2>ตั้งค่าเรียบร้อย</h2>
      <p class="sub">ต้องการให้ระบบ<b>ขอยืนยันตัวตนทุกครั้ง</b>ที่ล็อกอินไหม?</p>
    </div>
    <div class="modal-b">
      <p class="hint" style="text-align:left">
        ปกติระบบจะขอยืนยันเฉพาะตอนพบความเสี่ยง (เช่น เข้าจากประเทศใหม่)<br>
        เปิดตัวเลือกนี้ = ขอทุกครั้ง ปลอดภัยขึ้นแต่ช้าลงเล็กน้อย
      </p>
      <button class="btn btn-go" id="alwaysYes">เปิด — ขอทุกครั้ง</button>
      <button class="btn btn-mini" id="alwaysNo" style="margin-top:9px">
        ไม่ต้อง — ขอเฉพาะตอนเสี่ยง</button>
    </div>
  </div>
</div>

<div class="modal" id="bcModal">
  <div class="modal-card">
    <div class="modal-h"><h2>Backup Codes</h2>
      <p class="sub">บันทึกไว้กู้บัญชีถ้าทำอุปกรณ์หาย — แสดงครั้งเดียว</p></div>
    <div class="modal-b">
      <div class="warn">แต่ละ code ใช้ได้ครั้งเดียว เก็บในที่ปลอดภัย</div>
      <div class="codes" id="codes"></div>
      <div class="row">
        <button class="btn btn-mini" id="copyBtn">คัดลอก</button>
        <button class="btn btn-mini" id="dlBtn">ดาวน์โหลด</button>
      </div>
      <label class="ack"><input type="checkbox" id="ackChk"><span>ฉันบันทึก backup codes ไว้แล้ว</span></label>
      <button class="btn btn-go" id="bcContinue" disabled>เข้าสู่ระบบต่อ</button>
    </div>
  </div>
</div>

<script nonce="{nonce}">
const HUB_STATE = {json.dumps(hub_state)};
const CONTINUE_URL = '/oauth/continue?hub_state=' + encodeURIComponent(HUB_STATE);
const errEl = document.getElementById('err');
function showErr(m){{ errEl.textContent = m; errEl.classList.add('show'); }}
function clearErr(){{ errEl.classList.remove('show'); }}
function b64urlToBuf(s) {{ const p=s.replace(/-/g,'+').replace(/_/g,'/');
  const pad=p.length%4===0?'':'='.repeat(4-(p.length%4)); const bin=atob(p+pad);
  const a=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i); return a.buffer; }}
function bufToB64url(buf) {{ const a=new Uint8Array(buf); let b='';
  for(let i=0;i<a.length;i++)b+=String.fromCharCode(a[i]);
  return btoa(b).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,''); }}
function pkSupported() {{ return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.create); }}
// ติ๊กไว้ที่ขั้นเลือกวิธี → ส่งไปพร้อมตอนตั้งค่าสำเร็จ (เปิด Always-2FA)
function wantAlways() {{ return !!document.getElementById('alwaysChk').checked; }}

const HAS_FACTOR = {str(has_factor).lower()};
const ALREADY_ALWAYS = {str(mfa_always).lower()};

// ── สลับขั้น ──
function show(id) {{
  clearErr();
  ['stepManage','stepChoose','stepPasskey','stepTotp'].forEach(s =>
    document.getElementById(s).classList.toggle('on', s === id));
}}
show({json.dumps(first_step)});
document.querySelectorAll('[data-back]').forEach(b =>
  b.addEventListener('click', () => show('stepChoose')));

// ── ขั้นจัดการ: เปิด Always-2FA โดยไม่ต้องเพิ่ม factor ซ้ำ ──
const enableAlways = document.getElementById('enableAlways');
if (enableAlways) {{
  enableAlways.addEventListener('click', async () => {{
    clearErr();
    enableAlways.disabled = true;
    enableAlways.innerHTML = '<span class="spinner"></span> กำลังบันทึก…';
    try {{
      const r = await fetch('/oauth/security/always-2fa', {{method:'POST',
        headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{hub_state:HUB_STATE}})}});
      if(!r.ok) {{ const e = await r.json().catch(()=>({{}})); const d = e.detail;
        throw new Error(typeof d==='string' ? d : (d&&d.message ? d.message : 'บันทึกไม่สำเร็จ')); }}
      enableAlways.outerHTML =
        '<div class="done-row">✓ เปิด "ขอยืนยันทุกครั้งที่ล็อกอิน" แล้ว</div>';
    }} catch(err) {{ showErr(err.message || 'บันทึกไม่สำเร็จ');
      enableAlways.disabled = false;
      enableAlways.textContent = 'เปิด "ขอยืนยันทุกครั้งที่ล็อกอิน"'; }}
  }});
}}
const addMore = document.getElementById('addMore');
if (addMore) addMore.addEventListener('click', () => show('stepChoose'));

// ── หลังตั้งค่าสำเร็จ: ถาม Always-2FA ถ้ายังไม่ได้ติ๊ก/ยังไม่เปิด ──
function afterEnroll() {{
  if (ALREADY_ALWAYS || wantAlways()) {{ window.location.href = CONTINUE_URL; return; }}
  document.getElementById('alwaysModal').classList.add('show');
}}
document.getElementById('alwaysNo').addEventListener('click',
  () => {{ window.location.href = CONTINUE_URL; }});
document.getElementById('alwaysYes').addEventListener('click', async (e) => {{
  const b = e.currentTarget;
  b.disabled = true; b.innerHTML = '<span class="spinner"></span> กำลังบันทึก…';
  try {{
    await fetch('/oauth/security/always-2fa', {{method:'POST',
      headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{hub_state:HUB_STATE}})}});
  }} catch(err) {{ /* fail-safe — ตั้ง factor สำเร็จแล้ว อย่าขวางการเข้าระบบ */ }}
  window.location.href = CONTINUE_URL;
}});

if(!pkSupported()) document.getElementById('unsupported').classList.add('show');

// ── เลือก Passkey ──
document.getElementById('pickPasskey').addEventListener('click', () => {{
  if(!pkSupported()) {{ showErr('เบราว์เซอร์นี้ไม่รองรับ Passkey — กรุณาใช้แอป Authenticator แทน'); return; }}
  show('stepPasskey');
  document.getElementById('dev').focus();
}});

// ── เลือก Authenticator → ขอ secret + QR ──
const pickTotp = document.getElementById('pickTotp');
pickTotp.addEventListener('click', async () => {{
  clearErr();
  const original = pickTotp.innerHTML;
  pickTotp.disabled = true;
  try {{
    const r = await fetch('/oauth/totp/enroll/start', {{method:'POST',
      headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{hub_state:HUB_STATE}})}});
    if(!r.ok) {{ const e = await r.json().catch(()=>({{}}));
      throw new Error(typeof e.detail==='string' ? e.detail : 'เริ่มไม่สำเร็จ'); }}
    const d = await r.json();
    const qrEl = document.getElementById('qr');
    if (d.qr_svg) {{ qrEl.innerHTML = d.qr_svg; }}
    else {{ qrEl.style.display = 'none'; }}
    document.getElementById('secretTxt').textContent = d.secret;
    show('stepTotp');
    document.getElementById('totpCode').focus();
  }} catch(err) {{ showErr(err.message || 'เริ่มไม่สำเร็จ'); }}
  finally {{ pickTotp.disabled = false; pickTotp.innerHTML = original; }}
}});

// ── ตั้งค่า Passkey ──
const setup = document.getElementById('setup');
setup.addEventListener('click', async () => {{
  clearErr();
  const dev = (document.getElementById('dev').value || '').trim() || 'อุปกรณ์ของฉัน';
  setup.disabled = true; setup.innerHTML = '<span class="spinner"></span> กำลังตั้งค่า…';
  try {{
    const s = await fetch('/oauth/passkey/enroll/start', {{method:'POST',
      headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{hub_state:HUB_STATE}})}});
    if(!s.ok) {{ const e = await s.json().catch(()=>({{}}));
      throw new Error(typeof e.detail==='string' ? e.detail : 'เริ่มไม่สำเร็จ'); }}
    const opts = await s.json();
    opts.challenge = b64urlToBuf(opts.challenge);
    opts.user.id = b64urlToBuf(opts.user.id);
    (opts.excludeCredentials||[]).forEach(c => c.id = b64urlToBuf(c.id));
    let cred;
    try {{ cred = await navigator.credentials.create({{publicKey:opts}}); }}
    catch(ce) {{ throw new Error('การตั้งค่าถูกยกเลิก หรืออุปกรณ์ไม่รองรับ'); }}
    if(!cred) throw new Error('ไม่ได้รับข้อมูลจากอุปกรณ์');
    const resp = cred.response;
    const payload = {{ id:cred.id, rawId:bufToB64url(cred.rawId), type:cred.type,
      authenticatorAttachment:cred.authenticatorAttachment,
      response:{{ attestationObject:bufToB64url(resp.attestationObject),
        clientDataJSON:bufToB64url(resp.clientDataJSON),
        transports:resp.getTransports?resp.getTransports():[] }},
      clientExtensionResults:cred.getClientExtensionResults?cred.getClientExtensionResults():{{}} }};
    const f = await fetch('/oauth/passkey/enroll/finish', {{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{hub_state:HUB_STATE, device_name:dev, credential:payload,
        mfa_always:wantAlways()}})}});
    if(!f.ok) {{ const e = await f.json().catch(()=>({{}})); const d = e.detail;
      throw new Error(typeof d==='string' ? d : (d&&d.code ? d.code : 'ตั้งค่าไม่สำเร็จ')); }}
    const data = await f.json();
    if(data.backup_codes && data.backup_codes.length) showBackupCodes(data.backup_codes);
    else afterEnroll();
  }} catch(err) {{ showErr(err.message || 'ตั้งค่าไม่สำเร็จ');
    setup.disabled = false; setup.textContent = '🔑 ตั้งค่า Passkey'; }}
}});

// ── ยืนยันรหัส TOTP ──
const totpVerify = document.getElementById('totpVerify');
const totpCode = document.getElementById('totpCode');
async function doTotpVerify() {{
  clearErr();
  const code = (totpCode.value || '').trim();
  if(code.length < 6) {{ showErr('กรอกรหัส 6 หลัก'); return; }}
  totpVerify.disabled = true; totpVerify.innerHTML = '<span class="spinner"></span> กำลังตรวจสอบ…';
  try {{
    const r = await fetch('/oauth/totp/enroll/verify', {{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{hub_state:HUB_STATE, code:code, mfa_always:wantAlways()}})}});
    if(!r.ok) {{ const e = await r.json().catch(()=>({{}})); const d = e.detail;
      throw new Error(typeof d==='string' ? d : (d&&d.message ? d.message : 'รหัสไม่ถูกต้อง')); }}
    afterEnroll();
  }} catch(err) {{ showErr(err.message || 'ยืนยันไม่สำเร็จ');
    totpVerify.disabled = false; totpVerify.textContent = 'ยืนยันรหัส';
    totpCode.value = ''; totpCode.focus(); }}
}}
totpVerify.addEventListener('click', doTotpVerify);
totpCode.addEventListener('keydown', e => {{ if(e.key === 'Enter') doTotpVerify(); }});

// ── backup codes modal ──
function showBackupCodes(codes) {{
  document.getElementById('codes').innerHTML =
    codes.map(c => '<div class="code">' + c + '</div>').join('');
  document.getElementById('bcModal').classList.add('show');
  const txt = codes.join('\\n');
  let saved = false;
  const chk = document.getElementById('ackChk'), cont = document.getElementById('bcContinue');
  const copyBtn = document.getElementById('copyBtn'), dlBtn = document.getElementById('dlBtn');
  function refresh() {{ cont.disabled = !(saved && chk.checked); }}
  copyBtn.addEventListener('click', async () => {{
    try {{ await navigator.clipboard.writeText(txt); }} catch(e) {{}}
    copyBtn.classList.add('done'); copyBtn.textContent = '✓ คัดลอกแล้ว'; saved = true; refresh(); }});
  dlBtn.addEventListener('click', () => {{
    const b = new Blob(['Central Auth Hub — Backup Codes\\n\\n' + txt + '\\n'], {{type:'text/plain'}});
    const u = URL.createObjectURL(b); const a = document.createElement('a');
    a.href = u; a.download = 'passkey-backup-codes.txt'; a.click(); URL.revokeObjectURL(u);
    dlBtn.classList.add('done'); dlBtn.textContent = '✓ ดาวน์โหลดแล้ว'; saved = true; refresh(); }});
  chk.addEventListener('change', refresh);
  cont.addEventListener('click', () => {{
    document.getElementById('bcModal').classList.remove('show');
    afterEnroll();  // เก็บ backup codes เสร็จ → ค่อยถาม Always-2FA
  }});
}}
</script>
</body></html>"""


# ============ Passkey recovery page (Hub-served) ============


def _passkey_recover_html(nonce: str, return_to: str = "") -> str:
    """หน้ากู้บัญชี Passkey — backup code / email OTP. เสิร์ฟจาก Hub.

    fetch /auth/passkey/recover/* same-origin (localhost:8000). subsystem user
    ใช้ได้โดยไม่ต้องเข้า admin frontend.

    return_to: ถ้ามี — โชว์ปุ่ม "← กลับหน้า login ของระบบย่อย" หลังกู้สำเร็จ
    """
    import json as _json

    return_to_js = _json.dumps(return_to)  # safe JS string literal
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>กู้บัญชี Passkey · Central Auth Hub</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;700;800&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<style nonce="{nonce}">
.page {{
  --navy: #0b1420;
  --navy-2: #111e2c;
  --ink: #132033;
  --muted: #68788d;
  --line: #d7e0e7;
  --paper: #ffffff;
  --canvas: #f1f5f7;
  --teal: #18b99c;
  --teal-dark: #087a68;
  height: 100svh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--canvas);
  color: var(--ink);
}}

.topbar {{
  min-height: 54px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 0 clamp(16px, 3vw, 40px);
  border-bottom: 1px solid #263547;
  background: var(--navy);
  color: #fff;
}}

.brand {{
  display: inline-flex;
  align-items: center;
  gap: 12px;
  color: inherit;
  text-decoration: none;
}}

.brand > span {{
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border: 1px solid #2ac7aa;
  background: #0d2a2b;
  color: #43dfc2;
  font:500 1rem "IBM Plex Mono", monospace;
}}

.brand strong,
.brand small {{
  display: block;
}}

.brand strong {{
  font:500 1rem "Sarabun", sans-serif;
}}

.brand small {{
  margin-top: 2px;
  color: #7f91a7;
  font:500 .7rem "IBM Plex Mono", monospace;
  letter-spacing: .15em;
}}

.secureStatus {{
  display: flex;
  align-items: center;
  gap: 8px;
  color: #9fb0c3;
  font:500 .72rem "IBM Plex Mono", monospace;
  letter-spacing: .08em;
}}

.secureStatus i {{
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #38d7b9;
  box-shadow: 0 0 0 4px rgba(56, 215, 185, .12);
}}

.shell {{
  width: min(1380px, calc(100% - 36px));
  min-height: 0;
  flex: 1;
  display: grid;
  grid-template-columns: minmax(300px, .72fr) minmax(560px, 1.6fr);
  margin: 14px auto;
  overflow: hidden;
  border: 1px solid #cfd9e1;
  background: var(--paper);
  box-shadow: 0 18px 50px rgba(16, 31, 48, .08);
}}

.context {{
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: clamp(20px, 2.4vw, 38px);
  overflow: hidden;
  border-top: 3px solid var(--teal);
  background:
    radial-gradient(circle at 90% 10%, rgba(26, 182, 157, .14), transparent 35%),
    linear-gradient(160deg, var(--navy) 0%, #111d2b 70%, #0c2528 100%);
  color: #f3f7fa;
}}

.eyebrow {{
  display: block;
  color: #6f849b;
  font:500 .72rem/1.4 "IBM Plex Mono", monospace;
  letter-spacing: .16em;
}}

.context h1 {{
  max-width: 520px;
  margin: 10px 0 8px;
  font: 800 clamp(1.4rem, 1.9vw, 2.05rem)/1.22 "Sarabun", sans-serif;
  letter-spacing: -.025em;
}}

.context > div:first-child > p {{
  max-width: 510px;
  margin: 0;
  color: #9bacc0;
  font-size: .82rem;
  line-height: 1.6;
}}

.steps {{
  list-style: none;
  margin: auto 0;
  padding: 20px 0;
}}

.steps li {{
  position: relative;
  min-height: 58px;
  display: grid;
  grid-template-columns: 38px 1fr;
  align-items: start;
  gap: 16px;
  color: #65798f;
}}

.steps li:not(:last-child)::after {{
  content: "";
  position: absolute;
  left: 15px;
  top: 34px;
  width: 1px;
  height: 22px;
  background: #2b3b4e;
}}

.steps li > span {{
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 1px solid #324356;
  color: #7d90a6;
  font:500 .72rem "IBM Plex Mono", monospace;
}}

.steps strong,
.steps small {{
  display: block;
}}

.steps strong {{
  margin-top: 2px;
  font-size: .84rem;
}}

.steps small {{
  margin-top: 2px;
  font-size: .72rem;
}}

.steps .stepActive {{
  color: #f4f8fb;
}}

.steps .stepActive > span {{
  border-color: var(--teal);
  background: rgba(24, 185, 156, .13);
  color: #42dfc2;
}}

.securityNote {{
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding-top: 14px;
  border-top: 1px solid #29394b;
}}

.securityNote > span {{
  width: 24px;
  height: 24px;
  flex: none;
  display: grid;
  place-items: center;
  border: 1px solid #3f566c;
  border-radius: 50%;
  color: #83a0b9;
  font:500 .75rem "IBM Plex Mono", monospace;
}}

.securityNote p {{
  margin: 0;
  color: #73879c;
  font-size: .78rem;
  line-height: 1.55;
}}

.securityNote strong {{
  display: block;
  margin-bottom: 2px;
  color: #a8b7c6;
  font-size: .82rem;
}}

.workspace {{
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
}}

.workspaceHeader {{
  min-height: 72px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 14px clamp(20px, 2.4vw, 34px);
  border-bottom: 1px solid var(--line);
}}

.workspaceHeader h2 {{
  margin: 3px 0 0;
  font: 800 clamp(1.1rem, 1.5vw, 1.45rem)/1.25 "Sarabun", sans-serif;
}}

.sessionId {{
  flex: none;
  padding: 8px 10px;
  border: 1px solid #a8ded4;
  background: #effaf7;
  color: var(--teal-dark);
  font:500 .68rem "IBM Plex Mono", monospace;
  letter-spacing: .08em;
}}

.recoveryGrid {{
  min-height: 0;
  flex: 1;
  display: grid;
  grid-template-columns: minmax(200px, .66fr) minmax(340px, 1.4fr);
  overflow: hidden;
}}

.methods {{
  padding: 0;
  overflow-y: auto;
  border-right: 1px solid var(--line);
  background: #f6f8fa;
}}

.method,
.methodActive {{
  position: relative;
  width: 100%;
  min-height: 56px;
  display: grid;
  grid-template-columns: 32px 1fr;
  align-items: center;
  gap: 11px;
  padding: 9px 14px;
  border: 0;
  border-bottom: 1px solid #e4e9ee;
  background: transparent;
  color: var(--ink);
  text-align: left;
  cursor: pointer;
}}

.method:first-child,
.methodActive:first-child {{
  border-top: 1px solid #e4e9ee;
}}

.method:hover {{
  background: #edf3f4;
}}

.methodActive {{
  background: #fff;
  box-shadow: inset 3px 0 var(--teal);
}}

.method > span,
.methodActive > span,
.methodHeading > span {{
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 1px solid #cbd6df;
  background: #fff;
  color: #627389;
  font:500 .7rem "IBM Plex Mono", monospace;
}}

.methodActive > span,
.methodHeading > span {{
  border-color: #8cd7c9;
  background: #eaf9f5;
  color: var(--teal-dark);
}}

.method strong,
.method small,
.methodActive strong,
.methodActive small {{
  display: block;
}}

.method strong,
.methodActive strong {{
  font-size: .8rem;
  line-height: 1.3;
}}

.method small,
.methodActive small {{
  margin-top: 2px;
  color: #7c8b9d;
  font-size: .66rem;
  line-height: 1.4;
}}

.formPanel {{
  width: 100%;
  max-width: 560px;
  align-self: center;
  justify-self: center;
  overflow-y: auto;
  max-height: 100%;
  padding: clamp(18px, 2.4vw, 34px);
}}

.methodHeading {{
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}}

.methodHeading h3 {{
  margin: 0;
  font: 800 1.05rem "Sarabun", sans-serif;
}}

.methodHeading p {{
  margin: 2px 0 0;
  color: var(--muted);
  font-size: .76rem;
}}

.guidance {{
  margin-bottom: 14px;
  padding: 9px 12px;
  border-left: 3px solid #6a83a0;
  background: #f1f5f8;
  color: #4e6075;
  font-size: .74rem;
  line-height: 1.5;
}}

.field {{
  display: block;
  margin-bottom: 12px;
}}

.field > span {{
  display: flex;
  justify-content: space-between;
  margin-bottom: 5px;
  color: #405168;
  font-size: .78rem;
  font-weight:500;
}}

.field > span small {{
  color: #8b98a8;
  font-size: .75rem;
  font-weight: 500;
}}

.field input,
.field textarea {{
  width: 100%;
  min-height: 42px;
  border: 1px solid #c8d3dc;
  border-radius: 2px;
  outline: 0;
  padding: 9px 12px;
  background: #fff;
  color: #162438;
  font-size: .88rem;
  transition: border-color .15s ease, box-shadow .15s ease;
}}

.field textarea {{
  min-height: 78px;
  resize: vertical;
  line-height: 1.55;
}}

.field input:focus,
.field textarea:focus {{
  border-color: var(--teal);
  box-shadow: 0 0 0 3px rgba(24, 185, 156, .1);
}}

.field input:disabled,
.field textarea:disabled {{
  background: #f1f4f6;
  color: #8794a3;
}}

.codeInput,
.otpInput {{
  font-family: "IBM Plex Mono", monospace;
  letter-spacing: .12em;
}}

.otpInput {{
  text-align: center;
  font-size: 1.2rem !important;
  letter-spacing: .35em;
}}

.primaryButton {{
  width: 100%;
  min-height: 44px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border: 1px solid #07907a;
  border-radius: 2px;
  padding: 0 16px;
  background: var(--teal);
  color: #061c18;
  font-size: .95rem;
  font-weight:500;
  cursor: pointer;
  transition: background .15s ease, transform .15s ease;
}}

.primaryButton:hover:not(:disabled) {{
  background: #38d0b4;
  transform: translateY(-1px);
}}

.primaryButton:disabled {{
  border-color: #d8dee4;
  background: #e5e9ed;
  color: #94a0ad;
  cursor: not-allowed;
}}

.primaryButton > span {{
  font: 500 1.2rem "IBM Plex Mono", monospace;
}}

.infoMessage,
.errorMessage {{
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 11px;
  padding: 9px 12px;
  border: 1px solid #b9d9e8;
  background: #eff8fc;
  color: #245b73;
  font-size: .84rem;
  line-height: 1.5;
}}

.errorMessage {{
  border-color: #efb6c4;
  background: #fff2f5;
  color: #a2163a;
}}

.infoMessage > span,
.errorMessage > span {{
  width: 20px;
  height: 20px;
  flex: none;
  display: grid;
  place-items: center;
  border: 1px solid currentColor;
  border-radius: 50%;
  font:500 .7rem "IBM Plex Mono", monospace;
}}

.backLink {{
  display: inline-block;
  margin-top: 16px;
  color: #68798e;
  font-size: .84rem;
  font-weight:500;
  text-decoration: none;
}}

.backLink:hover {{
  color: var(--teal-dark);
}}

.resultPanel {{
  width: min(680px, calc(100% - 48px));
  margin: auto;
  padding: 36px;
}}

.codesPanel {{
  width: 100%;
}}

.codesHeader > span {{
  color: var(--teal-dark);
  font:500 .72rem "IBM Plex Mono", monospace;
  letter-spacing: .14em;
}}

.codesHeader h3 {{
  margin: 7px 0 5px;
  font: 800 1.55rem "Sarabun", sans-serif;
}}

.codesHeader p {{
  margin: 0;
  color: var(--muted);
  font-size: .88rem;
  line-height: 1.55;
}}

.codesGrid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 24px 0 16px;
}}

.codesGrid code {{
  min-height: 44px;
  display: grid;
  place-items: center;
  border: 1px solid #cdd7df;
  background: #f7f9fa;
  color: #1b2b3f;
  font:500 .9rem "IBM Plex Mono", monospace;
  letter-spacing: .1em;
}}

.codesActions {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}}

.codesActions button {{
  min-height: 44px;
  border: 1px solid #27384b;
  background: #172436;
  color: #fff;
  font-size: .84rem;
  font-weight:500;
  cursor: pointer;
}}

.codesActions button:hover {{
  background: #23344a;
}}

.codesActions .actionDone {{
  border-color: #70c9b8;
  background: #eaf9f5;
  color: var(--teal-dark);
}}

.codesConfirm {{
  display: flex;
  align-items: flex-start;
  gap: 11px;
  margin: 18px 0 12px;
  padding: 13px 14px;
  border: 1px solid #b8ddd5;
  background: #f0faf7;
  color: #31475b;
  font-size: .86rem;
  cursor: pointer;
}}

.codesConfirm input {{
  width: 17px;
  height: 17px;
  margin-top: 1px;
  accent-color: var(--teal-dark);
}}

.codesConfirmDisabled {{
  border-color: #dce2e7;
  background: #f5f7f8;
  color: #8b97a5;
  cursor: not-allowed;
}}

.codesSubmit {{
  width: 100%;
  min-height: 50px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 0;
  padding: 0 18px;
  background: var(--teal);
  color: #061c18;
  font-weight:500;
  cursor: pointer;
}}

.codesSubmit:disabled {{
  background: #e3e8ec;
  color: #929daa;
  cursor: not-allowed;
}}

.codesHint {{
  margin: 9px 0 0;
  color: #8895a4;
  text-align: center;
  font-size: .75rem;
}}

.donePanel {{
  width: min(520px, calc(100% - 48px));
  margin: auto;
  text-align: center;
}}

.donePanel h3 {{
  margin: 7px 0 8px;
  font: 800 1.6rem "Sarabun", sans-serif;
}}

.donePanel p {{
  margin: 0 0 24px;
  color: var(--muted);
  font-size: .95rem;
}}

.donePanel button {{
  width: 100%;
  min-height: 50px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 0;
  padding: 0 18px;
  background: var(--navy);
  color: #fff;
  font-weight:500;
  cursor: pointer;
}}

.footer {{
  min-height: 34px;
  flex: none;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 20px;
  padding: 0 clamp(16px, 3vw, 40px);
  border-top: 1px solid #d8e0e6;
  color: #79889a;
  font: 500 .68rem "IBM Plex Mono", monospace;
  letter-spacing: .05em;
}}

.footer span:last-child {{
  text-align: right;
}}

@media (max-width: 1080px) {{
  .shell {{
    grid-template-columns: 300px minmax(0, 1fr);
  }}

  .context {{
    padding: 36px 30px;
  }}

  .context h1 {{
    font-size: 2rem;
  }}

  .recoveryGrid {{
    grid-template-columns: 1fr;
  }}

  .methods {{
    display: grid;
    grid-template-columns: repeat(5, minmax(118px, 1fr));
    overflow-x: auto;
    padding: 0;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }}

  .method,
  .methodActive {{
    min-height: 92px;
    display: block;
    padding: 12px;
    border-right: 1px solid #e4e9ee;
    border-bottom: 0;
  }}

  .method > span,
  .methodActive > span {{
    width: 30px;
    height: 30px;
    margin-bottom: 8px;
  }}

  .method small,
  .methodActive small {{
    display: none;
  }}

  .methodActive {{
    box-shadow: inset 0 -3px var(--teal);
  }}
}}

@media (max-width: 780px) {{
  .topbar {{
    min-height: 64px;
    padding: 0 18px;
  }}

  .secureStatus {{
    font-size: 0;
  }}

  .shell {{
    width: 100%;
    min-height: 0;
    display: block;
    margin: 0;
    border: 0;
    box-shadow: none;
  }}

  .context {{
    min-height: auto;
    padding: 28px 22px;
  }}

  .context h1 {{
    margin: 12px 0 8px;
    font-size: 1.75rem;
  }}

  .context > div:first-child > p {{
    font-size: .9rem;
  }}

  .steps,
  .securityNote {{
    display: none;
  }}

  .workspaceHeader {{
    min-height: 92px;
    padding: 20px 22px;
  }}

  .sessionId {{
    display: none;
  }}

  .formPanel {{
    padding: 30px 22px 40px;
  }}

  .footer {{
    display: none;
  }}
}}

@media (max-width: 520px) {{
  .brand small {{
    display: none;
  }}

  .workspaceHeader h2 {{
    font-size: 1.45rem;
  }}

  .methods {{
    grid-template-columns: repeat(5, minmax(96px, 1fr));
  }}

  .method,
  .methodActive {{
    min-height: 82px;
    padding: 10px;
  }}

  .method strong,
  .methodActive strong {{
    font-size: .78rem;
  }}

  .methodHeading {{
    margin-bottom: 24px;
  }}

  .resultPanel {{
    width: 100%;
    padding: 24px 20px;
  }}
}}

.page strong,.page b,.page th,.page dt{{font-weight:500}}
.page h1,.page h2,.page h3{{font-weight:700}}

*{{box-sizing:border-box}}html,body{{margin:0;width:100%;min-height:100%;font-family:"Sarabun",sans-serif}}button,input{{font:inherit}}
.page{{--mint:#087a68;--mint-2:#087a68;--danger:#a2163a}}
.hide,#result{{display:none!important}}#result.show{{display:block!important}}
#result{{grid-column:1/-1;width:min(620px,100%);margin:auto;padding:28px;overflow:auto;max-height:100%}}
#form{{min-height:0;flex:1;display:flex;flex-direction:column}}.tabs{{min-width:0}}
.tab.active{{background:#fff;box-shadow:inset 3px 0 var(--teal)}}.tab.active>span{{border-color:#8cd7c9;background:#eaf9f5;color:var(--teal-dark)}}
.fld{{display:block;margin:12px 0 5px;color:#405168;font-size:.78rem}}
input:not([type=checkbox]){{width:100%;min-height:42px;border:1px solid #c8d3dc;border-radius:2px;padding:9px 12px;background:#fff;color:#162438;font-size:.88rem}}
input:focus-visible{{outline:2px solid var(--teal);outline-offset:2px}}
.mono{{font-family:"IBM Plex Mono",monospace;letter-spacing:.12em}}
.btn{{width:100%;min-height:44px;display:flex;justify-content:space-between;align-items:center;gap:18px;margin-top:12px;border:1px solid #07907a;border-radius:2px;padding:10px 16px;background:var(--teal);color:#061c18;cursor:pointer}}
.btn::after{{content:"→"}}.btn:disabled{{background:#e5e9ed;border-color:#d8dee4;color:#94a0ad;cursor:not-allowed}}
.back{{display:inline-block;margin-top:16px;color:#68798e;font-size:.84rem;text-decoration:none}}
.msg{{display:none}}.msg.show{{display:block;padding:9px 12px;background:#fff2f5;color:#a2163a;border:1px solid #efb6c4}}
.success-card{{text-align:center}}.success-icon svg{{width:36px;height:36px;fill:none;stroke:var(--teal-dark);stroke-width:2}}
.success-title{{color:var(--teal-dark)}}.success-msg,.codes-head-sub{{color:var(--muted)}}
.btn-return,.act-btn{{display:block;padding:12px;border:1px solid var(--line);background:#f1f5f7;color:var(--ink);text-decoration:none;cursor:pointer}}
.codes-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:18px 0}}.code-cell{{padding:12px;background:#f7f9fa;border:1px solid var(--line);font-family:"IBM Plex Mono",monospace}}.code-num{{color:var(--muted);margin-right:8px}}.actions-row{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.warn-band{{margin:12px 0;padding:10px;background:#fff8e7;color:#805a17}}.ack-box{{display:flex;gap:10px;margin:16px 0;color:var(--ink);font-size:.86rem}}
@media(max-width:1080px){{.methods{{grid-template-columns:repeat(4,minmax(0,1fr))}}.recoveryGrid{{grid-template-rows:auto minmax(0,1fr)}}}}
@media(max-width:780px){{.page{{height:auto;min-height:100svh;overflow:visible}}.shell{{overflow:visible}}.recoveryGrid{{overflow:visible}}.methods{{overflow:visible}}.formPanel{{max-height:none;overflow:visible}}}}
@media(max-width:520px){{.methods{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style></head><body>
<main class="page">
<header class="topbar"><a class="brand" href="/"><span>H</span><div><strong>Central Auth Hub</strong><small>IDENTITY CONTROL</small></div></a><div class="secureStatus"><i></i>SECURE RECOVERY SESSION</div></header>
<div class="shell">
<aside class="context">
<div><span class="eyebrow">ACCOUNT RECOVERY</span><h1>กลับเข้าใช้งานบัญชี<br>อย่างปลอดภัย</h1><p>เลือกวิธียืนยันตัวตนที่คุณยังเข้าถึงได้ ระบบจะยกเลิก Passkey เดิมก่อนให้ตั้งค่าอุปกรณ์ใหม่</p></div>
<ol class="steps"><li class="stepActive"><span>01</span><div><strong>เลือกวิธียืนยัน</strong><small>ใช้ข้อมูลที่คุณยังเข้าถึงได้</small></div></li><li><span>02</span><div><strong>ตรวจสอบตัวตน</strong><small>ยืนยันรหัสหรือส่งคำขอ</small></div></li><li><span>03</span><div><strong>กลับเข้าสู่ระบบ</strong><small>ตั้ง Passkey ใหม่หลัง Login</small></div></li></ol>
<div class="securityNote"><span>i</span><p><strong>ไม่มีรหัสผ่านถูกจัดเก็บในหน้านี้</strong>รหัสยืนยันมีอายุจำกัดและใช้ได้เพียงครั้งเดียว</p></div>
</aside>
<section class="workspace">
<header class="workspaceHeader"><div><span class="eyebrow">PASSKEY / RECOVERY</span><h2>กู้การเข้าถึงบัญชี</h2></div><span class="sessionId">SESSION · ACTIVE</span></header>
<div id="result"></div>
<div id="form">
<div class="recoveryGrid">
<nav class="methods tabs" aria-label="วิธีกู้บัญชี">
<button type="button" class="method tab active" id="tabBackup"><span>BC</span><div><strong>Backup Code</strong><small>ใช้รหัสสำรองที่บันทึกไว้</small></div></button>
<button type="button" class="method tab" id="tabOtp"><span>EM</span><div><strong>Email OTP</strong><small>รับรหัสยืนยันทางอีเมล</small></div></button>
<button type="button" class="method tab" id="tabTicket"><span>AD</span><div><strong>ขอความช่วยเหลือ</strong><small>ส่งคำขอให้ผู้ดูแลตรวจสอบ</small></div></button>
<button type="button" class="method tab" id="tabRegen"><span>RC</span><div><strong>สร้าง Codes ใหม่</strong><small>เปลี่ยนเฉพาะชุดรหัสสำรอง</small></div></button>
</nav>
<div class="formPanel">
<div class="methodHeading"><span id="methodCode">BC</span><div><h3 id="methodTitle">Backup Code</h3><p id="methodDescription">ใช้รหัสสำรองที่บันทึกไว้</p></div></div>
      <div id="err" class="msg err"></div>
      <label class="fld" for="email">อีเมลบัญชีมหาวิทยาลัย</label>
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

      <div id="paneTicket" class="hide">
        <label class="fld" for="reason">เหตุผล (อุปกรณ์หาย / เข้า email ไม่ได้ ฯลฯ)</label>
        <input type="text" id="reason" placeholder="เช่น ทำโทรศัพท์ที่มี passkey หาย">
        <button class="btn" id="btnTicket">ส่งคำขอให้ Admin</button>
      </div>
      <a class="back" id="backLink" href="javascript:history.back()">← กลับ</a>
</div></div></div></section></div>
<footer class="footer"><span>Central Auth Hub</span><span>TLS 1.3 · WEBAUTHN · OAUTH 2.0</span><span>Princess of Naradhiwas University</span></footer>
</main>

<script nonce="{nonce}">
const RETURN_TO = {return_to_js};
const $ = id => document.getElementById(id);
const errEl = $('err'), resultEl = $('result'), formEl = $('form');
function showErr(m) {{ errEl.textContent = m; errEl.classList.add('show'); }}
function clearErr() {{ errEl.classList.remove('show'); }}
// ถ้ามี RETURN_TO → เปลี่ยน back link เป็นกลับ subsystem
if (RETURN_TO) {{
  const bl = $('backLink');
  if (bl) {{ bl.href = RETURN_TO; bl.textContent = '← กลับหน้า login ของระบบย่อย'; }}
}}
function buildReturnButton() {{
  if (!RETURN_TO) return '';
  return '<a href="' + RETURN_TO + '" class="btn-return" style="margin-top:14px">' +
    '<span class="btn-return-arrow">←</span>' +
    '<span>กลับหน้า login ของระบบย่อย</span>' +
    '</a>';
}}
function buildSuccessCard(m) {{
  const action = RETURN_TO
    ? '<a href="' + RETURN_TO + '" class="btn-return">' +
        '<span class="btn-return-arrow">←</span>' +
        '<span>กลับหน้า login ของระบบย่อย</span>' +
      '</a>' +
      '<div class="return-hint"><span class="dot"></span>redirect อัตโนมัติ</div>'
    : '';
  return '<div class="success-card">' +
    '<div class="success-icon"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div>' +
    '<h3 class="success-title">กู้บัญชีสำเร็จ</h3>' +
    '<p class="success-msg">' + m + '</p>' +
    action +
  '</div>';
}}
function done(m, codes) {{
  formEl.classList.add('hide');
  if (!codes || !codes.length) {{
    resultEl.innerHTML = buildSuccessCard(m);
    resultEl.classList.add('show');
    if (RETURN_TO) setTimeout(() => {{ window.location.href = RETURN_TO; }}, 3500);
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
      '</div>' +
      buildReturnButton();
    // auto-redirect หลัง 2 วินาที ถ้ามี RETURN_TO
    if (RETURN_TO) setTimeout(() => {{ window.location.href = RETURN_TO; }}, 2000);
  }});
}}

let regenMode = false;
function setTab(active, regen) {{
  ['tabBackup','tabOtp','tabRegen','tabTicket'].forEach(t => document.getElementById(t).classList.toggle('active', t===active));
  $('paneBackup').classList.toggle('hide', active!=='tabBackup');
  $('paneOtp').classList.toggle('hide', active!=='tabOtp' && active!=='tabRegen');
  $('paneTicket').classList.toggle('hide', active!=='tabTicket');
  $('otpStep1').classList.remove('hide'); $('otpStep2').classList.add('hide');
  const selected = $(active);
  $('methodCode').textContent = selected.querySelector('span').textContent;
  $('methodTitle').textContent = selected.querySelector('strong').textContent;
  $('methodDescription').textContent = selected.querySelector('small').textContent;
  regenMode = regen; clearErr();
}}
$('tabBackup').addEventListener('click', () => setTab('tabBackup', false));
$('tabOtp').addEventListener('click', () => setTab('tabOtp', false));
$('tabRegen').addEventListener('click', () => setTab('tabRegen', true));
$('tabTicket').addEventListener('click', () => setTab('tabTicket', false));

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

$('btnTicket').addEventListener('click', async () => {{
  clearErr();
  if (!emailVal()) return showErr('กรุณากรอกอีเมล');
  $('btnTicket').disabled = true; $('btnTicket').textContent = 'กำลังส่ง…';
  const {{ok, data}} = await post('/auth/recovery/request', {{email:emailVal(), credential_type:'passkey', reason:($('reason').value||'').trim()}});
  // opaque เสมอ (ไม่บอกว่า email มีจริงไหม) → ถือว่าส่งสำเร็จถ้า HTTP ok
  if (ok) done(data.message || 'ส่งคำขอแล้ว — ผู้ดูแลระบบจะติดต่อยืนยันตัวตน');
  else {{ showErr(pickMsg(data, 'ส่งคำขอไม่สำเร็จ')); $('btnTicket').disabled=false; $('btnTicket').textContent='ส่งคำขอให้ Admin'; }}
}});
</script>
</body></html>"""


# ============ Login chooser page (A) — Google / Passkey ============


def _login_chooser_html(
    hub_state: str,
    subsystem_name: str,
    nonce: str,
    allow_google: bool = True,
    allow_passkey: bool = True,
) -> str:
    """หน้าเลือกวิธี login — Google (redirect) หรือ Passkey (WebAuthn JS).

    Aesthetic: Signal Room login — square console panel, compact Thai typography,
    mint-cyan accent, and the same visual language as the Hub frontend login.

    Same-origin: เสิร์ฟจาก Hub → fetch /oauth/passkey/* ตรง ไม่ผ่าน proxy.
    inline style+script ใช้ CSP nonce (กัน XSS — middleware ตั้ง nonce-{nonce}).

    allow_google / allow_passkey: ตาม global auth-policy — ปิดวิธีไหน ซ่อนปุ่มนั้น.
    """
    # esc ชื่อ subsystem (กัน HTML injection — ชื่อมาจาก DB)
    safe_name = (
        subsystem_name.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    # ── สร้าง fragment ตาม auth-policy (ปิดวิธีไหน ซ่อนปุ่มนั้น) ──
    passkey_block = (
        """
    <button class="btn btn-pk stagger s1" id="pkToggle">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
      <span>ดำเนินการต่อด้วย Passkey</span><b aria-hidden="true">→</b>
    </button>

    <div class="pk-form stagger s2" id="pkForm" aria-hidden="true">
      <div class="err" id="pkErr"></div>
      <label class="fld" for="pkEmail">อีเมลของคุณ</label>
      <input type="email" id="pkEmail" placeholder="you@uni.ac.th" autocomplete="username webauthn" inputmode="email">
      <button class="btn btn-pk" id="pkSubmit">ยืนยันตัวตน</button>
      <p class="hint" id="pkHint">ระบบจะขอ biometric หรือ security key ของอุปกรณ์นี้</p>
    </div>
"""
        if allow_passkey
        else ""
    )

    google_block = (
        f"""
    <a class="btn btn-ghost stagger s4" href="/oauth/authorize/google?hub_state={hub_state}">
      <svg class="gicon" viewBox="0 0 24 24"><path d="M21.6 12.227c0-.709-.064-1.39-.182-2.045H12v3.868h5.382a4.6 4.6 0 0 1-1.996 3.018v2.51h3.232c1.891-1.742 2.982-4.305 2.982-7.35Z" fill="#4285F4"/><path d="M12 22c2.7 0 4.964-.895 6.618-2.423l-3.232-2.509c-.895.6-2.04.955-3.386.955-2.605 0-4.81-1.76-5.595-4.123H3.064v2.59A9.996 9.996 0 0 0 12 22Z" fill="#34A853"/><path d="M6.405 13.9a6.003 6.003 0 0 1 0-3.8V7.51H3.064a9.996 9.996 0 0 0 0 8.98l3.341-2.59Z" fill="#FBBC05"/><path d="M12 5.977c1.468 0 2.786.505 3.823 1.496l2.868-2.868C16.96 2.99 14.695 2 12 2A9.996 9.996 0 0 0 3.064 7.51l3.341 2.59C7.19 7.736 9.395 5.977 12 5.977Z" fill="#EA4335"/></svg>
      <span>เข้าสู่ระบบด้วย Google Workspace</span><b aria-hidden="true">→</b>
    </a>
"""
        if allow_google
        else ""
    )

    # divider "หรือ" แสดงเฉพาะเมื่อเปิดทั้งคู่
    divider_block = (
        '<div class="divider stagger s3">หรือ</div>'
        if (allow_google and allow_passkey)
        else ""
    )
    # recover link เฉพาะเมื่อ passkey เปิด
    recover_block = (
        '<a class="recover-link" href="/oauth/passkey/recover">ใช้ Passkey ไม่ได้หรือกู้คืนบัญชี</a>'
        if allow_passkey
        else ""
    )
    # ทางเข้า "ตั้งค่าการยืนยันตัวตน" สำหรับ **ทุก role รวมนักศึกษา**
    # (นักศึกษาเข้า Hub console ไม่ได้ → ถ้าเคยกด "ข้าม/ไม่ถามอีก" ต้องมีทางกลับมาตั้ง)
    setup_link = (
        '<a class="recover-link" href="/auth/credentials/setup">เพิ่มวิธียืนยันตัวตน</a>'
    )
    recover_block = (
        '<div class="login-help">'
        + recover_block
        + ('<span>·</span>' if allow_passkey else '')
        + setup_link
        + '</div>'
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
    background:
      linear-gradient(115deg,rgba(52,232,196,.055),transparent 38%),
      linear-gradient(245deg,rgba(82,120,255,.06),transparent 42%),
      var(--bg-0);
    color:var(--ink);
    min-height:100vh; display:grid; place-items:center; padding:32px 16px;
    overflow:hidden; position:relative;
  }}
  /* subtle Signal Room grid */
  body::before {{
    content:''; position:fixed; inset:-20%; z-index:0;
    background:
      linear-gradient(rgba(148,178,224,.018) 1px,transparent 1px),
      linear-gradient(90deg,rgba(148,178,224,.018) 1px,transparent 1px);
    background-size:44px 44px;
  }}
  /* fine grain overlay */
  body::after {{
    content:''; position:fixed; inset:0; z-index:0; pointer-events:none; opacity:.05;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  }}
  .card {{
    position:relative; z-index:1; width:100%; max-width:524px;
    background:linear-gradient(150deg,rgba(18,25,40,.94),rgba(12,17,28,.97));
    border:1px solid rgba(148,178,224,.16); border-radius:0;
    box-shadow:0 24px 80px rgba(0,0,0,.28),inset 0 1px rgba(255,255,255,.025);
    backdrop-filter:blur(16px); overflow:hidden;
    animation:rise .7s cubic-bezier(.2,.8,.2,1) both;
  }}
  .card::before {{
    content:''; position:absolute; left:-1px; top:38px; width:2px; height:76px;
    background:linear-gradient(var(--mint),rgba(52,232,196,.06));
    box-shadow:0 0 14px rgba(52,232,196,.3);
  }}
  @keyframes rise {{ from{{opacity:0; transform:translateY(16px) scale(.985)}} to{{opacity:1; transform:none}} }}

  .top {{ padding:42px 40px 8px; }}
  .badge {{
    display:inline-flex; align-items:center; gap:8px; font-family:'IBM Plex Mono',monospace;
    font-size:9px; letter-spacing:1.25px; text-transform:uppercase; color:var(--mint);
    padding:0; background:transparent;
  }}
  .dot {{ width:6px; height:6px; border-radius:50%; background:var(--mint);
          box-shadow:0 0 8px var(--mint); animation:pulse 2s infinite; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.35}} }}
  h1 {{
    font-family:'Kanit',sans-serif; font-weight:600; font-size:28px; line-height:1.18;
    margin:18px 0 4px; letter-spacing:-.5px;
  }}
  h1 .accent {{ color:transparent; background:linear-gradient(92deg,var(--mint),#7ad6ff);
                -webkit-background-clip:text; background-clip:text; }}
  .sub {{ color:#76879e; font-size:11px; margin:0; }}

  .body {{ padding:24px 40px 32px; }}
  .stagger {{ opacity:0; animation:fade .6s ease forwards; }}
  .s1{{animation-delay:.12s}} .s2{{animation-delay:.20s}} .s3{{animation-delay:.28s}} .s4{{animation-delay:.36s}}
  @keyframes fade {{ from{{opacity:0; transform:translateY(8px)}} to{{opacity:1; transform:none}} }}

  .btn {{
    display:flex; align-items:center; justify-content:center; gap:11px; width:100%;
    height:56px; padding:0 18px; border-radius:0;
    font-family:'Kanit',sans-serif; font-weight:500;
    font-size:12px; text-decoration:none; border:1px solid transparent; cursor:pointer;
    transition:transform .15s ease, box-shadow .25s ease, background .2s ease; position:relative;
    overflow:hidden;
  }}
  .btn:active {{ transform:translateY(1px) scale(.995); }}
  .btn span {{ flex:1; text-align:left; }}
  .btn b {{ font-weight:500; }}
  .btn-pk {{
    color:#04221c; background:linear-gradient(100deg,var(--mint),#5ff0d6);
    box-shadow:0 0 24px rgba(52,232,196,.12);
  }}
  .btn-pk:hover {{ transform:translateY(-2px); box-shadow:0 16px 40px -12px rgba(52,232,196,.7); }}
  .btn-pk::after {{ /* shine sweep */
    content:''; position:absolute; top:0; left:-60%; width:40%; height:100%;
    background:linear-gradient(100deg,transparent,rgba(255,255,255,.55),transparent);
    transform:skewX(-18deg); transition:left .5s ease;
  }}
  .btn-pk:hover::after {{ left:130%; }}
  .btn-ghost {{
    color:#c0ccdc; background:#111827; border-color:rgba(148,178,224,.16);
    font-size:11px;
  }}
  .btn-ghost:hover {{ background:rgba(255,255,255,.08); border-color:rgba(148,178,224,.3); }}
  .btn[disabled] {{ opacity:.5; cursor:not-allowed; transform:none; box-shadow:none; }}

  .pk-form {{ display:grid; gap:11px; margin-bottom:4px; overflow:hidden;
              max-height:0; opacity:0; transition:max-height .4s ease, opacity .3s ease; }}
  .pk-form.open {{ max-height:280px; opacity:1; margin-bottom:14px; }}
  label.fld {{ font-size:11px; color:var(--muted); letter-spacing:.04em;
               margin-bottom:-4px; font-family:'IBM Plex Mono',monospace; }}
  input[type=email] {{
    width:100%; padding:13px 14px; border-radius:0; border:1px solid var(--line);
    background:rgba(7,11,20,.7); color:var(--ink); font-size:14.5px;
    font-family:'IBM Plex Sans Thai',sans-serif; transition:border .2s,box-shadow .2s;
  }}
  input[type=email]::placeholder {{ color:#52617e; }}
  input[type=email]:focus {{ outline:none; border-color:var(--mint-2);
                             box-shadow:0 0 0 3px rgba(52,232,196,.16); }}

  .err {{ display:none; align-items:flex-start; gap:8px; font-size:12.5px; color:var(--danger);
          background:rgba(255,107,129,.08); border:1px solid rgba(255,107,129,.28);
          padding:10px 12px; border-radius:0; line-height:1.45; }}
  .err.show {{ display:flex; animation:shake .35s; }}
  @keyframes shake {{ 0%,100%{{transform:translateX(0)}} 25%{{transform:translateX(-4px)}} 75%{{transform:translateX(4px)}} }}
  .hint {{ font-size:11.5px; color:var(--muted); }}

  .divider {{ display:flex; align-items:center; gap:12px; margin:18px 0;
              color:#526176; font-size:9px; font-family:'IBM Plex Mono',monospace; }}
  .divider::before, .divider::after {{ content:''; flex:1; height:1px;
              background:linear-gradient(90deg,transparent,var(--line),transparent); }}

  .spinner {{ width:16px; height:16px; border:2px solid rgba(4,34,28,.35);
              border-top-color:#04221c; border-radius:50%; animation:spin .7s linear infinite; }}
  @keyframes spin {{ to{{transform:rotate(360deg)}} }}

  .foot {{ padding:15px 40px; border-top:1px solid var(--line); text-align:center;
           font-family:'IBM Plex Mono',monospace; font-size:8px; letter-spacing:.08em;
           color:#56657f; }}
  .gicon {{ width:18px; height:18px; flex:none; }}
  .recover-link {{ display:block; text-align:center; margin-top:14px; font-size:9px;
                   color:var(--mint-2); text-decoration:none; }}
  .recover-link:hover {{ color:var(--mint); text-decoration:underline; }}
  @media (max-width:560px) {{
    body {{ padding:16px 12px; }}
    .top {{ padding:30px 24px 8px; }}
    .body {{ padding:22px 24px 26px; }}
    .foot {{ padding:14px 24px; font-size:9px; }}
    h1 {{ font-size:27px; }}
  }}

  /* Full Signal Room shell — identical structure to the administrator login. */
  body {{ display:block; width:100vw; max-width:none; padding:0; overflow-x:hidden; overflow-y:auto; }}
  .login-page {{ width:100vw; max-width:none; min-height:100vh; margin:0; position:relative; overflow:hidden; display:grid;
    grid-template-rows:72px 1fr 52px; }}
  .login-glow {{ position:absolute; border-radius:50%; pointer-events:none; filter:blur(2px); }}
  .glow-one {{ width:650px; height:650px; right:-210px; top:-310px;
    background:radial-gradient(circle,rgba(52,232,196,.13),rgba(52,232,196,.025) 42%,transparent 70%); }}
  .glow-two {{ width:550px; height:550px; left:-360px; bottom:-250px;
    background:radial-gradient(circle,rgba(14,165,233,.08),transparent 67%); }}
  .login-topbar {{ width:100%; max-width:none; height:72px; margin:0; position:relative; z-index:3; display:flex; align-items:center;
    justify-content:space-between; padding:0 clamp(24px,5vw,72px); border-bottom:1px solid rgba(148,178,224,.11); }}
  .login-topbar::after {{ content:''; position:absolute; left:clamp(24px,5vw,72px);
    right:clamp(24px,5vw,72px); bottom:-1px; height:1px;
    background:linear-gradient(90deg,rgba(52,232,196,.65),rgba(52,232,196,.06) 30%,transparent 65%); }}
  .login-brand {{ display:flex; align-items:center; gap:11px; color:#fff; text-decoration:none; }}
  .login-brand-icon {{ width:39px; height:39px; border:1px solid rgba(52,232,196,.3);
    border-radius:10px; background:linear-gradient(145deg,rgba(52,232,196,.14),rgba(52,232,196,.025));
    display:grid; place-items:center; color:var(--mint); position:relative; font:400 20px 'IBM Plex Mono'; }}
  .login-brand-icon .dot {{ position:absolute; right:-3px; top:-3px; }}
  .login-brand strong,.login-brand small {{ display:block; }}
  .login-brand strong {{ font:600 17px 'IBM Plex Sans Thai',sans-serif; letter-spacing:2px; }}
  .login-brand small {{ font:500 7px 'IBM Plex Mono'; letter-spacing:1.45px; color:#697c95; }}
  .login-system-status {{ display:flex; align-items:center; gap:7px; color:#73849b;
    font:500 7px 'IBM Plex Mono'; letter-spacing:.6px; }}
  .login-system-status b {{ color:var(--mint); font-size:7px; }}
  .login-stage {{ width:min(1160px,calc(100% - 48px)); margin:auto; position:relative; z-index:2;
    display:grid; grid-template-columns:minmax(0,1.05fr) minmax(390px,.72fr);
    gap:clamp(55px,9vw,130px); align-items:center; padding:45px 0; }}
  .login-context {{ animation:rise .65s ease both; }}
  .context-kicker {{ display:flex; align-items:center; gap:8px; color:#7f92aa;
    font:500 8px 'IBM Plex Mono'; letter-spacing:1.2px; }}
  .target-icon {{ width:14px; height:14px; color:var(--mint); }}
  .login-context h1 {{ font-family:'Kanit',sans-serif; font-weight:700;
    font-size:clamp(40px,5vw,68px); line-height:1.09; letter-spacing:-2.7px;
    margin:17px 0; max-width:660px; }}
  .login-context h1 span {{ color:transparent; background:linear-gradient(100deg,#fff 8%,var(--mint) 78%);
    background-clip:text; -webkit-background-clip:text; }}
  .trust-rail {{ position:relative; margin-top:40px; display:flex; gap:42px; }}
  .rail-line {{ position:absolute; left:22px; right:22px; top:18px; height:1px;
    background:linear-gradient(90deg,var(--mint),rgba(52,232,196,.2),rgba(148,178,224,.08)); }}
  .rail-line i {{ position:absolute; width:4px; height:4px; background:#506078; border-radius:50%; top:-2px; }}
  .rail-line i:first-child {{ left:0; background:var(--mint); box-shadow:0 0 8px var(--mint); }}
  .rail-line i:nth-child(2) {{ left:50%; }} .rail-line i:last-child {{ right:0; }}
  .trust-point {{ position:relative; z-index:1; flex:1; }}
  .trust-point>span {{ width:36px; height:36px; border:1px solid rgba(148,178,224,.16);
    background:#0c121e; color:#708198; display:grid; place-items:center; border-radius:50%; margin-bottom:11px; }}
  .trust-point.active>span {{ border-color:rgba(52,232,196,.42); color:var(--mint);
    box-shadow:0 0 18px rgba(52,232,196,.08); }}
  .trust-point svg {{ width:18px; height:18px; fill:none; stroke:currentColor; stroke-width:1.7; }}
  .trust-point b,.trust-point small {{ display:block; }}
  .trust-point b {{ font-size:9px; }} .trust-point small {{ font-size:7px; color:#697a92; margin-top:2px; white-space:nowrap; }}
  .card {{ max-width:none; padding:32px; animation-delay:.12s; }}
  .card::before {{ top:31px; height:62px; }}
  .panel-scanline {{ position:absolute; left:0; right:0; top:0; height:1px;
    background:linear-gradient(90deg,transparent,var(--mint),transparent); opacity:.35; }}
  .top {{ padding:0; }} .top h1 {{ font-size:24px; margin:7px 0 2px; }}
  .top .sub {{ font-size:9px; margin:0 0 23px; }} .badge {{ font-size:7px; }}
  .body {{ padding:0; }} .btn {{ height:44px; font-size:10px; padding:0 13px; }}
  .btn-pk {{ margin-top:13px; }} .btn-ghost {{ font-size:9px; }}
  .divider {{ height:29px; margin:0; gap:9px; font-size:7px; }}
  .login-help {{ display:flex; align-items:center; justify-content:center; gap:7px; margin:17px 0 0; }}
  .recover-link {{ display:inline; margin:0; color:#74869d; font-size:7px; }}
  .login-help span {{ color:#3f4e63; }}
  .foot {{ margin:22px -32px -32px; padding:10px 13px; background:rgba(5,9,15,.28);
    display:grid; grid-template-columns:16px 1fr auto; align-items:center; text-align:left;
    letter-spacing:0; color:#667a92; font-size:7px; }}
  .foot svg {{ color:#4eaf9a; }} .foot code {{ color:#587166; font-size:6px; }}
  .login-footer {{ position:relative; z-index:2; border-top:1px solid rgba(148,178,224,.08);
    display:flex; align-items:center; gap:18px; padding:0 clamp(24px,5vw,72px); color:#506078; font-size:7px; }}
  .login-footer code {{ font-size:6px; color:#405067; }} .login-footer span:last-child {{ margin-left:auto; }}
  @media (max-width:900px) {{
    .login-page {{ overflow:auto; }} .login-stage {{ grid-template-columns:1fr; gap:36px;
      width:min(580px,calc(100% - 38px)); padding:45px 0 60px; }}
    .login-context {{ text-align:center; }} .context-kicker {{ justify-content:center; }}
    .login-context h1 {{ font-size:46px; }} .trust-rail {{ text-align:left; }}
  }}
  @media (max-width:560px) {{
    .login-page {{ grid-template-rows:62px 1fr auto; }} .login-topbar {{ height:62px; padding:0 18px; }}
    .login-system-status span {{ display:none; }} .login-stage {{ width:calc(100% - 24px); padding:30px 0 38px; gap:29px; }}
    .login-context h1 {{ font-size:34px; letter-spacing:-1.5px; }} .trust-rail {{ gap:10px; margin-top:28px; }}
    .trust-point small {{ white-space:normal; }} .trust-point b {{ font-size:8px; }}
    .card {{ padding:25px 19px; }} .foot {{ margin:20px -19px -25px; }}
    .login-footer {{ padding:13px 18px; flex-wrap:wrap; gap:5px 12px; }}
    .login-footer span:last-child {{ width:100%; margin-left:0; }} .login-help {{ flex-wrap:wrap; }}
  }}
</style></head><body>
<main class="login-page">
  <div class="login-glow glow-one"></div><div class="login-glow glow-two"></div>
  <header class="login-topbar">
    <a class="login-brand" href="/" aria-label="Central Auth Hub">
      <span class="login-brand-icon">H<i class="dot"></i></span>
      <span><strong>HUB</strong><small>IDENTITY CONTROL</small></span>
    </a>
    <div class="login-system-status"><i class="dot"></i><span>AUTH GATEWAY</span><b>ONLINE</b></div>
  </header>
  <section class="login-stage">
    <div class="login-context">
      <div class="context-kicker">
        <svg class="target-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M22 12h-3M12 22v-3M2 12h3"/></svg>
        <span>SECURE ACCESS · TH-SOUTH-01</span>
      </div>
      <h1>ยืนยันตัวตน<br>ก่อนเข้าสู่ <span>{safe_name}</span></h1>
      <div class="trust-rail" aria-label="คุณสมบัติความปลอดภัย">
        <div class="rail-line"><i></i><i></i><i></i></div>
        <div class="trust-point active"><span><svg viewBox="0 0 24 24"><path d="M7 12a5 5 0 0 1 10 0v5M5 12a7 7 0 0 1 14 0v4M9 12a3 3 0 0 1 6 0v8M12 12v9"/></svg></span><div><b>Phishing-resistant</b><small>Passkey · WebAuthn</small></div></div>
        <div class="trust-point"><span><svg viewBox="0 0 24 24"><path d="M12 3 20 6v5c0 5-3 8-8 10-5-2-8-5-8-10V6l8-3Z"/><path d="m8 12 2.5 2.5L16 9"/></svg></span><div><b>Risk-aware access</b><small>4-layer scoring ก่อนอนุญาต</small></div></div>
        <div class="trust-point"><span><svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="11"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg></span><div><b>Audit protected</b><small>Append-only hash chain</small></div></div>
      </div>
    </div>
    <section class="card" aria-labelledby="login-title">
      <div class="panel-scanline"></div>
      <div class="top">
        <span class="badge">SUBSYSTEM AUTHENTICATION</span>
        <h1 id="login-title">เข้าสู่ระบบ</h1>
        <p class="sub">ใช้บัญชีมหาวิทยาลัยที่ได้รับสิทธิ์เท่านั้น</p>
      </div>
      <div class="body">{passkey_block}{divider_block}{google_block}{recover_block}</div>
      <div class="foot">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3 20 6v5c0 5-3 8-8 10-5-2-8-5-8-10V6l8-3Z"/><path d="m8 12 2.5 2.5L16 9"/></svg>
        <span>Auth policy loaded</span><code>passkey:{'on' if allow_passkey else 'off'} · google:{'on' if allow_google else 'off'}</code>
      </div>
    </section>
  </section>
  <footer class="login-footer"><span>Central Auth Hub</span><code>TLS 1.3 · WEBAUTHN · OAUTH 2.0</code><span>Princess of Naradhiwas University</span></footer>
</main>

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
// Passkey ถูกปิดโดย policy → ไม่มี element → ข้าม JS ทั้งบล็อก (กัน null crash)
if (toggle) {{
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
}}  // end if (toggle)
</script>
</body></html>"""


# ============ Maintenance page (Pre-flight Use Case 2) ============


def _maintenance_html(subsystem_name: str, health: dict) -> str:
    """หน้า HTML แสดงตอน subsystem ล่ม (alt. ของ redirect ไป Google)."""
    # esc ชื่อ + error (มาจาก DB / health) — กัน HTML injection (audit run-1 #1)
    safe_name = html.escape(subsystem_name, quote=True)
    checked_at = html.escape((health.get("checked_at") or "").replace("T", " ")[:19])
    error = html.escape(health.get("error") or "subsystem ไม่ตอบ health check")
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>{safe_name} · ปิดปรับปรุงชั่วคราว</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Sarabun', system-ui, -apple-system, 'Segoe UI', sans-serif;
          background: linear-gradient(160deg,#0f172a,#1e293b 55%,#312e81);
          margin: 0; min-height: 100vh; display: grid; place-items: center;
          padding: 40px 16px; color: #0f172a; }}
  .card {{ max-width: 500px; width: 100%; background: #fff; border-radius: 20px;
           overflow: hidden; box-shadow: 0 24px 60px rgba(2,6,23,0.45); }}
  .brandbar {{ display: flex; align-items: center; gap: 11px; padding: 16px 28px;
               border-bottom: 1px solid #eef2ff; }}
  .mark {{ width: 34px; height: 34px; border-radius: 10px;
           background: linear-gradient(135deg,#6366f1,#312e81); color: #fff;
           display: grid; place-items: center; font-weight: 800; font-size: 16px; }}
  .brandname {{ font-weight: 800; font-size: 13px; color: #0f172a; line-height: 1.1; }}
  .brandsub {{ font-size: 9.5px; letter-spacing: .18em; color: #94a3b8;
               font-weight: 700; text-transform: uppercase; margin-top: 2px; }}
  .hero {{ padding: 30px 32px 8px; text-align: center; }}
  .hicon {{ width: 64px; height: 64px; border-radius: 18px; margin: 0 auto 16px;
            display: grid; place-items: center; font-size: 30px;
            background: #fffbeb; border: 1px solid #fde68a; }}
  .eyebrow {{ font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
              font-weight: 700; color: #b45309; }}
  h1 {{ font-size: 22px; font-weight: 800; margin: 8px 0 0; color: #0f172a; }}
  .pill {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
           font-weight: 700; border-radius: 999px; padding: 4px 13px; margin-top: 12px;
           background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }}
  .body {{ padding: 20px 32px 8px; }}
  .body p {{ font-size: 14.5px; line-height: 1.65; color: #475569; margin: 8px 0;
             text-align: center; }}
  .reason {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px;
             padding: 14px 16px; margin: 18px 0 0; }}
  .reason .rlabel {{ font-size: 10.5px; font-weight: 700; letter-spacing: .05em;
                     text-transform: uppercase; color: #94a3b8; }}
  .reason .rtext {{ font-size: 12.5px; font-family: 'JetBrains Mono', monospace;
                    color: #334155; word-break: break-word; margin-top: 6px;
                    line-height: 1.5; }}
  .ts {{ font-size: 11px; color: #94a3b8; margin-top: 10px;
         font-family: 'JetBrains Mono', monospace; text-align: center; }}
  .actions {{ text-align: center; padding: 22px 32px 30px; }}
  .btn {{ display: inline-block; padding: 11px 22px; background: #0f172a;
          color: #fff; text-decoration: none; border-radius: 11px;
          font-weight: 700; font-size: 14px; }}
  .btn:hover {{ background: #1e293b; }}
  .footer {{ padding: 14px 32px; font-size: 11px; color: #94a3b8;
             border-top: 1px solid #f1f5f9; text-align: center; }}
</style></head><body>
<div class="card">
  <div class="brandbar">
    <div class="mark">H</div>
    <div><div class="brandname">Central Auth Hub</div>
         <div class="brandsub">Identity &amp; Access</div></div>
  </div>
  <div class="hero">
    <div class="hicon">🔧</div>
    <div class="eyebrow">บริการชั่วคราวไม่พร้อมใช้งาน</div>
    <h1>{safe_name}</h1>
    <span class="pill">● ปิดปรับปรุงชั่วคราว</span>
  </div>
  <div class="body">
    <p>ระบบนี้กำลังมีปัญหาทางเทคนิค ทีมงานได้รับแจ้งและอยู่ระหว่างแก้ไข</p>
    <p>กรุณาลองอีกครั้งในอีก 5 นาที</p>
    <div class="reason">
      <div class="rlabel">รายละเอียดสำหรับผู้ดูแลระบบ</div>
      <div class="rtext">{error}</div>
    </div>
    <div class="ts">Health check ล่าสุด: {checked_at} UTC</div>
  </div>
  <div class="actions">
    <a href="javascript:history.back()" class="btn">← กลับหน้าก่อนหน้า</a>
  </div>
  <div class="footer">
    Central Auth Hub · pre-flight health check ก่อน OAuth redirect
  </div>
</div>
</body></html>"""


def _suspended_html(subsystem_name: str) -> str:
    """หน้า HTML แสดงตอน subsystem ถูก admin ระงับ (status=suspended)."""
    # esc ชื่อ subsystem (มาจาก DB) — กัน HTML injection (audit run-1 #1)
    safe_name = html.escape(subsystem_name, quote=True)
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>{safe_name} ถูกระงับการใช้งาน</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: 'Sarabun', system-ui, sans-serif; background: #f8fafc;
          margin: 0; min-height: 100vh; display: grid; place-items: center;
          padding: 40px 16px; color: #0f172a; }}
  .card {{ max-width: 560px; width: 100%; background: #fff; border-radius: 16px;
           overflow: hidden; box-shadow: 0 4px 12px rgba(15,23,42,0.08); }}
  .hero {{ background: linear-gradient(135deg,#f59e0b,#b45309); padding: 32px;
           color: #fff; text-align: center; }}
  .icon {{ font-size: 56px; line-height: 1; }}
  .title {{ font-size: 22px; font-weight: 800; margin-top: 12px; }}
  .body {{ padding: 28px 32px; line-height: 1.6; }}
  .reason {{ background: #fef3c7; border: 1px solid #fde68a; border-radius: 10px;
             padding: 12px 14px; margin: 14px 0; font-size: 13px; color: #78350f; }}
  .actions {{ margin-top: 22px; }}
  .btn {{ display: inline-block; padding: 10px 18px; background: #0f172a;
          color: #fff; text-decoration: none; border-radius: 8px;
          font-weight: 600; font-size: 14px; }}
  .footer {{ padding: 14px 32px; font-size: 11px; color: #94a3b8;
             border-top: 1px solid #f1f5f9; }}
</style></head><body>
<div class="card">
  <div class="hero">
    <div class="icon">🚫</div>
    <div class="title">{safe_name}<br>ถูกระงับการใช้งาน</div>
  </div>
  <div class="body">
    <p>ระบบนี้ถูก admin <strong>ระงับการใช้งานชั่วคราว</strong> —
       ไม่สามารถเข้าใช้งานได้จนกว่าจะถูกเปิดใช้งานใหม่</p>
    <div class="reason">
      <strong>เหตุผลที่พบบ่อย:</strong><br>
      • กำลังตรวจสอบความปลอดภัย<br>
      • รอแก้ไขปัญหาจากเจ้าของระบบ<br>
      • ละเมิดเงื่อนไขการใช้งาน
    </div>
    <p style="font-size:13px;color:#64748b;">
      หากคิดว่าเป็นข้อผิดพลาด กรุณาติดต่อผู้ดูแลระบบ
    </p>
    <div class="actions">
      <a href="javascript:history.back()" class="btn">← กลับหน้าก่อน</a>
    </div>
  </div>
  <div class="footer">
    Central Auth Hub · HTTP 503 Service Unavailable
  </div>
</div>
</body></html>"""


# ============ ตัวช่วยทดสอบ (dev only) ============


def _dev_only() -> None:
    """404 ใน production — dev-only endpoint ไม่ควรเข้าถึงได้บนระบบจริง.

    404 (ไม่ใช่ 403) เพื่อไม่ให้ leak ว่ามี endpoint นี้อยู่.
    """
    if settings.app_env == "production":
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/pkce-helper")
def pkce_helper():
    """สร้างคู่ code_verifier / code_challenge สำหรับทดสอบ (dev only).

    ในระบบจริง subsystem จะสร้างคู่นี้เอง — endpoint นี้มีไว้ช่วยทดสอบ Week 4
    """
    _dev_only()
    verifier, challenge = generate_pkce_pair()
    return {
        "code_verifier": verifier,
        "code_challenge": challenge,
        "note": "ใช้ code_challenge ตอนเรียก /oauth/authorize และ code_verifier ตอน /oauth/token",
    }


@router.get("/test-callback", response_class=HTMLResponse)
def test_callback(code: str = "", state: str = ""):
    """หน้าจำลอง redirect_uri ของ subsystem — แสดง code + state ที่ Hub ส่งกลับมา (dev only).

    ตอนทดสอบ: ลงทะเบียน subsystem ด้วย
        redirect_uri = http://localhost:8000/oauth/test-callback
    """
    _dev_only()
    # escape code/state — เป็น query param ที่ client คุมได้ (กัน reflected XSS)
    import html as _html

    code = _html.escape(code)
    state = _html.escape(state)
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
