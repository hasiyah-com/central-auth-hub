"""Rule-based API anomaly detection — สแกน request_logs หาพฤติกรรมผิดปกติ.

อ้างอิง:
  - OWASP API Security Top 10 (2023) API4 — Unrestricted Resource Consumption
  - NIST SP 800-228 — Guidelines for API Protection
  - Wiefling et al. (2022) — comprehensive review of web log anomaly detection

กฎ 4 ข้อ:
  1. excessive_requests  — IP ส่ง request มากเกินไปใน 1 นาที
  2. high_error_rate     — IP ได้ 4xx error มากเกินไปใน 5 นาที
  3. unauthorized_probing — IP/User พยายามเข้า endpoint ที่ไม่มีสิทธิ์ซ้ำๆ (403)
  4. bot_pattern         — IP ส่ง request ที่ interval สม่ำเสมอผิดปกติ (automated)

ทุกกฎไม่กระทบ ML anomaly_score — เป็นระบบแยกอิสระ
"""

import logging
import statistics
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ApiAlert, RequestLog
from app.services.alert_service import send_alert

log = logging.getLogger(__name__)


# map ApiAlert.severity (warning|critical) → alert_service severity
def _severity_to_alert(sev: str) -> str:
    return "critical" if sev == "critical" else "warning"


# ============ Thresholds (ปรับได้ตาม environment) ============

RULES = {
    "excessive_requests": {
        "window_sec": 60,
        "threshold": 100,  # > 100 requests/min per IP
        "severity": "warning",
        "desc": "IP ส่ง request มากเกินปกติ",
    },
    "high_error_rate": {
        "window_sec": 300,
        "threshold": 20,  # > 20 4xx errors / 5 min per IP
        "severity": "warning",
        "desc": "IP ได้ error 4xx มากผิดปกติ (อาจ probing)",
    },
    "unauthorized_probing": {
        "window_sec": 300,
        "threshold": 5,  # > 5 403 errors / 5 min per IP
        "severity": "critical",
        "desc": "IP พยายามเข้า endpoint ที่ไม่มีสิทธิ์ซ้ำๆ",
    },
    "bot_pattern": {
        "window_sec": 120,
        "min_requests": 10,  # ต้องมีอย่างน้อย 10 requests ใน 2 min
        "max_cv": 0.15,  # coefficient of variation < 15% = interval สม่ำเสมอเกินไป
        "severity": "warning",
        "desc": "Request pattern สม่ำเสมอผิดปกติ (อาจเป็น bot)",
    },
}


def scan_request_logs(db: Session, minutes: int = 5) -> list[dict]:
    """สแกน request_logs ย้อนหลัง N นาที หาพฤติกรรมที่ผิดกฎ.

    Returns list ของ alert dict (ยังไม่ persist — caller เลือกเอง).
    """
    now = datetime.utcnow()
    alerts: list[dict] = []

    # ── Rule 1: excessive_requests ──
    rule = RULES["excessive_requests"]
    cutoff = now - timedelta(seconds=rule["window_sec"])
    rows = (
        db.query(RequestLog.ip, func.count(RequestLog.id).label("cnt"))
        .filter(RequestLog.created_at >= cutoff, RequestLog.ip.is_not(None))
        .group_by(RequestLog.ip)
        .having(func.count(RequestLog.id) > rule["threshold"])
        .all()
    )
    for ip, cnt in rows:
        # ดึง user_id ที่ใช้บ่อยสุดจาก IP นี้
        top_user = _top_user_for_ip(db, ip, cutoff)
        alerts.append(
            {
                "rule": "excessive_requests",
                "severity": rule["severity"],
                "ip": str(ip),
                "user_id": top_user,
                "detail": {
                    "count": cnt,
                    "window_sec": rule["window_sec"],
                    "threshold": rule["threshold"],
                    "desc": rule["desc"],
                },
            }
        )

    # ── Rule 2: high_error_rate ──
    rule = RULES["high_error_rate"]
    cutoff = now - timedelta(seconds=rule["window_sec"])
    rows = (
        db.query(RequestLog.ip, func.count(RequestLog.id).label("cnt"))
        .filter(
            RequestLog.created_at >= cutoff,
            RequestLog.ip.is_not(None),
            RequestLog.status_code >= 400,
            RequestLog.status_code < 500,
        )
        .group_by(RequestLog.ip)
        .having(func.count(RequestLog.id) > rule["threshold"])
        .all()
    )
    for ip, cnt in rows:
        # ดึง path ที่ error บ่อยสุด
        sample_paths = _top_error_paths(db, ip, cutoff)
        top_user = _top_user_for_ip(db, ip, cutoff)
        alerts.append(
            {
                "rule": "high_error_rate",
                "severity": rule["severity"],
                "ip": str(ip),
                "user_id": top_user,
                "detail": {
                    "count": cnt,
                    "window_sec": rule["window_sec"],
                    "threshold": rule["threshold"],
                    "sample_paths": sample_paths,
                    "desc": rule["desc"],
                },
            }
        )

    # ── Rule 3: unauthorized_probing ──
    rule = RULES["unauthorized_probing"]
    cutoff = now - timedelta(seconds=rule["window_sec"])
    rows = (
        db.query(RequestLog.ip, func.count(RequestLog.id).label("cnt"))
        .filter(
            RequestLog.created_at >= cutoff,
            RequestLog.ip.is_not(None),
            RequestLog.status_code == 403,
        )
        .group_by(RequestLog.ip)
        .having(func.count(RequestLog.id) > rule["threshold"])
        .all()
    )
    for ip, cnt in rows:
        sample_paths = _top_error_paths(db, ip, cutoff, status=403)
        top_user = _top_user_for_ip(db, ip, cutoff)
        alerts.append(
            {
                "rule": "unauthorized_probing",
                "severity": rule["severity"],
                "ip": str(ip),
                "user_id": top_user,
                "detail": {
                    "count": cnt,
                    "window_sec": rule["window_sec"],
                    "threshold": rule["threshold"],
                    "sample_paths": sample_paths,
                    "desc": rule["desc"],
                },
            }
        )

    # ── Rule 4: bot_pattern ──
    rule = RULES["bot_pattern"]
    cutoff = now - timedelta(seconds=rule["window_sec"])
    # หา IP ที่มี request >= min_requests
    ip_rows = (
        db.query(RequestLog.ip)
        .filter(RequestLog.created_at >= cutoff, RequestLog.ip.is_not(None))
        .group_by(RequestLog.ip)
        .having(func.count(RequestLog.id) >= rule["min_requests"])
        .all()
    )
    for (ip,) in ip_rows:
        timestamps = (
            db.query(RequestLog.created_at)
            .filter(RequestLog.created_at >= cutoff, RequestLog.ip == ip)
            .order_by(RequestLog.created_at)
            .all()
        )
        # SQLAlchemy คืน Row ที่มี 1 column → unpack (t,) ได้ datetime ตรงๆ
        # ไม่ต้องเรียก .created_at อีก (เป็น bug เดิมที่ทำให้ AttributeError)
        ts_list = [t.timestamp() for (t,) in timestamps]
        if len(ts_list) < rule["min_requests"]:
            continue
        # คำนวณ interval ระหว่าง request ติดกัน
        intervals = [ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1)]
        if not intervals:
            continue
        mean_interval = statistics.mean(intervals)
        if mean_interval <= 0:
            continue
        stdev = statistics.stdev(intervals) if len(intervals) >= 2 else 0
        cv = stdev / mean_interval  # coefficient of variation
        if cv < rule["max_cv"]:
            top_user = _top_user_for_ip(db, ip, cutoff)
            alerts.append(
                {
                    "rule": "bot_pattern",
                    "severity": rule["severity"],
                    "ip": str(ip),
                    "user_id": top_user,
                    "detail": {
                        "request_count": len(ts_list),
                        "mean_interval_sec": round(mean_interval, 2),
                        "cv": round(cv, 4),
                        "max_cv": rule["max_cv"],
                        "window_sec": rule["window_sec"],
                        "desc": rule["desc"],
                    },
                }
            )

    return alerts


def scan_and_persist(db: Session, minutes: int = 5) -> list[ApiAlert]:
    """สแกน + บันทึก alert ใหม่ลง DB (ข้ามถ้ามี alert ซ้ำ rule+ip ใน 10 นาทีล่าสุด)."""
    raw_alerts = scan_request_logs(db, minutes)
    dedup_cutoff = datetime.utcnow() - timedelta(minutes=10)
    persisted: list[ApiAlert] = []

    for a in raw_alerts:
        # Dedup: ถ้ามี alert เดียวกัน (rule + ip) ใน 10 นาที → ข้าม
        existing = (
            db.query(ApiAlert)
            .filter(
                ApiAlert.rule == a["rule"],
                ApiAlert.ip == a["ip"],
                ApiAlert.created_at >= dedup_cutoff,
            )
            .first()
        )
        if existing:
            continue

        alert = ApiAlert(
            rule=a["rule"],
            severity=a["severity"],
            ip=a["ip"],
            user_id=a["user_id"],
            detail=a["detail"],
        )
        db.add(alert)
        persisted.append(alert)

    if persisted:
        db.commit()
        for a in persisted:
            db.refresh(a)
        # Fire alerts (fail-safe — webhook/email error ห้าม rollback alert ใน DB)
        for a in persisted:
            try:
                send_alert(
                    severity=_severity_to_alert(a.severity),
                    kind=f"api_guard.{a.rule}",
                    key=str(a.ip),
                    title=f"{a.rule.replace('_', ' ').title()} — {a.ip}",
                    detail={
                        "rule": a.rule,
                        "ip": str(a.ip),
                        "user_id": str(a.user_id) if a.user_id else None,
                        **(a.detail or {}),
                    },
                )
            except Exception as e:
                log.exception("alert dispatch failed for ApiAlert %s: %r", a.id, e)

    return persisted


# ============ Helpers ============


def _top_user_for_ip(db: Session, ip: str, cutoff: datetime) -> str | None:
    """หา user_id ที่ใช้บ่อยสุดจาก IP ใน window."""
    row = (
        db.query(RequestLog.user_id, func.count(RequestLog.id).label("cnt"))
        .filter(
            RequestLog.created_at >= cutoff,
            RequestLog.ip == ip,
            RequestLog.user_id.is_not(None),
        )
        .group_by(RequestLog.user_id)
        .order_by(func.count(RequestLog.id).desc())
        .first()
    )
    return str(row.user_id) if row and row.user_id else None


def _top_error_paths(
    db: Session,
    ip: str,
    cutoff: datetime,
    status: int | None = None,
    limit: int = 5,
) -> list[str]:
    """หา path ที่ error บ่อยสุดจาก IP."""
    q = db.query(RequestLog.path, func.count(RequestLog.id).label("cnt")).filter(
        RequestLog.created_at >= cutoff,
        RequestLog.ip == ip,
    )
    if status:
        q = q.filter(RequestLog.status_code == status)
    else:
        q = q.filter(RequestLog.status_code >= 400, RequestLog.status_code < 500)

    rows = (
        q.group_by(RequestLog.path)
        .order_by(func.count(RequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [row.path for row in rows]
