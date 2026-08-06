# Findings Detail — HIGH + MEDIUM (run-2)

## Finding 1 — Force-logout doesn't revoke refresh tokens (HIGH)

### Data flow
1. **Force-logout entry** — `admin.py:820` `force_logout_user` (POST `/admin/users/{id}/force-logout`, `require_hub_admin` + step-up). Queries active sessions (`logout_at IS NULL`).
2. **Loop** — `admin.py:847-859`: `s.logout_at = now`; if `s.jti` → `revoke_jti(s.jti, exp)`; collects `subsystem_id` for webhooks. **No `s.refresh_id` / refresh revoke.** (Verified: zero `refresh` references in the whole function 820-925.)
3. **Refresh entry** — `auth.py:1459` `refresh_access_token` → `refresh_token_service.rotate(body.refresh_token)`. Succeeds because `refresh:{refresh_id}` Redis entry was never deleted.
4. **Sink** — `auth.py:1476-1487`: loads `LoginSession` by `result["session_id"]`, sets `sess.jti = token_jti`, `sess.refresh_id = result["refresh_id"]`, `sess.last_seen_at = now`, commits. **Never checks `sess.logout_at`.** The only guard is `User.status=='active'` (auth.py:1461), which force-logout does not change (by design: "kick now, re-login allowed"). No user-level token epoch / `valid_after` field exists.

### Trigger
```
POST /auth/refresh
{ "refresh_token": "<refresh token captured before the admin force-logout>" }
```
→ 200 with a fresh `access_token` + rotating `refresh_token`. Session revived; `logout_at` stays set but unused.

### Why not blocked
`rotate()` is a pure Redis-liveness + single-use check (`refresh_token_service.py`); the risk-gate `_refresh_risk_gate` returns allow in `ML_SHADOW_MODE=true` (default) and for normal-risk same-device refreshes. Sibling paths that get it right: self-logout `auth.py:1549-1552` and `account_link._revoke_all_sessions` both call `refresh_token_service.revoke`.

### Fix
```python
# admin.py force_logout_user loop:
for s in sessions:
    s.logout_at = now
    if s.refresh_id:
        refresh_token_service.revoke(s.refresh_id)   # add
    if s.jti: ... revoke_jti(...)
# auth.py refresh_access_token, after loading sess:
if sess and sess.logout_at is not None:
    raise HTTPException(status_code=401, detail="session terminated")
```

---

## Finding 2 — access_policy widening → directory harvest (MEDIUM)

### The asymmetry (developer.py `update_subsystem`)
- `redirect_uris` / `scope` / `allowed_roles` → `_enqueue()` → `create_change_request()` → **pending admin approval** for non-admins (`change_request_service.py:110`, auto-approve only if `is_hub_admin`).
- `access_policy` / `access_policy_config` → **immediate group** (`developer.py:1161-1183`): `_validate_access_policy` then `subsystem.access_policy = norm_policy` + `immediate_changes[...]`, committed. No change-request, no `status→pending`.

### Data flow to disclosure
1. `developer.py:1096` PATCH entry (`require_developer` + owner step-up).
2. `developer.py:1176` `subsystem.access_policy = "all"` applied immediately.
3. `access_policy.py:109` `list_allowed_users` — policy `"all"` = `User.status=='active'`, no `user_type` filter (students + staff + admins).
4. `roster.py:46` `GET /api/v1/roster` (`X-Api-Key`) returns `{user_id, email, user_type}` per allowed user; requires only `subsystem.status=='active'`.

### Attack chain
```
1. Register subsystem (access_policy="explicit") → admin approves → active
2. PATCH /developer/subsystems/{id}  {"access_policy":"all"}      # immediate
3. GET /api/v1/roster   (X-Api-Key: <owned>)                       # all 100 users
```
→ every active user's email + role label (identifies admins) with no admin re-review.

### Fix
Route policy *widening* (`explicit → all/role/attribute`, or broadening role/attribute sets) through `create_change_request()` like `scope`; narrowing stays immediate. Alternatives: reset `status→pending` on any policy change, or restrict `/api/v1/roster` to explicit-whitelist subsystems.

---

## Finding 3 — Student RBAC bypass via passkey login (MEDIUM)

### The invariant (B19)
Students must never receive a Hub-direct JWT. Enforced at:
- `auth.py:254` Google callback: `if user.user_type == "student" and not setup_intent: raise 403`
- `auth.py:802` LINE callback: same.

### The gap (passkey path, added later)
1. `auth.py:117` `GET /auth/credentials/setup` — allows **all roles incl. students** (by design), authenticates via Google, mints `enroll:{state}` context bound to the student `user_id` (`auth.py:344-379`, skips student block for `setup_intent`).
2. `oauth.py:1022` `POST /oauth/passkey/enroll/finish` → `_load_enroll_user` (no `user_type` check) → passkey saved for the student.
3. `passkey.py:866` `POST /auth/passkey/login/finish` → `webauthn_service.auth_complete` (no `user_type` filter in `webauthn_service`) → **`passkey.py:928` `create_access_token(result.user)`** issues `aud=hub.internal`, `user_type=student`. `login_discoverable_finish` (`passkey.py:1039`) identical. (Verified: no `user_type`/`student`/`require_` guard in passkey login-finish paths; `user_type` appears only as a response field.)

### Attack
```
(as student) enroll passkey via /auth/credentials/setup
POST /auth/passkey/login/start  {"email":"<student>@uni.ac.th"}
POST /auth/passkey/login/finish {<assertion>}   → hub.internal JWT + refresh
```

### Impact bound
`require_developer`/`require_hub_admin` re-query `user_type` from DB → `/developer` and `/admin` data stay protected. Realized impact: B19 layer-1 control defeated; a `hub.internal` token exists for a student (dangerous if any future `get_current_user`-only endpoint exposes cross-user data, or the Next.js console grants shell access on a valid `hub_token` cookie).

### Fix
```python
# passkey.py login_finish + login_discoverable_finish, after auth_complete:
if result.user.user_type == "student":
    log_action(db, actor_id=result.user.id, action="hub_login_blocked_student", ...)
    db.commit()
    raise HTTPException(status_code=403, detail={"code": "student_blocked"})
token, jti = create_access_token(result.user)
```
Keep student passkey **enrollment** (subsystem risk-stepup needs it); block only Hub-direct **login**.

---

## Finding 4 — Go auth-proxy open redirect (MEDIUM)

### Data flow
- `handler.go:77` `HandleLogin` — `return_to = r.URL.Query().Get("return_to")` (unauthenticated), stored in temp cookie.
- `handler.go:210-214` `HandleCallback` — `if target == "" || !strings.HasPrefix(target, "/") { target = "/" }; http.Redirect(w, r, target, 302)`. `handler.go:221-225` `HandleLogout` — same guard on `return_to`.

### Bypass
`//evil.com` starts with `/` → passes the guard. `net/http.Redirect` path-normalizes only when the parsed URL has empty Scheme **and** empty Host; `//evil.com` parses to Host=`evil.com`, so `Location: //evil.com` is emitted verbatim and the browser follows it to `http://evil.com`. `/\evil.com` is a secondary vector (browser folds `\`→`/`).

### Trigger
```
GET /cah-auth/logout?return_to=//evil.com     → Location: //evil.com
GET /cah-auth/login?return_to=//evil.com       (survives the round-trip)
```

### Fix
```go
if target == "" || !strings.HasPrefix(target, "/") ||
   strings.HasPrefix(target, "//") || strings.HasPrefix(target, "/\\") {
    target = "/"
}
```
(PoC not executed — no Go/Docker at hunt time — but rests on documented `net/http.Redirect` behavior.)
