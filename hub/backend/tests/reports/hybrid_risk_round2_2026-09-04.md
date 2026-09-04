# Hybrid Risk — Round 2 Final (2026-09-04)

> ## สถานะ: `final_round_2_failed_gate`
>
> **Config B (candidate ที่ประกาศล่วงหน้า) แก้ block สำเร็จ (0.25% -> 0.04%) แต่
> ไม่ผ่าน Final Gate เพราะ warn FPR = 5.26% > 5.0%** บน holdout ชุดใหม่ `[101-105]`
> -> ยังไม่มี config ใหม่พร้อม deploy · fallback = shadow / current deployment

| | |
|---|---|
| รอบ | **Final Round 2 — ไม่ผ่าน gate (warn)** |
| commit ที่ freeze | `fc9353fbad3b` · scoring fingerprint 21/21 ตรงกับ working tree |
| candidate ที่ประกาศ | Config B · γ=1.0 · warn=0.941667 · challenge=0.989833 · **block=0.9999** |
| fallback ที่ประกาศ | shadow / current deployment (ไม่ deploy อะไรใหม่) |
| holdout | `[101, 102, 103, 104, 105]` · 316,150 เหตุการณ์ · leakage 0 |
| shortcut audit (holdout) | 0/23 เข้าเกณฑ์ |
| ⚠️ provenance | **ดู §5 — holdout อาจถูกเปิดหลายครั้งระหว่าง optimize (single-open ไม่การันตี)** |

---

## 1. ผล Final Gate บน holdout [101-105]

| cfg | recall | rec@ch | warn FPR | ch FPR | blk FPR | gate |
|---|---|---|---|---|---|---|
| A legacy | 0.9022 | 0.7542 | 2.46% | **2.39% ✗** | 0.09% | ไม่ผ่าน |
| **B** (candidate) | **0.9178** | 0.7026 | **5.26% ✗** | 0.77% ✓ | **0.04% ✓** | **ไม่ผ่าน (warn)** |
| C +point | 0.8878 | 0.6801 | 4.78% | **1.15% ✗** | 0.13% | ไม่ผ่าน |
| D +sequence | 0.8028 | 0.6785 | 3.16% | **1.68% ✗** | 0.18% | ไม่ผ่าน |
| E +ทั้งสอง | 0.8311 | 0.6273 | 4.03% | **1.43% ✗** | 0.15% | ไม่ผ่าน |
| F weighted sum | 0.7763 | 0.4812 | 2.85% | 0.75% ✓ | 0.19% ✓ | **ผ่านครบ** — แต่ไม่ใช่ candidate |

งบ (ไม่เปลี่ยนจาก Round 1): warn ≤ 5.0% · challenge ≤ 1.0% · block ≤ 0.2%

**Config F ผ่านอีกครั้ง แต่ยังเลือกไม่ได้** — ไม่ได้ประกาศเป็น candidate/fallback
ก่อนเปิด holdout (post-hoc เหมือน Round 1) · เก็บเป็น comparator เท่านั้น

---

## 2. การแก้ block สำเร็จ — แต่เปิดข้อจำกัดใหม่ที่ warn

เทียบ Config B สองรอบ (คนละ holdout):

| | recall | warn FPR | ch FPR | **blk FPR** |
|---|---|---|---|---|
| Round 1 holdout [42-46] | 0.9068 | 4.03% ✓ | 0.93% ✓ | **0.25% ✗** |
| Round 2 holdout [101-105] | 0.9178 | **5.26% ✗** | 0.77% ✓ | **0.04% ✓** |

- **block: 0.25% -> 0.04%** — การยก block threshold 0.998112 -> 0.9999 ได้ผลตามที่พิสูจน์
  บน validation (ต้นทุน recall = 0 · recall กลับ **เพิ่ม**เล็กน้อย 0.9068 -> 0.9178)
- **warn: 4.03% -> 5.26%** — ข้อจำกัดใหม่ที่ไม่เคยเป็นปัญหาใน Round 1 โผล่บน holdout ชุดใหม่

**warn FPR รายขนาด:** 50→3.72% · 100→3.57% · **500→6.92% · 1000→6.81%** · 5000→5.30%
ขนาดกลาง-ใหญ่ (500/1000) ทะลุงบชัด — เป็น distribution shift ที่รุนแรงกว่าที่ขนาดเหล่านั้น

**tail calibration (deployed B, validation reference -> holdout):**
- p95 exceedance: nominal 5% -> **observed 6.76% (1.35×)** ← ตรงกับ warn FPR ที่ทะลุ
  (warn threshold ตั้งราว p95 ของ validation แต่ holdout เกินที่ 6.76%)
- p99 exceedance: nominal 1% -> observed 0.78% (0.78×) ← challenge ยังอยู่ในงบ
- PIT KS statistic 0.77 (p≈0) — distribution ของคะแนน normal บน holdout ต่างจาก
  validation อย่างมีนัย

> **บทเรียนซ้ำของ Round 1 ในระดับ warn:** threshold ที่จูนบน validation ไม่ย้ายมา
> ตรงบน holdout · Round 2 แก้เฉพาะ block (คันโยกฟรี) แต่ warn ไม่ใช่คันโยกฟรี
> (ยก warn threshold ลด warn FPR แต่ก็ลด recall เพราะ warn->allow ทำให้ attack ที่
> surface เฉพาะระดับ warn หลุด) — จึงแก้แบบไม่มีต้นทุนเหมือน block ไม่ได้

### 2.1 วิเคราะห์ (บน validation เท่านั้น) — warn peak ที่ขนาดกลางเป็นเรื่องโครงสร้าง

รูปแบบ warn FPR ต่อขนาดของ Config B **ทำซ้ำได้บน validation** (ไม่ใช่ holdout fluke):

| ขนาด | warn FPR (validation) | warn FPR (holdout [101-105]) |
|---|---|---|
| 50 | 3.09% | 3.72% |
| 100 | 2.74% | 3.57% |
| **500** | **4.41%** | **6.92%** |
| **1000** | **4.61%** | **6.81%** |
| 5000 | 3.94% | 5.30% |

- รูปแบบ **non-monotonic peak ที่ 500/1000** ปรากฏบนทั้งสองชุด → เป็นคุณสมบัติเชิง
  โครงสร้าง ไม่ใช่ความบังเอิญของ holdout · holdout shift แค่ **ขยาย**ให้ทะลุงบ
  (validation 4.4-4.6% ยังใต้ 5% แต่ holdout 6.8-6.9% ทะลุ)
- สัดส่วน normal ที่ **behavior evidence ≥ warn threshold** ก็ peak ที่ 500 (3.31% เทียบ
  50→2.79%, 5000→2.73%) → สอดคล้องสมมติฐาน **warm-up ของ behavior profiling**: ที่
  history ขนาดกลาง โปรไฟล์มีข้อมูลพอจะ flag ว่าผิดปกติ แต่ยังไม่พอจะแม่น → over-flag
  normal ที่ระดับ warn มากกว่าขนาดใหญ่ที่โปรไฟล์นิ่งแล้ว
- **หมายเหตุความซื่อตรง:** behavior evidence อธิบายได้ **บางส่วน** (peak ตื้นกว่า warn FPR)
  การ attribute เต็มรูปแบบ (velocity? feature ใด?) ยังไม่ได้ทำ — นี่เป็น **การวิเคราะห์**
  ไม่ใช่ข้อสรุปสุดท้าย · การแก้จริงต้องออกแบบใหม่และวัดบน validation + holdout ชุดใหม่

> **นัยต่อการแก้:** ยก warn threshold แบบ global จะลด warn FPR ทุกขนาดรวมขนาดที่ไม่ได้
> มีปัญหา → แลก recall โดยไม่จำเป็น · ทางที่ตรงจุดกว่าคือแก้ที่ต้นเหตุ (warm-up ของ
> behavior) หรือ threshold ที่ปรับตาม maturity tier — แต่ทั้งคู่เป็นงานออกแบบใหม่
> (Round 2b) ไม่ใช่การปรับค่าเดียว

---

## 3. Paired hierarchical bootstrap — ยืนยันว่า L3 ไม่ช่วย (เมทodology ใหม่)

ΔRecall(B − config) บน holdout เดียวกัน · paired · สุ่ม user→seed→event ชุดเดียวกัน:

| เทียบ | ΔRecall | 95% CI | sign_agreement | ΔCampaignRecall |
|---|---|---|---|---|
| B − C | **+0.0302** | [+0.0178, +0.0440] | 1.00 | +0.0090 |
| B − D | **+0.1153** | [+0.0912, +0.1420] | 1.00 | +0.0090 |
| B − E | **+0.0873** | [+0.0560, +0.1219] | 1.00 | +0.0082 |

ทุก CI **ไม่คร่อม 0** และ sign_agreement = 1.00 -> **B ชนะทุก config ที่มี L3 อย่างเสถียร**
ข้ามการสุ่มผู้ใช้ · ต่างจาก Round 1 ที่ใช้ unpaired CI (บอกได้แค่ว่าไม่ทับกัน)
ตอนนี้เป็นการทดสอบความต่างโดยตรง

ΔCampaignRecall ≈ 0.008-0.009 (ราว 2 แคมเปญจาก ~245) -> L3 แทบไม่เพิ่มการจับระดับ
แคมเปญ ตรงกับ Round 1 · ข้อสรุป **L3 คงไว้ที่ shadow mode** ยังยืน

---

## 4. สรุปสำหรับ Round 2

1. สถาปัตยกรรม Hybrid + candidate B (block=0.9999) **ยังไม่ผ่าน Final Gate**
   -> ไม่มี config ใหม่พร้อม deploy · ระบบ production ไม่เปลี่ยน · L3 ยัง shadow
2. การแก้ block เป็นคันโยกฟรีได้ผลจริง (0.25% -> 0.04%)
3. ข้อจำกัดใหม่ที่ warn (5.26%) เกิดจาก distribution shift บน holdout ชุดใหม่ ที่ขนาด
   500/1000 · **แก้แบบไม่มีต้นทุน recall ไม่ได้** เหมือน block
4. paired bootstrap ยืนยัน B > C/D/E ด้าน recall อย่างเสถียร (sign 1.0, CI ไม่คร่อม 0)

---

## 5. ⚠️ Provenance — ข้อกังวลเรื่องการเปิด holdout หลายครั้ง

**ต้องเปิดเผยตรงๆ:** commit ระหว่าง freeze arg (`193f6a1`) ถึง freeze สุดท้าย
(`fc9353f`) เป็นชุด perf 3 ตัว ช่วง 00:21–01:44 (~1.5 ชม.) โดยตัวแรกระบุ
**"final ช้าเกิน"** ซึ่งบ่งชี้ว่า **`final` ถูกรันบน holdout `[101-105]` มากกว่า
หนึ่งครั้ง**ระหว่าง optimize ความเร็วของ bootstrap

**สิ่งที่ยังเชื่อถือได้ (ไม่กระทบ):**
- ค่า gate (warn/challenge/block FPR) เป็น **deterministic** ของ threshold ที่ freeze
  ไว้ + scoring path · `git diff 193f6a1..fc9353f -- hub/backend/app/security/` = **ว่าง**
  (decision logic ไม่เปลี่ยนเลยระหว่าง perf) · perf แตะแค่ bootstrap/CI computation
- **ไม่มีการปรับ threshold/decision ตามผล holdout** — candidate B ถูกประกาศและ freeze
  ก่อนรัน final ครั้งแรก · การรันซ้ำเปลี่ยนแค่วิธีคำนวณ CI ไม่ใช่การตัดสิน
- ผลลัพธ์เป็น **fail-closed** (candidate ไม่ผ่าน -> fallback -> ไม่ deploy) จึงเป็น
  ข้อสรุปที่อนุรักษ์นิยม การเปิดซ้ำไม่ทำให้ตัดสินใจ deploy อะไรที่ไม่ควร

**สิ่งที่เสียไป:**
- การรับประกัน "เปิด holdout ครั้งเดียว" **ไม่เป็นจริงอีกต่อไป**สำหรับ `[101-105]`
- `[101-105]` ถือว่า **ใช้แล้ว** -> ห้ามใช้เป็น clean holdout สำหรับการตัดสินเชิงปรับตัว
  ใดๆ อีก · ถ้าต้องทำ Round 2 ใหม่ (แก้ warn) ต้องใช้ holdout seed ชุดใหม่
  (ไม่ใช่ `[201-205]` ซึ่งสงวนให้ Round 3 · ต้องเป็นชุดที่สี่ เช่น `[151-155]`)

**บทเรียน (ควรกันในโค้ด):** `cmd_final` ควรปฏิเสธการรันซ้ำบน holdout เดิมให้เข้มกว่านี้
และการ optimize ความเร็วของ bootstrap ต้องทำ/วัดบน validation หรือข้อมูลสังเคราะห์
ไม่ใช่บน holdout จริง · เดิม flag `--i-know-this-is-a-rerun` มีไว้กันเคสนี้ แต่ระหว่าง
perf work ถูกข้ามไป

---

## 6. ทางเลือกถัดไป (รอการตัดสิน)

| ทางเลือก | เนื้อหา |
|---|---|
| **ยอมรับ `final_round_2_failed_gate`** | บันทึกผลนี้เป็นทางการ · ไม่ deploy · L3 ยัง shadow · ปิด Round 2 |
| **Round 2b — แก้ warn บน validation** | ยก warn threshold (ยอมแลก recall) หรือหาวิธี robust · freeze ใหม่ · เปิด holdout ชุดที่สี่ (ไม่ใช่ 101-105 หรือ 201-205) |
| **ตรวจ warn distribution shift ลึก** | ทำไม 500/1000 warn FPR สูงกว่า 5000 · อาจเป็นปัญหา cold-start ของ behavior profiling ที่ขนาดกลาง |

**ข้อเสนอ:** ยอมรับผล Round 2 เป็น failed gate (ซื่อตรงต่อ pre-registration) และ
ก่อนตัดสินใจ Round 2b ควรวิเคราะห์ก่อนว่า warn shift ที่ขนาด 500/1000 มาจากอะไร
เพราะการยก warn threshold แบบตรงๆ จะแลก recall ทันที

## 7. ทำซ้ำ

```bash
cd hub/backend
# ผลนี้มาจาก frozen commit fc9353f · holdout [101-105] เปิดแล้ว (ดู §5)
# การรัน final ซ้ำจะถูกปฏิเสธเพราะมี final_result.json อยู่แล้ว
PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py parity --seed 42 --size 500
```

artifact: `ml-service/data/hybrid_experiment/final_result.json` (gitignored) ·
Round 1 archive: `ml-service/data/hybrid_experiment/round1_archive/`
