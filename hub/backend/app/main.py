"""FastAPI entrypoint."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from app.config import settings
from app.database import Base, engine
from app.hooks import register_default_listeners
from app.rate_limiter import limiter

# Init structured logging *ก่อน* import router/service อื่น
# กัน log line ที่เกิดขึ้นตอน import (เช่น auto-discover) หลุดเป็น default format
from app.services.structured_logger import setup_logging  # noqa: E402

setup_logging(fmt=settings.log_format, level=settings.log_level)

from app.routers import (  # noqa: E402
    health,
    users,
    admin,
    ml_admin,
    api_alerts,
    ip_blacklist,
    auth,
    developer,
    secret,
    oauth,
    oidc,
    passkey,
)
from app.services.jwt_service import get_jwks  # noqa: E402
from app.services.request_id import RequestIdMiddleware  # noqa: E402
from app.services.request_logger import RequestLoggerMiddleware  # noqa: E402
from app.services import api_guard_scheduler  # noqa: E402
from app.services import subsystem_health  # noqa: E402
from app.services import ipsum_refresh  # noqa: E402


# ============ Security Headers Middleware ============
# OWASP recommended headers — กัน clickjacking, MIME-sniff, XSS, info leak
# CSP ผ่อนสำหรับ /docs (Swagger UI ต้องการ inline script + CDN)
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        # ป้องกัน MIME type sniffing
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # กัน clickjacking (frame embed)
        response.headers.setdefault("X-Frame-Options", "DENY")
        # ปิดข้อมูล referer ไป cross-origin
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        # ปิด API ที่ไม่ใช้ — กัน fingerprint
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=()",
        )
        # HSTS — เฉพาะ production ที่เป็น HTTPS แล้ว
        if settings.app_env == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        # CSP — relax /docs (Swagger ใช้ inline + CDN), เข้มใน production
        path = request.url.path
        if path.startswith("/docs") or path.startswith("/redoc"):
            csp = (
                "default-src 'self'; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "font-src 'self' https://cdn.jsdelivr.net"
            )
        else:
            csp = "default-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers.setdefault("Content-Security-Policy", csp)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (dev only — use Alembic migrations in production)
    Base.metadata.create_all(bind=engine)

    # fail-fast ถ้าไม่มี JWT keys — ดีกว่ารอจน request แรกแล้วค่อยพัง
    for path in (settings.jwt_private_key_path, settings.jwt_public_key_path):
        if not os.path.exists(path):
            raise RuntimeError(
                f"ไม่พบ JWT key ที่ {path}. "
                "รันก่อน: docker compose exec hub-backend python -m scripts.generate_jwt_keys"
            )

    # Lifecycle hooks (event bus) — fail-safe extension points
    register_default_listeners()

    # API Guard — auto-scan request_logs ทุก 5 นาที (NIST SP 800-228)
    api_guard_scheduler.start(interval_sec=300, scan_window_min=5)

    # Subsystem health — ping /health ของ subsystem ที่ active ทุก 5 นาที
    subsystem_health.start()

    # ipsum threat-intel refresh — ดาวน์โหลด L5 IPs ทุก 24 ชม.
    ipsum_refresh.start()

    yield

    # Cleanup
    api_guard_scheduler.stop()
    subsystem_health.stop()
    ipsum_refresh.stop()


app = FastAPI(
    title="Central Auth Hub",
    description="ระบบจัดการสิทธิ์ผู้ใช้แบบศูนย์กลาง สำหรับมหาวิทยาลัย",
    version="0.5.0",
    lifespan=lifespan,
    # ปิด docs ใน production (set ENABLE_DOCS=false ใน .env)
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
)

# ── Rate limiter setup (must be first to register state + handler) ──
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Security headers — OWASP recommended (CSP, HSTS, X-Frame-Options, etc.)
app.add_middleware(SecurityHeadersMiddleware)

# Request logger — log ทุก HTTP request ลง request_logs (skip /health, /docs)
app.add_middleware(RequestLoggerMiddleware)

# Request-ID + structured-log context — ต้องอยู่ "นอก" RequestLogger (เพื่อให้
# log line ใน middleware ถัดเข้าไปได้ rid) → add ทีหลัง = outer
app.add_middleware(RequestIdMiddleware)

# Session middleware — จำเป็นสำหรับ Authlib OAuth (เก็บ state ระหว่าง flow)
# - https_only: production เท่านั้น (dev เป็น HTTP)
# - same_site: lax พอสำหรับ OAuth redirect (strict จะตัด state cookie ตอน redirect กลับ)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=(settings.app_env == "production"),
    same_site="lax",
    max_age=60 * 60,  # 1 ชม. — กัน session ค้างนาน
)

# CORS — env-driven (production ตัด localhost ออก ผ่าน CORS_ALLOW_ORIGINS)
_cors_origins = [
    o.strip()
    for o in getattr(settings, "cors_allow_origins", "").split(",")
    if o.strip()
] or [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin"],
)

# Routers
app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(oauth.router, prefix="/oauth", tags=["OAuth Flow (Subsystem)"])
app.include_router(developer.router, prefix="/developer", tags=["Developer Portal"])
app.include_router(secret.router, prefix="/secret", tags=["Secret Retrieval"])
app.include_router(users.router, prefix="/admin/users", tags=["Admin: Users"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(ml_admin.router, prefix="/admin/ml", tags=["Admin · ML"])
app.include_router(
    api_alerts.router, prefix="/admin/api-alerts", tags=["Admin · API Alerts"]
)
app.include_router(
    ip_blacklist.router, prefix="/admin/ip-blacklist", tags=["Admin · IP Blacklist"]
)
# OIDC Discovery + UserInfo + Introspection (no prefix — root paths per OIDC spec)
app.include_router(oidc.router, tags=["OIDC"])
# Passkey / WebAuthn (Phase 1+ — plan v3)
app.include_router(passkey.router, tags=["Passkey"])


# ============ JWKS endpoint (OIDC discovery standard path) ============


@app.get("/.well-known/jwks.json", tags=["Authentication"])
def jwks():
    """Public key set ตาม OIDC standard path. Subsystem ใช้ verify Hub JWT.

    คงตำแหน่งนี้ที่ root ตาม RFC 8414 / OIDC discovery — ไม่ผูกกับ prefix /auth
    """
    return get_jwks()


@app.get("/")
def root():
    return {
        "name": "Central Auth Hub",
        "version": "0.5.0",
        "docs": "/docs",
        "health": "/health",
        "login": "/auth/google/login",
        "jwks": "/.well-known/jwks.json",
    }
