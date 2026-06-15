"""Manual test driver — Failure-path logging ที่เหลือ (IDOR + user CRUD + subsystem).

รัน: docker compose exec hub-backend python -m tests.manual_failure_log_remaining_driver

ทดสอบว่าทุก failure path ที่เพิ่ง wire log จริง (B7):
  - _get_owned_subsystem 404 (IDOR — แตะ subsystem คนอื่น/ไม่มี) → subsystem_access_denied
  - user 404 (get/update/delete ID ที่ไม่มี) → *_failed / user_access_denied
  - create user email/identifier ซ้ำ (409) → create_user_failed
  - subsystem register scope ผิด → subsystem_register_failed
  - transfer owner ไม่พบ/ตัวเอง → subsystem_transfer_failed

ต้องผ่าน step-up cache สำหรับ endpoint ที่มี gate. ใช้ admin token.
cleanup audit rows ตอนจบ.
"""

from __future__ import annotations

import sys

import httpx

from app.database import SessionLocal
from app.models import AuditLog, Subsystem, User
from app.services.jwt_service import create_access_token
from app.services import stepup_cache

BASE = "http://localhost:8000"
PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
FAKE = "00000000-0000-0000-0000-000000000000"

results: list[tuple[str, bool, str]] = []
created_actions: set[str] = set()


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def audit_count(db, action: str, actor_id) -> int:
    db.expire_all()
    return (
        db.query(AuditLog)
        .filter(AuditLog.action == action, AuditLog.actor_id == actor_id)
        .count()
    )


def main() -> int:
    db = SessionLocal()
    admin = db.query(User).filter(User.is_hub_admin.is_(True)).first()
    if not admin:
        print("ไม่พบ admin")
        return 1
    tok, jti = create_access_token(admin)
    auth = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    stepup_cache.set_granted(str(admin.id), jti, method="passkey", ip="127.0.0.1")
    c = httpx.Client(base_url=BASE, timeout=10.0)
    print(f"\nadmin = {admin.email}\n")

    def expect_log(label, action, fn):
        before = audit_count(db, action, admin.id)
        r = fn()
        after = audit_count(db, action, admin.id)
        created_actions.add(action)
        check(
            f"{label} → log {action}",
            after > before,
            f"status={r.status_code} (+{after - before})",
        )
        return r

    # ── Group 1: IDOR — _get_owned_subsystem 404 ──
    print("── Group 1: IDOR — แตะ subsystem ที่ไม่มี/ไม่ใช่เจ้าของ ──")
    # admin เป็น hub_admin → query ไม่ filter owner แต่ FAKE id ไม่มี → 404 + log
    expect_log(
        "PATCH subsystem FAKE",
        "subsystem_access_denied",
        lambda: c.patch(
            f"/developer/subsystems/{FAKE}", headers=auth, json={"description": "x"}
        ),
    )

    # ── Group 2: User CRUD failures ──
    print("\n── Group 2: User CRUD 404/409 ──")
    expect_log(
        "GET user FAKE",
        "user_access_denied",
        lambda: c.get(f"/admin/users/{FAKE}", headers=auth),
    )
    expect_log(
        "PATCH user FAKE",
        "update_user_failed",
        lambda: c.patch(
            f"/admin/users/{FAKE}", headers=auth, json={"phone": "0810000000"}
        ),
    )
    expect_log(
        "DELETE user FAKE",
        "delete_user_failed",
        lambda: c.request("DELETE", f"/admin/users/{FAKE}", headers=auth),
    )
    # create email ซ้ำ (ใช้ admin email เอง = มีแน่)
    expect_log(
        "CREATE user email ซ้ำ",
        "create_user_failed",
        lambda: c.post(
            "/admin/users/",
            headers=auth,
            json={"email": admin.email, "full_name": "Dup", "user_type": "staff"},
        ),
    )

    # ── Group 3: Subsystem register / transfer ──
    print("\n── Group 3: Subsystem register / transfer ──")
    expect_log(
        "register scope ผิด",
        "subsystem_register_failed",
        lambda: c.post(
            "/developer/subsystems",
            headers=auth,
            json={
                "name": "x",
                "redirect_uris": ["http://localhost/cb"],
                "scope": ["evil:scope"],
            },
        ),
    )
    # transfer ต้องมี subsystem จริงที่ admin เข้าถึงได้
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    if sub:
        expect_log(
            "transfer owner email ไม่มี",
            "subsystem_transfer_failed",
            lambda: c.post(
                f"/developer/subsystems/{sub.id}/transfer-owner",
                headers=auth,
                json={"new_owner_email": "ghost_zzz@uni.ac.th"},
            ),
        )

    # ── Group 4: ตรวจ metadata มี ip + user_agent (traceability) ──
    print("\n── Group 4: metadata traceability ──")
    last = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "subsystem_access_denied", AuditLog.actor_id == admin.id
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    check(
        "G4.1 subsystem_access_denied มี reason + ip",
        last is not None
        and last.metadata_json.get("reason") == "not_found_or_not_owner"
        and last.ip is not None,
        str(last.metadata_json) if last else "none",
    )

    # ── cleanup ──
    db.expire_all()
    db.query(AuditLog).filter(
        AuditLog.action.in_(list(created_actions)),
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
