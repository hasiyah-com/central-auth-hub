"""In-process event bus — extension points "ก่อน/หลัง" event สำคัญ.

ดีไซน์:
- ไม่แก้ business logic เดิม แค่ `await emit(EVT, payload)` ที่จุดสำคัญ
- Fail-safe: listener fail → log แต่ไม่ propagate (เหมือนกฎ B21 ML client)
- Async-friendly: รองรับทั้ง sync และ async handler
- Pluggable: listener register ที่ startup ไม่ต้องแก้ emit call site

วิธีใช้:
    from app.services.hooks import register, emit, EVT_LOGIN_SUCCESS

    # ใน startup
    register(EVT_LOGIN_SUCCESS, my_handler)

    # ใน router/service
    await emit(EVT_LOGIN_SUCCESS, {"user_id": ..., "email": ...})
"""
import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable, Union

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Union[None, Awaitable[None]]]
_listeners: dict[str, list[Handler]] = defaultdict(list)


# ============ Event constants ============

EVT_LOGIN_PRE = "login.pre"
EVT_LOGIN_SUCCESS = "login.success"
EVT_LOGIN_FAILURE = "login.failure"
EVT_TOKEN_ISSUED = "token.issued"
EVT_OAUTH_AUTHORIZED = "oauth.authorized"
EVT_OAUTH_FAILURE = "oauth.failure"
EVT_ML_SCORED = "ml.scored"
EVT_AUDIT_PRE = "audit.pre"
EVT_AUDIT_LOGGED = "audit.logged"


# ============ Register / emit ============

def register(event: str, handler: Handler) -> None:
    """Register handler สำหรับ event. Handler จะ sync หรือ async ก็ได้."""
    _listeners[event].append(handler)


def listeners_count() -> int:
    """รวมจำนวน listener ทุก event — ใช้ใน startup log + test."""
    return sum(len(v) for v in _listeners.values())


async def emit(event: str, payload: dict) -> None:
    """Fire event ไปยังทุก listener. ไม่เคย raise — fail-safe ตามกฎ B21.

    Listener หนึ่งพังไม่กระทบ listener อื่น (loop ต่อจน หมด).
    """
    for handler in _listeners.get(event, ()):
        try:
            result = handler(payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            # log แต่ไม่ propagate — flow หลักต้องเดินต่อได้
            logger.exception(
                "hook listener failed: event=%s handler=%s error=%s",
                event, getattr(handler, "__name__", repr(handler)), e,
            )


def emit_nowait(event: str, payload: dict) -> None:
    """Fire-and-forget สำหรับ sync caller (เช่น audit_service.log_action).

    ถ้ามี running event loop → schedule เป็น task
    ถ้าไม่มี (เช่น CLI script) → silently skip (fail-safe)
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(emit(event, payload))
    except RuntimeError:
        # ไม่มี event loop — sync context ปกติของ CLI/script
        # ข้ามไปเงียบๆ ตามกฎ fail-safe
        pass
