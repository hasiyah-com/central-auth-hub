"""Seed ข้อมูลคงที่ของฐานข้อมูลทดสอบ + พิมพ์ manifest.

`app.seeds.seed_users` สร้างผู้ใช้ให้แล้ว แต่ fixture หลายตัวต้องการ subsystem ที่ active
ถ้าไม่มีก็จะ skip — และจำนวน skip ที่ขยับไปมาคือสิ่งที่ทำให้ผลการรันเชื่อถือไม่ได้
manifest ใช้เทียบว่าทุกรอบเริ่มจากสถานะตั้งต้นเดียวกันจริง

สคริปต์นี้ **ปฏิเสธการรันบนฐานข้อมูลที่ไม่ได้ลงท้าย `_test`**

    python -m scripts.seed_test_fixtures
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Subsystem, User  # noqa: E402
from tests.support.env_guard import database_name  # noqa: E402

# client_secret_hash เป็นค่าหลอก — เทสที่ต้องใช้ secret จริงสร้าง subsystem ของตัวเอง
PLACEHOLDER_HASH = "not-a-real-hash"

SUBSYSTEMS = [
    {
        "name": "ระบบหอพัก (test)",
        "client_id": "cli_test_dorm",
        "status": "active",
        "redirect_uris": ["http://localhost:8001/oauth/callback"],
        "scope": ["email", "name"],
    },
    {
        "name": "ระบบห้องสมุด (test)",
        "client_id": "cli_test_library",
        "status": "active",
        "redirect_uris": ["http://localhost:8002/oauth/callback"],
        "scope": ["email", "name"],
    },
    {
        "name": "ระบบทดสอบ รออนุมัติ",
        "client_id": "cli_test_pending",
        "status": "pending",
        "redirect_uris": ["http://localhost:8003/oauth/callback"],
        "scope": ["email"],
    },
]


def _guard() -> None:
    name = database_name(settings.database_url)
    if not name.endswith("_test"):
        raise SystemExit(
            f"ปฏิเสธ: seed_test_fixtures รันได้เฉพาะฐานข้อมูลที่ลงท้าย '_test' — ได้ {name!r}"
        )


def seed_subsystems(db) -> int:
    owner = (
        db.query(User).filter(User.user_type == "teacher").order_by(User.email).first()
    )
    created = 0
    for spec in SUBSYSTEMS:
        exists = (
            db.query(Subsystem).filter(Subsystem.client_id == spec["client_id"]).first()
        )
        if exists:
            continue
        db.add(
            Subsystem(
                name=spec["name"],
                client_id=spec["client_id"],
                client_secret_hash=PLACEHOLDER_HASH,
                redirect_uris=spec["redirect_uris"],
                scope=spec["scope"],
                status=spec["status"],
                owner_user_id=owner.id if owner else None,
            )
        )
        created += 1
    db.commit()
    return created


def manifest(db) -> dict:
    users = {
        f"{t}:{s}": n
        for t, s, n in db.query(User.user_type, User.status, func.count(User.id))
        .group_by(User.user_type, User.status)
        .all()
    }
    subs = {
        s: n
        for s, n in db.query(Subsystem.status, func.count(Subsystem.id))
        .group_by(Subsystem.status)
        .all()
    }
    body = {
        "database": database_name(settings.database_url),
        "users": dict(sorted(users.items())),
        "subsystems": dict(sorted(subs.items())),
    }
    body["sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    return body


def main() -> int:
    _guard()
    db = SessionLocal()
    try:
        created = seed_subsystems(db)
        print(f"สร้าง subsystem ใหม่ {created} รายการ")
        print(json.dumps(manifest(db), ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
