"""Passkey / WebAuthn router — Phase 1 (plan v3).

Phase 1 endpoints (registration + mandatory backup codes):

    POST /account/passkeys/register/start
    POST /account/passkeys/register/finish
    POST /account/passkeys/backup-codes/acknowledge
    GET  /account/passkeys/backup-codes/status

**Admin only** — ทุก endpoint ใช้ ``Depends(require_hub_admin)``.
Hub console security page สำหรับ admin จัดการ passkey ของตัวเอง.
teacher/staff/นักศึกษา ลง passkey ผ่าน subsystem enroll interstitial
(``/oauth/passkey/enroll/*``) แทน — เข้า console ไม่ได้.

The first Passkey registration auto-generates 10 backup codes (Improvement #3)
and returns them in the ``register/finish`` response. Subsequent registrations
do NOT regenerate codes — those need explicit /backup-codes/regenerate (Phase 4).

Critical Action Policy (Improvement #8): ``register_new_passkey`` is a critical
action, so the start endpoint goes through ``critical_action_policy.gate(...)``
EXCEPT for the very first Passkey (which can't have step-up cache yet).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, get_current_user, require_hub_admin
from app.models import LoginSession, User
from app.rate_limiter import limiter
from app.services import passkey_recovery, stepup_cache, webauthn_service
from app.services.audit_service import log_action
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
    user: User = Depends(require_hub_admin),
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
    user: User = Depends(require_hub_admin),
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
    user: User = Depends(require_hub_admin),
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
    user: User = Depends(require_hub_admin),
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
    user: User = Depends(require_hub_admin),
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
    user: User = Depends(require_hub_admin),
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
    user: User = Depends(require_hub_admin),
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
    user: User = Depends(require_hub_admin),
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
