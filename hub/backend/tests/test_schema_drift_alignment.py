"""ปิด drift ระหว่าง models / migration chain / hub_db ที่พบตอนทำ baseline (2026-09-22) — RED ก่อนแก้.

พบด้วย scripts/test/verify_migrations.sh (ฐานว่าง -> head เทียบกับ hub_schema.sql ทีละรายการ)
และ `alembic check`:

1. `login_sessions.is_attack_ip` / `is_account_takeover` — hub_db มี DEFAULT false แต่ migration chain
   ไม่มี · `subsystems.allowed_roles` default เป็น `'{user}'::text[]` ใน hub_db แต่ chain ได้
   `'{user}'::character varying[]` → ผู้ใช้เลือกแก้ด้วย migration ใหม่ที่ทำให้ทุกฐานเหมือนกัน
2. `user_totp_credentials.user_id` — model ประกาศ unique index แต่ migration a1b2 และ hub_db ใช้
   UNIQUE constraint + index ธรรมดา → ผู้ใช้เลือกแก้ model ให้ตรงฐานข้อมูล (ไม่แตะ DB)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import UniqueConstraint

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "alembic" / "versions"


def _alignment_migration():
    files = [f for f in VERSIONS.glob("*_align_schema_drift.py")]
    assert len(files) == 1, f"ต้องมี migration align_schema_drift หนึ่งไฟล์ (ได้ {files})"
    spec = importlib.util.spec_from_file_location("align_drift", files[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_totp_user_id_is_a_named_unique_constraint_plus_plain_index():
    from app.models import UserTotpCredential

    table = UserTotpCredential.__table__
    uniques = [
        c
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
        and [col.name for col in c.columns] == ["user_id"]
    ]
    assert [c.name for c in uniques] == ["user_totp_credentials_user_id_key"]
    idx = [i for i in table.indexes if [c.name for c in i.columns] == ["user_id"]]
    assert len(idx) == 1 and idx[0].unique is False
    assert idx[0].name == "ix_user_totp_credentials_user_id"
    assert table.c.user_id.unique is not True  # ไม่งั้น SQLAlchemy จะสร้าง unique index ซ้อน


def test_login_session_flags_default_to_false_on_the_server():
    from app.models import LoginSession

    for name in ("is_attack_ip", "is_account_takeover"):
        col = LoginSession.__table__.c[name]
        assert col.server_default is not None, f"{name} ต้องมี server_default"
        assert "false" in str(col.server_default.arg).lower()


def test_alignment_migration_follows_the_current_head_and_changes_defaults_only():
    m = _alignment_migration()
    assert m.down_revision == "f6a7b8c9d0e1"  # pragma: allowlist secret
    src = Path(m.__file__).read_text(encoding="utf-8")
    assert "SET DEFAULT false" in src
    assert "'{user}'::character varying[]" in src
    # ห้ามแตะข้อมูลหรือโครงสร้างอื่น — เป็น migration ปิด drift ของ default เท่านั้น
    for forbidden in ("drop_table", "drop_column", "DELETE", "UPDATE ", "create_table"):
        assert forbidden not in src, forbidden
