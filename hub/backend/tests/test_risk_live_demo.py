"""Risk scenarios — LIVE DEMO: ยิงผ่าน pipeline จริงแล้ว **เก็บข้อมูลไว้ดูที่หน้า admin**.

ต่างจาก `test_risk_scenarios.py` (unit — ลบข้อมูลทิ้งหลังเทส) ไฟล์นี้ตั้งใจ
**ไม่ลบ** เพื่อให้เปิด Hub Admin Console ไปดูผลจริงได้:
  - Dashboard → กราฟ/KPI login + decision distribution
  - Login Sessions / SOC → risk_score, decision, ประเทศ, อุปกรณ์, เหตุผล
  - User 360 → timeline ของ user คนนี้

ใช้ pipeline เดียวกับ `auth.py:google_callback` ทุกขั้น:
    extract_session_features() → evaluate_login_risk() → LoginSession(...) → commit
บันทึกครบทุก column ที่หน้า admin ใช้ (risk_breakdown, risk_reasons, os/browser/device,
geo_country, is_attack_ip, login_method) จึงแสดงผลเหมือน login จริงทุกอย่าง

─────────────────────────────────────────────────────────────────────────────
**ปลอดภัยต่อข้อมูลจริง** — ใช้บัญชีสาธิตแยก `risk-demo@uni.ac.th` เท่านั้น
ไม่แตะบัญชีผู้ใช้จริง และทุกแถวฝัง marker `RiskDemo` ใน user_agent
รันซ้ำได้เรื่อยๆ (test_00 ล้างของรอบก่อนให้อัตโนมัติ → ผลเหมือนเดิมทุกครั้ง)

รัน:
    docker compose exec hub-backend pytest tests/test_risk_live_demo.py -v -s

ล้างข้อมูลสาธิตทั้งหมดเมื่อดูเสร็จ:
    docker compose exec hub-postgres psql -U hub -d hub_db -c \\
      "DELETE FROM login_sessions WHERE user_agent LIKE '%RiskDemo%';"
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models import LoginSession, User
from app.security.risk_engine import evaluate_login_risk
from app.services.feature_extraction import (
    extract_session_features,
    parse_browser,
    parse_device_type,
    parse_os_name,
)
from app.services.ip_blacklist import is_blacklisted

# marker ใน user_agent — ใช้ค้น/ลบข้อมูลสาธิตได้ภายหลัง
MARK = "RiskDemo"

UA_DESKTOP_TH = (
    f"Mozilla/5.0 ({MARK}; Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
UA_IPHONE = (
    f"Mozilla/5.0 ({MARK}; iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

IP_TH = "203.0.113.10"  # RFC 5737 TEST-NET-3
IP_US = "198.51.100.77"  # RFC 5737 TEST-NET-2
IP_RU = "192.0.2.55"  # RFC 5737 TEST-NET-1
USUAL_HOUR = 9

# บัญชีสาธิตแยกต่างหาก — **ไม่แตะบัญชีจริง** เพื่อไม่ให้ข้อมูลปลอมปนกับของจริง
# (session ปลอมที่มี decision=block จะทำให้สถิติ/SOC ของบัญชีจริงเพี้ยน)
DEMO_EMAIL = "risk-demo@uni.ac.th"


# ─────────────────────────────────────────────────────────────
# helpers — mirror auth.py:google_callback
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def demo_user(db):
    """บัญชีสาธิตเฉพาะกิจ (สร้างครั้งแรก แล้ว reuse) — ไม่เกี่ยวกับ user จริง.

    function-scope แต่ idempotent (ค้นด้วย email ก่อน) → ทุกเทสได้ user คนเดียวกัน
    """
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(
        email=DEMO_EMAIL,
        google_sub=f"riskdemo_{uuid.uuid4().hex[:12]}",
        full_name="Risk Demo (ข้อมูลสาธิต)",
        user_type="teacher",
        identifier="RD001",
        faculty="วิทยาศาสตร์",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    print(f"\n>>> สร้างบัญชีสาธิตใหม่: {u.email}")
    return u


def _reset_demo_sessions(db, user) -> int:
    """ลบ session สาธิตของรอบก่อน — ให้ผลรันซ้ำได้เหมือนเดิมทุกครั้ง.

    ลบเฉพาะแถวที่ (1) เป็นของ user สาธิต และ (2) มี marker ใน user_agent
    → ไม่มีทางแตะข้อมูลจริง
    """
    n = (
        db.query(LoginSession)
        .filter(
            LoginSession.user_id == user.id,
            LoginSession.user_agent.like(f"%{MARK}%"),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return n


async def _login(
    db,
    user,
    *,
    ip: str,
    ua: str,
    country: str | None,
    now: datetime,
    label: str,
) -> LoginSession:
    """จำลอง login 1 ครั้งผ่าน pipeline จริง แล้ว **บันทึกถาวร**.

    ทำตามลำดับเดียวกับ auth.py:google_callback ข้อ 1→3
    """
    features = extract_session_features(
        db, user.id, ip=ip, user_agent=ua, geo_country=country, now=now
    )
    risk = await evaluate_login_risk(
        features=features,
        user_id=str(user.id),
        ip=ip,
        geo_country=country,
        db=db,
        shadow_mode=False,  # enforce → เห็น decision จริง (block/challenge) ที่หน้า admin
    )
    session = LoginSession(
        user_id=user.id,
        subsystem_id=None,  # Hub-direct
        ip=ip,
        user_agent=ua,
        geo_country=country,
        os_name=parse_os_name(ua),
        browser=parse_browser(ua),
        device_type=parse_device_type(ua),
        anomaly_score=risk["breakdown"].get("iforest_raw", 0.0),
        risk_score=risk["score"],
        risk_breakdown=risk["breakdown"],
        risk_reasons=risk["reasons"],
        decision=risk["decision"],
        is_attack_ip=is_blacklisted(db, ip),
        login_method="google",
        created_at=now,
    )
    db.add(session)
    db.commit()

    print(
        f"  [{label}] {country or '-':<3} {ip:<15} "
        f"score={risk['score']:.3f} decision={risk['decision']:<10} "
        f"{risk['reasons']}"
    )
    return session


# ═════════════════════════════════════════════════════════════
# 0. สร้างประวัติ "ปกติ" ให้ระบบรู้จักพฤติกรรม (ต้องรันก่อน)
# ═════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_00_seed_normal_history(demo_user, db):
    """ล้างรอบก่อน + สร้าง baseline 8 ครั้ง: ไทย · เครื่องเดิม · ~9 โมง.

    (ต้อง >= MIN_HISTORY_FOR_PERSONALIZATION=5 เพื่อพ้น cold start)
    """
    removed = _reset_demo_sessions(db, demo_user)
    base = datetime.utcnow().replace(hour=USUAL_HOUR, minute=0, second=0, microsecond=0)
    print(f"\n=== [0] ล้างข้อมูลสาธิตรอบก่อน {removed} แถว → สร้าง baseline 8 ครั้ง ===")
    print(f"    บัญชีสาธิต: {demo_user.email} (ไม่ใช่บัญชีจริง)")
    for i in range(8, 0, -1):
        await _login(
            db,
            demo_user,
            ip=IP_TH,
            ua=UA_DESKTOP_TH,
            country="TH",
            now=base - timedelta(days=i),
            label=f"baseline -{i}d",
        )
    count = db.query(LoginSession).filter(LoginSession.user_id == demo_user.id).count()
    assert count >= 8


# ═════════════════════════════════════════════════════════════
# 1. ปกติ
# ═════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_01_normal_login(demo_user, db):
    """ไทย · เครื่องเดิม · เวลาเดิม → ควร allow, คะแนนต่ำ."""
    now = datetime.utcnow().replace(hour=USUAL_HOUR, minute=15)
    print("\n=== [1] login ปกติ ===")
    s = await _login(
        db, demo_user, ip=IP_TH, ua=UA_DESKTOP_TH, country="TH", now=now, label="ปกติ"
    )
    assert s.decision != "block"
    assert float(s.risk_score) < 0.85


# ═════════════════════════════════════════════════════════════
# 2. IP + ประเทศต่างจากเดิม / เวลาต่างจากเดิม
# ═════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_02_new_country_and_ip(demo_user, db):
    """IP + ประเทศต่างจากเดิม — ดูที่ admin ว่าขึ้นธงความเสี่ยงเชิงภูมิศาสตร์.

    ใช้ประเทศที่ user ไม่เคย login (คำนวณจาก history จริง) เพื่อให้ได้ is_new_country
    แน่นอน — บัญชีที่ใช้งานจริงอาจเคยมีหลายประเทศอยู่แล้ว
    """
    seen = {
        row[0]
        for row in db.query(LoginSession.geo_country)
        .filter(
            LoginSession.user_id == demo_user.id,
            LoginSession.geo_country.is_not(None),
        )
        .distinct()
        .all()
    }
    # เลือกประเทศแรกที่ user ไม่เคยเข้าจาก
    country = next(c for c in ("US", "RU", "IS", "BR", "NG", "KZ") if c not in seen)
    now = datetime.utcnow().replace(hour=USUAL_HOUR, minute=30)
    print(f"\n=== [2] IP + ประเทศใหม่ ({country}; เคยเห็น: {sorted(seen)}) ===")
    s = await _login(
        db,
        demo_user,
        ip=IP_US,
        ua=UA_DESKTOP_TH,
        country=country,
        now=now,
        label="ประเทศใหม่",
    )
    assert float(s.risk_score) > 0.1
    # สัญญาณเชิงภูมิศาสตร์อย่างใดอย่างหนึ่ง (ประเทศใหม่ / ไม่ใช่ไทย / เดินทางผิดปกติ)
    joined = " ".join(s.risk_reasons).lower()
    assert any(
        k in joined for k in ("country", "thailand", "travel")
    ), f"คาดหวังสัญญาณภูมิศาสตร์ แต่ได้: {s.risk_reasons}"


@pytest.mark.asyncio
async def test_03_unusual_time(demo_user, db):
    """เวลาผิดปกติ — ปกติ 9 โมง ครั้งนี้ตี 3 (ไทย เครื่องเดิม)."""
    now = datetime.utcnow().replace(hour=3, minute=20)
    print("\n=== [3] เวลาผิดปกติ (ตี 3) ===")
    s = await _login(
        db, demo_user, ip=IP_TH, ua=UA_DESKTOP_TH, country="TH", now=now, label="ตี 3"
    )
    assert s.risk_score is not None


@pytest.mark.asyncio
async def test_04_new_device(demo_user, db):
    """อุปกรณ์ใหม่ (Windows Chrome → iPhone Safari) — admin ควรเห็น device/browser เปลี่ยน."""
    # เคสนี้ทดสอบ "เครื่องใหม่" ล้วน — ต้องตัดสัญญาณเดินทางออกก่อน ไม่งั้น login ต่างประเทศ
    # ของ test_02 ทำให้ impossible_travel hard-block (ประเมินความเสี่ยงใช้เวลาจริง utcnow
    # ไม่ใช่ created_at ที่ส่งเข้าไป -> เลื่อนวันไม่ช่วย) แล้วข้าม L2/L3 จนไม่มีเหตุผล device
    db.query(LoginSession).filter(
        LoginSession.user_id == demo_user.id,
        LoginSession.geo_country.is_not(None),
        LoginSession.geo_country != "TH",
    ).delete(synchronize_session=False)
    db.commit()
    now = datetime.utcnow().replace(hour=USUAL_HOUR, minute=45)
    print("\n=== [4] อุปกรณ์ใหม่ (iPhone) ===")
    s = await _login(
        db, demo_user, ip=IP_TH, ua=UA_IPHONE, country="TH", now=now, label="iPhone"
    )
    assert s.device_type is not None
    assert any("device" in r.lower() or "agent" in r.lower() for r in s.risk_reasons)


# ═════════════════════════════════════════════════════════════
# 3. Impossible travel — คนละประเทศห่างกัน 10 นาที
# ═════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_05_impossible_travel(demo_user, db):
    """login ไทย → 10 นาทีต่อมา login รัสเซีย = เป็นไปไม่ได้ → ต้อง block."""
    now = datetime.utcnow()
    print("\n=== [5] Impossible travel (TH → RU ใน 10 นาที) ===")
    await _login(
        db,
        demo_user,
        ip=IP_TH,
        ua=UA_DESKTOP_TH,
        country="TH",
        now=now - timedelta(minutes=10),
        label="อยู่ไทย",
    )
    s = await _login(
        db,
        demo_user,
        ip=IP_RU,
        ua=UA_DESKTOP_TH,
        country="RU",
        now=now,
        label="10 นาทีต่อมา อยู่รัสเซีย",
    )
    assert s.decision == "block", "ข้ามประเทศใน 10 นาทีต้องถูกบล็อก"
    assert any("travel" in r.lower() for r in s.risk_reasons)


# ═════════════════════════════════════════════════════════════
# สรุป — บอกว่าไปดูที่ไหน
# ═════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_99_summary(demo_user, db):
    """สรุปข้อมูลที่เพิ่งสร้าง + บอกจุดที่ไปดูในหน้า admin."""
    rows = (
        db.query(LoginSession)
        .filter(
            LoginSession.user_id == demo_user.id,
            LoginSession.user_agent.like(f"%{MARK}%"),  # เฉพาะแถวสาธิตของรอบนี้
        )
        .order_by(LoginSession.created_at.desc())
        .limit(20)
        .all()
    )
    print("\n" + "=" * 78)
    print(f"ข้อมูลสาธิตของ: {demo_user.email}   (user_id={demo_user.id})")
    print("=" * 78)
    print(f"{'เวลา (UTC)':<20}{'ประเทศ':<8}{'score':>7}  {'decision':<12}{'อุปกรณ์'}")
    print("-" * 78)
    for r in rows:
        print(
            f"{r.created_at:%Y-%m-%d %H:%M}   {r.geo_country or '-':<8}"
            f"{float(r.risk_score or 0):>7.3f}  {r.decision or '-':<12}"
            f"{r.browser or '-'}/{r.device_type or '-'}"
        )
    print("=" * 78)
    print("ไปดูผลที่หน้า admin:")
    print("  • Dashboard          http://localhost:3000/dashboard")
    print("  • Login sessions/SOC http://localhost:3000/sessions  (หรือเมนู SOC)")
    print(f"  • User 360           http://localhost:3000/users/{demo_user.id}")
    print("  • Audit log          http://localhost:3000/audit")
    print("-" * 78)
    print("ล้างข้อมูลสาธิตเมื่อดูเสร็จ:")
    print(
        "  docker compose exec hub-postgres psql -U hub -d hub_db -c "
        f"\"DELETE FROM login_sessions WHERE user_agent LIKE '%{MARK}%';\""
    )
    print("=" * 78)
    assert len(rows) > 0
