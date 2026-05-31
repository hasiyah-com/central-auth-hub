"""Background scheduler — สแกน request_logs ทุก N นาทีอัตโนมัติ.

เริ่มทำงานตอน app startup ผ่าน lifespan, หยุดเมื่อ shutdown.
ใช้ asyncio.sleep — ไม่ต้องเพิ่ม dependency ใหม่.

อ้างอิง: NIST SP 800-228 — continuous telemetry monitoring
"""

import asyncio
import logging
from datetime import datetime

from app.database import SessionLocal
from app.services.api_guard import scan_and_persist

logger = logging.getLogger(__name__)

# ค่า default — override ผ่าน start() parameter ได้
DEFAULT_INTERVAL_SEC = 5 * 60  # 5 นาที
DEFAULT_SCAN_WINDOW_MIN = 5  # สแกนย้อนหลัง 5 นาที

_task: asyncio.Task | None = None


async def _loop(interval_sec: int, scan_window_min: int) -> None:
    """Loop สแกน request_logs ทุก interval_sec วินาที (fail-safe)."""
    logger.info(
        "[api_guard] auto-scan started: every %ds, window %dm",
        interval_sec,
        scan_window_min,
    )
    while True:
        await asyncio.sleep(interval_sec)
        try:
            db = SessionLocal()
            try:
                new_alerts = scan_and_persist(db, scan_window_min)
                if new_alerts:
                    logger.warning(
                        "[api_guard] auto-scan found %d new alert(s) at %s",
                        len(new_alerts),
                        datetime.utcnow().isoformat(),
                    )
                else:
                    logger.debug("[api_guard] auto-scan: no new alerts")
            finally:
                db.close()
        except Exception as e:
            # Fail-safe: ไม่ให้ scheduler ตาย
            logger.exception("[api_guard] auto-scan error: %s", e)


def start(
    interval_sec: int = DEFAULT_INTERVAL_SEC,
    scan_window_min: int = DEFAULT_SCAN_WINDOW_MIN,
) -> None:
    """เรียกจาก lifespan startup — สร้าง background task."""
    global _task
    if _task is not None:
        return  # ป้องกันเรียกซ้ำ
    loop = asyncio.get_running_loop()
    _task = loop.create_task(_loop(interval_sec, scan_window_min))


def stop() -> None:
    """เรียกจาก lifespan shutdown — ยกเลิก task."""
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
