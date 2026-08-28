# L3 window sweep (W=5 / W=10 / multi-scale) + บั๊กเชิงวิธีที่พบระหว่างทาง

**วันที่:** 26 ส.ค. 2026 · seeds 42–46 (mean ± CI95) · size 5000 · final holdout

---

## ⚠️ แก้ผลที่รายงานไปก่อนหน้า

รอบแรกผมรายงานว่า **W=10 ให้ unique 4.18%** (ผ่านเกณฑ์ 3–5pp)
**ตัวเลขนั้นใช้ไม่ได้** — harness `exp_l3_multiscale.py` สร้าง window โดยเอา final attack
ทั้ง 53 เหตุการณ์ของผู้ใช้ (obvious + subtle + campaign) มาต่อกันเป็นลิสต์เดียว
→ window ยาว 10 จึง **คร่อมข้าม attack family** เช่น `new_device` + `off_hours` + `campaign`
อยู่ใน window เดียวกัน ซึ่งผิดปกติมากโดยธรรมชาติ → ตรวจจับได้ง่ายเกินจริง

**ในความเป็นจริง attack ไม่ได้มาเป็นชุดคละแบบนั้น** → ตัวเลขเฟ้อ

---

## วิธีที่ถูกต้อง (ใช้ใน `exp_lc_v3.py` หลังแก้)

| ประเด็น | ก่อน | หลัง |
|---|---|---|
| window ของ validation | เฉพาะ window เต็ม | **รวม padded window** (ให้ตรงกับตอน score จริง) |
| window ข้าม episode | ข้ามได้ (val/test) | **ห้ามข้าม** ทุกชุด |
| window ของ attack | คละทุก family | **แยกตาม family** + ใช้ history จริงท้าย train นำหน้า |

**บั๊กที่พบจากการแก้:** ถ้า validation มีแต่ window เต็ม แต่ test มี padded window
→ padded กลายเป็น "ของแปลก" → **L3 FPR พุ่งเป็น 5.8%** (เห็นจริงตอนทดลอง)

---

## ผลเทียบ W=5 vs W=10 (วิธีที่ถูกต้อง, final holdout)

| W | L3 event-unique | L3 FPR | campaign detection | false incident/user-day |
|---|---|---|---|---|
| **5** | **1.33 ± 0.46%** | **0.56 ± 0.04%** | **18.67 ± 5.51%** | **1.12 ± 0.10%** |
| 10 | 0.90 ± 0.45% | 0.90 ± 0.19% | 16.33 ± 2.61% | 1.56 ± 0.34% |
| 5+10 | 0.62 ± 0.44% | 0.57 ± 0.18% | 10.33 ± 3.17% | 1.14 ± 0.33% |

**paired-seed delta เทียบ W5:** W10 event-unique −0.43 ± 0.79 (CI คร่อม 0) ·
MULTI −0.71 ± 0.35 (ต่างอย่างมีนัย)

**W=10 ไม่ได้ดีกว่า** — unique ต่ำกว่าเล็กน้อยและ FPR สูงกว่า
ผลเดิมที่ว่า "W=10 เกือบ 2 เท่า" เป็นผลของบั๊ก cross-family ล้วนๆ

### multi-scale (W=5 + W=10, 36 มิติ) — รันใหม่ด้วย harness ที่แก้แล้ว

~~ผลเดิม 2.54% มาจาก harness ที่มีบั๊ก จึงใช้อ้างอิงไม่ได้~~
**ผลใหม่ (`exp_campaign_level.py`, 5 seeds):** MULTI event-unique **0.62 ± 0.44%**
paired-seed delta เทียบ W5 = **−0.71 ± 0.35 pp (ต่างอย่างมีนัย = แย่กว่าจริง)**
→ ยืนยันว่า multi-scale ไม่ช่วย โดยใช้ผลจาก harness ที่ถูกต้อง

---

## ข้อสรุป

> **ไม่มี window ขนาดไหนที่ดัน L3 unique ถึงเกณฑ์ 3–5pp ที่ FPR ≤1% บนชุดนี้**
> W=5 ให้ **1.3% ที่ FPR 0.6%** — คือจุดที่ดีที่สุดเท่าที่วัดได้

### ⚠️ สถานะเชิงวิธีของการเลือก W

**W=5 เป็น config ที่เลือกจาก development set ก่อนเปิด final holdout** — คงไว้ตามเดิม
ผล W=10 / multi-scale บน holdout เป็น **exploratory analysis** เพื่อปิดข้อสงสัยเท่านั้น
**ไม่ถูกนำมาใช้เลือกโมเดล** (ถ้าใช้ ชุดนี้จะไม่ใช่ final holdout อีกต่อไป)

### บทเรียนเชิงวิธี (สำคัญกว่าตัวเลข)

1. **window ต้องสร้างแบบเดียวกันทุกชุด (train/validation/test)** ไม่งั้น threshold เพี้ยน
   → FPR พุ่ง 6 เท่า (0.9% → 5.8%)
2. **window ห้ามคร่อม attack family** — ถ้าคละ จะได้ recall เฟ้อโดยไม่รู้ตัว
3. **ผลที่ดีขึ้นผิดปกติต้องสงสัยก่อนเสมอ** — 4.18% ดูดีเกินไปเมื่อเทียบกับ 2.14% ของ W=5
   และเมื่อตรวจก็พบว่าเป็น artifact

---

## สถานะ L3 หลังการทดลองทั้งหมด

| เกณฑ์ | ผล |
|---|---|
| L3 FPR ≤1% | ✅ 0.6% |
| Challenge FPR ไม่เพิ่ม | ✅ 1.6% |
| L3 unique ≥3–5pp | ❌ **1.3%** |
| ไม่ overfit (unseen campaign) | dev 1.7% · final 1.33 ± 0.46% — ต้องดู CI ก่อนสรุปว่าไม่ต่างกัน |

**⇒ L3 ยังไม่ผ่านเกณฑ์คุ้มค่าบนชุดจำลอง — คงสถานะ shadow monitoring**
สิ่งที่ยังทำได้: production replay (ข้อมูลจริงอาจมี campaign ที่ต่างจากที่เราจำลอง)

**ไฟล์:** `ml-service/scripts/exp_l3_multiscale.py` (มีบั๊ก cross-family — เก็บไว้เป็นบทเรียน) ·
`exp_lc_v3.py` (แก้แล้ว ใช้เป็นตัวหลัก)


---

## เพิ่มเติม: campaign-level metrics

ดู [`exp_campaign_level_2026-08-26.md`](exp_campaign_level_2026-08-26.md) —
campaign detection **18.67 ± 5.51%** แต่ campaign L3-unique เพียง **0.33 ± 0.65%** (CI คร่อม 0)
→ campaign ที่ L3 จับได้เกือบทั้งหมดเป็นชุดที่ L1/L2 จับได้อยู่แล้ว

## Regression test

`tests/test_l3_window_integrity.py` (5 tests) ล็อกกฎไว้:
window ห้ามคร่อม episode/family · จำนวน window = จำนวน event · group สั้นต้อง pad ไม่ยืม ·
`WINDOW` ต้องเป็นค่าที่ผ่านการทดลอง

`exp_l3_multiscale.py` ถูกทำเป็น **deprecated + fail-fast** (ต้องส่ง `--i-know-this-is-buggy`)
