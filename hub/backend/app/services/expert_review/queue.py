"""จ่ายงานให้ผู้ตรวจ (design §5.1–5.2).

ลำดับความสำคัญ
  1. adjudication   ผู้ตรวจสองคนเห็นต่างข้ามกลุ่ม (ปกติ vs น่าสงสัย) — ต้องการคนที่สาม
  2. second_review  กลุ่มใน double-review pool ที่มีผู้ตรวจแล้ว 1 คน
  3. primary        กลุ่มที่ยังไม่มีใครตรวจ

ผู้ตรวจไม่ได้รับกลุ่มที่ตัวเองตรวจไปแล้ว และคิวไม่เปิดเผยคำตอบของผู้ตรวจคนก่อน
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.models import ExpertAlertGroup, ExpertReview

from .metrics import consolidate
from .reviews import round1_by_reviewer

PRIORITY = ("adjudication", "second_review", "primary")


def next_for_reviewer(db: Session, reviewer_id, group_ids=None):
    q = db.query(ExpertAlertGroup)
    if group_ids is not None:
        q = q.filter(ExpertAlertGroup.id.in_(list(group_ids)))
    groups = q.order_by(ExpertAlertGroup.first_seen_at, ExpertAlertGroup.id).all()
    if not groups:
        return None

    rows = (
        db.query(ExpertReview)
        .filter(ExpertReview.group_id.in_([g.id for g in groups]))
        .all()
    )
    by_group = defaultdict(list)
    for r in rows:
        by_group[r.group_id].append(r)

    found: dict[str, object] = {}
    for g in groups:
        ordered = round1_by_reviewer(by_group[g.id])
        if any(r.reviewer_id == reviewer_id for r in ordered):
            continue
        n = len(ordered)
        if n == 0:
            kind = "primary"
        elif n == 1 and g.double_review:
            kind = "second_review"
        elif (
            n == 2
            and consolidate([r.verdict for r in ordered])["status"]
            == "needs_adjudication"
        ):
            kind = "adjudication"
        else:
            continue
        found.setdefault(kind, g.id)

    for kind in PRIORITY:
        if kind in found:
            return (found[kind], kind)
    return None
