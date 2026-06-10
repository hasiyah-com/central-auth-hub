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

import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID as UUIDType

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PasskeyBackupCode
from app.services.secret_service import hash_secret

log = logging.getLogger(__name__)

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
