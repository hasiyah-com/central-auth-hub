"""label ของผู้ตรวจ — append-only.

การแก้ label คือการเพิ่มแถวใหม่ที่ชี้ `supersedes_id` กลับไปยังแถวเดิม · Postgres มี
trigger ปฏิเสธ UPDATE และ `supersedes_id` เป็น UNIQUE จึงเขียนทับหรือแตกกิ่งไม่ได้
แม้เรียก SQL ตรง

กติกา
  * รอบ 1 — `model_output_visible = false` เสมอ · ระบบกำหนด ผู้ตรวจส่งค่ามาเองไม่ได้
  * รอบ 2 — ต้องมี label รอบ 1 ของตัวเอง และต้องเปิดดูผลของโมเดลแล้ว
  * เมื่อผู้ตรวจเปิดดูผลของโมเดลในกลุ่มใด label รอบ 1 ของกลุ่มนั้นถูกล็อก
    (หลักฐานการเปิดดูคือ audit log ซึ่งเป็น append-only อยู่แล้ว)
  * แก้ได้เฉพาะ label ของตัวเอง ในรอบเดียวกัน และแถวนั้นยังไม่เคยถูกแก้

ไม่มีการเขียน system_dispositions หรือ login_sessions จากโมดูลนี้
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, ExpertAlertGroup, ExpertReview, User
from app.services.audit_service import log_action

from .vocab import (
    CONFIDENCE,
    MAX_COMMENT_CHARS,
    REASON_CODES,
    REVIEW_ROUNDS,
    VERDICTS,
)

UNBLIND_ACTION = "expert_review_unblinded"
MAX_TIME_SPENT_SEC = 86400


class ReviewError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def effective(rows) -> list:
    """แถวที่ยังไม่ถูกแถวอื่นแก้ทับ."""
    superseded = {r.supersedes_id for r in rows if r.supersedes_id}
    return [r for r in rows if r.id not in superseded]


def round1_by_reviewer(rows) -> list:
    """label รอบ 1 ที่มีผลของผู้ตรวจแต่ละคน เรียงตามเวลาที่คนนั้นส่งครั้งแรก."""
    r1 = [r for r in rows if r.round == 1]
    first_at: dict = {}
    for r in r1:
        prev = first_at.get(r.reviewer_id)
        first_at[r.reviewer_id] = (
            r.created_at if prev is None else min(prev, r.created_at)
        )
    eff = {r.reviewer_id: r for r in effective(r1)}
    return [eff[k] for k in sorted(eff, key=lambda k: (first_at[k], str(k)))]


def has_unblinded(db: Session, group_id, reviewer_id) -> bool:
    return (
        db.query(AuditLog.id)
        .filter(
            AuditLog.actor_id == reviewer_id,
            AuditLog.action == UNBLIND_ACTION,
            AuditLog.target_id == group_id,
        )
        .first()
        is not None
    )


def has_effective_round1(db: Session, group_id, reviewer_id) -> bool:
    rows = (
        db.query(ExpertReview)
        .filter(
            ExpertReview.group_id == group_id, ExpertReview.reviewer_id == reviewer_id
        )
        .all()
    )
    return any(r.round == 1 for r in effective(rows))


def _validate(body: dict) -> dict:
    rnd = body.get("round")
    if isinstance(rnd, bool) or rnd not in REVIEW_ROUNDS:
        raise ReviewError(422, "round ต้องเป็น 1 หรือ 2")
    if body.get("verdict") not in VERDICTS:
        raise ReviewError(422, f"verdict ต้องเป็นหนึ่งใน: {', '.join(sorted(VERDICTS))}")
    if body.get("confidence") not in CONFIDENCE:
        raise ReviewError(
            422, f"confidence ต้องเป็นหนึ่งใน: {', '.join(sorted(CONFIDENCE))}"
        )

    codes = body.get("reason_codes")
    if not isinstance(codes, list) or not codes:
        raise ReviewError(422, "ต้องระบุ reason_codes อย่างน้อย 1 รหัส")
    unknown = sorted({c for c in codes if c not in REASON_CODES}, key=str)
    if unknown:
        raise ReviewError(422, f"reason_codes นอกรายการที่ประกาศไว้: {unknown}")
    if len(set(codes)) != len(codes):
        raise ReviewError(422, "reason_codes ซ้ำกัน")

    comment = body.get("comment")
    if comment is not None and (
        not isinstance(comment, str) or len(comment) > MAX_COMMENT_CHARS
    ):
        raise ReviewError(422, f"comment ต้องเป็นข้อความไม่เกิน {MAX_COMMENT_CHARS} ตัวอักษร")

    spent = body.get("time_spent_sec")
    if spent is not None and (
        isinstance(spent, bool)
        or not isinstance(spent, int)
        or not 0 <= spent <= MAX_TIME_SPENT_SEC
    ):
        raise ReviewError(422, "time_spent_sec ไม่ถูกต้อง")

    sup = body.get("supersedes_id")
    if sup:
        try:
            sup = uuid.UUID(str(sup))
        except ValueError:
            raise ReviewError(422, "supersedes_id ไม่ใช่ UUID") from None
    else:
        sup = None

    return {
        "round": rnd,
        "verdict": body["verdict"],
        "confidence": body["confidence"],
        "reason_codes": list(codes),
        "comment": comment,
        "time_spent_sec": spent,
        "supersedes_id": sup,
    }


def submit_review(
    db: Session, *, group_id, reviewer: User, body: dict, ip: str | None
) -> ExpertReview:
    data = _validate(body)

    group = db.query(ExpertAlertGroup).filter(ExpertAlertGroup.id == group_id).first()
    if group is None:
        raise ReviewError(404, "ไม่พบ alert group")

    in_group = db.query(ExpertReview).filter(ExpertReview.group_id == group.id).all()
    mine = [r for r in in_group if r.reviewer_id == reviewer.id]
    mine_effective = effective(mine)
    rnd = data["round"]
    sup = data["supersedes_id"]

    if sup is not None:
        target = next((r for r in in_group if r.id == sup), None)
        if target is None:
            raise ReviewError(404, "ไม่พบ label ที่ต้องการแก้ในกลุ่มนี้")
        if target.reviewer_id != reviewer.id:
            raise ReviewError(403, "แก้ได้เฉพาะ label ของตัวเอง")
        if target.round != rnd:
            raise ReviewError(409, "แก้ข้ามรอบไม่ได้")
        if any(r.supersedes_id == target.id for r in in_group):
            raise ReviewError(409, "label นี้ถูกแก้ไปแล้ว — ให้แก้จากแถวล่าสุด")
        if rnd == 1 and has_unblinded(db, group.id, reviewer.id):
            raise ReviewError(409, "label รอบแรกถูกล็อกแล้ว เพราะเปิดดูผลของโมเดลแล้ว")
    elif any(r.round == rnd for r in mine_effective):
        raise ReviewError(409, "มี label รอบนี้อยู่แล้ว — ถ้าจะแก้ให้ส่ง supersedes_id")

    if rnd == 2:
        if not any(r.round == 1 for r in mine_effective):
            raise ReviewError(409, "ต้องบันทึก label รอบแรกก่อน")
        if not has_unblinded(db, group.id, reviewer.id):
            raise ReviewError(409, "ต้องเปิดดูผลของโมเดลก่อนให้ label รอบสอง")

    row = ExpertReview(
        group_id=group.id,
        reviewer_id=reviewer.id,
        round=rnd,
        model_output_visible=(rnd == 2),
        verdict=data["verdict"],
        confidence=data["confidence"],
        reason_codes=data["reason_codes"],
        comment=data["comment"],
        time_spent_sec=data["time_spent_sec"],
        supersedes_id=sup,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ReviewError(409, "label นี้ถูกแก้ไปแล้ว — ให้แก้จากแถวล่าสุด") from None

    log_action(
        db,
        actor_id=reviewer.id,
        action="expert_review_submitted",
        target_type="expert_alert_group",
        target_id=group.id,
        ip=ip,
        metadata={
            "review_id": str(row.id),
            "round": rnd,
            "supersedes_id": str(sup) if sup else None,
        },
    )
    db.commit()
    db.refresh(row)
    return row
