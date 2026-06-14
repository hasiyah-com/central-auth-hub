"""Manual test driver — Subsystem mutations + Step-up gate.

รัน: docker compose exec hub-backend python -m tests.manual_subsystem_stepup_driver

ทดสอบว่า **ทุก mutation ในส่วนระบบย่อย** ต้องผ่าน step-up:
  - ก่อน set step-up cache → 403 stepup_required (action ตรง)
  - หลัง set cache → ผ่าน gate (ไม่ติด stepup; อาจติด validation อื่นซึ่ง OK)

ครอบคลุม 14 endpoints:
  developer.py: register, whitelist CSV/user/remove/role/bulk, update, transfer, rotate
  admin.py:     approve, reject, suspend, resume, session-revoke

ไม่สร้าง state ถาวร — ใช้ subsystem/uuid ปลอม (gate ทำงานก่อน business logic).
"""

from __future__ import annotations

import sys

import httpx

from app.database import SessionLocal
from app.models import User
from app.services.jwt_service import create_access_token
from app.services import stepup_cache

BASE = "http://localhost:8000"
PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
FAKE = "00000000-0000-0000-0000-000000000000"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


# (label, method, path, expected_action, json_body)
ENDPOINTS = [
    (
        "register",
        "POST",
        "/developer/subsystems",
        "subsystem_register",
        {"name": "x", "redirect_uris": ["http://localhost/cb"], "scope": "openid"},
    ),
    (
        "whitelist CSV",
        "POST",
        f"/developer/subsystems/{FAKE}/whitelist",
        "whitelist_add",
        None,
    ),
    (
        "whitelist add user",
        "POST",
        f"/developer/subsystems/{FAKE}/whitelist/user",
        "whitelist_add",
        {"email": "x@uni.ac.th", "role": "member"},
    ),
    (
        "whitelist remove",
        "DELETE",
        f"/developer/subsystems/{FAKE}/whitelist/{FAKE}",
        "whitelist_remove",
        None,
    ),
    (
        "whitelist role change",
        "PATCH",
        f"/developer/subsystems/{FAKE}/whitelist/{FAKE}",
        "whitelist_role_change",
        {"role_in_sub": "member"},
    ),
    (
        "whitelist bulk",
        "POST",
        f"/developer/subsystems/{FAKE}/whitelist/bulk-update",
        "whitelist_role_change",
        {"updates": []},
    ),
    (
        "subsystem update",
        "PATCH",
        f"/developer/subsystems/{FAKE}",
        "subsystem_update",
        {"description": "y"},
    ),
    (
        "transfer owner",
        "POST",
        f"/developer/subsystems/{FAKE}/transfer-owner",
        "subsystem_transfer_owner",
        {"new_owner_email": "x@uni.ac.th"},
    ),
    (
        "rotate secret",
        "POST",
        f"/developer/subsystems/{FAKE}/rotate-secret",
        "rotate_oauth_secret",
        None,
    ),
    ("approve", "POST", f"/admin/subsystems/{FAKE}/approve", "subsystem_approve", None),
    ("reject", "POST", f"/admin/subsystems/{FAKE}/reject", "subsystem_reject", None),
    ("suspend", "POST", f"/admin/subsystems/{FAKE}/suspend", "subsystem_suspend", None),
    ("resume", "POST", f"/admin/subsystems/{FAKE}/resume", "subsystem_resume", None),
    (
        "session revoke",
        "POST",
        f"/admin/subsystems/{FAKE}/sessions/{FAKE}/revoke?level=notify",
        "session_revoke",
        None,
    ),
]


def main() -> int:
    db = SessionLocal()
    admin = db.query(User).filter(User.is_hub_admin.is_(True)).first()
    if not admin:
        print("ไม่พบ admin")
        return 1
    tok, jti = create_access_token(admin)
    auth = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    c = httpx.Client(base_url=BASE, timeout=10.0)

    print(f"\nadmin = {admin.email}\n")

    # ── Phase 1: ทุก endpoint ต้อง 403 stepup_required ก่อน verify ──
    print("── Phase 1: ก่อน step-up — ทุก mutation ต้อง 403 stepup_required ──")
    stepup_cache.clear(str(admin.id), jti)  # มั่นใจว่าไม่มี cache
    for label, method, path, action, body in ENDPOINTS:
        r = c.request(method, path, headers=auth, json=body)
        ok = False
        got_action = ""
        if r.status_code == 403:
            try:
                d = r.json().get("detail", {})
                got_action = d.get("action", "")
                ok = d.get("code") == "stepup_required" and got_action == action
            except Exception:
                ok = False
        check(
            f"P1 {label:22s} → 403 stepup ({action})",
            ok,
            f"status={r.status_code} action={got_action}",
        )

    # ── Phase 2: หลัง set cache — ไม่ติด stepup อีก (gate ผ่าน) ──
    print("\n── Phase 2: หลัง step-up — gate ผ่าน (ไม่ 403 stepup_required) ──")
    stepup_cache.set_granted(str(admin.id), jti, method="passkey", ip="127.0.0.1")
    for label, method, path, action, body in ENDPOINTS:
        r = c.request(method, path, headers=auth, json=body)
        # ผ่าน gate = ไม่ใช่ 403 stepup_required (จะเป็น 404/422/400 จาก business logic = OK)
        is_stepup = False
        if r.status_code == 403:
            try:
                is_stepup = r.json().get("detail", {}).get("code") == "stepup_required"
            except Exception:
                is_stepup = False
        check(f"P2 {label:22s} → ผ่าน gate", not is_stepup, f"status={r.status_code}")

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
