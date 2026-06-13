"""Passkey recovery service — Phase 1 + Phase 4 (plan v3).

Phase 1 scope (this file):
    - generate_backup_codes()    — 10 codes, Argon2id hash, show-once
    - acknowledge_backup_codes() — mark all unused codes as acknowledged
                                   (Improvement #3 — mandatory UX before close)
    - get_status()               — used / remaining / low warning (Improvement #7)

Phase 4 scope (will be added later):
    - verify_backup_code()       — recovery flow: revoke all Passkeys, require re-register
    - email_otp_begin/verify()   — fallback recovery via email

Format: AB3D-7K9P (8 chars + dash, alphabet 32 chars no 0/1/I/O).
Entropy ≈ 40 bits per code = 1.1×10^12 combinations.
Storage: Argon2id (reuses ``secret_service.hash_secret``).
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID as UUIDType

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PasskeyBackupCode, PasskeyCredential, User
from app.redis_client import redis_client
from app.services import mfa_service
from app.services.secret_service import hash_secret, verify_secret

log = logging.getLogger(__name__)

# Recovery via email OTP — Redis state (ไม่ใช้ MFAChallenge เพราะไม่มี login_session)
_OTP_PREFIX = "passkey:recover:otp"
_OTP_TTL = 300  # 5 นาที
_OTP_MAX_ATTEMPTS = 5

# Alphabet — 32 chars (5 bits each), excludes ambiguous 0/1/I/O
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # pragma: allowlist secret
_SYSTEM_RNG = secrets.SystemRandom()

# Threshold for "low backup codes" warning (Improvement #7)
# 7+ used out of 10 → frontend shows toast "regenerate now"
_LOW_THRESHOLD = 7


def _generate_one_code() -> str:
    """One code formatted as XXXX-XXXX (8 chars + dash)."""
    parts = ["".join(_SYSTEM_RNG.choice(_ALPHABET) for _ in range(4)) for _ in range(2)]
    return "-".join(parts)


def _current_generation(user_id: UUIDType | str, db: Session) -> int:
    """Highest generation number for this user (0 if none yet)."""
    g = (
        db.query(func.max(PasskeyBackupCode.generation))
        .filter(PasskeyBackupCode.user_id == user_id)
        .scalar()
    )
    return g or 0


def generate_backup_codes(
    user_id: UUIDType | str,
    db: Session,
    *,
    rotate: bool = False,
) -> list[str]:
    """Generate N codes (default 10) — plaintext returned once for user to save.

    Hashes stored with Argon2id. If ``rotate=True`` (regenerate flow), bumps
    generation and inserts a new batch — old generations remain in DB for audit
    but business logic treats only highest generation as valid.

    Returns: list[str] of plaintext codes (caller MUST not log/persist these).
    """
    count = settings.webauthn_backup_codes_count
    if count <= 0:
        log.warning("webauthn_backup_codes_count=%d — using default 10", count)
        count = 10

    current = _current_generation(user_id, db)
    next_gen = current + 1 if (rotate or current == 0) else current
    if current > 0 and not rotate:
        # Don't generate duplicate batch unless explicitly rotating
        raise RuntimeError(
            f"Backup codes already exist (generation={current}). "
            "Use rotate=True to regenerate."
        )

    plaintext: list[str] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for _ in range(count):
        code = _generate_one_code()
        plaintext.append(code)
        row = PasskeyBackupCode(
            user_id=user_id,
            code_hash=hash_secret(code),
            generation=next_gen,
            created_at=now,
        )
        db.add(row)
    db.flush()
    return plaintext


def acknowledge_backup_codes(user_id: UUIDType | str, db: Session) -> int:
    """Mark all unused + unacknowledged codes (current generation) as acknowledged.

    Frontend MUST call this before closing the modal (Improvement #3 —
    mandatory). Returns count of rows updated.
    """
    current = _current_generation(user_id, db)
    if current == 0:
        return 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    updated = (
        db.query(PasskeyBackupCode)
        .filter(
            PasskeyBackupCode.user_id == user_id,
            PasskeyBackupCode.generation == current,
            PasskeyBackupCode.acknowledged_at.is_(None),
        )
        .update({PasskeyBackupCode.acknowledged_at: now}, synchronize_session=False)
    )
    return updated


def get_status(user_id: UUIDType | str, db: Session) -> dict:
    """Return: generation, total, used, remaining, low, acknowledged.

    Does NOT return code plaintext — that's only at generate time.
    """
    current = _current_generation(user_id, db)
    if current == 0:
        return {
            "generation": 0,
            "total": 0,
            "used": 0,
            "remaining": 0,
            "low": False,
            "acknowledged": False,
        }
    rows = (
        db.query(
            func.count(PasskeyBackupCode.id),
            func.count(PasskeyBackupCode.used_at),
            func.count(PasskeyBackupCode.acknowledged_at),
        )
        .filter(
            PasskeyBackupCode.user_id == user_id,
            PasskeyBackupCode.generation == current,
        )
        .first()
    )
    total, used, ack = rows
    remaining = total - used
    return {
        "generation": current,
        "total": total,
        "used": used,
        "remaining": remaining,
        "low": used >= _LOW_THRESHOLD,  # Improvement #7
        "acknowledged": ack > 0,
    }


# ─── Recovery (Phase 4) — Decision #6: backup code → email OTP → admin ──────
#
# ทุก recovery = "lock down" — revoke passkey ทั้งหมด (device หาย/ถูกขโมย)
# user ต้อง login ด้วย Google (fallback) แล้ว enroll passkey ใหม่.
# ไม่ออก JWT จาก recovery (กัน abuse + รองรับทุก user_type).


def _normalize_code(raw: str) -> str:
    """Normalize backup code: uppercase, strip, ใส่ dash ให้รูปแบบ XXXX-XXXX.

    รับได้ทั้ง 'ab3d7k9p', 'AB3D-7K9P', 'ab3d 7k9p' → 'AB3D-7K9P'
    """
    s = "".join(c for c in (raw or "").upper() if c.isalnum())
    if len(s) == 8:
        return f"{s[:4]}-{s[4:]}"
    return s  # ปล่อยให้ verify fail ถ้ารูปแบบผิด


def _revoke_all_passkeys(user_id: UUIDType | str, db: Session, *, reason: str) -> int:
    """Soft-revoke active passkeys ทั้งหมดของ user. คืนจำนวนที่ revoke."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    count = (
        db.query(PasskeyCredential)
        .filter(
            PasskeyCredential.user_id == user_id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .update(
            {
                PasskeyCredential.revoked_at: now,
                PasskeyCredential.revoked_reason: reason,
            },
            synchronize_session=False,
        )
    )
    return count


def verify_backup_code(
    user_id: UUIDType | str,
    code: str,
    db: Session,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> bool:
    """ตรวจ backup code (current generation, unused) → mark used + revoke passkeys.

    Returns True ถ้า code ถูก (และทำ revoke แล้ว), False ถ้าผิด/ใช้แล้ว/ไม่มี.
    Argon2id verify ทีละ row (rare op + rate-limited ที่ router).
    """
    normalized = _normalize_code(code)
    if len(normalized) != 9:  # XXXX-XXXX
        return False
    current = _current_generation(user_id, db)
    if current == 0:
        return False
    rows = (
        db.query(PasskeyBackupCode)
        .filter(
            PasskeyBackupCode.user_id == user_id,
            PasskeyBackupCode.generation == current,
            PasskeyBackupCode.used_at.is_(None),
        )
        .all()
    )
    matched = None
    for r in rows:
        if verify_secret(r.code_hash, normalized):
            matched = r
            break
    if matched is None:
        return False

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    matched.used_at = now
    matched.used_ip = ip
    matched.used_user_agent = (user_agent or None) and user_agent[:500]
    _revoke_all_passkeys(user_id, db, reason="backup_recovery")
    db.flush()

    # เตือนทาง email ถ้า codes เหลือน้อย (ไม่ส่ง codes — แค่เตือน + ลิงก์)
    if get_status(user_id, db).get("remaining", 99) <= _LOW_REMAINING:
        _maybe_send_low_codes_email(user_id, db)
    return True


_LOW_REMAINING = 3  # เหลือ <= 3 → เตือน


def _maybe_send_low_codes_email(user_id: UUIDType | str, db: Session) -> None:
    """ส่ง email เตือน 'backup codes ใกล้หมด' + ลิงก์ regenerate. fail-safe.

    ไม่ส่งตัว codes ทาง email (security) — แค่เตือน + ลิงก์ไปขอชุดใหม่ผ่าน OTP.
    """
    try:
        from app.config import settings
        from app.services.email_service import _send_html_email, _smtp_configured

        if not _smtp_configured():
            return
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.email:
            return
        remaining = get_status(user_id, db).get("remaining", 0)
        link = f"{settings.hub_base_url}/oauth/passkey/recover"
        html = f"""<div style="font-family:sans-serif">
<h2>Backup codes ใกล้หมด</h2>
<p>บัญชี {user.email} เหลือ backup codes <b>{remaining}</b> ตัว</p>
<p>แนะนำให้สร้างชุดใหม่เพื่อกู้บัญชีได้ในอนาคต:</p>
<p><a href="{link}" style="background:#059669;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">สร้าง Backup Codes ใหม่</a></p>
<p style="color:#888;font-size:12px">เราจะไม่ส่ง codes ทาง email — กดลิงก์เพื่อยืนยันตัวตน (OTP) แล้วรับชุดใหม่บนหน้าจอ</p>
</div>"""
        _send_html_email(
            user.email,
            "Backup codes ใกล้หมด — Central Auth Hub",
            html,
            f"Backup codes เหลือ {remaining} ตัว — สร้างใหม่ที่ {link}",
        )
    except Exception as e:
        log.warning("low codes email failed: %r", e)


def check_low_codes(user_id: UUIDType | str, db: Session) -> bool:
    """Improvement #7 — True ถ้าใช้ backup code ไป >= 7/10 (ควร regenerate)."""
    return get_status(user_id, db).get("low", False)


def has_backup_codes(user_id: UUIDType | str, db: Session) -> bool:
    """True ถ้า user เคยมี backup codes แล้ว (generation > 0).

    ใช้ guard ตอน enroll/register passkey — ป้องกัน generate_backup_codes ซ้ำ
    (bug: re-enroll หลัง recovery → passkey count=0 แต่ codes มีอยู่ → RuntimeError).
    """
    return _current_generation(user_id, db) > 0


# ─── Email OTP recovery ─────────────────────────────────────────────────────


def _otp_key(email: str) -> str:
    return f"{_OTP_PREFIX}:{email.lower()}"


def email_otp_begin(email: str, db: Session, *, purpose: str = "recovery") -> bool:
    """สร้าง OTP + ส่ง email (ถ้า user มีจริง). Opaque — คืน True เสมอ (anti-enum).

    purpose: "recovery" (revoke passkey + codes ใหม่) | "regenerate" (codes ใหม่อย่างเดียว)
    purpose ถูก bind ใน Redis → OTP ของ regenerate ใช้กับ recovery verify ไม่ได้ (กันสับสน).
    """
    email = (email or "").strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is not None:
        otp = mfa_service.generate_otp()
        expires_at = datetime.utcnow() + timedelta(seconds=_OTP_TTL)
        redis_client.setex(
            _otp_key(email),
            _OTP_TTL,
            json.dumps(
                {"hash": mfa_service.hash_otp(otp), "attempts": 0, "purpose": purpose}
            ),
        )
        try:
            mfa_service.send_otp_email(email, otp, expires_at)
        except Exception as e:  # fail-safe — ส่ง email ไม่ได้ไม่ทำให้ flow ล่ม
            log.warning("passkey OTP email send failed: %r", e)
    return True


def email_otp_verify(
    email: str,
    otp: str,
    db: Session,
    *,
    purpose: str = "recovery",
    ip: str | None = None,
    user_agent: str | None = None,
) -> list[str] | None:
    """ตรวจ OTP → ออก backup codes ชุดใหม่. lockout 5 ครั้ง.

    purpose="recovery"   → revoke passkey + codes ใหม่ (device หาย)
    purpose="regenerate" → codes ใหม่อย่างเดียว ไม่แตะ passkey (codes หาย/ใกล้หมด)

    purpose ต้องตรงกับที่ bind ตอน begin (กัน OTP ของ regenerate ถูกใช้ revoke passkey).
    Returns list[str] (codes ใหม่) ถ้าถูก, None ถ้าผิด/หมดอายุ/lockout/purpose ไม่ตรง.
    """
    email = (email or "").strip().lower()
    raw = redis_client.get(_otp_key(email))
    if not raw:
        return None
    data = json.loads(raw)
    if data.get("attempts", 0) >= _OTP_MAX_ATTEMPTS:
        redis_client.delete(_otp_key(email))  # lockout — ต้อง begin ใหม่
        return None
    # purpose binding — OTP ที่ขอเพื่อ regenerate ใช้กับ recovery ไม่ได้ (และกลับกัน)
    if data.get("purpose", "recovery") != purpose:
        return None

    if mfa_service.verify_otp(data["hash"], (otp or "").strip()):
        redis_client.delete(_otp_key(email))
        user = db.query(User).filter(func.lower(User.email) == email).first()
        if user is None:
            return None
        if purpose == "recovery":
            _revoke_all_passkeys(user.id, db, reason="email_recovery")
        # ออก backup codes ชุดใหม่ (rotate ถ้ามีเก่า)
        rotate = _current_generation(user.id, db) > 0
        codes = generate_backup_codes(user.id, db, rotate=rotate)
        db.flush()
        return codes

    # ผิด → attempts++
    data["attempts"] = data.get("attempts", 0) + 1
    ttl = redis_client.ttl(_otp_key(email))
    redis_client.setex(
        _otp_key(email), ttl if ttl and ttl > 0 else _OTP_TTL, json.dumps(data)
    )
    return None


def remaining_codes(user_id: UUIDType | str, db: Session) -> int:
    """จำนวน backup codes ที่ยังไม่ได้ใช้ (current generation)."""
    return get_status(user_id, db).get("remaining", 0)


def ensure_backup_codes(user_id: UUIDType | str, db: Session) -> list[str] | None:
    """ออก backup codes ถ้า user ไม่มี usable codes (remaining==0).

    Auto-heal: ใช้ตอน enroll/register passkey —
      - ไม่เคยมี (gen 0) → gen 1
      - มี usable codes → None (ไม่รบกวน codes ที่จดไว้)
      - มีแต่ใช้หมด → rotate ชุดใหม่ (ปิดช่องติดล็อกหลัง recovery)
    Returns codes ใหม่ (ให้ user เก็บ) หรือ None ถ้าไม่ต้องออกใหม่.
    """
    status = get_status(user_id, db)
    if status["remaining"] > 0:
        return None
    rotate = status["generation"] > 0
    return generate_backup_codes(user_id, db, rotate=rotate)


# ─── Admin reset ────────────────────────────────────────────────────────────


def admin_reset_passkeys(target_user_id: UUIDType | str, db: Session) -> int:
    """Admin revoke passkey ทั้งหมดของ user (กรณี user แจ้ง device หาย).

    คืนจำนวนที่ revoke. Router enforce require_hub_admin + audit PASSKEY_ADMIN_RESET.
    """
    return _revoke_all_passkeys(target_user_id, db, reason="admin_reset")
