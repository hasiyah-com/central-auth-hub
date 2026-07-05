# VM Pending Changes — รอ apply ขึ้น VM ครั้งเดียวตอนจบ

บันทึกทุกครั้งที่เพิ่ม/แก้ไขสำเร็จบน local — เพื่อ apply ขึ้น VM รวดเดียวตอนพัฒนาเสร็จ
ไม่ต้องไล่ทำทีละอย่างระหว่างทาง

**หลักการ:**
- **Code** = มากับ `git pull` อัตโนมัติ → เขียนแค่ชื่อสั้นๆ พอ (รายละเอียดอยู่ใน git)
- **Manual steps** (env / migration / data / firewall) = `git pull` ทำให้ไม่ได้ → เขียนคำสั่งเต็ม
- แก้เรื่องเดิมซ้ำ → **อัปเดตบรรทัดเดิม** ไม่เพิ่มใหม่

---

## 1. Env (`.env.prod`) — ต้องแก้มือ + force-recreate

| ตัวแปร | ค่า | เหตุผล |
|---|---|---|
| `PASSKEY_REQUIRED_AFTER_DAYS` | `7` | เปิด nudge เตือนตั้ง passkey หลังใช้งาน 7 วัน |

**คำสั่ง apply (บน VM):**
```bash
cd ~/central-auth-hub
grep -q '^PASSKEY_REQUIRED_AFTER_DAYS=' .env.prod \
  && sed -i 's/^PASSKEY_REQUIRED_AFTER_DAYS=.*/PASSKEY_REQUIRED_AFTER_DAYS=7/' .env.prod \
  || echo 'PASSKEY_REQUIRED_AFTER_DAYS=7' >> .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate hub-backend
```

---

## 2. Database migration (Alembic)

ทุกครั้งที่ pull โค้ดที่แก้ `models.py` → รัน migration:
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec hub-backend alembic upgrade head
```

**Pending migrations รอ apply:** _(ยังไม่มี — ถ้าเพิ่ม column ใหม่ให้จดที่นี่)_

---

## 3. Code (มากับ git pull — build ใหม่)

| commit / feature | build service ไหน |
|---|---|
| `fix(passkey)` — dev จัดการ passkey ตัวเองได้ (require_developer) | hub-backend |
| Passkey nudge banner (7 วัน) — `PasskeyNudgeBanner.tsx` + 2 layouts | hub-frontend |

**คำสั่ง apply (บน VM):**
```bash
cd ~/central-auth-hub
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build hub-backend hub-frontend
```

---

## 4. One-off / Data / Firewall

_(ยังไม่มี — เช่น seed, ALTER มือ, เปิด port ให้จดที่นี่)_

---

## ลำดับ apply สุดท้าย (รวบทุกอย่าง)

```bash
cd ~/central-auth-hub
git pull                                    # ← code
# ── env (ข้อ 1) ──
# (รันคำสั่ง sed/force-recreate จากข้อ 1)
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build hub-backend hub-frontend
docker compose --env-file .env.prod -f docker-compose.prod.yml exec hub-backend alembic upgrade head
```
