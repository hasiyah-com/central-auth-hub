"""Manual test driver — Risk-Triggered MFA (mechanism B).

รันใน container: docker compose exec hub-backend python -m tests.manual_risk_mfa_driver

ทดสอบ contract + security gates ของ flow ใหม่ (Week 9-10) โดย:
  - mint risk_challenge ผ่าน service จริง (จำลอง finalizer หลัง RBA = mfa)
  - ยิง HTTP endpoint จริงที่ localhost:8000 (เซิร์ฟเวอร์ที่รันอยู่)
  - ตรวจ status code + body ตาม expected

ส่วน WebAuthn ceremony (register/complete, stepup/verify ที่ต้อง signature จริง)
ครอบคลุมโดย pytest test_passkey_ceremony.py (soft-webauthn) — ไม่ทำซ้ำที่นี่.

ไม่ลบ test data อัตโนมัติ (เก็บ challenge ที่ consume แล้ว = หายเอง 5 นาที).
"""

from __future__ import annotations

import sys

import httpx

from app.database import SessionLocal
from app.models import User
from app.services import risk_challenge, webauthn_service as ws
from app.services.mfa_service import hash_otp
from app.redis_client import redis_client

BASE = "http://localhost:8000"
PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    mark = PASS if cond else FAIL
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def mint_for(user: User, kind: str) -> str:
    return risk_challenge.mint(
        user_id=str(user.id),
        hub_state="teststate12345678",
        authreq={
            "client_id": "cli_test",
            "subsystem_id": None,
            "code_challenge": "x" * 43,
            "scope": "openid",
            "state": "substate",
            "redirect_uri": "http://localhost:8002/auth/callback",
        },
        risk_score=0.72,
        risk_breakdown={"rule": 0.3, "behavior": 0.2, "iforest": 0.22},
        risk_reasons=["is_new_device (+0.30)", "is_new_country (+0.20)"],
        provider="google",
        kind=kind,
        flow="subsystem",
    )


def main() -> int:
    db = SessionLocal()
    reauth_user = next(
        (u for u in db.query(User).limit(300).all() if ws.count_active(u.id, db) > 0),
        None,
    )
    enroll_user = next(
        (u for u in db.query(User).limit(300).all() if ws.count_active(u.id, db) == 0),
        None,
    )
    if not reauth_user or not enroll_user:
        print("ไม่พบ user ที่เหมาะสม (ต้องมีทั้งมี/ไม่มี passkey)")
        return 1

    print(f"\nREAUTH_USER = {reauth_user.email} (has passkey)")
    print(f"ENROLL_USER = {enroll_user.email} (no passkey)\n")

    c = httpx.Client(base_url=BASE, timeout=10.0, follow_redirects=False)

    # ── Group 1: Challenge lifecycle ──────────────────────────────────
    print("── Group 1: Risk challenge lifecycle ──")
    cid = mint_for(reauth_user, "reauth")
    check("T1.1 mint reauth challenge", bool(cid), cid[:16] + "...")

    peek = risk_challenge.peek(cid)
    check("T1.2 peek returns payload", peek is not None and peek["kind"] == "reauth")

    # ── Group 2: Risk Re-Auth page + gates ────────────────────────────
    print("\n── Group 2: Risk Re-Auth (has passkey) ──")
    r = c.get(f"/auth/passkey/risk-stepup?challenge={cid}")
    check(
        "T2.1 GET risk-stepup page → 200",
        r.status_code == 200,
        f"status={r.status_code}",
    )
    check("T2.2 page แสดง email user", reauth_user.email in r.text or "***" in r.text)
    check(
        "T2.3 page แสดง risk reason",
        "is_new_device" in r.text or "0.72" in r.text or "reason" in r.text.lower(),
    )

    r = c.get("/auth/passkey/risk-stepup?challenge=nonexistent_xxx")
    check(
        "T2.4 invalid challenge → 410", r.status_code == 410, f"status={r.status_code}"
    )

    r = c.post("/auth/passkey/risk-stepup/start", json={"challenge_id": cid})
    check(
        "T2.5 start (reauth) → 200 + assertion options",
        r.status_code == 200 and "challenge" in r.text,
        f"status={r.status_code}",
    )

    # wrong-kind guard: enroll challenge ใช้ที่ reauth endpoint
    cid_enroll_wrong = mint_for(reauth_user, "enroll")
    r = c.post(
        "/auth/passkey/risk-stepup/start", json={"challenge_id": cid_enroll_wrong}
    )
    check(
        "T2.6 enroll-kind ที่ reauth/start → 400",
        r.status_code == 400,
        f"status={r.status_code}",
    )
    risk_challenge.consume(cid_enroll_wrong)

    # ── Group 3: Force Enroll — OTP gate (B45 — สำคัญสุด) ──────────────
    print("\n── Group 3: Force Enrollment OTP gate (B45) ──")
    ecid = mint_for(enroll_user, "enroll")
    r = c.get(f"/auth/passkey/force-enroll?challenge={ecid}")
    check(
        "T3.1 GET force-enroll page → 200",
        r.status_code == 200,
        f"status={r.status_code}",
    )
    check("T3.2 page แสดง email masked", "***" in r.text)

    # reauth challenge ที่ force-enroll page → 400 (wrong kind)
    r = c.get(f"/auth/passkey/force-enroll?challenge={cid}")
    check(
        "T3.3 reauth-kind ที่ force-enroll → 400",
        r.status_code == 400,
        f"status={r.status_code}",
    )

    # ⭐ B45 — register/start โดยยังไม่ผ่าน OTP → 403 otp_required
    r = c.post("/auth/passkey/force-enroll/register/start", json={"challenge_id": ecid})
    body = (
        r.json()
        if r.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    otp_required = (
        r.status_code == 403
        and str(body.get("detail", {}).get("code")) == "otp_required"
    )
    check(
        "T3.4 ⭐ register/start ก่อน OTP → 403 otp_required (B45)",
        otp_required,
        f"status={r.status_code}",
    )

    # register/complete โดยยังไม่ผ่าน OTP → 403 ด้วย
    r = c.post(
        "/auth/passkey/force-enroll/register/complete",
        json={"challenge_id": ecid, "credential": {"x": 1}},
    )
    check(
        "T3.5 register/complete ก่อน OTP → 403",
        r.status_code == 403,
        f"status={r.status_code}",
    )

    # ── Group 4: Force Enroll — OTP send/verify ───────────────────────
    print("\n── Group 4: Force Enrollment OTP send/verify ──")
    r = c.post("/auth/passkey/force-enroll/send-otp", json={"challenge_id": ecid})
    check(
        "T4.1 send-otp → 200 sent",
        r.status_code == 200 and r.json().get("sent") is True,
        f"status={r.status_code}",
    )
    check(
        "T4.2 OTP hash อยู่ใน Redis",
        redis_client.get(f"force_enroll_otp:{ecid}") is not None,
    )

    # wrong OTP → 401
    r = c.post(
        "/auth/passkey/force-enroll/verify-otp",
        json={"challenge_id": ecid, "otp": "000000"},
    )
    check("T4.3 verify-otp ผิด → 401", r.status_code == 401, f"status={r.status_code}")

    # set known OTP hash → verify ผ่าน (จำลอง user ได้ OTP จริงจาก email)
    known_otp = "246810"
    redis_client.setex(f"force_enroll_otp:{ecid}", 300, hash_otp(known_otp))
    r = c.post(
        "/auth/passkey/force-enroll/verify-otp",
        json={"challenge_id": ecid, "otp": known_otp},
    )
    check(
        "T4.4 verify-otp ถูก → 200 verified",
        r.status_code == 200 and r.json().get("verified") is True,
        f"status={r.status_code}",
    )
    check(
        "T4.5 passed flag set ใน Redis",
        redis_client.get(f"force_enroll_otp_passed:{ecid}") is not None,
    )
    check(
        "T4.6 OTP hash ถูกลบหลัง verify",
        redis_client.get(f"force_enroll_otp:{ecid}") is None,
    )

    # หลังผ่าน OTP → register/start คืน options ได้
    r = c.post("/auth/passkey/force-enroll/register/start", json={"challenge_id": ecid})
    check(
        "T4.7 หลัง OTP → register/start → 200 options",
        r.status_code == 200 and "challenge" in r.text,
        f"status={r.status_code}",
    )

    # ── Group 5: Input validation / anti-enum ─────────────────────────
    print("\n── Group 5: Input validation ──")
    r = c.post(
        "/auth/passkey/force-enroll/verify-otp",
        json={"challenge_id": ecid, "otp": "abc"},
    )
    check("T5.1 OTP non-digit → 422", r.status_code == 422, f"status={r.status_code}")

    r = c.post("/auth/passkey/risk-stepup/start", json={"challenge_id": "short"})
    check(
        "T5.2 challenge_id สั้นเกิน → 422", r.status_code == 422, f"status={r.status_code}"
    )

    r = c.post("/auth/passkey/force-enroll/send-otp", json={})
    check(
        "T5.3 missing challenge_id → 422",
        r.status_code == 422,
        f"status={r.status_code}",
    )

    # cleanup challenges ที่ยังค้าง
    risk_challenge.consume(cid)
    risk_challenge.consume(ecid)
    redis_client.delete(f"force_enroll_otp_passed:{ecid}")

    # ── Summary ───────────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*50}")
    print(f"RESULT: {passed}/{total} passed")
    print(f"{'='*50}")
    if passed < total:
        print("\nFAILED:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name} ({detail})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
