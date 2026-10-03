"""Tests — รายงานรายเดือนสำหรับผู้บริหาร (GET /admin/reports/monthly?month=YYYY-MM).

ความต้องการ:
  - เลือกเดือนตามปฏิทิน "เวลาไทย" (Asia/Bangkok, UTC+7) ไม่ใช่ย้อนหลัง N ชม.
  - เทียบกับเดือนก่อนหน้า (month-over-month)
  - ทุกค่าต้องมาจาก DB จริง — ไม่มีข้อมูล = 0 / None ห้ามค่าสมมติ
  - metric ที่ระบบไม่มีข้อมูลย้อนหลังพอ (uptime ระบบย่อย: health history อยู่ใน
    Redis แค่ 288 จุด ≈ 24 ชม.) ต้องประกาศใน `unavailable` แทนการเดาตัวเลข

ข้อมูลทดสอบ: สร้าง LoginSession ในเดือน ก.พ./ม.ค. 2001 (ไม่มีข้อมูลจริงปน)
แล้วลบทิ้งท้ายเทสต์ — assert ตัวเลขได้เป๊ะ

รัน:
  docker compose exec hub-backend pytest tests/test_monthly_report.py -v
"""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

from app.models import (
    ApiAlert,
    AuditLog,
    IpBlacklist,
    LoginSession,
    MLFeedback,
    RequestLog,
)
from app.services.monthly_report import (
    build_findings,
    build_monthly_report,
    build_narrative,
    build_recommendations,
)

URL = "/admin/reports/monthly"


# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def cleanup_sessions(db):
    """เก็บ id ของ session ที่เทสต์สร้าง แล้วลบทิ้งท้ายเทสต์ (แม้ fail)."""
    ids: list = []
    yield ids
    if ids:
        db.query(LoginSession).filter(LoginSession.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.commit()


def _mk(db, ids, user, created_utc: datetime, **kw):
    """สร้าง LoginSession ณ เวลา UTC ที่กำหนด (DB เก็บ naive UTC)."""
    defaults = dict(
        user_id=user.id,
        subsystem_id=None,
        ip="203.0.113.10",
        decision="allow",
        login_method="google",
        created_at=created_utc,
        last_seen_at=created_utc,
    )
    defaults.update(kw)
    s = LoginSession(**defaults)
    db.add(s)
    db.commit()
    ids.append(s.id)
    return s


@pytest.fixture
def seeded_feb_2001(db, cleanup_sessions, admin_user, teacher_user):
    """
    ใช้ admin + teacher เป็นผู้ใช้ 2 คนที่ต่างกัน (ไม่พึ่ง student — dev DB อาจไม่เหลือ
    student active หลังเทสต์ lifecycle ทำให้เทสต์ถูก skip เงียบๆ)

    ก.พ. 2001 (เวลาไทย) — 4 session นับ + 1 session ขอบเดือนที่ต้องไม่นับ
    ม.ค. 2001 (เวลาไทย) — 2 session สำหรับเทียบเดือนก่อน
    """
    ids = cleanup_sessions
    # ── ก.พ. ──
    _mk(
        db,
        ids,
        admin_user,
        datetime(2001, 2, 10, 3, 0),
        decision="allow",
        risk_score=0.10,
    )
    _mk(
        db,
        ids,
        teacher_user,
        datetime(2001, 2, 10, 4, 0),
        decision="would_challenge",
        risk_score=0.62,
    )
    _mk(
        db,
        ids,
        teacher_user,
        datetime(2001, 2, 15, 5, 0),
        decision="block",
        risk_score=0.90,
        is_attack_ip=True,
    )
    # ขอบต้นเดือน: UTC 31 ม.ค. 17:00 = ไทย 1 ก.พ. 00:00 → ต้องนับเป็น ก.พ.
    _mk(
        db,
        ids,
        admin_user,
        datetime(2001, 1, 31, 17, 0),
        decision="allow",
        risk_score=None,
    )
    # ขอบท้ายเดือน: UTC 28 ก.พ. 17:00 = ไทย 1 มี.ค. 00:00 → ต้องไม่นับเป็น ก.พ.
    _mk(
        db,
        ids,
        admin_user,
        datetime(2001, 2, 28, 17, 0),
        decision="allow",
        risk_score=0.20,
    )
    # ── ม.ค. ──
    _mk(
        db,
        ids,
        admin_user,
        datetime(2001, 1, 15, 3, 0),
        decision="allow",
        risk_score=0.10,
    )
    _mk(
        db,
        ids,
        teacher_user,
        datetime(2001, 1, 20, 3, 0),
        decision="block",
        risk_score=0.95,
    )
    return ids


# ── RBAC / validation ─────────────────────────────────────────────────────


@pytest.mark.smoke
def test_requires_auth(client):
    """ไม่มี token → 401/403 (B1: ทุก endpoint ต้องมี Depends)."""
    r = client.get(f"{URL}?month=2001-02")
    assert r.status_code in (401, 403)


def test_non_admin_forbidden(client, teacher_token, auth_headers):
    """ไม่ใช่ hub admin (teacher) → เรียกไม่ได้ — ใช้ teacher เพราะ dev DB อาจไม่มี student active."""
    r = client.get(f"{URL}?month=2001-02", headers=auth_headers(teacher_token))
    assert r.status_code in (401, 403)


@pytest.mark.parametrize("bad", ["2001-13", "2001-00", "abc", "2001-2", "01-2001", ""])
def test_invalid_month_rejected(client, admin_token, auth_headers, bad):
    """เดือนผิดรูปแบบ → 422 ไม่ใช่ 500."""
    r = client.get(f"{URL}?month={bad}", headers=auth_headers(admin_token))
    assert r.status_code == 422, f"month={bad!r} ได้ {r.status_code}"


# ── ตัวเลขจริงจากข้อมูลที่ใส่ ───────────────────────────────────────────


def test_structure(client, admin_token, auth_headers, seeded_feb_2001):
    d = client.get(f"{URL}?month=2001-02", headers=auth_headers(admin_token)).json()
    assert {
        "month",
        "range",
        "logins",
        "risk",
        "users",
        "audit",
        "daily",
        "by_subsystem",
        "previous",
        "change_pct",
        "unavailable",
    }.issubset(d)
    assert d["month"] == "2001-02"
    assert d["range"]["timezone"] == "Asia/Bangkok"
    assert {
        "total",
        "unique_users",
        "allowed",
        "challenged",
        "blocked",
        "success_rate",
    }.issubset(d["logins"])
    assert {"avg", "incidents", "attack_ip"}.issubset(d["risk"])


def test_login_counts_exact(client, admin_token, auth_headers, seeded_feb_2001):
    d = client.get(f"{URL}?month=2001-02", headers=auth_headers(admin_token)).json()
    lg = d["logins"]
    assert lg["total"] == 4, "ต้องนับ 3 session กลางเดือน + 1 ขอบต้นเดือน (ไม่รวมขอบท้าย)"
    assert lg["unique_users"] == 2
    assert lg["blocked"] == 1
    assert lg["challenged"] == 1
    assert lg["allowed"] == 2
    assert lg["success_rate"] == pytest.approx(75.0)


def test_bangkok_month_boundaries(client, admin_token, auth_headers, seeded_feb_2001):
    """ขอบเดือนต้องตัดตามเวลาไทย ไม่ใช่ UTC."""
    d = client.get(f"{URL}?month=2001-02", headers=auth_headers(admin_token)).json()
    days = {x["date"]: x for x in d["daily"]}
    assert len(d["daily"]) == 28, "ก.พ. 2001 มี 28 วัน — ต้องมีครบทุกวันแม้ไม่มีข้อมูล"
    assert days["2001-02-01"]["total"] == 1, "UTC 31 ม.ค. 17:00 = ไทย 1 ก.พ. 00:00"
    assert days["2001-02-10"]["total"] == 2
    assert "2001-03-01" not in days
    assert sum(x["total"] for x in d["daily"]) == d["logins"]["total"]


def test_risk_and_incidents(client, admin_token, auth_headers, seeded_feb_2001):
    d = client.get(f"{URL}?month=2001-02", headers=auth_headers(admin_token)).json()
    rk = d["risk"]
    # ค่าเฉลี่ยจาก session ที่มี risk_score เท่านั้น (0.10, 0.62, 0.90) — ตัดตัวที่เป็น None
    assert rk["avg"] == pytest.approx(0.54, abs=0.005)
    # นิยามเดียวกับหน้า Incidents: decision ใน INCIDENT_DECISIONS / attack IP / risk >= 0.5
    assert rk["incidents"] == 2
    assert rk["attack_ip"] == 1


def test_month_over_month(client, admin_token, auth_headers, seeded_feb_2001):
    d = client.get(f"{URL}?month=2001-02", headers=auth_headers(admin_token)).json()
    assert d["previous"]["month"] == "2001-01"
    assert d["previous"]["logins_total"] == 2
    assert d["previous"]["blocked"] == 1
    assert d["change_pct"]["logins"] == pytest.approx(100.0)
    assert d["change_pct"]["blocked"] == pytest.approx(0.0)


def test_by_subsystem_sums_to_total(client, admin_token, auth_headers, seeded_feb_2001):
    d = client.get(f"{URL}?month=2001-02", headers=auth_headers(admin_token)).json()
    assert sum(x["total"] for x in d["by_subsystem"]) == d["logins"]["total"]


def test_empty_month_is_honest(client, admin_token, auth_headers):
    """เดือนที่ไม่มีข้อมูล → 0 / None ไม่ใช่ค่าสมมติ และหารศูนย์ไม่ระเบิด."""
    d = client.get(f"{URL}?month=1999-05", headers=auth_headers(admin_token)).json()
    assert d["logins"]["total"] == 0
    assert d["logins"]["success_rate"] is None
    assert d["risk"]["avg"] is None
    assert d["change_pct"]["logins"] is None, "เดือนก่อนเป็น 0 → คำนวณ % ไม่ได้ ต้องเป็น None"
    assert len(d["daily"]) == 31


def test_uptime_declared_unavailable(client, admin_token, auth_headers):
    """uptime จริง + CPU/Memory ไม่มีข้อมูลรองรับ → ต้องประกาศ ไม่ใส่ตัวเลข.

    availability (ผลสุ่มตรวจ 3 ครั้ง/วัน) มีได้ แต่ห้ามตั้งชื่อว่า uptime
    """
    d = client.get(f"{URL}?month=2001-02", headers=auth_headers(admin_token)).json()
    assert "subsystem_uptime" in d["unavailable"]
    assert "resource_usage" in d["unavailable"]
    assert "uptime" not in d, "ห้ามมีฟิลด์ uptime ที่ไม่มีข้อมูลจริงรองรับ"


# ══════════════════════════════════════════════════════════════════════════
# รายงานฉบับเต็ม — ส่วนที่เพิ่มตามแม่แบบรายงานประจำเดือน
# ══════════════════════════════════════════════════════════════════════════


def _health_meta(details: list[dict]) -> dict:
    return {"slot": "morning", "total": len(details), "details": details}


@pytest.fixture
def seeded_full_feb_2001(db, seeded_feb_2001, admin_user):
    """ข้อมูลเสริมใน ก.พ. 2001 (+ ตัวหลอกนอกเดือน) — ลบทิ้งท้ายเทสต์.

    health snapshot 2 ครั้ง: hub ปกติทั้งคู่ · sub-x ล่ม 1 ครั้ง → 50%
    audit ความปลอดภัย: ip_blacklist_added ×2 (วันเดียวกัน) + force logout ×1
    api alert: critical 1 + warning 1
    request_logs: /oauth/token 100/200/300/400 ms (1 ตัวเป็น 500) + /admin/users 50 ms
    """
    rows: list = []

    def add(obj):
        db.add(obj)
        db.commit()
        rows.append(obj)
        return obj

    hub_ok = {"subsystem_id": "hub", "name": "Hub", "kind": "hub", "status": "online"}
    sub_down = {
        "subsystem_id": "sub-x",
        "name": "SubX",
        "kind": "subsystem",
        "status": "down",
    }
    sub_ok = dict(sub_down, status="online")
    add(
        AuditLog(
            action="subsystem_health_summary",
            target_type="system",
            metadata_json=_health_meta([hub_ok, sub_down]),
            created_at=datetime(2001, 2, 5, 1, 0),
        )
    )
    add(
        AuditLog(
            action="subsystem_health_summary",
            target_type="system",
            metadata_json=_health_meta([hub_ok, sub_ok]),
            created_at=datetime(2001, 2, 6, 1, 0),
        )
    )
    # นอกเดือน (ไทย 1 มี.ค. 08:00) → ต้องไม่นับ
    add(
        AuditLog(
            action="subsystem_health_summary",
            target_type="system",
            metadata_json=_health_meta([dict(hub_ok, status="down")]),
            created_at=datetime(2001, 3, 1, 1, 0),
        )
    )
    for h in (3, 5):
        add(
            AuditLog(
                action="ip_blacklist_added",
                target_type="ip",
                created_at=datetime(2001, 2, 7, h, 0),
            )
        )
    add(
        AuditLog(
            action="admin_force_logout_user",
            target_type="user",
            created_at=datetime(2001, 2, 8, 3, 0),
        )
    )
    # ไม่ใช่เหตุการณ์ความปลอดภัย → ต้องไม่อยู่ใน timeline
    add(AuditLog(action="hub_login_success", created_at=datetime(2001, 2, 8, 4, 0)))

    add(
        ApiAlert(
            rule="unauthorized_probing",
            severity="critical",
            ip="198.51.100.7",
            detail={},
            resolved=False,
            created_at=datetime(2001, 2, 9, 3, 0),
        )
    )
    add(
        ApiAlert(
            rule="high_error_rate",
            severity="warning",
            ip="198.51.100.8",
            detail={},
            resolved=False,
            created_at=datetime(2001, 2, 9, 4, 0),
        )
    )

    for ms, code in ((100, 200), (200, 200), (300, 200), (400, 500)):
        add(
            RequestLog(
                method="POST",
                path="/oauth/token",
                status_code=code,
                duration_ms=ms,
                created_at=datetime(2001, 2, 11, 3, 0),
            )
        )
    add(
        RequestLog(
            method="GET",
            path="/admin/users",
            status_code=200,
            duration_ms=50,
            created_at=datetime(2001, 2, 11, 3, 0),
        )
    )
    add(  # นอกเดือน
        RequestLog(
            method="POST",
            path="/oauth/token",
            status_code=500,
            duration_ms=9000,
            created_at=datetime(2001, 3, 2, 3, 0),
        )
    )

    add(IpBlacklist(ip_address="198.51.100.250", created_at=datetime(2001, 2, 7, 3, 0)))
    add(
        MLFeedback(
            session_id=seeded_feb_2001[0],
            label="false_positive",
            marked_by=admin_user.id,
            created_at=datetime(2001, 2, 12, 3, 0),
        )
    )

    yield rows
    # ลบย้อนลำดับ (MLFeedback อ้าง login_sessions — ต้องลบก่อน session)
    for obj in reversed(rows):
        db.delete(obj)
    db.commit()


def _get(client, admin_token, auth_headers, month="2001-02"):
    r = client.get(f"{URL}?month={month}", headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    return r.json()


def test_full_structure(client, admin_token, auth_headers, seeded_full_feb_2001):
    d = _get(client, admin_token, auth_headers)
    assert {
        "login_methods",
        "geo",
        "trend",
        "availability",
        "api_overall",
        "api_performance",
        "security_events",
        "security_summary",
        "subsystem_status",
        "ml_feedback",
        "findings",
        "recommendations",
        "narrative",
    }.issubset(d)


def test_by_subsystem_detail(client, admin_token, auth_headers, seeded_full_feb_2001):
    d = _get(client, admin_token, auth_headers)
    (hub,) = d["by_subsystem"]
    assert hub["subsystem_id"] is None
    assert hub["total"] == 4
    assert hub["unique_users"] == 2
    assert hub["blocked"] == 1
    assert hub["challenged"] == 1
    assert hub["block_rate"] == pytest.approx(25.0)


def test_login_methods_and_geo(client, admin_token, auth_headers, seeded_full_feb_2001):
    d = _get(client, admin_token, auth_headers)
    assert d["login_methods"] == [{"method": "google", "total": 4}]
    # ไม่มี geo_country → country เป็น None (ไม่เดาว่าเป็นไทย)
    assert d["geo"] == [{"country": None, "total": 4}]


def test_trend_six_months(client, admin_token, auth_headers, seeded_full_feb_2001):
    d = _get(client, admin_token, auth_headers)
    t = d["trend"]
    assert [x["month"] for x in t] == [
        "2000-09",
        "2000-10",
        "2000-11",
        "2000-12",
        "2001-01",
        "2001-02",
    ], "6 เดือนเรียงจากเก่าไปใหม่ จบที่เดือนที่เลือก"
    assert t[-1]["logins"] == 4 and t[-1]["blocked"] == 1
    assert t[-1]["block_rate"] == pytest.approx(25.0)
    assert t[-2]["logins"] == 2
    assert t[0]["logins"] == 0 and t[0]["block_rate"] is None


def test_availability_from_health_snapshots(
    client, admin_token, auth_headers, seeded_full_feb_2001
):
    d = _get(client, admin_token, auth_headers)
    av = d["availability"]
    assert av["samples"] == 2, "นับเฉพาะ snapshot ในเดือน (ตัว 1 มี.ค. ไม่นับ)"
    units = {u["unit_id"]: u for u in av["units"]}
    assert units["hub"]["samples"] == 2
    assert units["hub"]["online"] == 2
    assert units["hub"]["ok_pct"] == pytest.approx(100.0)
    assert units["sub-x"]["down"] == 1
    assert units["sub-x"]["ok_pct"] == pytest.approx(50.0)


def test_api_performance(client, admin_token, auth_headers, seeded_full_feb_2001):
    d = _get(client, admin_token, auth_headers)
    groups = {g["group"]: g for g in d["api_performance"]}
    oauth = groups["oauth"]
    assert oauth["requests"] == 4, "request นอกเดือนต้องไม่นับ"
    assert oauth["avg_ms"] == pytest.approx(250.0)
    # percentile_cont (linear): 0.95 × 3 = 2.85 → 300 + 0.85 × 100
    assert oauth["p95_ms"] == pytest.approx(385.0)
    assert oauth["p99_ms"] == pytest.approx(397.0)
    assert oauth["server_errors"] == 1
    assert oauth["error_rate"] == pytest.approx(25.0)
    assert groups["admin"]["requests"] == 1
    assert all(g["requests"] > 0 for g in d["api_performance"]), "ไม่แสดงกลุ่มที่ไม่มี request"
    assert d["api_overall"]["requests"] == 5


def test_security_events_and_summary(
    client, admin_token, auth_headers, seeded_full_feb_2001
):
    d = _get(client, admin_token, auth_headers)
    ev = d["security_events"]
    keys = {(e["date"], e["source"], e["code"]): e for e in ev}
    bl = keys[("2001-02-07", "audit", "ip_blacklist_added")]
    assert bl["count"] == 2, "เหตุการณ์ชนิดเดียวกันในวันเดียวกันรวมเป็นแถวเดียว"
    assert keys[("2001-02-08", "audit", "admin_force_logout_user")]["count"] == 1
    probe = keys[("2001-02-09", "api_alert", "unauthorized_probing")]
    assert probe["severity"] == "critical"
    assert all(e["code"] != "hub_login_success" for e in ev)
    assert all(e["label"] for e in ev), "ทุกแถวต้องมีคำอธิบายภาษาคน"
    assert [e["date"] for e in ev] == sorted(e["date"] for e in ev)

    s = d["security_summary"]
    assert s["api_alerts"] == {"total": 2, "critical": 1, "warning": 1, "unresolved": 2}
    assert s["ip_blacklist_added"] == 1
    assert s["force_logouts"] == 1


def test_subsystem_status_and_ml_feedback(
    client, admin_token, auth_headers, seeded_full_feb_2001
):
    d = _get(client, admin_token, auth_headers)
    st = d["subsystem_status"]
    assert {
        "active",
        "pending",
        "suspended",
        "registered_in_month",
        "approved_in_month",
    } <= set(st)
    assert st["registered_in_month"] == 0
    ml = d["ml_feedback"]
    assert ml["labeled"] == 1
    assert ml["false_positive"] == 1
    assert ml["fp_rate"] is None, "label น้อยกว่าเกณฑ์ → ห้ามคำนวณ FP rate"
    assert ml["min_labels"] >= 30


def test_findings_and_recommendations_from_real_data(
    client, admin_token, auth_headers, seeded_full_feb_2001
):
    d = _get(client, admin_token, auth_headers)
    codes = {f["code"]: f for f in d["findings"]}
    assert codes["availability_low"]["level"] == "critical"
    assert codes["availability_low"]["basis"]["unit"] == "SubX"
    assert "api_alert_critical" in codes
    assert "ml_labels_insufficient" in codes
    assert "logins_change" in codes
    assert "block_rate_up" not in codes, "block rate ลดจาก 50% เป็น 25% → ไม่ใช่ขาขึ้น"
    for f in d["findings"]:
        assert f["level"] in ("critical", "warn", "info") and f["text"] and "basis" in f

    recs = d["recommendations"]
    assert recs, "มีประเด็น critical ต้องมีข้อเสนอแนะ"
    order = {"high": 0, "medium": 1, "low": 2}
    assert [order[r["priority"]] for r in recs] == sorted(
        order[r["priority"]] for r in recs
    )
    high = {r["code"] for r in recs if r["priority"] == "high"}
    assert {"availability_low", "api_alert_critical"} <= high
    assert all(r["text"] and r["reason"] for r in recs)


def test_narrative_uses_real_numbers(
    client, admin_token, auth_headers, seeded_full_feb_2001
):
    d = _get(client, admin_token, auth_headers)
    n = d["narrative"]
    assert "กุมภาพันธ์" in n["summary"]
    assert "4 ครั้ง" in n["summary"]
    assert n["conclusion"]


def test_empty_month_full_report_is_honest(client, admin_token, auth_headers):
    d = _get(client, admin_token, auth_headers, month="1999-05")
    assert d["availability"] == {"samples": 0, "units": []}
    assert d["api_performance"] == []
    assert d["api_overall"]["requests"] == 0
    assert d["api_overall"]["avg_ms"] is None
    assert d["security_events"] == []
    assert len(d["trend"]) == 6 and all(x["logins"] == 0 for x in d["trend"])
    codes = {f["code"] for f in d["findings"]}
    assert {"no_logins", "no_health_samples"} <= codes
    assert "ไม่มีการเข้าสู่ระบบ" in d["narrative"]["summary"]


# ── กฎ findings (pure function — ป้อน report ที่แก้ค่าเอง) ───────────────────


@pytest.fixture
def empty_report(db):
    return build_monthly_report(db, 1999, 5)


def _with(report, **changes):
    r = copy.deepcopy(report)
    for path, value in changes.items():
        node = r
        *parents, leaf = path.split("__")
        for p in parents:
            node = node[p]
        node[leaf] = value
    return r


def test_rule_subsystem_block_rate_high(empty_report):
    r = _with(
        empty_report,
        logins__total=100,
        logins__blocked=2,
        by_subsystem=[
            {
                "subsystem_id": "a",
                "name": "A",
                "total": 80,
                "unique_users": 5,
                "blocked": 0,
                "challenged": 0,
                "block_rate": 0.0,
            },
            {
                "subsystem_id": "b",
                "name": "B",
                "total": 20,
                "unique_users": 3,
                "blocked": 2,
                "challenged": 0,
                "block_rate": 10.0,
            },
        ],
    )
    f = {x["code"]: x for x in build_findings(r)}
    assert f["subsystem_block_rate_high"]["basis"]["subsystem"] == "B"


def test_rule_subsystem_block_rate_ignores_tiny_samples(empty_report):
    r = _with(
        empty_report,
        logins__total=100,
        logins__blocked=1,
        by_subsystem=[
            {
                "subsystem_id": "b",
                "name": "B",
                "total": 3,
                "unique_users": 1,
                "blocked": 1,
                "challenged": 0,
                "block_rate": 33.3,
            },
        ],
    )
    assert "subsystem_block_rate_high" not in {x["code"] for x in build_findings(r)}


def test_rule_server_error_rate(empty_report):
    grp = {
        "group": "oauth",
        "label": "OAuth",
        "requests": 200,
        "avg_ms": 90.0,
        "p95_ms": 150.0,
        "p99_ms": 300.0,
        "server_errors": 4,
        "error_rate": 2.0,
    }
    r = _with(empty_report, api_performance=[grp])
    f = {x["code"]: x for x in build_findings(r)}
    assert f["server_error_rate"]["level"] == "warn"
    recs = build_recommendations(r, build_findings(r))
    assert any(
        x["code"] == "server_error_rate" and x["priority"] == "medium" for x in recs
    )


def test_rule_block_rate_up(empty_report):
    r = _with(
        empty_report,
        logins__total=100,
        logins__blocked=5,
        previous__logins_total=100,
        previous__blocked=2,
    )
    f = {x["code"]: x for x in build_findings(r)}
    assert f["block_rate_up"]["basis"] == {"current": 5.0, "previous": 2.0}


def test_rule_pending_subsystems_recommendation(empty_report):
    r = _with(empty_report, subsystem_status__pending=2)
    recs = build_recommendations(r, build_findings(r))
    assert any(x["code"] == "pending_subsystems" for x in recs)


def test_narrative_no_urgent_issue(empty_report):
    r = _with(empty_report, logins__total=10, logins__unique_users=3)
    n = build_narrative(r, [])
    assert "10 ครั้ง" in n["summary"]
    assert "ไม่พบประเด็นเร่งด่วน" in n["conclusion"]


def test_conclusion_groups_repeated_findings(empty_report):
    """ข้อสังเกตชนิดเดียวกันหลายรายการ (เช่น ระบบล่มพร้อมกัน 3 ระบบ) → บทสรุปนับเป็น 1 เรื่อง."""
    findings = [
        {
            "level": "critical",
            "code": "availability_low",
            "text": f"S{i} อยู่ในสถานะปกติ 0 จาก 10 ครั้งที่ตรวจ (0.0%)",
            "basis": {"unit": f"S{i}"},
        }
        for i in range(3)
    ]
    c = build_narrative(empty_report, findings)["conclusion"]
    assert "เร่งด่วน 1 เรื่อง" in c
    assert "S0" in c and "อีก 2 รายการ" in c
    assert "S2" not in c, "ไม่ไล่ทุกรายการในบทสรุป — รายละเอียดอยู่ในตารางข้อสังเกต"
