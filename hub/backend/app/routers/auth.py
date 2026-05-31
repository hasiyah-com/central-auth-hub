"""Authentication router — Google OAuth flow + JWT issuance.

Flow (Week 2 — Hub <-> Google เท่านั้น ยังไม่รวม subsystem):
  1. GET /auth/google/login    -> redirect ผู้ใช้ไป Google
  2. GET /auth/google/callback -> Google ส่งกลับ -> หา user ใน DB -> ออก JWT
  3. GET /auth/me              -> ทดสอบ token (ต้องแนบ Bearer token)
  4. GET /.well-known/jwks.json -> public key สำหรับ verify
"""

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
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
from app.services.ml_client import get_anomaly_score

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

    # ===== ML Anomaly Detection (Hub-direct) =====
    # Admin / teacher / staff = high-value target — ตรวจเข้มกว่า user ปกติ
    # บันทึก login_sessions ด้วย subsystem_id=None เพื่อแยกจาก subsystem flow
    user_agent = request.headers.get("user-agent")
    geo_country = lookup_country(client_ip)

    # 1) สกัด features จาก session + history
    features = extract_session_features(
        db,
        user_id=user.id,
        ip=client_ip,
        user_agent=user_agent,
        geo_country=geo_country,
    )

    # 2) เรียก ML service (fail-safe: ถ้า ML ล่ม → pass + 0.0)
    ml_result = await get_anomaly_score(features)
    anomaly_score = ml_result["anomaly_score"]
    ml_decision = ml_result["decision"]

    # 3) Shadow mode → log เฉย ๆ / Enforce mode → ทำตาม ML จริง
    if settings.ml_shadow_mode:
        actual_decision = (
            "would_block"
            if ml_decision == "block"
            else "would_mfa"
            if ml_decision == "mfa"
            else "pass"
        )
    else:
        actual_decision = ml_decision

    # 4) บันทึก login_session (subsystem_id=None = Hub-direct)
    db.add(
        LoginSession(
            user_id=user.id,
            subsystem_id=None,
            ip=client_ip,
            user_agent=user_agent,
            geo_country=geo_country,
            os_name=parse_os_name(user_agent),
            browser=parse_browser(user_agent),
            device_type=parse_device_type(user_agent),
            anomaly_score=anomaly_score,
            decision=actual_decision,
        )
    )

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

    # (decision='mfa' ใน Enforce mode — MFA flow ยังไม่ implement
    #  ปล่อยผ่าน + log ไว้ทำต่อ Week 9-10)

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

    # ออก JWT
    access_token = create_access_token(user)

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
