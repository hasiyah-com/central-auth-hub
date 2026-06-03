"""Subsystem A — ระบบหอพัก (Week 6 senior project).

Login flow:
  Browser → /login → /oauth/start → Hub /oauth/authorize → Google → Hub
       → Subsystem /oauth/callback → set session cookie → / (home)

ระบบนี้:
  - มี Postgres แยกของตัวเอง (postgres-dorm:5432)
  - ไม่มี FK ไป Hub — เก็บ hub_user_id (UUID จาก JWT.sub) เป็น opaque ID
  - role-based access ผ่าน JWT claim role_in_subsystem (resident / staff)
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import Scope

from app.database import Base, engine
from app.routers import auth, pages, reservation, staff, webhook

templates = Jinja2Templates(directory="app/templates")


class NoCacheStaticFiles(StaticFiles):
    """Dev mode: ปิด browser cache ทุก static asset (app.js, app.html, app.css)
    เพื่อให้ user เห็นการแก้ทันทีไม่ต้อง Ctrl+Shift+R.
    Production ควรใช้ CDN + content hash แทน
    """

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if os.getenv("APP_ENV", "development") != "production":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


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

app.mount("/static", NoCacheStaticFiles(directory="app/static"), name="static")

app.include_router(auth.router, tags=["Authentication"])
app.include_router(pages.router, tags=["Resident Pages"])
app.include_router(reservation.router, prefix="/reservation", tags=["Reservation"])
app.include_router(staff.router, prefix="/staff", tags=["Staff"])
app.include_router(webhook.router, tags=["Webhook (Hub → us)"])


@app.get("/app.html", response_class=FileResponse)
def spa():
    return FileResponse("app/static/app.html", media_type="text/html")


@app.get("/health")
def health():
    return {"status": "ok", "service": "subsystem-dorm", "version": "0.1.0"}
