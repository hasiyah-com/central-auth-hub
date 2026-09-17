"""lock กันรันชุดเทสซ้อนกันบน Redis DB ของเทส.

ทำไมต้องมี: key บางกลุ่มไม่ได้อยู่ใน namespace ของรอบ —
  * `l3resid:` / `l3dup:` เป็นสัญญาข้ามบริการกับ ml-service
  * `LIMITS:` เขียนโดย slowapi ผ่าน storage_uri ของตัวเอง
ดังนั้นการมี namespace ต่อรอบยัง **ไม่พอ** ที่จะรันหลายรอบพร้อมกันได้อย่างปลอดภัย
ฐานข้อมูล `hub_test` ก็ถูก drop/create ตอน setup จึงรันซ้อนไม่ได้อยู่แล้ว

lock มี TTL เสมอ เพื่อไม่ให้รอบที่ crash ค้างจนรอบถัดไปรันไม่ได้ถาวร
"""

from __future__ import annotations

LOCK_KEY = "test:lock"
DEFAULT_TTL = 3600


class TestRunLocked(RuntimeError):
    """มีชุดเทสรอบอื่นถือ lock อยู่."""


def acquire(client, run_id: str, ttl: int = DEFAULT_TTL) -> None:
    got = client.set(LOCK_KEY, run_id, nx=True, ex=ttl)
    if got:
        return
    holder = client.get(LOCK_KEY)
    raise TestRunLocked(
        f"มีชุดเทสอีกรอบกำลังใช้ Redis/ฐานข้อมูลของเทสอยู่ (run_id={holder!r}) — "
        f"รอให้จบก่อน หรือถ้าแน่ใจว่าค้างให้ลบ key '{LOCK_KEY}' ทิ้ง"
    )


def release(client, run_id: str) -> bool:
    """ปลด lock เฉพาะเจ้าของ — คืน False ถ้าไม่ใช่ของตัวเอง."""
    holder = client.get(LOCK_KEY)
    if holder is not None and str(holder) != str(run_id):
        return False
    client.delete(LOCK_KEY)
    return True
