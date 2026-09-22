"""schema snapshot ที่ CI ใช้สร้างฐานข้อมูลเทส — ต้องตรงกับ alembic head เสมอ (RED ก่อน).

ที่มา (2026-09-22): Backend CI ใช้ `hub_db` + Redis DB 0 → ตัวกัน env ปฏิเสธทุกรอบ · แก้เป็น
`hub_test` + DB 15 แล้ว แต่ CI สร้าง schema ด้วย `create_all` ซึ่ง**ไม่สร้าง trigger/server default**
ที่ migration ของ Expert Review สร้าง → เทสด้าน integrity ล้ม 5 ตัว · ตั้งแต่ B80 CI สร้างฐานด้วย
`alembic upgrade head` จากฐานว่าง แล้วเทียบกับ snapshot นี้ทีละรายการ

ในเครื่อง `setup_test_db.sh` clone schema จาก `hub_db` ด้วย `pg_dump -s` · CI จึงใช้ snapshot ของ
schema เดียวกันที่เก็บใน repo (`tests/support/schema/hub_schema.sql`) เป็นตัวอ้างอิง ·
ความเสี่ยงคือ snapshot เก่ากว่า migration — เทสนี้บังคับให้ head ใน snapshot ตรงกับ head จริง
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SNAPSHOT = BACKEND / "tests" / "support" / "schema" / "hub_schema.sql"


def _alembic_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"alembic มีหลาย head: {heads}"
    return heads[0]


def test_snapshot_exists():
    assert SNAPSHOT.exists(), f"ไม่พบ {SNAPSHOT}"


def test_snapshot_is_at_the_current_alembic_head():
    text = SNAPSHOT.read_text(encoding="utf-8")
    m = re.search(r"^-- alembic head: (\w+)$", text, re.MULTILINE)
    assert m, "snapshot ต้องมีบรรทัด '-- alembic head: <rev>'"
    assert (
        m.group(1) == _alembic_head()
    ), "schema snapshot เก่ากว่า migration — รัน scripts/test/dump_test_schema.sh ใหม่"


def test_snapshot_is_schema_only():
    """ห้ามมีข้อมูล — COPY/INSERT หมายถึง dump มีแถวของจริงติดมา."""
    text = SNAPSHOT.read_text(encoding="utf-8")
    assert not re.search(r"^(COPY|INSERT INTO) ", text, re.MULTILINE)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "พบรูปแบบอีเมลใน snapshot"


def test_snapshot_contains_the_expert_review_protections():
    """ของที่ create_all ไม่สร้าง แต่เทส integrity ต้องใช้."""
    text = SNAPSHOT.read_text(encoding="utf-8")
    assert "CREATE TRIGGER" in text
    assert "CREATE FUNCTION" in text or "CREATE OR REPLACE FUNCTION" in text
