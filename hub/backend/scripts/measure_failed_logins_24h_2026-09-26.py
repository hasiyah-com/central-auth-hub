"""วัดผลกระทบของนิยามใหม่ failed_logins_24h ต่อระดับกฎชั้นที่ 1 — อ่านอย่างเดียว.

ทุก session ใน login_sessions: คำนวณค่าเดิม (นับ block/would_block) และค่าใหม่
(extract_session_features · audit_logs) ที่ now = session.created_at แล้วจัดระดับกฎ
(>=10 บล็อก · >=5 บังคับยืนยันตัวตน · >=3 +0.20 · ต่ำกว่า = ไม่มีผล)

ไม่ replay ผลตัดสินรวม: กฎอื่นใน evaluate_rules อ้างเวลาปัจจุบัน (multi-account IP)
จึงให้ผลย้อนหลังไม่ตรงเวลา — วัดเฉพาะส่วนที่ฟีเจอร์นี้ควบคุมโดยตรง

    PYTHONPATH=. python scripts/measure_failed_logins_24h_2026-09-26.py
"""

import json
from collections import Counter
from datetime import timedelta

from sqlalchemy import func

from app.database import SessionLocal
from app.models import AuditLog, LoginSession
from app.security.rule_engine import FEAT
from app.services.feature_extraction import (
    FAILED_AUTH_ACTOR_ACTIONS,
    FAILED_AUTH_EMAIL_ACTIONS,
    extract_session_features,
)


def tier(n: float) -> str:
    if n >= 10:
        return "block"
    if n >= 5:
        return "challenge"
    if n >= 3:
        return "plus_0.20"
    return "none"


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.query(
            LoginSession.id,
            LoginSession.user_id,
            LoginSession.created_at,
            LoginSession.ip,
            LoginSession.user_agent,
            LoginSession.geo_country,
            LoginSession.subsystem_id,
        ).all()
        trans = Counter()
        old_t, new_t = Counter(), Counter()
        for sid, uid, at, ip, ua, geo, sub in rows:
            if uid is None or at is None:
                continue
            old = (
                db.query(func.count(LoginSession.id))
                .filter(
                    LoginSession.user_id == uid,
                    LoginSession.decision.in_(["block", "would_block"]),
                    LoginSession.created_at >= at - timedelta(hours=24),
                    LoginSession.created_at < at,
                )
                .scalar()
                or 0
            )
            new = extract_session_features(
                db, uid, str(ip) if ip else None, ua, geo, now=at, subsystem_id=sub
            )[FEAT["failed_logins_24h"]]
            old_t[tier(old)] += 1
            new_t[tier(new)] += 1
            trans[f"{tier(old)}->{tier(new)}"] += 1
        audit_actions = dict(
            db.query(AuditLog.action, func.count(AuditLog.id))
            .filter(
                AuditLog.action.in_(
                    FAILED_AUTH_ACTOR_ACTIONS + FAILED_AUTH_EMAIL_ACTIONS
                )
            )
            .group_by(AuditLog.action)
            .all()
        )
        print(
            json.dumps(
                {
                    "sessions": sum(old_t.values()),
                    "old_tiers": dict(old_t),
                    "new_tiers": dict(new_t),
                    "transitions": dict(sorted(trans.items())),
                    "counted_audit_rows_by_action": audit_actions,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
