"""Authentication router — Google OAuth flow + JWT issuance.

Flow (Week 2 — Hub <-> Google เท่านั้น ยังไม่รวม subsystem):
  1. GET /auth/google/login    -> redirect ผู้ใช้ไป Google
  2. GET /auth/google/callback -> Google ส่งกลับ -> หา user ใน DB -> ออก JWT
  3. GET /auth/me              -> ทดสอบ token (ต้องแนบ Bearer token)
  4. GET /.well-known/jwks.json -> public key สำหรับ verify
"""

from datetime import datetime

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, get_current_user
from app.rate_limiter import limiter
from app.models import LoginSession, User
from app.services.audit_service import log_action
from app.services.feature_extraction import (
    extract_session_features,
    parse_browser,
    parse_device_type,
    parse_os_name,
)
from app.services.geoip import lookup_country
from app.services.hooks import (
    EVT_LOGIN_FAILURE,
    EVT_LOGIN_PRE,
    EVT_LOGIN_SUCCESS,
    emit,
)
from app.services.jwt_service import create_access_token
from app.services.ip_blacklist import is_blacklisted
from app.services.alert_service import maybe_alert_ml_risk
from app.services.identity_challenge import is_user_challenged
from app.security.risk_engine import evaluate_login_risk

router = APIRouter()

# ============ ตั้งค่า OAuth client (Authlib) ============
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# ============ 1. เริ่ม login — redirect ไป Google ============


@router.get("/google/login")
@limiter.limit(settings.rate_limit_login)
async def google_login(request: Request):
    """พาผู้ใช้ไปหน้า login ของ Google. (rate-limited per-IP)"""
    await emit(
        EVT_LOGIN_PRE,
        {
            "ip": get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
        },
    )
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


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
    if user.user_type == "student":
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
                "นักศึกษาไม่สามารถเข้าระบบกลางโดยตรงได้ — "
                "กรุณาเข้าใช้ผ่านระบบย่อยที่ได้รับสิทธิ์ "
                "(เช่น ระบบหอพัก ระบบห้องสมุด)"
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
    geo_country = lookup_country(client_ip)

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
    db.add(login_session)
    db.flush()  # ต้องการ login_session.id สำหรับ MFA challenge

    # 5) Enforce mode + decision=block → ปฏิเสธ ก่อนออก JWT
    if actual_decision == "block":
        log_action(
            db,
            actor_id=user.id,
            action="hub_login_blocked_by_ml",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={"score": anomaly_score, "features": features},
        )
        db.commit()
        await emit(
            EVT_LOGIN_FAILURE,
            {
                "email": email,
                "reason": "ml_blocked",
                "ip": client_ip,
                "anomaly_score": anomaly_score,
            },
        )
        raise HTTPException(
            status_code=403,
            detail=(
                f"การ login ถูกบล็อกโดยระบบตรวจสอบความปลอดภัย "
                f"(anomaly_score={anomaly_score}) — ติดต่อ admin หากเป็นเรื่องผิดพลาด"
            ),
        )

    # 6) Enforce mode + decision=mfa → สร้าง MFA challenge + redirect ไป /auth/mfa
    if actual_decision == "mfa":
        from datetime import timedelta

        from app.models import MFAChallenge
        from app.services.mfa_service import generate_otp, hash_otp, send_otp_email

        otp = generate_otp()
        expires_at = datetime.utcnow() + timedelta(minutes=5)
        challenge = MFAChallenge(
            user_id=user.id,
            login_session_id=login_session.id,
            code_hash=hash_otp(otp),
            method="email",
            expires_at=expires_at,
        )
        db.add(challenge)
        log_action(
            db,
            actor_id=user.id,
            action="mfa_challenge_issued",
            target_type="user",
            target_id=user.id,
            ip=client_ip,
            metadata={
                "session_id": str(login_session.id),
                "method": "email",
                "score": anomaly_score,
            },
        )
        db.commit()
        db.refresh(challenge)

        # ส่ง email (fail-safe — ถ้า SMTP ไม่ตั้งค่าจะ log warning)
        send_otp_email(user.email, otp, expires_at)

        # Redirect frontend ไปหน้ารับ OTP
        if settings.admin_frontend_url:
            return RedirectResponse(
                f"{settings.admin_frontend_url}/auth/mfa?challenge={challenge.id}",
                status_code=302,
            )
        # API client fallback
        return JSONResponse(
            {
                "mfa_required": True,
                "challenge_id": str(challenge.id),
                "method": "email",
                "expires_at": expires_at.isoformat(),
                "message": "กรุณาตรวจ email + กรอก OTP ที่ /auth/mfa",
            },
            status_code=202,
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
        return RedirectResponse(
            f"{settings.admin_frontend_url}/auth/callback?token={access_token}",
            status_code=302,
        )

    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.jwt_access_token_expire_minutes * 60,
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
