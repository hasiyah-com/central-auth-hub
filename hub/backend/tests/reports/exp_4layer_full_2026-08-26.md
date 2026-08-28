# การทดลองรวม 4 ชั้น — L1 Rule + L2 Behavior + L3 IsolationForest(+SHAP) + L4 Fusion

**วันที่:** 26 ส.ค. 2026  
**seeds:** [42, 43, 44, 45, 46] (mean ± 95% CI) · size 5000 events/user · ชุดทดสอบเดียวกันทุก seed
**ชุด attack:** obvious (11) + subtle (5) + campaign (low-and-slow multi-phase)


## 1. ผลแยกชั้น

- **standalone** = ชั้นนั้นจับได้เท่าไรถ้าทำงานลำพัง (warn+)
- **unique** = attack ที่เฉพาะชั้นนั้นจับได้ (ชั้นอื่นพลาดหมด)
- **overlap** = จับได้แต่ชั้นอื่นก็จับได้ด้วย

| ชั้น | standalone | unique | overlap | FPR |
|---|---|---|---|---|
| L1 Rule | 43.6±0.5 | 36.4±1.5 | 7.3±1.2 | 1.5±0.2 |
| L2 Behavior | 33.5±3.3 | 21.1±2.7 | 12.4±2.0 | 1.3±0.1 |
| L3 IForest-23 ฟีเจอร์ | 13.3±1.4 | 0.0±0.1 | 13.2±1.4 | 1.3±0.3 |
| L3 IForest-sequence | 16.4±3.3 | 5.1±1.3 | 11.3±3.1 | 0.8±0.3 |

## 2. ผลรวมหลัง L4 fusion

| ตัวชี้วัด | ค่า |
|---|---|
| Recall (challenge+) | 58.6% ± 2.0 |
| Surfaced (warn+) | 76.4% |
| Precision | 64.4% |
| Challenge FPR | 1.6% |
| Warn FPR | 3.6% |
| ขนาดชุดทดสอบ | attack 413 · normal 8400 |

## 3. SHAP บน L3 (IsolationForest 23 ฟีเจอร์)

**ตัวอย่าง:** 112 เหตุการณ์ที่ L3 ยิง (attack 49)  
**Parity check:** PermutationExplainer diff = `1.11e-15` (TreeExplainer ใช้จัดอันดับได้ rank-corr=1.00 แต่ไม่ additive กับ `-score_samples`)

### DuplicateRatio — SHAP มาจากฟีเจอร์ของชั้นไหน

| กลุ่ม | L1/L2-owned | L3-only | geo (ตายเพราะ NAT) |
|---|---|---|---|
| ทั้งหมด | **75.7%** | 24.3% | 0.0% |
| attack | **79.1%** | 20.9% | 0.0% |
| normal | **73.0%** | 27.0% | 0.0% |

> เกณฑ์ตามแผน: DuplicateRatio > 70% = L3 ส่วนใหญ่ตรวจซ้ำกับ L1/L2


### Top features ที่ขับเคลื่อน anomaly score

| # | feature | mean \|SHAP\| |
|---|---|---|
| 1 | `active_subsystem_count` | 1.5915 |
| 2 | `concurrent_session_count` | 1.1943 |
| 3 | `scope_sensitivity_score` | 0.7964 |
| 4 | `login_count_24h` | 0.4916 |
| 5 | `log_minutes_since_last_login` | 0.4566 |
| 6 | `passkey_age_days` | 0.3991 |
| 7 | `hour_of_day` | 0.2503 |
| 8 | `hours_from_typical_login_time` | 0.2478 |

---

## 4. อ่านผล

### 4.1 ลำดับความสำคัญของชั้น (จาก unique detection)

| อันดับ | ชั้น | unique | อ่านว่า |
|---|---|---|---|
| 1 | **L1 Rule** | **36.4%** | เสาหลัก — เหตุการณ์ deterministic ที่ชั้นอื่นแทนไม่ได้ |
| 2 | **L2 Behavior** | **21.1%** | สำคัญรองลงมา — anomaly "รายคน" ที่ rule เขียนกฎไม่ได้ |
| 3 | L3 IForest-sequence | 5.1% | มีค่าเฉพาะทาง (campaign/joint-drift) |
| 4 | **L3 IForest-23 ฟีเจอร์** | **0.0%** | **ซ้ำซ้อนทั้งหมด — ไม่มีอะไรที่ชั้นอื่นจับไม่ได้เลย** |

**L1 + L2 = 57.5% ของ attack ที่จับได้แบบ unique** — ยืนยันว่าสองชั้นนี้คือระบบตรวจจับจริง

### 4.2 SHAP ยืนยัน "L3-23 ฟีเจอร์ ซ้ำซ้อน" ด้วยหลักฐานอิสระ

สองวิธีที่ไม่เกี่ยวกันให้คำตอบตรงกัน:

| วิธีวัด | ผล |
|---|---|
| **unique detection** (จาก decision) | L3-all23 unique = **0.0 ± 0.1%** |
| **SHAP DuplicateRatio** (จาก attribution) | **79.1%** ของ \|SHAP\| บน attack มาจากฟีเจอร์ที่ L1/L2 เป็นเจ้าของ |

เกณฑ์ในแผนคือ >70% = "ตรวจซ้ำเป็นส่วนใหญ่" → **79.1% เกินเกณฑ์ชัดเจน**

**Top features ที่ขับเคลื่อน anomaly score ของ L3-all23:**
`active_subsystem_count` (1.591) และ `concurrent_session_count` (1.194) — **ทั้งคู่เป็นฟีเจอร์ที่ L1
มีกฎตรงๆ อยู่แล้ว** → L3 กำลัง "ค้นพบ" สิ่งที่ rule ประกาศไว้ชัดเจนแล้ว

`scope_sensitivity_score` (0.796) และ `passkey_age_days` (0.399) เป็น L3-only ที่ติด top —
สอดคล้องกับการออกแบบ L3-sequence ที่เลือกใช้เฉพาะฟีเจอร์กลุ่มนี้

### 4.3 geo = 0.0% ยืนยันผลของ campus NAT

ฟีเจอร์ geo ทั้ง 4 ตัวมี **\|SHAP\| รวมเป็น 0.0%** — ไม่มีส่วนร่วมในการตัดสินเลย
เป็นหลักฐานเชิงปริมาณว่าระบบทำงานบน **18 ฟีเจอร์** ไม่ใช่ 23 ตามที่ระบุในข้อจำกัด

### 4.4 Methodology — SHAP กับ IsolationForest

| explainer | parity กับ `-score_samples` | ความเร็ว | ใช้ทำอะไร |
|---|---|---|---|
| `TreeExplainer` | ❌ ไม่ additive (อธิบาย path length ดิบ) · **rank-corr = 1.00** | เร็ว | จัดอันดับ attribution (bulk) |
| `PermutationExplainer` | ✅ **diff = 1.1e-15** | ช้า (~1.3s/event) | ตรวจ parity บน sample |

→ ใช้ Tree สำหรับปริมาณมาก + Permutation ยืนยันความถูกต้อง (ตามแผน §6)

---

## 5. ข้อสรุป

> **L1 + L2 คือระบบตรวจจับ (unique 36.4% + 21.1%) · L3 แบบ 23 ฟีเจอร์ ซ้ำซ้อน 100%
> (unique 0.0%, SHAP duplicate 79.1%) · L3 มีค่าเฉพาะเมื่อใช้ residual/sequence (unique 5.1%)**

**คำแนะนำ:** ถ้าจะใช้ L3 ให้ใช้แบบ **sequence/residual** เท่านั้น และให้ทำหน้าที่ surfacing channel
(warn) — ไม่ใช่ IForest บนฟีเจอร์ทั้ง 23 ตัวซึ่งพิสูจน์แล้วว่าไม่เพิ่มอะไรเลย

**ข้อจำกัด:** ข้อมูลจำลอง (anchor คนจริง) · SHAP วิเคราะห์บนโมเดลของผู้ใช้ 1 คน (112 เหตุการณ์ที่ยิง)
· ยังไม่ผ่าน production replay
