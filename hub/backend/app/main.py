"""FastAPI entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import health, users, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (dev only — use Alembic migrations in production)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Central Auth Hub",
    description="ระบบจัดการสิทธิ์ผู้ใช้แบบศูนย์กลาง สำหรับมหาวิทยาลัย",
    version="0.1.0",
    lifespan=lifespan,
)

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
app.include_router(users.router, prefix="/admin/users", tags=["Admin: Users"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])


@app.get("/")
def root():
    return {
        "name": "Central Auth Hub",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
