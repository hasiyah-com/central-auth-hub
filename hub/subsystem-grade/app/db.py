"""SQLite store ของระบบเกรด — ตาราง grades ผูกด้วย hub_user_id.

hub_user_id = JWT.sub ของ Hub (UUID) — ไม่มี FK ไป Hub (subsystem เป็นอิสระ),
เก็บเป็น anchor สำหรับ match ตอน login. เกรดถูก pre-create จาก roster ก่อน
student login (นี่คือจุดขายของ Roster Sync — JIT provisioning อย่างเดียวไม่พอ).
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS grades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hub_user_id   TEXT NOT NULL,
    email         TEXT,
    subject_code  TEXT NOT NULL,
    subject_name  TEXT NOT NULL,
    grade         TEXT NOT NULL,
    credits       INTEGER NOT NULL DEFAULT 3,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(hub_user_id, subject_code)
);
CREATE INDEX IF NOT EXISTS ix_grades_hub_user ON grades(hub_user_id);

-- Hub webhook แจ้งว่า user ต้อง re-auth (scope/role เปลี่ยน หรือ revoke) —
-- session ที่ออกก่อน reauth_after (epoch) ถือว่าหมดสิทธิ์ → เด้งไป login.
-- ใช้ epoch เทียบกับ session issued-time (itsdangerous timestamp) ตรงๆ
CREATE TABLE IF NOT EXISTS revocations (
    hub_user_id  TEXT PRIMARY KEY,
    reauth_after INTEGER NOT NULL
);
"""


def init_db() -> None:
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def _connect():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def grades_for(hub_user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT subject_code, subject_name, grade, credits "
            "FROM grades WHERE hub_user_id = ? ORDER BY subject_code",
            (hub_user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_grade(
    hub_user_id: str,
    email: str | None,
    subject_code: str,
    subject_name: str,
    grade: str,
    credits: int = 3,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO grades (hub_user_id, email, subject_code, subject_name, grade, credits) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(hub_user_id, subject_code) DO UPDATE SET grade=excluded.grade",
            (hub_user_id, email, subject_code, subject_name, grade, credits),
        )


# sentinel — global re-auth (config ทั้งระบบเปลี่ยน เช่น scope) เด้งทุกคน
GLOBAL_REAUTH = "__ALL__"


def set_reauth(hub_user_id: str) -> None:
    """mark ว่า user คนนี้ต้อง re-auth ตั้งแต่ตอนนี้ (session เก่าใช้ไม่ได้)."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO revocations (hub_user_id, reauth_after) VALUES (?, ?) "
            "ON CONFLICT(hub_user_id) DO UPDATE SET reauth_after=excluded.reauth_after",
            (hub_user_id, int(time.time())),
        )


def reauth_after(hub_user_id: str) -> int | None:
    """epoch ที่ต้อง re-auth หลังจากนั้น — None ถ้าไม่มี revocation."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT reauth_after FROM revocations WHERE hub_user_id = ?",
            (hub_user_id,),
        ).fetchone()
    return row["reauth_after"] if row else None


def clear_reauth(hub_user_id: str) -> None:
    """ยกเลิก revocation (เช่น Hub ส่ง access_restored)."""
    with _connect() as conn:
        conn.execute("DELETE FROM revocations WHERE hub_user_id = ?", (hub_user_id,))


def stats() -> dict:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0]
        students = conn.execute(
            "SELECT COUNT(DISTINCT hub_user_id) FROM grades"
        ).fetchone()[0]
    return {"total_grades": total, "students": students}


def delete_grades_for(hub_user_id: str) -> int:
    """ลบเกรดทั้งหมดของ user คนหนึ่ง — ใช้ล้าง record ที่สร้างผิด (เช่น teacher
    ที่เคยโดน sync สร้างเกรดให้ตอนก่อนแก้ filter ใน roster.sync())."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM grades WHERE hub_user_id = ?", (hub_user_id,))
        return cur.rowcount


def all_students(q: str | None = None) -> list[dict]:
    """รายชื่อนักศึกษาที่มีเกรด (มุมมองอาจารย์ — เห็นทุกคน).

    q = ค้นหาบางส่วนของ email (optional). ไม่มีชื่อจริงเก็บไว้ในระบบนี้
    (roster ส่งมาแค่ user_id/email/user_type — data minimization ตาม Hub) —
    ใช้ email เป็นตัวระบุตัวตนแทน
    """
    with _connect() as conn:
        sql = "SELECT DISTINCT hub_user_id, email FROM grades"
        params: tuple = ()
        if q:
            sql += " WHERE email LIKE ?"
            params = (f"%{q}%",)
        sql += " ORDER BY email"
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
