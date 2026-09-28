"""Recovery Ticket with evidence, verified alternate email, and resumable status."""

import base64
import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import RecoveryTicket, RecoveryTicketApproval, User
from app.rate_limiter import limiter
from app.redis_client import redis_client
from app.routers.account_link import _mint_change_token
from app.services import mfa_service
from app.services.audit_service import log_action
from app.services.alert_service import send_alert
from app.services.critical_action_policy import gate as _stepup_gate
from app.services.email_service import send_recovery_link_email
from app.services.secret_service import decrypt_secret, encrypt_secret, hash_secret, verify_secret

log = logging.getLogger(__name__)
router = APIRouter()

_LINK_TTL = 86400  # 24 ชั่วโมง — ให้ผู้ใช้มีเวลาทำรายการโดยไม่ลดความเป็น one-time
_ALT_OTP_TTL = 600
_ALT_VERIFY_TTL = 900
_ALT_MAX_ATTEMPTS = 5
_MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
_REQUIRED = {"NORMAL": 1, "HIGH": 2}
_ALLOWED_EVIDENCE = {"student_card", "citizen_id"}
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
_ALLOWED_REQUEST_KINDS = {"account_recovery", "blocked_account_appeal"}


class AlternateEmailBody(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    alternate_email: EmailStr = Field(..., max_length=255)


class AlternateEmailVerifyBody(AlternateEmailBody):
    otp: str = Field(..., min_length=6, max_length=8)


class RecoveryRequestBody(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    request_kind: str = Field("account_recovery", max_length=32)
    credential_type: str | None = Field(None, max_length=20)
    reason: str | None = Field(None, max_length=1000)
    evidence_type: str = Field(..., max_length=30)
    evidence_mime: str = Field(..., max_length=50)
    evidence_image: str = Field(..., min_length=32, max_length=6_000_000)
    alternate_email: EmailStr | None = Field(None, max_length=255)
    alternate_verification_token: str | None = Field(None, max_length=128)


class RecoveryStatusBody(BaseModel):
    ticket_id: str = Field(..., min_length=30, max_length=64)
    tracking_secret: str = Field(..., min_length=20, max_length=128)


class ApproveBody(BaseModel):
    evidence_type: str | None = Field(None, max_length=30)
    evidence_note: str | None = Field(None, max_length=1000)
    remark: str | None = Field(None, max_length=1000)


def _alt_key(prefix: str, email: str, alternate_email: str) -> str:
    value = f"{email.strip().lower()}|{alternate_email.strip().lower()}".encode()
    return f"recovery:{prefix}:{hashlib.sha256(value).hexdigest()}"


def _decode_evidence(raw: str, mime: str) -> bytes:
    if mime not in _ALLOWED_MIME:
        raise HTTPException(status_code=422, detail="รองรับเฉพาะ JPG, PNG หรือ WEBP")
    encoded = raw.split(",", 1)[1] if raw.startswith("data:") and "," in raw else raw
    try:
        data = base64.b64decode(encoded, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="ไฟล์หลักฐานไม่ถูกต้อง")
    if not data or len(data) > _MAX_EVIDENCE_BYTES:
        raise HTTPException(status_code=422, detail="ไฟล์หลักฐานต้องไม่เกิน 4 MB")
    valid = (
        (mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
        or (mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )
    if not valid:
        raise HTTPException(status_code=422, detail="ชนิดไฟล์ไม่ตรงกับเนื้อหา")
    return data


def _consume_alternate_verification(
    token: str | None, email: str, alternate_email: str | None
) -> bool:
    if not token or not alternate_email:
        return False
    raw = redis_client.getdel(f"recovery:alt:verified:{token}")
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return (
        data.get("email") == email
        and data.get("alternate_email") == alternate_email
    )


@router.get("/auth/recovery/ticket", response_class=HTMLResponse)
def recovery_ticket_page(request: Request):
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    return HTMLResponse(_ticket_page_html(nonce))


@router.post("/auth/recovery/alternate-email/start")
@limiter.limit("5/hour")
def alternate_email_start(request: Request, body: AlternateEmailBody):
    email = body.email.strip().lower()
    alternate = body.alternate_email.strip().lower()
    if alternate == email:
        raise HTTPException(status_code=422, detail="อีเมลสำรองต้องไม่ซ้ำอีเมลบัญชี")

    # ส่งไปยังอีเมลสำรองโดยไม่ตรวจว่าบัญชีหลักมีอยู่หรือไม่ เพื่อไม่เปิดช่อง
    # account enumeration และไม่แจ้งว่าส่งสำเร็จเมื่อ SMTP ใช้งานไม่ได้
    otp = mfa_service.generate_otp()
    try:
        delivered = mfa_service.send_otp_email(
            alternate,
            otp,
            datetime.utcnow() + timedelta(seconds=_ALT_OTP_TTL),
        )
    except Exception as exc:
        log.exception("recovery alternate email OTP failed: %r", exc)
        delivered = False
    if not delivered:
        raise HTTPException(
            status_code=503,
            detail="ระบบอีเมลยังไม่พร้อมใช้งาน กรุณาลองใหม่หรือติดต่อผู้ดูแล",
        )

    redis_client.setex(
        _alt_key("alt-otp", email, alternate),
        _ALT_OTP_TTL,
        json.dumps({"hash": mfa_service.hash_otp(otp), "attempts": 0}),
    )
    return {"sent": True, "message": "ส่ง OTP ไปยังอีเมลสำรองแล้ว"}


@router.post("/auth/recovery/alternate-email/verify")
@limiter.limit("10/hour")
def alternate_email_verify(request: Request, body: AlternateEmailVerifyBody):
    email = body.email.strip().lower()
    alternate = body.alternate_email.strip().lower()
    key = _alt_key("alt-otp", email, alternate)
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=400, detail="OTP ไม่ถูกต้องหรือหมดอายุ")
    data = json.loads(raw)
    if data.get("attempts", 0) >= _ALT_MAX_ATTEMPTS:
        redis_client.delete(key)
        raise HTTPException(status_code=429, detail="กรอก OTP ผิดเกินกำหนด กรุณาขอใหม่")
    if not mfa_service.verify_otp(data["hash"], body.otp.strip()):
        data["attempts"] = data.get("attempts", 0) + 1
        ttl = redis_client.ttl(key)
        redis_client.setex(key, ttl if ttl and ttl > 0 else _ALT_OTP_TTL, json.dumps(data))
        raise HTTPException(status_code=400, detail="OTP ไม่ถูกต้องหรือหมดอายุ")
    redis_client.delete(key)
    token = secrets.token_urlsafe(32)
    redis_client.setex(
        f"recovery:alt:verified:{token}",
        _ALT_VERIFY_TTL,
        json.dumps({"email": email, "alternate_email": alternate}),
    )
    return {"verified": True, "verification_token": token}


@router.post("/auth/recovery/request")
@limiter.limit("5/hour")
def recovery_request(
    request: Request,
    body: RecoveryRequestBody,
    db: Session = Depends(get_db),
):
    if body.request_kind not in _ALLOWED_REQUEST_KINDS:
        raise HTTPException(status_code=422, detail="หัวข้อคำขอไม่ถูกต้อง")
    if body.evidence_type not in _ALLOWED_EVIDENCE:
        raise HTTPException(status_code=422, detail="เลือกบัตรนักศึกษาหรือบัตรประชาชน")
    evidence = _decode_evidence(body.evidence_image, body.evidence_mime)
    email = body.email.strip().lower()
    alternate = body.alternate_email.strip().lower() if body.alternate_email else None
    alternate_verified = False
    if alternate:
        if alternate == email:
            raise HTTPException(status_code=422, detail="อีเมลสำรองต้องไม่ซ้ำอีเมลบัญชี")
        alternate_verified = _consume_alternate_verification(
            body.alternate_verification_token, email, alternate
        )
        if not alternate_verified:
            raise HTTPException(status_code=400, detail="กรุณายืนยันอีเมลสำรองด้วย OTP")

    user = db.query(User).filter(func.lower(User.email) == email).first()
    tracking_secret = secrets.token_urlsafe(32)
    public_ticket_id = str(uuid.uuid4())
    if user is not None:
        ticket = RecoveryTicket(
            id=uuid.UUID(public_ticket_id),
            user_id=user.id,
            email=email,
            request_kind=body.request_kind,
            credential_type=body.credential_type,
            reason=body.reason,
            recovery_level="HIGH" if user.is_hub_admin else "NORMAL",
            status="pending",
            requested_ip=get_client_ip(request),
            tracking_secret_hash=hash_secret(tracking_secret),
            evidence_type=body.evidence_type,
            evidence_mime=body.evidence_mime,
            evidence_encrypted=encrypt_secret(base64.b64encode(evidence).decode()),
            alternate_email=alternate,
            alternate_email_verified=alternate_verified,
            delivery_status="pending",
        )
        db.add(ticket)
        log_action(
            db,
            actor_id=user.id,
            action="recovery_ticket_requested",
            target_type="user",
            target_id=user.id,
            ip=get_client_ip(request),
            metadata={
                "ticket_id": public_ticket_id,
                "request_kind": body.request_kind,
                "credential_type": body.credential_type,
                "evidence_type": body.evidence_type,
                "alternate_email_verified": alternate_verified,
            },
        )
        db.commit()
        try:
            send_alert(
                severity="warning",
                kind=(
                    "recovery.blocked_account_appeal_requested"
                    if body.request_kind == "blocked_account_appeal"
                    else "recovery.account_recovery_requested"
                ),
                key=public_ticket_id,
                title=(
                    f"ขอทบทวนการบล็อกบัญชี: {email}"
                    if body.request_kind == "blocked_account_appeal"
                    else f"คำขอกู้บัญชีใหม่: {email}"
                ),
                detail={
                    "email": email,
                    "request_kind": body.request_kind,
                    "user_status": user.status,
                    "recovery_level": ticket.recovery_level,
                    "reason": body.reason,
                    "review_url": f"{settings.admin_frontend_url}/recovery-tickets",
                },
            )
        except Exception as exc:
            log.warning("recovery request alert failed: %r", exc)
    return {
        "submitted": True,
        "ticket_id": public_ticket_id,
        "tracking_secret": tracking_secret,
        "message": "ส่งคำขอแล้ว คุณปิดหน้านี้และกลับมาตรวจสอบภายหลังได้",
    }


@router.post("/auth/recovery/status")
@limiter.limit("30/hour")
def recovery_status(request: Request, body: RecoveryStatusBody, db: Session = Depends(get_db)):
    try:
        ticket_uuid = uuid.UUID(body.ticket_id)
    except ValueError:
        return {"status": "pending", "message": "คำขอกำลังรอตรวจสอบ"}
    ticket = db.query(RecoveryTicket).filter(RecoveryTicket.id == ticket_uuid).first()
    if not ticket or not ticket.tracking_secret_hash:
        return {"status": "pending", "message": "คำขอกำลังรอตรวจสอบ"}
    if not verify_secret(ticket.tracking_secret_hash, body.tracking_secret):
        raise HTTPException(status_code=403, detail="Ticket ID หรือรหัสติดตามไม่ถูกต้อง")

    messages = {
        "pending": "คำขอกำลังรอผู้ดูแลตรวจสอบ",
        "approved": "คำขอได้รับการอนุมัติแล้ว",
        "rejected": "คำขอไม่ได้รับการอนุมัติ กรุณาติดต่อผู้ดูแล",
        "consumed": "คำขอนี้ถูกใช้กู้บัญชีเรียบร้อยแล้ว",
        "expired": "ลิงก์กู้บัญชีหมดอายุ กรุณาติดต่อผู้ดูแล",
    }
    result = {
        "status": ticket.status,
        "message": messages.get(ticket.status, "กำลังดำเนินการ"),
        "delivery": ticket.delivery_status,
    }
    if ticket.request_kind == "blocked_account_appeal" and ticket.status == "approved":
        result["message"] = "คำขอได้รับการอนุมัติแล้ว บัญชีสามารถเข้าสู่ระบบได้"
        return result
    if ticket.status == "approved":
        expires = ticket.token_expires_at
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if not expires or expires <= datetime.now(timezone.utc):
            ticket.status = "expired"
            db.commit()
            result.update(status="expired", message=messages["expired"])
        elif ticket.link_token:
            try:
                token = decrypt_secret(ticket.link_token)
                result["relink_url"] = (
                    f"{settings.hub_base_url}/auth/account/change-google/redirect?t={token}"
                )
                result["expires_at"] = expires.isoformat()
            except Exception:
                log.exception("cannot decrypt recovery token ticket=%s", ticket.id)
    return result


@router.get("/admin/recovery-tickets")
def list_recovery_tickets(
    status_filter: str = Query("pending", alias="status"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    query = db.query(RecoveryTicket)
    if status_filter:
        query = query.filter(RecoveryTicket.status == status_filter)
    rows = query.order_by(RecoveryTicket.created_at.desc()).limit(200).all()
    items = []
    for ticket in rows:
        approvals = (
            db.query(RecoveryTicketApproval)
            .filter(RecoveryTicketApproval.ticket_id == ticket.id)
            .all()
        )
        items.append(
            {
                "id": str(ticket.id),
                "email": ticket.email,
                "request_kind": ticket.request_kind,
                "user_status": (
                    db.query(User.status).filter(User.id == ticket.user_id).scalar()
                    if ticket.user_id
                    else None
                ),
                "credential_type": ticket.credential_type,
                "reason": ticket.reason,
                "evidence_type": ticket.evidence_type,
                "has_evidence": bool(ticket.evidence_encrypted),
                "alternate_email": ticket.alternate_email,
                "alternate_email_verified": ticket.alternate_email_verified,
                "delivery_status": ticket.delivery_status,
                "recovery_level": ticket.recovery_level,
                "status": ticket.status,
                "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
                "latest_approval_at": max(
                    (row.approved_at for row in approvals if row.approved_at),
                    default=None,
                ).isoformat()
                if approvals
                else None,
                "token_expires_at": ticket.token_expires_at.isoformat()
                if ticket.token_expires_at
                else None,
                "delivery_sent_at": ticket.delivery_sent_at.isoformat()
                if ticket.delivery_sent_at
                else None,
                "consumed_at": ticket.consumed_at.isoformat()
                if ticket.consumed_at
                else None,
                "approvals": len(approvals),
                "required": _REQUIRED.get(ticket.recovery_level, 1),
                "approvers": [str(row.admin_id) for row in approvals],
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/admin/recovery-tickets/{ticket_id}/evidence")
def get_recovery_evidence(
    ticket_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    ticket = db.query(RecoveryTicket).filter(RecoveryTicket.id == ticket_id).first()
    if not ticket or not ticket.evidence_encrypted or not ticket.evidence_mime:
        raise HTTPException(status_code=404, detail="ไม่พบหลักฐาน")
    try:
        payload = decrypt_secret(ticket.evidence_encrypted)
        evidence = base64.b64decode(payload, validate=True)
    except Exception:
        log.exception("cannot decrypt recovery evidence ticket=%s", ticket.id)
        raise HTTPException(status_code=500, detail="ไม่สามารถอ่านหลักฐานได้")
    log_action(
        db,
        actor_id=admin.id,
        action="recovery_evidence_viewed",
        target_type="user",
        target_id=ticket.user_id,
        ip=get_client_ip(request),
        metadata={"ticket_id": str(ticket.id)},
    )
    db.commit()
    extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(ticket.evidence_mime, "bin")
    return Response(
        content=evidence,
        media_type=ticket.evidence_mime,
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": f'inline; filename="recovery-evidence-{ticket.id}.{extension}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/admin/recovery-tickets/{ticket_id}/approve",
    dependencies=[Depends(_stepup_gate("recovery_ticket_review"))],
)
def approve_recovery_ticket(
    ticket_id: str,
    body: ApproveBody,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    ticket = db.query(RecoveryTicket).filter(RecoveryTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="ไม่พบคำขอ")
    if ticket.status != "pending":
        raise HTTPException(status_code=409, detail=f"คำขอสถานะ {ticket.status} แล้ว")
    if not ticket.evidence_encrypted:
        raise HTTPException(status_code=409, detail="คำขอนี้ไม่มีหลักฐานสำหรับตรวจสอบ")
    duplicate = (
        db.query(RecoveryTicketApproval)
        .filter(
            RecoveryTicketApproval.ticket_id == ticket.id,
            RecoveryTicketApproval.admin_id == admin.id,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="คุณอนุมัติคำขอนี้ไปแล้ว ต้องใช้ admin คนอื่น")

    db.add(
        RecoveryTicketApproval(
            ticket_id=ticket.id,
            admin_id=admin.id,
            evidence_type=body.evidence_type or ticket.evidence_type,
            evidence_note=body.evidence_note,
            remark=body.remark,
        )
    )
    db.flush()
    approvals = (
        db.query(func.count(RecoveryTicketApproval.id))
        .filter(RecoveryTicketApproval.ticket_id == ticket.id)
        .scalar()
    )
    required = _REQUIRED.get(ticket.recovery_level, 1)
    log_action(
        db,
        actor_id=admin.id,
        action="recovery_ticket_approved",
        target_type="user",
        target_id=ticket.user_id,
        ip=get_client_ip(request),
        metadata={
            "ticket_id": str(ticket.id),
            "evidence_type": body.evidence_type or ticket.evidence_type,
            "approvals": approvals,
            "required": required,
            "level": ticket.recovery_level,
        },
    )
    if approvals < required:
        db.commit()
        return {
            "awaiting_second_approval": True,
            "approvals": approvals,
            "required": required,
        }

    if ticket.request_kind == "blocked_account_appeal":
        appealed_user = db.query(User).filter(User.id == ticket.user_id).first()
        if not appealed_user:
            raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้")
        if appealed_user.status == "deleted":
            raise HTTPException(
                status_code=409,
                detail="บัญชีถูกลบ ไม่สามารถเปิดใช้งานผ่านคำขอทบทวนได้",
            )
        previous_status = appealed_user.status
        appealed_user.status = "active"
        ticket.status = "approved"
        ticket.delivery_status = "status_page"
        ticket.evidence_encrypted = None
        log_action(
            db,
            actor_id=admin.id,
            action="blocked_account_appeal_approved",
            target_type="user",
            target_id=appealed_user.id,
            ip=get_client_ip(request),
            metadata={
                "ticket_id": str(ticket.id),
                "previous_status": previous_status,
                "new_status": "active",
            },
        )
        db.commit()
        try:
            send_alert(
                severity="warning",
                kind="recovery.blocked_account_appeal_approved",
                key=str(ticket.id),
                title=f"อนุมัติเปิดใช้งานบัญชี: {ticket.email}",
                detail={
                    "email": ticket.email,
                    "previous_status": previous_status,
                    "new_status": "active",
                    "approved_by": admin.email,
                    "approvals": approvals,
                },
            )
        except Exception as exc:
            log.warning("blocked appeal approval alert failed: %r", exc)
        return {
            "approved": True,
            "account_unblocked": True,
            "approvals": approvals,
            "delivery": ticket.delivery_status,
            "email_sent": False,
        }

    token, relink_url = _mint_change_token(
        str(ticket.user_id),
        source="RECOVERY",
        ttl=_LINK_TTL,
        ip=get_client_ip(request),
        ticket_id=str(ticket.id),
    )
    ticket.status = "approved"
    ticket.link_token = encrypt_secret(token)
    ticket.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=_LINK_TTL)
    ticket.delivery_status = "status_page"
    email_sent = False
    if ticket.alternate_email and ticket.alternate_email_verified:
        email_sent = send_recovery_link_email(
            ticket.alternate_email, relink_url, ticket.token_expires_at
        )
        if email_sent:
            ticket.delivery_status = "alternate_email"
            ticket.delivery_sent_at = datetime.now(timezone.utc)
    db.commit()
    try:
        send_alert(
            severity="warning",
            kind="recovery.account_recovery_approved",
            key=str(ticket.id),
            title=f"อนุมัติคำขอกู้บัญชี: {ticket.email}",
            detail={
                "email": ticket.email,
                "delivery": ticket.delivery_status,
                "approved_by": admin.email,
                "approvals": approvals,
                "link_expires_at": ticket.token_expires_at.isoformat(),
            },
        )
    except Exception as exc:
        log.warning("recovery approval alert failed: %r", exc)
    return {
        "approved": True,
        "relink_url": relink_url,
        "approvals": approvals,
        "delivery": ticket.delivery_status,
        "email_sent": email_sent,
    }


@router.post(
    "/admin/recovery-tickets/{ticket_id}/reject",
    dependencies=[Depends(_stepup_gate("recovery_ticket_review"))],
)
def reject_recovery_ticket(
    ticket_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    ticket = db.query(RecoveryTicket).filter(RecoveryTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="ไม่พบคำขอ")
    if ticket.status != "pending":
        raise HTTPException(status_code=409, detail=f"คำขอสถานะ {ticket.status} แล้ว")
    ticket.status = "rejected"
    ticket.evidence_encrypted = None
    log_action(
        db,
        actor_id=admin.id,
        action="recovery_ticket_rejected",
        target_type="user",
        target_id=ticket.user_id,
        ip=get_client_ip(request),
        metadata={"ticket_id": str(ticket.id)},
    )
    db.commit()
    try:
        send_alert(
            severity="warning",
            kind=(
                "recovery.blocked_account_appeal_rejected"
                if ticket.request_kind == "blocked_account_appeal"
                else "recovery.account_recovery_rejected"
            ),
            key=str(ticket.id),
            title=f"ปฏิเสธคำขอ: {ticket.email}",
            detail={
                "email": ticket.email,
                "request_kind": ticket.request_kind,
                "rejected_by": admin.email,
            },
        )
    except Exception as exc:
        log.warning("recovery rejection alert failed: %r", exc)
    return {"rejected": True}


def _ticket_page_html(nonce: str) -> str:
    page = """<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ศูนย์ช่วยเหลือบัญชี · Central Auth Hub</title>
  <style nonce="__NONCE__">
    :root{--navy:#081321;--panel:#101f31;--ink:#132033;--muted:#697a91;--line:#dce4ee;--bg:#f2f6fa;--mint:#10ad91;--mint-dark:#087765;--soft:#eaf9f6;--danger:#c73d55}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Sarabun,"Noto Sans Thai",system-ui,sans-serif}
    button,input,select,textarea{font:inherit}.shell{min-height:100vh;display:grid;grid-template-columns:minmax(280px,380px) minmax(0,1fr)}
    .side{background:linear-gradient(160deg,var(--navy),#0c2530);color:#fff;padding:42px;display:flex;flex-direction:column;justify-content:space-between}
    .brand{display:flex;gap:12px;align-items:center}.brand-mark{width:42px;height:42px;border:1px solid #2dd4bf;display:grid;place-items:center;color:#58e5d1;font:700 18px ui-monospace}
    .brand b{display:block;font-size:17px}.brand small{color:#8fa7bd;letter-spacing:.16em;font:10px ui-monospace}
    .side-copy{max-width:300px}.eyebrow{color:#52dbc7;letter-spacing:.15em;font:11px ui-monospace;text-transform:uppercase}
    .side h1{font-size:36px;line-height:1.18;margin:13px 0}.side p{color:#b9c8d6;line-height:1.7;font-size:14px}
    .steps{display:grid;gap:18px;margin-top:30px}.step{display:grid;grid-template-columns:34px 1fr;gap:12px;align-items:start}.step i{width:34px;height:34px;border:1px solid #355064;display:grid;place-items:center;font:12px ui-monospace;font-style:normal;color:#74e5d2}.step b{font-size:14px}.step span{display:block;color:#8399ad;font-size:12px;margin-top:3px}
    .privacy{padding-top:22px;border-top:1px solid #284052;color:#8fa7bd;font-size:11px;line-height:1.65}
    .main{padding:38px clamp(20px,5vw,76px);overflow:auto}.main-inner{max-width:900px;margin:auto}
    .topline{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}.topline h2{font-size:25px;margin:5px 0 0}.secure{border:1px solid #9eddd2;color:var(--mint-dark);padding:8px 11px;font:11px ui-monospace;letter-spacing:.08em;background:#f7fffd}
    .tabs{display:flex;border-bottom:1px solid var(--line);margin-bottom:18px}.tab{border:0;background:transparent;padding:12px 4px;margin-right:26px;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;font-weight:700}.tab.on{color:var(--ink);border-color:var(--mint)}
    .card{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 12px 34px rgba(15,23,42,.06);overflow:hidden}.card-head{padding:21px 24px;border-bottom:1px solid var(--line)}.card-head h3{margin:0;font-size:18px}.card-head p{margin:6px 0 0;color:var(--muted);font-size:13px}
    .body{padding:24px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.full{grid-column:1/-1}
    label{display:block;font-size:12px;font-weight:800;margin-bottom:7px}.required{color:var(--danger)}
    input,select,textarea{width:100%;border:1px solid #cfd9e5;border-radius:9px;padding:12px 13px;color:var(--ink);background:#fff;outline:none;transition:.15s}
    input:focus,select:focus,textarea:focus{border-color:var(--mint);box-shadow:0 0 0 3px rgba(16,173,145,.12)}textarea{resize:vertical;min-height:88px}
    .upload{border:1px dashed #aab9ca;border-radius:11px;padding:14px;background:#f9fbfd}.preview{display:none;align-items:center;gap:12px;margin-top:12px}.preview.show{display:flex}.preview img{width:68px;height:52px;object-fit:cover;border-radius:7px;border:1px solid var(--line)}.preview span{font-size:12px;color:var(--muted);word-break:break-all}
    .email-row{display:grid;grid-template-columns:1fr auto;gap:9px}.otp-box{display:none;grid-template-columns:1fr auto;gap:9px;margin-top:10px}.otp-box.show{display:grid}.verified{color:var(--mint-dark);font-size:12px;font-weight:700;margin-top:8px;display:none}.verified.show{display:block}
    .hint{font-size:11px;color:var(--muted);margin-top:7px}.actions{display:flex;justify-content:flex-end;gap:10px;padding-top:5px}
    button,.button{border:1px solid transparent;border-radius:9px;padding:11px 16px;font-weight:800;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:7px}
    .primary{background:var(--navy);color:#fff}.primary:hover{background:#132b43}.secondary{background:var(--soft);color:var(--mint-dark);border-color:#b9e8df}.ghost{background:#fff;color:var(--ink);border-color:var(--line)}button:disabled{opacity:.52;cursor:not-allowed}
    .notice{display:none;padding:12px 14px;border-radius:9px;margin-bottom:17px;font-size:13px}.notice.show{display:block}.notice.ok{background:#e8faf5;color:#087462;border:1px solid #b9eadf}.notice.err{background:#fff1f2;color:#ad1f3b;border:1px solid #fecdd3}
    .receipt{display:none}.receipt.show{display:block}.success-mark{width:50px;height:50px;border-radius:50%;display:grid;place-items:center;background:var(--soft);color:var(--mint-dark);font-size:24px;margin-bottom:13px}
    .secure-receipt{display:flex;align-items:center;gap:15px;border:1px solid #b8e5dd;border-radius:12px;padding:17px;margin-top:16px;background:linear-gradient(135deg,#f5fffd,#edf9f7)}.secret-icon{width:52px;height:52px;flex:0 0 auto;border-radius:12px;display:grid;place-items:center;background:var(--navy);color:#59dbc6;font:800 16px ui-monospace;letter-spacing:.14em}.secure-receipt b{display:block;font-size:14px}.secure-receipt span{display:block;color:var(--muted);font-size:12px;line-height:1.55;margin-top:4px}
    .warning{margin-top:15px;padding:12px 14px;background:#fff8e7;border:1px solid #f3d891;border-radius:9px;color:#7a5610;font-size:12px;line-height:1.55}
    .status-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.status-actions{display:flex;justify-content:flex-end;margin-top:17px}.continue{display:none;margin-top:12px}.continue.show{display:inline-flex}
    .hidden{display:none!important}
    @media(max-width:800px){.shell{grid-template-columns:1fr}.side{padding:25px}.side-copy{max-width:none}.side h1{font-size:27px}.steps{grid-template-columns:repeat(3,1fr)}.step{grid-template-columns:28px 1fr}.step i{width:28px;height:28px}.privacy{display:none}.main{padding:24px 16px}}
    @media(max-width:600px){.grid,.status-grid{grid-template-columns:1fr}.full{grid-column:auto}.steps{grid-template-columns:1fr}.topline{align-items:flex-start}.secure{font-size:9px}.body{padding:18px}.email-row,.otp-box{grid-template-columns:1fr}.actions{flex-direction:column}.actions button{width:100%}}
  </style>
</head>
<body>
<div class="shell">
  <aside class="side">
    <div class="brand"><div class="brand-mark">H</div><div><b>Central Auth Hub</b><small>IDENTITY CONTROL</small></div></div>
    <div class="side-copy">
      <div class="eyebrow">Account help center</div>
      <h1>ขอความช่วยเหลือบัญชี</h1>
      <p>ใช้หน้าเดียวสำหรับกู้บัญชีหรือขอทบทวนการบล็อก พร้อมติดตามผลได้โดยไม่ต้องเปิดหน้านี้ค้างไว้</p>
      <div class="steps">
        <div class="step"><i>01</i><div><b>ส่งหลักฐาน</b><span>บัตรนักศึกษาหรือบัตรประชาชน</span></div></div>
        <div class="step"><i>02</i><div><b>รอผู้ดูแลตรวจสอบ</b><span>บัญชีความเสี่ยงสูงต้องอนุมัติ 2 คน</span></div></div>
        <div class="step"><i>03</i><div><b>รับผลการตรวจสอบ</b><span>กู้บัญชีหรือเปิดใช้งานบัญชีตามหัวข้อ</span></div></div>
      </div>
    </div>
    <div class="privacy">หลักฐานถูกเข้ารหัสและลบออกหลังการกู้บัญชีสำเร็จหรือคำขอถูกปฏิเสธ</div>
  </aside>

  <main class="main"><div class="main-inner">
    <div class="topline"><div><div class="eyebrow">Account help center</div><h2>ส่งคำขอช่วยเหลือบัญชี</h2></div><div class="secure">● SECURE SESSION</div></div>
    <div class="tabs"><button class="tab on" data-pane="requestPane">ส่งคำขอใหม่</button><button class="tab" data-pane="statusPane">ตรวจสอบสถานะ</button></div>
    <div id="globalMsg" class="notice"></div>

    <section id="requestPane" class="card pane">
      <div class="card-head"><h3>ข้อมูลสำหรับตรวจสอบตัวตน</h3><p>ช่องที่มีเครื่องหมาย * จำเป็นต้องกรอก</p></div>
      <div class="body">
        <div id="requestForm" class="grid">
          <div class="full"><label>หัวข้อคำขอ <span class="required">*</span></label><select id="requestKind"><option value="account_recovery">กู้บัญชี / เข้าใช้งานไม่ได้</option><option value="blocked_account_appeal">ขอทบทวนการบล็อกบัญชี</option></select><div id="topicHint" class="hint">สำหรับผู้ที่ไม่มี Passkey หรือ Authenticator ที่ใช้งานได้</div></div>
          <div><label>อีเมลบัญชี <span class="required">*</span></label><input id="email" type="email" autocomplete="username" placeholder="name@uni.ac.th"></div>
          <div id="credentialField"><label>ช่องทางที่เข้าไม่ได้ <span class="required">*</span></label><select id="credential"><option value="PASSKEY">Passkey</option><option value="TOTP">Authenticator</option><option value="BOTH">ทั้ง Passkey และ Authenticator</option></select></div>
          <div><label>ประเภทหลักฐาน <span class="required">*</span></label><select id="evidenceType"><option value="student_card">บัตรนักศึกษา/บุคลากร</option><option value="citizen_id">บัตรประชาชน</option></select></div>
          <div><label>รูปหลักฐาน <span class="required">*</span></label><div class="upload"><input id="evidence" type="file" accept="image/jpeg,image/png,image/webp"><div id="preview" class="preview"><img id="previewImage" alt="ตัวอย่างหลักฐาน"><span id="previewName"></span></div><div class="hint">JPG, PNG หรือ WEBP ขนาดไม่เกิน 4 MB</div></div></div>
          <div class="full"><label>รายละเอียดคำขอ <span class="required">*</span></label><textarea id="reason" placeholder="อธิบายปัญหาและเหตุการณ์ที่เกิดขึ้นให้ผู้ดูแลตรวจสอบ"></textarea></div>
          <div class="full"><label>อีเมลสำรองสำหรับรับลิงก์ (ไม่บังคับ)</label><div class="email-row"><input id="alternate" type="email" placeholder="alternate@email.com"><button id="sendOtp" class="secondary" type="button">ส่ง OTP</button></div><div class="hint">หากไม่ระบุ คุณสามารถรับลิงก์จากหน้าตรวจสอบสถานะด้วย Ticket ID</div><div id="otpBox" class="otp-box"><input id="otp" inputmode="numeric" maxlength="6" placeholder="กรอก OTP 6 หลัก"><button id="verifyOtp" class="secondary" type="button">ยืนยัน OTP</button></div><div id="verified" class="verified">✓ ยืนยันอีเมลสำรองแล้ว</div></div>
          <div class="full actions"><button id="submit" class="primary" type="button">ส่งคำขอให้ผู้ดูแล</button></div>
        </div>

        <div id="receipt" class="receipt">
          <div class="success-mark">✓</div><h3>ส่งคำขอเรียบร้อย</h3><p>ระบบซ่อน Ticket ID และรหัสติดตามไว้เพื่อความปลอดภัย กดคัดลอกหนึ่งครั้งแล้วเก็บไว้ในที่ปลอดภัย</p>
          <div class="secure-receipt"><div class="secret-icon">••••</div><div><b>ข้อมูลติดตามคำขอพร้อมคัดลอก</b><span>ประกอบด้วย Ticket ID และ Tracking secret โดยจะไม่แสดงบนหน้าจอ</span></div></div>
          <div class="warning">ข้อมูลนี้คัดลอกได้เฉพาะระหว่างที่หน้านี้ยังเปิดอยู่ ระบบไม่สามารถแสดงรหัสเดิมให้ภายหลังได้</div>
          <div class="actions"><button id="copyReceipt" class="secondary" type="button">คัดลอกข้อมูลติดตาม</button><button id="goStatus" class="primary" type="button">ตรวจสอบสถานะ</button></div>
        </div>
      </div>
    </section>

    <section id="statusPane" class="card pane hidden">
      <div class="card-head"><h3>ติดตามคำขอ</h3><p>กรอก Ticket ID และรหัสติดตามที่ได้รับตอนส่งคำขอ</p></div>
      <div class="body"><div><label>ข้อมูลติดตามคำขอ</label><textarea id="trackingBundle" autocomplete="off" spellcheck="false" placeholder="วางข้อมูลที่คัดลอกไว้ทั้งชุดที่นี่"></textarea><div class="hint">ข้อมูลประกอบด้วย Ticket ID และ Tracking secret ระบบจะแยกค่าให้อัตโนมัติ</div></div><div class="status-actions"><button id="check" class="primary" type="button">ตรวจสอบสถานะ</button></div><div id="statusMsg" class="notice"></div><a id="continueLink" class="button primary continue">ดำเนินการกู้บัญชี</a></div>
    </section>
  </div></main>
</div>

<script nonce="__NONCE__">
const $=id=>document.getElementById(id);
let verificationToken="", previewUrl="", otpCooldown=null, receiptTicket="", receiptSecret="";
function note(id,text,ok){const e=$(id);e.textContent=text;e.className="notice show "+(ok?"ok":"err");e.scrollIntoView({behavior:"smooth",block:"nearest"})}
async function post(url,body){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:"ดำเนินการไม่สำเร็จ");return d}
function showPane(id){document.querySelectorAll(".pane").forEach(x=>x.classList.toggle("hidden",x.id!==id));document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x.dataset.pane===id))}
document.querySelectorAll(".tab").forEach(x=>x.addEventListener("click",()=>showPane(x.dataset.pane)));
function syncTopic(){const blocked=$("requestKind").value==="blocked_account_appeal";$("credentialField").classList.toggle("hidden",blocked);$("topicHint").textContent=blocked?"สำหรับบัญชีที่ถูกระงับหรือถูกระบบปฏิเสธการเข้าใช้งาน ผู้ดูแลจะตรวจหลักฐานก่อนเปิดใช้งาน":"สำหรับผู้ที่ไม่มี Passkey หรือ Authenticator ที่ใช้งานได้";$("reason").placeholder=blocked?"อธิบายเหตุผลที่คิดว่าบัญชีถูกบล็อกโดยผิดพลาด และเหตุการณ์ล่าสุด":"อธิบายว่าอุปกรณ์หรือช่องทางใดสูญหาย และเกิดขึ้นเมื่อใด"}
$("requestKind").addEventListener("change",syncTopic);const initialTopic=new URLSearchParams(location.search).get("topic");if(initialTopic==="blocked_account")$("requestKind").value="blocked_account_appeal";syncTopic();
async function copyText(value,button){try{if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(value);else{const t=document.createElement("textarea");t.value=value;t.style.position="fixed";t.style.opacity="0";document.body.appendChild(t);t.select();if(!document.execCommand("copy"))throw new Error();t.remove()}const old=button.textContent;button.textContent="คัดลอกแล้ว";setTimeout(()=>button.textContent=old,1600)}catch{note("globalMsg","คัดลอกอัตโนมัติไม่ได้ กรุณาเลือกข้อความแล้วคัดลอกด้วยตนเอง",false)}}
$("evidence").addEventListener("change",()=>{const f=$("evidence").files[0];if(previewUrl)URL.revokeObjectURL(previewUrl);if(!f){$("preview").classList.remove("show");return}previewUrl=URL.createObjectURL(f);$("previewImage").src=previewUrl;$("previewName").textContent=f.name+" · "+Math.ceil(f.size/1024)+" KB";$("preview").classList.add("show")});
$("alternate").addEventListener("input",()=>{verificationToken="";$("verified").classList.remove("show")});
$("sendOtp").addEventListener("click",async()=>{const b=$("sendOtp");try{b.disabled=true;b.textContent="กำลังส่ง…";const d=await post("/auth/recovery/alternate-email/start",{email:$("email").value.trim(),alternate_email:$("alternate").value.trim()});$("otpBox").classList.add("show");note("globalMsg",d.message||"ส่ง OTP แล้ว",true);let left=30;clearInterval(otpCooldown);otpCooldown=setInterval(()=>{left--;b.textContent=left>0?"ส่งใหม่ใน "+left+" วินาที":"ส่ง OTP อีกครั้ง";if(left<=0){clearInterval(otpCooldown);b.disabled=false}},1000)}catch(e){b.disabled=false;b.textContent="ส่ง OTP";note("globalMsg",e.message,false)}});
$("verifyOtp").addEventListener("click",async()=>{const b=$("verifyOtp");try{b.disabled=true;b.textContent="กำลังตรวจ…";const d=await post("/auth/recovery/alternate-email/verify",{email:$("email").value.trim(),alternate_email:$("alternate").value.trim(),otp:$("otp").value.trim()});verificationToken=d.verification_token;$("verified").classList.add("show");$("alternate").readOnly=true;$("otpBox").classList.remove("show");note("globalMsg","ยืนยันอีเมลสำรองเรียบร้อย",true)}catch(e){note("globalMsg",e.message,false)}finally{b.disabled=false;b.textContent="ยืนยัน OTP"}});
function readFile(f){return new Promise((ok,bad)=>{const r=new FileReader();r.onload=()=>ok(r.result);r.onerror=bad;r.readAsDataURL(f)})}
$("submit").addEventListener("click",async()=>{const f=$("evidence").files[0],b=$("submit");if(!$("email").value.trim())return note("globalMsg","กรุณากรอกอีเมลบัญชี",false);if(!f)return note("globalMsg","กรุณาแนบรูปหลักฐาน",false);if(f.size>4*1024*1024)return note("globalMsg","รูปหลักฐานต้องไม่เกิน 4 MB",false);if(!$("reason").value.trim())return note("globalMsg","กรุณาระบุเหตุผล",false);if($("alternate").value.trim()&&!verificationToken)return note("globalMsg","กรุณายืนยันอีเมลสำรองด้วย OTP ก่อน",false);try{b.disabled=true;b.textContent="กำลังส่งคำขอ…";const d=await post("/auth/recovery/request",{email:$("email").value.trim(),request_kind:$("requestKind").value,credential_type:$("requestKind").value==="account_recovery"?$("credential").value:null,reason:$("reason").value.trim(),evidence_type:$("evidenceType").value,evidence_mime:f.type,evidence_image:await readFile(f),alternate_email:$("alternate").value.trim()||null,alternate_verification_token:verificationToken||null});receiptTicket=d.ticket_id;receiptSecret=d.tracking_secret;$("requestForm").classList.add("hidden");$("receipt").classList.add("show");note("globalMsg",d.message,true)}catch(e){note("globalMsg",e.message,false);b.disabled=false;b.textContent="ส่งคำขอให้ผู้ดูแล"}});
$("copyReceipt").addEventListener("click",()=>copyText("Ticket ID: "+receiptTicket+String.fromCharCode(10)+"Tracking secret: "+receiptSecret,$("copyReceipt")));
$("goStatus").addEventListener("click",()=>showPane("statusPane"));
$("check").addEventListener("click",async()=>{const b=$("check"),lines=$("trackingBundle").value.split(String.fromCharCode(10)).map(x=>x.trim()).filter(Boolean),ticket=(lines.find(x=>x.toLowerCase().startsWith("ticket id:"))||"").split(":").slice(1).join(":").trim(),secret=(lines.find(x=>x.toLowerCase().startsWith("tracking secret:"))||"").split(":").slice(1).join(":").trim();if(!ticket||!secret)return note("statusMsg","กรุณาวางข้อมูลติดตามทั้งชุดที่คัดลอกไว้",false);try{b.disabled=true;b.textContent="กำลังตรวจ…";const d=await post("/auth/recovery/status",{ticket_id:ticket,tracking_secret:secret});note("statusMsg",d.message,true);const a=$("continueLink");if(d.relink_url){a.href=d.relink_url;a.classList.add("show")}else a.classList.remove("show")}catch(e){note("statusMsg",e.message,false)}finally{b.disabled=false;b.textContent="ตรวจสอบสถานะ"}});
</script>
</body>
</html>"""
    return page.replace("__NONCE__", nonce)
