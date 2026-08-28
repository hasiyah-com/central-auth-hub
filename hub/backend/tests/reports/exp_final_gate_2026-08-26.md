# FINAL GATE — เทสรอบสุดท้าย (fresh evaluation set)

**วันที่:** 26 ส.ค. 2026  
**train / validation:** seeds 42–46 (ชุดเดิม) · **evaluation:** seeds 101–105 (**normal + attack ใหม่ทั้งหมด — โมเดลไม่เคยเห็น**)  
**Config ที่ล็อก:** sequence-residual · W=5 · threshold p99.9 · L3 = monitoring channel เท่านั้น

**ขนาด eval:** attack 3230 · normal 60000 · campaign instance 300


## 1. ตรวจก่อนเชื่อผล

| การตรวจ | ผล |
|---|---|
| data leakage (eval ซ้ำ train) | **0/63230** — ✅ ไม่มี |
| generator shortcut (feature AUC>0.99 หรือ support<5%) | **0 feature** — ✅ ไม่พบ |
| L3 เปลี่ยน allow/challenge/block | **0 ครั้ง** — ✅ ไม่แตะ |

## 2. ผลตามขนาดข้อมูลต่อคน

| size | recall (challenge+) | precision | Challenge FPR | L3 FPR |
|---|---|---|---|---|
| 50 | 63.3% [61.7, 65.0] | 53.0% [51.4, 54.6] | 3.0% [2.9, 3.2] | 0.0% [0.0, 0.0] |
| 100 | 62.7% [61.0, 64.4] | 61.1% [59.4, 62.7] | 2.2% [2.0, 2.3] | 0.9% [0.8, 1.0] |
| 500 | 61.7% [60.0, 63.4] | 69.0% [67.3, 70.7] | 1.5% [1.4, 1.6] | 0.8% [0.7, 0.9] |
| 1000 | 61.9% [60.2, 63.5] | 68.7% [67.0, 70.4] | 1.5% [1.4, 1.6] | 0.8% [0.7, 0.9] |
| 5000 | 61.9% [60.2, 63.6] | 69.1% [67.4, 70.7] | 1.5% [1.4, 1.6] | 0.7% [0.6, 0.8] |

## 3. แยกชั้น (size 5000)

| ชั้น | ค่า [Wilson CI95] |
|---|---|
| L1 Rule อย่างเดียว (warn+) | 50.5% [48.7, 52.2] |
| L2 Behavior อย่างเดียว (warn+) | 49.8% [48.0, 51.5] |
| L3 ยิง (event) | 5.7% [5.0, 6.6] |
| **L4 รวม (challenge+)** | **61.9% [60.2, 63.6]** |

## 4. Campaign-level (n = 300)

| ตัวชี้วัด | ค่า [CI95] |
|---|---|
| L1/L2 surfaced | **96.7% [94.0, 98.2]** |
| L3 surfaced | 16.3% [12.6, 20.9] |
| **L3 only** | **0.7% [0.2, 2.4]** |
| event L3-unique | 1.0% [0.7, 1.4] |
| false incident/user-day | 1.4% [1.2, 1.5] |

## 5. Latency & abstention

| size | abstention | fit (s/คน) | score (ms/event) |
|---|---|---|---|
| 50 | 100.0% | 0.00 | 0.000 |
| 100 | 0.0% | 0.39 | 4.286 |
| 500 | 0.0% | 0.48 | 4.655 |
| 1000 | 0.0% | 0.54 | 4.533 |
| 5000 | 0.0% | 0.87 | 4.361 |

## 6. เกณฑ์ผ่าน/ไม่ผ่าน

| เกณฑ์ | ผล |
|---|---|
| ไม่มี data leakage | ✅ |
| L3 ไม่แตะ access decision | ✅ |
| ไม่มี generator shortcut | ✅ |
| L3 FPR ≤ 1% | ✅ |
| Challenge FPR ≤ 3% | ✅ |
| L1/L2 campaign surfaced ≥ 90% | ✅ |
| L3 มีคุณค่าพอสำหรับ enforcement (unique ≥3%) | ❌ |

---

## ข้อสรุป

> # พร้อมใช้แบบ shadow + พร้อมเข้าสู่ production replay

---

## 7. Full pytest (Docker)

```
docker compose exec hub-backend pytest . -q \
    --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
=> 756 passed, 52 skipped, 0 failed  (116.79s)
```

*(2 ไฟล์ที่ ignore เป็น standalone script ที่มี `sys.exit()` ระดับ module — collect ด้วย pytest ไม่ได้ตั้งแต่ต้น)*

---

## 8. บันทึกการตรวจ leakage (สำคัญเชิงวิธี)

รอบแรก leakage check **FAIL: 8/63,207 แถว** → ตรวจรายตัวก่อนสรุป พบว่าเป็น
**การชนกันของ timestamp โดยบังเอิญ ไม่ใช่ leakage**:

| ตัวอย่าง | train | eval |
|---|---|---|
| U03 @ 2158-01-04 15:53:59 | duration 25.64 · `passkey` | duration 10.32 · `google` |
| U03 @ 2167-11-12 15:59:05 | duration 133.84 | duration 58.15 |

เหตุการณ์คนละเหตุการณ์ที่บังเอิญมี `(timestamp, device, subsystem)` เดียวกัน
→ **check หยาบเกินไป** (เทียบแค่ 3 field) แก้เป็นเทียบ **11 field ทั้งแถว**
(`created_at, logout_at, device_signature, subsystem, duration_min, login_method,
login_successful, user_agent, passkey_age_days, permission_change_age, concurrent_session_count`)

**ผลหลังแก้: 0/63,230 → ไม่มี leakage จริง** ✅

> บทเรียน: check ที่ FAIL ต้องตรวจสาเหตุก่อนสรุป — อาจเป็น check เองที่ผิด ไม่ใช่ระบบ

---

## 9. อ่านผล

### สิ่งที่ยืนยันได้จาก fresh evaluation set

1. **ระบบ generalize ได้จริง** — normal + attack ชุดใหม่ทั้งหมด (seeds 101–105)
   ให้ recall **61.9%** · precision **69.1%** · Challenge FPR **1.5%** ใกล้เคียงชุด holdout เดิม
   (60.8% / 66.5% / 1.6%) → **ไม่ใช่การจำชุดข้อมูล**
2. **L1/L2 คือตัวตรวจจับ** — L1 อย่างเดียว 50.5% · L2 อย่างเดียว 49.8% · รวม 61.9%
   (สองชั้นเสริมกัน ไม่ซ้ำกันทั้งหมด)
3. **L3 ยิง 5.7% ของ attack event** แต่ unique เพียง **1.0%** และ campaign-only **0.7%**
4. **L3 ไม่แตะ access decision เลย (0 ครั้ง)** — monitoring channel ทำงานตามสเปค
5. **ขนาดข้อมูลอิ่มตัวที่ ~500/คน** — recall/precision/FPR แทบไม่ขยับตั้งแต่ 500 ถึง 5000
6. **latency ยอมรับได้** — fit 0.87s/คน (ทำ offline + cache) · score 4.4ms/event

### สิ่งที่ยังไม่ผ่าน

**L3 unique 1.0% < เกณฑ์ 3%** → ยังไม่มีหลักฐานสำหรับ enforcement (MFA/block)

---

## 10. ข้อสรุปสุดท้าย

> # ✅ พร้อมใช้แบบ shadow + พร้อมเข้าสู่ production replay
>
> ผ่านทุกเกณฑ์ความปลอดภัย (ไม่มี leakage · ไม่มี shortcut · L3 ไม่แตะ access ·
> L3 FPR 0.7% ≤1% · Challenge FPR 1.5% ≤3% · L1/L2 campaign surfaced 96.7% ≥90%)
> บนชุดข้อมูลที่โมเดลไม่เคยเห็น + full pytest 756 ผ่าน
>
> **แต่ยังไม่พร้อม enforcement** — L3 unique 1.0% ต่ำกว่าเกณฑ์ 3%
> L3 คงบทบาท **corroborating evidence / shadow monitoring** เท่านั้น

**สิ่งที่ต้องทำก่อนเปิดใช้ L3 shadow จริง:**
1. ตัดสินใจสถาปัตยกรรม — hub-backend ไม่มี numpy/sklearn (ต้องเพิ่ม deps หรือย้ายไป ml-service)
2. ตั้ง `L3_SEQUENCE_ENABLED=true` + `docker compose up -d --force-recreate` (B36)
3. เก็บ `l3_sequence` contract ลง audit เพื่อวัด raw vs effective บน traffic จริง
