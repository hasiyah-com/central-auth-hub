"""Helper ร่วมสำหรับเทสที่วิ่งผ่าน oauth._finalize_subsystem_login จริง (ไม่ใช่ไฟล์เทส).

สร้างผู้ใช้ + subsystem ชั่วคราว + TOTP (มีปัจจัยที่สอง → ได้ risk-stepup) + authreq ใน Redis
ในรูปแบบเดียวกับที่ /oauth/authorize เก็บ (JSON → subsystem_id เป็นสตริง) และประวัติ login ปกติ
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import pyotp
from starlette.requests import Request

from app.models import (
    AccessList,
    AuditLog,
    IpBlacklist,
    LoginSession,
    Subsystem,
    User,
    UserTotpCredential,
)
from app.redis_client import redis_client
from app.services import totp_service

UA_OWNER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/150.0 Safari/537.36"
)
UA_NEW_DEVICE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "Version/18.0 Mobile/15E148 Safari/604.1"
)


def random_test_ip() -> str:
    # TEST-NET-2 สุ่มต่อเทส — กันกฎ multi-account IP ชนกับเทสอื่น
    return f"198.51.100.{uuid.uuid4().int % 250 + 1}"


def make_subsystem(db, tag: str) -> Subsystem:
    sub = Subsystem(
        name=f"fin-sub-{tag}",
        client_id=f"cli_fin_{tag}",
        client_secret_hash="unused",  # pragma: allowlist secret (placeholder ไม่ใช่ secret)
        redirect_uris=["http://localhost:9999/cb"],
        scope=["email", "name"],
        status="active",
        access_policy="all",
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def build_env(db) -> dict:
    s = uuid.uuid4().hex[:8]
    user = User(
        email=f"fin_{s}@uni.ac.th",
        google_sub=f"gsub_{s}",
        full_name=f"Finalize {s}",
        user_type="teacher",
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    sub = make_subsystem(db, s)
    secret, _ = totp_service.start_enroll(user.id, db)
    totp_service.confirm_enroll(user.id, pyotp.TOTP(secret).now(), db)
    db.commit()
    hub_state = f"hs_fin_{s}"
    authreq = {
        "subsystem_id": str(sub.id),
        "client_id": sub.client_id,
        "redirect_uri": sub.redirect_uris[0],
        "state": "teststate",
        "code_challenge": "x" * 43,
        "scope": list(sub.scope),
    }
    redis_client.setex(f"authreq:{hub_state}", 600, json.dumps(authreq))
    # ผ่าน JSON เหมือน _load_authreq — ชนิดข้อมูลต้องตรงกับของจริง
    authreq = json.loads(redis_client.get(f"authreq:{hub_state}"))
    return {
        "tag": s,
        "user": user,
        "sub": sub,
        "extra_subs": [],
        "secret": secret,
        "hub_state": hub_state,
        "authreq": authreq,
    }


def teardown_env(db, env: dict, ip: str) -> None:
    db.rollback()
    redis_client.delete(f"authreq:{env['hub_state']}")
    uid = env["user"].id
    sids = [env["sub"].id] + [x.id for x in env["extra_subs"]]
    db.query(AuditLog).filter(
        (AuditLog.actor_id == uid) | (AuditLog.target_id == uid)
    ).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.target_id.in_(sids)).delete(
        synchronize_session=False
    )
    db.query(LoginSession).filter(LoginSession.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(AccessList).filter(AccessList.subsystem_id.in_(sids)).delete(
        synchronize_session=False
    )
    db.query(UserTotpCredential).filter(UserTotpCredential.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(IpBlacklist).filter(IpBlacklist.ip_address == ip).delete(
        synchronize_session=False
    )
    db.query(Subsystem).filter(Subsystem.id.in_(sids)).delete(synchronize_session=False)
    db.query(User).filter(User.id == uid).delete(synchronize_session=False)
    db.commit()


def add_owner_history(db, env, ip, *, subsystem=None, days=20) -> None:
    """ประวัติปกติ: 1 ครั้ง/วัน · เครื่องเดิม · subsystem เดิม · ชั่วโมงเดียวกับตอนนี้."""
    sub = subsystem or env["sub"]
    now = datetime.utcnow()
    for d in range(2, 2 + days):
        db.add(
            LoginSession(
                user_id=env["user"].id,
                ip=ip,
                user_agent=UA_OWNER,
                decision="allow",
                subsystem_id=sub.id,
                created_at=now - timedelta(days=d),
            )
        )
    db.commit()


def request_for(ip: str, ua: str = UA_OWNER) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/oauth/callback",
            "query_string": b"",
            "headers": [
                (b"x-forwarded-for", ip.encode()),
                (b"user-agent", ua.encode()),
            ],
            "client": (ip, 12345),
        }
    )


def spy_risk(monkeypatch) -> dict:
    """เก็บผลของ evaluate_login_risk ที่ finalizer เรียกจริง (score/reasons)."""
    import app.routers.oauth as oauth_mod

    real = oauth_mod.evaluate_login_risk
    captured: dict = {}

    async def spy(*args, **kwargs):
        result = await real(*args, **kwargs)
        captured["risk"] = result
        captured["kwargs"] = kwargs
        return result

    monkeypatch.setattr(oauth_mod, "evaluate_login_risk", spy)
    return captured


async def finalize(db, env, ip, ua: str = UA_OWNER) -> str:
    from app.routers.oauth import _finalize_subsystem_login

    return await _finalize_subsystem_login(
        user=env["user"],
        authreq=env["authreq"],
        hub_state=env["hub_state"],
        request=request_for(ip, ua),
        db=db,
        provider="google",
    )
