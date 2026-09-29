"""สร้างระบบย่อยอ้างอิง (หอพัก + ห้องสมุด) สถานะ active สำหรับ CI — ไม่ใช้กับ prod

เทส e2e / scope conformance ต้องมีระบบย่อยที่ active อย่างน้อย 2 ระบบ (ขอบเขตข้อ 5)
ใน dev/prod ระบบย่อยถูกลงทะเบียนผ่าน /developer/subsystems แล้ว admin อนุมัติ
CI เริ่มจากฐานว่างจึงสร้างตรงนี้ · client_secret สุ่มแล้วเก็บแค่ hash (ไม่ print)

idempotent: ข้ามถ้ามี client_id นี้อยู่แล้ว

รัน: python -m scripts.seed_ci_subsystems
"""

from __future__ import annotations

import secrets

from app.database import SessionLocal
from app.models import Subsystem, User
from app.services.secret_service import hash_secret

SUBSYSTEMS = [
    {
        "client_id": "cli_ci_dorm",
        "name": "ระบบหอพัก",
        "redirect_uris": ["http://localhost:8001/oauth/callback"],
        "allowed_roles": ["resident", "teacher", "staff"],
    },
    {
        "client_id": "cli_ci_library",
        "name": "ระบบห้องสมุด",
        "redirect_uris": ["http://localhost:8002/oauth/callback"],
        "allowed_roles": ["member", "librarian"],
    },
]


def main() -> None:
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.is_hub_admin.is_(True)).first()
        for spec in SUBSYSTEMS:
            if db.query(Subsystem).filter_by(client_id=spec["client_id"]).first():
                continue
            db.add(
                Subsystem(
                    **spec,
                    client_secret_hash=hash_secret(secrets.token_urlsafe(32)),
                    scope=["openid", "email", "profile"],
                    status="active",
                    access_policy="explicit",
                    owner_user_id=owner.id if owner else None,
                )
            )
        db.commit()
        n = db.query(Subsystem).filter(Subsystem.status == "active").count()
        print(f"active subsystems: {n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
