# Accuracy Gate — Hybrid RBA 4 Layers — pre-registration (2026-09-23)

ส่วนนี้ commit **ก่อน**สร้างผลใหม่ใด ๆ · ผลจะเพิ่มในส่วนท้ายโดยไม่แก้ส่วนนี้ · ตัวเลขและตรรกะทั้งหมดอยู่ใน
`ml-service/scripts/hybrid_experiment/accuracy_gate.py` และถูกล็อกด้วย `hub/backend/tests/test_accuracy_gate.py`

## 1. สถานะตั้งต้น

- ฐาน: branch `feature/hybrid-accuracy-validation` แตกจาก `44869d2` (worktree สะอาด · `git diff --check` ผ่าน)
- ผลเดิมที่คงไว้: P1 v2 ไม่ผ่าน · P1 v3 (§26) ไม่ผ่าน · A/B §27–28 ไม่พบว่าตัวจำกัดทำให้ช้าลง · **Capacity Gate
  ยังไม่ผ่าน** · P48-T2 = `inconclusive` (frozen) · holdout ของ P48-T2 (16 โปรไฟล์) และ seed 101–115 **ไม่แตะ**

## 2. ตัวชี้วัดและเกณฑ์

ไม่ใช้ accuracy รวม — เหตุการณ์ปกติมากกว่าการโจมตีหลายเท่า · ทุกเกณฑ์ตัดสินจาก **cluster CI (ผู้ใช้ → seed)**

| ตัวชี้วัด | เกณฑ์ | วิธี |
|---|---|---|
| Challenge FPR | ขอบบน CI ≤ **1%** ทุกขนาดประวัติ | `gate.config_gate` (เดิม) |
| Block FPR | ขอบบน CI ≤ **0.20%** ทุกขนาดประวัติ | เดิม |
| Severe recall@challenge | ขอบล่าง CI ≥ **90%** | `hierarchical_proportion` · ตระกูลที่มี policy floor 7 ตระกูล¹ |
| Campaign recall | ขอบล่าง CI ≥ **80%** | หน่วยนับ = แคมเปญ · จับได้ถ้ามีเหตุการณ์ใดถึง **challenge** |
| Recall@challenge ตระกูลที่อ่อน | ขอบล่าง CI ≥ เป้าในตาราง 2.1 | ต่อตระกูล |
| ไม่ถดถอย | ตระกูลที่ baseline จับได้ 100% ต้องได้ 100% | ค่าจุด |
| Precision (challenge / block) | รายงาน | — |
| Abstain rate ของ L3 | รายงานแยกตามขนาดประวัติ | — |
| Expert agreement | กำหนดก่อนเปิด Pilot (ยังไม่มีผู้ตรวจ) | — |
| ความเสถียรของ calibration | รายงานอัตรา L3 ยิงบนเหตุการณ์ปกติของ validation | — |

¹ `combined_ato, concurrent_sessions, failed_spike, new_device, new_os, new_ua_family, permission_change`

### 2.1 เป้าของตระกูลที่อ่อน (recall@challenge)

| ตระกูล | P48 / P48-T2 | เป้า (ขอบล่าง CI) |
|---|---|---|
| `new_passkey` | 24% / 18% | ≥ 60% |
| `subtle_rare_device` | 26% / 14% | ≥ 60% |
| `subtle_slow_burst` | 27% / 25% | ≥ 60% |
| `campaign` | 37% / 42% | ≥ 80% |
| `login_velocity` | 42% / 38% | ≥ 70% |
| `subtle_quiet_lateral` | 64% / 68% | ≥ 75% |

### 2.2 กฎตัดสิน

- `passed` = ทุกข้อผ่าน · `failed` = มีข้อใดไม่ผ่าน (ชนะ inconclusive) · `inconclusive` = CI คร่อมเกณฑ์ →
  **ยังไม่พร้อม deploy**
- ห้ามเปลี่ยนเกณฑ์หลังเห็นผล · ห้ามเพิ่มรอบหลังเห็นผลโดยไม่มีแผนที่ commit ล่วงหน้า
- ข้อสังเกตที่ประกาศไว้ก่อน: ประชากรมี 32 โปรไฟล์ validation → CI ต่อตระกูลจะกว้าง · ผล `inconclusive` เป็นไปได้สูง
  และจะรายงานตามนั้น

## 3. การแบ่งข้อมูลและการเทียบที่ FPR เท่ากัน

| ชุด | ข้อมูล | หน้าที่ |
|---|---|---|
| Train / Calibration (ECDF) | split ภายในผู้ใช้ของแต่ละ cell (`DS.build`) | fit โมเดล + ECDF (เดิม) |
| **Calibration ของรอบนี้** | P48-T2 validation profiles × seed **[401–405]** (เห็นแล้ว) | ตั้ง threshold ให้ FPR เท่ากัน + เลือกพารามิเตอร์ G |
| **Validation** | P48-T2 validation profiles × seed **[501–505]** (ใหม่) | ตัดสิน gate ครั้งเดียว |
| Final holdout | holdout 16 โปรไฟล์ของ P48-T2 | **ไม่เปิดในรอบนี้** |

- ทุก candidate ตั้ง threshold บน calibration ให้ **challenge FPR ≤ 0.5% และ block FPR ≤ 0.1% ทุกขนาด**
  (`pick_threshold` บน grid 0.400–0.995 ทีละ 0.005 · ต่ำกว่างบเพื่อเผื่อ tail shift ข้ามประชากรที่เคยวัดได้
  0.73% → 1.18%) · ถ้าไปไม่ถึง (FPR จาก policy floor) ต้องรายงาน `reachable=false`
- แล้วใช้ threshold เดียวกันนั้นบน validation — ไม่ปรับอีก

## 4. Candidate

| key | ความหมาย |
|---|---|
| B | baseline L1+L2 (max + corroboration) |
| E | hybrid ปัจจุบัน — L3 point + sequence ใช้ max ร่วมกับ L1/L2 |
| **G** | **conditional L3 fusion** (ระยะที่ 5) — gate ตัดสิน G เท่านั้น |

### 4.1 G — grid และกฎการเลือก (บน calibration เท่านั้น)

`ambiguous_low ∈ {0.30, 0.40, 0.50}` × `w_point ∈ {0.5, 1.0}` × `w_sequence ∈ {0.5, 1.0}` ×
`low_zone_agree ∈ {0.90, 0.95}` = 24 ชุด · แต่ละชุดตั้ง threshold ของตัวเองตามข้อ 3 แล้วเลือกด้วย `select_g`:

1. recall@challenge เฉลี่ยของ 6 ตระกูลในข้อ 2.1 สูงสุด
2. severe recall สูงสุด
3. challenge FPR ต่ำสุด
4. น้ำหนักรวมน้อยสุด

ชุดที่ไปไม่ถึง FPR เป้าถูกตัดทิ้งก่อน · เลือกแล้ว freeze ก่อนแตะ validation

### 4.2 การออกแบบของ G ที่ตรึงไว้ตอน implement (ก่อนวัดใด ๆ · commit ระยะที่ 5)

- ขอบบนของช่วงกำกวม `AMBIGUOUS_HIGH` = **0.70 คงที่** (ค่า challenge เริ่มต้นของ production) ไม่ผูกกับ threshold
  ที่กวาด → คะแนนของ G ไม่ขึ้นกับ threshold จึงกวาดหา FPR เท่ากันผ่าน `resolve_action` ตัวเดียวกับ B/E ได้
- "ยกได้สูงสุด warn" ในช่วงเสี่ยงต่ำ ส่งผ่าน `ResolverInput.action_cap` (ใหม่ · ค่าเริ่มต้น None ไม่เปลี่ยน B/E) ·
  policy floor ชนะเพดานเสมอ · L3 ห้าม block คนเดียวทุกช่วง (`SOLO_BLOCK_FORBIDDEN` เดิม)
- ช่วง high ใช้ L3 เป็นหลักฐานสนับสนุนด้วย gamma เดียวกับ fusion เดิม
- production: `L3_CONDITIONAL_PARAMS` (JSON) ว่าง = ไม่คำนวณ · ตั้งแล้วบันทึก `conditional_shadow` ใน
  `risk_breakdown` เป็นผลจำลองชุดที่สาม เฉพาะโหมด `shadow_hybrid`/`hybrid_stepup` · key ผิด/ค่าผิดช่วง = ไม่ start

## 5. ห้ามทำ

- ปรับ threshold หรือพารามิเตอร์หลังเห็น validation แล้ววัดชุดเดิมซ้ำ
- เลือก candidate ที่ผ่านแบบ post-hoc (gate ตัดสิน G ตัวเดียว)
- ใช้ accuracy รวมกลบผลของตระกูล
- เปิด holdout เมื่อ validation ไม่ผ่าน · เปิด L3 enforcement

## 5.1 Amendment 1 — แก้ก่อนวัด (2026-09-23)

พบตอนเตรียมสคริปต์วัด **ก่อนมีผล validation ใด ๆ** · ข้อมูลที่ดูมีเพียง probe บน **calibration** seed 401 size 50
(เวลา + การกระจายคะแนนของ E บนเหตุการณ์ปกติ) ไม่ได้ดู recall ของ candidate ใด

| ข้อ | เดิม | แก้เป็น | เหตุผล |
|---|---|---|---|
| threshold grid | 0.400–0.995 ทีละ 0.005 | เดิม + 0.9951–0.9999 (0.0001) + 0.99991–0.99999 (0.00001) + 0.999991–0.999999 (0.000001) | frozen config ของ B/E ใช้ gamma 1.0 และ threshold 0.995 / 0.9999 · คะแนนปกติของ E ที่ q99.5 = 0.99977 → grid เดิมไปไม่ถึง FPR 0.5% ทุก candidate โดยโครงสร้าง |
| gamma | ไม่ได้ระบุ | `per_config_gamma` ของ Round 2c (B = 1.0, E = 1.0) · G ใช้ของ E | ให้ G ต่างจาก E เฉพาะวิธีรวม L3 |
| warn threshold | ไม่ได้ระบุ | `min(warn เดิมของ config, challenge ที่ตั้งใหม่)` · G ใช้ warn ของ E | warn ไม่ใช่เกณฑ์ตัดสิน |
| Campaign recall | "หน่วยนับ = แคมเปญ" | กลุ่มการโจมตี (ผู้ใช้ × scenario × seed × size) จับได้ถ้ามีเหตุการณ์ใดถึง challenge · ต่างจากตระกูล `campaign` ในข้อ 2.1 (ระดับเหตุการณ์) | คำว่า "แคมเปญ" ใช้ซ้ำสองความหมาย |

ข้อสังเกตที่ประกาศไว้ก่อนวัด: `AMBIGUOUS_HIGH = 0.70` ของ G อยู่บนสเกลเดียวกับคะแนน L1/L2 ที่ calibrate แล้ว
(ค่ากลางของ E บนเหตุการณ์ปกติ ≈ 0.69) → ราวครึ่งหนึ่งของเหตุการณ์ปกติอยู่ช่วง high · ไม่แก้ (ออกแบบและ commit แล้ว)
และจะรายงานสัดส่วนเหตุการณ์ต่อช่วงในผล

## 6. ผล

(เพิ่มหลังวัด)
