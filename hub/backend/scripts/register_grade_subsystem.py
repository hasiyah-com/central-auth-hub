"""ลงทะเบียน "ระบบเกรด" (Grade System) เป็น subsystem ใน Hub — สำหรับ demo Roster Sync.

สร้าง Subsystem row พร้อม client credentials (OAuth login) + API key (roster pull)
แล้ว print ค่า plaintext ครั้งเดียว → เอาไปใส่ .env ของ grade app.

access_policy = "role" (student + teacher) — เกรดเป็นข้อมูลของนักศึกษา แต่ teacher
ต้อง login เข้าดูมุมมองอาจารย์ได้ด้วย (ดู app/roster.py:sync() docstring) Roster API
จะคืนทั้ง 2 role ตาม policy นี้ แล้ว roster.py กรอง user_type == "student" เอง
ตอน pre-create ตารางเกรด (เกรดยังเป็นข้อมูลของนักศึกษาเท่านั้น).

idempotent: ถ้ามี client_id นี้อยู่แล้ว → rotate secret + api key ใหม่ (ค่าเก่าใช้ไม่ได้).

รัน (dev — default localhost:8003):
  docker compose exec hub-backend python -m scripts.register_grade_subsystem

รัน (prod — redirect URI ตาม subdomain จริง):
  GRADE_REDIRECT_URI=https://grade.<domain>/oauth/callback \
    docker compose --env-file .env.prod -f docker-compose.prod.yml \
    exec hub-backend python -m scripts.register_grade_subsystem
"""

from __future__ import annotations

import os
from datetime import datetime

from app.database import SessionLocal
from app.models import Subsystem, User
from app.services.secret_service import generate_api_key, hash_secret
import secrets

CLIENT_ID = "cli_grade"
NAME = "ระบบเกรด (Grade System)"
REDIRECT_URI = os.environ.get(
    "GRADE_REDIRECT_URI", "http://localhost:8003/oauth/callback"
)
SCOPE = ["openid", "email", "profile"]
ACCESS_POLICY = "role"
ACCESS_POLICY_CONFIG = {"roles": ["student", "teacher"]}


def main() -> None:
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.is_hub_admin.is_(True)).first()
        if not owner:
            raise SystemExit("ไม่พบ admin ใน DB — seed users ก่อน")

        client_secret = secrets.token_urlsafe(32)
        api_key_plain, api_key_prefix = generate_api_key()

        sub = db.query(Subsystem).filter(Subsystem.client_id == CLIENT_ID).first()
        if sub:
            action = "rotated"
            sub.client_secret_hash = hash_secret(client_secret)
            sub.api_key_hash = hash_secret(api_key_plain)
            sub.api_key_prefix = api_key_prefix
            sub.redirect_uris = [REDIRECT_URI]
            sub.scope = SCOPE
            sub.access_policy = ACCESS_POLICY
            sub.access_policy_config = ACCESS_POLICY_CONFIG
            sub.status = "active"
            sub.approved_at = datetime.utcnow()
        else:
            action = "created"
            sub = Subsystem(
                name=NAME,
                description="ระบบจัดการเกรด — demo Roster Sync (ดึงรายชื่อ pre-create เกรด)",
                client_id=CLIENT_ID,
                client_secret_hash=hash_secret(client_secret),
                redirect_uris=[REDIRECT_URI],
                scope=SCOPE,
                allowed_roles=["student", "teacher"],
                access_policy=ACCESS_POLICY,
                access_policy_config=ACCESS_POLICY_CONFIG,
                api_key_hash=hash_secret(api_key_plain),
                api_key_prefix=api_key_prefix,
                status="active",
                owner_user_id=owner.id,
                approved_at=datetime.utcnow(),
            )
            db.add(sub)
        db.commit()
        db.refresh(sub)

        print("=" * 64)
        print(f"  ระบบเกรด {action} สำเร็จ (subsystem_id={sub.id})")
        print("=" * 64)
        print("  ใส่ค่าต่อไปนี้ใน hub/subsystem-grade/.env (แสดงครั้งเดียว):")
        print()
        print(f"  GRADE_CLIENT_ID={CLIENT_ID}")
        print(f"  GRADE_CLIENT_SECRET={client_secret}")
        print(f"  GRADE_ROSTER_API_KEY={api_key_plain}")
        print()
        print(f"  access_policy = {ACCESS_POLICY} {ACCESS_POLICY_CONFIG}")
        print(f"  redirect_uri  = {REDIRECT_URI}")
        print("=" * 64)
    finally:
        db.close()


if __name__ == "__main__":
    main()
