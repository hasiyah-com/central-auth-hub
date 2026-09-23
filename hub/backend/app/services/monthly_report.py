"""รายงานรายเดือนสำหรับผู้บริหาร — รวมตัวเลขของ "เดือนตามปฏิทินเวลาไทย"

ทำไมไม่ใช้ endpoint เดิม: ทุก endpoint ของ admin รับแค่ "ย้อนหลัง N ชม. จากตอนนี้"
(/activity ≤ 720 ชม., /incidents ≤ 2160 ชม.) — เลือกเดือนเจาะจงหรือเทียบเดือนก่อน
ไม่ได้ จึงคำนวณจากช่วงเวลาที่กำหนดเองตรงนี้

หลักการ:
  - ขอบเดือนตัดตาม Asia/Bangkok (UTC+7, ไม่มี DST) แล้วแปลงเป็น naive UTC
    ให้ตรงกับที่ DB เก็บ — ไม่งั้น session ช่วง 00:00–06:59 ต้นเดือนจะหลุดไปเดือนก่อน
  - นิยาม blocked / challenged / incident ใช้ค่าคงที่ชุดเดียวกับหน้า Activity และ
    Incidents เพื่อให้ตัวเลขในรายงานตรงกับที่ผู้ดูแลเห็นในคอนโซล
  - ไม่มีข้อมูล = 0 หรือ None ห้ามค่าสมมติ; metric ที่ระบบเก็บข้อมูลย้อนหลังไม่พอ
    ประกาศไว้ใน `unavailable` แทนการเดา
  - ข้อสังเกต / ข้อเสนอแนะ / บทสรุป สร้างจากกฎบนตัวเลขจริงเท่านั้น ทุกข้อมี `basis`
    บอกตัวเลขที่ใช้ตัดสิน — แอดมินแก้ถ้อยคำเพิ่มได้ที่หน้าเว็บก่อนพิมพ์ (ไม่บันทึก)
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import case, distinct, func, or_
from sqlalchemy.orm import Session

from app.models import (
    ApiAlert,
    AuditLog,
    IpBlacklist,
    LoginSession,
    MLFeedback,
    RequestLog,
    Subsystem,
    User,
)

# ใช้ชุดเดียวกับหน้า Activity/Dashboard (KPI blocked/challenged) — แหล่งเดียว ไม่เขียนซ้ำ
from app.routers.admin import _BLOCKED_DECISIONS, _CHALLENGED_DECISIONS

# ใช้นิยามเดียวกับหน้า Incidents
from app.services.incident_service import INCIDENT_DECISIONS, INCIDENT_RISK_SCORE_MIN

BKK_OFFSET = timedelta(hours=7)
TIMEZONE = "Asia/Bangkok"

THAI_MONTHS = (
    "มกราคม",
    "กุมภาพันธ์",
    "มีนาคม",
    "เมษายน",
    "พฤษภาคม",
    "มิถุนายน",
    "กรกฎาคม",
    "สิงหาคม",
    "กันยายน",
    "ตุลาคม",
    "พฤศจิกายน",
    "ธันวาคม",
)

# uptime จริง: health history ละเอียดอยู่ใน Redis แค่ 288 จุด (≈ 24 ชม.) — มีแค่ snapshot
#   3 ครั้ง/วันใน audit_logs จึงรายงานได้เป็น "ผลสุ่มตรวจ" (availability) ไม่ใช่ uptime
# resource_usage: CPU / Memory / Disk ไม่มีการเก็บไว้ที่ไหนเลย
UNAVAILABLE = ["subsystem_uptime", "resource_usage"]

HUB_DIRECT_LABEL = "Hub (เข้าสู่ระบบโดยตรง)"
TREND_MONTHS = 6

HEALTH_SUMMARY_ACTION = "subsystem_health_summary"
HEALTH_STATUSES = ("online", "degraded", "down", "unknown")

# กลุ่ม endpoint สำหรับภาคผนวกประสิทธิภาพ API (เรียงตามลำดับที่แสดง)
API_GROUPS = (
    ("oauth", "OAuth — ระบบย่อย", "/oauth/%"),
    ("auth", "Hub — เข้าสู่ระบบ / token", "/auth/%"),
    ("account", "บัญชีผู้ใช้", "/account/%"),
    ("roster", "Roster API", "/api/v1/%"),
    ("admin", "Admin console", "/admin/%"),
    ("developer", "Developer portal", "/developer/%"),
)
API_OTHER = ("other", "อื่นๆ")

# audit action ที่ถือเป็นเหตุการณ์ด้านความปลอดภัย → (คำอธิบาย, ระดับ)
SECURITY_ACTIONS = {
    "ip_blacklist_added": ("เพิ่ม IP ใน blacklist", "warn"),
    "ip_blacklist_bulk_upload": ("นำเข้า IP blacklist จากไฟล์", "info"),
    "ip_blacklist_removed": ("นำ IP ออกจาก blacklist", "info"),
    "attack_ip_toggled": ("ทำเครื่องหมาย IP ที่โจมตี", "warn"),
    "admin_force_logout_user": ("แอดมินบังคับผู้ใช้ออกจากระบบ", "warn"),
    "login_blocked_by_risk_engine": ("ระงับการเข้าสู่ระบบย่อยจากคะแนนความเสี่ยง", "warn"),
    "hub_login_blocked_by_ml": ("ระงับการเข้าสู่ Hub จากคะแนนความเสี่ยง", "warn"),
    "oauth_authorize_blocked_suspended": ("มีการเรียกใช้ระบบย่อยที่ถูกระงับ", "info"),
    "subsystem_suspended": ("ระงับระบบย่อย", "warn"),
    "subsystem_resumed": ("เปิดใช้ระบบย่อยอีกครั้ง", "info"),
    "subsystem_approved": ("อนุมัติระบบย่อยใหม่", "info"),
    "subsystem_rejected": ("ปฏิเสธคำขอลงทะเบียนระบบย่อย", "info"),
    "client_secret_rotated": ("แอดมินเปลี่ยน client secret", "info"),
    "rotate_secret_requested": ("มีคำขอเปลี่ยน client secret", "info"),
    "passkey_admin_reset": ("แอดมินรีเซ็ต passkey ของผู้ใช้", "warn"),
    "delete_user": ("ลบผู้ใช้", "info"),
    "auth_policy_updated": ("แก้ไขนโยบายการยืนยันตัวตน", "warn"),
    "recovery_ticket_approved": ("อนุมัติคำขอกู้คืนบัญชี", "warn"),
    "recovery_ticket_rejected": ("ปฏิเสธคำขอกู้คืนบัญชี", "info"),
}
API_ALERT_LABELS = {
    "unauthorized_probing": "มีการเรียก endpoint ที่ไม่มีสิทธิ์ซ้ำๆ",
    "high_error_rate": "อัตรา error ของ API สูงผิดปกติ",
    "repeated_failed_mutation": "มีการแก้ไขข้อมูลที่ล้มเหลวซ้ำๆ",
}
_SEVERITY_RANK = {"critical": 0, "warn": 1, "info": 2}
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}

# เกณฑ์ของกฎ — ตั้งให้ไม่ตัดสินจากตัวอย่างน้อยเกินไป
ML_MIN_LABELS = 30  # label น้อยกว่านี้ไม่คำนวณ FP rate
LOGINS_CHANGE_PCT = 20.0  # การเข้าสู่ระบบเปลี่ยน ≥ 20% จากเดือนก่อน
BLOCK_RATE_UP_PP = 1.0  # block rate เพิ่ม ≥ 1 จุดเปอร์เซ็นต์
SUB_MIN_LOGINS = 10  # ระบบย่อยต้องมี login อย่างน้อยเท่านี้ถึงเทียบ block rate
SUB_BLOCK_RATE_MIN = 2.0  # และ block rate ≥ 2% และ ≥ 2 เท่าของภาพรวม
AVAILABILITY_WARN = 99.0  # สถานะปกติ < 99% ของการตรวจ → warn
AVAILABILITY_CRITICAL = 90.0  # < 90% → critical
API_MIN_REQUESTS = 50
API_ERROR_RATE = 1.0  # 5xx ≥ 1%


def month_range_utc(year: int, month: int) -> tuple[datetime, datetime]:
    """[start, end) ของเดือนตามเวลาไทย แปลงเป็น naive UTC."""
    start_local = datetime(year, month, 1)
    end_local = (
        datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    )
    return start_local - BKK_OFFSET, end_local - BKK_OFFSET


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def thai_month_name(ym: str) -> str:
    y, m = (int(x) for x in ym.split("-"))
    return f"{THAI_MONTHS[m - 1]} {y + 543}"


def _pct_change(cur: int, prev: int) -> float | None:
    """% เปลี่ยนแปลง — เดือนก่อนเป็น 0 คำนวณไม่ได้ จึงคืน None (ไม่ใช่ 0 หรือ 100)."""
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _rate(part: int, total: int) -> float | None:
    return round(part / total * 100, 1) if total else None


def _round(v) -> float | None:
    return round(float(v), 1) if v is not None else None


def _core_counts(db: Session, start: datetime, end: datetime) -> dict:
    """ตัวเลขหลักที่ใช้ทั้งเดือนปัจจุบัน เดือนก่อน และแนวโน้ม."""
    in_range = (LoginSession.created_at >= start, LoginSession.created_at < end)
    base = db.query(LoginSession).filter(*in_range)

    total = base.count()
    unique_users = (
        db.query(func.count(distinct(LoginSession.user_id))).filter(*in_range).scalar()
        or 0
    )
    blocked = base.filter(LoginSession.decision.in_(_BLOCKED_DECISIONS)).count()
    challenged = base.filter(LoginSession.decision.in_(_CHALLENGED_DECISIONS)).count()
    incidents = base.filter(
        or_(
            LoginSession.decision.in_(INCIDENT_DECISIONS),
            LoginSession.is_attack_ip.is_(True),
            LoginSession.risk_score >= INCIDENT_RISK_SCORE_MIN,
        )
    ).count()
    return {
        "total": total,
        "unique_users": int(unique_users),
        "blocked": blocked,
        "challenged": challenged,
        "incidents": incidents,
    }


# ── ส่วนประกอบของรายงาน ─────────────────────────────────────────────────────


def _by_subsystem(db: Session, in_range) -> list[dict]:
    rows = (
        db.query(
            LoginSession.subsystem_id,
            Subsystem.name,
            func.count(LoginSession.id),
            func.count(distinct(LoginSession.user_id)),
            func.sum(case((LoginSession.decision.in_(_BLOCKED_DECISIONS), 1), else_=0)),
            func.sum(
                case((LoginSession.decision.in_(_CHALLENGED_DECISIONS), 1), else_=0)
            ),
        )
        .outerjoin(Subsystem, Subsystem.id == LoginSession.subsystem_id)
        .filter(*in_range)
        .group_by(LoginSession.subsystem_id, Subsystem.name)
        .all()
    )
    out = []
    for sid, name, total, users, blocked, challenged in rows:
        total, blocked = int(total), int(blocked or 0)
        out.append(
            {
                "subsystem_id": str(sid) if sid else None,
                "name": name if sid else HUB_DIRECT_LABEL,
                "total": total,
                "unique_users": int(users),
                "blocked": blocked,
                "challenged": int(challenged or 0),
                "block_rate": _rate(blocked, total),
            }
        )
    return sorted(out, key=lambda x: x["total"], reverse=True)


def _count_by(db: Session, column, in_range, key: str) -> list[dict]:
    rows = (
        db.query(column, func.count(LoginSession.id))
        .filter(*in_range)
        .group_by(column)
        .all()
    )
    return sorted(
        ({key: v, "total": int(c)} for v, c in rows),
        key=lambda x: (-x["total"], str(x[key])),
    )


def _trend(db: Session, year: int, month: int) -> list[dict]:
    months = [(year, month)]
    for _ in range(TREND_MONTHS - 1):
        months.append(previous_month(*months[-1]))
    out = []
    for y, m in reversed(months):
        c = _core_counts(db, *month_range_utc(y, m))
        out.append(
            {
                "month": f"{y:04d}-{m:02d}",
                "logins": c["total"],
                "unique_users": c["unique_users"],
                "blocked": c["blocked"],
                "challenged": c["challenged"],
                "incidents": c["incidents"],
                "block_rate": _rate(c["blocked"], c["total"]),
            }
        )
    return out


def _availability(db: Session, start: datetime, end: datetime) -> dict:
    """ผลสุ่มตรวจสุขภาพจาก snapshot ใน audit_logs (เช้า/บ่าย/เย็น + ที่กดเอง)."""
    rows = (
        db.query(AuditLog.metadata_json)
        .filter(
            AuditLog.action == HEALTH_SUMMARY_ACTION,
            AuditLog.created_at >= start,
            AuditLog.created_at < end,
        )
        .order_by(AuditLog.created_at)
        .all()
    )
    units: dict[str, dict] = {}
    for (meta,) in rows:
        for d in (meta or {}).get("details") or []:
            uid = str(d.get("subsystem_id") or d.get("name"))
            u = units.setdefault(
                uid,
                {
                    "unit_id": uid,
                    "name": d.get("name") or uid,
                    "kind": d.get("kind") or "subsystem",
                    "samples": 0,
                    **{s: 0 for s in HEALTH_STATUSES},
                },
            )
            status = d.get("status")
            u["samples"] += 1
            u[status if status in HEALTH_STATUSES else "unknown"] += 1
    for u in units.values():
        u["ok_pct"] = _rate(u["online"], u["samples"])
    return {
        "samples": len(rows),
        "units": sorted(units.values(), key=lambda u: (u["kind"] != "hub", u["name"])),
    }


def _api_performance(db: Session, start: datetime, end: datetime) -> tuple[dict, list]:
    group_expr = case(
        *[(RequestLog.path.like(pattern), g) for g, _, pattern in API_GROUPS],
        else_=API_OTHER[0],
    )
    sq = (
        db.query(
            group_expr.label("g"),
            RequestLog.duration_ms.label("ms"),
            RequestLog.status_code.label("code"),
        )
        .filter(RequestLog.created_at >= start, RequestLog.created_at < end)
        .subquery()
    )
    aggs = (
        func.count(),
        func.avg(sq.c.ms),
        func.percentile_cont(0.95).within_group(sq.c.ms),
        func.percentile_cont(0.99).within_group(sq.c.ms),
        func.sum(case((sq.c.code >= 500, 1), else_=0)),
    )

    def pack(row) -> dict:
        n, avg, p95, p99, errors = row
        n, errors = int(n or 0), int(errors or 0)
        return {
            "requests": n,
            "avg_ms": _round(avg),
            "p95_ms": _round(p95),
            "p99_ms": _round(p99),
            "server_errors": errors,
            "error_rate": _rate(errors, n),
        }

    overall = pack(db.query(*aggs).one())
    labels = {g: label for g, label, _ in API_GROUPS} | {API_OTHER[0]: API_OTHER[1]}
    order = [g for g, _, _ in API_GROUPS] + [API_OTHER[0]]
    rows = {g: pack(rest) for g, *rest in db.query(sq.c.g, *aggs).group_by(sq.c.g)}
    groups = [
        {"group": g, "label": labels[g], **rows[g]}
        for g in order
        if g in rows and rows[g]["requests"] > 0
    ]
    return overall, groups


def _security(db: Session, start: datetime, end: datetime) -> tuple[list, dict]:
    audit_day = func.date(AuditLog.created_at + BKK_OFFSET)
    audit_rows = (
        db.query(audit_day.label("d"), AuditLog.action, func.count(AuditLog.id))
        .filter(
            AuditLog.created_at >= start,
            AuditLog.created_at < end,
            AuditLog.action.in_(SECURITY_ACTIONS),
        )
        .group_by("d", AuditLog.action)
        .all()
    )
    alert_day = func.date(ApiAlert.created_at + BKK_OFFSET)
    alert_rows = (
        db.query(
            alert_day.label("d"),
            ApiAlert.rule,
            ApiAlert.severity,
            func.count(ApiAlert.id),
        )
        .filter(ApiAlert.created_at >= start, ApiAlert.created_at < end)
        .group_by("d", ApiAlert.rule, ApiAlert.severity)
        .all()
    )

    def iso(d) -> str:
        return d.isoformat() if isinstance(d, date) else str(d)

    events = [
        {
            "date": iso(d),
            "source": "audit",
            "code": action,
            "label": SECURITY_ACTIONS[action][0],
            "severity": SECURITY_ACTIONS[action][1],
            "count": int(c),
        }
        for d, action, c in audit_rows
    ]
    events += [
        {
            "date": iso(d),
            "source": "api_alert",
            "code": rule,
            "label": API_ALERT_LABELS.get(rule, rule),
            "severity": "critical" if sev == "critical" else "warn",
            "count": int(c),
        }
        for d, rule, sev, c in alert_rows
    ]
    events.sort(
        key=lambda e: (e["date"], _SEVERITY_RANK[e["severity"]], e["source"], e["code"])
    )

    alerts = db.query(ApiAlert).filter(
        ApiAlert.created_at >= start, ApiAlert.created_at < end
    )
    summary = {
        "api_alerts": {
            "total": alerts.count(),
            "critical": alerts.filter(ApiAlert.severity == "critical").count(),
            "warning": alerts.filter(ApiAlert.severity == "warning").count(),
            "unresolved": alerts.filter(ApiAlert.resolved.is_(False)).count(),
        },
        "ip_blacklist_added": db.query(IpBlacklist)
        .filter(IpBlacklist.created_at >= start, IpBlacklist.created_at < end)
        .count(),
        "force_logouts": db.query(AuditLog)
        .filter(
            AuditLog.action == "admin_force_logout_user",
            AuditLog.created_at >= start,
            AuditLog.created_at < end,
        )
        .count(),
    }
    return events, summary


def _subsystem_status(db: Session, start: datetime, end: datetime) -> dict:
    """สถานะปัจจุบัน (ณ เวลาที่สร้างรายงาน) + จำนวนที่ลงทะเบียน/อนุมัติในเดือน."""
    counts = dict(
        db.query(Subsystem.status, func.count(Subsystem.id))
        .group_by(Subsystem.status)
        .all()
    )
    return {
        "active": int(counts.get("active", 0)),
        "pending": int(counts.get("pending", 0)),
        "suspended": int(counts.get("suspended", 0)),
        "registered_in_month": db.query(Subsystem)
        .filter(Subsystem.created_at >= start, Subsystem.created_at < end)
        .count(),
        "approved_in_month": db.query(Subsystem)
        .filter(Subsystem.approved_at >= start, Subsystem.approved_at < end)
        .count(),
    }


def _ml_feedback(db: Session, start: datetime, end: datetime) -> dict:
    counts = dict(
        db.query(MLFeedback.label, func.count(MLFeedback.id))
        .filter(MLFeedback.created_at >= start, MLFeedback.created_at < end)
        .group_by(MLFeedback.label)
        .all()
    )
    labeled = int(sum(counts.values()))
    fp = int(counts.get("false_positive", 0))
    return {
        "labeled": labeled,
        "false_positive": fp,
        "true_positive": int(counts.get("true_positive", 0)),
        "normal_confirmed": int(counts.get("normal_confirmed", 0)),
        "fp_rate": _rate(fp, labeled) if labeled >= ML_MIN_LABELS else None,
        "min_labels": ML_MIN_LABELS,
    }


# ── กฎ: ข้อสังเกต / ข้อเสนอแนะ / บทสรุป (pure function — ทดสอบได้โดยไม่ต้องใช้ DB) ──


def build_findings(report: dict) -> list[dict]:
    out: list[dict] = []

    def add(level: str, code: str, text: str, basis: dict) -> None:
        out.append({"level": level, "code": code, "text": text, "basis": basis})

    lg = report["logins"]
    total = lg["total"]
    prev = report["previous"]

    if total == 0:
        add("info", "no_logins", "ไม่มีการเข้าสู่ระบบในเดือนนี้", {})

    pct = report["change_pct"]["logins"]
    if pct is not None and abs(pct) >= LOGINS_CHANGE_PCT:
        add(
            "info",
            "logins_change",
            f"การเข้าสู่ระบบ{'เพิ่มขึ้น' if pct > 0 else 'ลดลง'} {abs(pct)}% จากเดือนก่อน "
            f"({prev['logins_total']:,} → {total:,} ครั้ง)",
            {"change_pct": pct, "previous": prev["logins_total"], "current": total},
        )

    cur_br = _rate(lg["blocked"], total)
    prev_br = _rate(prev["blocked"], prev["logins_total"])
    if (
        cur_br is not None
        and prev_br is not None
        and cur_br - prev_br >= BLOCK_RATE_UP_PP
    ):
        add(
            "warn",
            "block_rate_up",
            f"อัตราการระงับการเข้าสู่ระบบเพิ่มจาก {prev_br}% เป็น {cur_br}%",
            {"current": cur_br, "previous": prev_br},
        )

    for s in report.get("by_subsystem", []):
        br = s.get("block_rate")
        if (
            s["total"] >= SUB_MIN_LOGINS
            and br is not None
            and br >= SUB_BLOCK_RATE_MIN
            and (cur_br is None or br >= 2 * cur_br)
        ):
            add(
                "warn",
                "subsystem_block_rate_high",
                f"{s['name']} มีอัตราการระงับ {br}% สูงกว่าภาพรวม ({cur_br}%)",
                {"subsystem": s["name"], "block_rate": br, "overall": cur_br},
            )

    av = report.get("availability", {"samples": 0, "units": []})
    if av["samples"] == 0:
        add(
            "info",
            "no_health_samples",
            "ไม่มีผลตรวจสุขภาพระบบในเดือนนี้ จึงประเมินความพร้อมใช้งานไม่ได้",
            {},
        )
    for u in av["units"]:
        ok = u["ok_pct"]
        if ok is not None and ok < AVAILABILITY_WARN:
            add(
                "critical" if ok < AVAILABILITY_CRITICAL else "warn",
                "availability_low",
                f"{u['name']} อยู่ในสถานะปกติ {u['online']} จาก {u['samples']} ครั้งที่ตรวจ ({ok}%)",
                {
                    "unit": u["name"],
                    "ok_pct": ok,
                    "samples": u["samples"],
                    "down": u["down"],
                },
            )

    alerts = report.get("security_summary", {}).get("api_alerts", {})
    if alerts.get("critical", 0) > 0:
        add(
            "critical",
            "api_alert_critical",
            f"มีการแจ้งเตือน API ระดับวิกฤต {alerts['critical']} ครั้ง "
            f"(ยังไม่ปิด {alerts.get('unresolved', 0)} รายการจากทั้งหมด {alerts.get('total', 0)})",
            {"critical": alerts["critical"], "unresolved": alerts.get("unresolved", 0)},
        )

    for g in report.get("api_performance", []):
        if (
            g["requests"] >= API_MIN_REQUESTS
            and g["error_rate"] is not None
            and g["error_rate"] >= API_ERROR_RATE
        ):
            add(
                "warn",
                "server_error_rate",
                f"API กลุ่ม {g['label']} มี error ฝั่งเซิร์ฟเวอร์ {g['error_rate']}% "
                f"({g['server_errors']:,} จาก {g['requests']:,} request)",
                {
                    "group": g["label"],
                    "error_rate": g["error_rate"],
                    "requests": g["requests"],
                },
            )

    ml = report.get("ml_feedback")
    if ml and ml["labeled"] < ml["min_labels"]:
        add(
            "info",
            "ml_labels_insufficient",
            f"ผลการตัดสินที่ตรวจยืนยันแล้ว (label) มี {ml['labeled']} รายการ ต่ำกว่า "
            f"{ml['min_labels']} รายการ จึงยังคำนวณอัตรา false positive ไม่ได้",
            {"labeled": ml["labeled"], "min_labels": ml["min_labels"]},
        )

    foreign = [
        g for g in report.get("geo", []) if g["country"] and g["country"] != "TH"
    ]
    if foreign:
        n = sum(g["total"] for g in foreign)
        add(
            "info",
            "foreign_logins",
            f"มีการเข้าสู่ระบบจากต่างประเทศ {n:,} ครั้ง "
            f"({', '.join(g['country'] for g in foreign)})",
            {"total": n, "countries": [g["country"] for g in foreign]},
        )

    return sorted(out, key=lambda f: _SEVERITY_RANK[f["level"]])


_RECOMMENDATIONS = {
    "availability_low": (
        "high",
        "ตรวจสอบสาเหตุที่ระบบไม่พร้อมใช้งานและตั้งการแจ้งเตือนเมื่อสถานะผิดปกติ",
    ),
    "api_alert_critical": (
        "high",
        "ตรวจสอบ IP ที่ถูกแจ้งเตือนระดับวิกฤต และพิจารณาเพิ่มใน IP blacklist",
    ),
    "server_error_rate": (
        "medium",
        "ตรวจสอบ error ฝั่งเซิร์ฟเวอร์ของกลุ่ม API ที่มีอัตรา error สูง",
    ),
    "subsystem_block_rate_high": (
        "medium",
        "ทบทวนรายชื่อผู้มีสิทธิ์และนโยบายการเข้าถึงของระบบย่อยที่มีอัตราการระงับสูง",
    ),
    "block_rate_up": (
        "medium",
        "ตรวจสอบรายการที่ถูกระงับในหน้า Incidents ว่าเป็นการโจมตีจริงหรือระงับผิด",
    ),
    "ml_labels_insufficient": (
        "low",
        "เพิ่มการยืนยันผลการตัดสิน (label) ในหน้า ML เพื่อให้วัดอัตรา false positive ได้",
    ),
    "no_health_samples": (
        "low",
        "ตรวจสอบว่าตัวตรวจสุขภาพระบบ (health scheduler) ทำงานตามรอบเวลา",
    ),
}


def build_recommendations(report: dict, findings: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for f in findings:
        if f["code"] in _RECOMMENDATIONS:
            grouped.setdefault(f["code"], []).append(f)

    out = []
    for code, items in grouped.items():
        priority, text = _RECOMMENDATIONS[code]
        subjects = [
            f["basis"].get("unit")
            or f["basis"].get("subsystem")
            or f["basis"].get("group")
            for f in items
        ]
        subjects = [s for s in subjects if s]
        out.append(
            {
                "priority": priority,
                "code": code,
                "text": text + (f": {', '.join(subjects)}" if subjects else ""),
                "reason": " · ".join(f["text"] for f in items),
            }
        )

    pending = report.get("subsystem_status", {}).get("pending", 0)
    if pending > 0:
        out.append(
            {
                "priority": "medium",
                "code": "pending_subsystems",
                "text": f"พิจารณาคำขอลงทะเบียนระบบย่อยที่รออนุมัติ {pending} รายการ",
                "reason": f"มีคำขอค้างอยู่ {pending} รายการ ณ เวลาที่สร้างรายงาน",
            }
        )
    return sorted(out, key=lambda r: _PRIORITY_RANK[r["priority"]])


def _group_by_code(findings) -> list[str]:
    """ข้อสังเกตชนิดเดียวกันรวมเป็น 1 เรื่อง: ข้อความของรายการแรก + "(และอีก N รายการ)"."""
    groups: dict[str, list[str]] = {}
    for f in findings:
        groups.setdefault(f["code"], []).append(f["text"])
    return [
        texts[0] + (f" (และอีก {len(texts) - 1} รายการ)" if len(texts) > 1 else "")
        for texts in groups.values()
    ]


def build_narrative(report: dict, findings: list[dict]) -> dict:
    name = thai_month_name(report["month"])
    lg = report["logins"]
    total = lg["total"]

    if total == 0:
        summary = f"เดือน{name} ไม่มีการเข้าสู่ระบบ"
    else:
        summary = (
            f"เดือน{name} มีการเข้าสู่ระบบรวม {total:,} ครั้ง จากผู้ใช้ {lg['unique_users']:,} คน "
            f"ระบบระงับ {lg['blocked']:,} ครั้ง ({_rate(lg['blocked'], total)}%) "
            f"และให้ยืนยันตัวตนเพิ่ม {lg['challenged']:,} ครั้ง ({_rate(lg['challenged'], total)}%)"
        )
        pct = report["change_pct"]["logins"]
        if pct is not None:
            summary += (
                f" การเข้าสู่ระบบ{'เพิ่มขึ้น' if pct >= 0 else 'ลดลง'} {abs(pct)}% จากเดือนก่อน"
            )

    av = report.get("availability", {"samples": 0, "units": []})
    samples = sum(u["samples"] for u in av["units"])
    if samples:
        ok = _rate(sum(u["online"] for u in av["units"]), samples)
        summary += (
            f" ผลตรวจสุขภาพระบบ {av['samples']} รอบ พบสถานะปกติ {ok}% ของการตรวจทั้งหมด"
        )

    critical = _group_by_code(f for f in findings if f["level"] == "critical")
    warns = _group_by_code(f for f in findings if f["level"] == "warn")
    if critical:
        conclusion = f"พบประเด็นที่ควรดำเนินการเร่งด่วน {len(critical)} เรื่อง: " + "; ".join(
            critical
        )
    elif warns:
        conclusion = (
            f"ไม่พบประเด็นเร่งด่วน แต่มีเรื่องที่ควรติดตาม {len(warns)} เรื่อง: " + "; ".join(warns)
        )
    else:
        conclusion = "ไม่พบประเด็นเร่งด่วนหรือความผิดปกติที่ต้องติดตามในเดือนนี้"
    return {"summary": summary, "conclusion": conclusion}


# ── รวมรายงาน ────────────────────────────────────────────────────────────────


def build_monthly_report(db: Session, year: int, month: int) -> dict:
    start, end = month_range_utc(year, month)
    in_range = (LoginSession.created_at >= start, LoginSession.created_at < end)
    cur = _core_counts(db, start, end)

    # ── ความเสี่ยง ──
    avg_risk = (
        db.query(func.avg(LoginSession.risk_score))
        .filter(*in_range, LoginSession.risk_score.isnot(None))
        .scalar()
    )
    attack_ip = (
        db.query(LoginSession)
        .filter(*in_range, LoginSession.is_attack_ip.is_(True))
        .count()
    )

    # ── รายวันตามเวลาไทย (ครบทุกวันของเดือน แม้ไม่มีข้อมูล) ──
    bkk_day = func.date(LoginSession.created_at + BKK_OFFSET)
    day_rows = (
        db.query(
            bkk_day.label("d"),
            func.count(LoginSession.id),
            func.sum(
                case((LoginSession.decision.in_(_CHALLENGED_DECISIONS), 1), else_=0)
            ),
            func.sum(case((LoginSession.decision.in_(_BLOCKED_DECISIONS), 1), else_=0)),
        )
        .filter(*in_range)
        .group_by("d")
        .all()
    )
    by_day = {
        (d if isinstance(d, date) else date.fromisoformat(str(d))): (
            int(c or 0),
            int(ch or 0),
            int(bl or 0),
        )
        for d, c, ch, bl in day_rows
    }
    n_days = calendar.monthrange(year, month)[1]
    daily = []
    for day in range(1, n_days + 1):
        dd = date(year, month, day)
        c, ch, bl = by_day.get(dd, (0, 0, 0))
        daily.append(
            {"date": dd.isoformat(), "total": c, "challenged": ch, "blocked": bl}
        )

    # ── อื่นๆ ──
    new_users = (
        db.query(User).filter(User.created_at >= start, User.created_at < end).count()
    )
    audit_events = (
        db.query(AuditLog)
        .filter(AuditLog.created_at >= start, AuditLog.created_at < end)
        .count()
    )

    # ── เดือนก่อน ──
    py, pm = previous_month(year, month)
    prev = _core_counts(db, *month_range_utc(py, pm))

    api_overall, api_performance = _api_performance(db, start, end)
    security_events, security_summary = _security(db, start, end)

    total = cur["total"]
    report = {
        "month": f"{year:04d}-{month:02d}",
        "range": {
            "from": start.isoformat() + "Z",
            "to": end.isoformat() + "Z",
            "timezone": TIMEZONE,
        },
        "logins": {
            "total": total,
            "unique_users": cur["unique_users"],
            "allowed": max(total - cur["blocked"] - cur["challenged"], 0),
            "challenged": cur["challenged"],
            "blocked": cur["blocked"],
            "success_rate": round((total - cur["blocked"]) / total * 100, 1)
            if total
            else None,
        },
        "risk": {
            "avg": round(float(avg_risk), 3) if avg_risk is not None else None,
            "incidents": cur["incidents"],
            "attack_ip": attack_ip,
        },
        "users": {"new": new_users},
        "audit": {"events": audit_events},
        "daily": daily,
        "by_subsystem": _by_subsystem(db, in_range),
        "login_methods": _count_by(db, LoginSession.login_method, in_range, "method"),
        "geo": _count_by(db, LoginSession.geo_country, in_range, "country"),
        "trend": _trend(db, year, month),
        "availability": _availability(db, start, end),
        "api_overall": api_overall,
        "api_performance": api_performance,
        "security_events": security_events,
        "security_summary": security_summary,
        "subsystem_status": _subsystem_status(db, start, end),
        "ml_feedback": _ml_feedback(db, start, end),
        "previous": {
            "month": f"{py:04d}-{pm:02d}",
            "logins_total": prev["total"],
            "unique_users": prev["unique_users"],
            "blocked": prev["blocked"],
            "challenged": prev["challenged"],
            "incidents": prev["incidents"],
        },
        "change_pct": {
            "logins": _pct_change(total, prev["total"]),
            "unique_users": _pct_change(cur["unique_users"], prev["unique_users"]),
            "blocked": _pct_change(cur["blocked"], prev["blocked"]),
            "challenged": _pct_change(cur["challenged"], prev["challenged"]),
            "incidents": _pct_change(cur["incidents"], prev["incidents"]),
        },
        "unavailable": list(UNAVAILABLE),
    }
    findings = build_findings(report)
    report["findings"] = findings
    report["recommendations"] = build_recommendations(report, findings)
    report["narrative"] = build_narrative(report, findings)
    return report
