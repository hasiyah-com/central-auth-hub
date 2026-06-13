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

import sys
from pathlib import Path

# เพิ่ม /app เข้า sys.path เพื่อ import app.* ได้
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


# ─────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def auth_headers():
    """ใช้: headers=auth_headers(admin_token) → {"Authorization": "Bearer ..."}"""

    def _make(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    return _make
