# รายงานผลการทดลอง — Hybrid Risk-Based Authentication (4 ชั้น)

ตั้งแต่การสร้างชุดข้อมูล การตรวจสอบคุณภาพ การวัดประสิทธิภาพ จนถึงการทดสอบซอฟต์แวร์

วันที่ 9 ก.ย. 2569 · ปรับปรุง 10 ก.ย. 2569 · สถานะล่าสุด: `p48t2-validation-inconclusive`
รายงานนี้เป็นเอกสาร**สรุปรวม** — ตัวเลขทุกตัวอ้างกลับไปยังรายงานรายรอบใน
`hub/backend/tests/reports/` ซึ่งถูก freeze ไว้แล้ว

> **สถานะปัจจุบัน** — ระบบ Hybrid Risk Assessment ผ่านการทดสอบเชิงฟังก์ชันและการตรวจสอบ
> บนประชากรจำลอง P48-T2 แต่ Challenge FPR ยังสรุปไม่ได้ภายใต้ช่วงความเชื่อมั่นระดับ
> ผู้ใช้ จึงคงใช้งานเฉพาะ Shadow Mode และยังไม่ใช้ผลของ Hybrid หรือ Isolation Forest
> บังคับ MFA หรือปฏิเสธการเข้าถึง
>
> ผลรอบ P48-T2 (หลังแก้ `weekend_rate`) อยู่ที่
> `hub/backend/tests/reports/p48t2_validation_2026-09-09.md` · ตัวเลขในเนื้อหาด้านล่าง
> ส่วนใหญ่เป็นของ P48 รุ่นเดิม และไม่นำมารวมกับ P48-T2

---

## สารบัญ

1. [ขอบเขตและคำถามที่รายงานนี้ตอบ](#1-ขอบเขตและคำถามที่รายงานนี้ตอบ)
2. [ระบบที่นำมาทดสอบ](#2-ระบบที่นำมาทดสอบ)
3. [การสร้างชุดข้อมูล](#3-การสร้างชุดข้อมูล)
4. [การแบ่งชุดข้อมูล](#4-การแบ่งชุดข้อมูล)
5. [การตรวจสอบคุณภาพข้อมูล](#5-การตรวจสอบคุณภาพข้อมูล)
6. [วิธีการวัดประสิทธิภาพ](#6-วิธีการวัดประสิทธิภาพ)
7. [ลำดับการทดลองและสิ่งที่เรียนรู้ระหว่างทาง](#7-ลำดับการทดลองและสิ่งที่เรียนรู้ระหว่างทาง)
8. [ผลการวัดฉบับล่าสุด](#8-ผลการวัดฉบับล่าสุด)
9. [การทดสอบซอฟต์แวร์](#9-การทดสอบซอฟต์แวร์)
10. [กลไกรักษาความซื่อตรงของกระบวนการ](#10-กลไกรักษาความซื่อตรงของกระบวนการ)
11. [ข้อจำกัด](#11-ข้อจำกัด)
12. [สรุปและงานต่อยอด](#12-สรุปและงานต่อยอด)
13. [ภาคผนวก — วิธีทำซ้ำ](#13-ภาคผนวก--วิธีทำซ้ำ)

---

## 1. ขอบเขตและคำถามที่รายงานนี้ตอบ

### คำถามหลัก

> สถาปัตยกรรม Hybrid RBA แบบ 4 ชั้น ลดการแจ้งเตือนผิด (false positive) เมื่อเทียบกับ
> ระบบเดิมได้จริงหรือไม่ และอยู่ในงบที่ตั้งไว้หรือไม่

### สิ่งที่ **อยู่ใน** ขอบเขต

- การประเมินบนชุดข้อมูลสังเคราะห์ที่ anchor จากพฤติกรรมผู้ใช้จริง
- การเปรียบเทียบกับสถาปัตยกรรมเดิม (baseline) บนข้อมูลชุดเดียวกัน
- ความถูกต้องของวิธีวัด (unit of analysis, ช่วงความเชื่อมั่น, การตัดสิน)

### สิ่งที่ **ไม่อยู่ใน** ขอบเขต

- การประเมินบน traffic จริงในระบบ production (ยังไม่เคยทำ)
- การอ้างว่าตัวเลขที่ได้จะเกิดขึ้นจริงเมื่อ deploy — ข้อมูลเป็นข้อมูลสังเคราะห์
- การนำ Hybrid RBA ขึ้นตัดสินสิทธิ์จริง (สถานะปัจจุบันคือ **Shadow**)

### ข้อสรุปย่อ

Hybrid RBA ลด challenge false positive จาก **3.561%** เหลือ **0.79–0.87%** (ราว 4 เท่า)
แต่ **ยังพิสูจน์ไม่ได้ว่าอยู่ในงบ 1%** — ช่วงความเชื่อมั่นระดับ cluster คร่อมเส้นงบ
ตามกติกาที่ประกาศไว้ล่วงหน้าจึงถือว่ายังไม่ผ่าน และระบบคงสถานะ Shadow

---

## 2. ระบบที่นำมาทดสอบ

### 2.1 โครงสร้าง

```
Login -> Policy Gate -> Feature Extraction -> {L1 Rule, L2 Behavior, L3 Anomaly}
                                                      |
                                                      v
                                            L4 Fusion -> final_risk_score
                                                      -> access_decision
```

### 2.2 สัญญาของแต่ละชั้น (evidence contract)

| ชั้น | หน้าที่ | สิ่งที่คืน |
|---|---|---|
| Policy Gate | ข้อบังคับตายตัวที่ตรวจได้แน่นอน (deny-list, brute-force lockout, step-up บังคับ) | `denied` / `min_action` |
| L1 Rule Engine | กฎเชิงสถิติจากฟีเจอร์ | **หลักฐาน** (คะแนน) เท่านั้น |
| L2 Behavior Profiling | เทียบพฤติกรรมกับ baseline ของผู้ใช้คนนั้น | **หลักฐาน** เท่านั้น |
| L3 Anomaly (IForest) | คะแนนความผิดปกติ point / sequence | **หลักฐาน** เท่านั้น |
| L4 Fusion | รวมหลักฐาน + ตัดสิน | `final_risk_score` + `access_decision` |

**หลักการที่บังคับด้วยเทส:** ชั้นหลักฐาน (L1/L2/L3) ห้ามมีฟิลด์ในแกน access decision
เลย — มีเมื่อไรจะมีคนเชื่อว่ามันทำงาน (บทเรียน B70 · ดู §7.6)

### 2.3 การรวมหลักฐาน (L4)

```
R = M + gamma * S * (1 - M)
```

- `M` = หลักฐานสูงสุดจากชั้นใดชั้นหนึ่ง
- `S` = หลักฐานรองที่สนับสนุน (corroboration)
- `gamma = 1` คือ noisy-OR

การแปลงคะแนนดิบของแต่ละชั้นให้เทียบกันได้ใช้ **empirical CDF (ECDF)** ที่ fit จาก
login ปกติในชุด validation-calibration เท่านั้น

> ค่าที่ได้เรียกว่า **percentile evidence ไม่ใช่ probability** — ไม่ได้ปรับเทียบกับ
> อัตราการเกิด attack จริง การเรียกผิดจะทำให้ผู้อ่านตีความ 0.99 ว่า "มั่นใจ 99%
> ว่าเป็นการโจมตี" ซึ่งไม่ถูกต้อง

### 2.4 คอนฟิกที่นำมาเทียบ

| Config | คำอธิบาย | fusion | L3 views |
|---|---|---|---|
| **A** | Legacy aggregate (baseline เดิม) | legacy | — |
| **B** | L4 ใหม่ + L1/L2 | max + corroboration | — |
| C | B + L3 point | max + corroboration | point |
| D | B + L3 sequence | max + corroboration | sequence |
| E | B + L3 สองมุมมอง | max + corroboration | point, sequence |
| F | Weighted sum + L3 สองมุมมอง | weighted sum | point, sequence |

รอบล่าสุดวัดเฉพาะ **A (baseline)** กับ **B (candidate)** เพราะการทดลองรอบก่อนพบว่า
L3 ไม่เพิ่มการตรวจจับระดับแคมเปญ (ดู §7.3)

### 2.5 งบ false positive (ประกาศไว้ตั้งแต่ต้น ไม่เคยขยับ)

| ระดับ | งบ | ความหมาย |
|---|---|---|
| warn | ≤ 5.0% | บันทึกเฝ้าระวัง ไม่รบกวนผู้ใช้ |
| challenge | ≤ 1.0% | ขอยืนยันตัวตนซ้ำ (Passkey / OTP) |
| block | ≤ 0.2% | ปฏิเสธการเข้าถึง |

---

## 3. การสร้างชุดข้อมูล

### 3.1 ภาพรวม

ข้อมูลสังเคราะห์ถูกสร้างจาก **โปรไฟล์พฤติกรรม** ของผู้ใช้แต่ละคน โดย anchor
พารามิเตอร์จากการวัด `login_sessions` จริง แล้วสุ่มเหตุการณ์ตามโปรไฟล์นั้น

```
โปรไฟล์ผู้ใช้ (18 พารามิเตอร์)
        |
        v
gen_v3.build_seed(seed)  ->  7,000 เหตุการณ์ปกติต่อคน + ชุด attack
        |
        v
dataset.build(size)      ->  แบ่ง 4 ส่วน + สกัดฟีเจอร์ 23 ตัว
```

### 3.2 โครงสร้างเวลาแบบ episode

เหตุการณ์ปกติถูกสร้างเป็น **episode** — ก้อนละ 50 เหตุการณ์กระจายในช่วง 25 วัน
โดยแต่ละ episode ห่างกัน 400 วันบนปฏิทิน

| ค่าคงที่ | ค่า | เหตุผล |
|---|---|---|
| `EPISODE_EVENTS` | 50 | ~2 login/วัน ในช่วง 25 วัน |
| `EPISODE_DAYS` | 25 | ช่วงที่พฤติกรรมยังต่อเนื่องกัน |
| `EPISODE_STRIDE_DAYS` | 400 | ให้ timestamp ไม่ชนกัน |
| `TRAIN_POOL` | 5,000 | episode 0–99 |
| `VAL_N` | 1,000 | episode 100–119 |
| `TEST_N` | 1,000 | episode 120–139 |
| **รวม** | **7,000** | ต่อผู้ใช้หนึ่งคน |

**สถานะ rolling ถูก reset ทุก episode** (velocity, gap, concurrent) แต่ **ความรู้
ระยะยาวสะสมต่อเนื่อง** (เครื่องที่เคยเห็น, ระบบที่เคยใช้, โปรไฟล์เวลา) —
เลียนแบบผู้ใช้ที่หายไปแล้วกลับมา

### 3.3 ฟีเจอร์ 23 ตัว

สกัดด้วย `features_v2.py` แบบ incremental ตามลำดับเวลา (ไม่มีการมองอนาคต)
ครอบคลุมหมวด Temporal / Geographic / Device / Velocity / Brute-force / Scope

> **กฎ B49 — ลำดับฟีเจอร์คือสัญญา** เปลี่ยน/เพิ่ม/สลับ ต้องแก้พร้อมกัน 4 จุด:
> `features.py:FEATURE_NAMES` · `generate_data.py` headers ·
> `feature_extraction.py` return order · `rule_engine.py:FEAT`
> ลืมจุดที่ 4 = rule/behavior อ่านฟีเจอร์ผิดตำแหน่ง (เคยทำคะแนนพุ่ง 1.0)

### 3.4 ชุด attack

สร้างแยกเป็นสองชุดที่ใช้ **พารามิเตอร์คนละชุด** เพื่อกันการเลือก config ให้ตรง test

| ชุด | ใช้ทำอะไร | องค์ประกอบ |
|---|---|---|
| `dev_attacks` | validation | obvious 11 ตระกูล + subtle 5 ตระกูล + campaign |
| `final_attacks` | holdout | เหมือนกัน แต่ปรับ parameter + campaign รูปแบบใหม่ที่ไม่เคยใช้เลือกฟีเจอร์ |

ตัวอย่างจำนวนจริง (P01, seed 301): `dev_attacks` 38 แถว · `final_attacks` 53 แถว

**ตระกูล attack ที่ใช้ประเมิน** — `combined_ato`, `new_device`, `new_ua_family`,
`new_os`, `off_hours`, `failed_spike`, `login_velocity`, `concurrent_sessions`,
`new_passkey`, `permission_change`, `subsystem_lateral` และตระกูล subtle อีก 5:
`subtle_mild_offhour`, `subtle_slow_burst`, `subtle_rare_device`,
`subtle_quiet_lateral`, `subtle_lowandslow`

attack ทุกแถวถูกวางบนปฏิทินของ **episode สุดท้าย** — ถ้าวางก่อนหน้า ค่า gap เทียบ
history จะติดลบ ทำให้กฎ velocity ยิงมั่วจน recall = 100% ปลอม

### 3.5 ประชากรโปรไฟล์ผู้ใช้

#### 3.5.1 ชุดเดิม L12 (12 โปรไฟล์)

เขียนขึ้นด้วยมือจากการวัด `login_sessions` จริง — แต่ละโปรไฟล์มี 18 พารามิเตอร์
(ช่วงเวลา login, อุปกรณ์, subsystem, ความถี่ผิดพลาด, scope ฯลฯ)

**ข้อจำกัดที่พบภายหลัง:** ทุก seed ใช้โปรไฟล์ชุดเดิม การเปลี่ยน seed เปลี่ยนเพียง
การสุ่มเหตุการณ์ ไม่ได้เพิ่มหน่วยทดลอง → ผู้ใช้คนเดียว (U01) ครองสัดส่วน false
positive ได้ถึง **62%** ในบาง seed (ดู §7.4)

#### 3.5.2 ชุดใหม่ P48 (48 โปรไฟล์)

สร้างจาก **การแจกแจงที่ประกาศล่วงหน้า** (`docs/design/USER_POPULATION_P48_PREREG.md`)
ก่อนเขียน generator และมีเทส 22 รายการบังคับให้โค้ดทำตามที่ประกาศ

| ฟิลด์ | การแจกแจง |
|---|---|
| `rows` | `randint(40, 160)` |
| `hour_peaks` | 1–3 จุด · จุดแรก `randint(6,20)` · จุดถัดไป `(prev + randint(3,9)) % 24` |
| `hour_spread` | `uniform(1.5, 4.5)` |
| `weekend_rate` | 0 (25%) / `uniform(0.02,0.15)` (50%) / `uniform(0.15,0.40)` (25%) |
| `devices` | 1–3 เครื่องจาก pool ปกติ · ตัวเด่น `uniform(0.55,1.0)` |
| `subsystems` | 1–3 ระบบ (HUB เสมอ) · ตัวเด่น `uniform(0.50,1.0)` · **โหมดรอง ≥ 0.03** |
| `dur` | `(log(uniform(8,45)), uniform(1.2,2.2))` |
| `fail_rate` | `uniform(0.005, 0.060)` |
| `scope` | `{0.3, 0.5, 0.8, 1.0}` ถ่วงน้ำหนัก |
| `incidents` | **ตรึงที่ 0** (amendment #2 · ดู §3.5.4) |
| อื่น ๆ | `drift`, `sticky`, `overlap`, `active_sub`, `methods`, `passkey`, `perm_age`, `mfa_always` |

`POP_SEED = 480906` · deterministic ทำซ้ำได้เป๊ะ

#### 3.5.3 ข้อบังคับ "โหมดรอง ≥ 0.03" และเหตุผล

ถ้าปล่อยให้สุ่มโหมดรองต่ำมาก (เช่น 0.5%) ประชากรจะเต็มไปด้วยโหมดที่ **ไม่มีทาง**
ปรากฏในชุดฝึก 50 เหตุการณ์ → false positive ที่ cold start จะถูกกำหนดโดย
พารามิเตอร์ตัวนี้ตัวเดียว แทนที่จะสะท้อนคุณสมบัติของระบบ

#### 3.5.4 Amendment #2 — ตรึง `incidents = 0`

**สิ่งที่พบ:** `rule_engine.SCORE_RULES_SPEC` มีกฎ
`confirmed_incident_count >= 1 -> challenge` เป็น **policy floor** ผู้ใช้ที่มีค่านี้
จึงถูก challenge **ทุก login ตลอดกาล** โดยผลลัพธ์ไม่ขึ้นกับโมเดลเลย

หลักฐาน (validation seed 301 · size 50 · Config B):

| user | FPR | สัดส่วนจาก policy floor | `incidents` |
|---|---|---|---|
| P03 | 100.0% | 100% | 1 |
| P44 | 100.0% | 100% | 1 |
| P29 | 100.0% | 100% | 1 |
| ที่เหลือ | ≤ 5.4% | — | 0 |

3 คนใน 32 ดันค่าเฉลี่ยขึ้น **9.4 pp** ด้วยตัวเอง → ตัวเลขที่ได้จะวัด "สัดส่วนผู้ใช้ที่
เคยมี incident" ไม่ใช่อัตราแจ้งเตือนผิดของโมเดล

**การแก้และการรักษาความซื่อตรง:**
- แก้ **ก่อนเปิด holdout** — ไม่กระทบความบริสุทธิ์ของ holdout
- ตัวเลข validation ก่อนหน้าถือเป็น pre-amendment และถูกทิ้งทั้งหมด
- เป็นการแก้ **ข้อผิดพลาดเชิงสเปค** ที่พิสูจน์ได้จากการอ่านกฎ policy floor
  โดยไม่ต้องดูตัวเลขประสิทธิภาพ ไม่ใช่การปรับตามผล
- generator ยังเรียก `rng.choices` ตามเดิมแล้วทิ้งค่า เพื่อไม่ให้ลำดับการสุ่มขยับ →
  ประชากรเปลี่ยน **ฟิลด์เดียว** พิสูจน์ด้วย hash ใน
  `test_amendment_2_changed_only_the_incidents_field`

#### 3.5.5 การผูก identity และนโยบาย PII

โปรไฟล์แต่ละตัวจับคู่กับอีเมล **`@uni.ac.th` เท่านั้น** (บัญชีสังเคราะห์จาก seed
มี 95 บัญชี) — ไม่แตะบัญชี Gmail / `pnu.ac.th` ซึ่งบางบัญชีเป็นของบุคคลจริง

ไฟล์ roster (`ml-service/data/roster_p48.json`) อยู่ใน `.gitignore` ตามนโยบาย
**ข้อมูลจริงห้ามขึ้น git เด็ดขาด**

---

## 4. การแบ่งชุดข้อมูล

### 4.1 การแบ่งภายในผู้ใช้ (4 ส่วน)

```
train                   episode 0–99     สร้างโปรไฟล์ + fit IsolationForest
validation-calibration  episode 100–109  fit ECDF ของแต่ละชั้น (normal ล้วน)
validation-tuning       episode 110–119  เลือก gamma และ threshold
final holdout           episode 120–139  วัดครั้งเดียวหลัง freeze
```

**ทำไมต้องสี่ส่วนไม่ใช่สาม:** ถ้าใช้ validation ชุดเดียวทำทั้ง fit ECDF และเลือก
threshold ค่าที่เลือกจะ overfit กับ ECDF ที่มาจากข้อมูลชุดเดียวกัน ทำให้ผล
มองโลกในแง่ดีเกินจริงโดยไม่มีใครเห็น

### 4.2 การแบ่งระดับโปรไฟล์ (P48)

| ชุด | จำนวน | ใช้ทำอะไร |
|---|---|---|
| **P48-validation** | 32 โปรไฟล์ | วัด/ตรวจทั้งหมดทำที่นี่ |
| **P48-holdout** | 16 โปรไฟล์ | เปิดครั้งเดียว เฉพาะเมื่อ validation ผ่าน |
| **L12-reference** | 12 โปรไฟล์เดิม | รายงาน**แยก** เป็น stratum อ้างอิง |

แบ่งด้วย seeded shuffle (`POP_SEED = 480906`) — 32 ตัวแรกเป็น validation
**ล็อกก่อนวัดผลใด ๆ**

**L12 ไม่ถูกรวมเข้าประชากร** เพราะเขียนขึ้นจากการเลือกวัดของจริงแบบ hand-picked
การเอามารวมทำให้ประชากรไม่ใช่ตัวอย่างจากการแจกแจงที่ประกาศไว้

### 4.3 ขนาดประวัติที่ทดสอบ (learning curve)

`[50, 100, 500, 1000, 5000]` เหตุการณ์ต่อผู้ใช้ — ชุดฝึกซ้อนกัน (nested subset)
ตัดจากหัวเสมอ เพื่อให้เทียบข้ามขนาดได้อย่างเป็นธรรม

### 4.4 seed ของข้อมูล

`SEEDS_P48 = [301, 302, 303, 304, 305]` — ประกาศไว้ใน pre-registration §2b
**ก่อนมีการวัดใด ๆ**

seed `[101–115]` ถูกใช้ไปแล้วในรอบก่อน · `[201–205]` จองไว้ให้ Round 3
(conditional L3) · เริ่มชุดใหม่ที่ 301

---

## 5. การตรวจสอบคุณภาพข้อมูล

ต้องผ่านทั้งสองข้อนี้ **ก่อน** วัดประสิทธิภาพใด ๆ

### 5.1 ตรวจ leakage

เทียบว่าแถวใน holdout ทับกับ train หรือไม่ โดยเทียบ **ทั้งแถว** (11 ฟิลด์) ไม่ใช่
แค่ timestamp — เคยเจอกรณีเวลาเดียวกันแต่เป็นคนละเหตุการณ์จริง

```
overlapping_rows: 0
holdout_rows:     843,475
clean:            true
```

### 5.2 ตรวจ shortcut (การเรียนทางลัด)

หาฟีเจอร์เดี่ยวที่แยก attack/normal ได้เกือบสมบูรณ์ ซึ่งแปลว่า generator รั่ว

| เกณฑ์ | ค่า |
|---|---|
| separation AUC | > 0.99 → flag |
| coverage | < 0.05 → flag |
| วิธีคำนวณ AUC | Mann-Whitney **แบบ mid-rank จัดการค่าเสมอ** |

> **บั๊กที่เคยเกิด:** ตัวตรวจรุ่นแรกใช้ `ranks[order] = arange(1, N+1)` ซึ่งให้อันดับ
> ต่างกันกับค่าที่เท่ากัน → ฟีเจอร์ที่ฝั่งหนึ่งผูกที่ค่าเดียวทั้งหมด (เช่น attack ทุกแถว
> มี `passkey_last_used_days = 0`) ได้ AUC = 1.0 ปลอม ทั้งที่แยกไม่ได้จริง
> ผลการตรวจ shortcut ของรอบก่อนหน้าจึงเชื่อถือไม่ได้ ต้องตรวจใหม่ทั้งหมด

**ผลบน P48-validation** (5 seeds × 5 sizes = 25 runs, 23 ฟีเจอร์):

```
flagged features: 0
```

ฟีเจอร์ที่แยกได้ดีที่สุด 5 อันดับ:

| feature | auc_max | auc_mean | coverage_min |
|---|---|---|---|
| `log_minutes_since_last_login` | 0.9103 | 0.8921 | 1.0000 |
| `login_count_24h` | 0.9013 | 0.8807 | 0.7401 |
| `day_of_week` | 0.6720 | 0.6683 | 1.0000 |
| `passkey_last_used_days` | 0.6658 | 0.6626 | 1.0000 |
| `hours_from_typical_login_time` | 0.6325 | 0.6180 | 1.0000 |

ตัวสูงสุด 0.9103 ยังห่างจากเกณฑ์ 0.99 และ `coverage = 1.0` แปลว่าค่าของ attack
อยู่ในช่วงของ normal ทั้งหมด — ไม่ใช่การแยกด้วยค่าที่ normal ไม่มีทางได้

### 5.3 การกันไม่ให้ holdout รั่วระหว่างตรวจ

สคริปต์ตรวจ (`audit_p48_generator.py`) เปิดเฉพาะ **P48-validation** และเฉพาะ
split `tune` โดยมี `assert` กันไว้ว่าถ้าหลุดไปสร้างโปรไฟล์ holdout ให้หยุดทันที

---

## 6. วิธีการวัดประสิทธิภาพ

### 6.1 นิยามตัวชี้วัด

| ตัวชี้วัด | นิยาม |
|---|---|
| `surfaced` | decision อยู่ใน {warn, challenge, block} |
| `recall` | สัดส่วน attack ที่ถูก surfaced |
| **`recall_challenge`** | สัดส่วน attack ที่ถูก challenge หรือ block — **ตัวที่ใช้ตัดสิน** |
| `challenge_fpr` | สัดส่วน login **ปกติ** ที่ถูก challenge หรือ block |
| `block_fpr` | สัดส่วน login ปกติที่ถูก block |
| `warn_fpr` | สัดส่วน login ปกติที่ถูก warn |
| `campaign_recall` | สัดส่วนแคมเปญที่ถูกจับได้อย่างน้อยหนึ่งเฟส |

> **ทำไมต้องรายงาน `recall` คู่กับ `recall_challenge` เสมอ** — `recall` นับ `warn` ด้วย
> จุดทำงานจึงดัน `recall` ขึ้นได้ด้วยการเตือนถี่ขึ้นโดยไม่มีอะไรฟ้อง เคยเป็นช่องโหว่จริง
> (งบ warn ถูกประกาศไว้แต่ไม่เคยถูกตรวจ)

### 6.2 หน่วยทดลองคือ "ผู้ใช้" ไม่ใช่ "เหตุการณ์"

เหตุการณ์ของผู้ใช้คนเดียวกันไม่เป็นอิสระต่อกัน — ถ้าโมเดลเข้าใจผู้ใช้คนหนึ่งผิด
มันมักผิดทั้งชุดของเขา การนับเหตุการณ์เป็นหน่วยอิสระจึงให้ช่วงความเชื่อมั่นที่แคบ
เกินจริง

ตัวเลขทุกตัวจึงคำนวณเป็น **per-user rate** ก่อน แล้วจึงสรุประดับประชากร

### 6.3 ช่วงความเชื่อมั่นแบบ cluster-aware

`bootstrap.cluster_rate_ci()` — resample **ผู้ใช้ → seed** (2 ชั้น)

**ไม่ resample ชั้นเหตุการณ์โดยตั้งใจ:** ความแปรปรวนของ binomial ที่ n = 6,000,
p = 0.01 คือ sd 0.13 pp ขณะที่การกระจายระหว่างผู้ใช้ที่วัดได้จริงเกิน 10 pp —
ชั้นในสุดไม่เปลี่ยนผลแต่ทำให้ช้ามาก · ประกาศไว้ในฟิลด์ `levels_resampled`

**กรณี k = 0 ทุก cell:** bootstrap ของศูนย์ล้วนได้ศูนย์เสมอ → ขอบบน 0 ซึ่งหลอกว่า
"เป็นไปไม่ได้เลย" · ใช้ Wilson **ระดับเหตุการณ์** เป็นขอบบนสำรอง พร้อมประกาศ
ข้อจำกัดว่าครอบคลุมเฉพาะผู้ใช้ในตัวอย่าง ไม่เผื่อผู้ใช้ประเภทใหม่

### 6.4 การตัดสินแบบสามทาง

```
passed        ขอบบน CI <= งบ    -> มั่นใจว่าอยู่ในงบ
failed        ขอบล่าง CI > งบ   -> มั่นใจว่าเกินงบ
inconclusive  CI คร่อมงบ        -> ข้อมูลไม่พอตัดสิน
```

`deployable` เป็นจริงเฉพาะ `passed` — **inconclusive = ไม่ deploy (fail-closed)**

> เกณฑ์เดิมเทียบ **ค่าประมาณจุด** กับงบแล้วประกาศ passed/failed ทั้งที่หน่วยอิสระ
> มีเพียง 12 ผู้ใช้ → ค่า 1.18% เทียบงบ 1.0% ถูกประกาศว่า "ไม่ผ่าน" ทั้งที่ CI
> ระดับ cluster คร่อมงบอยู่ ซึ่งเป็นการสรุปเกินหลักฐาน

### 6.5 เกณฑ์ per-size ไม่ใช่ macro

จุดทำงานที่ FPR รวม 0.9% แต่ที่ขนาด 50 อยู่ที่ 4% แปลว่าผู้ใช้ใหม่รับภาระเกินงบ
ทั้งที่ตัวเลขรวมผ่าน → **ต้องผ่านทุกขนาดข้อมูล** (ตัดสิน 4 ก.ย. 2569)

### 6.6 การเปรียบเทียบต้องเป็น paired

CI แบบ unpaired ที่ทับกัน **ไม่ใช่** การทดสอบความแตกต่าง · การเทียบระหว่างสอง
คอนฟิกใช้ `paired_cluster_multi_delta()` ซึ่งวัดทั้งสองอาร์มบนเหตุการณ์ชุดเดียวกัน
แล้ว bootstrap ระดับ cluster บนผลต่าง

### 6.7 การตรวจ calibration ของหาง

**ไม่ใช้ ECE** — ECE เป็นเครื่องมือของ probability prediction แต่ `final_risk_score`
เป็น percentile evidence ไม่ใช่ probability

ใช้แทนด้วย `tailcal.py`:
- `benign_exceedance` — สัดส่วน login ปกติที่ทะลุ p95 / p99 / p99.9
- `pit_uniformity` — KS test บน PIT values

### 6.8 เกณฑ์ที่ **ไม่** ใช้ตัดสิน

`max user FPR <= 1%` — เป็น **order statistic** ที่โตตามจำนวนผู้ใช้โดยธรรมชาติ
ทำให้เกณฑ์เข้มขึ้นเองเมื่อขยายประชากร → ใช้ **mean + CI** และ **p90** เป็นเกณฑ์
และรายงานผู้ใช้ที่เกินงบเป็น **outlier report แยก**

---

## 7. ลำดับการทดลองและสิ่งที่เรียนรู้ระหว่างทาง

### 7.1 Round 1 — ไม่ผ่าน gate

- candidate: Config B · holdout seeds `[42–46]`
- **ผล:** block FPR 0.25% เกินงบ 0.20% → `final_round_1_failed_gate`
- Config F ผ่านงบ แต่ **ห้ามเลือกแบบ post-hoc** — การเลือก config ที่ผ่านหลังเห็นผล
  ทำลายความหมายของ holdout

### 7.2 Round 2 / 2b / 2c — ปรับ threshold สามรอบ ไม่สำเร็จ

| รอบ | holdout seeds | สิ่งที่ปรับ | ผล challenge FPR @50 |
|---|---|---|---|
| 2 | `[101–105]` | ยก block threshold เป็น 0.9999 | ไม่ผ่าน |
| 2b | `[106–110]` | ยก warn เป็น 0.98 | 1.23% |
| 2c | `[111–115]` | ยก challenge เป็น 0.995 | 1.18% |

**บทเรียนวิธีวิทยา (B69):** รอบ 2c เคยสรุปว่า "threshold tuning หมดทาง" จากการเทียบ
1.23% (2b) กับ 1.18% (2c) ซึ่งเป็น **holdout คนละประชากร** — เป็นการเทียบที่มีตัวแปรกวน
ข้อสรุปถูกแก้และบันทึกไว้ในรายงานรอบนั้น

### 7.3 ผลของ L3 ตลอดทุกรอบ

L3 ให้ within-config counterfactual unique 9–17% ที่ระดับเหตุการณ์ แต่
**ΔCampaignRecall ≈ 0** — L3 ไม่เพิ่มการตรวจจับระดับแคมเปญ

> ชื่อตัวชี้วัดถูกเปลี่ยนจาก `l3_effective_unique` เป็น
> `within_config_l3_counterfactual_unique` เพราะชื่อเดิมทำให้อ่านว่า "L3 เพิ่มการ
> ตรวจจับ 12.7%" ทั้งที่ recall สุทธิลดลง 8.35 pp

### 7.4 การวินิจฉัยต้นเหตุ — ความแปรปรวนระดับผู้ใช้

ตั้งสมมติฐานสามข้อแล้ววัดทีละข้อ:

| สมมติฐาน | ผล |
|---|---|
| H1: population variance ของ seed | **หักล้าง** — ทุก seed ใช้โปรไฟล์ชุดเดิม |
| H2: split/time effect | **หักล้าง** — บล็อกที่ใกล้ calibration กว่ากลับให้ FPR สูงกว่า (4/5 seed) |
| H3: ความแปรปรวนระดับผู้ใช้ | **ยืนยัน** |

หลักฐาน H3 (challenge FPR ราย user @ size 50):

| user | s46 tune | s46 testA | s44 testA |
|---|---|---|---|
| **U01** | 4.00% | **16.20%** | **11.20%** |
| ที่เหลือ | ≤ 1.20% | ≤ 3.20% | ≤ 3.20% |

U01 คนเดียวกิน **61.8%** (s46) และ **63.6%** (s44) ของ FPR ทั้งหมด

**กลไก:** 78 จาก 81 เหตุการณ์ที่ U01 ถูก challenge มาจาก `new_subsystem` +
`scope_escalation` ยิงพร้อมกัน เพราะชุดฝึก 50 เหตุการณ์ของ U01 มีแต่ HUB ทั้งที่
โปรไฟล์จริงคือ HUB 0.9 / SUB_A 0.1 → ทุก login เข้า SUB_A (10.6% ของ holdout)
ถูกตีเป็น "ระบบที่ไม่เคยใช้"

### 7.5 การทดลองที่ให้ผลลบ — L2 subsystem novelty family

ทดลองรวมสองสัญญาณเป็นตระกูลเดียว (`max` แทนผลรวม) พร้อมถ่วงน้ำหนักตามขนาด
ประวัติ (rule-of-three confidence heuristic) · กวาดกริดสองรอบบน validation

**ผล paired delta เทียบ legacy** (จุดที่ดีที่สุด `w0.5_floor0.4`):

| ขนาด | ΔchallengeFPR | ΔRecall@challenge |
|---|---|---|
| 50 | −0.080 pp `[−0.293, +0.000]` | **−0.0060 `[−0.0142, −0.0009]`** |
| 500 | +0.000 pp `[+0.000, +0.000]` | −0.0013 `[−0.0073, +0.0043]` |

**ΔFPR ทุกช่วงแตะหรือคร่อมศูนย์** (แยกไม่ออกจากศูนย์) แต่ **ΔRecall ที่ cold start
ไม่คร่อมศูนย์** (ความเสียหายมีนัยจริง) · `subtle_quiet_lateral` ตก 6.7 pp คงที่ทุกขนาด

**ข้อค้นพบสำคัญ:** `max` แทนผลรวม **ไม่มีผลใด ๆ** — ให้ตัวเลขเท่าเดิมทุกหลัก เพราะ
ECDF เป็น **อันดับ** การลดคะแนนของทุกเหตุการณ์ในตระกูลลงเท่า ๆ กันไม่เปลี่ยน
เปอร์เซ็นไทล์ → เหตุผลที่ใช้ออกแบบ ("การนับหลักฐานซ้ำคือต้นเหตุ") **ไม่ถูกต้อง**

โค้ดถูกถอนออกจาก production แล้ว มี parity test พิสูจน์ว่าคะแนนเท่าเดิม 400 เคสสุ่ม
(ต่างสูงสุด < 1e-12) · ตัวแปรที่ถูกปฏิเสธเก็บไว้ใน
`hybrid_experiment/l2_family_variant.py` เพื่อให้ผลลบทำซ้ำได้

### 7.6 บั๊กเชิงวิธีวิทยาที่บันทึกไว้

| # | บั๊ก | ผลกระทบ |
|---|---|---|
| B66 | harness เรียก `aggregate(rule, beh, NEUTRAL)` แต่ production เรียกด้วยคะแนนจริง | 12.5% ของการตัดสินจริงถูกกำหนดโดยชั้นที่การทดลองวัดว่าไม่มีส่วนร่วม |
| B67 | SHAP เสื่อม **ก่อน** คะแนนอิ่มตัว — พังพอดีในย่านที่ใช้งานจริง | เปลี่ยนไปใช้ robust deviation `(x−median)/IQR` |
| B68 | optimize ความเร็วของ `final` เผลอเปิด holdout ซ้ำ | เพิ่ม holdout ledger บันทึกถาวรว่า seed ใดเปิดแล้ว |
| B69 | สรุปผลจากการเทียบสอง holdout คนละประชากร | แก้ข้อสรุป Round 2c |
| B70 | `BehaviorResult.min_action` ประกาศว่าเป็น policy floor แต่ไม่เคยมีผล | ตัดฟิลด์ทิ้ง + เทสบังคับ evidence-only |

---

## 8. ผลการวัดฉบับล่าสุด

### 8.1 การตั้งค่า

- **P48-validation 32 โปรไฟล์** × seeds `[301..305]` × sizes `[50..5000]`
- split `tune` เท่านั้น · **holdout 16 โปรไฟล์ไม่ถูกเปิด**
- Config B ใช้ gamma = 1.0 และ threshold ที่ freeze ไว้ `{warn 0.98, challenge 0.995, block 0.9999}`
- ผ่าน shortcut/leakage audit แล้ว
- ขนาดตัวอย่างที่ size 50: **80,000 เหตุการณ์ปกติ · 32 ผู้ใช้**

### 8.2 ผลหลัก — Config B (candidate)

| size | mean | cluster CI | median | p90 | เกินงบ | verdict |
|---|---|---|---|---|---|---|
| 50 | 0.871% | [0.620, 1.176] | 0.640% | 1.920% | 9/32 | **inconclusive** |
| 100 | 0.809% | [0.574, 1.105] | 0.640% | 1.800% | 7/32 | inconclusive |
| 500 | 0.841% | [0.593, 1.142] | 0.640% | 1.800% | 9/32 | inconclusive |
| 1000 | 0.792% | [0.557, 1.085] | 0.600% | 1.640% | 9/32 | inconclusive |
| 5000 | 0.802% | [0.565, 1.101] | 0.640% | 1.640% | 10/32 | inconclusive |

ระดับอื่น (size 50):

| ระดับ | mean | CI | งบ | verdict |
|---|---|---|---|---|
| block | 0.005% | [0.000, 0.015] | 0.20% | **passed** |
| warn | 2.295% | [1.669, 3.114] | 5.00% | **passed** |

### 8.3 Baseline (Config A) ไม่ผ่านทุกขนาด

| size | mean | cluster CI | เกินงบ | verdict |
|---|---|---|---|---|
| 50 | 3.561% | [2.565, 4.741] | 29/32 | **failed** |
| 500 | 2.794% | [2.236, 3.475] | 30/32 | failed |
| 5000 | 2.670% | [2.144, 3.269] | 30/32 | failed |

block ก็ไม่ผ่าน: 1.010% [0.404, 1.766] เทียบงบ 0.20%

**Hybrid ลด challenge false positive ลงราว 4 เท่า**

### 8.4 การกระจาย per-user FPR (Config B)

| size | min | q25 | median | q75 | p90 | max |
|---|---|---|---|---|---|---|
| 50 | 0.04% | 0.44% | 0.64% | 1.32% | 1.92% | 3.40% |
| 5000 | 0.00% | 0.36% | 0.64% | 1.20% | 1.64% | 3.40% |

**outlier report** — ผู้ใช้ที่เกินงบ 1% ที่ size 50 (9/32 คน · ไม่ใช้เป็นเกณฑ์ตัดสิน):

```
P15 3.40%   P07 2.08%   P48 2.04%   P14 1.92%   P25 1.80%
P32 1.60%   P41 1.48%   P37 1.32%   P16 1.32%
```

ไม่มีใครแตะระดับ 16% แบบ U01 อีก — ตัวสูงสุด 3.40%

### 8.5 ผลที่กลับข้อสรุปของสามรอบก่อนหน้า

| ประชากร | chFPR @50 | @5000 | อัตราส่วน |
|---|---|---|---|
| L12 (12 โปรไฟล์, holdout) | 1.18–1.23% | ~0.61% | ~2.0× |
| **P48-validation (32 โปรไฟล์)** | **0.871%** | **0.802%** | **1.09×** |

ความชันตามขนาดประวัติแทบหายไป → ปัญหา "cold-start FPR" ที่ไล่ตามมาสามรอบ
**ส่วนใหญ่เป็นคุณสมบัติของประชากร 12 คน ไม่ใช่ของระบบ**

ช่วงความเชื่อมั่นแคบลงตามจำนวนหน่วยทดลอง: `[0.31, 0.96]` (12 คน) → `[0.62, 1.18]` (32 คน)

### 8.6 L12-reference stratum — ประชากรเล็กลำเอียงไปทางดี

วัดด้วยโค้ดชุดเดียวกันเป๊ะ บน seeds `[301..305]` เหมือนกัน:

| size | L12 (12 คน) | P48 (32 คน) | verdict L12 | verdict P48 |
|---|---|---|---|---|
| 50 | 0.693% [0.363, 1.090] | 0.871% [0.620, 1.176] | inconclusive | inconclusive |
| 500 | 0.560% [0.310, 0.863] | 0.841% [0.593, 1.142] | **passed** | inconclusive |
| 5000 | 0.477% [0.280, 0.683] | 0.802% [0.565, 1.101] | **passed** | inconclusive |

ที่ size 5000 ต่างกัน **1.68 เท่า** และ L12 "ผ่าน" เกือบทุกขนาดขณะที่ P48 ไม่ผ่านเลย

**ถ้าไม่ขยายประชากร เราจะสรุปว่าระบบผ่านงบทั้งที่ยังไม่ผ่าน** — ประชากรเล็กไม่เพียง
มีความแปรปรวนสูง แต่ยัง **ลำเอียงไปทางดี** อย่างเป็นระบบด้วย

### 8.7 Recall แยก attack family

> **คำเตือน: ไม่ใช่การเทียบที่เป็นธรรม** — Config A challenge บ่อยกว่า Config B
> ประมาณ 4 เท่า recall ที่สูงกว่าจึงส่วนหนึ่งมาจากการยิงถี่กว่า ไม่ใช่ความสามารถ
> ในการแยกแยะ · การเทียบที่ FPR เท่ากันทำกับ Config A ไม่ได้ เพราะพื้น FPR ของมัน
> วัดไว้ที่ 1.2467% ซึ่งสูงกว่างบ 1% อยู่แล้วเชิงโครงสร้าง

| family | n | A@50 | B@50 | B@5000 |
|---|---|---|---|---|
| combined_ato | 320 | 1.0000 | 1.0000 | 1.0000 |
| concurrent_sessions | 320 | 1.0000 | 1.0000 | 1.0000 |
| failed_spike | 320 | 1.0000 | 1.0000 | 1.0000 |
| new_device | 320 | 1.0000 | 1.0000 | 1.0000 |
| new_os | 320 | 1.0000 | 1.0000 | 1.0000 |
| new_ua_family | 320 | 1.0000 | 1.0000 | 1.0000 |
| permission_change | 160 | 1.0000 | 1.0000 | 1.0000 |
| subtle_lowandslow | 320 | 0.9406 | 0.9344 | 0.9313 |
| off_hours | 320 | 0.9563 | 0.8844 | 0.8844 |
| subtle_mild_offhour | 320 | 0.8281 | 0.8094 | 0.8031 |
| subsystem_lateral | 160 | 1.0000 | 0.7875 | 0.7812 |
| subtle_quiet_lateral | 320 | 0.9250 | 0.6406 | 0.6375 |
| login_velocity | 320 | 1.0000 | 0.4188 | 0.3937 |
| campaign | 1600 | 0.5781 | 0.3725 | 0.3013 |
| subtle_slow_burst | 320 | 0.9781 | 0.2719 | 0.2594 |
| subtle_rare_device | 230 | 0.8130 | 0.2565 | 0.2217 |
| new_passkey | 320 | 0.8812 | 0.2437 | 0.2281 |

7 ตระกูลที่ Config B จับได้ครบ 100% เป็นตระกูลที่มี **policy floor** รองรับ ·
ตระกูลที่พึ่งคะแนนล้วนตกลงมามาก — เป็นราคาที่จ่ายเพื่อ FPR ที่ต่ำกว่า 4 เท่า

### 8.8 คำตัดสิน

challenge ได้ **inconclusive ทุกขนาด** — ค่าจุดอยู่ใต้งบ (0.79–0.87%) แต่ขอบบนของ
CI เกิน (1.09–1.18%) ข้อมูลจาก 32 ผู้ใช้ × 5 seeds **ยังแยกไม่ออก**

ตาม pre-registration:
- `inconclusive` = ไม่ deploy (fail-closed)
- เปิด holdout ได้เฉพาะเมื่อ validation ผ่าน → **ยังไม่เปิด**
- ถ้าไม่ผ่าน หยุดที่ Shadow ห้ามปรับ threshold ต่อ

**สถานะระบบ: Hybrid RBA + L3 คง Shadow · การตัดสินการเข้าถึงจริงใช้ policy /
baseline ที่อนุมัติไว้เดิม**

---

## 9. การทดสอบซอฟต์แวร์

### 9.1 กระบวนการ TDD

ทุก feature ทำตาม RED → GREEN → REFACTOR โดยต้อง paste output จริงทุกเฟส
ห้าม commit ถ้าเทสยังไม่ผ่านทุกตัว

ตัวอย่างเฟส RED ที่เกิดขึ้นจริงในรอบนี้:

```
FAILED tests/test_cluster_aware_gate.py::test_point_estimate_equals_pooled_ratio
... (12 failed — AttributeError: module has no attribute 'cluster_rate_ci')

E   ImportError: cannot import name 'gate' from 'hybrid_experiment'
E   ModuleNotFoundError: No module named 'population_p48'
```

> **บทเรียน:** รอบแรกใช้ `pytest.importorskip("population_p48")` ทำให้เทสทั้งไฟล์
> **skip แทนที่จะ fail** ตอนโมดูลยังไม่มี — กลืนเฟส RED ไปทั้งชุด · แก้ให้ skip เฉพาะ
> เมื่อไม่มี harness เลย (กรณีรันในคอนเทนเนอร์) ส่วนกรณีมี harness แต่โมดูลหายต้อง fail

### 9.2 ผลการทดสอบล่าสุด

```
docker compose exec hub-backend pytest . -q
  947 passed, 60 skipped in 158.20s
```

เทสฝั่ง host (harness ของ ml-service ซึ่ง skip ในคอนเทนเนอร์):

```
77 passed
  test_population_p48.py         22 เทส
  test_cluster_aware_gate.py     18 เทส
  test_round2_statistics.py      25 เทส
  test_l2_subsystem_family.py    11 เทส
  test_l2_legacy_mode_parity.py   1 เทส (400 เคสสุ่ม)
```

### 9.3 เทสที่คุ้มครองความถูกต้องของ**วิธีวัด** (ไม่ใช่แค่ของโค้ด)

| ไฟล์ | สิ่งที่คุ้มครอง |
|---|---|
| `test_population_p48.py` | ประชากรตรงกับ pre-registration ทุกฟิลด์ · การแบ่ง 32/16 ล็อกไว้ · roster ไม่แตะอีเมลบุคคลจริง |
| `test_cluster_aware_gate.py` | CI เคารพ clustering · verdict สามทาง · inconclusive = fail-closed · k=0 ต้องไม่ให้ขอบบน 0 |
| `test_round2_statistics.py` | paired bootstrap · hierarchical CI · tail calibration · ชื่อ metric ต้องไม่สื่อเกินหลักฐาน |
| `test_scoring_freeze.py` | scoring logic ต้องไม่ขยับระหว่างรอบทดลอง |
| `test_l2_evidence_only.py` | L2 คืนหลักฐานเท่านั้น ไม่มีฟิลด์ในแกน access decision (B70) |
| `test_l2_legacy_mode_parity.py` | การตัดฟิลด์ที่ตายแล้วไม่กระทบคะแนน (400 เคสสุ่ม ต่าง < 1e-12) |
| `test_evidence_contract.py` | ชั้นหลักฐานไม่รู้จัก L4 · L4 เป็นผู้ตัดสินจุดเดียว |

### 9.4 ข้อจำกัดของชุดเทส

มี 2 ไฟล์ที่ `sys.exit()` อยู่นอก `if __name__ == "__main__"` (`test_e2e_full_stack.py`,
`test_l1_oidc.py`) ทำให้ `pytest .` ล้มทั้งชุดตอน collect — ต้อง `--ignore` ทั้งสองไฟล์
เป็นปัญหาเดิมของ repo ที่ควรแก้แยก

---

## 10. กลไกรักษาความซื่อตรงของกระบวนการ

### 10.1 Pre-registration

ประกาศประชากร การแจกแจงทุกฟิลด์ การแบ่ง seed และเกณฑ์รายงาน **ก่อนเขียน generator**
และ commit เอกสารก่อน · การแก้ทุกครั้งบันทึกเป็น amendment พร้อมเหตุผลและวันที่

### 10.2 Holdout ledger (B68)

`holdout_ledger.json` บันทึกถาวรว่า seed ชุดใดถูกเปิดไปแล้ว → ปฏิเสธการเปิดซ้ำ
เว้นแต่ใส่ `--reopen-spent-holdout` อย่างตั้งใจ (ห้ามลบ entry)

ปัจจุบันบันทึกไว้ 3 ชุด: `[101–105]`, `[106–110]`, `[111–115]` ·
**P48-holdout ยังไม่มีใน ledger เพราะไม่เคยถูกเปิด**

### 10.3 Scoring freeze

`hub/backend/tests/scoring_freeze.json` เก็บ sha256 (normalize CRLF→LF) ของไฟล์ที่
ตัดสินคะแนน/การเข้าถึงทั้ง 10 ไฟล์ พร้อม commit เหตุผล และเงื่อนไขปลด freeze ·
`test_scoring_freeze.py` ฟ้องทันทีถ้าไฟล์ใดขยับ

พิสูจน์ทั้งสองทาง (บทเรียน B61): เติมบรรทัดใน `risk_fusion.py` แล้วเทส fail จริง
จากนั้นคืนไฟล์แล้วผ่านครบ

**ขอบเขต:** freeze เฉพาะตรรกะการตัดสิน · generator และ harness ไม่ถูก freeze
เพราะต้องแก้เพื่อเพิ่มโปรไฟล์ผู้ใช้

### 10.4 Evidence manifest

`docs/RBA_EVIDENCE_MANIFEST_2026-09-08.md` — hash ของไฟล์หลักฐาน 89 รายการ
(รายงาน + โค้ดที่ผลิตตัวเลข + เอกสารกำกับวิธีวิทยา) พร้อม commit และ tag

**manifest แต่ละรอบเป็นคนละไฟล์ ห้ามเขียนทับ** เพราะ tag เก่าอ้างไฟล์นั้นอยู่

> **บั๊กที่แก้ในรอบนี้:** `--verify` เดิมตรวจจาก **รายการไฟล์ปัจจุบัน** ไม่ใช่จากสิ่งที่
> manifest บันทึกไว้ → พอรอบใหม่เพิ่มไฟล์ manifest เก่าจะ verify ไม่ผ่านตลอดกาล
> ทั้งที่ไฟล์ของรอบนั้นไม่ได้ถูกแก้เลย ซึ่งทำลายจุดประสงค์ของ manifest

### 10.5 Scoring fingerprint

`frozen_config.json` เก็บ hash ของไฟล์ที่ "ถ้าแก้แล้วตัวเลขเปลี่ยน" 21 ไฟล์ และ
`cmd_final` ปฏิเสธการเปิด holdout ถ้า hash ไม่ตรง

### 10.6 นโยบายข้อมูลส่วนบุคคล

| ประเภท | ที่อยู่ | เหตุผลที่ไม่ขึ้น git |
|---|---|---|
| โปรไฟล์ผู้ใช้จริง (anchor) | `ml-service/data/*.xlsx` | PII — อีเมล/ชื่อ/แผนก |
| login ที่ generate จาก anchor | `ml-service/data/*.csv` | สาวกลับหาบุคคลได้ |
| roster (alias → email) | `ml-service/data/roster_*.json` | ผูก alias กับตัวตน |
| ฟีเจอร์/โมเดลรายคน | `ml-service/models/` | derived จาก PII |

pre-commit hook `block-real-pii` ตรวจจับอีเมลโดเมนจริงในไฟล์ที่จะขึ้น git —
ในรอบนี้จับ placeholder ที่ผู้เขียนใช้โดเมนจริงได้จริง และถูกแก้เป็นโดเมนสงวน
ตาม RFC 2606

---

## 11. ข้อจำกัด

### 11.1 ตัวเลขทั้งหมดมาจาก split `tune`

split `test` ภายในผู้ใช้และโปรไฟล์ holdout 16 คนยังไม่ถูกเปิด · จากรอบก่อนมีจุด
สอบเทียบเดียวว่า tune ให้ค่าต่ำกว่า holdout ราว 1.70 เท่า

> ตัวเลขนี้เป็นการเทียบ **ข้าม seed และข้าม split** จึงเป็นการประมาณคร่าว ๆ ไม่ใช่
> ค่าที่วัดได้โดยตรง (ความผิดพลาดแบบเดียวกับ B69) · ถ้าอัตราส่วนใกล้เคียงกันจริง
> P48 บน holdout จะอยู่ราว 1.5% ซึ่งเกินงบ

**นัยสำคัญ:** ความกว้างของ CI เป็นปัญหา **variance** ซึ่งแก้ได้ด้วยการเพิ่มหน่วยทดลอง
แต่ความต่างระหว่าง tune กับ holdout เป็นปัญหา **bias** ซึ่ง **การเพิ่ม seed แก้ไม่ได้**

### 11.2 ข้อมูลเป็นข้อมูลสังเคราะห์

การแจกแจงของประชากร P48 เป็น **การประกาศ ไม่ใช่การวัด** — ช่วงค่าอ้างอิงจาก
12 โปรไฟล์ที่วัดจากของจริงแล้วขยายให้กว้างขึ้น · ความสมจริงของการแจกแจงนี้เป็น
ข้อจำกัดที่ผู้จัดทำระบุเอง

### 11.3 การเทียบ recall กับ baseline ไม่เป็นธรรม

baseline challenge ถี่กว่า 4 เท่า และเทียบที่ FPR เท่ากันทำไม่ได้เพราะพื้น FPR ของ
baseline อยู่ที่ 1.2467% ซึ่งเกินงบอยู่แล้วเชิงโครงสร้าง

### 11.4 การนับ `inconclusive` เป็นไม่ผ่านเป็นการตัดสินเชิงนโยบาย

ไม่ใช่เชิงสถิติ — ผู้ตรวจอาจเห็นต่างว่าค่าจุด 0.87% ที่ต่ำกว่างบควรถือว่าผ่าน

### 11.5 Amendment #2 แก้หลังเห็น validation

แม้จะพิสูจน์ได้จากการอ่านกฎ policy floor โดยไม่ต้องดูตัวเลขประสิทธิภาพ และแก้
ก่อนเปิด holdout แต่ยังเป็นการแก้ pre-registration ระหว่างทาง

### 11.6 L3 ยังไปไม่ถึงเกณฑ์ที่จะมีประโยชน์ใน deployment จริง

ข้อจำกัด tier reachability — ผู้ใช้จริงต้องสะสม history ราว 1.7 ปีจึงจะถึงเกณฑ์

---

## 12. สรุปและงานต่อยอด

### 12.1 สิ่งที่พิสูจน์ได้

1. **Hybrid RBA ลด false positive ได้จริงและมาก** — 3.561% → 0.79–0.87% (ราว 4 เท่า)
   baseline ไม่ผ่านงบทั้งใน challenge และ block ที่ทุกขนาดข้อมูล
2. **block และ warn ผ่านงบอย่างชัดเจน** — block 0.005% (งบ 0.20%) · warn 2.295% (งบ 5.00%)
3. **ปัญหา cold-start FPR ที่ไล่ตามมาสามรอบเป็นคุณสมบัติของประชากรตัวอย่าง**
   ไม่ใช่ของระบบ
4. **ประชากรขนาดเล็กลำเอียงไปทางดีอย่างเป็นระบบ** — เป็นข้อค้นพบเชิงวิธีวิทยาที่
   ใช้ได้กับงานประเมิน RBA ทั่วไป ไม่เฉพาะระบบนี้

### 12.2 สิ่งที่ยังพิสูจน์ไม่ได้

**challenge FPR อยู่ในงบ 1% หรือไม่** — ข้อมูล 32 ผู้ใช้ × 5 seeds ยังแยกไม่ออก

### 12.3 สถานะระบบ

| องค์ประกอบ | สถานะ |
|---|---|
| Hybrid RBA (4 ชั้น) + L3 | **Shadow** — ให้คะแนนและบันทึก ไม่ตัดสินสิทธิ์ |
| การตัดสินการเข้าถึงจริง | policy / baseline ที่อนุมัติไว้เดิม |
| P48-holdout 16 โปรไฟล์ | **ไม่เคยเปิด** สงวนไว้สำหรับ external validation |
| P48-T2-holdout 16 โปรไฟล์ | **ไม่เคยเปิด** · challenge ของรอบ P48-T2 ก็ได้ `inconclusive` ทุกขนาด |
| Expert Label Workflow (backend) | พร้อมสำหรับ integration testing แต่ยังไม่เปิดใช้งาน operational review บน production · ยังไม่มี UI / retention · ยังไม่คำนวณ production FPR |

### 12.4 งานต่อยอด

1. **เปิด P48-holdout** เมื่อมีหลักฐานว่า validation ผ่าน — เป็นการวัดครั้งเดียว
   ที่ยังบริสุทธิ์อยู่
2. **ประเมินบน traffic จริง** ในโหมด Shadow เพื่อสอบเทียบว่าตัวเลขจากข้อมูล
   สังเคราะห์ตรงกับของจริงแค่ไหน
3. **ลดช่องว่าง tune → holdout** ซึ่งเป็นปัญหา bias ที่การเพิ่ม seed แก้ไม่ได้
4. **ขยายประชากรต่อ** ถ้าต้องการ CI ที่แคบพอจะตัดสินได้ — แต่ต้องประกาศจำนวน
   ล่วงหน้าให้ตายตัว และยอมรับผลไม่ว่าออกทางไหน (กัน optional stopping)
5. **Round 3 — conditional L3 fusion** จองโปรไฟล์/seed ไว้แล้วที่ `[201–205]`

---

## 13. ภาคผนวก — วิธีทำซ้ำ

### 13.1 ลำดับคำสั่ง

```bash
# 1. ตรวจว่าไฟล์หลักฐานยังตรงกับ manifest
python scripts/build_evidence_manifest.py --verify \
    --manifest docs/RBA_EVIDENCE_MANIFEST_2026-09-08.md

# 2. สร้างประชากร + roster (เขียนลง ml-service/data ซึ่ง gitignored)
python ml-service/scripts/population_p48.py

# 3. ตรวจ shortcut / leakage ของ generator — ต้องผ่านก่อนวัดใด ๆ
python ml-service/scripts/audit_p48_generator.py

# 4. วัด Config B + baseline บน validation เท่านั้น
python ml-service/scripts/exp_p48_validation.py

# 5. stratum อ้างอิง 12 โปรไฟล์เดิม (โค้ดวัดชุดเดียวกัน)
python ml-service/scripts/exp_p48_validation.py --population l12 \
    --out ../data/hybrid_experiment/l12_reference.json

# 6. ชุดเทส
docker compose exec hub-backend pytest . -q \
    --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
```

**ข้อมูลจริงไม่อยู่ใน git** — ผู้ตรวจต้องใช้ anchor ของตนเองแล้วส่งผ่าน `--users`
ทุกสคริปต์รับ `--users`, `--seeds`, `--sizes` เป็นอาร์กิวเมนต์

### 13.2 ไฟล์หลักฐาน

**รายงานการทดลอง** (`hub/backend/tests/reports/`)

| ไฟล์ | เนื้อหา |
|---|---|
| `hybrid_risk_experiment_2026-09-03.md` | Round 1 — failed gate |
| `round2_statistics_2026-09-03.md` | paired bootstrap · hierarchical CI · tail calibration |
| `hybrid_risk_round2_2026-09-04.md` | Round 2 — failed gate + B68 |
| `hybrid_risk_round2b_2026-09-04.md` | Round 2b — holdout ชุดใหม่ |
| `hybrid_risk_round2c_2026-09-04.md` | Round 2c + บันทึกแก้ข้อสรุปที่เกินหลักฐาน (B69) |
| `cold_start_fpr_rootcause_2026-09-06.md` | วินิจฉัยต้นเหตุ |
| `cluster_aware_gate_2026-09-06.md` | cluster-aware FPR + verdict สามทาง |
| `l2_subsystem_family_grid_2026-09-06.md` | ผลลบของ L2 family |
| `p48_population_and_audit_2026-09-08.md` | ประชากร P48 + ตรวจ shortcut/leakage |
| `p48_validation_2026-09-08.md` | **ผลหลัก (freeze)** |

**เอกสารกำกับวิธีวิทยา** (`docs/`)

| ไฟล์ | เนื้อหา |
|---|---|
| `design/USER_POPULATION_P48_PREREG.md` | pre-registration + amendment ทั้งหมด |
| `design/L2_SUBSYSTEM_NOVELTY_FAMILY.md` | ออกแบบที่ถูกปฏิเสธ |
| `RBA_ROUND2_PROTOCOL.md` | โปรโตคอลของ Round 2 |
| `RBA_EVIDENCE_MANIFEST_2026-09-08.md` | manifest 89 รายการ |
| `RBA_EXPERT_REVIEW_PACK_2026-09-08.md` | ชุดส่งผู้เชี่ยวชาญตรวจ |
| `bugs-encountered.md` | B1–B70 พร้อมกฎที่ได้จากแต่ละบั๊ก |

**โค้ดที่ผลิตตัวเลข**

```
ml-service/scripts/population_p48.py              ประชากร + split + roster
ml-service/scripts/audit_p48_generator.py         shortcut / leakage audit
ml-service/scripts/exp_p48_validation.py          การวัดหลัก
ml-service/scripts/exp_hybrid_gate.py             harness ของ hybrid gate
ml-service/scripts/exp_l2_family_grid.py          กริดที่ให้ผลลบ
ml-service/scripts/gen_v3.py                      generator เหตุการณ์
ml-service/scripts/build_profiles_v2.py           โปรไฟล์ L12 + attack packs
ml-service/scripts/hybrid_experiment/bootstrap.py cluster_rate_ci + rate_verdict
ml-service/scripts/hybrid_experiment/gate.py      ตรรกะการตัดสินสามทาง
ml-service/scripts/hybrid_experiment/dataset.py   การแบ่ง 4 ส่วน + ECDF
ml-service/scripts/hybrid_experiment/tailcal.py   tail calibration
```

**สคริปต์วินิจฉัย**

```
ml-service/scripts/diag_split_distance.py       FPR ต่อ block ย่อยของ test
ml-service/scripts/diag_user_concentration.py   FPR ราย user ต่อ block
ml-service/scripts/diag_u01_burst.py            องค์ประกอบของการตัดสิน
ml-service/scripts/diag_beh_reasons.py          เหตุผลของ L2 + การกระจายคะแนน
ml-service/scripts/diag_u01_profile.py          ความครอบคลุมของโปรไฟล์
```

### 13.3 tag ที่เกี่ยวข้อง

| tag | คืออะไร |
|---|---|
| `rba-freeze-2026-08-29` | ผลการทดลองรอบ L3 ถูก freeze |
| `rba-expert-review-2026-09-01-r2` | ส่งตรวจรอบ 2 แก้ไขครั้งที่ 1 |
| `rba-hybrid-round1-failed-gate-2026-09-03` | Hybrid gate รอบ 1 — ไม่ผ่าน |
| **`p48-validation-inconclusive`** | **รอบนี้** — ประเมินบน 48 โปรไฟล์ · challenge = inconclusive |
