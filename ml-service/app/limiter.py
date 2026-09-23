"""จำกัดคำขอ L3 ที่ค้างพร้อมกันต่อผู้ใช้ ภายใน process เดียว (ML Capacity Gate §25, 2026-09-22).

ที่มา: แบ่ง worker ตามผู้ใช้แล้ว ผู้ใช้คนเดียวที่ยิงถี่ลง worker เดียวทั้งหมด ทำให้ผู้ใช้อื่นบน worker
เดียวกันช้าตาม (p95 289–312 ms, §24.4) · จำกัดที่ ml-service เพราะเป็นจุดเดียวที่รู้ว่า worker นี้
กำลังทำงานให้ผู้ใช้คนไหนอยู่ · คำขอที่เกินเพดานไม่เรียกโมเดล และ hub ถือเป็น L3 abstain ธรรมดา
(login ไม่ถูกจำกัด)

ไม่เก็บผู้ใช้ที่ไม่มีคำขอค้าง → dict ไม่โตตามจำนวนผู้ใช้
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

LIMIT_ENV = "L3_PER_USER_MAX_INFLIGHT"
DEFAULT_LIMIT = 2
MAX_LIMIT = 50


def limit_from_env() -> int:
    """ค่าผิด = ValueError (main.startup เรียกก่อนรับงาน → ไม่ start)."""
    raw = os.getenv(LIMIT_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_LIMIT
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if not (1 <= value <= MAX_LIMIT):
        raise ValueError(f"{LIMIT_ENV} ต้องเป็นจำนวนเต็ม 1–{MAX_LIMIT} (ได้ {raw!r})")
    return value


class PerUserLimiter:
    def __init__(self, limit: int):
        if not (1 <= limit <= MAX_LIMIT):
            raise ValueError(f"limit ต้องอยู่ในช่วง 1–{MAX_LIMIT}")
        self.limit = limit
        self._lock = threading.Lock()
        self._inflight: dict[str, int] = {}
        self._refused = 0

    def try_acquire(self, user_id: str) -> bool:
        with self._lock:
            n = self._inflight.get(user_id, 0)
            if n >= self.limit:
                self._refused += 1
                return False
            self._inflight[user_id] = n + 1
            return True

    def release(self, user_id: str) -> None:
        with self._lock:
            n = self._inflight.get(user_id, 0) - 1
            if n > 0:
                self._inflight[user_id] = n
            else:
                self._inflight.pop(user_id, None)

    @contextmanager
    def slot(self, user_id: str) -> Iterator[bool]:
        ok = self.try_acquire(user_id)
        try:
            yield ok
        finally:
            if ok:
                self.release(user_id)

    def in_flight(self, user_id: str) -> int:
        with self._lock:
            return self._inflight.get(user_id, 0)

    def tracked_users(self) -> int:
        with self._lock:
            return len(self._inflight)

    @property
    def refused(self) -> int:
        with self._lock:
            return self._refused
