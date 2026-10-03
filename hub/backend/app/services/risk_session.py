"""Resolve the exact login challenged, never the latest login of an account."""
from uuid import UUID

from fastapi import HTTPException

from app.models import LoginSession


def resolve_challenge_session(db, payload, user_id):
    try:
        session_id = UUID(str(payload.get("session_id")))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=410, detail="challenge เก่าหรือไม่สมบูรณ์ — login ใหม่")
    flow = payload.get("flow")
    if flow not in {"hub_direct", "subsystem"}:
        raise HTTPException(status_code=400, detail="invalid challenge flow")
    query = db.query(LoginSession).filter(
        LoginSession.id == session_id, LoginSession.user_id == user_id,
    )
    if flow == "subsystem":
        try:
            subsystem_id = UUID(str((payload.get("authreq") or {}).get("subsystem_id")))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(status_code=410, detail="invalid challenge subsystem")
        query = query.filter(LoginSession.subsystem_id == subsystem_id)
    else:
        query = query.filter(LoginSession.subsystem_id.is_(None))
    session = query.first()
    if session is None:
        raise HTTPException(status_code=410, detail="ไม่พบ session ต้นทาง — login ใหม่")
    return session
