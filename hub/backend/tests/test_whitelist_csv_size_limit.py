"""จำกัดขนาดไฟล์ CSV whitelist upload — กัน memory DoS.

เดิม `file.file.read()` โหลดทั้งไฟล์เข้า memory ไม่จำกัด → developer ที่ login แล้ว
อัปโหลดไฟล์ใหญ่ทำ RAM พุ่ง/ระบบช้าได้. `_read_capped` อ่านแบบมีเพดาน → เกิน = 413.

รัน:
    docker compose exec hub-backend pytest tests/test_whitelist_csv_size_limit.py -v
"""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException

from app.routers.developer import WHITELIST_CSV_MAX_BYTES, _read_capped


def test_reads_small_file_ok():
    data = _read_capped(io.BytesIO(b"email,role\na@x.ac.th,user\n"), 1000)
    assert data == b"email,role\na@x.ac.th,user\n"


def test_reads_at_exactly_max_ok():
    payload = b"a" * 1000
    assert _read_capped(io.BytesIO(payload), 1000) == payload


def test_rejects_over_max_with_413():
    with pytest.raises(HTTPException) as ei:
        _read_capped(io.BytesIO(b"a" * 1001), 1000)
    assert ei.value.status_code == 413


def test_does_not_load_more_than_cap_into_memory():
    # ไฟล์ใหญ่กว่าเพดานมาก — helper ต้องไม่ดึงเกิน cap+1 เข้า memory
    huge = io.BytesIO(b"x" * (5 * 1024 * 1024))
    with pytest.raises(HTTPException) as ei:
        _read_capped(huge, 1024)
    assert ei.value.status_code == 413
    # อ่านไปแค่ ~cap+1 ไม่ใช่ทั้ง 5MB (cursor ไม่ถึงท้าย)
    assert huge.tell() <= 1024 + 1


def test_default_cap_is_reasonable():
    # เพดาน default ต้องมีจริงและไม่เล็กเกินไป (>= 256KB) / ไม่ใหญ่เว่อร์ (<= 10MB)
    assert 256 * 1024 <= WHITELIST_CSV_MAX_BYTES <= 10 * 1024 * 1024
