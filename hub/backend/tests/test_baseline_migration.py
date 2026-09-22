"""baseline migration 609c11174142 ต้องเริ่มจากฐานข้อมูลว่างได้ — เขียนก่อน implementation (RED).

ที่มา: `609c11174142` เป็น diff จากฐานข้อมูลเดิมที่ create_all สร้างไว้ (drop mfa_challenges, drop/สร้าง
index) จึงรันบนฐานว่างไม่ได้ · CI ต้องโหลด snapshot ของ head แทน

ข้อกำหนด (ผู้ใช้อนุมัติ 2026-09-22):
  - DB ว่าง (ไม่มีตารางของแอปเลย) → สร้างจาก snapshot คงที่ของ schema **หลัง baseline**
    (สร้างจาก models ที่ commit `da0003b`) — ห้ามใช้ snapshot ของ head
  - DB สภาพเดิมที่รองรับ → เส้นทาง diff เดิม
  - มีตารางบางส่วน → หยุดแบบ fail-closed พร้อมข้อความชัดเจน
  - ห้าม import models ปัจจุบันหรือเรียก create_all() จาก migration

การรันจริงบนฐานข้อมูลอยู่ใน scripts/test/verify_migrations.sh
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "609c11174142_baseline_current_schema.py"
SNAPSHOT = ROOT / "alembic" / "baseline" / "baseline_609c11174142.sql"


def _module():
    spec = importlib.util.spec_from_file_location("baseline_609c", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── สามสภาพของฐานข้อมูล ────────────────────────────────────────────────────


def test_empty_database_takes_the_snapshot_path():
    assert _module().classify(set()) == "empty"


def test_alembic_version_alone_counts_as_empty():
    assert _module().classify({"alembic_version"}) == "empty"


def test_legacy_database_takes_the_diff_path():
    m = _module()
    assert (
        m.classify(set(m.LEGACY_REQUIRED) | {"audit_logs", "alembic_version"})
        == "legacy"
    )


@pytest.mark.parametrize("drop", ["mfa_challenges", "users", "passkey_credentials"])
def test_partial_database_is_refused(drop):
    m = _module()
    tables = set(m.LEGACY_REQUIRED) - {drop}
    assert m.classify(tables) == "partial"


def test_database_built_at_head_without_stamp_is_refused():
    """create_all ของ models ปัจจุบันไม่มี mfa_challenges → ไม่ใช่สภาพเดิม · ต้อง stamp เอง."""
    m = _module()
    tables = (set(m.LEGACY_REQUIRED) - {"mfa_challenges"}) | {"expert_reviews"}
    assert m.classify(tables) == "partial"


def test_partial_error_message_names_the_missing_tables():
    m = _module()
    with pytest.raises(RuntimeError, match="mfa_challenges") as e:
        m.refuse_partial(set(m.LEGACY_REQUIRED) - {"mfa_challenges"})
    assert "stamp" in str(e.value)


def test_legacy_tables_are_the_ones_the_diff_path_touches():
    m = _module()
    assert {
        "mfa_challenges",
        "login_sessions",
        "passkey_backup_codes",
        "passkey_credentials",
        "subsystem_change_requests",
        "subsystems",
        "users",
    } <= set(m.LEGACY_REQUIRED)


# ── snapshot ──────────────────────────────────────────────────────────────


def test_snapshot_file_exists_and_is_not_the_head_snapshot():
    text = SNAPSHOT.read_text(encoding="utf-8")
    assert "CREATE TABLE" in text
    # ตารางที่ migration รุ่นหลังสร้าง ต้องไม่อยู่ใน baseline
    for later in ("expert_reviews", "expert_alert_groups", "system_dispositions"):
        assert later not in text, f"{later} มาจาก migration รุ่นหลัง ห้ามอยู่ใน baseline"
    # คอลัมน์ที่ migration รุ่นหลังเพิ่ม
    for col in ("refresh_id", "last_seen_at", "hybrid_shadow_score"):
        assert col not in text, f"{col} มาจาก migration รุ่นหลัง ห้ามอยู่ใน baseline"
    assert "mfa_challenges" not in text  # baseline drop ตารางนี้


def test_snapshot_records_its_source_commit():
    head = SNAPSHOT.read_text(encoding="utf-8").splitlines()[:5]
    assert any("da0003b" in line for line in head)


@pytest.mark.parametrize(
    "bad",
    [
        "SET search_path = '';",
        "SELECT pg_catalog.set_config('search_path', '', false);",
        "\\restrict abc",
        "CREATE TABLE public.alembic_version (x int);",
    ],
)
def test_snapshot_loader_refuses_session_changes_and_meta_commands(bad):
    m = _module()
    with pytest.raises(ValueError):
        m.snapshot_sql("CREATE TABLE users (id uuid);\n" + bad + "\n")


def test_snapshot_loader_accepts_the_committed_snapshot():
    m = _module()
    sql = m.snapshot_sql(SNAPSHOT.read_text(encoding="utf-8"))
    assert "CREATE TABLE" in sql


# ── ห้ามพึ่ง models ปัจจุบัน ───────────────────────────────────────────────


def test_migration_does_not_use_current_models():
    src = MIGRATION.read_text(encoding="utf-8")
    assert "create_all" not in src
    assert "from app" not in src and "import app" not in src
    assert "hub_schema.sql" not in src
