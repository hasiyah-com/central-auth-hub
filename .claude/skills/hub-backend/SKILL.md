# Hub Backend Skill

**Domain**: Central Auth Hub — FastAPI backend (port 8000)
**Invoke**: `/hub-backend` หรือเมื่อทำงานใน `hub/backend/`
**Security rules**: ดู `/central-auth-hub` (shared, ไม่ copy ซ้ำที่นี่)

---

## Architecture

```
hub/backend/app/
├── main.py          FastAPI entrypoint + lifespan (JWT key check, register_default_listeners)
├── config.py        Pydantic Settings + validate_production() fail-fast
├── deps.py          get_current_user, get_client_ip, require_hub_admin, require_developer
├── routers/
│   ├── auth.py      /auth/google/login, /callback  (Hub-direct, blocks students)
│   ├── oauth.py     /oauth/authorize, /callback, /token  (subsystem flow + PKCE)
│   ├── developer.py /developer/subsystems, /whitelist
│   ├── admin.py     /admin/overview, /admin/subsystems
│   ├── users.py     /admin/users
│   └── secret.py    /secret/retrieve (one-time HTML page)
└── services/
    ├── jwt_service.py      create_access_token / create_subsystem_token / JWKS
    ├── secret_service.py   Argon2id + Fernet
    ├── audit_service.py    log_action()
    ├── ml_client.py        async httpx → ML (fail-safe)
    ├── feature_extraction.py  12 features → ML
    └── pkce.py             verify_pkce (hmac.compare_digest)
```

## Endpoint Pattern (ทุก endpoint ใหม่ทำตามนี้)

```python
@router.post("/resource/{id}/action", tags=["Tag"])
async def action_name(
    id: uuid.UUID,
    body: RequestSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # ← ห้ามลืม (B1)
    request: Request = None,
):
    ip = get_client_ip(request)                       # ← ไม่ใช้ request.client.host (B20)
    target = db.get(Model, id)
    if not target:
        raise HTTPException(404)

    # ... business logic ...

    log_action(db, current_user.id, "action_name", "Model", str(id), ip)  # (B6)
    db.commit()                                        # ← commit ก่อน raise (B6)
    return {"ok": True}
```

**Depends hierarchy:**
- Public endpoint: ไม่ต้องใช้ (comment ชัดๆ ว่า public)
- Auth required: `Depends(get_current_user)`
- Teacher/Staff/Admin: `Depends(require_developer)`
- Admin only: `Depends(require_hub_admin)`

## JWT Rules

```python
# Hub-direct token
create_access_token(sub=str(user.id), email=user.email, ...)
# → aud = "hub.internal"

# Subsystem token (หลัง OAuth flow)
create_subsystem_token(sub=str(user.id), client_id=client_id, ...)
# → aud = client_id (e.g. "cli_abc123")

# Decode — ต้อง verify_aud=True เสมอ (B4)
jwt.decode(token, key, algorithms=["RS256"], audience="hub.internal")
```

## Critical Bugs (Hub backend specific)

| Bug | อาการ | กฎ |
|-----|------|-----|
| B1 | endpoint ไม่มี Depends → ใครก็เรียกได้ | ทุก endpoint ต้องมี Depends |
| B4 | decode ไม่ verify aud → token cross-subsystem | verify_aud=True + ระบุ audience= |
| B6 | log_action หลัง raise → audit หาย | order: log → commit → raise |
| B9 | /oauth/token race condition | ใช้ Redis `getdel` (atomic) |

## Common Tasks

**Add endpoint**: router → Depends → log_action → commit → raise → register in main.py ถ้าไฟล์ใหม่

**Re-seed users** (preserves Gmail admin):
```bash
docker compose exec hub-backend python -m app.seeds.seed_users
```

**Test endpoint** (dev):
```bash
curl http://localhost:8000/health
# หรือ Swagger: http://localhost:8000/docs
```

**Restart after code change** (uvicorn auto-reloads แต่ถ้าไม่ reload):
```bash
docker compose restart hub-backend
```
