"""ML Admin router — overview KPIs, feedback loop, threshold preview, per-user timeline.

Endpoints:
  GET  /admin/ml/overview                           -> score histogram + decision breakdown + top anomalies
  POST /admin/ml/sessions/{session_id}/feedback     -> mark false/true positive (upsert)
  GET  /admin/ml/threshold/preview                  -> จำลอง threshold ใหม่กับ scores ที่มีอยู่
  GET  /admin/ml/users/{user_id}/sessions           -> timeline session ของ user คนเดียว
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import LoginSession, MLFeedback, User
from app.services.audit_service import log_action
from app.services.feature_extraction import browser_family

router = APIRouter()

# Thresholds — ต้องตรงกับ ml-service/app/main.py
_DEFAULT_BLOCK = 0.70
_DEFAULT_MFA = 0.40


# ============ P1-4: Overview KPIs ============

@router.get("/overview")
def ml_overview(
    days: int = Query(7, ge=1, le=365, description="จำนวนวันย้อนหลัง"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """KPI สรุป ML สำหรับ admin dashboard:
    - score histogram 10 buckets
    - decision breakdown
    - top 20 anomalies เรียงตาม score DESC
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)

    # ดึงทุก session ในช่วงเวลา — ใช้ Python bucket (หลีกเลี่ยง edge case ของ Numeric(3,2))
    sessions = (
        db.query(LoginSession)
        .filter(LoginSession.created_at >= cutoff)
        .all()
    )
    total_logins = len(sessions)

    # Score histogram — 10 buckets [0.0-0.1, 0.1-0.2, ..., 0.9-1.0]
    bucket_labels = [f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)]
    buckets = [0] * 10
    for s in sessions:
        if s.anomaly_score is not None:
            idx = min(int(float(s.anomaly_score) * 10), 9)
            buckets[idx] += 1
    score_histogram = [
        {"bucket": bucket_labels[i], "count": buckets[i]} for i in range(10)
    ]

    # Decision breakdown
    decision_counter: dict[str, int] = {}
    for s in sessions:
        d = s.decision or "unknown"
        decision_counter[d] = decision_counter.get(d, 0) + 1

    # Top 20 anomalies — join User เพื่อดึง email
    top_rows = (
        db.query(LoginSession, User)
        .join(User, User.id == LoginSession.user_id)
        .filter(
            LoginSession.created_at >= cutoff,
            LoginSession.anomaly_score.is_not(None),
        )
        .order_by(LoginSession.anomaly_score.desc())
        .limit(20)
        .all()
    )
    top_anomalies = [
        {
            "session_id": str(sess.id),
            "user_email": u.email,
            "score": float(sess.anomaly_score),
            "decision": sess.decision,
            "ip": str(sess.ip) if sess.ip else None,
            "geo_country": sess.geo_country,
            "os_name": sess.os_name,
            "browser": sess.browser,
            "device_type": sess.device_type,
            "is_attack_ip": sess.is_attack_ip,
            "is_account_takeover": sess.is_account_takeover,
            "created_at": sess.created_at,
        }
        for sess, u in top_rows
    ]

    return {
        "data": {
            "range": {
                "days": days,
                "from": cutoff.isoformat(),
                "to": now.isoformat(),
            },
            "total_logins": total_logins,
            "score_histogram": score_histogram,
            "decision_breakdown": decision_counter,
            "top_anomalies": top_anomalies,
        },
        "meta": {
            "shadow_mode": settings.ml_shadow_mode,
            "thresholds": {"block": _DEFAULT_BLOCK, "mfa": _DEFAULT_MFA},
        },
    }


# ============ P1-5: Feedback loop ============

class FeedbackBody(BaseModel):
    label: str   # false_positive | true_positive | normal_confirmed
    note: str | None = None


_VALID_LABELS = {"false_positive", "true_positive", "normal_confirmed"}


@router.post("/sessions/{session_id}/feedback")
def add_feedback(
    session_id: str,
    body: FeedbackBody,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Mark session เป็น false/true positive (upsert — 1 session = 1 label, แก้ทับได้).

    ใช้สำหรับสะสม ground truth ก่อน retrain หรือ threshold tuning.
    """
    if body.label not in _VALID_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"label ต้องเป็นหนึ่งใน: {', '.join(sorted(_VALID_LABELS))}",
        )

    sess = db.query(LoginSession).filter(LoginSession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="ไม่พบ login session")

    # Upsert
    existing = (
        db.query(MLFeedback).filter(MLFeedback.session_id == sess.id).first()
    )
    if existing:
        existing.label = body.label
        existing.note = body.note
        existing.marked_by = admin.id
        existing.created_at = datetime.utcnow()
        action_name = "ml_feedback_updated"
    else:
        existing = MLFeedback(
            session_id=sess.id,
            label=body.label,
            note=body.note,
            marked_by=admin.id,
        )
        db.add(existing)
        action_name = "ml_feedback_added"

    # Sync ground truth label → login_sessions.is_account_takeover
    # (ตรงกับ RBA dataset ของ Wiefling 2022 — "Is Account Takeover" column)
    if body.label == "true_positive":
        sess.is_account_takeover = True
    elif body.label in ("false_positive", "normal_confirmed"):
        sess.is_account_takeover = False

    log_action(
        db,
        actor_id=admin.id,
        action=action_name,
        target_type="login_session",
        target_id=sess.id,
        ip=get_client_ip(request),
        metadata={"label": body.label, "note": body.note},
    )
    db.commit()
    db.refresh(existing)

    return {
        "session_id": session_id,
        "label": existing.label,
        "note": existing.note,
        "marked_by": str(existing.marked_by),
        "created_at": existing.created_at,
    }


# ============ P1-6: Threshold preview ============

@router.get("/threshold/preview")
def threshold_preview(
    block: float = Query(_DEFAULT_BLOCK, ge=0.0, le=1.0, description="proposed block threshold"),
    mfa: float = Query(_DEFAULT_MFA, ge=0.0, le=1.0, description="proposed mfa threshold"),
    days: int = Query(30, ge=1, le=365, description="จำนวนวันย้อนหลัง"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """จำลองว่าถ้าใช้ threshold ใหม่กับ scores ที่บันทึกไว้ ผลจะเปลี่ยนยังไง.

    ไม่ retrain model — แค่ apply threshold ใหม่กับข้อมูลที่มีอยู่ใน window.
    ถ้ามี MLFeedback labels จะคำนวณ precision estimate ด้วย.
    """
    if mfa >= block:
        raise HTTPException(
            status_code=400,
            detail=f"mfa threshold ({mfa}) ต้องน้อยกว่า block threshold ({block})",
        )

    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)

    # ดึง (session_id, anomaly_score) ทั้งหมดในช่วง
    score_rows = (
        db.query(LoginSession.id, LoginSession.anomaly_score, LoginSession.decision)
        .filter(
            LoginSession.created_at >= cutoff,
            LoginSession.anomaly_score.is_not(None),
        )
        .all()
    )

    # Current breakdown จาก decision column ที่บันทึกไว้
    current_breakdown: dict[str, int] = {}
    for _, _, dec in score_rows:
        d = dec or "unknown"
        current_breakdown[d] = current_breakdown.get(d, 0) + 1

    # Simulated breakdown ด้วย proposed threshold
    sim: dict[str, int] = {"pass": 0, "mfa": 0, "block": 0}
    high_score_ids = []
    for sess_id, score_val, _ in score_rows:
        s = float(score_val)
        if s >= block:
            sim["block"] += 1
            high_score_ids.append(sess_id)
        elif s >= mfa:
            sim["mfa"] += 1
        else:
            sim["pass"] += 1

    # Feedback precision estimate — จากเฉพาะ session ที่ score >= proposed block
    with_feedback: dict = {
        "true_positive": 0,
        "false_positive": 0,
        "precision_estimate": None,
        "recall_estimate": None,
    }
    if high_score_ids:
        fb_rows = (
            db.query(MLFeedback.label, func.count(MLFeedback.id))
            .filter(MLFeedback.session_id.in_(high_score_ids))
            .group_by(MLFeedback.label)
            .all()
        )
        label_counts = {label: cnt for label, cnt in fb_rows}
        tp = label_counts.get("true_positive", 0)
        fp = label_counts.get("false_positive", 0)
        with_feedback["true_positive"] = tp
        with_feedback["false_positive"] = fp
        denom = tp + fp
        if denom > 0:
            with_feedback["precision_estimate"] = round(tp / denom, 4)

    return {
        "data": {
            "proposed": {"block": block, "mfa": mfa},
            "current": {"block": _DEFAULT_BLOCK, "mfa": _DEFAULT_MFA},
            "simulated_breakdown": sim,
            "current_breakdown": current_breakdown,
            "with_feedback": with_feedback,
        }
    }


# ============ P1-7: Per-user session timeline ============

@router.get("/users/{user_id}/sessions")
def user_session_timeline(
    user_id: str,
    days: int = Query(30, ge=1, le=365, description="จำนวนวันย้อนหลัง"),
    limit: int = Query(100, ge=1, le=500, description="จำนวน session สูงสุด"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Timeline session + ML score ของ user คนเดียว (เรียงตาม created_at DESC).

    ใช้ใน UI page "ดูพฤติกรรม user" — รวม feedback label ถ้ามี.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบ user")

    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)

    rows = (
        db.query(LoginSession, MLFeedback)
        .outerjoin(MLFeedback, MLFeedback.session_id == LoginSession.id)
        .filter(
            LoginSession.user_id == user_id,
            LoginSession.created_at >= cutoff,
        )
        .order_by(LoginSession.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "data": {
            "user": {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "user_type": user.user_type,
            },
            "sessions": [
                {
                    "id": str(sess.id),
                    "score": float(sess.anomaly_score) if sess.anomaly_score is not None else None,
                    "decision": sess.decision,
                    "ip": str(sess.ip) if sess.ip else None,
                    "geo_country": sess.geo_country,
                    "os_name": sess.os_name,
                    "browser": sess.browser or browser_family(sess.user_agent),
                    "device_type": sess.device_type,
                    "is_attack_ip": sess.is_attack_ip,
                    "is_account_takeover": sess.is_account_takeover,
                    "created_at": sess.created_at,
                    "feedback_label": fb.label if fb else None,
                }
                for sess, fb in rows
            ],
            "range": {
                "days": days,
                "from": cutoff.isoformat(),
                "to": now.isoformat(),
            },
        }
    }
