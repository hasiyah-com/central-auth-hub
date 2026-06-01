"""Middleware ที่ log ทุก HTTP request ลง request_logs.

หลักการทำงาน:
  1. รับ request เข้ามา -> จับเวลา
  2. ตรวจ Authorization header เพื่อหา user_id (ถ้ามี JWT)
  3. ส่ง request ต่อ -> รอ response
  4. คำนวณ duration + log ลง DB (session แยก)
  5. ส่ง response กลับ

ข้อสำคัญ:
  - ใช้ session แยกจาก request — กัน rollback ของ request ทำให้ log หาย
  - ถ้า log fail ไม่ทำให้ request ล่ม (try/except)
  - skip endpoint ที่ไม่ควร log (health, docs, openapi)
"""

import time

from fastapi import Request
from jwt.exceptions import InvalidTokenError as JWTError
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import SessionLocal
from app.models import RequestLog
from app.services.jwt_service import verify_token

# path ที่ไม่ log (noise + บ่อยเกินไป)
SKIP_PATHS = {
    "/health",
    "/health/db",
    "/openapi.json",
    "/favicon.ico",
}
SKIP_PREFIXES = ("/docs", "/redoc")


def _extract_user_id(request: Request) -> str | None:
    """ดึง user_id จาก JWT ถ้ามีใน Authorization header."""
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


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # ข้าม path ที่ไม่ต้อง log
        if request.url.path in SKIP_PATHS or any(
            request.url.path.startswith(p) for p in SKIP_PREFIXES
        ):
            return await call_next(request)

        start = time.time()
        user_id = _extract_user_id(request)
        # ใช้ X-Forwarded-For ถ้ามี (Docker/nginx/cloudflare) — กัน 172.x.x.x
        xff = request.headers.get("x-forwarded-for")
        if xff:
            client_ip = xff.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        # เรียก endpoint จริง
        error_detail = None
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            # endpoint ระเบิด — log ก่อน raise ต่อ
            status_code = 500
            error_detail = f"{type(e).__name__}: {e}"
            self._log(
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                user_id=user_id,
                ip=client_ip,
                user_agent=user_agent,
                duration_ms=int((time.time() - start) * 1000),
                error_detail=error_detail,
            )
            raise

        duration_ms = int((time.time() - start) * 1000)
        # error_detail จาก HTTPException ก็เก็บไว้ดูได้
        if status_code >= 400:
            error_detail = f"HTTP {status_code}"

        self._log(
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            user_id=user_id,
            ip=client_ip,
            user_agent=user_agent,
            duration_ms=duration_ms,
            error_detail=error_detail,
        )
        return response

    @staticmethod
    def _log(**kwargs) -> None:
        """commit log ใน session แยก — ห้ามทำ request ล่มเพราะ log error."""
        db = SessionLocal()
        try:
            db.add(RequestLog(**kwargs))
            db.commit()
        except Exception as e:
            # log failure to stdout — ไม่ raise
            print(f"[request_logger] failed to log: {e}")
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()
