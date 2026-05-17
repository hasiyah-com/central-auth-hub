"""Subsystem A — ระบบหอพัก (Week 6 senior project).

Login flow:
  Browser → /login → /oauth/start → Hub /oauth/authorize → Google → Hub
       → Subsystem /oauth/callback → set session cookie → / (home)

ระบบนี้:
  - มี Postgres แยกของตัวเอง (postgres-dorm:5432)
  - ไม่มี FK ไป Hub — เก็บ hub_user_id (UUID จาก JWT.sub) เป็น opaque ID
  - role-based access ผ่าน JWT claim role_in_subsystem (resident / staff)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import Base, engine
from app.routers import auth, pages, reservation, staff

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="ระบบหอพัก (Subsystem A)",
    description="Senior Project — Subsystem A ของ Central Auth Hub",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router, tags=["Authentication"])
app.include_router(pages.router, tags=["Resident Pages"])
app.include_router(reservation.router, prefix="/reservation", tags=["Reservation"])
app.include_router(staff.router, prefix="/staff", tags=["Staff"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "subsystem-dorm", "version": "0.1.0"}
