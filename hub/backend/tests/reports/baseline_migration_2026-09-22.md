# Baseline migration — สร้างฐานข้อมูลจากศูนย์ด้วย migration chain — 2026-09-22

## 1. ปัญหา (B80)

- `alembic upgrade head` บนฐานว่างล้มที่ `DROP INDEX ix_mfa_challenges_created_at` เพราะ baseline `609c11174142`
  เป็น autogenerate **diff** จากฐานข้อมูลที่แอปสร้างตารางเองก่อนใช้ Alembic ไม่ใช่ baseline จริง
- CI จึงโหลด snapshot ของ head (`hub_schema.sql`) แล้ว `alembic stamp head` — ไม่ได้พิสูจน์ว่า migration chain สร้าง
  schema ได้ถูกต้อง

## 2. สิ่งที่แก้

| ส่วน | การเปลี่ยนแปลง |
|---|---|
| `alembic/versions/609c11174142_baseline_current_schema.py` | แยกสามสภาพ: **empty** → รัน snapshot คงที่ · **legacy** (มีตาราง 7 ตารางที่ diff แตะครบ) → diff เดิม · **partial** → `RuntimeError` fail-closed ไม่สร้างหรือลบอะไร · ไม่ import models ปัจจุบัน ไม่เรียก create_all |
| `alembic/baseline/baseline_609c11174142.sql` | schema หลัง baseline: create_all ของ models ที่ commit `da0003b` (commit ที่สร้าง baseline) · สร้างด้วย `scripts/test/build_baseline_snapshot.sh` · ห้ามแก้มือ · loader ปฏิเสธ `SET`, `set_config`, คำสั่ง `\` ของ psql และ `alembic_version` |
| `alembic/versions/a7b8c9d0e1f2_align_schema_drift.py` (ใหม่) | ปิด drift ที่พบ: `SET DEFAULT false` ให้ `login_sessions.is_attack_ip` / `is_account_takeover` · `subsystems.allowed_roles` default เป็น `'{user}'::character varying[]` · รันซ้ำได้ ไม่แตะข้อมูล (ผู้ใช้เลือกแนวทางนี้) |
| `app/models.py` | `UserTotpCredential`: UNIQUE constraint ชื่อ `user_totp_credentials_user_id_key` + index ธรรมดา ให้ตรงกับที่ migration สร้าง (ผู้ใช้เลือกแก้ model ไม่แตะฐาน) · สอง flag ของ `LoginSession` มี `server_default false` |
| `scripts/schema_catalog.py` (ใหม่) | เทียบ schema สองฐานทีละรายการจาก catalog: extension, ตาราง, คอลัมน์ (ชนิด / NOT NULL / default), index, constraint, trigger, ฟังก์ชัน, sequence, enum, view · ไม่เทียบลำดับคอลัมน์ |
| `scripts/test/verify_migrations.sh` (ใหม่) | ตรวจครบทุกสภาพ (ข้อ 3) |
| `.github/workflows/backend-ci.yml` | เลิกโหลด snapshot แล้ว stamp · ใช้ `alembic upgrade head` จากฐานว่าง → ตรวจ `alembic current` = head → `alembic check` → เทียบกับ `hub_schema.sql` ทีละรายการ |
| `tests/support/schema/hub_schema.sql` | dump ใหม่จาก hub_db หลัง upgrade ถึง `a7b8c9d0e1f2` (ต่างเดิมเฉพาะ default ของ `allowed_roles`) |

hub_db ของ dev อัปเกรดแล้ว (`f6a7b8c9d0e1` → `a7b8c9d0e1f2`, login_sessions 1,879 แถวเท่าเดิม) · **production ต้องรัน
`alembic upgrade head` ตอน deploy ครั้งถัดไป** (เปลี่ยนเฉพาะ default)

## 3. ผลตรวจ — `scripts/test/verify_migrations.sh`

```
== อ้างอิง: โหลด hub_schema.sql ==
  ok    โหลด snapshot ของ head
== 1. ฐานว่าง ==
  ok    alembic upgrade head จากฐานว่าง
  ok    ฐานว่าง: alembic current = head (a7b8c9d0e1f2)
  ok    alembic check (models ตรงกับ schema)
  ok    ฐานว่าง: schema ตรงกับ hub_schema.sql ทีละรายการ
== 2. ฐานข้อมูลเดิมก่อนใช้ Alembic ==
  ok    upgrade head จากสภาพเดิม (เส้นทาง diff)
  ok    สภาพเดิม: alembic current = head (a7b8c9d0e1f2)
  ok    สภาพเดิม: ข้อมูลอยู่ครบ
  ok    สภาพเดิม: schema ตรงกับ hub_schema.sql ทีละรายการ
== 3. stamp แล้ว อยู่ revision กลางทาง ==
  ok    upgrade d4e5f6a7b8c9 -> head
  ok    กลางทาง: alembic current = head (a7b8c9d0e1f2)
  ok    กลางทาง: ข้อมูลอยู่ครบ
  ok    กลางทาง: schema ตรงกับ hub_schema.sql ทีละรายการ
== 4. ฐานข้อมูลที่สร้างค้างครึ่งหนึ่ง ==
  ok    ถูกปฏิเสธพร้อมข้อความ
  ok    ฐานที่ถูกปฏิเสธไม่ถูกแก้ (เหลือ users ตารางเดียว)
ผ่านทุกรายการ (head a7b8c9d0e1f2)
```

- **สภาพเดิม** สร้างโดย baseline จาก snapshot แล้ว `downgrade base` (คืน `mfa_challenges` และ index เดิม) ลบ
  `alembic_version` แล้วใส่ข้อมูลตัวอย่าง (ไม่ใช่ข้อมูลจริง) ก่อน upgrade
- **ข้อมูลไม่หาย** = แถวตัวอย่างใน `users` อยู่ครบค่าเดิมหลัง upgrade ถึง head

## 4. ตัวตรวจจับได้จริง (ไม่ใช่ผ่านเพราะไม่ได้เทียบ)

รอบแรกก่อนแก้ drift ตัวเทียบรายงานต่าง **ทั้งสามเส้นทาง**:

| รายการ | ฐานที่ migrate | hub_schema.sql | สาเหตุ |
|---|---|---|---|
| `login_sessions.is_attack_ip` / `is_account_takeover` default | ไม่มี | `false` | default ที่เพิ่มนอก Alembic ใน dev |
| `subsystems.allowed_roles` default | `'{user}'::character varying[]` | `'{user}'::text[]` | baseline เปลี่ยนชนิดแต่คง expression เดิม |
| CHECK 3 ตัวของ Expert Review | `ANY ((ARRAY[...])::text[])` | `ANY (ARRAY[(...)::text, ...])` | **ไม่ใช่ drift** — ข้อความต่างเพราะฝั่งอ้างอิงผ่าน dump → โหลดกลับ · เทียบกับ hub_db ตรง ๆ แล้วตรงกัน |

และ `alembic check` รายงาน `user_totp_credentials.user_id` (unique index ใน model / UNIQUE constraint ในฐาน) ·
หลังแก้: ให้ฝั่งที่ตรวจผ่าน dump → โหลดกลับเหมือนฝั่งอ้างอิง (ทั้งในสคริปต์และ CI) + migration `a7b8c9d0e1f2` +
แก้ model → ผ่านทุกรายการ

## 5. เทส

| ไฟล์ | จำนวน | ครอบคลุม |
|---|---|---|
| `tests/test_baseline_migration.py` | 17 | สามสภาพ (empty / legacy / partial), ข้อความตอนปฏิเสธ, snapshot ไม่มีของรุ่นหลัง, ระบุ commit ต้นทาง, loader ปฏิเสธคำสั่งที่เปลี่ยน session, ไม่ใช้ models ปัจจุบัน |
| `tests/test_schema_catalog.py` | 6 | หมวดที่ต้องเทียบครบ, normalize, ไม่ขึ้นกับลำดับ, รายงานฝั่งที่ต่าง |
| `tests/test_schema_drift_alignment.py` | 3 | model TOTP ตรงฐาน, server default ของสอง flag, migration ใหม่แตะเฉพาะ default |

RED: รันกับ migration เดิม → baseline 16 failed / 1 passed (ข้อ "ไม่ใช้ models ปัจจุบัน" ซึ่งโค้ดเดิมก็ผ่าน) ·
`test_schema_catalog.py` เขียน**หลัง**ตัวโค้ด (ผิดลำดับ TDD) จึงผ่านตั้งแต่แรก — ยืนยันว่าตัวเทียบจับได้จริงจากข้อ 4 แทน ·
drift alignment → 3 failed · GREEN: ทั้งหมดผ่าน

## 6. รันซ้ำ

```bash
bash scripts/test/build_baseline_snapshot.sh   # สร้าง snapshot ของ baseline ใหม่ (ปกติไม่ต้อง — ไฟล์คงที่)
bash scripts/test/verify_migrations.sh         # ตรวจทุกสภาพ · ใช้ฐานชื่อลงท้าย _test แล้วลบทิ้ง
bash scripts/test/dump_test_schema.sh          # dump hub_schema.sql ใหม่หลังมี migration ใหม่
```
