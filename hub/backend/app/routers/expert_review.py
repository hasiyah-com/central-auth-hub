"""Expert Label Workflow — API ของผู้เชี่ยวชาญ (hub admin เท่านั้น).

  POST /admin/expert-review/groups/sync             ระบบสร้าง alert group จาก shadow decision
  GET  /admin/expert-review/queue/next              รายการถัดไปของผู้ตรวจคนนี้
  GET  /admin/expert-review/groups/{id}             รอบแรก — blind
  GET  /admin/expert-review/groups/{id}/unblinded   รอบสอง — ต้องมี label รอบแรกแล้ว และล็อก label รอบแรก
  POST /admin/expert-review/groups/{id}/reviews     ให้ label (append-only)
  GET  /admin/expert-review/metrics                 สถิติเชิงพรรณนา + readiness gate

**ไม่มี endpoint ใดเขียน system_dispositions หรือสถานะของ login** — label ของผู้ตรวจ
ไม่ย้อนกลับไปเปลี่ยนการตัดสินการเข้าถึง และไม่ถูกนำไป train อัตโนมัติ

ทุกครั้งที่เปิดดูรายการจะถูกบันทึก audit log (design §6)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import (
    ExpertAlertGroup,
    LoginSession,
    Subsystem,
    SystemDisposition,
    User,
)
from app.services.audit_service import log_action
from app.services.expert_review import metrics as MT
from app.services.expert_review import queue as Q
from app.services.expert_review import reviews as R
from app.services.expert_review import sync as SY
from app.services.expert_review import views as V
from app.services.expert_review.vocab import EPOCH_FIELDS

router = APIRouter()


class ReviewIn(BaseModel):
    # ตรวจค่าจริงใน reviews._validate — ที่เดียวกับที่ service ใช้
    round: int
    verdict: str
    confidence: str
    reason_codes: list[str]
    comment: str | None = None
    time_spent_sec: int | None = None
    supersedes_id: str | None = None


def _epoch() -> dict:
    return {k: getattr(settings, k, None) for k in EPOCH_FIELDS}


def _load_group(db: Session, group_id: uuid.UUID) -> ExpertAlertGroup:
    g = db.query(ExpertAlertGroup).filter(ExpertAlertGroup.id == group_id).first()
    if g is None:
        raise HTTPException(status_code=404, detail="ไม่พบ alert group")
    return g


def _context(db: Session, g: ExpertAlertGroup):
    ids = [uuid.UUID(s) for s in g.session_ids]
    events = db.query(LoginSession).filter(LoginSession.id.in_(ids)).all()
    history = []
    if g.user_id is not None:
        history = (
            db.query(LoginSession)
            .filter(
                LoginSession.user_id == g.user_id,
                LoginSession.created_at
                >= g.first_seen_at - timedelta(days=V.HISTORY_DAYS),
                LoginSession.created_at < g.first_seen_at,
            )
            .all()
        )
    sub_ids = {e.subsystem_id for e in (*events, *history) if e.subsystem_id}
    names = {}
    if sub_ids:
        names = {
            str(s.id): s.name
            for s in db.query(Subsystem).filter(Subsystem.id.in_(sub_ids))
        }
    return events, history, names


@router.post("/groups/sync")
def sync_groups(
    request: Request,
    since_hours: int = Query(168, ge=1, le=24 * 90),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    epoch = _epoch()
    out = SY.sync_alert_groups(
        db, now=now, since=now - timedelta(hours=since_hours), epoch=epoch
    )
    log_action(
        db,
        actor_id=admin.id,
        action="expert_review_sync_requested",
        target_type="expert_alert_group",
        ip=get_client_ip(request),
        metadata={**out, "since_hours": since_hours},
    )
    db.commit()
    return {**out, "epoch": epoch}


@router.get("/queue/next")
def queue_next(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    nxt = Q.next_for_reviewer(db, admin.id)
    if nxt is None:
        return {"group_id": None, "assignment": None}
    gid, kind = nxt
    return {"group_id": str(gid), "assignment": kind}


@router.get("/groups/{group_id}")
def get_group_blind(
    group_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    g = _load_group(db, group_id)
    events, history, names = _context(db, g)
    payload = V.blind_payload(g, events, history, names)
    log_action(
        db,
        actor_id=admin.id,
        action="expert_review_group_viewed",
        target_type="expert_alert_group",
        target_id=g.id,
        ip=get_client_ip(request),
        metadata={"round": 1},
    )
    db.commit()
    return payload


@router.get("/groups/{group_id}/unblinded")
def get_group_unblinded(
    group_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    g = _load_group(db, group_id)
    ip = get_client_ip(request)
    if not R.has_effective_round1(db, g.id, admin.id):
        log_action(
            db,
            actor_id=admin.id,
            action="expert_review_unblind_denied",
            target_type="expert_alert_group",
            target_id=g.id,
            ip=ip,
            metadata={"reason": "round1_label_required"},
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="ต้องบันทึก label รอบแรกก่อนจึงจะเปิดดูผลของโมเดลได้",
        )

    disp = (
        db.query(SystemDisposition).filter(SystemDisposition.group_id == g.id).first()
    )
    events, history, names = _context(db, g)
    payload = V.unblinded_payload(g, disp, events, history, names)
    # การเปิดดูครั้งนี้เป็นหลักฐานที่ล็อก label รอบแรกของผู้ตรวจคนนี้
    log_action(
        db,
        actor_id=admin.id,
        action=R.UNBLIND_ACTION,
        target_type="expert_alert_group",
        target_id=g.id,
        ip=ip,
        metadata={"round": 2},
    )
    db.commit()
    return payload


@router.post("/groups/{group_id}/reviews", status_code=201)
def post_review(
    group_id: uuid.UUID,
    body: ReviewIn,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    ip = get_client_ip(request)
    data = {
        "round": body.round,
        "verdict": body.verdict,
        "confidence": body.confidence,
        "reason_codes": body.reason_codes,
        "comment": body.comment,
        "time_spent_sec": body.time_spent_sec,
        "supersedes_id": body.supersedes_id,
    }
    try:
        row = R.submit_review(db, group_id=group_id, reviewer=admin, body=data, ip=ip)
    except R.ReviewError as e:
        db.rollback()
        if e.status == 403:
            log_action(
                db,
                actor_id=admin.id,
                action="expert_review_forbidden",
                target_type="expert_alert_group",
                target_id=group_id,
                ip=ip,
                metadata={"detail": e.detail},
            )
            db.commit()
        raise HTTPException(status_code=e.status, detail=e.detail) from None

    return {
        "id": str(row.id),
        "round": row.round,
        "model_output_visible": row.model_output_visible,
        "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/metrics")
def get_metrics(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    return MT.summarize(db)
