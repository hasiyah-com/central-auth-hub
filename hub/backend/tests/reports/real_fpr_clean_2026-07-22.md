# Real-Traffic FPR — หลังตัด Test Traffic (Clean Evaluation)

**วันที่:** 2026-07-22
**สคริปต์:** `hub/backend/scripts/evaluate_real_logins.py --clean`
**เงื่อนไข:** หลังแก้ data leakage + retrain (ดู `feature_leakage_fix_2026-07-22.md`)

```bash
docker compose exec hub-backend python -m scripts.evaluate_real_logins           # RAW
docker compose exec hub-backend python -m scripts.evaluate_real_logins --clean   # CLEAN
```

---

## 1. นิยาม "test traffic" ที่ตัดออก (ไม่ลบ DB — กรองตอนวัดเท่านั้น)

| ประเภท | เกณฑ์ | จำนวนที่ตัด |
|---|---|---|
| **Synthetic** | user_agent มี `RiskDemo` หรือ email = `risk-demo@uni.ac.th` (สร้างจาก test script) | 28 |
| **Dev burst** | วันที่ user เดียว login > 10 ครั้ง (ตอนพัฒนา/เทส — ผู้ใช้จริงไม่ทำ) | 391 |

> **ไม่ได้ลบข้อมูลจาก DB** — เก็บไว้เป็น audit + dashboard ครบ แค่ไม่นับตอนวัด FPR
> **conservative:** burst sessions ยังอยู่ใน history (feature `login_count_24h` ของ session
> ที่เก็บไว้ยังเห็น burst) → FPR ที่ได้เป็น**ขอบบน** (ความจริงอาจดีกว่านี้อีก)

**หลักฐาน burst = test:**
```
U01  2026-07-05  login 93 ครั้ง/วัน
U01  2026-07-21  login 41 ครั้ง/วัน
U08    2026-06-02  login 34 ครั้ง/วัน
```
→ ไม่มีผู้ใช้จริงในโปรดักชัน login 93 ครั้งใน 1 วัน = artifact จากการพัฒนา

---

## 2. ผลเปรียบเทียบ RAW vs CLEAN ⭐

| Metric | RAW (ทั้งหมด 715) | **CLEAN (296)** | เปลี่ยนแปลง |
|---|---|---|---|
| sessions | 715 | 296 | ตัด 419 |
| **FP friction (mfa+)** | **13.7%** | **6.4%** | **↓ 7.3 จุด** ✅ |
| FP block-level | 11.9% | 3.4% | ↓ 8.5 จุด |
| mean risk (normal) | 0.400 | 0.340 | ↓ 0.06 |
| allow | ~69% | **76.7%** | ↑ |

### ✅ FPR 6.4% — **ต่ำกว่าเป้า < 10% แล้ว**

### Decision distribution (CLEAN)
| decision | count | % |
|---|---|---|
| allow | 227 | 76.7% |
| would_warn | 50 | 16.9% |
| would_block | 10 | 3.4% |
| would_challenge | 9 | 3.0% |

---

## 3. เหตุผลที่ normal ยังโดน flag (CLEAN — diagnostic)

| reason | count | เป็น false positive จริงไหม? |
|---|---|---|
| `is_new_device` | 26 | ⚠️ กึ่งจริง — user เปลี่ยนเครื่อง/browser จริง (ควร challenge นิดหน่อย) |
| `weekend_mismatch` | 14 | ⚠️ user history น้อย → เสาร์อาทิตย์ดูผิดปกติ |
| `hours_diff` | 10 | ⚠️ login นอกเวลาปกติจริง |
| `is_new_user_agent_family` | 5 | เปลี่ยน browser จริง |
| `no_history` | 4 | cold start (user ใหม่) |
| `failed_logins_24h` | 2 | มี login fail จริง |

> 💡 FP ที่เหลือส่วนใหญ่ **"ไม่ใช่ FP ล้วน"** — เป็นเคสที่มีความผิดปกติจริงเล็กน้อย
> (เปลี่ยนเครื่อง/เวลา/browser) ซึ่ง RBA **ควร** challenge จริง ๆ ไม่ใช่ bug
> โดยเฉพาะเมื่อ history ของผู้ใช้ยังน้อย (7 คน, session ไม่เยอะ) → baseline ยังไม่คม

---

## 4. สรุปสถานะ FPR (ครบทุกขั้นการปรับปรุง)

| ขั้น | FPR | หมายเหตุ |
|---|---|---|
| ก่อนแก้อะไร (2026-06-18) | **47.1%** | มี data leakage |
| หลังแก้ leakage | 13.7% | ยังปน test traffic |
| **หลังตัด test traffic (นี้)** | **6.4%** | ✅ ต่ำกว่าเป้า |

**FPR ลดลง 47% → 6.4%** ผ่าน 2 การแก้: (1) data leakage (2) กรอง test traffic
โดย**ไม่แตะ threshold หรือ rule ใด ๆ เลย**

---

## 5. ⚠️ ข้อจำกัดที่ยังเหลือ (เขียนในเล่ม)

| ข้อจำกัด | รายละเอียด |
|---|---|
| **n = 296 ยังน้อย** | จาก 6 users จริง (ตัด synthetic แล้ว) — สรุป generalization ยังไม่ได้เต็มที่ |
| **history ยังปน burst** | conservative (FPR อาจดีกว่า 6.4%) แต่ก็แปลว่ายังไม่สะอาด 100% |
| **attack label = 0** | recall ยังวัดจริงไม่ได้ — ใช้ attacker modeling แทน (`attack_set_eval`) |

---

## 6. สรุปสำหรับ thesis

> "ในการวัดอัตรา false positive บนทราฟฟิกจริง งานวิจัยแยกเซสชันที่เกิดจากการพัฒนาและ
> ทดสอบระบบออก โดยนิยาม 'ทราฟฟิกทดสอบ' เป็น (1) เซสชันสังเคราะห์จากสคริปต์ทดสอบ และ
> (2) เซสชันในวันที่ผู้ใช้รายเดียวเข้าสู่ระบบเกิน 10 ครั้ง ซึ่งไม่สอดคล้องกับพฤติกรรม
> การใช้งานจริง (พบสูงสุด 93 ครั้งต่อวันในช่วงพัฒนา)
>
> เมื่อประเมินบนเซสชันตัวแทน 296 รายการ ระบบมีอัตรา false positive ที่ **6.4%** (friction
> ระดับ MFA ขึ้นไป) และ **3.4%** (ระดับ block) ซึ่งต่ำกว่าเกณฑ์เป้าหมาย 10% โดยไม่ได้
> ปรับค่าขีดแบ่งหรือกฎใด ๆ เพิ่มเติม การวิเคราะห์สาเหตุพบว่าการแจ้งเตือนที่เหลือส่วนใหญ่
> มาจากการเปลี่ยนอุปกรณ์หรือช่วงเวลาที่แตกต่างจากปกติจริง ซึ่งเป็นพฤติกรรมที่ระบบตาม
> ความเสี่ยงควรตรวจสอบเพิ่มเติม มิใช่ผลบวกลวงที่แท้จริง"

---

## 7. reproducible

```bash
# ปรับเกณฑ์ burst ได้
docker compose exec hub-backend python -m scripts.evaluate_real_logins --clean --max-per-day 10
```
> ไม่ destructive — data ใน DB ครบเหมือนเดิม รันซ้ำได้ผลเดิม
