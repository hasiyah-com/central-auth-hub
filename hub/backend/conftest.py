"""Shared pytest fixtures for Central Auth Hub backend tests.

Fixtures:
  - client: TestClient(app) — FastAPI test client
  - db: SQLAlchemy session connected to live Postgres (Hub DB)
  - admin_user, teacher_user, staff_user, student_user — fetched from seeded DB
  - admin_token, teacher_token, staff_token — JWT issued by jwt_service
  - auth_headers(token) — helper สำหรับ Authorization header

ใช้ live DB เพราะ:
  - SQLAlchemy ARRAY/JSONB/INET ใช้ SQLite ไม่ได้
  - dev DB seeded แล้ว (100 users) — ไม่ต้องสร้าง fixtures เอง
  - tests ไม่แก้ data (read-only หรือ rollback-safe)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# เพิ่ม /app เข้า sys.path เพื่อ import app.* ได้
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Guard: ห้ามรันเทสบนฐานข้อมูล/Redis ของ dev (fail-closed ไม่มีทางข้าม) ──
# ต้องทำก่อน import app.database / app.main เพราะสองตัวนั้นผูก engine กับ URL ทันที
from app.config import settings  # noqa: E402
from tests.support.env_guard import assert_test_environment  # noqa: E402

assert_test_environment(
    database_url=settings.database_url,
    redis_url=settings.redis_url,
    env=os.environ,
)

# ── Redis namespace ต่อรอบ — ทุก key ของรอบนี้ขึ้นต้นด้วย test:{run_id}: ──
# patch ก่อน import app.main เพราะโมดูลปลายทาง `from app.redis_client import redis_client`
# ผูกกับ object ตั้งแต่ตอน import
import app.redis_client as _redis_module  # noqa: E402
from tests.support.redis_namespace import (  # noqa: E402
    NamespacedRedis,
    namespace_prefix,
    new_run_id,
)

TEST_RUN_ID = os.environ.get("TEST_RUN_ID") or new_run_id()
TEST_NAMESPACE = namespace_prefix(TEST_RUN_ID)
if not isinstance(_redis_module.redis_client, NamespacedRedis):
    _redis_module.redis_client = NamespacedRedis(
        _redis_module.redis_client, TEST_NAMESPACE
    )

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.services.jwt_service import create_access_token  # noqa: E402


# ─────────────────────────────────────────────────────────────
# Core fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI TestClient — reuse across all tests ใน session."""
    return TestClient(app)


@pytest.fixture
def db() -> Session:
    """SQLAlchemy session — open ก่อนเทสต์, close หลังเทสต์."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# User fixtures (ดึงจาก seeded data — ไม่สร้างใหม่)
# ─────────────────────────────────────────────────────────────


def _find_user(db: Session, user_type: str) -> User | None:
    """หา user คนแรกตาม user_type — ถ้าไม่มี return None."""
    return (
        db.query(User)
        .filter(User.user_type == user_type, User.status == "active")
        .first()
    )


@pytest.fixture
def admin_user(db: Session) -> User:
    u = _find_user(db, "admin")
    if not u:
        pytest.skip("ไม่พบ admin user ใน DB — รัน seed_users ก่อน")
    return u


@pytest.fixture
def teacher_user(db: Session) -> User:
    u = _find_user(db, "teacher")
    if not u:
        pytest.skip("ไม่พบ teacher user ใน DB — รัน seed_users ก่อน")
    return u


@pytest.fixture
def staff_user(db: Session) -> User:
    u = _find_user(db, "staff")
    if not u:
        pytest.skip("ไม่พบ staff user ใน DB — รัน seed_users ก่อน")
    return u


@pytest.fixture
def student_user(db: Session) -> User:
    u = _find_user(db, "student")
    if not u:
        pytest.skip("ไม่พบ student user ใน DB — รัน seed_users ก่อน")
    return u


# ─────────────────────────────────────────────────────────────
# Token fixtures (ออก JWT จริงผ่าน jwt_service)
# ─────────────────────────────────────────────────────────────


# create_access_token คืน tuple (token, jti) — unpack เอาเฉพาะ token string
@pytest.fixture
def admin_token(admin_user: User) -> str:
    token, _jti = create_access_token(admin_user)
    return token


@pytest.fixture
def teacher_token(teacher_user: User) -> str:
    token, _jti = create_access_token(teacher_user)
    return token


@pytest.fixture
def staff_token(staff_user: User) -> str:
    token, _jti = create_access_token(staff_user)
    return token


@pytest.fixture
def student_token(student_user: User) -> str:
    token, _jti = create_access_token(student_user)
    return token


# ─────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def auth_headers():
    """ใช้: headers=auth_headers(admin_token) → {"Authorization": "Bearer ..."}"""

    def _make(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """ล้างตัวนับ rate-limit ก่อนทุกเทสต์.

    ทั้ง suite ยิงจาก IP เดียว ("testclient") จึงใช้โควตาร่วมกัน — endpoint ที่จำกัดเข้ม
    (เช่น /auth/google/login 10/นาที, change-google 1/ชม.) จะถูกใช้หมดกลางรัน ทำให้เทสต์
    ที่มาทีหลัง fail แบบสุ่มตามลำดับ (ไม่ใช่บั๊กของโค้ด) — ล้างก่อนทุกเทสต์ให้ผลคงที่
    """
    try:
        from app.redis_client import redis_client

        # slowapi ต่อ Redis ด้วย storage_uri ของตัวเอง — key `LIMITS:*` จึงอยู่นอก
        # namespace ของรอบเทส ต้องล้างผ่าน client จริง
        raw = getattr(redis_client, "raw", redis_client)
        keys = list(raw.scan_iter(match="LIMITS:*", count=500))
        if keys:
            raw.delete(*keys)
    except Exception:  # noqa: BLE001 — ไม่มี Redis ก็ให้เทสต์เดินต่อ
        pass
    yield


# ─────────────────────────────────────────────────────────────
# ตรวจ state ก่อน/หลังรอบเทส + เครื่องมือวินิจฉัย
# (tests/support/state_invariant.py — เปิดด้วย TEST_DIAG / TEST_FORCE_FAIL)
# ─────────────────────────────────────────────────────────────

from tests.support import state_invariant as _state  # noqa: E402
from tests.support.redis_namespace import delete_namespace as _delete_namespace  # noqa: E402
from tests.support.redis_namespace import delete_shared_keys as _delete_shared  # noqa: E402
from tests.support.redis_namespace import keys_in_namespace as _keys_left  # noqa: E402
from tests.support import run_lock as _run_lock  # noqa: E402

_BASELINE: dict = {}


def _raw_redis():
    return getattr(_redis_module.redis_client, "raw", _redis_module.redis_client)


def pytest_sessionstart(session):
    # lock กันรันซ้อน — key l3resid/l3dup/LIMITS ไม่ได้อยู่ใน namespace ของรอบ
    # และ hub_test ถูก drop/create ตอน setup จึงรันสองรอบพร้อมกันไม่ได้
    _run_lock.acquire(_raw_redis(), TEST_RUN_ID)
    if os.environ.get("TEST_DIAG") == "1":
        _state.enable_diagnostics()
    _BASELINE["before"] = _state.snapshot(
        session_factory=SessionLocal,
        redis_raw=_raw_redis(),
        namespace=TEST_NAMESPACE,
        app=app,
    )


_MODULE: dict = {"name": None, "before": None}


def _module_snapshot():
    return _state.snapshot(
        session_factory=SessionLocal,
        redis_raw=_raw_redis(),
        namespace=TEST_NAMESPACE,
        app=app,
    )


def _finish_module():
    """เทียบ state ของไฟล์ที่เพิ่งจบ — ชี้ว่าไฟล์ไหนทิ้งข้อมูลไว้ (เฉพาะ TEST_DIAG=1)."""
    if _MODULE["name"] is None:
        return
    leaks = _state.diff(_MODULE["before"], _module_snapshot())
    if leaks:
        _state.record_module_leak(_MODULE["name"], leaks)
    _MODULE["name"] = None
    _MODULE["before"] = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _state.set_current_nodeid(item.nodeid)
    per_module = os.environ.get("TEST_DIAG") == "1"
    module = item.nodeid.split("::")[0]
    if per_module and _MODULE["name"] != module:
        _finish_module()
        _MODULE["name"] = module
        _MODULE["before"] = _module_snapshot()
    yield
    _state.set_current_nodeid(None)
    if per_module and (nextitem is None or nextitem.nodeid.split("::")[0] != module):
        _finish_module()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """TEST_FORCE_FAIL=<คำ> — บังคับให้เทสที่ตรงคำนั้นล้ม เพื่อพิสูจน์ว่า cleanup ยังทำงาน."""
    outcome = yield
    forced = os.environ.get("TEST_FORCE_FAIL")
    if forced and forced in item.nodeid and outcome.excinfo is None:
        outcome.force_exception(
            AssertionError(f"TEST_FORCE_FAIL: บังคับให้ {item.nodeid} ล้มเพื่อตรวจ cleanup")
        )


def pytest_sessionfinish(session, exitstatus):
    before = _BASELINE.get("before")
    if not before:
        return
    raw = _raw_redis()
    after = _state.snapshot(
        session_factory=SessionLocal,
        redis_raw=raw,
        namespace=TEST_NAMESPACE,
        app=app,
    )
    leaks = _state.diff(before, after)
    # แยกความรุนแรง: แถวใน DB ที่ค้าง = รั่วจริง (ข้ามรอบ) ส่วน key ใน namespace ของรอบนี้
    # มี TTL และถูกลบท้ายรอบอยู่แล้ว — รายงานไว้ดูว่าไฟล์ไหนทิ้งไว้ แต่ไม่ตัดสินว่าไม่ผ่าน
    # เกณฑ์จริงคือ "namespace ต้องว่างหลัง cleanup" ซึ่งตรวจด้านล่าง
    namespace_left = leaks.pop("redis_namespace_keys", None)
    print(_state.format_report(before, after, leaks))
    if namespace_left:
        print(f"  (key ใน namespace ระหว่างรอบ ซึ่งจะถูกลบท้ายรอบ: {namespace_left})")
    removed = _delete_namespace(raw, TEST_NAMESPACE) + _delete_shared(raw)
    if removed:
        print(f"ลบ key ของรอบนี้ {removed} รายการ (namespace {TEST_NAMESPACE})")
    left = _keys_left(raw, TEST_NAMESPACE)
    if left:
        print(f"เตือน: ลบ namespace ไม่หมด เหลือ {len(left)} key — {left[:5]}")
    _run_lock.release(raw, TEST_RUN_ID)
    if leaks or left:
        session.exitstatus = 1
