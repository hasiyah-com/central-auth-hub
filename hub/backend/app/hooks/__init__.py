"""Default listeners — register ที่ startup จาก main.py

วิธีเพิ่ม listener ใหม่:
  1. สร้าง <ชื่อ>_listener.py พร้อม register_listeners() function
  2. เพิ่มใน register_default_listeners() ด้านล่าง
"""
import logging

from app.config import settings
from app.hooks import metrics_listener, security_listener
from app.services.hooks import listeners_count

logger = logging.getLogger(__name__)


def register_default_listeners() -> None:
    """เรียกครั้งเดียวตอน startup. Idempotent ไม่ได้ — ห้ามเรียกซ้ำ."""
    metrics_listener.register_listeners()
    security_listener.register_listeners()

    # dev logger เฉพาะ development — ไม่ noise production log
    if settings.app_env == "development":
        from app.hooks import dev_logger_listener
        dev_logger_listener.register_listeners()

    logger.info("hook listeners registered: %d total", listeners_count())
