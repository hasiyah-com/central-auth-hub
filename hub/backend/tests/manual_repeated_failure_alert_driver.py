"""Manual test driver — repeated_failed_mutation alert (api_guard rule 5).

รัน: docker compose exec hub-backend python -m tests.manual_repeated_failure_alert_driver

ทดสอบว่า: actor พยายามทำ action ที่ fail ซ้ำ > threshold (10/5min)
→ scan_request_logs สร้าง alert + dedup ทำงาน + persist เป็น ApiAlert

ใช้ audit_logs จริง (insert + cleanup) — ไม่กระทบ data จริง.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import ApiAlert, AuditLog, User
from app.services.api_guard import (
    RULES,
    _FAILED_ACTION_LIKE,
    scan_and_persist,
    scan_request_logs,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    db = SessionLocal()
    admin = db.query(User).filter(User.is_hub_admin.is_(True)).first()
    if not admin:
        print("ไม่พบ admin")
        return 1

    # cleanup audit ค้างจากรอบก่อน (ใช้ ip pattern พิเศษ)
    db.query(AuditLog).filter(
        AuditLog.actor_id == admin.id,
        AuditLog.ip.in_(["10.0.0.1", "10.0.0.2"]),
    ).delete(synchronize_session=False)
    db.commit()

    print(f"actor = {admin.email}\n")
    rule = RULES["repeated_failed_mutation"]
    threshold = rule["threshold"]
    now = datetime.utcnow()

    # ── Group 1: ใส่ failed audit ต่ำกว่า threshold → ไม่ alert ──
    print("── Group 1: ต่ำกว่า threshold (10) — ไม่ alert ──")
    for i in range(5):
        db.add(
            AuditLog(
                actor_id=admin.id,
                action="whitelist_add_failed",
                target_type="subsystem",
                ip="10.0.0.1",
                metadata_json={"test": "low", "i": i},
                created_at=now - timedelta(seconds=60),
            )
        )
    db.commit()

    alerts = scan_request_logs(db)
    rule5 = [a for a in alerts if a["rule"] == "repeated_failed_mutation"]
    me = [a for a in rule5 if a["user_id"] == str(admin.id)]
    check(
        "T1.1 5 fail < threshold(10) → ไม่มี alert ของ admin",
        len(me) == 0,
        f"got {len(me)}",
    )

    # ── Group 2: ใส่ failed audit เกิน threshold → alert ──
    print("\n── Group 2: เกิน threshold — มี alert ──")
    for i in range(threshold + 2):  # 12 ครั้ง
        db.add(
            AuditLog(
                actor_id=admin.id,
                action="user_access_denied"
                if i % 2 == 0
                else "subsystem_access_denied",
                target_type="user",
                ip="10.0.0.2",
                metadata_json={"test": "high", "i": i},
                created_at=now - timedelta(seconds=60 + i),
            )
        )
    db.commit()

    alerts = scan_request_logs(db)
    rule5 = [
        a
        for a in alerts
        if a["rule"] == "repeated_failed_mutation" and a["user_id"] == str(admin.id)
    ]
    check(
        "T2.1 fail > threshold → มี alert ของ admin",
        len(rule5) == 1,
        f"got {len(rule5)}",
    )
    if rule5:
        a = rule5[0]
        check(
            "T2.2 alert มี actor_email ใน detail",
            a["detail"].get("actor_email") == admin.email,
        )
        check(
            "T2.3 alert มี top_actions (เห็น action breakdown)",
            len(a["detail"].get("top_actions", [])) >= 2,
        )
        check("T2.4 alert มี count ตรงจำนวน", a["detail"]["count"] >= threshold + 1)
        check("T2.5 severity = warning", a["severity"] == "warning")

    # ── Group 3: persist + dedup ──
    print("\n── Group 3: persist + dedup ──")
    before = (
        db.query(ApiAlert).filter(ApiAlert.rule == "repeated_failed_mutation").count()
    )
    persisted = scan_and_persist(db)
    after = (
        db.query(ApiAlert).filter(ApiAlert.rule == "repeated_failed_mutation").count()
    )
    new5 = [a for a in persisted if a.rule == "repeated_failed_mutation"]
    check("T3.1 persist สร้าง ApiAlert จริง", after > before, f"+{after - before}")

    # รัน persist ซ้ำ → ต้องไม่เพิ่ม (dedup ภายใน 10 นาที)
    persisted2 = scan_and_persist(db)
    after2 = (
        db.query(ApiAlert).filter(ApiAlert.rule == "repeated_failed_mutation").count()
    )
    new5_round2 = [a for a in persisted2 if a.rule == "repeated_failed_mutation"]
    check(
        "T3.2 dedup ภายใน 10 นาที → ไม่ persist ซ้ำ",
        len(new5_round2) == 0 or after2 == after,
        f"round2 persisted={len(new5_round2)}",
    )

    # ── Group 4: pattern coverage ──
    print("\n── Group 4: _FAILED_ACTION_LIKE ครอบคลุม ──")
    check("T4.1 มี _failed", any("_failed" in p for p in _FAILED_ACTION_LIKE))
    check("T4.2 มี _denied", any("_denied" in p for p in _FAILED_ACTION_LIKE))
    check("T4.3 มี _blocked", any("_blocked" in p for p in _FAILED_ACTION_LIKE))

    # ── cleanup — ลบ audit ที่ใส่เอง (ตาม ip ที่ตั้งให้พิเศษ) + alert ใหม่ ──
    db.query(AuditLog).filter(
        AuditLog.actor_id == admin.id,
        AuditLog.ip.in_(["10.0.0.1", "10.0.0.2"]),
    ).delete(synchronize_session=False)
    if new5:
        ids = [a.id for a in new5]
        db.query(ApiAlert).filter(ApiAlert.id.in_(ids)).delete(
            synchronize_session=False
        )
    db.commit()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*52}\nRESULT: {passed}/{total} passed\n{'='*52}")
    if passed < total:
        print("\nFAILED:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name} ({detail})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
