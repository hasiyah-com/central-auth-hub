# Hybrid Risk Architecture — การทดลอง Final Round 1 (2026-09-03)

> ## สถานะ: `final_round_1_failed_gate`
>
> **สถาปัตยกรรม Hybrid ถูกสร้างและทดลองสำเร็จ แต่ไม่มี Config ใดที่ถูกเลือกไว้ล่วงหน้า
> แล้วผ่าน Final Gate ครบทุกข้อ ดังนั้น *ยังไม่มี Config ใหม่พร้อม deploy***
>
> Config B ซึ่งเป็น candidate ที่ประกาศไว้ก่อนเปิด holdout **ไม่ผ่านงบ block FPR**
> (0.25% > 0.20%) · Config F ผ่านงบ FPR ทุกระดับแต่ **ไม่ใช่ candidate ที่ประกาศไว้**
> จึงเลือกย้อนหลังไม่ได้ (post-hoc selection) และ recall ต่ำกว่าอย่างชัดเจน

| | |
|---|---|
| รอบ | **Final Round 1 — ไม่ผ่าน gate** |
| commit ที่ freeze | `bdd05e6d0c22952d3f53579c3f768e87c6b0431c` · `git_dirty = true` (ดู §11) |
| provenance ตรวจแล้ว | scoring files 21/21 ตรง · split cells 25/25 ตรง |
| harness | `ml-service/scripts/exp_hybrid_gate.py` (+ `hybrid_experiment/`) |
| baseline เดิม | `ml-service/scripts/exp_final_gate.py` — อ่านอย่างเดียว ไม่ต่อยอด |
| ข้อมูล | 5 seeds × 5 ขนาด × 12 ผู้ใช้ · tuning 161,650 เหตุการณ์ · **holdout 316,150 เหตุการณ์** |
| holdout เปิดกี่ครั้ง | **1 ครั้ง** หลัง freeze · หลังจากนี้ชุดนี้ **ใช้เป็น final ไม่ได้อีก** |
| leakage | 0 / 316,150 แถว |

---

## 1. ลำดับที่บังคับ และเหตุผลของแต่ละขั้น

```
smoke -> parity -> audit -> prepare -> tune -> freeze -> final
```

| ขั้น | ทำอะไร | ทำไมต้องอยู่ตรงนี้ |
|---|---|---|
| `smoke` | ตรวจเส้นทาง 1 seed × 1 size | จับบั๊กเส้นทางก่อนเสียเวลารันเต็ม — ผลติดป้าย `diagnostic_smoke_only` ห้ามใช้สรุปในเล่ม |
| `parity` | harness == production ทุกจุด | ถ้าไม่ผ่าน ผลอธิบายไม่ได้ว่ามาจากระบบหรือจากความต่างของ harness (B66) |
| `audit` | shortcut **ชุดพัฒนาเท่านั้น** | เห็น AUC ของ holdout ก่อน freeze = เปิดดูข้อมูลแล้ว |
| `prepare` | คำนวณ+cache ผลของชั้นทุก cell | ขั้นแพงที่สุด · cache ทำให้ tune ทำซ้ำได้และ hash ตรวจได้ |
| `tune` | กวาด γ/threshold บน validation-tuning | holdout ยังไม่ถูกอ่านเลย |
| `freeze` | ตรึงค่า + hash โค้ดและ split | `final` ปฏิเสธรันถ้า hash ไม่ตรง |
| `final` | เปิด holdout ครั้งเดียว | รวม shortcut audit ของ holdout ไว้ตรงนี้ |

`final` **ปฏิเสธการรัน** ถ้า: ยังไม่ freeze · parity ไม่ผ่าน · โค้ดที่ให้คะแนนเปลี่ยนหลัง
freeze · split เปลี่ยนหลัง freeze · มีผล final อยู่แล้ว

---

## 2. Parity gate — 6 กลุ่ม ผ่านทั้งหมด

| # | ตรวจอะไร | ผล |
|---|---|---|
| 1 | sequence 18 มิติ: production `_windows` vs harness `_winfeat` | ตรงทุกตำแหน่ง (max diff 0.00e+00) |
| 2 | ECDF ของ harness vs ตาราง calibration ของ production | ตรงทุกจุดที่สุ่มตรวจ |
| 3 | `apply_config` vs `fuse` ของ production | ตรง 400/400 แถว |
| 4 | counterfactual ใช้ Policy Gate object เดียวกันสองรอบ | ตรง · `min_action` ถูกบังคับครบ |
| 5 | เรียก sklearn เป็นชุด vs ทีละแถว | ตรงทุกหลัก (500 แถว) |
| 6 | `resolve_action` vs `fuse` เต็มรูปแบบ ที่หลาย threshold | ตรงทุกแถว (400 แถว) |

กลุ่ม 5 และ 6 เพิ่มในรอบนี้เพราะเป็นการเปลี่ยนวิธีคำนวณเพื่อความเร็ว —
**การเปลี่ยนวิธีคำนวณต้องพิสูจน์ว่าให้ค่าเท่าเดิม ไม่ใช่เชื่อว่าเท่า**

- กลุ่ม 5: เรียก `score_samples` ทีละแถวใช้ 7.8 ms/แถว (overhead ของ sklearn ล้วน)
  → 6,000 แถวกิน 47 วินาที · เรียกเป็นชุดลดเหลือระดับมิลลิวินาที
- กลุ่ม 6: production แยก `ResolverInput` + `resolve_action()` ออกมาเป็น
  **จุดเดียวที่แปลงคะแนนเป็น action** — ทั้ง `fuse`, `fuse_weighted_sum` และการทดลอง
  เดินผ่านฟังก์ชันนี้หมด · ทำให้กวาด threshold นับสิบล้านจุดได้โดยไม่ต้องมีสำเนา logic
  ใน harness (ต้นเหตุของ B66)

---

## 3. Shortcut audit — ชุดพัฒนา (ก่อน freeze)

75 runs = 5 seeds × 5 sizes × 3 splits (`train`, `validation-calibration`, `validation-tuning`)
ครบทั้ง 23 ฟีเจอร์ · ฝั่ง attack ใช้ `dev_attacks` เท่านั้น · **ไม่อ่าน holdout เลย**

เกณฑ์ประกาศก่อนรัน: `separation_auc > 0.99` หรือ `coverage < 0.05`
AUC ใช้ Mann-Whitney แบบ **mid-rank** (จัดการค่าเสมอ)

| | ค่า |
|---|---|
| ฟีเจอร์ที่เข้าเกณฑ์ | **0 / 23** |
| AUC สูงสุด | 0.9508 (`login_count_24h`) |
| coverage ต่ำสุด | 0.2039 (`log_minutes_since_last_login`) |

> **ถ้อยคำที่ถูกต้อง:** *ไม่พบ single-feature shortcut บนชุดพัฒนา ตามเกณฑ์ที่กำหนด*
> **ไม่ใช่** "ไม่มี shortcut" — เกณฑ์นี้ตรวจได้เฉพาะฟีเจอร์เดี่ยว ไม่ครอบคลุมการรวมกัน
> ของหลายฟีเจอร์

**ผลตรวจ shortcut ของรอบก่อนถูกประกาศเป็น `superseded`** เหตุผล: `tie-unsafe AUC
implementation` — ตัวตรวจเดิมให้อันดับต่างกันกับค่าที่เท่ากันโดยขึ้นกับลำดับใน array
ทำให้ฟีเจอร์ที่ฝั่งหนึ่งผูกค่าเดียวทั้งหมดได้ AUC = 1.0 ปลอม (เคยรายงาน
`passkey_last_used_days` = 1.000 ทั้งที่ค่าจริง 0.5832) บั๊กนี้สืบทอดมาจาก
`exp_final_gate.py` ผลรอบก่อนจึงเชื่อถือไม่ได้ทั้งที่รายงานว่า "ไม่พบ"

---

## 4. Grid search — validation-tuning เท่านั้น

161,650 เหตุการณ์ · 25 cells · macro-average ข้าม (seed × size × user)

### 4.1 งบที่ประกาศก่อนรัน

| | งบ | พื้นต่ำสุดที่สถาปัตยกรรมใหม่ทำได้ (Policy Gate ล้วน) |
|---|---|---|
| challenge FPR | ≤ 1.0% | **0.127%** → เป้าทำได้ |
| block FPR | ≤ 0.2% | 0.000% → เป้าทำได้ |
| warn FPR | ≤ 5.0% | — |

**ไม่มีการขยับเป้าหลังเห็นผล** · `attainable_floor` วัดโดยดัน threshold ทุกตัวไปเกิน 1.0
แล้วดูว่าเหลืออะไร — ส่วนที่เหลือมาจาก Policy Gate ล้วน ซึ่ง threshold ไม่มีอำนาจลด

### 4.2 γ — ประกาศสองรอบ บันทึกทั้งคู่

| pass | กริด | ผล |
|---|---|---|
| 1 | 0.0, 0.1, 0.2, 0.35, 0.5 | ค่าที่เลือก **ติดขอบกริด** (0.5) recall ยังเพิ่มขึ้นเรื่อยๆ |
| 2 | + 0.65, 0.8, **1.0** | เลือก γ = 1.0 · ส่วนเพิ่มลดลงชัด (0.5→1.0 ได้ +0.8 จุด เทียบกับ 0.0→0.5 ได้ +4.8 จุด) |

หยุดที่ 1.0 เพราะ γ = 1 คือ `R = M + S(1−M) = 1 − (1−M)(1−S)` = **noisy-OR** ของหลักฐาน
สองชั้น ซึ่งเป็นปลายทางที่มีความหมายของสูตร ไม่ใช่เลขที่สุ่มตัด

> การขยายกริดหลังเห็นผลของ tuning เป็นสิ่งที่ tuning split มีไว้ให้ทำ (holdout ยังปิดสนิท)
> แต่ **ต้องบันทึกว่าเป็นรอบที่สอง** ไม่ใช่รายงานเหมือนประกาศกริดนี้มาตั้งแต่แรก

### 4.3 ผลบน tuning (γ กลาง = 1.0 เลือกจาก Config E)

| cfg | γ | recall (warn+) | recall@challenge | precision | warn FPR | ch FPR | within-config L3 unique |
|---|---|---|---|---|---|---|---|
| A legacy | fixed | 0.8937 | **0.8422** | 0.6366 | 2.13% | **1.85% ✗** | 0.020 |
| B L1+L2 | 1.0 | **0.8961** | 0.7252 | 0.6144 | 3.76% | 0.78% | — |
| C +point | 1.0 | 0.8713 | 0.6747 | 0.5743 | 4.13% | 0.88% | 0.122 |
| D +sequence | 1.0 | 0.8268 | 0.6853 | 0.6294 | 3.42% | 0.77% | 0.102 |
| E +ทั้งสอง | 1.0 | 0.8620 | 0.6296 | 0.6195 | 3.41% | 0.73% | **0.168** |
| F weighted sum | — | 0.8392 | 0.6375 | **0.6753** | 2.61% | 0.55% | — |

รายงานสองมุมเสมอ — **γ กลางตัวเดียว** (ค่าที่ deploy ได้จริง เพราะระบบตั้ง γ ได้ค่าเดียว)
และ **γ ดีที่สุดต่อ config** (เทียบสถาปัตยกรรมอย่างเป็นธรรม) · สองมุมให้ผลตรงกันทุก config
ยกเว้น D · γ ไม่แยกตามขนาดข้อมูลในทั้งสองมุม

**Candidate ที่ประกาศก่อนเปิด holdout: Config B** (บันทึกใน `frozen_config.json`
ฟิลด์ `deployed_config`) — **ไม่มีการประกาศ fallback ไว้**

---

## 5. บั๊กที่พบในกฎการเลือกของตัวเอง — และแก้ก่อน freeze

**อาการ:** Config B กระโดดจาก recall 0.8682 (γ ≤ 0.8) เป็น 0.8961 ที่ γ = 1.0
พร้อม precision ตกจาก 0.680 เหลือ 0.614 ทั้งที่ challenge FPR เท่าเดิม (0.78%)

**สาเหตุ:** `WARN_FPR_BUDGET = 0.05` ถูกประกาศไว้แต่ **ไม่เคยถูกตรวจใน `eligible()`**
และนิยาม `recall` นับ `warn` ด้วย → จุดทำงานดัน recall ขึ้นได้ด้วยการ **เตือนถี่ขึ้น**
โดยไม่มีคอลัมน์ไหนฟ้อง · ค่าจริงคือ warn FPR 2.40% → 3.76%

**แก้:** (1) `eligible()` ตรวจงบ warn ทั้งค่ารวมและทุกขนาด (2) เพิ่ม `recall_challenge`
รายงานคู่กับ `recall` เสมอ

**ผลของการแก้:** คอลัมน์ `recall@challenge` เปลี่ยนการอ่านผลอย่างมีนัยสำคัญ —
recall แบบ surfaced อยู่ที่ 0.77–0.91 เกือบเท่ากันทุก config แต่ที่ระดับ challenge
กระจายตั้งแต่ 0.47 ถึง 0.75 · **ถ้ารายงานแค่ recall แบบเดิม ความต่างนี้จะหายไปหมด**

---

## 6. เทียบกับระบบเดิม — เทียบที่ Challenge FPR 1% ไม่ได้

วัดโดยดัน `THRESHOLDS` ภายในของ `risk_aggregator` ให้คะแนนไม่มีทางถึง แล้วดูว่าเหลืออะไร
(คืนค่าเดิมหลังวัด) — artifact: `legacy_floor.json`

| Config A | recall | challenge FPR | block FPR |
|---|---|---|---|
| จุดทำงานที่ส่งมอบ | 0.8937 | 1.85% | 0.04% |
| ดัน threshold จนสุด | 0.7514 | **1.2467%** | 0.00% |

**ถ้อยคำที่ถูกต้อง:**

> ไม่สามารถเปรียบเทียบที่ **Challenge FPR = 1%** ได้ เพราะ Legacy Floor เท่ากับ **1.2467%**
> ซึ่งเป็นผลจาก policy floor ที่ฝังอยู่ใน**ชั้นให้คะแนน**ของดีไซน์เดิม
> (`rule.min_action` / `behavior.min_action`) ที่ threshold ไม่มีอำนาจลด

**ไม่ใช่** "เทียบที่ FPR เท่ากันไม่ได้ทางโครงสร้าง" — ยังเปรียบเทียบที่ **common FPR
ที่สูงกว่า 1.2467%** ได้ เช่น 1.5% หากทุก config มี operating point ที่ทำได้จริงที่ระดับนั้น
**การเทียบที่ common FPR 1.5% ยังไม่ได้ทำในรอบนี้** — เป็นงานของรอบถัดไป (ต้องกวาดบน
validation ไม่ใช่บน holdout)

สถาปัตยกรรมใหม่มีพื้นที่ **0.127%** — ต่ำกว่าสิบเท่า · เป็นผลลัพธ์ที่จับต้องได้ของการ
แยก Policy Gate (ข้อบังคับ) ออกจาก risk evidence (การคาดการณ์)

---

## 7. ผลบน final holdout — เปิดครั้งเดียว

316,150 เหตุการณ์ (attack 16,150 · normal 300,000) · leakage 0 แถว
shortcut audit บน holdout: **0/23 เข้าเกณฑ์** (AUC สูงสุด 0.7819 = `hours_from_typical_login_time`)

| cfg | recall (warn+) | recall@challenge | precision | warn FPR | ch FPR | block FPR | campaign surfaced |
|---|---|---|---|---|---|---|---|
| A legacy | 0.9018 | **0.7459** | 0.5158 | 2.39% | 2.26% | 0.08% | 0.9918 |
| **B** (candidate) | **0.9068** | 0.7080 | 0.5082 | 4.03% | 0.93% | **0.25%** | 0.9878 |
| C +point | 0.8805 | 0.6602 | 0.4592 | 4.54% | 1.05% | 0.13% | 0.9837 |
| D +sequence | 0.7982 | 0.6692 | 0.5185 | 3.48% | 1.43% | 0.12% | 0.9796 |
| E +ทั้งสอง | 0.8233 | 0.6107 | 0.4656 | 4.13% | 1.29% | 0.11% | 0.9796 |
| F weighted sum | 0.7696 | 0.4678 | 0.5638 | 2.58% | **0.66%** | 0.16% | 0.9551 |

### 7.1 Final Gate — ผ่าน/ไม่ผ่าน ต่องบที่ประกาศไว้

| cfg | warn ≤ 5.0% | challenge ≤ 1.0% | block ≤ 0.2% | ผ่านครบ |
|---|---|---|---|---|
| A legacy | 2.39% ✓ | 2.26% ✗ | 0.08% ✓ | **ไม่ผ่าน** (นอกงบตั้งแต่ต้นตามดีไซน์) |
| **B (candidate)** | 4.03% ✓ | 0.93% ✓ | **0.25% ✗** | **ไม่ผ่าน** |
| C | 4.54% ✓ | 1.05% ✗ | 0.13% ✓ | ไม่ผ่าน |
| D | 3.48% ✓ | 1.43% ✗ | 0.12% ✓ | ไม่ผ่าน |
| E | 4.13% ✓ | 1.29% ✗ | 0.11% ✓ | ไม่ผ่าน |
| F | 2.58% ✓ | 0.66% ✓ | 0.16% ✓ | **ผ่านครบ** — แต่ไม่ใช่ candidate ที่ประกาศไว้ |

> **ถ้อยคำที่ถูกต้อง:** Config B ให้ recall สูงสุดในกลุ่ม candidate ใหม่และผ่านงบ
> Challenge FPR แต่ **ไม่ผ่านงบ Block FPR** · ส่วน Config F ผ่านงบ FPR ทุกระดับ
> แต่ให้ recall ต่ำกว่าอย่างชัดเจน และ **ไม่ได้ถูกประกาศเป็น candidate หรือ fallback
> ไว้ก่อนเปิด holdout** จึงเลือกย้อนหลังไม่ได้ (post-hoc selection)

### 7.2 ช่วงเชื่อมั่น (cluster/hierarchical bootstrap สุ่มระดับผู้ใช้ 1,000 รอบ)

| cfg | recall [95% CI] | challenge FPR [95% CI] |
|---|---|---|
| A | 0.9016 [0.8866, 0.9165] | 0.0226 [0.0165, 0.0292] |
| B | 0.9067 [0.8960, 0.9161] | 0.0093 [0.0063, 0.0133] |
| C | 0.8802 [0.8618, 0.9005] | 0.0105 [0.0057, 0.0161] |
| D | 0.7978 [0.7668, 0.8224] | 0.0143 [0.0048, 0.0293] |
| E | 0.8227 [0.7844, 0.8569] | 0.0129 [0.0054, 0.0235] |
| F | 0.7687 [0.7128, 0.8222] | 0.0066 [0.0045, 0.0093] |

> ⚠️ **CI ชุดนี้เป็นแบบ unpaired** — บอกความไม่แน่นอนของแต่ละ config ได้ แต่
> **ยังไม่ใช่การทดสอบความแตกต่าง** เพราะทุก config ประเมินบนเหตุการณ์**ชุดเดียวกัน**
> การที่ CI ไม่ทับกันเป็นหลักฐานเบื้องต้นเท่านั้น · ต้องทำ **paired hierarchical
> bootstrap** (สุ่มโครงสร้าง `user → seed → instance/event` เดียวกันแล้ววัดผลต่าง)
> จึงจะสรุปได้ — **ยังไม่ได้ทำในรอบนี้** ดู §12

Latency (เฉพาะเส้นทาง L1/L2/L3 + fusion ไม่รวม I/O): p50 0.044–0.078 ms · p95 0.248–0.301 ms

---

## 8. ข้อค้นพบ

### 8.1 L3 จับได้เฉพาะตัวใน**ระดับเหตุการณ์** แต่ไม่พบในระดับแคมเปญ

| | Config C | Config D | Config E |
|---|---|---|---|
| **within-config L3 counterfactual unique** (เหตุการณ์) | 16.7% | 9.0% | 12.7% |
| แคมเปญที่เฉพาะ L3 จับได้ | **0 / 245** | **0 / 245** | **0 / 245** |
| Wilson 95% upper bound ของสัดส่วนนั้น | **1.54%** | 1.54% | 1.54% |
| **net recall difference เทียบ B** | −2.63 pp | −10.86 pp | **−8.35 pp** |
| net recall@challenge เทียบ B | −4.78 pp | −3.88 pp | −9.73 pp |

**ชื่อของตัวเลข 12.7% ต้องระบุให้ครบว่าเป็น `within-config L3 counterfactual unique`**
— คือ "ภายใต้ threshold ของ Config E เอง มีกี่เหตุการณ์ที่ผลเปลี่ยนเพราะหลักฐาน L3"
มัน **ไม่ใช่กำไรสุทธิ** และห้ามอ่านว่า "L3 เพิ่มการตรวจจับ 12.7%" เพราะ recall รวมของ E
ต่ำกว่า B ถึง 8.35 pp · ต้องรายงานสามตัวนี้คู่กันเสมอ:

```
within-config L3 counterfactual unique = 12.7%
net recall difference B -> E            = -8.35 pp
campaign-level unique                   = 0/245  (Wilson 95% upper 1.54%)
```

**`0/245` ห้ามอ่านว่า "L3 ไม่มีโอกาสช่วยระดับแคมเปญเลย"** — สิ่งที่วัดได้คือ
*ไม่พบในตัวอย่างนี้* ขอบบนที่ 95% ยังเปิดไว้ถึง 1.54% (ราว 3.8 แคมเปญจาก 245)
ค่านี้คำนวณแบบ Wilson ซึ่งสมมติว่าแคมเปญเป็นอิสระต่อกัน — ควรเสริมด้วย
hierarchical bootstrap ตาม `user / seed / instance` ด้วย (ยังไม่ได้ทำ ดู §12)

### 8.2 L3 ทำให้ recall แย่ลง โดยเฉพาะกับ attack แบบที่คาดว่ามันจะเก่ง

recall รายตระกูล — Config B เทียบ Config E บน holdout:

| ตระกูล | n | B | E | ต่าง |
|---|---|---|---|---|
| `u_subsystem_shuffle` | 1,500 | 0.833 | 0.624 | **−0.209** |
| `u_off_f_axis` | 1,500 | 0.907 | 0.701 | **−0.206** |
| `u_intermittent` | 1,500 | 0.821 | 0.645 | −0.176 |
| `u_scope_only` | 1,500 | 0.795 | 0.655 | −0.140 |
| `u_mixed_direction` | 1,500 | 0.811 | 0.706 | −0.105 |
| `subtle_rare_device` | 250 | 0.696 | 0.644 | −0.052 |
| `combined_ato`, `new_device`, `failed_spike`, … | 600 ต่อตระกูล | 1.000 | 1.000 | 0.000 |

ตระกูล `u_*` คือ attack ที่ออกแบบให้ **ไม่ตรงกับกฎตายตัว** — กลุ่มที่ anomaly detection
ควรได้เปรียบที่สุด แต่กลับเป็นกลุ่มที่ E แย่กว่า B มากที่สุด

**กลไก:** การเพิ่มหลักฐาน L3 ดันคะแนนของ login **ปกติ** ขึ้นด้วย → threshold ต้องสูงขึ้น
เพื่อรักษางบ FPR → attack ที่ L1/L2 เคยจับได้พอดีๆ หลุดไป · L3 จ่ายค่าใช้จ่ายให้ทุกเหตุการณ์
เพื่อแลกกับการจับได้เพิ่มเฉพาะบางเหตุการณ์ที่ไม่เปลี่ยนผลระดับแคมเปญ

> ตัวเลขในตารางนี้เป็นผลต่างแบบ **point estimate ยังไม่มี paired CI** — ดู §12.1

### 8.3 threshold ที่จูนบน validation **ไม่ย้ายมาตรงบน holdout**

| cfg | ch FPR (tuning) | ch FPR (holdout) | ส่วนต่าง |
|---|---|---|---|
| B | 0.78% | 0.93% | +0.15 pp |
| C | 0.88% | 1.05% | +0.17 pp |
| E | 0.73% | 1.29% | **+0.56 pp** |
| D | 0.77% | 1.43% | **+0.66 pp** |

FPR สูงขึ้น**ทุก config** · config ที่มี L3 ส่วนต่างใหญ่กว่าอย่างชัดเจน — distribution
ของคะแนน L3 บน holdout ต่างจาก validation มากกว่าที่ L1/L2 ต่าง · ผลคือ C, D, E
หลุดงบ challenge 1% บน holdout ทั้งที่อยู่ในงบตอนจูน และ B หลุดงบ block

นี่คือเหตุผลเชิงประจักษ์ที่ต้องมี holdout แยก และเป็นตัวเลขที่ต้องอยู่ในเล่ม —
ไม่ใช่รายงานเฉพาะตัวเลข validation ที่ดูดีกว่า

### 8.4 threshold ที่เลือกได้อยู่ที่ค่าสูงมาก — และนั่นถูกต้องตามนิยาม

`challenge = 0.9898` (Config B) ไม่ได้แปลว่า "ต้องเสี่ยงเกือบเต็ม 100 ถึงจะถาม" —
เพราะ evidence คือ percentile ของ login ปกติ threshold ที่ percentile 98.98
**คือ** จุดที่ทำให้ FPR ราว 1% โดยตรง · อ่านตรงตัวได้ว่า "หายากกว่า login ปกติ 98.98%"
ต้องอธิบายจุดนี้ในเล่ม ไม่งั้นผู้อ่านจะตีความ threshold ผิด

### 8.5 หมายเหตุเรื่อง ECE — ถอดออกจาก metric หลัก

รอบนี้เคยคำนวณ Expected Calibration Error ไว้ (B 0.198 · E 0.607) แต่ **ตัวเลขนี้ถูกถอด
ออกจาก metric หลักแล้ว** เพราะใช้ผิดบริบท: ECE เป็นเครื่องมือสำหรับ **probability
prediction** ขณะที่รายงานฉบับนี้ยืนยันเองว่า `final_risk_score` **ไม่ใช่ probability**
แต่เป็น percentile evidence · ค่า ECE 0.607 ของ Config E จึง **ไม่ได้พิสูจน์ว่า E แย่**
เพราะคะแนนไม่เคยอ้างว่าเป็นความน่าจะเป็นตั้งแต่ต้น (ค่ายังอยู่ใน `final_result.json`
ในฐานะข้อมูลดิบ แต่ไม่ถูกใช้สรุปอะไร)

เครื่องมือที่ถูกต้องสำหรับคำถามนี้ (ยังไม่ได้ทำ — ดู §12):
- benign percentile exceedance
- observed FPR ที่ p95 / p99 / p99.9
- Kolmogorov–Smirnov / PIT uniformity บน login ปกติ
- tail calibration ระหว่าง validation กับ holdout

ถ้าจะใช้ ECE จริง ต้องสร้าง probability calibrator แยกต่างหากก่อน

---

## 9. ข้อสรุปสำหรับงานวิจัย

ผลนี้ **ไม่ได้แปลว่า IsolationForest ใช้ไม่ได้** แต่แปลว่า:

> บนข้อมูลสังเคราะห์ชุดนี้และงบ FPR ที่กำหนด การนำ L3 เข้า L4 แบบ point-all,
> sequence หรือทั้งสองแบบ **ไม่เพิ่มการตรวจพบในระดับแคมเปญ** และทำให้ threshold
> ต้องสูงขึ้นจน **recall สุทธิลดลง** ดังนั้น L3 **ยังไม่ผ่านเกณฑ์สำหรับ enforcement**
> และควรคงไว้ใน shadow mode

เป็นผลลัพธ์เชิงทดลองที่ตรงไปตรงมา และใช้เป็นบทที่ 4 ได้ แม้ Hybrid ที่มี L3
จะไม่ชนะ baseline ก็ตาม

**สมมติฐานสำหรับรอบถัดไป — conditional L3 fusion:** ให้ L3 มีผลเฉพาะเมื่อ L1/L2
อยู่ในช่วงไม่แน่ใจ แทนการดันคะแนนทุกเหตุการณ์ · ต้องถือเป็น **สมมติฐานใหม่**
ใช้ validation ใหม่ และ final holdout ชุดใหม่

---

## 10. สถานะ Deploy

| ส่วน | สถานะ |
|---|---|
| สถาปัตยกรรมใหม่ (Policy Gate + evidence contract + L4 จุดเดียว) | พัฒนาและทดสอบแล้ว |
| Config B | ดีที่สุดด้าน recall แต่ **Final Gate ไม่ผ่าน** (block FPR 0.25% > 0.20%) |
| Config F | ผ่านงบ FPR แต่ **ไม่ใช่ candidate ที่เลือกไว้** และ recall ต่ำ |
| L3 monitoring / shadow | ใช้ต่อได้ |
| L3 มีผลต่อ MFA / Block | **ยังไม่พร้อม** |
| **Production deployment ใหม่** | **ยังไม่อนุมัติ** |

ระบบที่ให้บริการอยู่ **ไม่เปลี่ยน** จากผลรอบนี้

---

## 11. Provenance — สิ่งที่ต้องทำก่อนออก tag

`frozen_config.json` บันทึก `git_commit = bdd05e6d0c22` พร้อม `git_dirty = true`
→ commit SHA เพียงอย่างเดียว **สร้างผลเดิมไม่ได้**

ตรวจแล้ว ณ 2026-09-03 หลัง `final` เสร็จ:

| | ผล |
|---|---|
| scoring files ปัจจุบัน vs hash ใน `frozen_config.json` | **21/21 ตรง** |
| split cells ปัจจุบัน vs hash ใน `frozen_config.json` | **25/25 ตรง** |

### 11.1 เหตุการณ์ระหว่าง commit — `ruff-format` แก้ไฟล์หลัง `final` เสร็จ

ตอน commit รอบ 1 pre-commit hook `ruff-format` **จัดรูปแบบไฟล์ 5 ไฟล์ใหม่**
(4 ไฟล์อยู่ใน `scoring_fingerprint`) → hash ของไฟล์ที่ commit **ไม่ตรง** กับ hash
ที่บันทึกไว้ใน `frozen_config.json` อีกต่อไป

**ทำไม provenance ยังยืนอยู่ได้:** พิสูจน์ว่าเป็นการเปลี่ยน **รูปแบบล้วน** ด้วย
AST equality — `ast.dump(ast.parse(before)) == ast.dump(ast.parse(after))`
เป็นจริงทุกไฟล์ และ byte ที่ใช้รันจริง (ดึงจาก git index ก่อน hook แก้)
ถูกเก็บไว้ที่ `ml-service/data/hybrid_experiment/run_bytes_round1/`

| ไฟล์ | hash ที่ใช้รัน | hash หลัง format | AST เหมือน | อยู่ใน fingerprint |
|---|---|---|---|---|
| `exp_hybrid_gate.py` | `f7ed9d93969d` | `ef941e0ebdd5` | ✓ | ✓ |
| `hybrid_experiment/sweep.py` | `aa1d313af8f6` | `c10c60605bd6` | ✓ | ✓ |
| `hybrid_experiment/tune.py` | `018b2c68e53b` | `9fb148c367ef` | ✓ | ✓ |
| `hybrid_experiment/audit.py` | `5ea4845b4fb5` | `98c9b835da01` | ✓ | ✓ |
| `tests/test_evidence_contract.py` | `f84ce8e66b6c` | `04e0bea7e9b7` | ✓ | — |

**ข้อจำกัดที่ต้องยอมรับตรงๆ:** คำสั่ง `final` จะ **ปฏิเสธการรันซ้ำ** เพราะ hash ไม่ตรง
— เป็นพฤติกรรมที่ถูกต้องของ guard ไม่ใช่บั๊ก · การทำซ้ำแบบ **byte-exact** ต้องใช้ไฟล์
ใน `run_bytes_round1/` ไม่ใช่ไฟล์ที่ commit · รายละเอียดเต็มอยู่ใน
`ml-service/data/hybrid_experiment/provenance_round1.json`

### 11.2 ขั้นตอนที่เหลือ

1. ✅ ตรวจว่า scoring files ตรงกับ hash ใน `frozen_config.json` ก่อน commit — **ผ่าน 21/21**
2. ✅ Commit working tree **โดยไม่เปลี่ยน logic** (ยืนยันด้วย AST equality — §11.1)
3. ✅ บันทึก hash ทั้งสองชุด + หลักฐาน AST ลงรายงานและ `provenance_round1.json`
4. Manifest ต้องรวม `final_result.json`, `frozen_config.json`, `provenance_round1.json`
5. Tag commit ใหม่
6. **ห้ามรัน `final` ซ้ำเพียงเพราะ commit เปลี่ยน** ถ้าโค้ดต่างกันแค่รูปแบบ

ถ้ามี scoring file ใดเปลี่ยน **เชิง logic** หลัง `final` → ผลรอบนี้ต้องถือว่า
**provenance ไม่สมบูรณ์** และต้องรันใหม่ทั้งรอบ

---

## 12. สิ่งที่ยังไม่ได้ทำ และโปรโตคอลรอบถัดไป

### 12.1 การวิเคราะห์ที่ยังขาด

| # | สิ่งที่ต้องทำ | เหตุผล |
|---|---|---|
| 1 | **Paired hierarchical bootstrap** — ΔRecall(B−C), ΔRecall(B−D), ΔRecall(B−E), ΔChallengeFPR(B−E), ΔCampaignRecall(B−E) สุ่มโครงสร้าง `user → seed → instance/event` เดียวกัน | CI แบบ unpaired ใน §7.2 ไม่ใช่การทดสอบความแตกต่าง |
| 2 | **Tail calibration** — benign percentile exceedance, FPR ที่ p95/p99/p99.9, KS/PIT uniformity บน normal, เทียบ validation vs holdout | แทน ECE ซึ่งใช้ผิดบริบท (§8.5) |
| 3 | **Hierarchical bootstrap ของสัดส่วนระดับแคมเปญ** | Wilson สมมติแคมเปญเป็นอิสระ ซึ่งไม่จริง |
| 4 | **เปรียบเทียบที่ common FPR ≥ 1.2467%** (เช่น 1.5%) | ทำให้เทียบกับระบบเดิมได้จริง — ต้องกวาดบน validation |
| 5 | เปลี่ยนชื่อฟิลด์ `l3_effective_unique` → `within_config_l3_counterfactual_unique` | ชื่อเดิมสื่อเกินหลักฐาน |
| 6 | รัน pytest เต็มชุดแล้วบันทึก command + container image + commit SHA | ดู §12.3 |

ข้อ 1–5 แก้ในโค้ด **หลัง** commit รอบ 1 เสร็จแล้วเท่านั้น เพราะการแก้ตอนนี้จะทำให้
hash ของ scoring files ไม่ตรงกับ `frozen_config.json` และทำลาย provenance ของรอบ 1

### 12.2 โปรโตคอลของ Final Round 2 — **ห้ามใช้ holdout ชุดเดิม**

holdout ชุดปัจจุบันถูกเปิดแล้ว **จึงไม่เป็น final holdout อีกต่อไป**
ถ้าปรับ block threshold โดยอาศัยข้อมูลว่า B ได้ 0.25% แล้วรัน holdout เดิมซ้ำ
ตัวเลขที่ได้จะไม่ใช่ผลบน holdout ที่บริสุทธิ์

ลำดับที่ถูกต้อง:

1. ปรับ block threshold **ด้วย validation เท่านั้น** (ห้ามดูตัวเลข holdout ประกอบ)
2. ประกาศ candidate **และ fallback** ล่วงหน้า ก่อน freeze
3. Freeze config ใหม่
4. ใช้ **holdout seed ชุดใหม่ที่ไม่เคยเปิด** (`HOLDOUT_SEEDS = [101, 102, 103, 104, 105]`
   สำรองไว้แล้วใน harness) หรือ prospective production replay
5. รายงาน holdout ปัจจุบันในชื่อ **`final_round_1_failed_gate`** เป็นหลักฐานถาวร

### 12.3 จำนวนเทสที่ต้องกระทบยอด

| ตัวเลข | ที่มา | ขอบเขต |
|---|---|---|
| 934 passed | รายงานรอบก่อน (session ก่อนหน้า) | **ยังไม่ยืนยันว่าใช้คำสั่งใด** |
| 893 passed / 46 skipped | 2026-09-03 · `pytest . -q` ใน container `hub-backend` โดย `--ignore` ไฟล์ 9 ตัวที่เป็นสคริปต์ live-stack (เรียก `sys.exit()` ตอน import: `test_behavior_rarity`, `test_behavior_scope_escalation`, `test_behavior_tier2`, `test_e2e_full_stack`, `test_l1_oidc`, `test_l3_sequence`, `test_l3_window_integrity`, `test_rule_engine_v2_signals`, `test_tier2_catches_evasive`) | unit + integration ที่รันได้โดยไม่ต้องมี stack ครบ |

**ยังไม่กระทบยอด** — ต้องรัน full pytest อีกครั้งก่อน freeze รอบ 2 พร้อมบันทึก
command, container image digest และ commit SHA ลงในรายงาน
(ณ เวลาเขียนรายงานนี้ Docker engine ไม่ตอบสนอง จึงยังรันซ้ำไม่ได้)

---

## 13. ข้อจำกัดที่ต้องระบุในเล่ม

1. **ข้อมูลสังเคราะห์** — ตระกูล attack ถูกออกแบบโดยผู้พัฒนา จึงอาจเอียงไปทางสัญญาณ
   ที่ L1/L2 มองเห็น · ข้อสรุปว่า "L3 ไม่คุ้ม" เป็นข้อสรุป**สำหรับข้อมูลชุดนี้**
   ไม่ใช่ข้อสรุปทั่วไปเกี่ยวกับ anomaly detection
2. **ผู้ใช้ 12 คนต่อ seed** — CI คำนวณด้วย cluster bootstrap ที่สุ่มระดับผู้ใช้แล้ว
   แต่จำนวนคลัสเตอร์ยังน้อย ช่วงเชื่อมั่นจึงกว้างสำหรับ config ที่แปรปรวนมาก (D, E)
3. **การเปรียบเทียบระหว่าง config ยังเป็น unpaired** — ดู §12.1 ข้อ 1
4. **shortcut audit ตรวจฟีเจอร์เดี่ยว** — ไม่ครอบคลุมการรวมกันของหลายฟีเจอร์
5. **sequence model ต้องมีประวัติ ≥ 100** — ที่ขนาด 50 Config D abstain ทั้งหมด
   (`l3_abstain_rate` = 0.2 คือ 1 ใน 5 ขนาดที่ไม่มีโมเดล ไม่ใช่ความผิดพลาด) ·
   ค่า 1.0 ของ Config A/B เป็นเรื่องปกติเพราะสอง config นั้นไม่มีมุมมอง L3 เลย
6. **latency วัดเฉพาะเส้นทางคำนวณ** ไม่รวม HTTP ไป ml-service, DB query, หรือ I/O จริง
7. **`git_dirty = true` ตอน freeze** — ดู §11

---

## 14. Artifacts

ทุกไฟล์อยู่ใน `ml-service/data/hybrid_experiment/` (gitignored — ข้อมูลจริงห้ามขึ้น git)

| ไฟล์ | เนื้อหา |
|---|---|
| `shortcut_audit_dev.json` | audit ชุดพัฒนา 75 runs + `supersedes` ของรอบก่อน |
| `tuning_result_pass1.json` | grid search รอบแรก (γ ≤ 0.5) เก็บไว้เป็นหลักฐาน |
| `tuning_result_pass2.json` | รอบสอง ก่อนแก้บั๊กงบ warn |
| `tuning_result.json` | รอบสุดท้าย — สองมุม + full grid |
| `legacy_floor.json` | พื้น FPR ของระบบเดิม |
| `frozen_config.json` | commit + hash โค้ด 21 ไฟล์ + hash split 25 cells + เกณฑ์ทั้งหมด |
| `final_result.json` | ผล holdout **รอบ 1 (ไม่ผ่าน gate)** + CI + shortcut audit ของ holdout |
| `cells/*.pkl` | ผลของชั้น L1/L2/L3 ต่อ cell (25 ไฟล์ · ~1.4 MB ต่อไฟล์) |

## 15. ทำซ้ำ

```bash
cd hub/backend
PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py parity --seed 42 --size 500
PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py audit
PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py prepare
PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py tune
PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py legacy-floor
PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py freeze --parity-passed --deploy-config B
PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py final
```

ต้องมีไฟล์ผู้ใช้จริง (`users.xlsx`) + `roster_v2.json` ซึ่ง **gitignored โดยตั้งใจ**
`final` ปฏิเสธการรันซ้ำถ้ามีผลอยู่แล้ว (ต้องใส่ `--i-know-this-is-a-rerun`
และบันทึกเหตุผลในรายงาน)

เทสของสัญญาสถาปัตยกรรม:

```bash
docker compose exec hub-backend pytest tests/test_evidence_contract.py -v
```
