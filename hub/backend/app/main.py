"""FastAPI entrypoint."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
from app.hooks import register_default_listeners
from app.routers import health, users, admin, auth, developer, secret, oauth
from app.services.jwt_service import get_jwks
from app.services.request_logger import RequestLoggerMiddleware


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

    yield


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

# Request logger — log ทุก HTTP request ลง request_logs (skip /health, /docs)
app.add_middleware(RequestLoggerMiddleware)

# Session middleware — จำเป็นสำหรับ Authlib OAuth (เก็บ state ระหว่าง flow)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

# CORS — allow frontend during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(oauth.router, prefix="/oauth", tags=["OAuth Flow (Subsystem)"])
app.include_router(developer.router, prefix="/developer", tags=["Developer Portal"])
app.include_router(secret.router, prefix="/secret", tags=["Secret Retrieval"])
app.include_router(users.router, prefix="/admin/users", tags=["Admin: Users"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])


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
