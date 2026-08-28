# Phase 1 — Learning Curve ของ Contract V2+ (ไล่ระดับข้อมูล 10→5000)

**วันที่:** 21 ส.ค. 2026
**คำถาม:** ผู้ใช้ต้องมี login history กี่ครั้ง ระบบถึงจะป้องกันได้ดี
**วิธี:** 6 sizes × 5 seeds = **30 รอบ** · แต่ละรอบ generate→extract→split 80/20→เทรน IForest→score contract_v2_plus
**สคริปต์:** `ml-service/scripts/learning_curve_v2.py` · **กราฟ:** [`learning_curve_v2.svg`](learning_curve_v2.svg)

---

## สรุป 3 บรรทัด

1. **ระบบป้องกันได้ตั้งแต่ history น้อยมาก** — recall **87% ที่แค่ 10 login/คน** (rule เป็นตัวคุม floor ไม่ต้องรอ history)
2. **FPR ต้องการ ~50 login ถึงจะนิ่ง** — ตกจาก 3.3% (size 10) → 1.2% (size 50) แล้วคงที่ ~1.6%
3. **เกิน 50–100 login ไม่มี gain เชิงปฏิบัติ** — recall/FPR/policy อิ่มตัวหมด

---

## 1. ตาราง Learning Curve (mean ± std จาก 5 seeds)

| history/คน | Recall | Challenge FPR | Policy success | PR-AUC | train ทั้งหมด |
|---|---|---|---|---|---|
| **10** | 87.0% ±1.0 | **3.3%** ±1.7 | 90.8% ±1.2 | 0.994 | 96 |
| **50** | 88.9% ±0.3 | **1.2%** ±0.4 | 94.8% ±0.8 | 0.986 | 480 |
| **100** | 88.6% ±0.7 | 1.8% ±0.9 | 94.9% ±1.1 | 0.976 | 960 |
| **500** | 88.8% ±0.9 | 1.7% ±0.3 | 94.1% ±1.5 | 0.924 | 4,800 |
| **1000** | 89.4% ±0.2 | 1.6% ±0.3 | 94.6% ±0.7 | 0.813 | 9,600 |
| **5000** | 88.9% ±0.6 | 1.6% ±0.1 | 94.4% ±0.8 | 0.598 | 48,000 |

Attack test คงที่ **240 แถว** ทุก size (ไม่ขึ้นกับ history) — เป็น test set ที่เทียบกันได้

---

## 2. อ่านกราฟ

- **Recall (ฟ้า) แบนเกือบตรง ~87–89%** ทุก size — เพราะ **rule ให้คะแนน attack โดยไม่พึ่ง history**
  → ผู้ใช้ใหม่ที่เพิ่งล็อกอิน 10 ครั้งก็ได้รับการป้องกัน 87% ทันที
- **Challenge FPR (แดง) ตกชันจาก size 10→50** แล้วนิ่ง — behavior baseline ต้องการ ~50 login
  ถึงจะเลิก "ระแวงเกิน" (personalized temporal features cold start ที่ history < 5)
- **Policy success (เขียว) กระโดด 90.8%→95% ที่ size 50** แล้วคงที่
- **PR-AUC (ม่วง) ลาดลง 0.99→0.60** — ⚠️ **เป็น artifact ของการวัด ไม่ใช่โมเดลแย่ลง** (ดูข้อ 3)

---

## 3. ⚠️ PR-AUC ที่ตก — เป็น artifact ของ class imbalance ไม่ใช่ degradation

attack คงที่ 240 แต่ **normal test โตตาม size** → attack prevalence ยิ่งเล็ก → PR-AUC (ผูกกับ base rate) ยิ่งต่ำ **โดยที่ความสามารถแยกแยะจริง _เพิ่มขึ้น_**

| size | normal test | attack prevalence | PR-AUC | **lift เหนือ random** |
|---|---|---|---|---|
| 10 | 24 | 90.9% | 0.994 | **1.09x** |
| 50 | 120 | 66.7% | 0.986 | 1.48x |
| 100 | 240 | 50.0% | 0.976 | 1.95x |
| 500 | 1,200 | 16.7% | 0.924 | 5.55x |
| 1000 | 2,400 | 9.1% | 0.813 | 8.94x |
| 5000 | 12,000 | 2.0% | 0.598 | **30.49x** |

**lift เหนือ random เพิ่มจาก 1.09x → 30.49x** → โมเดลแยก attack ออกจาก normal ได้**ดีขึ้นมาก**ตาม history
raw PR-AUC แค่ตามฐาน prevalence ที่หดลง (ตรงกับที่รายงาน V2 เตือนเรื่อง F1 ตกเพราะ attack test คงที่)

> **บทเรียนเชิงวิธีการ:** เมื่อ test set ไม่สมดุลและ base rate เปลี่ยนตาม size ต้องดู
> **operational metric (recall/FPR/policy ที่ threshold คงที่)** + **lift เหนือ random**
> อย่าอ่าน raw PR-AUC ข้าม size ตรงๆ

---

## 4. คำตอบเชิงปฏิบัติ (สำหรับ production rollout)

| คำถาม | คำตอบจากข้อมูล |
|---|---|
| ผู้ใช้ใหม่ (cold start) โดนป้องกันไหม | ✅ recall 87% ตั้งแต่ 10 login · rule เป็น floor ไม่ต้องรอ |
| จุดที่ FPR นิ่ง (ผู้ใช้เลิกโดน false positive) | **~50 login** (FPR 3.3%→1.2%) |
| history เท่าไหร่ถึง "พอ" | **50–100 login/คน** — เกินนั้นไม่มี gain |
| ต้องเก็บ history ยาวไหม | ❌ ไม่ — 5000 ไม่ดีกว่า 100 เลย (เปลืองที่ + ไม่คุ้ม) |

**นัยต่อ production:** ไม่ต้องรอให้ผู้ใช้สะสม history นานก่อนเปิดป้องกัน — เปิดได้เลย
rule คุม recall ตั้งแต่วันแรก · behavior แค่ช่วยลด FPR ในเดือนแรก (~50 login ≈ 3–4 สัปดาห์ที่ 2/วัน)

---

## 5. เทียบกับ V3–V7

| | จุดอิ่มตัว | หมายเหตุ |
|---|---|---|
| V3–V7 (รายงานเดิม) | 500–1,000 แถว/คน | วัดบน synthetic profiles |
| **Contract V2+ (นี่)** | **~50–100 แถว/คน** | วัดบน **12 โปรไฟล์ anchor ผู้ใช้จริง** |

Contract V2+ อิ่มตัวเร็วกว่าเพราะ **rule เป็น floor** — ไม่ต้องรอ ML/behavior เรียนรู้
(V3–V7 พึ่งการเรียนรู้มากกว่า จึงต้องการข้อมูลมากกว่า)

---

## 6. ข้อจำกัด

1. **attack test คงที่ 240** — เหมาะวัด recall/FPR แต่ทำ PR-AUC ข้าม size อ่านตรงๆ ไม่ได้ (ข้อ 3)
2. **size ใหญ่ = density ไม่จริง** — 5000 login ยืดเป็น ~7 ปี (คง ~2/วัน) เพื่อไม่ให้ `login_count_24h` พุ่ง
   → learning curve วัด "ผลของ history volume" ไม่ใช่ "ผลของเวลาที่ผ่านไป"
3. **ยังเป็นข้อมูลจำลอง** — attack เนียนแต่สร้างเอง · ตัวเลขจริงต้องรอ shadow mode บน log จริง
4. **rule ครอง recall** — ถ้า attacker หลบ rule ได้ recall นี้จะตก (rule เก่งกับ known pattern)

---

## 7. รันซ้ำ

```bash
py ml-service/scripts/learning_curve_v2.py                          # 6 sizes × 5 seeds
py ml-service/scripts/learning_curve_v2.py --sizes 10 100 --seeds 42   # เร็ว
```

**ประสิทธิภาพ:** feature extraction เขียนใหม่แบบ incremental (O(n log n)) —
size 5000 (120k แถว) จาก 10+ นาที เหลือ **20 วินาที**

ผล: `ml-service/data/learning_curve_v2.json`
