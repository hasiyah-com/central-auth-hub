# แก้ชนิดของ subsystem_id ที่ขอบข้อมูลจาก Redis (B86) — 2026-09-26

**branch:** `fix/failed-logins-24h` · commit แยกจากงานกฎบล็อก · **ขอบเขต:** L2 (Behavior Profiling) เท่านั้น · L3 คงเดิมโดยเจตนา
**ที่มา:** พบระหว่างวัดเส้นทางคะแนนของ lockout DoS บน `_finalize_subsystem_login` จริง

## 1. บั๊ก

- `/oauth/authorize` เก็บ authreq เป็น JSON ใน Redis → `authreq["subsystem_id"]` เป็นสตริง
- `_finalize_subsystem_login` ส่งค่านี้ให้ `evaluate_login_risk` ตรงๆ
- `behavior_profiling.get_user_profile` สร้าง `seen_subsystems` / `subsystem_counts` จาก `LoginSession.subsystem_id` ซึ่งเป็น UUID
- `evaluate_behavior`: `subsystem_id not in seen` จริงเสมอ → `new_subsystem +0.30 floor=challenge` ทุกครั้งที่ผู้ใช้มีประวัติ >= 20 ครั้ง · กิ่ง `subsystem_rarity` ไม่เคยถูกเรียก

| จุดที่ใช้ subsystem_id | วิธีเทียบ | โดนบั๊ก |
|---|---|---|
| ฟีเจอร์ (`scope_sensitivity_score`, `active_subsystem_count`) | SQL | ไม่ |
| L1 cross-subsystem risk | SQL | ไม่ |
| **L2 `new_subsystem` / `subsystem_rarity`** | Python `in` / `dict.get` | **โดน → แก้ใน commit นี้** |
| **L3 residual `sub_rarity`** | Python `dict.get` | **โดน → งานแยก** (ประวัติสะสมด้วยค่าเดิม ต้องเปลี่ยนคีย์/รุ่นแบบ B84) |

## 2. การแก้

| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `hub/backend/app/routers/oauth.py` | แปลง `uuid.UUID(str(authreq["subsystem_id"]))` ก่อนส่งให้ `evaluate_login_risk` (ขอบข้อมูล) · authreq ที่ต้อง serialize ต่อ (risk challenge) ไม่แตะ |
| `hub/backend/app/security/risk_engine.py` | ส่งค่าให้ `_evaluate_l3` เป็นสตริงเหมือนเดิมโดยเจตนา พร้อมเหตุผล |
| `hub/backend/tests/finalize_env.py` (ใหม่) | helper ร่วม: ผู้ใช้/subsystem/TOTP ชั่วคราว · authreq ผ่าน JSON เหมือน `_load_authreq` · ประวัติ login ปกติ · spy ผลของ risk engine |
| `hub/backend/tests/test_subsystem_id_type_b86.py` (ใหม่) | 4 tests |
| `docs/bugs-encountered.md` | B86 |

## 3. เทส (ผ่าน `_finalize_subsystem_login` จริง · โหมดบังคับใช้ · ผู้ใช้มีประวัติ 20 วันบนเครื่องเดิมและ subsystem เดิม)

| เทส | ก่อนแก้ (RED) | หลังแก้ |
|---|---|---|
| เครื่องเดิม: ไม่มี `new_subsystem` และได้ authorization code ตรงๆ | ล้ม — มี `new_subsystem` (behavior 0.4) | ผ่าน |
| เครื่องใหม่: ไม่ถูกบล็อก ได้ challenge แล้วใช้ TOTP ยืนยันจนได้ code กลับ subsystem | ล้ม — **403 risk_score 0.900** | ผ่าน |
| ประวัติทั้งหมดอยู่ระบบอื่น → ระบบนี้ยังเป็น `new_subsystem` (กฎยังทำงาน) | ผ่าน | ผ่าน |
| L3 ยังได้รับสตริง (ตรึงไว้จนกว่าจะแก้ L3) | ผ่าน | ผ่าน · mutation (ถอด `str()`) ถูกจับ |

**ชุดเทสเต็มของ hub-backend** (ยกเว้น `test_e2e_full_stack.py` และ `test_l1_oidc.py` ที่ต้องใช้ stack Dorm/Library — ล้มเหมือน `origin/main` ตามรายงาน `failed_logins_24h_fix_2026-09-26.md`):
**916 passed · 1 failed · 13 skipped**

ข้อที่ล้มคือ `test_l3_explainability.py::test_concurrent_requests_agree` (สำเร็จ 0/20 = timeout ทั้งหมด) · เทสนี้เรียก client ของ L3 ไปที่ ml-service โดยตรง ไม่ผ่าน risk engine ·
รันเดี่ยว 5 รอบบนโค้ดนี้ ผ่าน 4 ล้ม 1 · ล้มบน `origin/main` ในรอบ `fix/l3-hub-direct` เช่นกัน และผ่านในสองรอบก่อนของ branch นี้ → ความไม่เสถียรตาม timeout เดิม ไม่เกี่ยวกับการแก้นี้

## 4. ผลต่อผลตัดสินที่ freeze ไว้ (2026-08-29)

- ตัวเลขที่ freeze มาจาก harness การทดลองที่ใช้ชื่อ subsystem เป็นสตริงทั้งฝั่ง profile และฝั่งที่ถาม (`build_profiles_v2` · `exp_hybrid_gate.fit_ecdf` ส่ง `raw["subsystem"]`) → ชนิดตรงกันอยู่แล้ว **ตัวเลขที่ freeze ไม่เปลี่ยน**
- ระบบจริงหลังโค้ดนี้เข้า (2026-08-29) ทำงานต่างจากที่วัด: ทุก login เข้า subsystem ของผู้ใช้ที่มีประวัติ >= 20 ครั้งได้ +0.30 และ challenge floor ที่การทดลองไม่มี
- การแก้**ทำให้ระบบจริงตรงกับที่วัดไว้** · ไม่ได้ปรับโมเดล เกณฑ์ หรือน้ำหนัก
- ผลตัดสินที่เปลี่ยนในระบบจริง: login เข้า subsystem ที่ใช้ประจำไม่ได้ +0.30 / challenge floor อีก · กฎ `subsystem_rarity` เริ่มทำงานได้ตามที่ออกแบบ
- ฐานข้อมูล dev ไม่มี session เข้า subsystem หลัง 2026-07-28 (ก่อนโค้ดเข้า) จึงวัดจำนวนที่ได้รับผลย้อนหลังไม่ได้ · ยังไม่ได้ตรวจข้อมูลบน production
- ค่าเริ่มต้นเป็นโหมด shadow → ในระบบที่ไม่ได้เปิดบังคับใช้ ผลคือป้าย `would_*` ที่เกินจริง ไม่ใช่การบล็อกจริง

## 5. ยังไม่ได้ทำ

- L3 residual (`sub_counts.get(str)`) — งานแยก: แก้ชนิด + เปลี่ยนคีย์ประวัติและรุ่นโมเดล (ต่อจาก `fix/l3-hub-direct` · B84)
- push / merge / deploy
