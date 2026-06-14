"""Manual test driver — Admin User CRUD + Step-up gate.

รัน: docker compose exec hub-backend python -m tests.manual_user_crud_stepup_driver

ทดสอบ:
  - POST/PATCH/DELETE ก่อน step-up → 403 stepup_required
  - หลัง set stepup cache → ผ่าน
  - validation (email ซ้ำ, identifier ซ้ำ, user_type ผิด)
  - self-lockout guards (ลบ/ถอดสิทธิ์ตัวเอง)
  - audit log ครบ (create_user/update_user/delete_user)
  - soft delete (status=deleted ไม่ hard delete)

cleanup user ที่สร้างตอนจบ (hard delete row ทดสอบ).
"""

from __future__ import annotations

import sys

import httpx

from app.database import SessionLocal
from app.models import AuditLog, User
from app.services.jwt_service import create_access_token
from app.services import stepup_cache

BASE = "http://localhost:8000"
PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
TEST_EMAIL = "crud_driver_test@uni.ac.th"
TEST_IDENT = "650777"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    db = SessionLocal()
    admin = db.query(User).filter(User.is_hub_admin.is_(True)).first()
    if not admin:
        print("ไม่พบ admin user")
        return 1

    # ลบ test user ค้างจากรอบก่อน (ถ้ามี)
    for stale in db.query(User).filter(User.email == TEST_EMAIL).all():
        db.delete(stale)
    db.commit()

    tok, jti = create_access_token(admin)
    auth = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    c = httpx.Client(base_url=BASE, timeout=10.0)

    print(f"\nadmin = {admin.email}\n")

    # ── Group 1: step-up gate blocks ก่อน verify ──────────────────────
    print("── Group 1: Step-up gate blocks (ก่อน verify) ──")
    r = c.post(
        "/admin/users/",
        headers=auth,
        json={"email": TEST_EMAIL, "full_name": "X", "user_type": "student"},
    )
    body = (
        r.json().get("detail", {})
        if r.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    check(
        "T1.1 CREATE ก่อน step-up → 403 stepup_required",
        r.status_code == 403 and body.get("code") == "stepup_required",
        f"status={r.status_code}",
    )

    r = c.patch(
        "/admin/users/" + str(admin.id), headers=auth, json={"phone": "0810000000"}
    )
    body = r.json().get("detail", {})
    check(
        "T1.2 PATCH ก่อน step-up → 403",
        r.status_code == 403 and body.get("code") == "stepup_required",
        f"status={r.status_code}",
    )

    r = c.request(
        "DELETE",
        "/admin/users/" + "0" * 8 + "-0000-0000-0000-000000000000",
        headers=auth,
    )
    body = r.json().get("detail", {})
    check(
        "T1.3 DELETE ก่อน step-up → 403",
        r.status_code == 403 and body.get("code") == "stepup_required",
        f"status={r.status_code}",
    )

    # ── set step-up cache (จำลอง passkey verify ผ่าน) ─────────────────
    stepup_cache.set_granted(str(admin.id), jti, method="passkey", ip="127.0.0.1")

    # ── Group 2: CREATE หลัง step-up ──────────────────────────────────
    print("\n── Group 2: CREATE (หลัง step-up) ──")
    r = c.post(
        "/admin/users/",
        headers=auth,
        json={
            "email": TEST_EMAIL,
            "full_name": "CRUD Driver",
            "user_type": "student",
            "identifier": TEST_IDENT,
            "faculty": "วิศวกรรมศาสตร์",
        },
    )
    check("T2.1 CREATE → 201", r.status_code == 201, f"status={r.status_code}")
    new_id = r.json().get("id") if r.status_code == 201 else None
    check(
        "T2.2 response มี id + status=active",
        bool(new_id) and r.json().get("status") == "active",
    )

    # email ซ้ำ → 409
    r = c.post(
        "/admin/users/",
        headers=auth,
        json={"email": TEST_EMAIL, "full_name": "Dup", "user_type": "staff"},
    )
    check("T2.3 email ซ้ำ → 409", r.status_code == 409, f"status={r.status_code}")

    # identifier ซ้ำ → 409
    r = c.post(
        "/admin/users/",
        headers=auth,
        json={
            "email": "other@uni.ac.th",
            "full_name": "Dup2",
            "user_type": "staff",
            "identifier": TEST_IDENT,
        },
    )
    check("T2.4 identifier ซ้ำ → 409", r.status_code == 409, f"status={r.status_code}")

    # user_type ผิด → 422
    r = c.post(
        "/admin/users/",
        headers=auth,
        json={"email": "bad@uni.ac.th", "full_name": "Bad", "user_type": "wizard"},
    )
    check("T2.5 user_type ผิด → 422", r.status_code == 422, f"status={r.status_code}")

    # ── Group 3: UPDATE ───────────────────────────────────────────────
    print("\n── Group 3: UPDATE ──")
    r = c.patch(
        f"/admin/users/{new_id}",
        headers=auth,
        json={"full_name": "CRUD Driver แก้แล้ว", "phone": "0899999999"},
    )
    check(
        "T3.1 PATCH → 200 + ค่าใหม่",
        r.status_code == 200 and r.json().get("full_name") == "CRUD Driver แก้แล้ว",
        f"status={r.status_code}",
    )

    r = c.patch(f"/admin/users/{new_id}", headers=auth, json={})
    check("T3.2 PATCH ว่าง → 422", r.status_code == 422, f"status={r.status_code}")

    r = c.patch(f"/admin/users/{new_id}", headers=auth, json={"status": "frozen"})
    check("T3.3 status ผิด → 422", r.status_code == 422, f"status={r.status_code}")

    # ── Group 4: self-lockout guards ──────────────────────────────────
    print("\n── Group 4: Self-lockout guards ──")
    r = c.patch(f"/admin/users/{admin.id}", headers=auth, json={"user_type": "student"})
    check("T4.1 ถอด admin ตัวเอง → 400", r.status_code == 400, f"status={r.status_code}")

    r = c.patch(f"/admin/users/{admin.id}", headers=auth, json={"status": "suspended"})
    check("T4.2 suspend ตัวเอง → 400", r.status_code == 400, f"status={r.status_code}")

    r = c.request("DELETE", f"/admin/users/{admin.id}", headers=auth)
    check("T4.3 ลบตัวเอง → 400", r.status_code == 400, f"status={r.status_code}")

    # ── Group 5: DELETE (soft) ────────────────────────────────────────
    print("\n── Group 5: DELETE (soft) ──")
    r = c.request("DELETE", f"/admin/users/{new_id}", headers=auth)
    check(
        "T5.1 DELETE → 200 + status=deleted",
        r.status_code == 200 and r.json().get("status") == "deleted",
        f"status={r.status_code}",
    )

    db.expire_all()
    deleted_user = db.query(User).filter(User.id == new_id).first()
    check("T5.2 soft delete — row ยังอยู่ (ไม่ hard delete)", deleted_user is not None)
    check(
        "T5.3 status = deleted ใน DB",
        deleted_user is not None and deleted_user.status == "deleted",
    )

    r = c.request("DELETE", f"/admin/users/{new_id}", headers=auth)
    check("T5.4 ลบซ้ำ → 409", r.status_code == 409, f"status={r.status_code}")

    # ── Group 6: audit log ────────────────────────────────────────────
    print("\n── Group 6: Audit log ──")
    actions = {
        a.action for a in db.query(AuditLog).filter(AuditLog.target_id == new_id).all()
    }
    check("T6.1 audit มี create_user", "create_user" in actions, str(actions))
    check("T6.2 audit มี update_user", "update_user" in actions)
    check("T6.3 audit มี delete_user", "delete_user" in actions)

    # ── cleanup ───────────────────────────────────────────────────────
    if deleted_user:
        db.query(AuditLog).filter(AuditLog.target_id == new_id).delete()
        db.delete(deleted_user)
        db.commit()
    stepup_cache.clear(str(admin.id), jti)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*50}\nRESULT: {passed}/{total} passed\n{'='*50}")
    if passed < total:
        print("\nFAILED:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name} ({detail})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
