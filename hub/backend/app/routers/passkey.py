"""Passkey / WebAuthn router — Phase 1 (plan v3).

Phase 1 endpoints (registration + mandatory backup codes):

    POST /account/passkeys/register/start
    POST /account/passkeys/register/finish
    POST /account/passkeys/backup-codes/acknowledge
    GET  /account/passkeys/backup-codes/status

All endpoints require login JWT (``Depends(get_current_user)``).

The first Passkey registration auto-generates 10 backup codes (Improvement #3)
and returns them in the ``register/finish`` response. Subsequent registrations
do NOT regenerate codes — those need explicit /backup-codes/regenerate (Phase 4).

Critical Action Policy (Improvement #8): ``register_new_passkey`` is a critical
action, so the start endpoint goes through ``critical_action_policy.gate(...)``
EXCEPT for the very first Passkey (which can't have step-up cache yet).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, get_current_user
from app.models import LoginSession, User
from app.rate_limiter import limiter
from app.services import passkey_recovery, webauthn_service
from app.services.audit_service import log_action
from app.services.jwt_service import create_access_token

log = logging.getLogger(__name__)

router = APIRouter()


# Audit action constants (Phase 1 + 2 subset — see plan § 7 for full list)
PASSKEY_REGISTERED = "passkey_registered"
PASSKEY_BACKUP_CODES_GENERATED = "passkey_backup_codes_generated"
PASSKEY_BACKUP_CODES_ACKNOWLEDGED = "passkey_backup_codes_acknowledged"
PASSKEY_REGISTER_FAILED = "passkey_register_failed"
# Phase 2 — auth events
PASSKEY_LOGIN_SUCCESS = "passkey_login_success"
PASSKEY_LOGIN_FAILED = "passkey_login_failed"
PASSKEY_LOGIN_COUNTER_REGRESSION = "passkey_login_counter_regression"


# ─── Registration ───────────────────────────────────────────────────────────


@router.post(
    "/account/passkeys/register/start",
    summary="เริ่ม Passkey registration ceremony",
)
async def register_start(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return PublicKeyCredentialCreationOptionsJSON for navigator.credentials.create().

    Frontend then submits the resulting PublicKeyCredential to /register/finish.

    Note: First Passkey is exempt from step-up gate (chicken-and-egg —
    cannot do step-up without an existing Passkey or verified-email OTP).
    Subsequent registrations could be gated, but for simplicity we let
    Phase 4 add stepup_required check on management endpoints instead.
    """
    try:
        options = webauthn_service.register_begin(user, db)
        return options
    except HTTPException:
        raise
    except Exception as e:
        log.warning("register_start failed user=%s err=%r", user.id, e)
        log_action(
            db,
            actor_id=user.id,
            action=PASSKEY_REGISTER_FAILED,
            target_type="passkey",
            ip=get_client_ip(request),
            metadata={"phase": "start", "error": str(e)[:200]},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="register_start failed",
        )


@router.post(
    "/account/passkeys/register/finish",
    summary="ยืนยัน attestation + save Passkey (+ auto-generate backup codes ถ้าเป็นตัวแรก)",
)
async def register_finish(
    request: Request,
    body: dict = Body(
        ...,
        examples=[
            {
                "device_name": "MacBook Air",
                "credential": {
                    "id": "...",
                    "rawId": "...",
                    "type": "public-key",
                    "response": {
                        "attestationObject": "...",
                        "clientDataJSON": "...",
                        "transports": ["internal", "hybrid"],
                    },
                },
            }
        ],
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Verify attestation, save credential, optionally generate backup codes.

    Response:
        {
            "passkey_id": "<uuid>",
            "device_name": "...",
            "device_type": "platform" | "cross-platform",
            "backup_codes": [...]    # only on FIRST Passkey, else key absent
        }
    """
    device_name = (body.get("device_name") or "").strip()
    credential = body.get("credential")
    if not credential or not isinstance(credential, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing 'credential' object",
        )

    try:
        existing_count = webauthn_service.count_active(user.id, db)
        row = webauthn_service.register_complete(user, credential, device_name, db)
    except HTTPException as e:
        # Audit before re-raise (B6 — log → commit → raise)
        log_action(
            db,
            actor_id=user.id,
            action=PASSKEY_REGISTER_FAILED,
            target_type="passkey",
            ip=get_client_ip(request),
            metadata={
                "phase": "finish",
                "code": (e.detail.get("code") if isinstance(e.detail, dict) else None),
                "device_name": device_name[:50],
            },
        )
        db.commit()
        raise

    # Audit success
    log_action(
        db,
        actor_id=user.id,
        action=PASSKEY_REGISTERED,
        target_type="passkey",
        target_id=row.id,
        ip=get_client_ip(request),
        metadata={
            "device_name": row.device_name,
            "device_type": row.device_type,
            "aaguid": str(row.aaguid) if row.aaguid else None,
        },
    )

    response: dict[str, Any] = {
        "passkey_id": str(row.id),
        "device_name": row.device_name,
        "device_type": row.device_type,
    }

    # First Passkey → auto-generate backup codes (Improvement #3 — mandatory)
    if existing_count == 0:
        codes = passkey_recovery.generate_backup_codes(user.id, db)
        log_action(
            db,
            actor_id=user.id,
            action=PASSKEY_BACKUP_CODES_GENERATED,
            target_type="user",
            target_id=user.id,
            ip=get_client_ip(request),
            metadata={"count": len(codes), "generation": 1, "trigger": "first_passkey"},
        )
        response["backup_codes"] = codes
        response["backup_codes_must_acknowledge"] = True

    db.commit()
    return response


# ─── Backup codes (mandatory ack — Improvement #3) ──────────────────────────


@router.post(
    "/account/passkeys/backup-codes/acknowledge",
    summary="User confirm 'I saved the codes' — required to close BackupCodesModal",
)
async def acknowledge_backup_codes(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    updated = passkey_recovery.acknowledge_backup_codes(user.id, db)
    log_action(
        db,
        actor_id=user.id,
        action=PASSKEY_BACKUP_CODES_ACKNOWLEDGED,
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"codes_marked": updated},
    )
    db.commit()
    return {"acknowledged": updated > 0, "codes_marked": updated}


@router.get(
    "/account/passkeys/backup-codes/status",
    summary="แสดงสถานะ backup codes (ไม่แสดง plaintext)",
)
async def backup_codes_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return passkey_recovery.get_status(user.id, db)


# ─── Login (Phase 2 — email-first) ──────────────────────────────────────────


@router.post(
    "/auth/passkey/login/start",
    summary="เริ่ม Passkey login ceremony (email-first, Decision #1)",
)
@limiter.limit("10/minute")  # per-IP — same rate as Google login
async def login_start(
    request: Request,
    body: dict = Body(..., examples=[{"email": "user@uni.ac.th"}]),
    db: Session = Depends(get_db),
) -> dict:
    email = (body.get("email") or "").strip()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email required",
        )
    # auth_begin is opaque on miss (Decision #1) — returns options either way
    return webauthn_service.auth_begin(email, db)


@router.post(
    "/auth/passkey/login/finish",
    summary="ยืนยัน assertion + issue JWT",
)
@limiter.limit("20/minute")
async def login_finish(
    request: Request,
    body: dict = Body(
        ...,
        examples=[
            {
                "email": "user@uni.ac.th",
                "credential": {
                    "id": "...",
                    "rawId": "...",
                    "type": "public-key",
                    "response": {
                        "authenticatorData": "...",
                        "clientDataJSON": "...",
                        "signature": "...",
                        "userHandle": "...",
                    },
                },
            }
        ],
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Verify Passkey assertion → JWT (aud=hub.internal).

    Counter regression (Improvement #10): success, but audit + returned in
    response (frontend can show subtle notice; Phase 5 will use this signal
    to bump the risk score).
    """
    email = (body.get("email") or "").strip()
    credential = body.get("credential")
    if not email or not isinstance(credential, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email + credential required",
        )

    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    try:
        result = webauthn_service.auth_complete(
            email, credential, db, ip=ip, user_agent=user_agent
        )
    except HTTPException as e:
        code = e.detail.get("code") if isinstance(e.detail, dict) else None
        log_action(
            db,
            actor_id=None,
            action=PASSKEY_LOGIN_FAILED,
            target_type="passkey",
            ip=ip,
            metadata={
                "email": email[:120],
                "code": code,
            },
        )
        db.commit()
        raise

    # Counter regression — log separately + flag in response
    if result.counter_regression:
        log_action(
            db,
            actor_id=result.user.id,
            action=PASSKEY_LOGIN_COUNTER_REGRESSION,
            target_type="passkey",
            target_id=result.credential.id,
            ip=ip,
            metadata={
                "credential_id": str(result.credential.id),
                "previous_sign_count": result.previous_sign_count,
                "new_sign_count": result.credential.sign_count,
            },
        )

    # Issue JWT
    token, jti = create_access_token(result.user)

    # LoginSession row (audit trail + ML training data)
    session_row = LoginSession(
        user_id=result.user.id,
        ip=ip,
        user_agent=user_agent,
        decision="allow",
        jti=jti,
    )
    db.add(session_row)

    log_action(
        db,
        actor_id=result.user.id,
        action=PASSKEY_LOGIN_SUCCESS,
        target_type="user",
        target_id=result.user.id,
        ip=ip,
        metadata={
            "provider": "passkey",
            "credential_id": str(result.credential.id),
            "device_name": result.credential.device_name,
            "counter_regression": result.counter_regression,
        },
    )
    db.commit()

    response = {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(result.user.id),
            "email": result.user.email,
            "full_name": result.user.full_name,
            "user_type": result.user.user_type,
            "is_hub_admin": result.user.is_hub_admin,
        },
    }
    if result.counter_regression:
        response["notice"] = "passkey_counter_regression"
    return response


@router.post(
    "/auth/passkey/login/discoverable/start",
    summary="(Reserved — Phase 7) Discoverable Credential / passwordless login",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
async def login_discoverable_start() -> dict:
    """Reserved for plan v3 Phase 7 (Improvement #1). Returns 501."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "not_implemented",
            "message": "Discoverable Credential login is planned for Phase 7+",
        },
    )
