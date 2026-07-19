"""Credential Management — มุมมองรวม credential ของ user (GOOGLE + PASSKEY + TOTP).

credential_type ∈ {GOOGLE, PASSKEY, TOTP}:
  - GOOGLE = virtual (derived จาก user.email/google_sub/email_verified — ไม่มีตาราง)
  - PASSKEY = passkey_credentials (ต่อ device)
  - TOTP = user_totp_credentials

recovery_ready = มี ACTIVE Passkey OR ACTIVE TOTP (backup code ไม่นับ — re-link Google ไม่ได้).
"""

from __future__ import annotations

from uuid import UUID as UUIDType

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    CRED_ACTIVE,
    AuditLog,
    LoginSession,
    PasskeyCredential,
    User,
)
from app.services import passkey_recovery, totp_service


def _iso(dt):
    return dt.isoformat() if dt else None


def recovery_ready(user_id: UUIDType | str, db: Session) -> bool:
    """พร้อมกู้บัญชี self-service (re-link Google) ไหม — ต้องมี ACTIVE passkey หรือ TOTP."""
    has_passkey = (
        db.query(PasskeyCredential.id)
        .filter(
            PasskeyCredential.user_id == user_id,
            PasskeyCredential.status == CRED_ACTIVE,
        )
        .first()
        is not None
    )
    return has_passkey or totp_service.is_enabled(user_id, db)


def list_credentials(user: User, db: Session) -> dict:
    """คืน credential ทั้งหมด + สรุป recovery status ของ user."""
    creds: list[dict] = []

    # GOOGLE (virtual)
    last_login = (
        db.query(func.max(LoginSession.created_at))
        .filter(LoginSession.user_id == user.id)
        .scalar()
    )
    last_changed = (
        db.query(func.max(AuditLog.created_at))
        .filter(
            AuditLog.target_id == user.id,
            AuditLog.action == "account_google_changed",
        )
        .scalar()
    )
    creds.append(
        {
            "credential_type": "GOOGLE",
            "label": user.email,
            "status": "verified" if user.email_verified else "unverified",
            "linked": bool(user.google_sub),
            "last_login": _iso(last_login),
            "last_changed": _iso(last_changed),
        }
    )

    # PASSKEY (ต่อ device — โชว์ทุก status ยกเว้น REVOKED)
    passkeys = (
        db.query(PasskeyCredential)
        .filter(
            PasskeyCredential.user_id == user.id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .order_by(PasskeyCredential.created_at.desc())
        .all()
    )
    for pk in passkeys:
        creds.append(
            {
                "credential_type": "PASSKEY",
                "id": str(pk.id),
                "label": pk.device_name,
                "device_type": pk.device_type,
                "status": pk.status,
                "created_at": _iso(pk.created_at),
                "last_used": _iso(pk.last_used_at),
            }
        )

    # TOTP
    totp_row = totp_service.get_row(user.id, db)
    if totp_row and totp_row.status != "REVOKED":
        creds.append(
            {
                "credential_type": "TOTP",
                "id": str(totp_row.id),
                "label": "Authenticator app",
                "status": totp_row.status,
                "created_at": _iso(totp_row.created_at),
                "last_used": _iso(totp_row.last_used_at),
            }
        )

    backup = passkey_recovery.get_status(user.id, db)
    return {
        "credentials": creds,
        "backup_codes_remaining": backup.get("remaining", 0),
        "recovery_ready": recovery_ready(user.id, db),
    }
