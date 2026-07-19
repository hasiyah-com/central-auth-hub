"""Recovery Ticket — ทางสุดท้ายกู้บัญชี (ไม่มี email/passkey/TOTP เหลือ).

Flow: User → Recovery Request → Ticket(pending) → Admin Approve(×N ตาม level) →
One-time Link → user เชื่อม Gmail ใหม่เอง (reuse change_google flow).

Recovery Level: NORMAL = 1 approval · HIGH = 2 approvals จาก admin ต่างคน (four-eyes).
default level: target is_hub_admin → HIGH, อื่น → NORMAL.

Admin ยืนยันตัวตนนอกระบบ (บัตร นศ./บัตร ปชช.) ก่อน approve — บันทึก evidence ต่อครั้ง.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import RecoveryTicket, RecoveryTicketApproval, User
from app.rate_limiter import limiter
from app.routers.account_link import _mint_change_token
from app.services.audit_service import log_action
from app.services.critical_action_policy import gate as _stepup_gate

log = logging.getLogger(__name__)
router = APIRouter()

_LINK_TTL = 1800  # 30 นาที — เผื่อ admin ส่งต่อ user
_REQUIRED = {"NORMAL": 1, "HIGH": 2}


class RecoveryRequestBody(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    credential_type: str | None = Field(None, max_length=20)  # PASSKEY | TOTP
    reason: str | None = Field(None, max_length=1000)


class ApproveBody(BaseModel):
    evidence_type: str | None = Field(None, max_length=30)
    evidence_note: str | None = Field(None, max_length=1000)
    remark: str | None = Field(None, max_length=1000)


# ── User: ยื่นคำขอ (public, opaque) ──


@router.post("/auth/recovery/request", summary="ยื่นคำขอกู้บัญชี (admin ต้อง approve)")
@limiter.limit("5/hour")
def recovery_request(
    request: Request,
    body: RecoveryRequestBody,
    db: Session = Depends(get_db),
):
    email = body.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is not None:
        level = "HIGH" if user.is_hub_admin else "NORMAL"
        db.add(
            RecoveryTicket(
                user_id=user.id,
                email=email,
                credential_type=body.credential_type,
                reason=body.reason,
                recovery_level=level,
                status="pending",
                requested_ip=get_client_ip(request),
            )
        )
        log_action(
            db,
            actor_id=user.id,
            action="recovery_ticket_requested",
            target_type="user",
            target_id=user.id,
            ip=get_client_ip(request),
            metadata={"email": email[:120], "credential_type": body.credential_type},
        )
        db.commit()
    # opaque — ไม่บอกว่า email มีจริงไหม
    return {"submitted": True, "message": "ส่งคำขอแล้ว — ผู้ดูแลระบบจะติดต่อยืนยันตัวตน"}


# ── Admin: review + approve/reject ──


@router.get("/admin/recovery-tickets", summary="รายการคำขอกู้บัญชี (admin)")
def list_recovery_tickets(
    status_filter: str = Query("pending", alias="status"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    q = db.query(RecoveryTicket)
    if status_filter:
        q = q.filter(RecoveryTicket.status == status_filter)
    rows = q.order_by(RecoveryTicket.created_at.desc()).limit(200).all()
    out = []
    for t in rows:
        approvals = (
            db.query(RecoveryTicketApproval)
            .filter(RecoveryTicketApproval.ticket_id == t.id)
            .all()
        )
        out.append(
            {
                "id": str(t.id),
                "email": t.email,
                "credential_type": t.credential_type,
                "reason": t.reason,
                "recovery_level": t.recovery_level,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "approvals": len(approvals),
                "required": _REQUIRED.get(t.recovery_level, 1),
                "approvers": [str(a.admin_id) for a in approvals],
            }
        )
    return {"items": out, "total": len(out)}


@router.post(
    "/admin/recovery-tickets/{ticket_id}/approve",
    dependencies=[Depends(_stepup_gate("recovery_ticket_review"))],
    summary="อนุมัติคำขอ (four-eyes ถ้า HIGH) → ออก one-time link",
)
def approve_recovery_ticket(
    ticket_id: str,
    body: ApproveBody,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    t = db.query(RecoveryTicket).filter(RecoveryTicket.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="ไม่พบคำขอ")
    if t.status not in ("pending",):
        raise HTTPException(status_code=409, detail=f"คำขอสถานะ {t.status} แล้ว")

    # กัน admin คนเดิม approve ซ้ำ (four-eyes = ต้องต่างคน)
    dup = (
        db.query(RecoveryTicketApproval)
        .filter(
            RecoveryTicketApproval.ticket_id == t.id,
            RecoveryTicketApproval.admin_id == admin.id,
        )
        .first()
    )
    if dup:
        raise HTTPException(
            status_code=409, detail="คุณอนุมัติคำขอนี้ไปแล้ว — ต้องใช้ admin คนอื่น (four-eyes)"
        )

    db.add(
        RecoveryTicketApproval(
            ticket_id=t.id,
            admin_id=admin.id,
            evidence_type=body.evidence_type,
            evidence_note=body.evidence_note,
            remark=body.remark,
        )
    )
    db.flush()
    approvals = (
        db.query(func.count(RecoveryTicketApproval.id))
        .filter(RecoveryTicketApproval.ticket_id == t.id)
        .scalar()
    )
    required = _REQUIRED.get(t.recovery_level, 1)

    log_action(
        db,
        actor_id=admin.id,
        action="recovery_ticket_approved",
        target_type="user",
        target_id=t.user_id,
        ip=get_client_ip(request),
        metadata={
            "ticket_id": str(t.id),
            "evidence_type": body.evidence_type,
            "approvals": approvals,
            "required": required,
            "level": t.recovery_level,
        },
    )

    if approvals < required:
        db.commit()
        return {
            "awaiting_second_approval": True,
            "approvals": approvals,
            "required": required,
        }

    # ครบ → ออก one-time link (bypass cooldown), ผูก ticket_id เพื่อ consume ตอน callback
    _token, relink_url = _mint_change_token(
        str(t.user_id),
        source="RECOVERY",
        ttl=_LINK_TTL,
        ip=get_client_ip(request),
        ticket_id=str(t.id),
    )
    t.status = "approved"
    t.link_token = _token
    t.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=_LINK_TTL)
    db.commit()
    return {"approved": True, "relink_url": relink_url, "approvals": approvals}


@router.post(
    "/admin/recovery-tickets/{ticket_id}/reject",
    dependencies=[Depends(_stepup_gate("recovery_ticket_review"))],
    summary="ปฏิเสธคำขอ",
)
def reject_recovery_ticket(
    ticket_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    t = db.query(RecoveryTicket).filter(RecoveryTicket.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="ไม่พบคำขอ")
    if t.status != "pending":
        raise HTTPException(status_code=409, detail=f"คำขอสถานะ {t.status} แล้ว")
    t.status = "rejected"
    log_action(
        db,
        actor_id=admin.id,
        action="recovery_ticket_rejected",
        target_type="user",
        target_id=t.user_id,
        ip=get_client_ip(request),
        metadata={"ticket_id": str(t.id)},
    )
    db.commit()
    return {"rejected": True}
