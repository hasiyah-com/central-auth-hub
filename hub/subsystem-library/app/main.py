"""Subsystem B — ระบบห้องสมุด (Week 7 senior project).

Login flow เหมือน Subsystem A (ผ่าน Hub OAuth + PKCE)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers import auth, borrow, librarian, pages


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

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router, tags=["Authentication"])
app.include_router(pages.router, tags=["Member Pages"])
app.include_router(borrow.router, prefix="/borrow", tags=["Borrow"])
app.include_router(librarian.router, prefix="/librarian", tags=["Librarian"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "subsystem-library", "version": "0.1.0"}
