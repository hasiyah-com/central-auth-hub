"""WebAuthn (Passkey) ceremony service — Phase 1 (plan v3).

Wraps the FIDO Alliance `webauthn` Python library to provide
RP-side registration and authentication ceremonies.

Phase 1 scope:
    - register_begin()    — generate PublicKeyCredentialCreationOptions
    - register_complete() — verify attestation + persist credential
    - count_active()      — used to enforce max_passkeys_per_user (Improvement #9)

Phase 2 (later): auth_begin/auth_complete
Phase 5 (later): stepup_begin/stepup_complete + counter regression handling

Conventions:
    - All challenges stored in Redis (atomic getdel pattern — B9)
    - Origin allowlist via ``settings.webauthn_origins`` (comma-separated)
    - User Verification: REQUIRED (Decision #2)
    - Resident key: PREFERRED (future-ready Discoverable Credential — Improvement #1)
    - Authenticator type: BOTH (Decision #3) — no attachment restriction
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from uuid import UUID as UUIDType

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import settings
from app.models import PasskeyCredential, User
from app.redis_client import redis_client

log = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _origins() -> list[str]:
    """Parse comma-separated origin allowlist (Improvement #6)."""
    raw = settings.webauthn_origins or ""
    return [o.strip() for o in raw.split(",") if o.strip()]


def _reg_challenge_key(user_id: str) -> str:
    return f"passkey:reg:challenge:{user_id}"


def _auth_challenge_key_email(email: str) -> str:
    """Email-first authentication challenge (Decision #1)."""
    return f"passkey:auth:challenge:email:{email.lower()}"


def _stepup_challenge_key(user_id: str) -> str:
    """Step-up re-auth challenge (Phase 5) — keyed by user (รู้ตัวตนแล้วจาก JWT)."""
    return f"passkey:stepup:challenge:{user_id}"


def _disc_challenge_key(challenge_b64: str) -> str:
    """Discoverable login challenge (Phase 7) — keyed by challenge (ยังไม่รู้ user)."""
    return f"passkey:disc:challenge:{challenge_b64}"


def _b64url(data: bytes) -> str:
    """Standard base64url no-padding (frontend uses same — `lib/passkey.ts`)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _dummy_descriptors(email: str) -> list[PublicKeyCredentialDescriptor]:
    """Deterministic decoy credential descriptors สำหรับ email ที่ไม่มี passkey.

    Anti-enumeration (Decision #1): ``login/start`` ต้องคืน allowCredentials
    ที่ **ไม่ว่าง** สำหรับทุก email — ไม่งั้นผู้โจมตีแยกได้ว่า
    "มี passkey" (list ไม่ว่าง) vs "ไม่มี account/passkey" (list ว่าง).

    derive จาก HMAC-SHA256(SECRET_KEY, email) →
      - email เดิม → decoy id เดิมทุกครั้ง (กัน shape/timing tell ข้าม request)
      - email ต่างกัน → decoy id ต่างกัน (เลียนแบบ credential จริงที่ unique)
      - 20 bytes เลียน credential_id ของ platform authenticator (Windows Hello/Touch ID)
      - ไม่มีทางตรง credential จริงใน DB → ceremony fail แบบเดียวกับ wrong cred
        (401 invalid_credential) ที่ ``auth_complete``.
    """
    key = (settings.secret_key or "").encode()
    digest = hmac.new(
        key, f"passkey-decoy:{email.lower()}".encode(), hashlib.sha256
    ).digest()
    return [
        PublicKeyCredentialDescriptor(
            id=digest[:20],
            transports=[AuthenticatorTransport.INTERNAL],
        )
    ]


def count_active(user_id: UUIDType | str, db: Session) -> int:
    """Number of non-revoked Passkeys for max-per-user enforcement (Improvement #9)."""
    return (
        db.query(func.count(PasskeyCredential.id))
        .filter(
            PasskeyCredential.user_id == user_id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .scalar()
        or 0
    )


def _existing_credential_ids(user_id: UUIDType | str, db: Session) -> list[bytes]:
    """Active credential_id list — used as exclude_credentials to prevent dup register."""
    rows = (
        db.query(PasskeyCredential.credential_id)
        .filter(
            PasskeyCredential.user_id == user_id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .all()
    )
    return [r[0] for r in rows]


# ─── Registration ───────────────────────────────────────────────────────────


def register_begin(user: User, db: Session) -> dict:
    """Build PublicKeyCredentialCreationOptions for navigator.credentials.create().

    Enforces:
        - Max Passkeys per user (Improvement #9) — raises 400 if exceeded
        - User verification REQUIRED (Decision #2)
        - Resident key PREFERRED (future Discoverable Credential)
        - No authenticator attachment — user picks (Decision #3)
        - Exclude existing credentials (prevent dup register on same device)

    Stores challenge in Redis with TTL = ``webauthn_challenge_ttl_sec`` (default 300s).
    Returns:
        dict — PublicKeyCredentialCreationOptionsJSON-compatible
                (snake_case keys converted to camelCase by ``options_to_json``)
    """
    active = count_active(user.id, db)
    if active >= settings.webauthn_max_passkeys_per_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "max_passkeys_exceeded",
                "current": active,
                "max": settings.webauthn_max_passkeys_per_user,
            },
        )

    exclude = [
        PublicKeyCredentialDescriptor(id=cid)
        for cid in _existing_credential_ids(user.id, db)
    ]

    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=str(user.id).encode("utf-8"),
        user_name=user.email,
        user_display_name=user.full_name or user.email,
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Decision #3 — ทั้ง platform + cross-platform (ไม่ระบุ attachment)
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        timeout=settings.webauthn_challenge_ttl_sec * 1000,
    )

    # Persist raw challenge (bytes → b64url for Redis text storage)
    redis_client.setex(
        _reg_challenge_key(str(user.id)),
        settings.webauthn_challenge_ttl_sec,
        _b64url(options.challenge),
    )

    # options_to_json → JSON string with WebAuthn camelCase keys
    return json.loads(options_to_json(options))


def register_complete(
    user: User,
    credential_payload: dict,
    device_name: str,
    db: Session,
) -> PasskeyCredential:
    """Verify attestation from navigator.credentials.create() and persist credential.

    Args:
        user: authenticated user (from JWT)
        credential_payload: raw JSON from browser PublicKeyCredential.toJSON()
        device_name: user-typed friendly name (e.g. "MacBook Air")

    Raises:
        HTTPException 400 — challenge expired, invalid attestation, credential reused
    Returns:
        Created PasskeyCredential row
    """
    if not device_name or not device_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="device_name required",
        )

    # Atomic getdel — B9 pattern: prevents challenge replay
    challenge_b64 = redis_client.getdel(_reg_challenge_key(str(user.id)))
    if not challenge_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "challenge_expired_or_missing"},
        )
    expected_challenge = _b64url_decode(challenge_b64)

    try:
        verification = verify_registration_response(
            credential=credential_payload,
            expected_challenge=expected_challenge,
            expected_origin=_origins(),
            expected_rp_id=settings.webauthn_rp_id,
            require_user_verification=True,  # Decision #2
        )
    except Exception as e:
        log.warning(
            "webauthn register verify failed user=%s err=%r",
            user.id,
            e,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "attestation_verify_failed", "message": str(e)},
        )

    # Idempotency / uniqueness check before insert
    cred_id_bytes = verification.credential_id
    existing = (
        db.query(PasskeyCredential)
        .filter(PasskeyCredential.credential_id == cred_id_bytes)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "credential_already_registered"},
        )

    transports_raw = credential_payload.get("response", {}).get("transports", []) or []

    # AAGUID from verification (UUID type or None)
    aaguid = verification.aaguid
    aaguid_uuid: UUIDType | None
    try:
        aaguid_uuid = UUIDType(aaguid) if aaguid and isinstance(aaguid, str) else aaguid
    except (ValueError, TypeError):
        aaguid_uuid = None

    # device_type best-effort guess from transports
    device_type = "platform" if "internal" in transports_raw else "cross-platform"

    row = PasskeyCredential(
        user_id=user.id,
        credential_id=cred_id_bytes,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        aaguid=aaguid_uuid,
        transports=transports_raw,
        device_name=device_name.strip()[:100],
        device_type=device_type,
        backup_eligible=getattr(verification, "credential_backed_up", None),
        backup_state=getattr(verification, "credential_device_type", None)
        == "multi_device",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    db.flush()
    return row


# ─── Listing / lifecycle helpers (used by Phase 3 router) ───────────────────


def list_for_user(user_id: UUIDType | str, db: Session) -> list[PasskeyCredential]:
    """Active Passkeys (revoked_at IS NULL), newest first."""
    return (
        db.query(PasskeyCredential)
        .filter(
            PasskeyCredential.user_id == user_id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .order_by(PasskeyCredential.created_at.desc())
        .all()
    )


def adoption_status(user: User, db: Session) -> dict:
    """Force adoption nudge (Phase 7 — Q5, soft enforcement).

    คืน {has_passkey, nudge, days_since_signup, required_after_days}.
    nudge=True ถ้า passkey_required_after_days > 0 + account เกิน N วัน + ยังไม่มี passkey.
    ไม่ block — frontend ใช้ flag นี้เตือน/พาไปตั้งค่า.
    """
    has = count_active(user.id, db) > 0
    after = settings.passkey_required_after_days
    days = 0
    if user.created_at:
        days = max(
            0, (datetime.now(timezone.utc).replace(tzinfo=None) - user.created_at).days
        )
    nudge = bool(after > 0 and not has and days >= after)
    in_grace = bool(not has and days < settings.passkey_grace_period_days)
    grace_days_remaining = (
        max(0, settings.passkey_grace_period_days - days) if not has else 0
    )
    return {
        "has_passkey": has,
        "nudge": nudge,
        "days_since_signup": days,
        "required_after_days": after,
        # Risk-triggered MFA grace period (Week 9-10)
        "in_grace_period": in_grace,
        "grace_days_remaining": grace_days_remaining,
        "grace_period_days": settings.passkey_grace_period_days,
    }


def in_grace_period(user: User, db: Session) -> bool:
    """True ถ้า user ยังไม่มี passkey + account_age < passkey_grace_period_days.

    ใช้ใน finalizer (oauth.py / auth.py) — Risk-triggered MFA branch:
    score >= challenge + no passkey + in_grace → Allow Once + Show Banner
    score >= challenge + no passkey + ไม่ grace → Force Enrollment

    Self-contained — ไม่ derive จาก adoption_status เพื่อไม่ shadow logic.
    """
    if count_active(user.id, db) > 0:
        return False
    if not user.created_at:
        # ไม่มี created_at = treat as old account (no grace) — เป็นค่า conservative
        return False
    days = (datetime.now(timezone.utc).replace(tzinfo=None) - user.created_at).days
    return days < settings.passkey_grace_period_days


def get_owned_passkey(
    user_id: UUIDType | str, passkey_id: str, db: Session
) -> PasskeyCredential:
    """หา active passkey ที่เป็นของ user นี้ — 404 ถ้าไม่เจอ.

    Scoped to user_id เสมอ (security: ห้ามแก้/ลบ passkey ของคนอื่น แม้รู้ id).
    """
    try:
        pk_uuid = UUIDType(str(passkey_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="ไม่พบ Passkey")
    row = (
        db.query(PasskeyCredential)
        .filter(
            PasskeyCredential.id == pk_uuid,
            PasskeyCredential.user_id == user_id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="ไม่พบ Passkey")
    return row


def rename_passkey(
    user_id: UUIDType | str, passkey_id: str, new_name: str, db: Session
) -> PasskeyCredential:
    """เปลี่ยนชื่ออุปกรณ์ + append nickname_history (Improvement #4)."""
    new_name = (new_name or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="device_name required")
    row = get_owned_passkey(user_id, passkey_id, db)
    old_name = row.device_name
    if new_name == old_name:
        return row  # no-op
    history = list(row.nickname_history or [])
    history.append(
        {
            "from": old_name,
            "to": new_name[:100],
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    row.device_name = new_name[:100]
    row.nickname_history = history
    db.flush()
    return row


def count_active_excluding(
    user_id: UUIDType | str, exclude_id: str, db: Session
) -> int:
    """จำนวน active passkey ที่ไม่ใช่ id ที่ระบุ (ใช้ last-Passkey guard)."""
    q = db.query(func.count(PasskeyCredential.id)).filter(
        PasskeyCredential.user_id == user_id,
        PasskeyCredential.revoked_at.is_(None),
        PasskeyCredential.id != exclude_id,
    )
    return q.scalar() or 0


def revoke_passkey(
    user_id: UUIDType | str,
    passkey_id: str,
    db: Session,
    *,
    reason: str = "user_deleted",
    allow_last: bool = False,
) -> PasskeyCredential:
    """Soft-delete passkey (revoked_at=now). last-Passkey guard (Decision #15).

    ถ้าเป็น passkey ตัวสุดท้าย + allow_last=False → 400 last_passkey
    (กัน user ลบจนเข้าระบบไม่ได้ — ต้องใช้ backup code recovery แทน).
    """
    row = get_owned_passkey(user_id, passkey_id, db)
    if not allow_last and count_active_excluding(user_id, row.id, db) == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "last_passkey",
                "message": (
                    "ลบ Passkey ตัวสุดท้ายไม่ได้ — ต้องเหลืออย่างน้อย 1 ตัว "
                    "หรือใช้ backup code กู้บัญชี"
                ),
            },
        )
    row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.revoked_reason = reason
    db.flush()
    return row


# ─── Authentication (Phase 2) ───────────────────────────────────────────────


class AuthResult:
    """Returned by auth_complete — small object > dict for type clarity."""

    __slots__ = ("user", "credential", "counter_regression", "previous_sign_count")

    def __init__(
        self,
        user: User,
        credential: PasskeyCredential,
        *,
        counter_regression: bool,
        previous_sign_count: int,
    ) -> None:
        self.user = user
        self.credential = credential
        self.counter_regression = counter_regression
        self.previous_sign_count = previous_sign_count


def auth_begin(email: str, db: Session) -> dict:
    """Build PublicKeyCredentialRequestOptions for navigator.credentials.get().

    Decision #1 — email-first: client sends email, server resolves user,
    returns allow_credentials list (transports hint). Discoverable login
    (no email) is Phase 7+ (returns 501 from a separate endpoint).

    To avoid account-enumeration timing/response differences:
      - If email not found OR user has no active Passkeys → STILL generate
        a challenge with empty allow_credentials. Client gets options but
        the ceremony will fail at verify time the same way as a wrong cred.
      - Caller (router) MAY log/audit the "no user" path internally.
    """
    email = (email or "").strip().lower()
    if not email:
        from fastapi import HTTPException, status as st

        raise HTTPException(
            status_code=st.HTTP_400_BAD_REQUEST, detail="email required"
        )

    user = db.query(User).filter(func.lower(User.email) == email).first()

    allow_credentials: list[PublicKeyCredentialDescriptor] = []
    if user is not None:
        rows = (
            db.query(PasskeyCredential)
            .filter(
                PasskeyCredential.user_id == user.id,
                PasskeyCredential.revoked_at.is_(None),
            )
            .all()
        )
        for r in rows:
            transports = []
            for t in r.transports or []:
                try:
                    transports.append(AuthenticatorTransport(t))
                except ValueError:
                    pass  # unknown transport — skip
            allow_credentials.append(
                PublicKeyCredentialDescriptor(
                    id=r.credential_id,
                    transports=transports or None,
                )
            )

    # Anti-enumeration (Decision #1): ไม่มี active passkey (หรือไม่มี account)
    # → คืน decoy descriptors เพื่อให้ allowCredentials ไม่ว่าง — แยก
    # "มี passkey" ไม่ออกจาก "ไม่มี" (จุดรั่ว: empty vs non-empty list).
    if not allow_credentials:
        allow_credentials = _dummy_descriptors(email)

    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.REQUIRED,  # Decision #2
        timeout=settings.webauthn_challenge_ttl_sec * 1000,
    )

    redis_client.setex(
        _auth_challenge_key_email(email),
        settings.webauthn_challenge_ttl_sec,
        _b64url(options.challenge),
    )

    return json.loads(options_to_json(options))


def auth_complete(
    email: str,
    credential_payload: dict,
    db: Session,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuthResult:
    """Verify assertion + update sign_count + last_used.

    Lenient counter mode (Decision #9, Improvement #10): if new_count is
    less-or-equal stored (cloud-sync edge case) — log + audit + bump
    ``counter_regression_count`` but DO NOT raise. Caller applies the
    +0.2 risk boost (Improvement #10) by reading ``result.counter_regression``.
    """
    from fastapi import HTTPException, status as st

    email = (email or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=st.HTTP_400_BAD_REQUEST, detail="email required"
        )
    if not credential_payload or not isinstance(credential_payload, dict):
        raise HTTPException(
            status_code=st.HTTP_400_BAD_REQUEST,
            detail="missing credential",
        )

    # Atomic getdel — B9 (prevents challenge replay)
    challenge_b64 = redis_client.getdel(_auth_challenge_key_email(email))
    if not challenge_b64:
        raise HTTPException(
            status_code=st.HTTP_400_BAD_REQUEST,
            detail={"code": "challenge_expired_or_missing"},
        )
    expected_challenge = _b64url_decode(challenge_b64)

    # Resolve user — opaque error on miss (same code as wrong credential)
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None:
        raise HTTPException(
            status_code=st.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credential"},
        )

    # Find credential by raw_id
    raw_id_b64 = credential_payload.get("rawId") or credential_payload.get("id")
    if not raw_id_b64:
        raise HTTPException(
            status_code=st.HTTP_400_BAD_REQUEST,
            detail={"code": "credential_missing_rawId"},
        )
    try:
        cred_id_bytes = _b64url_decode(raw_id_b64)
    except Exception:
        raise HTTPException(
            status_code=st.HTTP_400_BAD_REQUEST,
            detail={"code": "credential_id_bad_b64"},
        )

    credential = (
        db.query(PasskeyCredential)
        .filter(
            PasskeyCredential.credential_id == cred_id_bytes,
            PasskeyCredential.user_id == user.id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .first()
    )
    if credential is None:
        raise HTTPException(
            status_code=st.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credential"},
        )

    try:
        verification = verify_authentication_response(
            credential=credential_payload,
            expected_challenge=expected_challenge,
            expected_origin=_origins(),
            expected_rp_id=settings.webauthn_rp_id,
            credential_public_key=bytes(credential.public_key),
            # pass 0 → py_webauthn ข้าม strict count check
            # (มันจะ raise ถ้า new<=current); เราทำ lenient check เอง
            # ด้านล่าง (Decision #9 — กัน false positive จาก cloud sync)
            credential_current_sign_count=0,
            require_user_verification=True,
        )
    except Exception as e:
        log.warning(
            "passkey auth verify failed user=%s err=%r",
            user.id,
            e,
        )
        raise HTTPException(
            status_code=st.HTTP_401_UNAUTHORIZED,
            detail={"code": "assertion_verify_failed", "message": str(e)[:200]},
        )

    new_count = verification.new_sign_count
    previous = credential.sign_count or 0

    # Counter regression detection (Improvement #10)
    counter_regression = False
    if new_count > 0 and new_count <= previous:
        counter_regression = True
        credential.counter_regression_count = (
            credential.counter_regression_count or 0
        ) + 1
        credential.last_counter_regression_at = datetime.now(timezone.utc).replace(
            tzinfo=None
        )
        log.warning(
            "passkey sign counter regression user=%s cred=%s stored=%d received=%d "
            "(lenient — allowing login, caller will +0.2 risk)",
            user.id,
            credential.id,
            previous,
            new_count,
        )

    # Always update to latest (lenient mode)
    credential.sign_count = new_count
    credential.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    credential.last_used_ip = ip
    credential.last_used_user_agent = (user_agent or None) and user_agent[:500]
    db.flush()

    return AuthResult(
        user=user,
        credential=credential,
        counter_regression=counter_regression,
        previous_sign_count=previous,
    )


# ─── Discoverable Credential login (Phase 7 — Improvement #1) ───────────────
# login โดยไม่กรอก email — browser โชว์ resident keys, authenticator คืน
# userHandle (= user.id) → identify user จาก userHandle ไม่ใช่ email


def discoverable_begin(db: Session) -> dict:
    """Assertion options แบบ allow_credentials ว่าง (browser โชว์ทุก passkey ของ RP).

    เก็บ challenge ใน Redis keyed by challenge เอง (ยังไม่รู้ user).
    """
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=[],  # discoverable — ให้ browser เลือก resident key
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=settings.webauthn_challenge_ttl_sec * 1000,
    )
    challenge_b64 = _b64url(options.challenge)
    redis_client.setex(
        _disc_challenge_key(challenge_b64),
        settings.webauthn_challenge_ttl_sec,
        "1",
    )
    return json.loads(options_to_json(options))


def discoverable_complete(
    credential_payload: dict,
    db: Session,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuthResult:
    """Verify discoverable assertion → identify user จาก userHandle.

    ต่างจาก auth_complete: ไม่มี email มาก่อน — หา user จาก userHandle (= user.id)
    + ตรวจว่า credential เป็นของ user นั้นจริง (กัน userHandle ปลอม).
    """
    if not credential_payload or not isinstance(credential_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="missing credential"
        )

    # 1. ดึง challenge จาก clientDataJSON → lookup Redis (getdel — atomic B9)
    try:
        cdata_b64 = credential_payload["response"]["clientDataJSON"]
        cdata = json.loads(_b64url_decode(cdata_b64))
        challenge_b64 = cdata["challenge"]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "bad_client_data"},
        )
    if not redis_client.getdel(_disc_challenge_key(challenge_b64)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "challenge_expired_or_missing"},
        )
    expected_challenge = _b64url_decode(challenge_b64)

    # 2. userHandle = user.id (จาก register_begin: user_id=str(user.id).encode())
    user_handle_b64 = credential_payload.get("response", {}).get("userHandle")
    if not user_handle_b64:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "no_user_handle"},
        )
    try:
        user_id_str = _b64url_decode(user_handle_b64).decode("utf-8")
        user = db.query(User).filter(User.id == user_id_str).first()
    except Exception:
        user = None
    if user is None or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credential"},
        )

    # 3. หา credential by rawId + ต้องเป็นของ user นี้ (กัน userHandle ปลอม)
    raw_id_b64 = credential_payload.get("rawId") or credential_payload.get("id")
    try:
        cred_id_bytes = _b64url_decode(raw_id_b64)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "credential_id_bad_b64"},
        )
    credential = (
        db.query(PasskeyCredential)
        .filter(
            PasskeyCredential.credential_id == cred_id_bytes,
            PasskeyCredential.user_id == user.id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .first()
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credential"},
        )

    # 4. verify signature
    try:
        verification = verify_authentication_response(
            credential=credential_payload,
            expected_challenge=expected_challenge,
            expected_origin=_origins(),
            expected_rp_id=settings.webauthn_rp_id,
            credential_public_key=bytes(credential.public_key),
            credential_current_sign_count=0,  # lenient — เราเช็คเอง
            require_user_verification=True,
        )
    except Exception as e:
        log.warning("discoverable verify failed user=%s err=%r", user.id, e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "assertion_verify_failed", "message": str(e)[:200]},
        )

    new_count = verification.new_sign_count
    previous = credential.sign_count or 0
    counter_regression = False
    if new_count > 0 and new_count <= previous:
        counter_regression = True
        credential.counter_regression_count = (
            credential.counter_regression_count or 0
        ) + 1
        credential.last_counter_regression_at = datetime.now(timezone.utc).replace(
            tzinfo=None
        )
    credential.sign_count = new_count
    credential.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    credential.last_used_ip = ip
    credential.last_used_user_agent = (user_agent or None) and user_agent[:500]
    db.flush()

    return AuthResult(
        user=user,
        credential=credential,
        counter_regression=counter_regression,
        previous_sign_count=previous,
    )


# ─── Step-up re-auth (Phase 5 — Improvement #2 + #8) ────────────────────────


def stepup_begin(user: User, db: Session) -> dict:
    """Assertion options สำหรับ step-up — user รู้ตัวตนแล้ว (จาก JWT).

    เหมือน auth_begin แต่ keyed by user_id. ถ้า user ไม่มี active passkey
    → 400 no_passkey (caller fallback ไป email OTP).
    """
    rows = list_for_user(user.id, db)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "no_passkey"},
        )
    allow_credentials = []
    for r in rows:
        transports = []
        for t in r.transports or []:
            try:
                transports.append(AuthenticatorTransport(t))
            except ValueError:
                pass
        allow_credentials.append(
            PublicKeyCredentialDescriptor(
                id=r.credential_id, transports=transports or None
            )
        )

    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=settings.webauthn_challenge_ttl_sec * 1000,
    )
    redis_client.setex(
        _stepup_challenge_key(str(user.id)),
        settings.webauthn_challenge_ttl_sec,
        _b64url(options.challenge),
    )
    return json.loads(options_to_json(options))


def stepup_complete(
    user: User,
    credential_payload: dict,
    db: Session,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuthResult:
    """Verify step-up assertion — เหมือน auth_complete แต่ scoped to user จาก JWT.

    ไม่ออก JWT — caller เรียก stepup_cache.set_granted() เพื่อ mark trusted session.
    """
    if not credential_payload or not isinstance(credential_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="missing credential"
        )

    challenge_b64 = redis_client.getdel(_stepup_challenge_key(str(user.id)))
    if not challenge_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "challenge_expired_or_missing"},
        )
    expected_challenge = _b64url_decode(challenge_b64)

    raw_id_b64 = credential_payload.get("rawId") or credential_payload.get("id")
    if not raw_id_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "credential_missing_rawId"},
        )
    try:
        cred_id_bytes = _b64url_decode(raw_id_b64)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "credential_id_bad_b64"},
        )

    credential = (
        db.query(PasskeyCredential)
        .filter(
            PasskeyCredential.credential_id == cred_id_bytes,
            PasskeyCredential.user_id == user.id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .first()
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credential"},
        )

    try:
        verification = verify_authentication_response(
            credential=credential_payload,
            expected_challenge=expected_challenge,
            expected_origin=_origins(),
            expected_rp_id=settings.webauthn_rp_id,
            credential_public_key=bytes(credential.public_key),
            # pass 0 → py_webauthn ข้าม strict count check
            # (มันจะ raise ถ้า new<=current); เราทำ lenient check เอง
            # ด้านล่าง (Decision #9 — กัน false positive จาก cloud sync)
            credential_current_sign_count=0,
            require_user_verification=True,
        )
    except Exception as e:
        log.warning("passkey stepup verify failed user=%s err=%r", user.id, e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "assertion_verify_failed", "message": str(e)[:200]},
        )

    new_count = verification.new_sign_count
    previous = credential.sign_count or 0
    counter_regression = False
    if new_count > 0 and new_count <= previous:
        counter_regression = True
        credential.counter_regression_count = (
            credential.counter_regression_count or 0
        ) + 1
        credential.last_counter_regression_at = datetime.now(timezone.utc).replace(
            tzinfo=None
        )
    credential.sign_count = new_count
    credential.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    credential.last_used_ip = ip
    credential.last_used_user_agent = (user_agent or None) and user_agent[:500]
    db.flush()

    return AuthResult(
        user=user,
        credential=credential,
        counter_regression=counter_regression,
        previous_sign_count=previous,
    )
