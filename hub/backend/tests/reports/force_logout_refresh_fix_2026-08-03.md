# Fix — Force-logout doesn't revoke refresh tokens (audit run-2 #1, HIGH)

Date: 2026-08-03 · TDD (RED → GREEN). Test file (permanent): `tests/test_force_logout_refresh.py`.

## Defect
`POST /admin/users/{id}/force-logout` blacklisted each session's access `jti` and set
`logout_at`, but never revoked the rotating refresh token; and `POST /auth/refresh` never
checked `logout_at` (only `User.status=='active'`, which force-logout doesn't change). A
compromised/ejected session was fully restored by one `/auth/refresh` call — defeating the
incident-response control. HIGH.

## Fix (two guards)
1. **`hub/backend/app/routers/admin.py`** `force_logout_user` — added `import refresh_token_service`
   and, in the session loop, `if s.refresh_id: refresh_token_service.revoke(s.refresh_id)`
   (mirrors `account_link._revoke_all_sessions`).
2. **`hub/backend/app/routers/auth.py`** `refresh_access_token` — after loading the session,
   `if sess is not None and sess.logout_at is not None: revoke(result["refresh_id"]); raise 401`
   (defense-in-depth; also revokes the just-rotated token so no orphan lingers in Redis).

## RED (fix reverted via git stash)
```
tests/test_force_logout_refresh.py  3 failed
  test_refresh_rejected_when_session_logged_out   assert 200 == 401   (session revived)
  test_force_logout_revokes_refresh_token         rts.rotate(raw) returned a live result (not revoked)
  test_force_logout_then_refresh_is_fully_blocked assert 200 == 401   (attacker back in)
```

## GREEN (fix applied)
```
tests/test_force_logout_refresh.py  3 passed
  test_refresh_rejected_when_session_logged_out
  test_force_logout_revokes_refresh_token
  test_force_logout_then_refresh_is_fully_blocked
```

## Regression
```
docker compose exec hub-backend pytest \
  tests/test_force_logout_refresh.py tests/test_refresh_token.py tests/test_token_revocation.py -q
=> 26 passed
```
py_compile: admin.py, auth.py OK.

## Files changed
- `hub/backend/app/routers/admin.py` (import + revoke in force-logout loop)
- `hub/backend/app/routers/auth.py` (reject refresh when logout_at set)
- `hub/backend/tests/test_force_logout_refresh.py` (new)

Not committed — user commits. Run-2 findings #2 (access_policy widening) and #3 (student passkey bypass) remain open.
