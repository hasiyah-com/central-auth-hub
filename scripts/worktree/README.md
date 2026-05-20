# Worktree Scripts

Quick-ref สำหรับรัน Claude Code sessions ขนานบน git worktree พร้อม Docker stack แยก

## Slots + port allocation

| Slot      | Offset | Hub  | Dorm | Lib  | ML   | PG   | PG-Dorm | PG-Lib | Redis |
|-----------|--------|------|------|------|------|------|---------|--------|-------|
| `main`    | +0     | 8000 | 8001 | 8002 | 9000 | 5432 | 5433    | 5434   | 6379  |
| `hub`     | +10    | 8010 | 8011 | 8012 | 9010 | 5442 | 5443    | 5444   | 6389  |
| `dorm`    | +20    | 8020 | 8021 | 8022 | 9020 | 5452 | 5453    | 5454   | 6399  |
| `library` | +30    | 8030 | 8031 | 8032 | 9030 | 5462 | 5463    | 5464   | 6409  |
| `ml`      | +40    | 8040 | 8041 | 8042 | 9040 | 5472 | 5473    | 5474   | 6419  |

`COMPOSE_PROJECT_NAME=cah-<slot>` → volume + network namespace แยกสมบูรณ์

## 4 Sessions — ขั้นตอนต่อ slot

### Session 1 — Hub Backend (port 8010)
```bash
# One-time setup
bash scripts/worktree/create.sh hub

# ทุก session
cd ../central-auth-starter-hub
bash ../central-auth-starter/scripts/worktree/up.sh
claude
# ใน Claude Code:
/hub-backend
เริ่มงาน

# ปิด session
เลิกงาน
bash ../central-auth-starter/scripts/worktree/down.sh
```

### Session 2 — Subsystem A: หอพัก (port 8020)
```bash
bash scripts/worktree/create.sh dorm

cd ../central-auth-starter-dorm
bash ../central-auth-starter/scripts/worktree/up.sh
claude
/subsystem-dorm
เริ่มงาน

เลิกงาน
bash ../central-auth-starter/scripts/worktree/down.sh
```

### Session 3 — Subsystem B: ห้องสมุด (port 8030)
```bash
bash scripts/worktree/create.sh library

cd ../central-auth-starter-library
bash ../central-auth-starter/scripts/worktree/up.sh
claude
/subsystem-library
เริ่มงาน

เลิกงาน
bash ../central-auth-starter/scripts/worktree/down.sh
```

### Session 4 — ML Verifier (port 8040)
```bash
bash scripts/worktree/create.sh ml

cd ../central-auth-starter-ml
bash ../central-auth-starter/scripts/worktree/up.sh
claude
/ml-service
เริ่มงาน

เลิกงาน
bash ../central-auth-starter/scripts/worktree/down.sh
```

---

## Other Commands

```bash
# สร้าง worktree ใหม่ (จะอยู่ที่ ../central-auth-starter-<slot>)
bash scripts/worktree/create.sh hub                  # → branch feature/hub-dev
bash scripts/worktree/create.sh ml mfa-week9         # → branch feature/ml-mfa-week9

# ลิสต์ทั้งหมด + docker status
bash scripts/worktree/list.sh

# เข้า worktree แล้ว start/stop
cd ../central-auth-starter-hub
bash ../central-auth-starter/scripts/worktree/up.sh        # docker compose up -d --build
bash ../central-auth-starter/scripts/worktree/down.sh      # docker compose down
bash ../central-auth-starter/scripts/worktree/down.sh -v   # + ลบ volume

# เปิด Claude Code ใน worktree
claude                                                      # session แยกจาก main

# ลบ worktree สมบูรณ์ (docker down -v + git worktree remove + branch -d)
bash scripts/worktree/remove.sh hub
bash scripts/worktree/remove.sh hub --yes                  # ข้าม confirm
```

## Manual one-time setup ที่ user ต้องทำเอง

**Google OAuth Console** — เพิ่ม redirect URIs (Google ไม่รองรับ wildcard):
```
http://localhost:8010/auth/google/callback   (hub)
http://localhost:8010/oauth/callback
http://localhost:8020/auth/google/callback   (dorm)
http://localhost:8020/oauth/callback
http://localhost:8030/auth/google/callback   (library)
http://localhost:8030/oauth/callback
http://localhost:8040/auth/google/callback   (ml)
http://localhost:8040/oauth/callback
```

## How it works

- **`docker-compose.override.yml`** ใน worktree (auto-generated, gitignored) — override `container_name:` + `ports:` ของทุก service โดยไม่แตะ base `docker-compose.yml`
- **`docker compose -p cah-<slot>`** flag ใน wrapper scripts → volume + network แยก namespace
- **JWT keys**: symlink `hub/backend/keys` ไปยัง main repo (Windows ต้อง Developer Mode สำหรับ symlink — fallback เป็น copy)
- **`.env` ของ worktree**: copy จาก main แล้ว `sed` แก้ `HUB_BASE_URL`, `GOOGLE_REDIRECT_URI`, `OAUTH_CALLBACK_URI` ให้ตรง port ใหม่

## Backward-compat กับ main repo

Main repo `docker-compose.yml` ไม่ถูกแตะเลย — รัน `docker compose up -d` ที่ root ใช้ port + container name เดิม (5432, 8000, `hub-postgres`, `hub-backend` etc.) เพราะ override file ไม่มีใน main

## Troubleshooting

| ปัญหา | สาเหตุ | แก้ |
|------|--------|-----|
| `bind: address already in use` | port ของ slot ชนกับโปรเซสอื่น | `lsof -i :8010` หาว่าใครใช้, kill หรือเปลี่ยน slot |
| Subsystem login fail "OAuth Error" | ลืมเพิ่ม redirect URI ใน Google Console | เพิ่ม URI ทั้ง 2 ตัวของ port ใหม่ |
| `docker compose down` ที่ main ไม่ลบ worktree's container | ใช้ project name คนละตัว | `docker compose -p cah-<slot> down` ที่ worktree |
| Worktree พังหลังลบ folder เอง | git ค้าง state | `git worktree prune` |
| Symlink keys ใช้ไม่ได้ | Windows ไม่ได้ Developer Mode | enable Developer Mode หรือใช้ copy (script fallback ให้แล้ว) |
| Volume orphan กิน disk | ลืมรัน `remove.sh` | `docker volume ls \| grep cah-` แล้ว `docker volume rm` |
