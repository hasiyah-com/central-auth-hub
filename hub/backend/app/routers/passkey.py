"""Passkey / WebAuthn router — Phase 1 (plan v3).

Phase 1 endpoints (registration + mandatory backup codes):

    POST /account/passkeys/register/start
    POST /account/passkeys/register/finish
    POST /account/passkeys/backup-codes/acknowledge
    GET  /account/passkeys/backup-codes/status

**Developer Portal + Admin** — ทุก endpoint ใช้ ``Depends(require_developer)``
(teacher/staff/admin — กัน student เท่านั้น). ทั้ง admin และ teacher/staff
login ผ่าน Hub-direct OAuth เส้นทางเดียวกัน (``/auth/google/*``) จึงควรมีสิทธิ์
จัดการ passkey ของตัวเองเหมือนกัน — จำเป็นสำหรับผ่าน step-up gate ของ
``subsystem_register`` (critical_action_policy) ด้วย.
นักศึกษา (เข้า Hub console ไม่ได้เลย) ลง passkey ผ่าน subsystem enroll
interstitial (``/oauth/passkey/enroll/*``) แทน.

The first Passkey registration auto-generates 10 backup codes (Improvement #3)
and returns them in the ``register/finish`` response. Subsequent registrations
do NOT regenerate codes — those need explicit /backup-codes/regenerate (Phase 4).

Critical Action Policy (Improvement #8): ``register_new_passkey`` is a critical
action, so the start endpoint goes through ``critical_action_policy.gate(...)``
EXCEPT for the very first Passkey (which can't have step-up cache yet).
"""

import json
import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, get_current_user, require_developer
from app.models import AccessList, LoginSession, User
from app.rate_limiter import limiter
from app.redis_client import redis_client
from app.services import (
    passkey_recovery,
    risk_challenge,
    stepup_cache,
    webauthn_service,
)
from app.services.audit_service import log_action
from app.services.auth_policy import get_auth_policy
from app.services.critical_action_policy import _bearer, _extract_jti, gate
from app.services.alert_service import maybe_alert_ml_risk
from app.services.feature_extraction import (
    extract_session_features,
    parse_browser,
    parse_device_type,
    parse_os_name,
)
from app.services.geoip import lookup_country
from app.services.ip_blacklist import is_blacklisted
from app.services.jwt_service import create_access_token
from app.services import refresh_token_service
from app.security.risk_engine import evaluate_login_risk

log = logging.getLogger(__name__)

router = APIRouter()


# ─── Request schemas (input validation — SQLi/format guard) ─────────────────
# EmailStr → format validation (rejects "notanemail", "x' OR '1'='1" ฯลฯ ด้วย 422)
# max_length → กัน oversized-payload DoS
# credential เป็น dict ของ WebAuthn JSON — โครงสร้างตรวจลึกใน webauthn lib อีกชั้น


class LoginStartRequest(BaseModel):
    email: EmailStr = Field(..., max_length=255)


class LoginFinishRequest(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    credential: dict = Field(
        ..., description="WebAuthn assertion (PublicKeyCredential.toJSON())"
    )


class RegisterFinishRequest(BaseModel):
    device_name: str = Field(..., min_length=1, max_length=100)
    credential: dict = Field(
        ..., description="WebAuthn attestation (PublicKeyCredential.toJSON())"
    )


class RenamePasskeyRequest(BaseModel):
    device_name: str = Field(..., min_length=1, max_length=100)


class RecoverBackupCodeRequest(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    code: str = Field(..., min_length=8, max_length=20)


class RecoverEmailOtpStartRequest(BaseModel):
    email: EmailStr = Field(..., max_length=255)


class RecoverEmailOtpVerifyRequest(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    otp: str = Field(..., min_length=4, max_length=10)


# Audit action constants (Phase 1 + 2 subset — see plan § 7 for full list)
PASSKEY_REGISTERED = "passkey_registered"
PASSKEY_BACKUP_CODES_GENERATED = "passkey_backup_codes_generated"
PASSKEY_BACKUP_CODES_REGENERATED = "passkey_backup_codes_regenerated"
PASSKEY_BACKUP_CODES_ACKNOWLEDGED = "passkey_backup_codes_acknowledged"
PASSKEY_REGISTER_FAILED = "passkey_register_failed"
# Phase 2 — auth events
PASSKEY_LOGIN_SUCCESS = "passkey_login_success"
PASSKEY_LOGIN_FAILED = "passkey_login_failed"
PASSKEY_LOGIN_COUNTER_REGRESSION = "passkey_login_counter_regression"


async def _build_login_session(result, request, jti, db, method: str) -> LoginSession:
    """รัน 4-Layer RBA + ML จริงสำหรับ Hub-direct passkey login → LoginSession.

    เดิม hardcode risk=0.0 (ML ไม่รัน) — แก้ให้รัน risk engine เหมือน Google/subsystem
    เพื่อให้ ML passkey features (Phase 5) ทำงาน + dashboard โชว์ score จริง.

    Passkey = strong auth → ไม่ hard-block (always allow login) แต่ record decision
    ของ engine (shadow mode default ไม่ block อยู่แล้ว) + counter regression boost.
    """
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    geo_country = lookup_country(ip)

    features = extract_session_features(
        db,
        user_id=result.user.id,
        ip=ip,
        user_agent=user_agent,
        geo_country=geo_country,
    )
    risk = await evaluate_login_risk(
        features=features,
        user_id=str(result.user.id),
        ip=ip,
        geo_country=geo_country,
        db=db,
        shadow_mode=settings.ml_shadow_mode,
    )
    risk_score = risk["score"]
    risk_breakdown = risk["breakdown"]
    risk_reasons = risk["reasons"]
    anomaly_score = risk_breakdown.get("iforest_raw", 0.0)
    iforest_explanation = risk.get("iforest_explanation", [])

    # counter regression → +0.2 risk (Improvement #10)
    if result.counter_regression:
        risk_score = min(
            1.0, risk_score + settings.stepup_counter_regression_risk_boost
        )
        risk_reasons = [*risk_reasons, "passkey_counter_regression (+0.20)"]
    if iforest_explanation:
        risk_breakdown = {**risk_breakdown, "iforest_explanation": iforest_explanation}

    maybe_alert_ml_risk(
        user_email=result.user.email,
        user_id=str(result.user.id),
        risk_score=risk_score,
        decision=risk["decision"],
        risk_breakdown=risk_breakdown,
        risk_reasons=risk_reasons,
        ip=ip,
        geo_country=geo_country,
        subsystem_name="Hub-direct (Passkey)",
    )

    return LoginSession(
        user_id=result.user.id,
        ip=ip,
        user_agent=user_agent,
        geo_country=geo_country,
        os_name=parse_os_name(user_agent),
        browser=parse_browser(user_agent),
        device_type=parse_device_type(user_agent),
        anomaly_score=anomaly_score,
        risk_score=risk_score,
        risk_breakdown=risk_breakdown,
        risk_reasons=risk_reasons,
        # passkey = strong auth → always allow (record engine decision สำหรับ monitoring)
        decision=risk["decision"] if risk["decision"] != "block" else "would_block",
        is_attack_ip=is_blacklisted(db, ip),
        jti=jti,
        login_method=method,
    )


# Phase 3 — lifecycle events
PASSKEY_RENAMED = "passkey_renamed"
PASSKEY_DELETED = "passkey_deleted"
PASSKEY_LAST_DELETION_BLOCKED = "passkey_last_deletion_blocked"
# Phase 4 — recovery events (Improvement #7 — full trail)
PASSKEY_RECOVERY_STARTED = "passkey_recovery_started"
PASSKEY_RECOVERY_SUCCESS = "passkey_recovery_success"
PASSKEY_RECOVERY_FAILED = "passkey_recovery_failed"
PASSKEY_RECOVERY_VIA_BACKUP_CODE = "passkey_recovery_via_backup_code"
PASSKEY_RECOVERY_VIA_EMAIL_OTP = "passkey_recovery_via_email_otp"
BACKUP_CODE_USED = "backup_code_used"


# ─── Registration ───────────────────────────────────────────────────────────


@router.post(
    "/account/passkeys/register/start",
    summary="เริ่ม Passkey registration ceremony",
)
async def register_start(
    request: Request,
    user: User = Depends(require_developer),
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
    body: RegisterFinishRequest,
    user: User = Depends(require_developer),
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
    device_name = body.device_name.strip()
    credential = body.credential

    try:
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

    # Auto-heal: ออก backup codes เมื่อ user ไม่มี usable codes (remaining==0)
    # — ไม่เคยมี → gen 1; ใช้หมดแล้ว → rotate ชุดใหม่ (ปิดช่องติดล็อกหลัง recovery)
    codes = passkey_recovery.ensure_backup_codes(user.id, db)
    if codes:
        log_action(
            db,
            actor_id=user.id,
            action=PASSKEY_BACKUP_CODES_GENERATED,
            target_type="user",
            target_id=user.id,
            ip=get_client_ip(request),
            metadata={"count": len(codes), "trigger": "register"},
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
    user: User = Depends(require_developer),
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
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
) -> dict:
    return passkey_recovery.get_status(user.id, db)


@router.post(
    "/account/passkeys/backup-codes/regenerate",
    summary="สร้าง backup codes ชุดใหม่ (ชุดเก่าตายทั้งหมด) — admin + step-up gate",
    dependencies=[Depends(gate("regenerate_backup_codes"))],  # Improvement #8 — Phase 5
)
async def regenerate_backup_codes(
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
) -> dict:
    """Rotate backup codes — ชุดเก่าทั้งหมด invalid, ออกชุดใหม่ 10 ตัว (show once).

    (A) ใช้ตอน codes ใกล้หมด/หาย/สงสัยรั่ว. Critical action — Phase 5 จะ gate step-up.
    """
    rotate = passkey_recovery.has_backup_codes(user.id, db)
    codes = passkey_recovery.generate_backup_codes(user.id, db, rotate=rotate)
    log_action(
        db,
        actor_id=user.id,
        action=PASSKEY_BACKUP_CODES_REGENERATED,
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"count": len(codes), "trigger": "manual_regenerate"},
    )
    db.commit()
    return {"backup_codes": codes, "backup_codes_must_acknowledge": True}


# ─── Lifecycle management (Phase 3 — Improvement #4) ────────────────────────


def _serialize_passkey(row) -> dict:
    """Public view ของ passkey (ไม่ส่ง credential_id/public_key ออก)."""
    return {
        "id": str(row.id),
        "device_name": row.device_name,
        "device_type": row.device_type,
        "transports": list(row.transports or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "last_used_country": lookup_country(str(row.last_used_ip))
        if row.last_used_ip
        else None,
        "counter_regression_count": row.counter_regression_count or 0,
        "rename_count": len(row.nickname_history or []),
    }


@router.get(
    "/account/passkeys",
    summary="รายการ Passkey ของ admin (active เท่านั้น)",
)
async def list_passkeys(
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
) -> dict:
    rows = webauthn_service.list_for_user(user.id, db)
    return {
        "passkeys": [_serialize_passkey(r) for r in rows],
        "count": len(rows),
        "max": settings.webauthn_max_passkeys_per_user,
    }


@router.patch(
    "/account/passkeys/{passkey_id}",
    summary="เปลี่ยนชื่ออุปกรณ์ Passkey",
)
async def rename_passkey(
    passkey_id: str,
    body: RenamePasskeyRequest,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
) -> dict:
    row = webauthn_service.rename_passkey(user.id, passkey_id, body.device_name, db)
    log_action(
        db,
        actor_id=user.id,
        action=PASSKEY_RENAMED,
        target_type="passkey",
        target_id=row.id,
        ip=get_client_ip(request),
        metadata={"new_name": row.device_name},
    )
    db.commit()
    return _serialize_passkey(row)


@router.delete(
    "/account/passkeys/{passkey_id}",
    summary="ลบ Passkey (soft delete + last-Passkey guard + step-up gate)",
    dependencies=[Depends(gate("delete_passkey"))],  # Improvement #8 — Phase 5
)
async def delete_passkey(
    passkey_id: str,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
) -> dict:
    # last-Passkey guard (Decision #15) — block + audit ก่อน raise (B6)
    try:
        row = webauthn_service.revoke_passkey(
            user.id, passkey_id, db, reason="user_deleted"
        )
    except HTTPException as e:
        if isinstance(e.detail, dict) and e.detail.get("code") == "last_passkey":
            log_action(
                db,
                actor_id=user.id,
                action=PASSKEY_LAST_DELETION_BLOCKED,
                target_type="passkey",
                ip=get_client_ip(request),
                metadata={"passkey_id": passkey_id},
            )
            db.commit()
        raise

    log_action(
        db,
        actor_id=user.id,
        action=PASSKEY_DELETED,
        target_type="passkey",
        target_id=row.id,
        ip=get_client_ip(request),
        metadata={"device_name": row.device_name, "reason": row.revoked_reason},
    )
    db.commit()
    return {"deleted": True, "id": str(row.id)}


# ─── Recovery (Phase 4 — public, Decision #6) ───────────────────────────────
# ทุก recovery = revoke passkey ทั้งหมด (lock down) → login Google → enroll ใหม่
# audit trail เต็ม (Improvement #7). Opaque responses (anti-enumeration).


def _resolve_user(email: str, db: Session) -> User | None:
    from sqlalchemy import func as _f

    return db.query(User).filter(_f.lower(User.email) == email.strip().lower()).first()


@router.post(
    "/auth/passkey/recover/backup-code",
    summary="กู้บัญชีด้วย backup code → revoke passkey ทั้งหมด",
)
@limiter.limit("5/minute")
async def recover_backup_code(
    request: Request,
    body: RecoverBackupCodeRequest,
    db: Session = Depends(get_db),
) -> dict:
    email = body.email.strip().lower()
    ip = get_client_ip(request)
    user = _resolve_user(email, db)

    log_action(
        db,
        actor_id=user.id if user else None,
        action=PASSKEY_RECOVERY_STARTED,
        target_type="user",
        target_id=user.id if user else None,
        ip=ip,
        metadata={"email": email[:120], "method": "backup_code"},
    )

    ok = False
    if user is not None:
        ok = passkey_recovery.verify_backup_code(
            user.id, body.code, db, ip=ip, user_agent=request.headers.get("user-agent")
        )

    if not ok:
        log_action(
            db,
            actor_id=user.id if user else None,
            action=PASSKEY_RECOVERY_FAILED,
            target_type="user",
            target_id=user.id if user else None,
            ip=ip,
            metadata={"email": email[:120], "method": "backup_code"},
        )
        db.commit()
        # opaque — ไม่บอกว่า email มี/code ผิด (anti-enum)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "recovery_failed",
                "message": "email หรือ backup code ไม่ถูกต้อง",
            },
        )

    log_action(
        db,
        actor_id=user.id,
        action=BACKUP_CODE_USED,
        target_type="user",
        target_id=user.id,
        ip=ip,
        metadata={"email": email[:120]},
    )
    log_action(
        db,
        actor_id=user.id,
        action=PASSKEY_RECOVERY_VIA_BACKUP_CODE,
        target_type="user",
        target_id=user.id,
        ip=ip,
    )
    log_action(
        db,
        actor_id=user.id,
        action=PASSKEY_RECOVERY_SUCCESS,
        target_type="user",
        target_id=user.id,
        ip=ip,
        metadata={"method": "backup_code"},
    )
    db.commit()
    return {
        "recovered": True,
        "message": "Passkey ทั้งหมดถูกลบแล้ว — login ด้วย Google แล้วตั้งค่า Passkey ใหม่",
    }


@router.post(
    "/auth/passkey/recover/email-otp/start",
    summary="ส่ง OTP ทาง email เพื่อกู้บัญชี",
)
@limiter.limit("3/minute")
async def recover_email_otp_start(
    request: Request,
    body: RecoverEmailOtpStartRequest,
    db: Session = Depends(get_db),
) -> dict:
    email = body.email.strip().lower()
    passkey_recovery.email_otp_begin(email, db)  # opaque — ส่งถ้ามี user
    log_action(
        db,
        actor_id=None,
        action=PASSKEY_RECOVERY_STARTED,
        target_type="user",
        ip=get_client_ip(request),
        metadata={"email": email[:120], "method": "email_otp"},
    )
    db.commit()
    # opaque — ตอบเหมือนกันไม่ว่ามี email ไหม
    return {"sent": True, "message": "ถ้า email มีในระบบ จะได้รับ OTP ภายใน 5 นาที"}


@router.post(
    "/auth/passkey/recover/email-otp/verify",
    summary="ยืนยัน OTP → revoke passkey + ออก backup codes ชุดใหม่",
)
@limiter.limit("5/minute")
async def recover_email_otp_verify(
    request: Request,
    body: RecoverEmailOtpVerifyRequest,
    db: Session = Depends(get_db),
) -> dict:
    email = body.email.strip().lower()
    ip = get_client_ip(request)
    # email_otp_verify คืน codes ใหม่ (list) ถ้าถูก, None ถ้าผิด
    new_codes = passkey_recovery.email_otp_verify(
        email, body.otp, db, ip=ip, user_agent=request.headers.get("user-agent")
    )
    user = _resolve_user(email, db)
    if new_codes is None:
        log_action(
            db,
            actor_id=user.id if user else None,
            action=PASSKEY_RECOVERY_FAILED,
            target_type="user",
            target_id=user.id if user else None,
            ip=ip,
            metadata={"email": email[:120], "method": "email_otp"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "recovery_failed", "message": "OTP ไม่ถูกต้องหรือหมดอายุ"},
        )

    log_action(
        db,
        actor_id=user.id if user else None,
        action=PASSKEY_RECOVERY_VIA_EMAIL_OTP,
        target_type="user",
        target_id=user.id if user else None,
        ip=ip,
    )
    log_action(
        db,
        actor_id=user.id if user else None,
        action=PASSKEY_BACKUP_CODES_REGENERATED,
        target_type="user",
        target_id=user.id if user else None,
        ip=ip,
        metadata={"count": len(new_codes), "trigger": "email_otp_recovery"},
    )
    log_action(
        db,
        actor_id=user.id if user else None,
        action=PASSKEY_RECOVERY_SUCCESS,
        target_type="user",
        target_id=user.id if user else None,
        ip=ip,
        metadata={"method": "email_otp"},
    )
    db.commit()
    return {
        "recovered": True,
        "message": "Passkey ถูกลบแล้ว + นี่คือ backup codes ชุดใหม่ — เก็บไว้ให้ดี",
        "backup_codes": new_codes,  # B — ออก codes ใหม่ให้เลย
    }


# ─── Regenerate backup codes via OTP (ไม่ revoke passkey) ────────────────────
# สำหรับ codes หาย/ใกล้หมด แต่ passkey ยังอยู่ — ทุก user ใช้ได้ (ไม่ต้อง console)


@router.post(
    "/auth/passkey/backup-codes/regen-otp/start",
    summary="ส่ง OTP เพื่อขอ backup codes ชุดใหม่ (ไม่แตะ passkey)",
)
@limiter.limit("3/minute")
async def regen_otp_start(
    request: Request,
    body: RecoverEmailOtpStartRequest,
    db: Session = Depends(get_db),
) -> dict:
    email = body.email.strip().lower()
    passkey_recovery.email_otp_begin(email, db, purpose="regenerate")
    db.commit()
    return {"sent": True, "message": "ถ้า email มีในระบบ จะได้รับ OTP ภายใน 5 นาที"}


@router.post(
    "/auth/passkey/backup-codes/regen-otp/verify",
    summary="ยืนยัน OTP → ออก backup codes ชุดใหม่ (passkey ไม่ถูกแตะ)",
)
@limiter.limit("5/minute")
async def regen_otp_verify(
    request: Request,
    body: RecoverEmailOtpVerifyRequest,
    db: Session = Depends(get_db),
) -> dict:
    email = body.email.strip().lower()
    ip = get_client_ip(request)
    new_codes = passkey_recovery.email_otp_verify(
        email,
        body.otp,
        db,
        purpose="regenerate",
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    user = _resolve_user(email, db)
    if new_codes is None:
        log_action(
            db,
            actor_id=user.id if user else None,
            action=PASSKEY_RECOVERY_FAILED,
            target_type="user",
            target_id=user.id if user else None,
            ip=ip,
            metadata={"email": email[:120], "method": "regen_otp"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "regen_failed", "message": "OTP ไม่ถูกต้องหรือหมดอายุ"},
        )

    log_action(
        db,
        actor_id=user.id if user else None,
        action=PASSKEY_BACKUP_CODES_REGENERATED,
        target_type="user",
        target_id=user.id if user else None,
        ip=ip,
        metadata={"count": len(new_codes), "trigger": "regen_otp"},
    )
    db.commit()
    return {
        "regenerated": True,
        "message": "นี่คือ backup codes ชุดใหม่ — passkey ของคุณยังใช้ได้ปกติ",
        "backup_codes": new_codes,
    }


# ─── Login (Phase 2 — email-first) ──────────────────────────────────────────


@router.post(
    "/auth/passkey/login/start",
    summary="เริ่ม Passkey login ceremony (email-first, Decision #1)",
)
@limiter.limit("10/minute")  # per-IP — same rate as Google login
async def login_start(
    request: Request,
    body: LoginStartRequest,
    db: Session = Depends(get_db),
) -> dict:
    # เคารพ global auth-policy — ถ้า admin ปิด Passkey login จะปฏิเสธ
    if not get_auth_policy(db)["passkey"]:
        raise HTTPException(
            status_code=403,
            detail="Passkey login ถูกปิดใช้งานโดยผู้ดูแลระบบ — ใช้ Google แทน",
        )
    # EmailStr ตรวจ format แล้ว (ไม่ใช่ email → 422 ก่อนถึงตรงนี้)
    # auth_begin is opaque on miss (Decision #1) — returns options either way
    return webauthn_service.auth_begin(body.email.strip().lower(), db)


@router.post(
    "/auth/passkey/login/finish",
    summary="ยืนยัน assertion + issue JWT",
)
@limiter.limit("20/minute")
async def login_finish(
    request: Request,
    body: LoginFinishRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Verify Passkey assertion → JWT (aud=hub.internal).

    Counter regression (Improvement #10): success, but audit + returned in
    response (frontend can show subtle notice; Phase 5 will use this signal
    to bump the risk score).
    """
    email = body.email.strip().lower()
    credential = body.credential

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

    # LoginSession + 4-Layer RBA/ML จริง (ไม่ hardcode 0.0 แล้ว)
    session_row = await _build_login_session(result, request, jti, db, method="passkey")
    refresh_token, refresh_id = refresh_token_service.issue(
        user_id=str(result.user.id), session_id=str(session_row.id)
    )
    session_row.refresh_id = refresh_id
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
        "refresh_token": refresh_token,
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


@router.get(
    "/auth/passkey/adoption",
    summary="สถานะ force adoption nudge (Phase 7 — soft enforcement)",
)
async def passkey_adoption(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Frontend เรียกหลัง login → ถ้า nudge=true พาไปตั้งค่า passkey (ไม่ block)."""
    return webauthn_service.adoption_status(user, db)


@router.post(
    "/auth/passkey/login/discoverable/start",
    summary="เริ่ม discoverable login (ไม่ต้องกรอก email — Phase 7)",
)
@limiter.limit("10/minute")
async def login_discoverable_start(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Assertion options แบบไม่มี email — browser โชว์ resident keys ให้เลือก."""
    if not get_auth_policy(db)["passkey"]:
        raise HTTPException(
            status_code=403,
            detail="Passkey login ถูกปิดใช้งานโดยผู้ดูแลระบบ — ใช้ Google แทน",
        )
    return webauthn_service.discoverable_begin(db)


@router.post(
    "/auth/passkey/login/discoverable/finish",
    summary="ยืนยัน discoverable assertion → JWT (identify จาก userHandle)",
)
@limiter.limit("20/minute")
async def login_discoverable_finish(
    request: Request,
    body: dict = None,  # noqa: ARG001 — {credential}
    db: Session = Depends(get_db),
) -> dict:
    credential = (body or {}).get("credential")
    if not isinstance(credential, dict):
        raise HTTPException(status_code=400, detail="credential required")

    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    try:
        result = webauthn_service.discoverable_complete(
            credential, db, ip=ip, user_agent=user_agent
        )
    except HTTPException as e:
        code = e.detail.get("code") if isinstance(e.detail, dict) else None
        log_action(
            db,
            actor_id=None,
            action=PASSKEY_LOGIN_FAILED,
            target_type="passkey",
            ip=ip,
            metadata={"code": code, "method": "discoverable"},
        )
        db.commit()
        raise

    token, jti = create_access_token(result.user)
    session_row = await _build_login_session(
        result, request, jti, db, method="discoverable"
    )
    refresh_token, refresh_id = refresh_token_service.issue(
        user_id=str(result.user.id), session_id=str(session_row.id)
    )
    session_row.refresh_id = refresh_id
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
            "method": "discoverable",
            "credential_id": str(result.credential.id),
        },
    )
    db.commit()
    return {
        "access_token": token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": str(result.user.id),
            "email": result.user.email,
            "full_name": result.user.full_name,
            "user_type": result.user.user_type,
            "is_hub_admin": result.user.is_hub_admin,
        },
    }


# ─── Step-up re-auth (Phase 5 — Improvement #2 + #8) ────────────────────────
# Critical action โดน gate() 403 stepup_required → frontend พามาที่นี่
# → verify passkey (หรือ OTP fallback) → grant trusted session 15 นาที (Q7)

PASSKEY_STEPUP_SUCCESS = "passkey_stepup_success"
PASSKEY_STEPUP_FAILED = "passkey_stepup_failed"
STEPUP_OTP_SUCCESS = "stepup_otp_success"

_STEPUP_OTP_PREFIX = "stepup:otp"
_STEPUP_OTP_TTL = 300
_STEPUP_OTP_MAX_ATTEMPTS = 5


class StepupFinishRequest(BaseModel):
    credential: dict = Field(..., description="WebAuthn assertion")


class StepupOtpVerifyRequest(BaseModel):
    otp: str = Field(..., min_length=4, max_length=10)


def _grant_stepup(user: User, request: Request, credentials, method: str) -> bool:
    """อ่าน jti จาก Bearer token → set stepup cache. คืน False ถ้าไม่มี jti."""
    jti = _extract_jti(credentials)
    if not jti:
        return False
    stepup_cache.set_granted(
        str(user.id), jti, method=method, ip=get_client_ip(request)
    )
    return True


@router.post(
    "/auth/passkey/stepup/start",
    summary="เริ่ม step-up ceremony (ต้อง login แล้ว)",
)
async def stepup_start(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Assertion options ของ user ปัจจุบัน. 400 no_passkey → frontend fallback OTP."""
    return webauthn_service.stepup_begin(user, db)


@router.post(
    "/auth/passkey/stepup/finish",
    summary="ยืนยัน step-up → trusted session 15 นาที",
)
async def stepup_finish(
    request: Request,
    body: StepupFinishRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    credentials=Depends(_bearer),
) -> dict:
    ip = get_client_ip(request)
    try:
        result = webauthn_service.stepup_complete(
            user,
            body.credential,
            db,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
    except HTTPException as e:
        code = e.detail.get("code") if isinstance(e.detail, dict) else None
        log_action(
            db,
            actor_id=user.id,
            action=PASSKEY_STEPUP_FAILED,
            target_type="user",
            target_id=user.id,
            ip=ip,
            metadata={"code": code},
        )
        db.commit()
        raise

    if not _grant_stepup(user, request, credentials, "passkey"):
        raise HTTPException(status_code=400, detail="token ไม่มี jti — login ใหม่")

    log_action(
        db,
        actor_id=user.id,
        action=PASSKEY_STEPUP_SUCCESS,
        target_type="user",
        target_id=user.id,
        ip=ip,
        metadata={
            "method": "passkey",
            "credential_id": str(result.credential.id),
            "counter_regression": result.counter_regression,
        },
    )
    db.commit()
    return {"granted": True, "ttl_sec": settings.stepup_cache_ttl_sec}


# OTP fallback — admin ที่ยังไม่มี passkey (ใช้ email OTP เดิม ไม่ใช่ TOTP)


@router.post(
    "/auth/stepup/otp/start",
    summary="ส่ง OTP step-up ทาง email (fallback เมื่อไม่มี passkey)",
)
@limiter.limit("3/minute")
async def stepup_otp_start(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from datetime import datetime, timedelta
    import json as _json

    from app.redis_client import redis_client
    from app.services import mfa_service

    otp = mfa_service.generate_otp()
    redis_client.setex(
        f"{_STEPUP_OTP_PREFIX}:{user.id}",
        _STEPUP_OTP_TTL,
        _json.dumps({"hash": mfa_service.hash_otp(otp), "attempts": 0}),
    )
    try:
        mfa_service.send_otp_email(
            user.email, otp, datetime.utcnow() + timedelta(seconds=_STEPUP_OTP_TTL)
        )
    except Exception as e:
        log.warning("stepup OTP email failed: %r", e)
    return {"sent": True, "message": f"ส่ง OTP ไปที่ {user.email} แล้ว (5 นาที)"}


@router.post(
    "/auth/stepup/otp/verify",
    summary="ยืนยัน OTP step-up → trusted session 15 นาที",
)
@limiter.limit("5/minute")
async def stepup_otp_verify(
    request: Request,
    body: StepupOtpVerifyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    credentials=Depends(_bearer),
) -> dict:
    import json as _json

    from app.redis_client import redis_client
    from app.services import mfa_service

    key = f"{_STEPUP_OTP_PREFIX}:{user.id}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(
            status_code=400,
            detail={"code": "otp_expired", "message": "OTP หมดอายุ — ขอใหม่"},
        )
    data = _json.loads(raw)
    if data.get("attempts", 0) >= _STEPUP_OTP_MAX_ATTEMPTS:
        redis_client.delete(key)
        raise HTTPException(
            status_code=400,
            detail={"code": "otp_locked", "message": "ผิดเกิน 5 ครั้ง — ขอ OTP ใหม่"},
        )
    if not mfa_service.verify_otp(data["hash"], body.otp.strip()):
        data["attempts"] = data.get("attempts", 0) + 1
        ttl = redis_client.ttl(key)
        redis_client.setex(
            key, ttl if ttl and ttl > 0 else _STEPUP_OTP_TTL, _json.dumps(data)
        )
        raise HTTPException(
            status_code=400, detail={"code": "otp_invalid", "message": "OTP ไม่ถูกต้อง"}
        )

    redis_client.delete(key)
    if not _grant_stepup(user, request, credentials, "otp"):
        raise HTTPException(status_code=400, detail="token ไม่มี jti — login ใหม่")

    log_action(
        db,
        actor_id=user.id,
        action=STEPUP_OTP_SUCCESS,
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"method": "otp"},
    )
    db.commit()
    return {"granted": True, "ttl_sec": settings.stepup_cache_ttl_sec}


# ════════════════════════════════════════════════════════════════════════════
# Risk-Triggered Re-Authentication (Week 9-10)
# ════════════════════════════════════════════════════════════════════════════
# Triggered จาก finalizer เมื่อ RBA decision = mfa_required + user has passkey.
# Flow:
#   GET  /auth/passkey/risk-stepup?challenge=<id>          (Hub-served HTML)
#   POST /auth/passkey/risk-stepup/start  {challenge_id}   → assertion options
#   POST /auth/passkey/risk-stepup/verify {challenge_id, credential}
#                                                          → mint redirect URL
# ----------------------------------------------------------------------------


def _load_challenge_user(challenge_id: str, db: Session) -> tuple[dict, User]:
    """Peek challenge + load User. Raise 410 ถ้า expired/missing."""
    payload = risk_challenge.peek(challenge_id)
    if not payload:
        raise HTTPException(status_code=410, detail="challenge หมดอายุ — กรุณา login ใหม่")
    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบ user")
    return payload, user


def _finalize_after_reauth(
    *,
    user: User,
    payload: dict,
    request: Request,
    db: Session,
) -> str:
    """หลัง re-auth ผ่าน → ออก authorization code (subsystem) หรือ JWT (hub_direct).

    Returns: redirect URL string.
    """
    flow = payload.get("flow")
    client_ip = get_client_ip(request)

    if flow == "subsystem":
        authreq = payload["authreq"]
        hub_state = payload["hub_state"]
        raw = redis_client.get(f"authreq:{hub_state}")
        if not raw:
            raise HTTPException(
                status_code=410, detail="OAuth session หมดอายุ — login ใหม่"
            )
        access = (
            db.query(AccessList)
            .filter(
                AccessList.user_id == user.id,
                AccessList.subsystem_id == authreq["subsystem_id"],
                AccessList.revoked_at.is_(None),
            )
            .first()
        )
        if not access:
            raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์เข้า subsystem นี้")

        auth_code = secrets.token_urlsafe(32)
        AUTH_CODE_TTL = 60
        redis_client.setex(
            f"authcode:{auth_code}",
            AUTH_CODE_TTL,
            json.dumps(
                {
                    "user_id": str(user.id),
                    "client_id": authreq["client_id"],
                    "subsystem_id": authreq["subsystem_id"],
                    "code_challenge": authreq["code_challenge"],
                    "scope": authreq["scope"],
                    "role_in_sub": access.role_in_sub,
                }
            ),
        )
        latest = (
            db.query(LoginSession)
            .filter(
                LoginSession.user_id == user.id,
                LoginSession.subsystem_id == authreq["subsystem_id"],
            )
            .order_by(LoginSession.created_at.desc())
            .first()
        )
        if latest:
            latest.decision = "mfa_passed"
        log_action(
            db,
            actor_id=user.id,
            action="risk_mfa_passed",
            target_type="subsystem",
            target_id=authreq["subsystem_id"],
            ip=client_ip,
            metadata={
                "method": "passkey",
                "risk_score": payload.get("risk_score"),
            },
        )
        redis_client.delete(f"authreq:{hub_state}")
        sep = "&" if "?" in authreq["redirect_uri"] else "?"
        return (
            f"{authreq['redirect_uri']}{sep}code={auth_code}&state={authreq['state']}"
        )

    # flow == "hub_direct"
    access_token, token_jti = create_access_token(user)
    latest = (
        db.query(LoginSession)
        .filter(LoginSession.user_id == user.id)
        .order_by(LoginSession.created_at.desc())
        .first()
    )
    refresh_token = None
    if latest:
        latest.jti = token_jti
        latest.decision = "mfa_passed"
        refresh_token, refresh_id = refresh_token_service.issue(
            user_id=str(user.id), session_id=str(latest.id)
        )
        latest.refresh_id = refresh_id
    log_action(
        db,
        actor_id=user.id,
        action="risk_mfa_passed",
        target_type="user",
        target_id=user.id,
        ip=client_ip,
        metadata={
            "method": "passkey",
            "risk_score": payload.get("risk_score"),
            "flow": "hub_direct",
        },
    )
    stepup_cache.set_granted(
        user_id=str(user.id),
        jti=token_jti,
        method="passkey",
        ip=client_ip,
    )
    refresh_qs = f"&refresh_token={refresh_token}" if refresh_token else ""
    if settings.admin_frontend_url:
        return f"{settings.admin_frontend_url}/auth/callback?token={access_token}{refresh_qs}"
    return f"/auth/me?token={access_token}{refresh_qs}"


class RiskStepupStartBody(BaseModel):
    challenge_id: str = Field(..., min_length=8, max_length=128)


class RiskStepupVerifyBody(BaseModel):
    challenge_id: str = Field(..., min_length=8, max_length=128)
    credential: dict = Field(..., description="WebAuthn assertion")


@router.get("/auth/passkey/risk-stepup", response_class=HTMLResponse)
async def risk_stepup_page(
    request: Request,
    challenge: str,
    db: Session = Depends(get_db),
):
    """Hub-served HTML page สำหรับ Risk Re-Auth (Passkey)."""
    payload, user = _load_challenge_user(challenge, db)
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    reasons = payload.get("risk_reasons") or []
    return HTMLResponse(
        content=_risk_stepup_html(
            challenge_id=challenge,
            user_email=user.email,
            risk_score=payload.get("risk_score", 0.0),
            reasons=reasons,
            nonce=nonce,
        )
    )


@router.post("/auth/passkey/risk-stepup/start")
@limiter.limit(settings.rate_limit_token)
async def risk_stepup_start(
    request: Request,
    body: RiskStepupStartBody,
    db: Session = Depends(get_db),
):
    """Return assertion options — peek challenge + stepup_begin()."""
    payload, user = _load_challenge_user(body.challenge_id, db)
    if payload.get("kind") != "reauth":
        raise HTTPException(status_code=400, detail="challenge นี้ไม่ใช่สำหรับ re-auth")
    return webauthn_service.stepup_begin(user, db)


@router.post("/auth/passkey/risk-stepup/verify")
@limiter.limit(settings.rate_limit_token)
async def risk_stepup_verify(
    request: Request,
    body: RiskStepupVerifyBody,
    db: Session = Depends(get_db),
):
    """Verify assertion + mint redirect URL (atomic consume หลัง verify ผ่าน)."""
    payload, user = _load_challenge_user(body.challenge_id, db)
    if payload.get("kind") != "reauth":
        raise HTTPException(status_code=400, detail="challenge นี้ไม่ใช่สำหรับ re-auth")
    ip = get_client_ip(request)
    try:
        result = webauthn_service.stepup_complete(
            user,
            body.credential,
            db,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
    except HTTPException as e:
        code = e.detail.get("code") if isinstance(e.detail, dict) else None
        log_action(
            db,
            actor_id=user.id,
            action="risk_mfa_verify_failed",
            target_type="user",
            target_id=user.id,
            ip=ip,
            metadata={"code": code, "method": "passkey"},
        )
        db.commit()
        raise
    if result.counter_regression:
        log_action(
            db,
            actor_id=user.id,
            action="passkey_counter_regression_during_reauth",
            target_type="passkey",
            target_id=result.credential.id,
            ip=ip,
            metadata={"risk_score": payload.get("risk_score")},
        )

    consumed = risk_challenge.consume(body.challenge_id)
    if not consumed:
        raise HTTPException(status_code=410, detail="challenge ถูกใช้ไปแล้ว — login ใหม่")
    redirect_url = _finalize_after_reauth(
        user=user, payload=consumed, request=request, db=db
    )
    db.commit()
    return JSONResponse({"redirect_url": redirect_url})


# ════════════════════════════════════════════════════════════════════════════
# Force Passkey Enrollment (Week 9-10) — High Risk + No Passkey + No Grace
# ════════════════════════════════════════════════════════════════════════════
# Triggered จาก finalizer เมื่อ RBA decision=mfa + no passkey + account_age>=7d.
# Flow:
#   GET  /auth/passkey/force-enroll?challenge=<id>     (Hub-served HTML)
#   POST .../send-otp           {challenge_id}         → ส่ง OTP email
#   POST .../verify-otp         {challenge_id, otp}    → mark OTP passed
#   POST .../register/start     {challenge_id}         → require OTP-passed
#   POST .../register/complete  {challenge_id, ...}    → enroll + redirect
#
# OTP gate — ป้องกัน attacker ที่ trigger mfa branch แล้ว register passkey ของตน
# เข้าบัญชี (B45). OTP ใช้ mfa_service เดิม (HMAC-SHA256, NIST 800-63B-4).
# ----------------------------------------------------------------------------


_FORCE_ENROLL_OTP_TTL = 300  # 5 นาที


def _force_enroll_otp_key(challenge_id: str) -> str:
    return f"force_enroll_otp:{challenge_id}"


def _force_enroll_otp_passed_key(challenge_id: str) -> str:
    return f"force_enroll_otp_passed:{challenge_id}"


def _require_otp_passed(challenge_id: str) -> None:
    """403 ถ้าไม่มี force_enroll_otp_passed flag ใน Redis."""
    if not redis_client.get(_force_enroll_otp_passed_key(challenge_id)):
        raise HTTPException(
            status_code=403,
            detail={"code": "otp_required", "message": "กรุณายืนยัน OTP ก่อน"},
        )


class ForceEnrollOTPSendBody(BaseModel):
    challenge_id: str = Field(..., min_length=8, max_length=128)


class ForceEnrollOTPVerifyBody(BaseModel):
    challenge_id: str = Field(..., min_length=8, max_length=128)
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class ForceEnrollStartBody(BaseModel):
    challenge_id: str = Field(..., min_length=8, max_length=128)


class ForceEnrollCompleteBody(BaseModel):
    challenge_id: str = Field(..., min_length=8, max_length=128)
    credential: dict = Field(..., description="WebAuthn attestation")
    device_name: str = Field("อุปกรณ์ของฉัน", max_length=100)


@router.get("/auth/passkey/force-enroll", response_class=HTMLResponse)
async def force_enroll_page(
    request: Request,
    challenge: str,
    db: Session = Depends(get_db),
):
    """Hub-served HTML page สำหรับ Force Enrollment (OTP + Passkey register)."""
    payload, user = _load_challenge_user(challenge, db)
    if payload.get("kind") != "enroll":
        raise HTTPException(status_code=400, detail="challenge นี้ไม่ใช่สำหรับ enroll")
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    parts = user.email.split("@")
    email_masked = (
        f"{parts[0][0]}***{parts[0][-1] if len(parts[0]) > 1 else ''}@{parts[1]}"
        if len(parts) == 2 and parts[0]
        else "***"
    )
    return HTMLResponse(
        content=_force_enroll_html(
            challenge_id=challenge,
            email_masked=email_masked,
            risk_score=payload.get("risk_score", 0.0),
            reasons=payload.get("risk_reasons") or [],
            nonce=nonce,
        )
    )


@router.post("/auth/passkey/force-enroll/send-otp")
@limiter.limit("3/minute")
async def force_enroll_send_otp(
    request: Request,
    body: ForceEnrollOTPSendBody,
    db: Session = Depends(get_db),
):
    """สร้าง OTP + ส่ง email + เก็บ hash ใน Redis."""
    from datetime import datetime, timedelta

    from app.services.mfa_service import generate_otp, hash_otp, send_otp_email

    payload, user = _load_challenge_user(body.challenge_id, db)
    if payload.get("kind") != "enroll":
        raise HTTPException(status_code=400, detail="challenge นี้ไม่ใช่สำหรับ enroll")

    otp = generate_otp()
    expires_at = datetime.utcnow() + timedelta(seconds=_FORCE_ENROLL_OTP_TTL)
    redis_client.setex(
        _force_enroll_otp_key(body.challenge_id),
        _FORCE_ENROLL_OTP_TTL,
        hash_otp(otp),
    )
    log_action(
        db,
        actor_id=user.id,
        action="risk_force_enroll_otp_sent",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"challenge_id": body.challenge_id},
    )
    db.commit()
    # fail-safe — ถ้า SMTP ไม่ตั้งค่า log warning + ดำเนินต่อ
    send_otp_email(user.email, otp, expires_at)
    return {
        "sent": True,
        "expires_at": expires_at.isoformat(),
        "ttl_sec": _FORCE_ENROLL_OTP_TTL,
    }


@router.post("/auth/passkey/force-enroll/verify-otp")
@limiter.limit("10/minute")
async def force_enroll_verify_otp(
    request: Request,
    body: ForceEnrollOTPVerifyBody,
    db: Session = Depends(get_db),
):
    """Verify OTP + set passed flag."""
    from app.services.mfa_service import verify_otp

    payload, user = _load_challenge_user(body.challenge_id, db)
    stored_hash = redis_client.get(_force_enroll_otp_key(body.challenge_id))
    if not stored_hash:
        raise HTTPException(status_code=410, detail="OTP หมดอายุ — กรุณาขอ OTP ใหม่")
    stored = stored_hash.decode() if isinstance(stored_hash, bytes) else stored_hash
    if not verify_otp(stored, body.otp):
        log_action(
            db,
            actor_id=user.id,
            action="risk_force_enroll_otp_failed",
            target_type="user",
            target_id=user.id,
            ip=get_client_ip(request),
            metadata={"challenge_id": body.challenge_id},
        )
        db.commit()
        raise HTTPException(status_code=401, detail="OTP ไม่ถูกต้อง")

    # ผ่าน — set passed flag + delete OTP hash
    redis_client.setex(
        _force_enroll_otp_passed_key(body.challenge_id),
        _FORCE_ENROLL_OTP_TTL,
        "1",
    )
    redis_client.delete(_force_enroll_otp_key(body.challenge_id))
    log_action(
        db,
        actor_id=user.id,
        action="risk_force_enroll_otp_verified",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"challenge_id": body.challenge_id},
    )
    db.commit()
    return {"verified": True}


@router.post("/auth/passkey/force-enroll/register/start")
@limiter.limit(settings.rate_limit_token)
async def force_enroll_register_start(
    request: Request,
    body: ForceEnrollStartBody,
    db: Session = Depends(get_db),
):
    """Return registration options — ต้องผ่าน OTP ก่อน."""
    _require_otp_passed(body.challenge_id)
    payload, user = _load_challenge_user(body.challenge_id, db)
    return webauthn_service.register_begin(user, db)


@router.post("/auth/passkey/force-enroll/register/complete")
@limiter.limit(settings.rate_limit_token)
async def force_enroll_register_complete(
    request: Request,
    body: ForceEnrollCompleteBody,
    db: Session = Depends(get_db),
):
    """Verify attestation + create credential + backup codes + mint redirect.

    Atomic: consume challenge **หลัง** register ผ่าน — กัน replay.
    """
    _require_otp_passed(body.challenge_id)
    payload, user = _load_challenge_user(body.challenge_id, db)
    ip = get_client_ip(request)

    try:
        row = webauthn_service.register_complete(
            user, body.credential, body.device_name, db
        )
    except HTTPException as e:
        code = e.detail.get("code") if isinstance(e.detail, dict) else None
        log_action(
            db,
            actor_id=user.id,
            action="risk_force_enroll_register_failed",
            target_type="passkey",
            ip=ip,
            metadata={"code": code, "challenge_id": body.challenge_id},
        )
        db.commit()
        raise

    log_action(
        db,
        actor_id=user.id,
        action="passkey_registered",
        target_type="passkey",
        target_id=row.id,
        ip=ip,
        metadata={
            "device_name": row.device_name,
            "via": "risk_force_enroll",
            "risk_score": payload.get("risk_score"),
        },
    )
    # ออก backup codes — passkey แรกของ user (Force Enroll = ไม่มี passkey มาก่อน)
    codes = passkey_recovery.ensure_backup_codes(user.id, db)
    if codes:
        log_action(
            db,
            actor_id=user.id,
            action="passkey_backup_codes_generated",
            target_type="user",
            target_id=user.id,
            ip=ip,
            metadata={"count": len(codes), "trigger": "risk_force_enroll"},
        )

    # consume challenge + cleanup OTP flag
    consumed = risk_challenge.consume(body.challenge_id)
    if not consumed:
        raise HTTPException(status_code=410, detail="challenge ถูกใช้ไปแล้ว — login ใหม่")
    redis_client.delete(_force_enroll_otp_passed_key(body.challenge_id))

    # mint redirect URL (same finalizer as re-auth — issues auth code/JWT)
    redirect_url = _finalize_after_reauth(
        user=user, payload=consumed, request=request, db=db
    )
    db.commit()
    return JSONResponse(
        {
            "redirect_url": redirect_url,
            "passkey_id": str(row.id),
            "backup_codes": codes if codes else None,
        }
    )


def _force_enroll_html(
    *,
    challenge_id: str,
    email_masked: str,
    risk_score: float,
    reasons: list,
    nonce: str,
) -> str:
    """Force Enrollment page — OTP gate (step 1) + Passkey register (step 2)."""
    safe_email = (
        email_masked.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    reasons_html = (
        "".join(
            f"<li>{r.replace('<', '&lt;').replace('>', '&gt;')}</li>"
            for r in reasons[:5]
        )
        or "<li>ตรวจพบความเสี่ยงผิดปกติจากระบบ ML</li>"
    )
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>ลงทะเบียน Passkey · Central Auth Hub</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Kanit:wght@500;600;700&family=IBM+Plex+Sans+Thai:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style nonce="{nonce}">
  :root {{ --bg-0:#070b14; --ink:#e8eef7; --muted:#8a99b5; --mint:#34e8c4;
           --mint-2:#13b89a; --line:rgba(148,178,224,.14); --danger:#ff6b81; --amber:#f5b97a; }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; height:100%; }}
  body {{ font-family:'IBM Plex Sans Thai',system-ui,sans-serif; background:var(--bg-0);
          color:var(--ink); min-height:100vh; display:grid; place-items:center;
          padding:32px 16px; overflow:hidden; position:relative; }}
  body::before {{ content:''; position:fixed; inset:-20%; z-index:0;
    background:radial-gradient(40% 50% at 18% 22%, rgba(245,185,122,.18), transparent 70%),
      radial-gradient(45% 55% at 85% 18%, rgba(255,107,129,.12), transparent 70%);
    filter:blur(20px); }}
  .card {{ position:relative; z-index:1; width:100%; max-width:460px;
    background:linear-gradient(180deg, rgba(20,28,48,.86), rgba(11,17,32,.92));
    border:1px solid var(--line); border-radius:22px; backdrop-filter:blur(14px);
    box-shadow:0 30px 80px -20px rgba(0,0,0,.7); overflow:hidden;
    animation:rise .7s cubic-bezier(.2,.8,.2,1) both; }}
  @keyframes rise {{ from{{opacity:0; transform:translateY(16px)}} to{{opacity:1; transform:none}} }}
  .top {{ padding:30px 32px 4px; text-align:center; }}
  .emblem {{ width:62px; height:62px; margin:0 auto 14px; border-radius:18px;
    background:linear-gradient(135deg, rgba(245,185,122,.2), rgba(245,185,122,.05));
    border:1px solid rgba(245,185,122,.35); display:grid; place-items:center; color:var(--amber); }}
  h1 {{ font-family:'Kanit',sans-serif; font-weight:600; font-size:22px; margin:0 0 6px; }}
  .sub {{ color:var(--muted); font-size:13.5px; margin:0; line-height:1.55; }}
  .who {{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--mint);
          margin-top:10px; word-break:break-all; }}
  .body {{ padding:20px 32px 26px; }}
  .reasons {{ background:rgba(255,107,129,.06); border:1px solid rgba(255,107,129,.22);
    border-radius:12px; padding:14px 16px; margin-bottom:18px; }}
  .reasons-title {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase;
    color:var(--danger); margin-bottom:6px; font-family:'IBM Plex Mono',monospace; }}
  .reasons ul {{ margin:0; padding-left:18px; font-size:13px; color:#c4d0e4; line-height:1.6; }}
  .score {{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--muted); margin-top:8px; }}
  .step {{ display:none; }}
  .step.active {{ display:block; }}
  .step-h {{ font-family:'Kanit',sans-serif; font-size:14px; color:var(--mint);
             margin:0 0 10px; letter-spacing:.04em; }}
  label.fld {{ font-size:11px; color:var(--muted); font-family:'IBM Plex Mono',monospace;
               display:block; margin-bottom:6px; }}
  input {{ width:100%; padding:13px 14px; border-radius:11px; border:1px solid var(--line);
           background:rgba(7,11,20,.7); color:var(--ink); font-size:14.5px;
           font-family:'IBM Plex Sans Thai',sans-serif; margin-bottom:14px; }}
  input:focus {{ outline:none; border-color:var(--mint-2); box-shadow:0 0 0 3px rgba(52,232,196,.16); }}
  #otpIn {{ font-family:'IBM Plex Mono',monospace; font-size:24px; letter-spacing:.4em;
            text-align:center; padding:14px; }}
  .btn {{ display:flex; align-items:center; justify-content:center; gap:10px; width:100%;
    padding:14px 16px; border-radius:13px; font-family:'Kanit',sans-serif; font-weight:500;
    font-size:15.5px; border:1px solid transparent; cursor:pointer; text-decoration:none;
    transition:transform .15s; }}
  .btn-pk {{ color:#04221c; background:linear-gradient(100deg,var(--mint),#5ff0d6);
             box-shadow:0 10px 30px -10px rgba(52,232,196,.6); }}
  .btn-pk:hover {{ transform:translateY(-2px); }}
  .btn-pk[disabled] {{ opacity:.5; cursor:not-allowed; transform:none; }}
  .btn-recover {{ color:var(--muted); background:transparent; margin-top:10px; font-size:13px; }}
  .btn-recover:hover {{ color:var(--ink); }}
  .err {{ display:none; font-size:12.5px; color:var(--danger); margin-bottom:12px;
    background:rgba(255,107,129,.08); border:1px solid rgba(255,107,129,.28);
    padding:10px 12px; border-radius:10px; line-height:1.45; }}
  .err.show {{ display:block; }}
  .ok {{ display:none; font-size:12.5px; color:var(--mint); margin-bottom:12px;
    background:rgba(52,232,196,.08); border:1px solid rgba(52,232,196,.28);
    padding:10px 12px; border-radius:10px; }}
  .ok.show {{ display:block; }}
  .unsupported {{ display:none; font-size:12.5px; color:var(--amber); margin-bottom:12px;
    background:rgba(245,185,122,.08); border:1px solid rgba(245,185,122,.28);
    padding:12px 14px; border-radius:10px; line-height:1.55; }}
  .unsupported.show {{ display:block; }}
  .spinner {{ width:16px; height:16px; border:2px solid rgba(4,34,28,.35);
    border-top-color:#04221c; border-radius:50%; animation:spin .7s linear infinite; }}
  @keyframes spin {{ to{{transform:rotate(360deg)}} }}
  .foot {{ padding:13px 32px; border-top:1px solid var(--line); text-align:center;
    font-family:'IBM Plex Mono',monospace; font-size:10px; color:#56657f; letter-spacing:.06em; }}
  .codes {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:6px 0 16px; }}
  .code {{ font-family:'IBM Plex Mono',monospace; font-size:13.5px; letter-spacing:.06em;
    background:rgba(7,11,20,.8); border:1px solid var(--line); border-radius:9px;
    padding:8px 10px; color:#cfe; text-align:center; }}
</style></head><body>
<div class="card">
  <div class="top">
    <div class="emblem">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
    </div>
    <h1>ต้องลงทะเบียน Passkey</h1>
    <p class="sub">ระบบตรวจพบความเสี่ยงสูง — กรุณาตั้งค่า Passkey<br>เพื่อความปลอดภัยของบัญชีคุณ</p>
    <div class="who">{safe_email}</div>
  </div>
  <div class="body">
    <div class="reasons">
      <div class="reasons-title">ปัจจัยเสี่ยงที่ตรวจพบ</div>
      <ul>{reasons_html}</ul>
      <div class="score">risk_score: {risk_score:.3f}</div>
    </div>

    <div class="err" id="err"></div>
    <div class="ok" id="ok"></div>
    <div class="unsupported" id="unsupported">
      ⚠️ <strong>เบราว์เซอร์นี้ไม่รองรับ Passkey</strong><br>
      กรุณาใช้อุปกรณ์ที่รองรับ หรือใช้
      <a href="/auth/passkey/recover" style="color:var(--mint)">Account Recovery</a>
    </div>

    <div class="step active" id="step1">
      <div class="step-h">ขั้นที่ 1 — ยืนยัน OTP ทาง email</div>
      <button class="btn btn-pk" id="sendBtn">📧 ส่ง OTP ไปที่ email</button>
      <label class="fld" for="otpIn" style="margin-top:14px">รหัส OTP 6 หลัก</label>
      <input type="text" id="otpIn" inputmode="numeric" maxlength="6" pattern="\\d{{6}}" placeholder="——————">
      <button class="btn btn-pk" id="verifyOtpBtn" disabled style="margin-top:6px">ยืนยัน OTP</button>
    </div>

    <div class="step" id="step2">
      <div class="step-h">ขั้นที่ 2 — ตั้งค่า Passkey</div>
      <label class="fld" for="dev">ชื่ออุปกรณ์</label>
      <input type="text" id="dev" value="อุปกรณ์ของฉัน" maxlength="100">
      <button class="btn btn-pk" id="enrollBtn">🔑 ตั้งค่า Passkey</button>
    </div>

    <a class="btn btn-recover" href="/auth/passkey/recover">ทำ Passkey หาย? → กู้บัญชี</a>
  </div>
  <div class="foot">WebAuthn · FIDO2 · Force Enrollment</div>
</div>
<script nonce="{nonce}">
const CHALLENGE_ID = {json.dumps(challenge_id)};
function b64urlToBuf(s) {{ const p=s.replace(/-/g,'+').replace(/_/g,'/');
  const pad=p.length%4===0?'':'='.repeat(4-(p.length%4)); const bin=atob(p+pad);
  const a=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i); return a.buffer; }}
function bufToB64url(buf) {{ const a=new Uint8Array(buf); let b='';
  for(let i=0;i<a.length;i++)b+=String.fromCharCode(a[i]);
  return btoa(b).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,''); }}
function pkSupported() {{ return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.create); }}

const errEl=document.getElementById('err'), okEl=document.getElementById('ok');
const sendBtn=document.getElementById('sendBtn'), otpIn=document.getElementById('otpIn');
const verifyBtn=document.getElementById('verifyOtpBtn'), enrollBtn=document.getElementById('enrollBtn');
const devEl=document.getElementById('dev');
const step1=document.getElementById('step1'), step2=document.getElementById('step2');

function showErr(m){{ errEl.textContent=m; errEl.classList.add('show'); okEl.classList.remove('show'); }}
function showOk(m){{ okEl.textContent=m; okEl.classList.add('show'); errEl.classList.remove('show'); }}

if(!pkSupported()){{
  document.getElementById('unsupported').classList.add('show');
  sendBtn.disabled=true; enrollBtn.disabled=true;
}}

otpIn.addEventListener('input', ()=>{{ verifyBtn.disabled = !/^\\d{{6}}$/.test(otpIn.value); }});

sendBtn.addEventListener('click', async()=>{{
  errEl.classList.remove('show');
  sendBtn.disabled=true; sendBtn.innerHTML='<span class="spinner"></span> กำลังส่ง…';
  try {{
    const r=await fetch('/auth/passkey/force-enroll/send-otp',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{challenge_id:CHALLENGE_ID}})}});
    if(!r.ok){{ const e=await r.json().catch(()=>({{}})); throw new Error(e.detail||'ส่งไม่สำเร็จ'); }}
    showOk('✓ ส่ง OTP ไปแล้ว — ตรวจ email ของคุณ');
    sendBtn.textContent='📧 ส่งใหม่อีกครั้ง'; sendBtn.disabled=false;
  }} catch(err){{ showErr(err.message||'ส่งไม่สำเร็จ');
    sendBtn.disabled=false; sendBtn.textContent='📧 ส่ง OTP ไปที่ email'; }}
}});

verifyBtn.addEventListener('click', async()=>{{
  errEl.classList.remove('show');
  verifyBtn.disabled=true; verifyBtn.innerHTML='<span class="spinner"></span> กำลังตรวจ…';
  try {{
    const r=await fetch('/auth/passkey/force-enroll/verify-otp',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{challenge_id:CHALLENGE_ID,otp:otpIn.value}})}});
    if(!r.ok){{ const e=await r.json().catch(()=>({{}})); throw new Error(e.detail||'OTP ไม่ถูกต้อง'); }}
    showOk('✓ ยืนยัน OTP สำเร็จ — กรุณาตั้งค่า Passkey');
    step1.classList.remove('active'); step2.classList.add('active');
  }} catch(err){{ showErr(err.message||'OTP ไม่ถูกต้อง');
    verifyBtn.disabled=false; verifyBtn.textContent='ยืนยัน OTP'; }}
}});

enrollBtn.addEventListener('click', async()=>{{
  errEl.classList.remove('show');
  const dev=(devEl.value||'').trim()||'อุปกรณ์ของฉัน';
  enrollBtn.disabled=true; enrollBtn.innerHTML='<span class="spinner"></span> กำลังตั้งค่า…';
  try {{
    const s=await fetch('/auth/passkey/force-enroll/register/start',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{challenge_id:CHALLENGE_ID}})}});
    if(!s.ok){{ const e=await s.json().catch(()=>({{}})); throw new Error(typeof e.detail==='string'?e.detail:'เริ่มไม่สำเร็จ'); }}
    const opts=await s.json();
    opts.challenge=b64urlToBuf(opts.challenge);
    opts.user.id=b64urlToBuf(opts.user.id);
    (opts.excludeCredentials||[]).forEach(c=>c.id=b64urlToBuf(c.id));
    let cred;
    try {{ cred=await navigator.credentials.create({{publicKey:opts}}); }}
    catch(ce){{ throw new Error('การตั้งค่าถูกยกเลิก หรืออุปกรณ์ไม่รองรับ'); }}
    if(!cred) throw new Error('ไม่ได้รับข้อมูลจากอุปกรณ์');
    const resp=cred.response;
    const payload={{ id:cred.id, rawId:bufToB64url(cred.rawId), type:cred.type,
      authenticatorAttachment:cred.authenticatorAttachment,
      response:{{ attestationObject:bufToB64url(resp.attestationObject),
        clientDataJSON:bufToB64url(resp.clientDataJSON),
        transports:resp.getTransports?resp.getTransports():[] }} }};
    const f=await fetch('/auth/passkey/force-enroll/register/complete',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{challenge_id:CHALLENGE_ID,device_name:dev,credential:payload}})}});
    if(!f.ok){{ const e=await f.json().catch(()=>({{}})); throw new Error(typeof e.detail==='string'?e.detail:'ตั้งค่าไม่สำเร็จ'); }}
    const data=await f.json();
    if(data.backup_codes && data.backup_codes.length){{
      const codesDiv=document.createElement('div');
      codesDiv.className='reasons'; codesDiv.style.marginTop='14px';
      codesDiv.innerHTML='<div class="step-h" style="color:var(--mint)">🔑 Backup Codes (เก็บไว้กู้บัญชี)</div>'+
        '<div class="codes">'+data.backup_codes.map(c=>'<div class="code">'+c+'</div>').join('')+'</div>'+
        '<button class="btn btn-pk" id="contBtn">บันทึกแล้ว → ดำเนินการต่อ</button>';
      step2.innerHTML=''; step2.appendChild(codesDiv);
      document.getElementById('contBtn').addEventListener('click', ()=>{{ window.location.href=data.redirect_url; }});
    }} else {{ window.location.href=data.redirect_url; }}
  }} catch(err){{ showErr(err.message||'ตั้งค่าไม่สำเร็จ');
    enrollBtn.disabled=false; enrollBtn.textContent='🔑 ตั้งค่า Passkey'; }}
}});
</script>
</body></html>"""


def _risk_stepup_html(
    *,
    challenge_id: str,
    user_email: str,
    risk_score: float,
    reasons: list,
    nonce: str,
) -> str:
    """Hub-served HTML page สำหรับ Risk Re-Auth (Passkey).

    Dark theme + IBM Plex Sans Thai + CSP nonce — pattern เดียวกับ
    _passkey_enroll_html ใน oauth.py.
    """
    safe_email = (
        user_email.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    reasons_html = (
        "".join(
            f"<li>{r.replace('<', '&lt;').replace('>', '&gt;')}</li>"
            for r in reasons[:5]
        )
        or "<li>ตรวจพบความเสี่ยงผิดปกติจากระบบ ML</li>"
    )
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>ยืนยันตัวตน · Central Auth Hub</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Kanit:wght@500;600;700&family=IBM+Plex+Sans+Thai:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style nonce="{nonce}">
  :root {{ --bg-0:#070b14; --ink:#e8eef7; --muted:#8a99b5; --mint:#34e8c4;
           --mint-2:#13b89a; --line:rgba(148,178,224,.14); --danger:#ff6b81; --amber:#f5b97a; }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; height:100%; }}
  body {{ font-family:'IBM Plex Sans Thai',system-ui,sans-serif; background:var(--bg-0);
          color:var(--ink); min-height:100vh; display:grid; place-items:center;
          padding:32px 16px; overflow:hidden; position:relative; }}
  body::before {{ content:''; position:fixed; inset:-20%; z-index:0;
    background:radial-gradient(40% 50% at 18% 22%, rgba(245,185,122,.16), transparent 70%),
      radial-gradient(45% 55% at 85% 18%, rgba(82,120,255,.16), transparent 70%);
    filter:blur(20px); }}
  .card {{ position:relative; z-index:1; width:100%; max-width:440px;
    background:linear-gradient(180deg, rgba(20,28,48,.86), rgba(11,17,32,.92));
    border:1px solid var(--line); border-radius:22px; backdrop-filter:blur(14px);
    box-shadow:0 30px 80px -20px rgba(0,0,0,.7); overflow:hidden;
    animation:rise .7s cubic-bezier(.2,.8,.2,1) both; }}
  @keyframes rise {{ from{{opacity:0; transform:translateY(16px)}} to{{opacity:1; transform:none}} }}
  .top {{ padding:30px 32px 4px; text-align:center; }}
  .emblem {{ width:62px; height:62px; margin:0 auto 14px; border-radius:18px;
    background:linear-gradient(135deg, rgba(245,185,122,.2), rgba(245,185,122,.05));
    border:1px solid rgba(245,185,122,.35); display:grid; place-items:center; color:var(--amber); }}
  h1 {{ font-family:'Kanit',sans-serif; font-weight:600; font-size:24px; margin:0 0 6px; }}
  .sub {{ color:var(--muted); font-size:13.5px; margin:0; line-height:1.55; }}
  .who {{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--mint);
          margin-top:10px; word-break:break-all; }}
  .body {{ padding:20px 32px 26px; }}
  .reasons {{ background:rgba(245,185,122,.08); border:1px solid rgba(245,185,122,.22);
    border-radius:12px; padding:14px 16px; margin-bottom:18px; }}
  .reasons-title {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase;
    color:var(--amber); margin-bottom:6px; font-family:'IBM Plex Mono',monospace; }}
  .reasons ul {{ margin:0; padding-left:18px; font-size:13px; color:#c4d0e4; line-height:1.6; }}
  .score {{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--muted); margin-top:8px; }}
  .btn {{ display:flex; align-items:center; justify-content:center; gap:10px; width:100%;
    padding:14px 16px; border-radius:13px; font-family:'Kanit',sans-serif; font-weight:500;
    font-size:15.5px; border:1px solid transparent; cursor:pointer; text-decoration:none;
    transition:transform .15s; }}
  .btn-pk {{ color:#04221c; background:linear-gradient(100deg,var(--mint),#5ff0d6);
             box-shadow:0 10px 30px -10px rgba(52,232,196,.6); }}
  .btn-pk:hover {{ transform:translateY(-2px); }}
  .btn-pk[disabled] {{ opacity:.5; cursor:not-allowed; transform:none; }}
  .btn-recover {{ color:var(--muted); background:transparent; margin-top:10px; font-size:13px; }}
  .btn-recover:hover {{ color:var(--ink); }}
  .err {{ display:none; font-size:12.5px; color:var(--danger); margin-bottom:12px;
    background:rgba(255,107,129,.08); border:1px solid rgba(255,107,129,.28);
    padding:10px 12px; border-radius:10px; line-height:1.45; }}
  .err.show {{ display:block; }}
  .unsupported {{ display:none; font-size:12.5px; color:var(--amber); margin-bottom:12px;
    background:rgba(245,185,122,.08); border:1px solid rgba(245,185,122,.28);
    padding:12px 14px; border-radius:10px; line-height:1.55; }}
  .unsupported.show {{ display:block; }}
  .spinner {{ width:16px; height:16px; border:2px solid rgba(4,34,28,.35);
    border-top-color:#04221c; border-radius:50%; animation:spin .7s linear infinite; }}
  @keyframes spin {{ to{{transform:rotate(360deg)}} }}
  .foot {{ padding:13px 32px; border-top:1px solid var(--line); text-align:center;
    font-family:'IBM Plex Mono',monospace; font-size:10px; color:#56657f; letter-spacing:.06em; }}
</style></head><body>
<div class="card">
  <div class="top">
    <div class="emblem">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
    </div>
    <h1>ยืนยันตัวตนอีกครั้ง</h1>
    <p class="sub">ระบบตรวจพบความเสี่ยงจากการ login ครั้งนี้<br>กรุณายืนยันด้วย Passkey เพื่อความปลอดภัย</p>
    <div class="who">{safe_email}</div>
  </div>
  <div class="body">
    <div class="reasons">
      <div class="reasons-title">ปัจจัยเสี่ยงที่ตรวจพบ</div>
      <ul>{reasons_html}</ul>
      <div class="score">risk_score: {risk_score:.3f}</div>
    </div>
    <div class="err" id="err"></div>
    <div class="unsupported" id="unsupported">
      ⚠️ <strong>เบราว์เซอร์นี้ไม่รองรับ Passkey</strong><br>
      กรุณาใช้อุปกรณ์ที่รองรับ หรือใช้ <a href="/auth/passkey/recover" style="color:var(--mint)">Account Recovery</a>
    </div>
    <button class="btn btn-pk" id="verify">🔑 ยืนยันด้วย Passkey</button>
    <a class="btn btn-recover" href="/auth/passkey/recover">ทำ Passkey หาย? → กู้บัญชี</a>
  </div>
  <div class="foot">WebAuthn · FIDO2 · Risk-Based Authentication</div>
</div>
<script nonce="{nonce}">
const CHALLENGE_ID = {json.dumps(challenge_id)};
function b64urlToBuf(s) {{ const p=s.replace(/-/g,'+').replace(/_/g,'/');
  const pad=p.length%4===0?'':'='.repeat(4-(p.length%4)); const bin=atob(p+pad);
  const a=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i); return a.buffer; }}
function bufToB64url(buf) {{ const a=new Uint8Array(buf); let b='';
  for(let i=0;i<a.length;i++)b+=String.fromCharCode(a[i]);
  return btoa(b).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,''); }}
function pkSupported() {{ return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.get); }}

const btn=document.getElementById('verify'), errEl=document.getElementById('err');
function showErr(m){{ errEl.textContent=m; errEl.classList.add('show'); }}

if(!pkSupported()){{
  document.getElementById('unsupported').classList.add('show');
  btn.disabled=true;
}}

async function doVerify(){{
  errEl.classList.remove('show');
  btn.disabled=true; btn.innerHTML='<span class="spinner"></span> กำลังยืนยัน…';
  try {{
    const s=await fetch('/auth/passkey/risk-stepup/start',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{challenge_id:CHALLENGE_ID}})}});
    if(!s.ok){{ const e=await s.json().catch(()=>({{}})); throw new Error(typeof e.detail==='string'?e.detail:'เริ่มไม่สำเร็จ'); }}
    const opts=await s.json();
    opts.challenge=b64urlToBuf(opts.challenge);
    (opts.allowCredentials||[]).forEach(c=>c.id=b64urlToBuf(c.id));
    let assertion;
    try {{ assertion=await navigator.credentials.get({{publicKey:opts}}); }}
    catch(ce){{ throw new Error('การยืนยันถูกยกเลิก หรืออุปกรณ์ไม่รองรับ'); }}
    if(!assertion) throw new Error('ไม่ได้รับข้อมูลจากอุปกรณ์');
    const r=assertion.response;
    const payload={{ id:assertion.id, rawId:bufToB64url(assertion.rawId), type:assertion.type,
      response:{{ authenticatorData:bufToB64url(r.authenticatorData),
        clientDataJSON:bufToB64url(r.clientDataJSON),
        signature:bufToB64url(r.signature),
        userHandle:r.userHandle?bufToB64url(r.userHandle):null }} }};
    const f=await fetch('/auth/passkey/risk-stepup/verify',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{challenge_id:CHALLENGE_ID,credential:payload}})}});
    if(!f.ok){{ const e=await f.json().catch(()=>({{}})); const d=e.detail;
      throw new Error(typeof d==='string'?d:(d&&d.code?d.code:'ยืนยันไม่สำเร็จ')); }}
    const data=await f.json();
    window.location.href=data.redirect_url;
  }} catch(err){{ showErr(err.message||'ยืนยันไม่สำเร็จ');
    btn.disabled=false; btn.textContent='🔑 ยืนยันด้วย Passkey'; }}
}}
btn.addEventListener('click', doVerify);
</script>
</body></html>"""
