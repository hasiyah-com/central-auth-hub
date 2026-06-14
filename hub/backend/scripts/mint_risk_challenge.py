"""Helper — mint risk_challenge สำหรับทดสอบ Risk-Triggered MFA ด้วย browser.

ใช้เมื่ออยาก test หน้า Re-Auth / Force-Enroll โดยตรง (ข้าม RBA trigger):

    docker compose exec hub-backend python -m scripts.mint_risk_challenge reauth
    docker compose exec hub-backend python -m scripts.mint_risk_challenge enroll

จะ print URL เต็มให้เปิดใน browser. challenge อายุ 5 นาที.
ผูกกับ subsystem จริง (ห้องสมุด) → verify สำเร็จจะ redirect กลับ subsystem ได้.
"""

from __future__ import annotations

import sys

from app.database import SessionLocal
from app.models import AccessList, Subsystem, User
from app.services import risk_challenge, webauthn_service as ws

HUB = "http://localhost:8000"


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else "reauth"
    if kind not in ("reauth", "enroll"):
        print("usage: mint_risk_challenge [reauth|enroll]")
        return 1

    db = SessionLocal()
    # subsystem จริงที่ active (ห้องสมุด) — verify จะ redirect กลับได้
    sub = (
        db.query(Subsystem)
        .filter(Subsystem.status == "active", Subsystem.name.like("%ห้องสมุด%"))
        .first()
    ) or db.query(Subsystem).filter(Subsystem.status == "active").first()
    if not sub:
        print("ไม่พบ active subsystem")
        return 1

    # เลือก user ตาม kind + ต้องอยู่ใน access_list ของ subsystem
    want_passkey = kind == "reauth"
    user = None
    for u in db.query(User).limit(300).all():
        has = ws.count_active(u.id, db) > 0
        if has != want_passkey:
            continue
        in_acl = (
            db.query(AccessList)
            .filter(
                AccessList.user_id == u.id,
                AccessList.subsystem_id == sub.id,
                AccessList.revoked_at.is_(None),
            )
            .first()
        )
        if in_acl:
            user = u
            break
    if not user:
        # fallback — ไม่สน access_list (re-auth/enroll page ไม่ต้อง check ACL)
        user = next(
            (
                u
                for u in db.query(User).limit(300).all()
                if (ws.count_active(u.id, db) > 0) == want_passkey
            ),
            None,
        )
    if not user:
        print(f"ไม่พบ user ({'มี' if want_passkey else 'ไม่มี'} passkey)")
        return 1

    cid = risk_challenge.mint(
        user_id=str(user.id),
        hub_state="browsertest_" + cid_suffix(),
        authreq={
            "client_id": sub.client_id,
            "subsystem_id": str(sub.id),
            # ค่า PKCE ตัวอย่างจาก RFC 7636 Appendix B (ไม่ใช่ secret จริง)
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",  # pragma: allowlist secret
            "scope": sub.scope or "openid",
            "state": "browser_state_xyz",
            "redirect_uri": sub.redirect_uris[0],
        },
        risk_score=0.72,
        risk_breakdown={"rule": 0.30, "behavior": 0.20, "iforest": 0.22},
        risk_reasons=["is_new_device (+0.30)", "is_new_country (+0.20)"],
        provider="google",
        kind=kind,
        flow="subsystem",
    )

    page = "risk-stepup" if kind == "reauth" else "force-enroll"
    url = f"{HUB}/auth/passkey/{page}?challenge={cid}"
    print("\n" + "=" * 64)
    print(f"  kind     : {kind}")
    print(f"  user     : {user.email}")
    print(f"  subsystem: {sub.name}")
    print("  TTL      : 5 นาที")
    print("=" * 64)
    print(f"\n  เปิด browser:\n  {url}\n")
    return 0


def cid_suffix() -> str:
    import secrets

    return secrets.token_hex(4)


if __name__ == "__main__":
    sys.exit(main())
