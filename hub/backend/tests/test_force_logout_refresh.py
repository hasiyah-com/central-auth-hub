"""Security test — admin force-logout must durably kill refresh tokens (audit run-2 #1, HIGH).

Before the fix, POST /admin/users/{id}/force-logout blacklisted the access jti and set
logout_at but left the rotating refresh token live in Redis, and POST /auth/refresh never
checked logout_at — so an ejected/compromised session was fully restored by one /auth/refresh
call. Two guards close it:
  (A) refresh_access_token rejects a session whose logout_at is set (defense-in-depth)
  (B) force_logout_user revokes each session's refresh token (refresh_token_service.revoke)

รัน:
    docker compose exec hub-backend pytest tests/test_force_logout_refresh.py -v
"""

from __future__ import annotations

from app.models import LoginSession
from app.services import refresh_token_service as rts
from app.services import stepup_cache
from app.services.jwt_service import create_access_token


def _login_session(db, user, jti, refresh_id):
    sess = LoginSession(
        user_id=user.id,
        subsystem_id=None,
        ip="127.0.0.1",
        user_agent="pytest",
        login_method="google",
        decision="allow",
        jti=jti,
        refresh_id=refresh_id,
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


# ── (A) refresh must reject a logged-out session, even if the token is still live ──


def test_refresh_rejected_when_session_logged_out(client, db, admin_user):
    """A session with logout_at set must not be revivable via /auth/refresh."""
    token, jti = create_access_token(admin_user)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id="tmp")
    sess = _login_session(db, admin_user, jti, refresh_id)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id=str(sess.id))
    sess.refresh_id = refresh_id
    # simulate force-logout having marked the session (token left live on purpose)
    from datetime import datetime

    sess.logout_at = datetime.utcnow()
    db.commit()

    r = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 401, "logged-out session must not mint a new access token"


# ── (B) force_logout endpoint must revoke the refresh token in Redis ──


def test_force_logout_revokes_refresh_token(client, db, admin_user, auth_headers):
    """After Force Logout All, the pre-logout refresh token can no longer rotate."""
    admin_token, admin_jti = create_access_token(admin_user)
    # pass the session_revoke step-up gate
    stepup_cache.set_granted(str(admin_user.id), admin_jti, method="passkey")

    # target session with a live refresh token (target == admin_user for simplicity)
    _t, sjti = create_access_token(admin_user)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id="tmp")
    sess = _login_session(db, admin_user, sjti, refresh_id)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id=str(sess.id))
    sess.refresh_id = refresh_id
    db.commit()

    try:
        r = client.post(
            f"/admin/users/{admin_user.id}/force-logout",
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        # the refresh token must be dead now
        assert rts.rotate(raw) is None, "force-logout must revoke the refresh token"
    finally:
        stepup_cache.clear(str(admin_user.id), admin_jti)


def test_force_logout_then_refresh_is_fully_blocked(
    client, db, admin_user, auth_headers
):
    """End-to-end: force-logout, then /auth/refresh with the old token → 401 (both guards)."""
    admin_token, admin_jti = create_access_token(admin_user)
    stepup_cache.set_granted(str(admin_user.id), admin_jti, method="passkey")

    _t, sjti = create_access_token(admin_user)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id="tmp")
    sess = _login_session(db, admin_user, sjti, refresh_id)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id=str(sess.id))
    sess.refresh_id = refresh_id
    db.commit()

    try:
        r = client.post(
            f"/admin/users/{admin_user.id}/force-logout",
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        r2 = client.post("/auth/refresh", json={"refresh_token": raw})
        assert (
            r2.status_code == 401
        ), "ejected session must not come back via /auth/refresh"
    finally:
        stepup_cache.clear(str(admin_user.id), admin_jti)
