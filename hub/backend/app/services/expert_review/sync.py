"""สร้าง alert group + system disposition จาก shadow decision.

* อ่าน login ที่ `decision` เป็น `would_*` **หรือ** L3 ทำให้ผลจำลองเปลี่ยน **หรือ**
  L3 ขอให้ตรวจ (`l3_investigate`) — ขั้นที่ 10 ของแผน Hybrid Shadow
* ที่มาของคอนฟิกของกลุ่มอ่านจาก **แถวของ login** ไม่ใช่ settings ตอน sync · ถ้าแถว
  ในกลุ่มคอนฟิกไม่ตรงกัน ฟิลด์นั้นเป็น None (พิสูจน์ที่มาไม่ได้) — B66
* สร้างเฉพาะกลุ่มของหน้าต่างที่ **ปิดแล้ว** — เนื้อหาของกลุ่มจึงไม่เปลี่ยนหลังผู้ตรวจเริ่มดู
* `since` ถูกปัดลงต้นหน้าต่าง กันกลุ่มถูกสร้างจากหน้าต่างที่ขาดครึ่ง
* idempotent — group_key ที่มีแล้วข้าม
* system disposition เขียนครั้งเดียวตอนสร้าง (Postgres ปฏิเสธ UPDATE)
* provenance ของกลุ่ม = ที่มาที่น่าเชื่อถือน้อยที่สุดในกลุ่ม · กลุ่มจะเป็น
  external ได้ก็ต่อเมื่อทุกเหตุการณ์มาจากภายนอก
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import Text, cast, or_
from sqlalchemy.orm import Session

from app.models import ExpertAlertGroup, LoginSession, SystemDisposition
from app.services.audit_service import log_action

from . import grouping as G
from . import provenance as PV
from .vocab import EPOCH_FIELDS, PROVENANCES

_SEVERITY = ("would_block", "would_challenge", "would_mfa", "would_warn")


def group_provenance(values) -> str:
    for p in PROVENANCES:
        if p in values:
            return p
    return "unknown"


def _disposition(decisions: Counter) -> str:
    for d in _SEVERITY:
        if d in decisions:
            return d
    return sorted(decisions)[0]


def _num(x):
    return None if x is None else float(x)


def _model_row(s: LoginSession) -> dict:
    bd = s.risk_breakdown if isinstance(s.risk_breakdown, dict) else {}
    l3 = bd.get("l3") if isinstance(bd.get("l3"), dict) else {}
    return {
        "session_id": str(s.id),
        "created_at": s.created_at.isoformat(),
        "decision": s.decision,
        "risk_score": _num(s.risk_score),
        "anomaly_score": _num(s.anomaly_score),
        "primary_layer": bd.get("primary_layer"),
        "final_risk_score": bd.get("final_risk_score"),
        "reasons": list(s.risk_reasons or []),
        # ผลจำลอง — ผู้ตรวจเห็นได้เฉพาะรอบ unblinded (blind_payload ไม่อ่านส่วนนี้)
        "selected_because": sorted(G.selection_reasons(s)),
        "baseline_shadow_decision": s.baseline_shadow_decision,
        "baseline_shadow_score": _num(s.baseline_shadow_score),
        "hybrid_shadow_decision": s.hybrid_shadow_decision,
        "hybrid_shadow_score": _num(s.hybrid_shadow_score),
        "l3_changed_shadow_decision": s.l3_changed_shadow_decision,
        "l3_monitoring_decision": l3.get("monitoring_decision"),
        "l3_eligibility": s.l3_eligibility,
        "shadow_epoch_id": s.shadow_epoch_id,
    }


def group_epoch(rows) -> dict:
    """ที่มาของคอนฟิกของกลุ่ม = ค่าที่ทุกแถวตรงกัน · ไม่ตรงกันหรือว่าง = None.

    ไม่เติมจาก settings ตอน sync — แถวที่เกิดก่อนมีการบันทึกที่มา (NULL) ต้องคง
    NULL ไว้ ไม่ใช่ถูกติดป้ายด้วยคอนฟิกที่รันอยู่ตอนนี้
    """
    out = {}
    for field in EPOCH_FIELDS:
        values = {getattr(r, field, None) for r in rows}
        out[field] = values.pop() if len(values) == 1 else None
    return out


def sync_alert_groups(
    db: Session,
    *,
    now: datetime,
    since: datetime,
    user_id=None,
) -> dict:
    q = db.query(LoginSession).filter(
        LoginSession.created_at >= G.window_start(since),
        LoginSession.created_at <= now,
        or_(
            LoginSession.decision.like("would%"),
            LoginSession.l3_changed_shadow_decision.is_(True),
            # risk_breakdown เป็น JSON (ไม่ใช่ JSONB) — คัดหยาบด้วยข้อความก่อน
            # แล้วตัดสินจริงด้วย G.is_candidate ด้านล่าง
            cast(LoginSession.risk_breakdown, Text).like(
                f"%{G.REASON_L3_INVESTIGATE}%"
            ),
        ),
    )
    if user_id is not None:
        q = q.filter(LoginSession.user_id == user_id)
    sessions = [s for s in q.all() if G.is_candidate(s)]

    width = timedelta(minutes=G.WINDOW_MINUTES)
    closed = [s for s in sessions if G.window_start(s.created_at) + width <= now]
    still_open = [s for s in sessions if G.window_start(s.created_at) + width > now]

    drafts = G.build_groups(closed)
    keys = [d.group_key for d in drafts]
    existing = set()
    if keys:
        existing = {
            k
            for (k,) in db.query(ExpertAlertGroup.group_key).filter(
                ExpertAlertGroup.group_key.in_(keys)
            )
        }

    by_id = {s.id: s for s in closed}
    created = skipped = 0
    for d in drafts:
        if d.group_key in existing:
            skipped += 1
            continue
        rows = [by_id[i] for i in d.session_ids]
        epoch = group_epoch(rows)
        prov = group_provenance(
            {PV.classify(str(s.ip) if s.ip else None, s.user_agent) for s in rows}
        )
        eligible = PV.is_eligible(
            prov, epoch["risk_config_id"], epoch["scoring_commit"]
        )
        g = ExpertAlertGroup(
            group_key=d.group_key,
            user_id=d.user_id,
            primary_signal=d.primary_signal,
            window_start=d.window_start,
            session_ids=[str(i) for i in d.session_ids],
            n_events=d.n_events,
            first_seen_at=d.first_seen_at,
            last_seen_at=d.last_seen_at,
            provenance=prov,
            eligible_for_production_metrics=eligible,
            double_review=G.in_double_review_pool(d.group_key),
            **epoch,
        )
        db.add(g)
        db.flush()

        decisions = Counter(s.decision for s in rows)
        scores = [float(s.risk_score) for s in rows if s.risk_score is not None]
        first_bd = (
            rows[0].risk_breakdown if isinstance(rows[0].risk_breakdown, dict) else {}
        )
        db.add(
            SystemDisposition(
                group_id=g.id,
                disposition=_disposition(decisions),
                decision_counts=dict(sorted(decisions.items())),
                max_risk_score=max(scores) if scores else None,
                primary_layer=first_bd.get("primary_layer"),
                model_output=[_model_row(s) for s in rows],
            )
        )
        log_action(
            db,
            actor_id=None,
            action="expert_alert_group_created",
            target_type="expert_alert_group",
            target_id=g.id,
            metadata={
                "n_events": d.n_events,
                "provenance": prov,
                "eligible_for_production_metrics": eligible,
                "shadow_epoch_id": epoch["shadow_epoch_id"],
            },
        )
        created += 1

    db.commit()
    return {
        "created": created,
        "skipped_existing": skipped,
        "skipped_open_window": len(G.build_groups(still_open)),
    }
