"""API Alerts router — Rule-based API anomaly detection dashboard.

อ้างอิง:
  - OWASP API Security Top 10 (2023) API4 — Unrestricted Resource Consumption
  - NIST SP 800-228 — Guidelines for API Protection

Endpoints:
  GET  /admin/api-alerts          → list recent alerts
  POST /admin/api-alerts/scan     → สแกน request_logs ตอนนี้ + persist alerts ใหม่
  POST /admin/api-alerts/{id}/resolve → mark alert as resolved
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_hub_admin
from app.models import ApiAlert, User
from app.services.api_guard import RULES, scan_and_persist

router = APIRouter()


@router.get("")
def list_alerts(
    days: int = Query(7, ge=1, le=90, description="จำนวนวันย้อนหลัง"),
    rule: str | None = Query(None, description="filter ตาม rule name"),
    severity: str | None = Query(None, description="filter: warning | critical"),
    resolved: bool | None = Query(None, description="filter: resolved status"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """แสดง API alerts ล่าสุด พร้อม filter."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = db.query(ApiAlert).filter(ApiAlert.created_at >= cutoff)

    if rule:
        q = q.filter(ApiAlert.rule == rule)
    if severity:
        q = q.filter(ApiAlert.severity == severity)
    if resolved is not None:
        q = q.filter(ApiAlert.resolved == resolved)

    alerts = q.order_by(ApiAlert.created_at.desc()).limit(200).all()

    return {
        "data": {
            "alerts": [
                {
                    "id": str(a.id),
                    "rule": a.rule,
                    "severity": a.severity,
                    "ip": str(a.ip) if a.ip else None,
                    "user_id": str(a.user_id) if a.user_id else None,
                    "detail": a.detail,
                    "resolved": a.resolved,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in alerts
            ],
            "total": len(alerts),
            "rules": {k: v["desc"] for k, v in RULES.items()},
        },
    }


@router.post("/scan")
def scan_now(
    minutes: int = Query(5, ge=1, le=60, description="สแกนย้อนหลังกี่นาที"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """สแกน request_logs ตอนนี้ → persist alerts ใหม่ (dedup 10 นาที)."""
    new_alerts = scan_and_persist(db, minutes)
    return {
        "scanned_minutes": minutes,
        "new_alerts": len(new_alerts),
        "alerts": [
            {
                "id": str(a.id),
                "rule": a.rule,
                "severity": a.severity,
                "ip": str(a.ip) if a.ip else None,
                "detail": a.detail,
            }
            for a in new_alerts
        ],
    }


@router.post("/{alert_id}/resolve")
def resolve_alert(
    alert_id: str,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Mark alert ว่าตรวจสอบแล้ว (resolved)."""
    alert = db.query(ApiAlert).filter(ApiAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="ไม่พบ alert")
    alert.resolved = True
    db.commit()
    return {"id": str(alert.id), "resolved": True}
