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


def _b64url(data: bytes) -> str:
    """Standard base64url no-padding (frontend uses same — `lib/passkey.ts`)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


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
            credential_current_sign_count=credential.sign_count,
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
