# ผลปิดท้าย Synthetic Experiment — Campaign-level (Wilson / cluster / hierarchical bootstrap)

**วันที่:** 26 ส.ค. 2026 · seeds 42–46 · Config F (W=5, p99.9) · **final holdout**

> **หยุดปรับโมเดลจาก final holdout แล้ว** — รายงานนี้ปรับเฉพาะ *วิธีวัด* ไม่แตะฟีเจอร์/threshold/window
> W=5 เลือกจาก **development set** ก่อนเปิด holdout · ผล W10/MULTI เป็น exploratory เท่านั้น

---

## 1. ขนาดข้อมูลและนิยาม

| รายการ | จำนวน |
|---|---|
| **campaign instance** | **300** (60/seed × 5 seeds) · **5 event ต่อ instance** |
| attack event (holdout) | 3,230 |
| normal event | 60,000 |
| user-day ที่สังเกต | 21,939 |

### นิยาม (ห้ามอ่านกว้างกว่านี้)

> **"Campaign surfaced"** = มี **อย่างน้อย 1 เหตุการณ์** ใน campaign ถูกยกเป็น warn+
> **ไม่ได้แปลว่า**ระบบเข้าใจว่า 5 เหตุการณ์นั้นเป็น campaign เดียวกัน

### ⚠️ ข้อจำกัดของหน่วยประเมิน

campaign 300 ชุด **ไม่อิสระต่อกันเต็มที่** — สร้างจาก **โปรไฟล์ผู้ใช้พื้นฐาน 12 คนที่ใช้ซ้ำใน 5 seed**
จึงรายงานทั้ง Wilson (ถือ campaign ต่าง seed เป็นหน่วยแยก) และ **hierarchical bootstrap**
(resample user → seed → instance) ที่สะท้อนความสัมพันธ์ตามผู้ใช้

### วิธีคำนวณช่วงความเชื่อมั่น

| ตัวชี้วัด | วิธี |
|---|---|
| สัดส่วนระดับ campaign | Wilson (n=300) **+ hierarchical bootstrap** `(user → seed → instance)` |
| event-level metrics | cluster bootstrap `(seed, user, campaign_instance)` |
| normal FPR | cluster bootstrap `(seed, user, day)` |
| **false incident/user-day** | **cluster bootstrap `(seed, user)`** |
| lead-time / TTD / alerts | percentile bootstrap 5,000 resample |

---

## 2. Campaign surfaced (n = 300 campaign)

| ตัวชี้วัด | Wilson | **Hierarchical bootstrap** |
|---|---|---|
| **L1/L2 surfaced ≥1 เหตุการณ์** | 97.3% [94.8, 98.6] | **97.3% [93.7, 99.7]** |
| L3 surfaced ≥1 เหตุการณ์ | 18.7% [14.7, 23.5] | **18.7% [6.7, 33.3]** |
| **L3 only** (L1/L2 ไม่ surface เลย) | 0.3% [0.1, 1.9] | **0.3% [0.0, 1.7]** |
| L1/L2 only | 79.0% [74.0, 83.2] | — |
| surfaced ทั้งคู่ | 18.3% [14.4, 23.1] | — |
| รวมสองชั้น | 97.7% [95.3, 98.9] | — |

**hierarchical CI กว้างกว่า Wilson ชัดเจน** (L3 surfaced: 14.7–23.5 → **6.7–33.3**)
ยืนยันว่าการถือ campaign เป็นอิสระทำให้ประเมินความแม่นสูงเกินจริง

> **ข้อสรุป:** บน final holdout นี้ L3 มี campaign-level unique contribution เพียง
> **1 จาก 300 campaign (0.3%)** ภายใต้นิยาม "surface ≥1 เหตุการณ์"
> ⚠️ ไม่ใช่ข้อสรุปว่า L3 ไม่มีทางมี unique contribution — campaign ใน production
> อาจมีรูปแบบต่างจาก generator (upper CI ยังเปิดถึง 1.7–1.9%)

---

## 3. First-detector & Lead-time

> **ฐาน = 55 campaign** ที่ **ทั้ง L1/L2 และ L3 surface** (18.3% ของ 300) — ไม่ใช่ 300

| ตัวชี้วัด | ค่า [CI95] |
|---|---|
| L1/L2 surface ก่อน | **58.2% [45.0, 70.3]** |
| surface พร้อมกัน (เหตุการณ์เดียวกัน) | 34.5% [23.4, 47.7] |
| L3 surface ก่อน | **7.3% [2.9, 17.3]** |
| **lead-time** (base_pos − l3_pos · + = L3 เร็วกว่า) | **−1.47 [−1.89, −1.04]** |

**CI ของ lead-time เป็นลบทั้งช่วง** → L3 ตรวจพบ **ช้ากว่า L1/L2 เฉลี่ย 1.47 เหตุการณ์
อย่างมีนัยสำคัญ** ⇒ ไม่มีคุณค่าเชิง early-warning

| ตัวชี้วัด | ค่า [CI95] | ฐาน |
|---|---|---|
| time-to-detect ของ L3 (ลำดับที่) | 2.96 [2.57, 3.36] | **56 campaign ที่ L3 surface** |
| alerts ต่อ campaign | **2.07 [1.75, 2.43]** | **56 campaign ที่ L3 surface** |
| **deduplicated incident** | **1.00** ต่อ campaign | ถ้ารวม alert ของ campaign เดียวเป็น incident เดียว |

**Sanity check (บังคับใน harness):** alerts CI บน (2.43) ต้อง ≤ **5** = จำนวน event สูงสุดต่อ campaign ✅
*(assert อยู่ในโค้ด — ถ้า instance key ผิดจะหยุดทำงานทันที)*

---

## 4. Event-level และภาระงาน

| ตัวชี้วัด | ค่า [CI95] | cluster |
|---|---|---|
| event L3-unique | 1.3% [0.9, 1.8] | `(seed, user, campaign)` |
| L3 FPR (event) | 0.6% [0.5, 0.6] | `(seed, user, day)` |
| false incident ต่อ user-day | 1.1% [0.9, 1.4] | `(seed, user)` |

### ภาระ alert ตามขนาดผู้ใช้

| ผู้ใช้ | false incident/วัน [CI95] |
|---|---|
| 100 | **1.1** [0.9, 1.4] |
| 1,000 | 11.2 [8.7, 14.0] |
| 5,000 | 56.1 [43.5, 70.1] |

> ที่ 100 ผู้ใช้ ระบบ**คาดว่าจะสร้าง false incident ประมาณ 1.1 รายการต่อวัน**
> **ความสามารถในการรองรับต้องยืนยันจากกระบวนการปฏิบัติงานจริง** — ยังไม่ได้วัดเวลาตรวจ
> ต่อ incident · การ dedup alert · จำนวนเจ้าหน้าที่ · precision หลังตรวจจริง

---

## 5. L3 surfaced แยก campaign family (n = 60 ต่อ family)

| family | L3 surfaced [Wilson CI95] |
|---|---|
| `u_mixed_direction` | 33.3% [22.7, 45.9] |
| `u_scope_only` | 30.0% [19.9, 42.5] |
| `u_subsystem_shuffle` | 18.3% [10.6, 29.9] |
| `u_intermittent` | 8.3% [3.6, 18.1] |
| `u_off_f_axis` | 3.3% [0.9, 11.4] |

---

## 6. ข้อสรุปสำหรับบทที่ 4

> บนชุดข้อมูลสังเคราะห์ Final Holdout (300 campaign จากโปรไฟล์ผู้ใช้พื้นฐาน 12 คน × 5 seed)
> ชั้น L1 และ L2 **surface อย่างน้อยหนึ่งเหตุการณ์ได้ 97.3%** ของ campaign
> [Wilson 94.8–98.6 · hierarchical 93.7–99.7] ขณะที่ L3 surface ได้ **18.7%**
> [hierarchical 6.7–33.3] และมี **campaign ที่ตรวจได้เฉพาะ L3 เพียง 0.3% (1 จาก 300)**
> นอกจากนี้ ใน 55 campaign ที่ surface ร่วมกัน L3 ตรวจพบ **ช้ากว่า L1/L2 เฉลี่ย 1.47 เหตุการณ์**
> (CI −1.89 ถึง −1.04) ดังนั้น **L3 ยังไม่มีหลักฐานเพียงพอสำหรับใช้ตัดสิน MFA หรือ Block**
> แต่ใช้เป็น **Shadow Monitoring** เพื่อให้หลักฐานเสริมและอธิบายการเบี่ยงเบนเชิงลำดับได้

---

## 7. สถานะสถาปัตยกรรมที่ล็อก

| ชั้น | บทบาท |
|---|---|
| L1 Rule | Access decision |
| L2 Behavior | Access decision |
| **L3 Config F (W=5, p99.9)** | **Shadow / corroborating evidence เท่านั้น** |
| L4 Fusion | แยก Access ออกจาก Monitoring |
| Config G / W10 / MULTI | เก็บเป็นผลเปรียบเทียบ — ไม่ใช้จริง |

L3 ไม่บวก risk score · ไม่สั่ง MFA/block · สร้าง `l3_investigate` เท่านั้น · default ปิด

**ขั้นถัดไป:** ทำระบบให้เสถียร → **Production Shadow Replay** → ให้ผู้เชี่ยวชาญประเมิน

---

## 8. บั๊กเชิงวิธีที่พบและแก้ (บันทึกไว้เป็นบทเรียน)

| # | บั๊ก | ผลกระทบ | แก้แล้ว |
|---|---|---|---|
| 1 | IForest anomaly sign กลับด้าน | L3 ยิง 0/240 (ไม่ทำงานเลย) | `-score_samples` + calibrate จาก normal |
| 2 | window คร่อมข้าม attack family | W=10 วัดได้ 4.18% ทั้งที่จริง 0.9% (เฟ้อ 4 เท่า) | แยก window ตาม family + regression test |
| 3 | window construction ไม่ตรงกัน train/val/test | L3 FPR พุ่ง 0.9% → 5.8% (6 เท่า) | สร้าง window แบบเดียวกันทุกชุด |
| 4 | pooling `(user, day)` ข้าม seed | false incident เฟ้อ 4 เท่า (1.1% → 4.2%) | ใส่ seed ในคีย์ |
| 5 | **pooling `campaign instance` ข้าม seed** | **300 instance ยุบเหลือ 60 (25 event/instance)** → alerts/campaign 4.83 เกินค่าที่เป็นไปได้ · L1/L2 surfaced ดูเป็น 100% ทั้งที่จริง 97.3% | ใส่ seed ในคีย์ + **assert alerts ≤ event สูงสุด** |
| 6 | ใช้สูตรประมาณแทนการวัด L1/L2 | ประเมิน campaign surfaced ผิด | วัดจริง |
| 7 | CI ไม่คิด cluster / ใช้ normal-approx | CI แคบเกินจริง | Wilson + cluster + hierarchical bootstrap |

**Regression test:** `tests/test_l3_window_integrity.py` (5 tests) ·
`exp_l3_multiscale.py` deprecated + fail-fast · sanity assert ใน `exp_final_synthetic.py`
