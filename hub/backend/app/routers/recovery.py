"""Recovery Ticket with evidence, verified alternate email, and resumable status."""

import base64
import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import RecoveryTicket, RecoveryTicketApproval, User
from app.rate_limiter import limiter
from app.redis_client import redis_client
from app.routers.account_link import _mint_change_token
from app.services import mfa_service
from app.services.audit_service import log_action
from app.services.critical_action_policy import gate as _stepup_gate
from app.services.email_service import send_recovery_link_email
from app.services.secret_service import decrypt_secret, encrypt_secret, hash_secret, verify_secret

log = logging.getLogger(__name__)
router = APIRouter()

_LINK_TTL = 1800
_ALT_OTP_TTL = 600
_ALT_VERIFY_TTL = 900
_ALT_MAX_ATTEMPTS = 5
_MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
_REQUIRED = {"NORMAL": 1, "HIGH": 2}
_ALLOWED_EVIDENCE = {"student_card", "citizen_id"}
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


class AlternateEmailBody(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    alternate_email: EmailStr = Field(..., max_length=255)


class AlternateEmailVerifyBody(AlternateEmailBody):
    otp: str = Field(..., min_length=6, max_length=8)


class RecoveryRequestBody(BaseModel):
    email: EmailStr = Field(..., max_length=255)
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
def alternate_email_start(
    request: Request,
    body: AlternateEmailBody,
    db: Session = Depends(get_db),
):
    email = body.email.strip().lower()
    alternate = body.alternate_email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is not None and alternate != email:
        otp = mfa_service.generate_otp()
        redis_client.setex(
            _alt_key("alt-otp", email, alternate),
            _ALT_OTP_TTL,
            json.dumps({"hash": mfa_service.hash_otp(otp), "attempts": 0}),
        )
        try:
            mfa_service.send_otp_email(
                alternate,
                otp,
                datetime.utcnow() + timedelta(seconds=_ALT_OTP_TTL),
            )
        except Exception as exc:
            log.warning("recovery alternate email OTP failed: %r", exc)
    return {"sent": True, "message": "หากข้อมูลถูกต้อง ระบบได้ส่ง OTP แล้ว"}


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
                "credential_type": body.credential_type,
                "evidence_type": body.evidence_type,
                "alternate_email_verified": alternate_verified,
            },
        )
        db.commit()
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
                from app.config import settings

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
    except Exception:
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
    return {"mime": ticket.evidence_mime, "data_url": f"data:{ticket.evidence_mime};base64,{payload}"}


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
    return {"rejected": True}


def _ticket_page_html(nonce: str) -> str:
    return f"""<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>คำขอกู้บัญชี · Central Auth Hub</title>
<style nonce="{nonce}">
:root{{--ink:#0f172a;--muted:#64748b;--line:#dbe3ee;--mint:#0f9f89;--navy:#081321;--bg:#f3f6fa}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);font-family:Sarabun,system-ui,sans-serif;color:var(--ink)}}
.top{{background:var(--navy);color:#fff;padding:22px 5vw;display:flex;justify-content:space-between}}.top span{{font:12px ui-monospace;color:#6ee7d2}}
.wrap{{max-width:920px;margin:36px auto;padding:0 18px}}.card{{background:#fff;border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:0 14px 40px #0f172a12}}
.head,.body{{padding:26px 30px}}.head{{border-bottom:1px solid var(--line)}}h1{{margin:0 0 7px;font-size:25px}}p{{color:var(--muted);line-height:1.65}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.full{{grid-column:1/-1}}label{{display:block;font-size:12px;font-weight:700;margin-bottom:7px}}
input,select,textarea{{width:100%;border:1px solid var(--line);border-radius:10px;padding:12px 13px;font:14px inherit}}textarea{{min-height:82px}}
.row{{display:flex;gap:10px;align-items:center}}.row input{{flex:1}}button,.btn{{border:0;border-radius:10px;padding:12px 17px;font-weight:700;cursor:pointer;text-decoration:none}}
.primary{{background:var(--navy);color:#fff}}.secondary{{background:#e7f8f4;color:#087462}}button:disabled{{opacity:.5}}
.notice{{padding:12px 14px;border-radius:10px;margin:15px 0;display:none;font-size:13px}}.notice.show{{display:block}}.ok{{background:#e8faf5;color:#087462}}.err{{background:#fff1f2;color:#be123c}}
.secret{{font:13px ui-monospace;word-break:break-all;background:#f8fafc;border:1px dashed #a7b3c4;padding:12px;border-radius:9px;margin:8px 0 14px}}
.divider{{height:1px;background:var(--line);margin:28px 0}}.status{{display:grid;grid-template-columns:1fr 1fr auto;gap:10px;align-items:end}}.hint{{font-size:11px;color:var(--muted);margin-top:6px}}
@media(max-width:700px){{.grid,.status{{grid-template-columns:1fr}}.full{{grid-column:auto}}.head,.body{{padding:21px}}}}
</style></head><body><header class="top"><b>Central Auth Hub</b><span>ACCOUNT RECOVERY</span></header>
<main class="wrap"><section class="card"><header class="head"><h1>ส่งคำขอกู้บัญชี</h1><p>แนบหลักฐานให้ผู้ดูแลตรวจสอบ อีเมลสำรองไม่บังคับ แต่ต้องยืนยัน OTP ก่อนใช้รับลิงก์</p></header>
<div class="body"><div id="msg" class="notice"></div><div class="grid" id="form">
<div><label>อีเมลบัญชีมหาวิทยาลัย</label><input id="email" type="email" autocomplete="username"></div>
<div><label>Credential ที่เข้าไม่ได้</label><select id="credential"><option value="PASSKEY">Passkey</option><option value="TOTP">Authenticator</option><option value="BOTH">ทั้งสองอย่าง</option></select></div>
<div><label>ประเภทหลักฐาน</label><select id="evidenceType"><option value="student_card">บัตรนักศึกษา/บุคลากร</option><option value="citizen_id">บัตรประชาชน</option></select></div>
<div><label>รูปหลักฐาน (ไม่เกิน 4 MB)</label><input id="evidence" type="file" accept="image/jpeg,image/png,image/webp"></div>
<div class="full"><label>เหตุผล</label><textarea id="reason" placeholder="อธิบายอุปกรณ์หรือช่องทางที่สูญหาย"></textarea></div>
<div class="full"><label>อีเมลสำรอง (ไม่บังคับ)</label><div class="row"><input id="alternate" type="email"><button id="sendOtp" class="secondary">ส่ง OTP</button></div><div class="hint">หากไม่กรอก ให้กลับมาตรวจสถานะด้วย Ticket ID และรหัสติดตาม</div></div>
<div class="full row" id="otpRow" style="display:none"><input id="otp" inputmode="numeric" maxlength="6" placeholder="OTP 6 หลัก"><button id="verifyOtp" class="secondary">ยืนยันอีเมล</button></div>
<div class="full"><button id="submit" class="primary">ส่งคำขอ</button></div></div>
<div id="receipt" style="display:none"><p><b>ส่งคำขอแล้ว</b> ปิดหน้านี้ได้ แต่โปรดเก็บข้อมูลทั้งสองรายการ</p><label>Ticket ID</label><div id="ticketOut" class="secret"></div><label>รหัสติดตาม</label><div id="secretOut" class="secret"></div><button id="copyReceipt" class="secondary">คัดลอกข้อมูล</button></div>
<div class="divider"></div><h2 style="font-size:18px">ตรวจสอบสถานะคำขอ</h2><p>กลับมาตรวจภายหลังได้ ไม่ต้องเปิดหน้านี้ค้าง</p>
<div class="status"><div><label>Ticket ID</label><input id="ticketId"></div><div><label>รหัสติดตาม</label><input id="trackingSecret"></div><button id="check" class="secondary">ตรวจสอบ</button></div>
<div id="statusMsg" class="notice"></div><a id="continueLink" class="btn primary" style="display:none;margin-top:12px">ดำเนินการกู้บัญชี</a>
</div></section></main><script nonce="{nonce}">
const $=id=>document.getElementById(id);let verificationToken='';
function note(id,text,ok){{const e=$(id);e.textContent=text;e.className='notice show '+(ok?'ok':'err')}}
async function post(url,body){{const r=await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});const d=await r.json().catch(()=>({{}}));if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:'ดำเนินการไม่สำเร็จ');return d}}
$('sendOtp').onclick=async()=>{{try{{await post('/auth/recovery/alternate-email/start',{{email:$('email').value,alternate_email:$('alternate').value}});$('otpRow').style.display='flex';note('msg','ส่ง OTP แล้ว กรุณาตรวจสอบอีเมลสำรอง',true)}}catch(e){{note('msg',e.message,false)}}}};
$('verifyOtp').onclick=async()=>{{try{{const d=await post('/auth/recovery/alternate-email/verify',{{email:$('email').value,alternate_email:$('alternate').value,otp:$('otp').value}});verificationToken=d.verification_token;note('msg','ยืนยันอีเมลสำรองเรียบร้อย',true)}}catch(e){{note('msg',e.message,false)}}}};
function readFile(f){{return new Promise((ok,bad)=>{{const r=new FileReader();r.onload=()=>ok(r.result);r.onerror=bad;r.readAsDataURL(f)}})}}
$('submit').onclick=async()=>{{const f=$('evidence').files[0];if(!f)return note('msg','กรุณาแนบรูปหลักฐาน',false);try{{$('submit').disabled=true;const d=await post('/auth/recovery/request',{{email:$('email').value,credential_type:$('credential').value,reason:$('reason').value,evidence_type:$('evidenceType').value,evidence_mime:f.type,evidence_image:await readFile(f),alternate_email:$('alternate').value||null,alternate_verification_token:verificationToken||null}});$('form').style.display='none';$('receipt').style.display='block';$('ticketOut').textContent=d.ticket_id;$('secretOut').textContent=d.tracking_secret;$('ticketId').value=d.ticket_id;$('trackingSecret').value=d.tracking_secret;note('msg',d.message,true)}}catch(e){{note('msg',e.message,false);$('submit').disabled=false}}}};
$('copyReceipt').onclick=()=>navigator.clipboard.writeText('Ticket ID: '+$('ticketOut').textContent+'\nรหัสติดตาม: '+$('secretOut').textContent);
$('check').onclick=async()=>{{try{{const d=await post('/auth/recovery/status',{{ticket_id:$('ticketId').value,tracking_secret:$('trackingSecret').value}});note('statusMsg',d.message,true);const a=$('continueLink');if(d.relink_url){{a.href=d.relink_url;a.style.display='inline-block'}}else a.style.display='none'}}catch(e){{note('statusMsg',e.message,false)}}}};
</script></body></html>"""
