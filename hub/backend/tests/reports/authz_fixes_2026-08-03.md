# Fixes — audit run-2 #2 (access_policy widening) + #3 (student passkey bypass)

Date: 2026-08-03 · TDD (RED → GREEN). Both MEDIUM.
Test files (permanent): `tests/test_access_policy_approval.py`, `tests/test_passkey_student_block.py`.

---

## #3 — Student RBAC bypass via passkey login (MEDIUM)

**Defect:** `passkey.py` `login_finish` / `login_discoverable_finish` issued a Hub-direct JWT
(`create_access_token(result.user)`) with no `user_type=='student'` block — unlike the Google
(auth.py:254) / LINE (auth.py:802) callbacks. A student who enrolled a passkey (allowed, for
subsystem risk-stepup) could obtain a `hub.internal` token, defeating B19.

**Fix:** added `_block_student_hub_login(user, db, ip, method)` helper in `passkey.py` and called
it in both finish functions right after `auth_complete`/`discoverable_complete` (before
`create_access_token`). Student → audit `hub_login_blocked_student` + 403 `student_blocked`.
Enrollment still allowed; only Hub-direct login rejected.

**RED (fix stashed):** student passkey login proceeded past the guard — risk engine ran
`decision=allow`, reached `_build_login_session` / token issuance (not 403).
**GREEN:** `tests/test_passkey_student_block.py` — 4 passed (helper blocks student / allows
non-student; `login/finish` and `login/discoverable/finish` both 403 + audit row).

---

## #2 — access_policy widening skips admin approval (MEDIUM)

**Defect:** `PATCH /developer/subsystems/{id}` applied `access_policy` immediately, while
`scope`/`redirect_uris`/`allowed_roles` require admin re-approval. A developer widened an
admin-approved narrow subsystem to `access_policy="all"` and dumped all users via the Roster API.

**Fix:**
- `change_request_service.py` — new request type `edit_access_policy` (+ `_apply_edit_access_policy`
  dispatcher, added to `VALID_TYPES` and `_CONFIG_EDIT_TYPES` so approval kicks all sessions).
- `developer.py` — new `_access_policy_widens(old_p, old_cfg, new_p, new_cfg)` (rank
  `explicit<role/attribute<all`; conservative — only a rank-narrowing applies immediately).
  The access_policy branch now: **widening → `_enqueue("edit_access_policy", ...)`** (developer →
  pending admin approval; admin → auto-approved) ; **narrowing → immediate apply + kick sessions.**

**RED (fix stashed):** `test_developer_widening_creates_pending_not_applied` FAILED — widening
applied immediately (no pending request; access_updated webhook fired = policy changed).
`test_developer_narrowing_applies_immediately` passed unchanged (not a regression).
**GREEN:** `tests/test_access_policy_approval.py` — 9 passed (widening truth table incl.
`explicit→all`; developer widening → pending + policy unchanged; developer narrowing → immediate).

---

## Regression
```
docker compose exec hub-backend pytest \
  tests/test_access_policy_approval.py tests/test_passkey_student_block.py \
  tests/test_force_logout_refresh.py tests/test_access_policy.py \
  tests/test_developer_redirect_uri.py -q
=> 47 passed
```
py_compile: developer.py, change_request_service.py, passkey.py OK.

## Files changed
- `hub/backend/app/routers/passkey.py` (student block helper + 2 call sites)
- `hub/backend/app/routers/developer.py` (`_access_policy_widens` + widen→enqueue routing)
- `hub/backend/app/services/change_request_service.py` (`edit_access_policy` type + apply + config-edit set)
- `hub/backend/tests/test_passkey_student_block.py`, `tests/test_access_policy_approval.py` (new)

Not committed — user commits. Run-2 LOWs (#4 SDK open-redirect, #5–8) remain open.
