# Test isolation — แยกสภาพแวดล้อมของชุดเทสออกจาก dev และปิด state leak

วันที่ 13–15 ก.ย. 2569 · commit ฐาน `9dd2278` (งานนี้ยังไม่ commit ขณะเขียนรายงาน)

## สถานะ

| รายการ | ผล |
|---|---|
| ชุดเทสเต็ม 3 รอบติดบน image ที่ pin แล้ว | **0 failed ทั้งสามรอบ** (§8) |
| ผลไม่ขึ้นกับลำดับการรัน (forward/reverse/shuffle×3) | **ผ่าน** (§7) |
| รันทีละไฟล์ 94 ไฟล์ ตัวเลขตรงกับรันทั้งชุด | **ผ่าน** (§7) |
| state รั่วข้ามรอบ | **ไม่พบ** — ชุดเต็ม 8 รอบ + รันทีละไฟล์ 94 ครั้ง |
| cleanup ทำงานแม้เทสล้ม | **ผ่าน** (§6) |
| สาเหตุของ flaky 401 | **ยังไม่สรุป** (§9) |
| baseline migration ที่สร้างจากศูนย์ได้ | **ยังไม่มี** — ใช้ schema snapshot (§3) |
| คอนฟิกที่รันอยู่ = Config B | **ไม่ใช่** (§11) |
| พร้อมเปิด Shadow epoch ใหม่ | **ยังไม่พร้อม** (§11) |

เกณฑ์ "full suite 0 failed" ที่ตกลงไว้ **ผ่านแล้ว** ส่วนการสร้าง tag / deploy /
Config B artifact ยังไม่ทำ — รอการตัดสินใจ และคอนฟิกยังไม่ตรง Config B (§11)

---

## 1. ปัญหาที่ทำให้ผลรันก่อนหน้าเชื่อถือไม่ได้

| # | อาการ | ต้นเหตุ |
|---|---|---|
| 1 | ไม่มีนักศึกษาสถานะ active เหลือใน `hub_db` เลย (จาก 70 คน) | fixture ของ `test_user_lifecycle` คืนสถานะด้วย ORM object ที่ stale หลัง API commit ไปแล้ว → SQLAlchemy ไม่สั่ง UPDATE · สะสมรอบละหลายคนตั้งแต่ ก.ค. |
| 2 | เทสที่ต้องใช้ `student_user` ถูก skip ทั้งหมด (skip 42 → 62) | ผลของข้อ 1 |
| 3 | ผล "0 failed" ไม่มีความหมาย | เทสที่ควรทดสอบถูก skip ไปเงียบ ๆ |
| 4 | flaky 401 นาน ๆ ครั้ง 4 ตัว | ยังไม่สรุปสาเหตุ — ดู §9 |
| 5 | `l3resid` ค้างใน Redis 311 key ไม่มี TTL | เทสสร้างผู้ใช้ชั่วคราวแล้วไม่ลบ key |

**หลักฐานของข้อ 1** — นักศึกษา 56 คนที่ค้าง graduated/resigned ถูก PATCH จาก TestClient
ทั้งหมด (IP ว่าง) ไม่มีสักคนถูกแก้จากหน้า console (`172.18.0.1`) และไม่มี login จริงหลังจากนั้น

---

## 2. สภาพแวดล้อมของเทสหลังแก้

| ชั้น | dev | test |
|---|---|---|
| PostgreSQL | `hub_db` | `hub_test` — drop/create ใหม่ทุกครั้งที่ setup |
| Redis | DB 0 | DB 15 · key ขึ้นต้น `test:{run_id}:` |
| ml-service | `ml-service` (Redis DB 0) | `ml-service-test` (Redis DB 15) |

**guard แบบ fail-closed** ใน `conftest.py` หยุดก่อน collect ถ้าชี้ผิด — ตรวจ 3 ข้อพร้อมกัน
(ชื่อฐานข้อมูลต้องลงท้าย `_test`, Redis ต้องไม่ใช่ DB ของ dev, ต้องมี `TEST_ENVIRONMENT=1`)
และ **ไม่มี flag ยกเว้น** · เทส `test_no_bypass_flag_exists` ยืนยันว่าตั้ง env ชื่ออะไรก็ข้ามไม่ได้

**ทำไมต้องมี ml-service แยก** — แกน L3 อยู่ใน ml-service และอ่าน `l3resid:{user_id}`
ด้วย connection ของตัวเอง ถ้าเทสย้ายไป Redis DB 15 แต่ ml-service ยังอ่าน DB 0 จะมองไม่เห็น
ประวัติแล้ว **abstain ทั้งหมด** (เจอจริง — เทส L3 fail 25 ตัวก่อนแก้) · key กลุ่มนี้
(`l3resid:`, `l3dup:`) จึงไม่ใส่ prefix และอาศัยการแยก DB แทน

**lock กันรันซ้อน** — `test:lock` (SET NX + TTL 1 ชม.) เพราะ `l3resid:`/`l3dup:`/`LIMITS:`
ไม่ได้อยู่ใน namespace และ `hub_test` ถูก drop/create ตอน setup จึงรันสองรอบพร้อมกันไม่ได้

---

## 3. ข้อจำกัดที่ต้องพูดให้ตรง — "ทดสอบจาก schema snapshot" ไม่ใช่สร้างจาก migration

`alembic upgrade head` บนฐานข้อมูลเปล่า **ล้มเหลว**

```
sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedObject)
index "ix_mfa_challenges_created_at" does not exist
```

เพราะ baseline `609c11174142` เป็น **diff จากฐานข้อมูลที่มีอยู่แล้ว** (ขึ้นต้นด้วย
`op.drop_index(...)` / `op.drop_table("mfa_challenges")`) ไม่ใช่การสร้างจากศูนย์

`hub_test` จึงถูกสร้างด้วยการ **clone schema จาก `hub_db`** แล้ว `alembic stamp head`
ซึ่ง stamp เพียงบันทึกเลข revision **ไม่ได้พิสูจน์ว่า schema ถูกต้อง** จึงต้องตรวจของจริง
ด้วย `scripts/test/verify_test_schema.sh` — 14 รายการ ผ่านทั้งหมด

```
ตารางครบ 3 ตาราง · trigger append-only 2 ตัว + ฟังก์ชัน
UNIQUE เฉพาะคอลัมน์ supersedes_id · uq_expert_reviews_chain_key
uq_expert_reviews_one_root (partial, WHERE supersedes_id IS NULL)
fk_expert_reviews_supersedes_same_chain (4 คอลัมน์) · FK ทุกตัวไม่ cascade/set null
CHECK 5 ข้อ · alembic_version = e5f6a7b8c9d0
```

### drift ที่ `alembic check` รายงาน — แจกแจงทีละรายการ

| รายการ | สถานะ |
|---|---|
| `expert_reviews.round` SMALLINT เทียบ Integer ใน model | **แก้แล้ว** — เปลี่ยน model เป็น `SmallInteger` |
| `uq_expert_reviews_chain_key` ไม่มีใน model | **แก้แล้ว** — เพิ่มใน `__table_args__` |
| `uq_expert_reviews_one_root` ไม่มีใน model | **แก้แล้ว** — เพิ่ม partial `Index` |
| `fk_expert_reviews_supersedes_same_chain` ไม่มีใน model | **แก้แล้ว** — เพิ่ม `ForeignKeyConstraint` |
| `ix_user_totp_credentials_user_id` unique เทียบ non-unique | **ยังไม่แก้** — มีอยู่ก่อนงานนี้ ไม่เกี่ยวกับ Expert Review · บันทึกไว้เป็นงานแยก |

**งานที่ควรทำต่อ (ยังไม่ทำ):** สร้าง baseline migration ที่สร้างฐานข้อมูลจากศูนย์ได้จริง
ตราบใดที่ยังไม่มี ข้อความ "ทำซ้ำได้จาก clean worktree" ยังหมายถึง *สร้างจาก schema snapshot*
เท่านั้น

---

## 4. state leak ที่พบและแก้

ตัวตรวจเทียบ state ก่อน/หลังรอบ (`tests/support/state_invariant.py`) ชี้ตัวการรายไฟล์

| ไฟล์ | รั่ว | ต้นเหตุ | การแก้ |
|---|---|---|---|
| `test_oauth_policy_integration` | นักศึกษา seed ค้าง `suspended` | `_finalize_subsystem_login` commit ภายใน ทำให้สถานะที่ flush ไว้ถูกบันทึกถาวร `db.rollback()` จึงไม่มีอะไรย้อน | คืนค่าด้วย `UPDATE` ตาม id แล้ว commit |
| `test_risk_live_demo` | teacher ค้าง 1 คน + session 13 แถว | ตั้งใจให้บัญชีสาธิตค้างไว้ดูบน console ของ dev | ลบบัญชีและ session ท้ายไฟล์ (ตอนนี้รันบนฐานข้อมูลของเทสแล้ว) |
| `test_refresh_token` | session 10 แถว | สร้าง `LoginSession` แล้วไม่ลบ | มาร์ค user agent เฉพาะไฟล์ + ลบท้ายไฟล์ |
| `test_force_logout_refresh` | session 3 แถว | เหมือนกัน | เหมือนกัน |
| `test_user_lifecycle` | นักศึกษา seed ค้าง graduated/resigned | คืนสถานะผ่าน ORM object ที่ stale | สร้างนักศึกษาชั่วคราวเอง + ลบทิ้งท้ายเทส |

### เกณฑ์ตัดสินของตัวตรวจ

- **รั่วจริง (ตกรอบ)** — แถวใน DB ค้างข้ามรอบ, ผู้ใช้/สถานะ seed เปลี่ยน, `dependency_overrides`
  หรือ env/settings ไม่กลับสภาพเดิม, และ **key ใน namespace ที่ยังเหลือหลัง cleanup**
- **รายงานอย่างเดียว** — key ใน namespace ระหว่างรอบ (มี TTL และถูกลบท้ายรอบ) กับ `audit_logs`
  ที่โตตามธรรมชาติของการรันเทส

---

## 5. ผลรันหลังแก้ (ฐานข้อมูลสร้างใหม่)

```
1187 passed · 21 skipped · 0 failed   (210 วินาที)
state: ไม่มี state รั่ว · ลบ key ของรอบ 119 รายการ
```

### เหตุผลของ skip ทั้ง 21 ตัว

| จำนวน | เหตุผล |
|---|---|
| 9 | `test_l3_sequence` ต้องมี numpy/sklearn ซึ่งมีเฉพาะใน ml-service |
| 6 | harness ของ ml-service ไม่อยู่ใน path ของคอนเทนเนอร์ hub-backend |
| 2 | ต้องรันบน host (ใช้ `ml-service/data` ของ repo) |
| 2 | `test_incidents` — ฐานข้อมูลใหม่ยังไม่มี incident |
| 1 | `test_l2_legacy_mode_parity` ต้องอยู่ใน git working tree |
| 1 | `test_l3_sequence_client` — ml-service ไม่ได้ mount ในคอนเทนเนอร์นี้ |

ทั้งหมดเป็นเหตุผลเชิงโครงสร้าง ไม่ใช่ skip เพราะข้อมูลถูกเทสก่อนหน้าทำพัง

### L3 อ่านประวัติจริง ไม่ใช่ abstain

`test_l3_remote_e2e` บังคับเงื่อนไขนี้ไว้เองในเทส

```python
out = await _ok(USER, [4.0, 0.3, 3.0, 0.8, 0.5, 0.2])
assert out["eligibility"] == "warn"
assert out["n_history"] >= L3.TIER_WARN
```

ก่อนแก้ ml-service ของเทส เทสกลุ่มนี้ fail เพราะได้ `abstain` — หลังแก้ผ่านทั้งหมด

---

## 6. cleanup ทำงานแม้เทสล้ม

บังคับให้ล้มด้วย `TEST_FORCE_FAIL`

```
7 failed, 18 passed
state: ไม่มี state รั่ว
exit code 1
```

---

## 7. order matrix — ผลไม่ขึ้นกับลำดับการรัน

ทุกโหมด `drop/create hub_test → clone schema → stamp → seed → ล้าง Redis DB 15` ใหม่ก่อนรัน
และตรวจว่าจุดตั้งต้นเหมือนกันด้วย manifest hash ของ seed

| โหมด | ลำดับที่ส่งให้ pytest | ผล | เวลา | state รั่ว |
|---|---|---|---|---|
| forward | `.` (ลำดับปกติของ pytest) | 1187 passed · 21 skipped · 0 failed | 205 s | ไม่มี |
| reverse | ไฟล์เรียงกลับหลัง | 1187 passed · 21 skipped · 0 failed | 208 s | ไม่มี |
| shuffle seed 1 | สุ่มด้วย `random.Random(1)` | 1187 passed · 21 skipped · 0 failed | 202 s | ไม่มี |
| shuffle seed 2 | สุ่มด้วย `random.Random(2)` | 1187 passed · 21 skipped · 0 failed | 203 s | ไม่มี |
| shuffle seed 3 | สุ่มด้วย `random.Random(3)` | 1187 passed · 21 skipped · 0 failed | 204 s | ไม่มี |

ทั้ง 5 โหมดเปิด `TEST_DIAG=1` (บันทึกเหตุที่ token ถูกปฏิเสธ + การกระโดดของนาฬิกา
ไม่บันทึก JWT/PII) และรายงาน state ท้ายรอบให้ผลเดียวกันหมด

```
ตรวจสภาพแวดล้อมก่อน/หลังรอบเทส
  audit_logs: 0 -> 60..72 (โตได้)
  ไม่มี state รั่ว
ลบ key ของรอบนี้ 119-121 รายการ (namespace test:{run_id}:)
```

`audit_logs` ต่างกันระหว่าง 60–72 แถวเพราะลำดับที่ต่างกันทำให้จำนวน event ที่เขียน log
ต่างกัน — คอลัมน์นี้ถูกประกาศไว้ว่า "โตได้" ตั้งแต่ §4 จึงไม่นับเป็นการรั่ว
ส่วนตัวเลขที่ต้องเท่ากันเป๊ะ (ผู้ใช้, session, subsystem, access_list, key ค้างท้ายรอบ)
เท่ากันทุกโหมด

**ข้อจำกัดที่ต้องบอกให้ตรง** — 5 รอบนี้รันก่อน pin image ของ `ml-service-test`
(ตอนนั้นเป็น image ที่ build จาก Dockerfile เดียวกันแต่คนละ build) ส่วน 3 รอบใน §8
รันบน image ที่ pin แล้ว ดังนั้นหลักฐานระดับ release gate คือ §8 ไม่ใช่ตารางนี้

### รันทีละไฟล์ — 94 ไฟล์ แยกกันคนละกระบวนการ

รันไฟล์ละหนึ่ง process บนฐานข้อมูลที่ setup ใหม่หนึ่งครั้ง แล้วรวมตัวเลข

| รายการ | รวมจากการรันทีละไฟล์ | รันทั้งชุดรอบเดียว | ตรงกัน |
|---|---|---|---|
| passed | 1187 | 1187 | ใช่ |
| skipped | 21 | 21 | ใช่ |
| failed / error | 0 | 0 | ใช่ |
| state รั่ว | ไม่มีสักไฟล์ | ไม่มี | ใช่ |

ตัวเลขตรงกันเป๊ะแปลว่า **ไม่มีเทสตัวไหนต้องพึ่งไฟล์อื่นรันมาก่อน** และไม่มีตัวไหน
ที่ผ่านได้เพราะไฟล์ก่อนหน้าทิ้งข้อมูลไว้ให้

10 ไฟล์ไม่มีบรรทัดสรุปแบบ `passed` เพราะเป็นไฟล์ที่ skip ล้วน (`1 skipped` ทั้งไฟล์)
ตรงกับเหตุผล skip ใน §5 — ยกเว้นหนึ่งไฟล์ที่ต่างออกไป ดูด้านล่าง

### พบระหว่างทาง: `tests/test_l1_oidc_authlib.py` collect ได้ 0 ตัว

```
collected 0 items
no tests ran in 1.81s
```

ไฟล์นี้เป็น **สคริปต์สแตนด์อโลน** (มี `main()` + `if __name__ == "__main__"`
ไม่มีฟังก์ชันขึ้นต้นด้วย `test_`) แต่ตั้งชื่อว่า `test_*.py` — pytest จึงเก็บมันมา
แล้วไม่ได้อะไรเลย **โดยไม่มีอะไรฟ้อง** ต่างจาก `test_e2e_full_stack.py` กับ
`test_l1_oidc.py` ที่ถูกใส่ `--ignore` ไว้ชัดเจน

ไม่กระทบตัวเลข 1187/21/0 (มันไม่ได้นับอะไรอยู่แล้ว) แต่เป็นหลุมแบบเดียวกับที่ทำให้
รอบก่อน ๆ เชื่อผลไม่ได้ — ไฟล์ที่ดูเหมือนเทสแต่ไม่ได้เทสอะไร · **ยังไม่แก้**
(เปลี่ยนชื่อไฟล์หรือย้ายไป `scripts/` เป็นงานแยก)

### บั๊กของ harness ที่เจอตอนทำหัวข้อนี้

`scripts/test/order_matrix.sh per-file` รอบแรก ๆ **จบตั้งแต่ไฟล์แรกโดยไม่มีใครฟ้อง**
สองสาเหตุซ้อนกัน

1. `summarize()` ใช้ `grep -E "passed|failed|error"` — ไฟล์ที่ skip ล้วนไม่มีคำพวกนี้
   grep คืน 1 แล้ว `set -e` ฆ่าสคริปต์ทั้งตัว
2. วนด้วย `list_files | while read` แต่ `run_tests.sh` เรียก `docker compose exec -T`
   ซึ่ง **กลืน stdin** จึงดูดรายชื่อไฟล์ที่เหลือไปหมดตั้งแต่ไฟล์แรก

แก้ด้วย `|| true` ที่ grep, ใช้ `mapfile` แทน pipe-to-while, ส่ง `< /dev/null`
ให้ `run_tests.sh` และพิมพ์ `จำนวนไฟล์ที่จะรัน` ออกมาให้เห็นว่าลูปเดินครบจริง

---

## 8. full suite 3 รอบติด (release gate)

### สภาพแวดล้อมที่ใช้เป็นหลักฐาน

| รายการ | ค่า |
|---|---|
| commit | `9dd2278` |
| image `hub-backend` | `sha256:d140bf98e81d1b0802c7d9183ea235493e4b2520a5b1428d7ece97bd4fc20e4d` |
| image `ml-service` (dev) | `sha256:d7282b7d0112135eba9254bb429fbd58bd840ef60491896e69d30fb0b533c87e` |
| image `ml-service-test` | `sha256:d7282b7d0112135eba9254bb429fbd58bd840ef60491896e69d30fb0b533c87e` — **ตัวเดียวกับ dev** |
| ฐานข้อมูล | `hub_test` (สร้างใหม่ทุกรอบ) |
| Redis | DB 15 + prefix `test:{run_id}:` + lock `test:lock` |
| manifest ของ seed | `f7c41f7af1b07b93` เท่ากันทั้ง 9 ครั้งที่ setup (§7 ห้า + ทีละไฟล์หนึ่ง + §8 สาม) |

`ml-service-test` ถูกเปลี่ยนเป็น `image: cah-hub-ml-service:latest` (ไม่ build ซ้ำ)
เพื่อให้หลักฐานอ้าง digest เดียวกับที่ dev ใช้จริง ไม่ใช่ image ที่บังเอิญ build จาก
Dockerfile เดียวกัน — ยืนยันด้วย `docker inspect` ว่า `hub-ml` กับ `hub-ml-test`
ชี้ image id เดียวกัน

### ผล

| รอบ | ลำดับ | ผล | เวลา | state รั่ว |
|---|---|---|---|---|
| repeat 1 | forward | 1187 passed · 21 skipped · 0 failed | 197.43 s | ไม่มี |
| repeat 2 | forward | 1187 passed · 21 skipped · 0 failed | 198.24 s | ไม่มี |
| repeat 3 | forward | 1187 passed · 21 skipped · 0 failed | 199.11 s | ไม่มี |

สถิติก่อน–หลังของทั้ง 3 รอบเหมือนกันทุกตัว

```
audit_logs: 0 -> 60 (โตได้)
ไม่มี state รั่ว
ลบ key ของรอบนี้ 119 รายการ
```

จำนวน skip คงที่ที่ 21 ทุกรอบ (เหตุผลแจกแจงไว้ใน §5) — ไม่มีเทสที่หายไปเงียบ ๆ
เพราะถูกข้าม และ `1187 + 21 = 1208` เท่ากับจำนวนที่ collect ได้ทุกรอบ

### เกณฑ์ที่ยัง **ไม่** ถือว่าผ่านจากผลชุดนี้

- flaky 401 ยังไม่สรุปสาเหตุ (§9) — ชุดเต็ม 8 รอบติดไม่เจอ ไม่ได้แปลว่าไม่มี
- ตัวเลขนี้ผูกกับคอนฟิกของคอนเทนเนอร์ที่รันอยู่ตอนนี้ ไม่ใช่คอนฟิก Config B
  (gamma 1.0 / เกณฑ์ 0.98-0.995-0.9999) — การเปิด Shadow epoch ใหม่ต้องตรวจคอนฟิกแยก
  ตาม B66 ไม่ใช่อ้างผลเทสชุดนี้ · รายละเอียดใน §11

---

## 9. flaky 401 — ยังไม่สรุปสาเหตุ

- เก็บหลักฐานด้วย plugin แบบเปิดผ่าน env (`TEST_DIAG=1`) ซึ่งบันทึก **เหตุผล** ที่ token
  ถูกปฏิเสธ + ส่วนต่างเวลา + การกระโดดของนาฬิกา · **ไม่บันทึก JWT, อีเมล, user id หรือ jti**
- วัดแล้วพบว่านาฬิกาใน container ถอยหลังจริง 1–8 ms ราวทุก 30 วินาที และ PyJWT 2.12
  ปฏิเสธ token ที่ `iat > now` โดย leeway = 0 — **แต่ยังจับ `ImmatureSignatureError` จริง
  ไม่ได้สักครั้ง** จึงยังไม่ใช่ข้อสรุป
- **ยังไม่แตะ `verify_token` และไม่เพิ่ม leeway** ตามที่ตกลงไว้

---

## 10. สิ่งที่ยังไม่ทำ

| งาน | สถานะ |
|---|---|
| baseline migration ที่สร้างจากศูนย์ได้ | ยังไม่ทำ — §3 |
| `ix_user_totp_credentials_user_id` drift | ยังไม่แก้ (มีมาก่อนงานนี้) |
| กู้ข้อมูล `hub_db` ของ dev (นักศึกษา 56 คน + ผู้ใช้ทดสอบค้าง + key ค้าง) | ยังไม่ทำ — ต้องสำรองและ dry-run ก่อน |
| Config B shadow artifact | ยังไม่เริ่ม — รอ release gate ผ่าน |
| `tests/test_l1_oidc_authlib.py` collect ได้ 0 ตัว | ยังไม่แก้ — §7 (เปลี่ยนชื่อ/ย้ายเป็นงานแยก) |

---

## 11. ตรวจคอนฟิกก่อนจะพูดถึง Shadow epoch ใหม่ (B66)

อ่านค่าจาก **คอนเทนเนอร์ที่รันอยู่จริง** ไม่ใช่จาก `.env` หรือค่า default ในโค้ด

```
docker compose exec -T hub-backend python -c "from app.config import settings; ..."
```

| รายการ | Config B ที่ freeze ไว้ (P48-T2) | คอนเทนเนอร์ตอนนี้ | ตรงกัน |
|---|---|---|---|
| `l4_gamma` | 1.0 | **0.35** | ไม่ |
| threshold warn | percentile 0.98 | **0.50** (ค่าสัมบูรณ์) | ไม่ |
| threshold challenge | percentile 0.995 | **0.70** (ค่าสัมบูรณ์) | ไม่ |
| threshold block | percentile 0.9999 | **0.85** (ค่าสัมบูรณ์) | ไม่ |
| `calibration_version` | ต้องมี (ตาราง ECDF) | `None` | ไม่ |
| `calibration_sha256` | ต้องมี | `None` | ไม่ |
| `shadow_epoch_id` | ต้องมี | `None` | ไม่ |
| `ml_shadow_mode` | `true` | `true` | ใช่ |
| `l3_mode` | `shadow` | `shadow` | ใช่ |

ค่าที่คอนเทนเนอร์ใช้อยู่คือ `DEFAULT_GAMMA = 0.35` และ
`DEFAULT_THRESHOLDS = {warn 0.50, challenge 0.70, block 0.85}` ใน
`app/security/risk_fusion.py` ผ่าน `settings.l4_gamma` / `settings.l4_threshold_*`
(`app/security/risk_engine.py:94-98`)

**สรุป** — ระบบที่รันอยู่ **ไม่ใช่ Config B** · threshold ของ Config B เป็น *เปอร์เซ็นไทล์*
ซึ่งแปลงเป็นค่าตัดสินจริงไม่ได้ถ้าไม่มีตาราง calibration และตารางนั้นยังไม่มีอยู่
(`calibration_version`/`calibration_sha256` เป็น `None`)

ตามบทเรียน B66 การประกาศว่า "พร้อมเปิด Shadow ด้วย Config B" ในสภาพนี้จะเป็นการ
วัดคนละระบบกับที่ deploy อีกครั้ง — **จึงยังไม่พร้อม** สิ่งที่ต้องทำก่อน เรียงตามลำดับ

1. สร้างตาราง calibration (ECDF) จากผลที่ freeze แล้ว พร้อม `calibration_version`
   + `calibration_sha256` — ยังไม่ทำ และ**ห้ามสร้างจากผลเก่าที่ปะติดปะต่อ**
2. แปลง percentile 0.98 / 0.995 / 0.9999 เป็นค่าตัดสินผ่านตารางนั้น
3. ตั้ง `l4_gamma=1.0` + threshold ที่ได้ + `shadow_epoch_id` แล้ว
   `up -d --force-recreate` (B36 — `restart` ไม่อ่าน env ใหม่)
4. ทดสอบ integration ในสภาพแวดล้อมแยก พิสูจน์ว่า login จริงบันทึกคะแนนเป็น shadow
   อย่างเดียว (`would_*`) และคอนฟิกที่อ่านจากคอนเทนเนอร์ตรงกับ Config B ทุกช่อง
5. ค่อยพูดเรื่องเปิด Shadow epoch

ผลเทส 1187 passed ในรายงานนี้ **ไม่ใช่หลักฐานว่า Config B ใช้งานได้** — เป็นหลักฐาน
ว่าชุดเทสของคอนฟิกปัจจุบันเสถียรและไม่รั่วข้ามรอบเท่านั้น

---

## 12. วิธีรันและวิธีทำซ้ำหลักฐานในรายงานนี้

```bash
bash scripts/test/setup_test_db.sh          # drop/create + clone schema + seed + manifest
bash scripts/test/verify_test_schema.sh     # ตรวจ schema ทีละรายการ (ไม่เชื่อ stamp head)
bash scripts/test/run_tests.sh              # ทั้งชุด
bash scripts/test/run_tests.sh tests/test_auth.py    # เฉพาะไฟล์
TEST_DIAG=1 bash scripts/test/run_tests.sh           # เปิดเครื่องมือวินิจฉัย (ไม่บันทึก JWT/PII)
TEST_FORCE_FAIL=test_auth bash scripts/test/run_tests.sh tests/test_auth.py   # พิสูจน์ cleanup
```

ทำซ้ำหลักฐานแต่ละหัวข้อ

| หัวข้อ | คำสั่ง |
|---|---|
| §7 order matrix | `bash scripts/test/order_matrix.sh all` |
| §7 รันทีละไฟล์ | `bash scripts/test/order_matrix.sh per-file` |
| §8 release gate | `bash scripts/test/order_matrix.sh repeat 3` |
| §11 คอนฟิก Shadow | `docker compose exec -T hub-backend python -c "from app.config import settings; print(settings.l4_gamma, settings.l4_threshold_warn, settings.l4_threshold_challenge, settings.l4_threshold_block, settings.calibration_version, settings.calibration_sha256, settings.shadow_epoch_id)"` |
| ยืนยัน image ตรงกัน | `docker inspect hub-ml hub-ml-test --format '{{.Image}}'` |

ไฟล์ผลดิบของทุกรอบเขียนลง `${TEST_RESULT_DIR:-/tmp/cah-test-results}` ซึ่ง **ไม่ถาวร**
(หายเมื่อล้าง temp) ตัวเลขทั้งหมดที่ใช้ตัดสินจึงคัดลอกมาไว้ในรายงานนี้แล้ว
ถ้าต้องการเก็บผลดิบไว้ ให้ตั้ง `TEST_RESULT_DIR` ชี้ที่อื่นก่อนรัน

```bash
TEST_RESULT_DIR=/e/hub/test-evidence/2026-09-15 bash scripts/test/order_matrix.sh repeat 3
```

**ห้ามชี้ `TEST_RESULT_DIR` เข้าไปใน repo** — ผลดิบมีอีเมลและ user id ของข้อมูล seed
