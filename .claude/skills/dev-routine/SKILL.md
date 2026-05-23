# Dev Routine Skill

**Invoke**: `/dev-routine` หรือเมื่อ user พูดว่า "เริ่มงาน", "start working", "เลิกงาน", "end of day", "สรุปงาน", "ประจำวัน"

---

## Subagent Dispatch — โหลด context ตาม domain

ก่อนเริ่มพัฒนาทุก session — ระบุ domain skill ให้ตรงกับ worktree/งานที่ทำ:

| ทำงานที่ไหน | พูดว่า | Context ที่โหลด |
|-------------|--------|----------------|
| main repo, งาน Hub | `/hub-backend` | FastAPI, JWT, OAuth, RBAC, audit |
| main repo, งาน Frontend | `/frontend-admin` | Next.js, admin pages, Hub API |
| worktree-hub | `/hub-backend` | Hub backend เต็ม |
| worktree-dorm | `/subsystem-dorm` | Dorm business logic, hub_client |
| worktree-library | `/subsystem-library` | Library, borrow/return |
| worktree-ml | `/ml-service` | 12 features, training pipeline |

**Cross-domain work** (เช่น Hub + ML ในคราวเดียว):
- Spawn subagent สำหรับงานรอง — `Agent` tool พร้อม focused prompt
- Subagent ไม่โหลด context ของ domain อื่น
- Main session รับผลกลับ → merge

**กฎ**: อย่าให้ subagent เข้าถึง `.env`, `keys/`, หรือ secrets โดยตรง

---

## Daily Structure

```
เช้า  → morning.sh        ← docker/git/log check
      → test_workflow.sh  ← smoke test ก่อนพัฒนา
      → พัฒนาระบบ
      → test_workflow.sh  ← smoke test หลังพัฒนา
เย็น  → eod.sh            ← pre-commit + commit guidance
      → docs/daily/YYYY-MM-DD.md  ← สรุปงานวันนี้
```

---

## Morning Routine (เริ่มงาน)

Run in order:

1. **`bash scripts/routine/morning.sh`** — read output carefully
2. If any service shows `Exit` or `(not running)` → `docker compose up -d <service-name>`
3. If git has uncommitted changes → ask user: stash / commit first / ignore?
4. If hub-backend log shows `ERROR` or `Exception` → read traceback, report to user before starting
5. State today's session goal: read `CLAUDE.md § Project Roadmap` → echo what we work on today

## System Test — Before Dev

1. **`bash scripts/routine/test_workflow.sh`**
2. If any ❌ → diagnose and fix first, then re-run until all ✅
3. Record results in `docs/daily/YYYY-MM-DD.md § System Test — Before`

## Coding Routine (ระหว่าง session)

**Before writing a new endpoint:**
- Always add `Depends(get_current_user)` or `require_hub_admin` or `require_developer` — never unprotected (B1)
- If new file: register router in `main.py`

**After writing an endpoint:**
- Verify audit order: `log_action()` → `db.commit()` → `raise HTTPException` (B6)
- Confirm `log_action()` called on BOTH success AND failure paths (B7)
- Test: `curl http://localhost:8000/...` or open Swagger at http://localhost:8000/docs

**JWT rules (every token operation):**
- Hub-direct: `aud=hub.internal`; Subsystem: `aud=client_id`
- Every `jwt.decode()` must use `verify_aud=True` (B4)
- Secret comparisons: `hmac.compare_digest()` never `==` (B3)

**After ML feature change:**
- `docker compose exec ml-service python -m scripts.generate_data`
- `docker compose exec ml-service python -m scripts.train_model`
- Feature order in `feature_extraction.py` must match `features.py:FEATURE_NAMES` (B27)

**Commit pattern**: small commits per feature, correct prefix (`feat:` / `fix:` / `security:` / `docs:` / `refactor:` / `ui:`)

## TDD Workflow — กฎบังคับ

ทุก feature ต้องทำตาม RED → GREEN → REFACTOR เสมอ **ห้ามเขียน implementation ก่อน test**

### วงจรต่อ 1 feature

```
RED      เขียน test ที่ fail ก่อน
         รัน → ยืนยันว่า fail จริง → รายงานผลให้เห็น
GREEN    เขียน implementation ให้ test ผ่าน
         รัน → ยืนยันว่า pass → รายงานผลให้เห็น
REFACTOR ปรับโค้ดให้สะอาด (rename, extract, simplify)
         รัน → ยืนยันว่ายังผ่านอยู่ → รายงานผลให้เห็น
```

### กฎที่ต้องทำตามเสมอ

1. **ห้ามเขียน implementation ก่อน test** — ถ้าไม่มี test อย่าเขียนโค้ด
2. **รายงานผล test ทุกรอบ** — paste output ให้ user เห็น ไม่ใช่แค่บอกว่า "ผ่านแล้ว"
3. **ถ้า test fail → บอกตรงไหน** — อ่าน traceback เต็ม อย่าเดาหรือข้าม
4. **ห้าม commit ถ้า test ยังไม่ผ่านทุกตัว** — test is source of truth
5. **ถ้า test เดิมพังหลัง refactor** → revert refactor ก่อน หา root cause

### Run commands (Hub backend)

Container WORKDIR = `/app` (COPY from `./hub/backend` → `/app`) — รัน pytest จาก `.` ภายใน container

```bash
# รัน test ทั้งหมด
docker compose exec hub-backend pytest . -v

# รันเฉพาะไฟล์
docker compose exec hub-backend pytest tests/test_auth.py -v

# รัน + แสดง print output
docker compose exec hub-backend pytest . -v -s

# รัน + stop ที่ fail แรก
docker compose exec hub-backend pytest . -x
```

### Test file convention

```
hub/backend/tests/
├── test_auth.py           # routers/auth.py
├── test_oauth.py          # routers/oauth.py
├── test_developer.py      # routers/developer.py
├── test_admin.py          # routers/admin.py
├── test_jwt_service.py    # services/jwt_service.py
└── conftest.py            # shared fixtures (db, client, user)
```

## System Test — After Dev

1. **`bash scripts/routine/test_workflow.sh`** — confirm no regression
2. Record results in `docs/daily/YYYY-MM-DD.md § System Test — After`
3. If any new ❌ → fix before EOD (revert if needed)

## Evening Routine (เลิกงาน)

1. **`docker compose exec hub-backend pytest . -v`** — ต้อง pass ทุกตัวก่อน commit (TDD rule)
2. **`bash scripts/routine/eod.sh`** — shows diff + pre-commit result
3. Fix any pre-commit errors (ruff format, detect-secrets)
4. Stage specific files: `git add hub/backend/app/routers/...` (never `git add .` or `git add -A`)
5. Commit: `git commit -m "feat: ..."` — **ห้าม commit ถ้า pytest ยังไม่ผ่าน**
5. **Write `docs/daily/YYYY-MM-DD.md`** (Claude Code creates this file):

```markdown
# YYYY-MM-DD

## Session Goal
(อะไรที่ตั้งใจทำวันนี้)

## ทำอะไรบ้าง
- (bullet list of changes/files modified)

## System Test — Before
| Service | Status |
|---------|--------|
| Hub /health | ✅ 200 |
| Hub /health/db | ✅ 200 |
| Hub JWKS | ✅ 200 |
| Subsystem A | ✅ 200 |
| Subsystem B | ✅ 200 |
| ML /health | ✅ 200 |

## System Test — After
(same table with actual results)

## Commits Today
(git log --oneline --since="today 00:00")

## Bug ใหม่ที่เจอ
(ถ้ามี — อธิบาย + เพิ่มใน CLAUDE.md § Bugs Encountered)

## Next Session
(ต้องทำอะไรพรุ่งนี้)
```

## Weekly Routine (ทุกวันศุกร์)

1. ML check: if any feature added this week → `generate_data` + `train_model`
2. Seed check: if email pattern changed → update `docs/sample_whitelist.csv` (B28)
3. Update `CLAUDE.md § Project Roadmap`: mark completed weeks ✅
4. Bug review: add new bugs to `§ Bugs Encountered` as B(N+1) with full description
5. Worktree cleanup: `bash scripts/worktree/list.sh` → `bash scripts/worktree/remove.sh <slot>` for unused
