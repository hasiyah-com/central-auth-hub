"""Roster Sync — ดึงรายชื่อ student จาก Hub ผ่าน API key แล้ว pre-create ตารางเกรด.

นี่คือหัวใจของ demo: ข้อมูลเกรดถูกสร้าง**ก่อน** student login (ต่างจาก JIT ที่รอ
login ก่อนถึงสร้าง record). Roster คืนแค่ 3 field (user_id, email, user_type) —
พอสำหรับ pre-create anchor; ข้อมูลเต็ม (ชื่อ) ไหลตอน login ตาม JWT scope.

เกรดในตัวอย่างนี้ generate แบบ deterministic จาก hub_user_id (จะได้ค่าเดิมทุกครั้ง
ที่ sync — demo ซ้ำได้). ระบบจริงจะ import จากไฟล์/ฐานข้อมูลสำนักทะเบียนแทน.
"""

from __future__ import annotations

import hashlib

import httpx

from app.config import settings
from app import db

# วิชาตัวอย่างที่ทุกนักศึกษา "ลงทะเบียน" ในเทอมนี้
_SUBJECTS = [
    ("CS101", "Introduction to Programming", 3),
    ("CS201", "Data Structures", 3),
    ("MA111", "Calculus I", 3),
    ("EN101", "English Communication", 2),
]
_GRADE_SCALE = ["A", "B+", "B", "C+", "C", "D+", "D", "F"]


def _deterministic_grade(hub_user_id: str, subject_code: str) -> str:
    """เกรดคงที่ต่อ (user, วิชา) — sha256 → index ใน scale (demo ซ้ำได้)."""
    h = hashlib.sha256(f"{hub_user_id}:{subject_code}".encode()).hexdigest()
    return _GRADE_SCALE[int(h, 16) % len(_GRADE_SCALE)]


def fetch_roster() -> dict:
    """เรียก Hub GET /api/v1/roster ด้วย X-Api-Key (S2S ผ่าน internal URL)."""
    if not settings.grade_roster_api_key:
        raise RuntimeError("ยังไม่ได้ตั้ง GRADE_ROSTER_API_KEY — รัน register script ก่อน")
    with httpx.Client(timeout=10.0) as client:
        r = client.get(
            f"{settings.hub_internal_url}/api/v1/roster",
            headers={"X-Api-Key": settings.grade_roster_api_key},
        )
        r.raise_for_status()
        return r.json()


def sync() -> dict:
    """ดึง roster → pre-create เกรดทุกวิชาให้ "นักศึกษา" เท่านั้น. คืนสรุปผล.

    Access Policy ของ subsystem นี้เปิดทั้ง student + teacher (teacher ต้อง login
    ได้เพื่อดูมุมมองอาจารย์) → roster เลยคืนทั้ง 2 role ตาม policy จริง — แต่
    "เกรด" เป็น business data ของนักศึกษาเท่านั้น ต้องกรอง user_type ที่นี่เอง
    (แยกคนละชั้นกับ Access Policy ของ Hub — Hub ตัดสินว่า "เข้าระบบได้ไหม",
    subsystem ตัดสินว่า "ข้อมูลนี้เป็นของใคร")
    """
    data = fetch_roster()
    users = [u for u in data.get("users", []) if u.get("user_type") == "student"]
    created = 0
    for u in users:
        uid = u["user_id"]
        for code, name, credits in _SUBJECTS:
            db.upsert_grade(
                hub_user_id=uid,
                email=u.get("email"),
                subject_code=code,
                subject_name=name,
                grade=_deterministic_grade(uid, code),
                credits=credits,
            )
            created += 1
    return {
        "subsystem": data.get("subsystem"),
        "students": len(users),
        "grade_rows": created,
        "subjects": len(_SUBJECTS),
    }
