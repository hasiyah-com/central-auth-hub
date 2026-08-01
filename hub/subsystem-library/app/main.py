"""Subsystem B — ระบบห้องสมุด (Week 7 senior project).

Login flow เหมือน Subsystem A (ผ่าน Hub OAuth + PKCE)
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from app.database import Base, engine
from app.routers import auth, borrow, librarian, pages, webhook


class NoCacheStaticFiles(StaticFiles):
    """In development we want browsers (esp. Chrome) to always re-fetch
    static assets so design tweaks show up immediately on refresh.
    Production should serve via a CDN with proper Cache-Control instead.
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
    title="ระบบห้องสมุด (Subsystem B)",
    description="Senior Project — Subsystem B ของ Central Auth Hub",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", NoCacheStaticFiles(directory="app/static"), name="static")

app.include_router(auth.router, tags=["Authentication"])
app.include_router(pages.router, tags=["Member Pages"])
app.include_router(borrow.router, prefix="/borrow", tags=["Borrow"])
app.include_router(librarian.router, prefix="/librarian", tags=["Librarian"])
app.include_router(webhook.router, tags=["Webhook (Hub → us)"])


@app.get("/health")
def health():
    return {"status": "healthy", "service": "subsystem-library", "version": "0.1.0"}
