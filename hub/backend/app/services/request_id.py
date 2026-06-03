"""Request-ID middleware — bind contextvar + echo X-Request-ID header.

ทำหน้าที่:
  - อ่าน X-Request-ID จาก header (เผื่อ upstream ส่งมา) หรือ generate ใหม่
  - ตั้ง request_id ลง contextvar ก่อน handler รัน
  - ใส่ header กลับใน response
  - extract user_id จาก Authorization header ถ้ามี (สำหรับ structured log)

ต้อง register *ก่อน* RequestLoggerMiddleware เพื่อให้ log line มี request_id
"""

from __future__ import annotations

import uuid

from fastapi import Request
from jwt.exceptions import InvalidTokenError as JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.services.jwt_service import verify_token
from app.services.structured_logger import bind_request


def _extract_user_id(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = verify_token(token)
        return payload.get("sub")
    except JWTError:
        return None
    except Exception:
        return None


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # ใช้ X-Request-ID ถ้า upstream (Caddy / Cloudflare) ส่งมา ไม่งั้น gen ใหม่
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        uid = _extract_user_id(request)
        bind_request(request_id=rid, user_id=uid)

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
