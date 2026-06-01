"""MFA router — Email OTP challenge + verify.

Flow:
  /auth/google/callback (ML decision = mfa)
    └─> สร้าง MFAChallenge + ส่ง OTP email + redirect → /auth/mfa?challenge=<id>

  Frontend /auth/mfa
    ├─ POST /mfa/resend?challenge=<id>   # ส่ง OTP ใหม่ (rate-limited)
    └─ POST /mfa/verify                  # body: {challenge_id, otp}
                                            ↓ ถ้าผ่าน
                                          ออก JWT + redirect /dashboard
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip
from app.models import LoginSession, MFAChallenge, User
from app.rate_limiter import limiter
from app.services.audit_service import log_action
from app.services.jwt_service import create_access_token
from app.services.mfa_service import (
    generate_otp,
    hash_otp,
    send_otp_email,
    verify_otp,
)

router = APIRouter()

# ค่าคงที่ — แมตช์กับ auth.py
OTP_TTL_MIN = 5
MAX_ATTEMPTS = 5


class VerifyBody(BaseModel):
    challenge_id: str
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


# ─────────────────────────────────────────────────────────────
# POST /mfa/verify — ตรวจ OTP + ออก JWT
# ─────────────────────────────────────────────────────────────


@router.post("/verify")
@limiter.limit("10/minute")
def verify_mfa(
    body: VerifyBody,
    request: Request,
    db: Session = Depends(get_db),
):
    """Verify OTP — ถ้าผ่าน ออก JWT จริง + mark used.

    Failure modes:
      - 404: challenge ไม่พบ
      - 410: challenge หมดอายุ / ถูกใช้แล้ว / lockout (attempts >= MAX)
      - 401: OTP ไม่ถูกต้อง (attempts += 1)
    """
    challenge = (
        db.query(MFAChallenge).filter(MFAChallenge.id == body.challenge_id).first()
    )
    if not challenge:
        raise HTTPException(status_code=404, detail="ไม่พบ MFA challenge")

    ip = get_client_ip(request)

    # used แล้ว
    if challenge.used_at is not None:
        raise HTTPException(status_code=410, detail="OTP นี้ถูกใช้ไปแล้ว — login ใหม่")

    # expired
    if datetime.utcnow() > challenge.expires_at:
        raise HTTPException(status_code=410, detail="OTP หมดอายุแล้ว — login ใหม่")

    # lockout
    if challenge.attempts >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=410,
            detail=f"ใส่ผิดเกิน {MAX_ATTEMPTS} ครั้ง — challenge ถูก lock; login ใหม่",
        )

    # verify
    if not verify_otp(challenge.code_hash, body.otp):
        challenge.attempts += 1
        log_action(
            db,
            actor_id=challenge.user_id,
            action="mfa_verify_failed",
            target_type="mfa_challenge",
            target_id=challenge.id,
            ip=ip,
            metadata={"attempts": challenge.attempts},
        )
        db.commit()
        remaining = MAX_ATTEMPTS - challenge.attempts
        raise HTTPException(
            status_code=401,
            detail=f"OTP ไม่ถูกต้อง (เหลือ {remaining} ครั้ง)",
        )

    # success — mark used + upgrade login_session decision
    challenge.used_at = datetime.utcnow()
    sess = (
        db.query(LoginSession)
        .filter(LoginSession.id == challenge.login_session_id)
        .first()
    )
    if sess:
        sess.decision = "mfa_passed"

    user = db.query(User).filter(User.id == challenge.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบ user")

    log_action(
        db,
        actor_id=user.id,
        action="mfa_verified",
        target_type="user",
        target_id=user.id,
        ip=ip,
        metadata={"challenge_id": str(challenge.id)},
    )
    db.commit()

    access_token = create_access_token(user)

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
            },
        }
    )


# ─────────────────────────────────────────────────────────────
# POST /mfa/resend — ส่ง OTP ใหม่ (rate-limited 3/min)
# ─────────────────────────────────────────────────────────────


class ResendBody(BaseModel):
    challenge_id: str


@router.post("/resend")
@limiter.limit("3/minute")
def resend_otp(
    body: ResendBody,
    request: Request,
    db: Session = Depends(get_db),
):
    """ส่ง OTP ใหม่สำหรับ challenge เดิม (rotate code + reset expires).

    ใช้กรณี user ไม่ได้รับ email ครั้งแรก
    """
    challenge = (
        db.query(MFAChallenge).filter(MFAChallenge.id == body.challenge_id).first()
    )
    if not challenge:
        raise HTTPException(status_code=404, detail="ไม่พบ MFA challenge")
    if challenge.used_at is not None:
        raise HTTPException(status_code=410, detail="Challenge นี้ถูกใช้แล้ว")
    if challenge.attempts >= MAX_ATTEMPTS:
        raise HTTPException(status_code=410, detail="Challenge ถูก lock — login ใหม่")

    user = db.query(User).filter(User.id == challenge.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบ user")

    # rotate OTP + extend expiry
    otp = generate_otp()
    challenge.code_hash = hash_otp(otp)
    challenge.expires_at = datetime.utcnow() + timedelta(minutes=OTP_TTL_MIN)

    log_action(
        db,
        actor_id=user.id,
        action="mfa_otp_resent",
        target_type="mfa_challenge",
        target_id=challenge.id,
        ip=get_client_ip(request),
        metadata={"method": challenge.method},
    )
    db.commit()

    send_otp_email(user.email, otp, challenge.expires_at)

    return {
        "challenge_id": str(challenge.id),
        "method": challenge.method,
        "expires_at": challenge.expires_at.isoformat(),
        "message": "ส่ง OTP ใหม่แล้ว ตรวจ email",
    }


# ─────────────────────────────────────────────────────────────
# GET /mfa/challenge/{id} — meta (ไม่เผยรหัส) สำหรับหน้า frontend
# ─────────────────────────────────────────────────────────────


@router.get("/challenge/{challenge_id}")
def get_challenge_meta(challenge_id: str, db: Session = Depends(get_db)):
    """คืน meta ของ challenge (ไม่เผย OTP) — ให้ frontend แสดง email mask + countdown."""
    challenge = db.query(MFAChallenge).filter(MFAChallenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="ไม่พบ challenge")

    user = db.query(User).filter(User.id == challenge.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบ user")

    # mask email: a***@example.com
    parts = user.email.split("@")
    masked = (
        (parts[0][0] + "***" + (parts[0][-1] if len(parts[0]) > 1 else ""))
        + "@"
        + parts[1]
        if len(parts) == 2 and parts[0]
        else "***"
    )

    return {
        "challenge_id": str(challenge.id),
        "method": challenge.method,
        "email_masked": masked,
        "expires_at": challenge.expires_at.isoformat(),
        "attempts": challenge.attempts,
        "max_attempts": MAX_ATTEMPTS,
        "used": challenge.used_at is not None,
        "expired": datetime.utcnow() > challenge.expires_at,
    }
