"""TOTP service — authenticator app (RFC 6238) เป็น Fallback Authentication Factor.

Lifecycle (models.CREDENTIAL_STATUSES):
  enroll/start  → row REGISTERED (secret encrypted, ยังใช้ไม่ได้)
  enroll/verify → ACTIVE (พร้อมใช้ step-up / recovery)
  suspend/reactivate/revoke → SUSPENDED / ACTIVE / REVOKED

Secret เก็บ **Fernet-encrypted** (secret_service.encrypt_secret) — reversible เพราะต้องเอามา
gen/verify code (ต่างจาก passkey/backup-code ที่ hash ทางเดียว).
เฉพาะ status=ACTIVE เท่านั้นที่ verify ผ่าน.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID as UUIDType

import pyotp
from sqlalchemy.orm import Session

from app.models import (
    CRED_ACTIVE,
    CRED_REGISTERED,
    CRED_REVOKED,
    CRED_SUSPENDED,
    UserTotpCredential,
)
from app.services.secret_service import decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)

_ISSUER = "Central Auth Hub"


def generate_secret() -> str:
    """สุ่ม base32 secret (160-bit) สำหรับ authenticator."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    """otpauth:// URI สำหรับสร้าง QR (สแกนด้วย Google/MS Authenticator)."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=_ISSUER)


def verify(secret: str, code: str, valid_window: int = 1) -> bool:
    """ตรวจ code 6 หลัก — valid_window=1 (ยอม ±1 step กัน clock skew, ไม่กว้างเกิน)."""
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=valid_window)
    except Exception as e:  # noqa: BLE001 — code รูปแบบผิด ฯลฯ
        log.warning("totp verify error: %r", e)
        return False


# ── row helpers ──


def get_row(user_id: UUIDType | str, db: Session) -> UserTotpCredential | None:
    return (
        db.query(UserTotpCredential)
        .filter(UserTotpCredential.user_id == user_id)
        .first()
    )


def is_enabled(user_id: UUIDType | str, db: Session) -> bool:
    row = get_row(user_id, db)
    return bool(row and row.status == CRED_ACTIVE)


def start_enroll(user_id: UUIDType | str, db: Session) -> tuple[str, str]:
    """สร้าง secret ใหม่ → upsert row status=REGISTERED. คืน (secret, otpauth_uri).

    ถ้ามี row เดิม (REGISTERED ค้าง หรือ REVOKED) → เขียนทับด้วย secret ใหม่ + REGISTERED.
    ถ้า ACTIVE อยู่แล้ว → เขียนทับ (re-enroll = ต้อง verify ใหม่).
    """
    secret = generate_secret()
    row = get_row(user_id, db)
    now = datetime.utcnow()
    if row is None:
        row = UserTotpCredential(
            user_id=user_id,
            secret_encrypted=encrypt_secret(secret),
            status=CRED_REGISTERED,
            created_at=now,
        )
        db.add(row)
    else:
        row.secret_encrypted = encrypt_secret(secret)
        row.status = CRED_REGISTERED
        row.enabled_at = None
        row.created_at = now
    db.flush()
    return secret, provisioning_uri(secret, str(user_id))


def confirm_enroll(user_id: UUIDType | str, code: str, db: Session) -> bool:
    """ตรวจ code กับ REGISTERED row → ACTIVE. คืน True ถ้าสำเร็จ."""
    row = get_row(user_id, db)
    if row is None or row.status not in (CRED_REGISTERED, CRED_ACTIVE):
        return False
    secret = decrypt_secret(row.secret_encrypted)
    if not verify(secret, code):
        return False
    row.status = CRED_ACTIVE
    row.enabled_at = datetime.utcnow()
    db.flush()
    return True


def verify_active(user_id: UUIDType | str, code: str, db: Session) -> bool:
    """ตรวจ code กับ ACTIVE credential เท่านั้น (step-up / recovery). update last_used_at."""
    row = get_row(user_id, db)
    if row is None or row.status != CRED_ACTIVE:
        return False
    if not verify(decrypt_secret(row.secret_encrypted), code):
        return False
    row.last_used_at = datetime.utcnow()
    db.flush()
    return True


def set_status(user_id: UUIDType | str, status: str, db: Session) -> bool:
    """เปลี่ยน lifecycle status (suspend/reactivate/revoke). คืน True ถ้ามี row."""
    row = get_row(user_id, db)
    if row is None:
        return False
    row.status = status
    db.flush()
    return True


def suspend(user_id, db) -> bool:
    return set_status(user_id, CRED_SUSPENDED, db)


def reactivate(user_id, db) -> bool:
    return set_status(user_id, CRED_ACTIVE, db)


def revoke(user_id, db) -> bool:
    return set_status(user_id, CRED_REVOKED, db)
