"""Account security settings — Always-2FA toggle + preferred factor + onboarding dismiss.

Endpoints (mount ไม่มี prefix — full paths):
  GET   /auth/account/security-status         → flags สำหรับ UI (การ์ด onboarding / toggle)
  PATCH /auth/account/security                → ตั้ง mfa_always / mfa_preferred_factor
  POST  /auth/account/security/dismiss-onboarding → กด "ไม่ต้องถามอีก"

หมายเหตุ: admin (is_hub_admin) ถูกบังคับ Always-2FA — ปิด mfa_always=false ไม่ได้
(server ignore) เพราะ effective_mfa_always อ่านจาก is_hub_admin ด้วย.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, get_current_user
from app.models import User
from app.services import mfa_policy, totp_service, webauthn_service
from app.services.audit_service import log_action

log = logging.getLogger(__name__)
router = APIRouter()

_VALID_FACTORS = {"passkey", "totp"}


class SecurityPatch(BaseModel):
    mfa_always: bool | None = Field(default=None)
    mfa_preferred_factor: str | None = Field(default=None)


def _status_dict(user: User, db: Session) -> dict:
    has_passkey = webauthn_service.count_active(user.id, db) > 0
    has_totp = totp_service.is_enabled(user.id, db)
    snoozed = user.security_onboarding_snoozed_until
    return {
        "mfa_always": bool(user.mfa_always),
        "effective_mfa_always": user.effective_mfa_always,
        "is_admin": bool(user.is_hub_admin),
        "mfa_preferred_factor": user.mfa_preferred_factor,
        "has_passkey": has_passkey,
        "has_totp": has_totp,
        "has_second_factor": has_passkey or has_totp,
        "security_onboarding_dismissed": bool(user.security_onboarding_dismissed),
        "security_onboarding_snoozed_until": snoozed.isoformat() if snoozed else None,
        # source of truth เดียวกับ OAuth interstitial — frontend ใช้ตัดสินใจแสดงการ์ด
        "should_prompt_setup": mfa_policy.should_prompt_setup(user, db),
    }


@router.get("/auth/account/security-status")
async def security_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """flags สำหรับ frontend — decide การ์ด onboarding + สถานะ Always-2FA."""
    return _status_dict(user, db)


@router.patch("/auth/account/security")
async def update_security(
    request: Request,
    body: SecurityPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ตั้งค่า Always-2FA / preferred factor.

    admin ปิด mfa_always ไม่ได้ (ignore false) — effective ยังบังคับผ่าน is_hub_admin.
    """
    changed = {}

    if body.mfa_always is not None:
        # admin: ห้ามปิด (ignore false) — บังคับเสมอ
        if user.is_hub_admin and body.mfa_always is False:
            pass  # ignore — effective_mfa_always ยัง True อยู่แล้ว
        else:
            user.mfa_always = body.mfa_always
            changed["mfa_always"] = body.mfa_always

    if body.mfa_preferred_factor is not None:
        pref = body.mfa_preferred_factor.strip().lower()
        # ยอมรับเฉพาะ factor ที่ valid หรือ "" (ล้างค่า)
        if pref == "":
            user.mfa_preferred_factor = None
            changed["mfa_preferred_factor"] = None
        elif pref in _VALID_FACTORS:
            user.mfa_preferred_factor = pref
            changed["mfa_preferred_factor"] = pref

    if changed:
        log_action(
            db,
            actor_id=user.id,
            action="account_security_updated",
            target_type="user",
            target_id=user.id,
            ip=get_client_ip(request),
            metadata={"changed_by": "SELF", **changed},
        )
    db.commit()
    db.refresh(user)
    return _status_dict(user, db)


@router.post("/auth/account/security/snooze-onboarding")
async def snooze_onboarding(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """กด 'ข้ามไปก่อน' → พักเตือน 7 วัน แล้วเตือนใหม่ (ไม่บล็อกการใช้งาน)."""
    mfa_policy.snooze_onboarding(user)
    log_action(
        db,
        actor_id=user.id,
        action="security_onboarding_snoozed",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"days": mfa_policy.ONBOARDING_SNOOZE_DAYS},
    )
    db.commit()
    return {
        "snoozed": True,
        "until": user.security_onboarding_snoozed_until.isoformat(),
    }


@router.post("/auth/account/security/dismiss-onboarding")
async def dismiss_onboarding(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """กด 'ไม่ต้องถามอีก' ในการ์ดชวนตั้งความปลอดภัยหลัง login (per-account)."""
    user.security_onboarding_dismissed = True
    log_action(
        db,
        actor_id=user.id,
        action="security_onboarding_dismissed",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
    )
    db.commit()
    return {"dismissed": True}
