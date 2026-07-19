"""TOTP authenticator router — enroll / lifecycle / step-up (Fallback Auth Factor).

Endpoints (mount ไม่มี prefix — full paths):
  POST /auth/account/totp/enroll/start   [gate totp_enroll] → QR (otpauth_uri) + secret
  POST /auth/account/totp/enroll/verify  → ยืนยัน code → ACTIVE
  POST /auth/account/totp/suspend|reactivate | DELETE /auth/account/totp  [gate]
  GET  /auth/account/totp/status
  POST /auth/stepup/totp/verify          → grant step-up (method=totp)

Enroll/lifecycle = critical action (กัน session hijack วาง factor) + alert email.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, get_current_user
from app.models import User
from app.services import stepup_cache, totp_service
from app.services.audit_service import log_action
from app.services.critical_action_policy import _bearer, _extract_jti, gate
from app.services.email_service import _send_html_email

log = logging.getLogger(__name__)
router = APIRouter()


class TotpCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


def _alert(to: str | None, action_th: str) -> None:
    """แจ้งเตือนการเปลี่ยนแปลง TOTP ทาง email (fail-safe)."""
    if not to:
        return
    html = (
        f'<div style="font-family:system-ui,sans-serif">'
        f"<h2>Authenticator (TOTP) — {action_th}</h2>"
        f"<p>บัญชีของคุณใน Central Auth Hub เพิ่ง <b>{action_th}</b> ตัวยืนยันตัวตน Authenticator</p>"
        f'<p style="color:#b91c1c;font-size:13px">ถ้าไม่ใช่คุณ กรุณาติดต่อผู้ดูแลระบบทันที</p></div>'
    )
    try:
        _send_html_email(to, f"แจ้งเตือน: Authenticator {action_th}", html, action_th)
    except Exception as e:  # noqa: BLE001
        log.warning("totp alert email failed: %r", e)


# ── Enroll ──


@router.post(
    "/auth/account/totp/enroll/start",
    dependencies=[Depends(gate("totp_enroll"))],
)
def totp_enroll_start(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """สร้าง secret ใหม่ (REGISTERED) → คืน otpauth_uri (QR) + secret (manual entry)."""
    secret, uri = totp_service.start_enroll(user.id, db)
    db.commit()
    return {"otpauth_uri": uri, "secret": secret}


@router.post("/auth/account/totp/enroll/verify")
def totp_enroll_verify(
    body: TotpCodeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ยืนยัน code แรก → REGISTERED → ACTIVE."""
    if not totp_service.confirm_enroll(user.id, body.code, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "totp_verify_failed", "message": "รหัสไม่ถูกต้อง — ลองใหม่"},
        )
    log_action(
        db,
        actor_id=user.id,
        action="totp_enrolled",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
    )
    db.commit()
    _alert(user.email, "เปิดใช้งาน")
    return {"enabled": True, "status": "ACTIVE"}


# ── Lifecycle ──


@router.post("/auth/account/totp/suspend", dependencies=[Depends(gate("totp_enroll"))])
def totp_suspend(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not totp_service.suspend(user.id, db):
        raise HTTPException(status_code=404, detail="ไม่มี Authenticator")
    log_action(
        db,
        actor_id=user.id,
        action="totp_suspended",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
    )
    db.commit()
    _alert(user.email, "ระงับชั่วคราว")
    return {"status": "SUSPENDED"}


@router.post(
    "/auth/account/totp/reactivate", dependencies=[Depends(gate("totp_enroll"))]
)
def totp_reactivate(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not totp_service.reactivate(user.id, db):
        raise HTTPException(status_code=404, detail="ไม่มี Authenticator")
    log_action(
        db,
        actor_id=user.id,
        action="totp_reactivated",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
    )
    db.commit()
    _alert(user.email, "เปิดใช้งานอีกครั้ง")
    return {"status": "ACTIVE"}


@router.delete("/auth/account/totp", dependencies=[Depends(gate("totp_enroll"))])
def totp_revoke(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not totp_service.revoke(user.id, db):
        raise HTTPException(status_code=404, detail="ไม่มี Authenticator")
    log_action(
        db,
        actor_id=user.id,
        action="totp_revoked",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
    )
    db.commit()
    _alert(user.email, "ลบออก")
    return {"status": "REVOKED"}


@router.get("/auth/account/totp/status")
def totp_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = totp_service.get_row(user.id, db)
    return {
        "enabled": bool(row and row.status == "ACTIVE"),
        "status": row.status if row else None,
    }


@router.get("/auth/account/credentials")
def my_credentials(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Credential Management (self) — Google + Passkey + TOTP + recovery status."""
    from app.services import credential_service

    return credential_service.list_credentials(user, db)


# ── Step-up ──


@router.post("/auth/stepup/totp/verify")
def stepup_totp_verify(
    body: TotpCodeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """ยืนยัน TOTP → grant step-up (method=totp) → critical action ผ่านได้ (ยกเว้น change_google)."""
    if not totp_service.verify_active(user.id, body.code, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "totp_verify_failed", "message": "รหัสไม่ถูกต้อง"},
        )
    jti = _extract_jti(credentials)
    if not jti:
        raise HTTPException(status_code=400, detail="token ไม่มี jti")
    stepup_cache.set_granted(
        str(user.id), jti, method="totp", ip=get_client_ip(request)
    )
    db.commit()
    log_action(
        db,
        actor_id=user.id,
        action="stepup_totp_success",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
    )
    db.commit()
    from app.config import settings

    return {"granted": True, "ttl_sec": settings.stepup_cache_ttl_sec}
