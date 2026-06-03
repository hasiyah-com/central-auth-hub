"""Structured JSON logging + contextvars (request_id, user_id).

ทำหน้าที่:
  - configure root logger ให้ emit JSON line ต่อ record (production)
  - dev mode = text format อ่านง่าย
  - inject request_id + user_id อัตโนมัติทุก log (ผ่าน contextvar)
  - replace stdlib uvicorn formatter ให้สอดคล้องกัน

ใช้ร่วมกับ:
  - request_id.py (middleware) — ตั้ง request_id ก่อน handler รัน
  - hooks ที่ขอเขียน log ใน scope ของ request

เรียก setup_logging() ครั้งเดียวที่ main.py ตอน import (ก่อน FastAPI())
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ── Context vars (per-request) ──
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


def bind_request(request_id: str | None, user_id: str | None = None) -> None:
    """ตั้ง contextvar ใน scope ของ request ปัจจุบัน — เรียกจาก middleware."""
    if request_id is not None:
        request_id_var.set(request_id)
    if user_id is not None:
        user_id_var.set(user_id)


# ── Field ที่จะดึงจาก LogRecord ตรงๆ (ไม่ใช่ extra) ──
_STD_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """JSON line per log record — รองรับ extra dict + contextvar."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # context (per-request)
        rid = request_id_var.get()
        uid = user_id_var.get()
        if rid:
            payload["request_id"] = rid
        if uid:
            payload["user_id"] = uid

        # location (เฉพาะ WARNING ขึ้นไป — ลด noise)
        if record.levelno >= logging.WARNING:
            payload["src"] = f"{record.module}:{record.lineno}"

        # extra dict (ทุก key ที่ไม่ใช่ standard)
        for key, val in record.__dict__.items():
            if key in _STD_FIELDS or key.startswith("_"):
                continue
            try:
                json.dumps(val)
                payload[key] = val
            except (TypeError, ValueError):
                payload[key] = repr(val)

        # exception
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Dev-friendly text format — มี request_id ต่อท้าย."""

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{datetime.fromtimestamp(record.created).strftime('%H:%M:%S')} "
            f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        )
        rid = request_id_var.get()
        if rid:
            base += f" [rid={rid[:8]}]"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(fmt: str = "json", level: str = "INFO") -> None:
    """Configure root logger + เงียบ noisy library.

    Args:
        fmt: "json" (production) | "text" (dev)
        level: "DEBUG" | "INFO" | "WARNING" | "ERROR"
    """
    formatter: logging.Formatter = (
        JsonFormatter() if fmt.lower() == "json" else TextFormatter()
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # clear handler เดิม กัน double-log จาก uvicorn default
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # ลดเสียง library ที่ verbose เกินไป
    for noisy in ("uvicorn.access", "httpx", "httpcore", "authlib"):
        logging.getLogger(noisy).setLevel("WARNING")
    # uvicorn.error ให้ผ่าน — มี startup info สำคัญ
    logging.getLogger("uvicorn").setLevel("INFO")
