"""Manual test driver — Failure-path audit logging + rate limit + traceability.

รัน: docker compose exec hub-backend python -m tests.manual_failure_log_ratelimit_driver

ทดสอบ:
  1. failure path log จริง — 404 (email ไม่มี), 400 (duplicate) → audit row + ทุก attempt
  2. request_logs (middleware) เก็บทุก request พร้อม ip + user_agent (traceability)
  3. rate limit — ยิง whitelist add เกิน threshold → 429

ต้องมี subsystem active + admin มี passkey access. ใช้ step-up cache จำลอง verify.
cleanup audit rows ที่สร้างตอนจบ.
"""

from __future__ import annotations

import sys

import httpx

from app.database import SessionLocal
from app.models import AuditLog, RequestLog, Subsystem, User
from app.services.jwt_service import create_access_token
from app.services import stepup_cache

BASE = "http://localhost:8000"
PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
# email format ถูกต้อง (ผ่าน pydantic EmailStr) แต่ไม่มีใน Hub → 404 (ไม่ใช่ 422)
GHOST_EMAIL = "ghost_notreal_zzz999@uni.ac.th"
UA = "FailLogDriver/1.0 (TestWindows)"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    db = SessionLocal()
    admin = db.query(User).filter(User.is_hub_admin.is_(True)).first()
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    if not admin or not sub:
        print("ต้องมี admin + active subsystem")
        return 1

    tok, jti = create_access_token(admin)
    auth = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "User-Agent": UA,
    }
    stepup_cache.set_granted(str(admin.id), jti, method="passkey", ip="127.0.0.1")
    c = httpx.Client(base_url=BASE, timeout=10.0)
    print(f"\nadmin = {admin.email} | subsystem = {sub.name}\n")

    wl = f"/developer/subsystems/{sub.id}/whitelist/user"

    # ── Group 1: failure path 404 (email ไม่มีใน Hub) — log ทุก attempt ──
    print("── Group 1: Failure log — email ไม่มีใน Hub (404) ──")
    before = (
        db.query(AuditLog).filter(AuditLog.action == "whitelist_add_failed").count()
    )
    for i in range(3):
        r = c.post(wl, headers=auth, json={"email": GHOST_EMAIL, "role": "member"})
    db.expire_all()
    after = db.query(AuditLog).filter(AuditLog.action == "whitelist_add_failed").count()
    check(
        "T1.1 ยิง 3 ครั้ง (email ไม่มี) → 404",
        r.status_code == 404,
        f"status={r.status_code}",
    )
    check(
        "T1.2 audit log เพิ่ม 3 row (ทุก attempt — ไม่ใช่ครั้งเดียว)",
        after - before == 3,
        f"+{after - before}",
    )
    last = (
        db.query(AuditLog)
        .filter(AuditLog.action == "whitelist_add_failed")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    check(
        "T1.3 audit เก็บ reason + email + user_agent (traceability)",
        last is not None
        and last.metadata_json.get("reason") == "email_not_found"
        and last.metadata_json.get("user_agent") == UA,
        str(last.metadata_json) if last else "none",
    )
    check(
        "T1.4 audit เก็บ ip (ต้นทาง)",
        last is not None and last.ip is not None,
        str(last.ip) if last else "none",
    )

    # ── Group 2: request_logs (middleware) — traceability ทุก request ──
    print("\n── Group 2: request_logs — เข้าทางไหน ใช้อะไร ──")
    db.expire_all()
    rlog = (
        db.query(RequestLog)
        .filter(RequestLog.path == wl, RequestLog.user_agent == UA)
        .order_by(RequestLog.created_at.desc())
        .first()
    )
    check("T2.1 request_logs เก็บ request นี้", rlog is not None)
    if rlog:
        check(
            "T2.2 เก็บ method + path (ทำอะไร ที่ไหน)",
            rlog.method == "POST" and "whitelist" in rlog.path,
        )
        check("T2.3 เก็บ user_agent (ใช้อะไรเข้ามา)", rlog.user_agent == UA)
        check("T2.4 เก็บ user_id (ใครทำ)", rlog.user_id is not None)
        check(
            "T2.5 เก็บ status_code (ผลลัพธ์)",
            rlog.status_code == 404,
            f"status={rlog.status_code}",
        )
        check("T2.6 เก็บ ip (ต้นทาง)", rlog.ip is not None, str(rlog.ip))

    # ── Group 3: rate limit — spam เกิน 30/min → 429 ──
    print("\n── Group 3: Rate limit (30/min) — spam → 429 ──")
    got_429 = False
    sent = 0
    for i in range(40):
        r = c.post(wl, headers=auth, json={"email": GHOST_EMAIL, "role": "member"})
        sent += 1
        if r.status_code == 429:
            got_429 = True
            break
    check("T3.1 ยิงรัวเกิน 30/min → เจอ 429", got_429, f"429 ที่ request #{sent}")

    # ── cleanup ───────────────────────────────────────────────────────
    db.expire_all()
    db.query(AuditLog).filter(
        AuditLog.action.in_(
            ["whitelist_add_failed", "whitelist_add_blocked_duplicate"]
        ),
        AuditLog.actor_id == admin.id,
    ).delete(synchronize_session=False)
    db.commit()
    stepup_cache.clear(str(admin.id), jti)

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
