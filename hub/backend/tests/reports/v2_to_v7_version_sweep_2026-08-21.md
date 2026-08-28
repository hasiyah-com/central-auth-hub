# ไล่ทดสอบโมเดล V2 → V7 — จุดที่ตัวเลขกระโดด และเหตุผลที่แท้จริง

**วันที่:** 21 ส.ค. 2026
**ฐาน:** `agent/rba-user-learning-curve-contracts` commit `b45c350`
**วิธี:** รันทุกเวอร์ชัน **2 รอบด้วย config เดียวกันเป๊ะ** (`size 5000, seed 42, normal_staggered`)
บน generator เดิม (`orig`) และ generator ที่แก้ `success_10m` แล้ว (`fixed`)

---

## สรุป 4 บรรทัด

1. **จุดกระโดดอยู่ที่ V6 ไม่ใช่ V7** — recall 4.4% → 84.6% จากการเปลี่ยน **one-class → supervised**
2. **bug `success_10m` มีจริงแต่ผลน้อย** — แก้แล้ว V6 ตกแค่ 5.2 จุด (84.6% → 79.4%)
3. **ปัญหาจริงคือ generalization** — V6 ได้ ROC-AUC **0.996 บนข้อมูลตัวเอง** แต่ **0.64 บนชุด V2**
4. **สาเหตุ: "normal" ของ generator สม่ำเสมอเกินจริง** จน attack ที่นิยามด้วย "การไต่ขึ้น" แยกออกง่ายเกินไป

---

## 1. ตัวเลขที่แต่ละเวอร์ชันรายงานไว้ (จาก DOCX)

| เวอร์ชัน | สถาปัตยกรรม | Event recall | Precision | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|
| V4 | sequence prototype | 7.29% | N/A | N/A | N/A |
| V5 | **one-class** IsolationForest | 8.65% | 76.28% | 82.08% | 66.50% |
| **V6** | **supervised** RandomForest | **90.90%** | 97.80% | 99.75% | 98.88% |
| V7 | ห่อ V6 เป็น bundle (ไม่เปลี่ยนโมเดล) | 90.90% | 97.80% | 99.75% | 98.88% |

V7 เขียนเองว่า *"บรรจุ V6 เป็น joblib bundle"* → **การกระโดด 10.5 เท่าเกิดที่ V6**
รายงาน V6 ระบุการเปลี่ยนแปลงเพียง *"เพิ่ม Random Forest sequence layer"* โดยไม่อธิบายว่าทำไมถึงกระโดดขนาดนั้น

---

## 2. ผลรันซ้ำ — orig vs fixed (config เดียวกัน)

| เวอร์ชัน | metric | orig | fixed | ต่าง |
|---|---|---|---|---|
| **V3** | evasive_challenge_recall | 1.0000 | 1.0000 | 0 |
| | known_policy_success | 1.0000 | 1.0000 | 0 |
| | challenge_fpr | 0.0015 | 0.0014 | −0.0001 |
| **V4** | event_challenge_recall | 0.0441 | 0.0699 | +0.026 |
| | sequence_detection_rate | 0.1176 | 0.2059 | **+0.088** |
| | challenge_fpr | 0.0741 | 0.0720 | −0.002 |
| **V5** | event_challenge_recall | 0.0441 | 0.0515 | +0.007 |
| | roc_auc | 0.8096 | 0.8279 | +0.018 |
| | pr_auc | 0.1214 | 0.1877 | +0.066 |
| **V6** | **event_challenge_recall** | **0.8456** | **0.7941** | **−0.052** |
| | precision | 0.8519 | 0.8471 | −0.005 |
| | **roc_auc** | **0.9959** | **0.9955** | **−0.0004** |
| | pr_auc | 0.9141 | 0.8878 | −0.026 |
| | sequence_detection_rate | 0.9853 | 0.9853 | 0 |

> ⚠️ ตัวเลขเหล่านี้เทียบกับตัวเลขในรายงาน DOCX ตรงๆ **ไม่ได้** เพราะรายงานใช้ค่าเฉลี่ย 60 runs
> (6 sizes × 5 seeds × 2 scenarios) ส่วนนี่คือ 1 run — แต่**เทียบ orig กับ fixed กันเองได้**
> เพราะต่างกันแค่ generator ทุกอย่างอื่นเหมือนกันหมด

---

## 3. ข้อค้นพบที่ 1 — จุดกระโดดคือ V5 → V6

| | V5 (one-class) | V6 (supervised) |
|---|---|---|
| โมเดล | `IsolationForest` เทรนบน normal เท่านั้น | `RandomForestClassifier` + `labels = [0]*normal + [1]*attack` |
| recall (orig) | **4.41%** | **84.56%** |
| ROC-AUC (orig) | 0.8096 | 0.9959 |

**ยืนยันในโค้ด:**
```python
# run_sequence_model_v5.py
from sklearn.ensemble import IsolationForest        # เห็นแต่ normal

# run_supervised_sequence_v6.py
from sklearn.ensemble import RandomForestClassifier # เห็น label
labels = np.asarray([0] * len(normal_fit) + [1] * len(attack_fit), dtype=int)
```

**ทำไมถึงกระโดด:** one-class เรียนได้แค่ "ปกติหน้าตายังไง" — แต่ supervised **หาอะไรก็ได้ที่แยก 2 กลุ่ม**
และในข้อมูลชุดนี้มีตัวแยกที่ง่ายเกินไปรออยู่

---

## 4. ข้อค้นพบที่ 2 — bug `success_10m` มีจริง แต่เป็นแค่ส่วนเดียว

**bug:** `generate_normal()` ส่ง `failed_1h` และ `concurrent_sessions` เข้า `Event()` แต่
**ไม่เคยส่ง `success_10m`** → normal เป็น 0 ทุกแถว 100% ขณะที่ attack ตั้งเป็น 1–5

**ผลหลังแก้:** V6 recall ตกแค่ **84.56% → 79.41%** และ **ROC-AUC แทบไม่ขยับ (0.9959 → 0.9955)**

→ `success_10m` อธิบายการกระโดดได้แค่ **ประมาณ 6%** ของทั้งหมด

**เพราะยังมีทางลัดอื่นเหลืออยู่** — attack ทุก family นิยามด้วย "การไต่ขึ้นอย่างเป็นระบบ" ที่ normal ไม่เคยมี:

```python
# run_adversarial_v4.py
gradual_exfiltration : session_duration *= (1.20, 1.55, 2.05, 2.80)   # ×2.8 ใน 4 phase
                       scope_sensitivity += 0.06 * phase_index
stealth_mimicry_ato  : session_duration *= (0.90, 1.00, 1.18, 1.45)
                       scope_sensitivity += 0.03 * phase_index
session_replay_chain : session_duration *= (1.0, 0.8, 0.60, 0.42)
```

ขณะที่ normal คือ `duration = lognormvariate(log(18), 0.42)` — **σ แคบมาก ไม่มี trend เลย**

→ รายงาน V6 แสดงว่า **ทั้ง 6 family ได้ ~100%** รวมถึง 3 ตัวที่**ไม่ได้**ตั้ง `success_10m`
(`gradual_exfiltration`, `distributed_lateral_drift`, `profile_poisoning_chain`)
ซึ่งพิสูจน์ว่ามีทางลัดมากกว่าหนึ่งช่อง

---

## 5. ข้อค้นพบที่ 3 — ช่องว่างของการ generalize คือปัญหาที่แท้จริง

โมเดลตัวเดียวกัน วัดสองชุดข้อมูล:

| | ข้อมูลของ V7 เอง | **ชุด V2 (12 โปรไฟล์จริง)** |
|---|---|---|
| ROC-AUC | **0.996** | **0.641** |
| Recall | 79.4% (หลังแก้) | **0.0%** (ที่ threshold ของ bundle) |
| Challenge FPR | 0.32% | 0.53% |

**สาเหตุ — วัดจาก support ของฟีเจอร์:** normal ในชุด V2 หลุดออกนอกช่วงที่โมเดลเคยเห็นบ่อยมาก

| feature | ค่าสูงสุดตอนเทรน | normal ใน V2 ที่หลุดช่วง |
|---|---|---|
| `duration_log_range` | 2.509 | **62.1%** |
| `browser_version_slope` | 0.400 | **40.0%** |
| `success_sum` | 0.000 | **37.4%** |
| `duration_log_slope` | 0.756 | 26.8% |
| `scope_slope` | 0.080 | 11.6% |

ผู้ใช้จริงมี session ตั้งแต่ 0.1 ถึง 1,302 นาที · ใช้หลายเครื่องคนละเวอร์ชัน · ล็อกอินซ้ำใน 10 นาที
สิ่งเหล่านี้**อยู่นอกโลกที่โมเดลเคยเห็น** → ตีความไม่ถูก

---

## 6. ข้อสรุป

**ไม่ใช่ว่าโมเดลหรือโค้ดผิด** — pipeline, runtime, portable bundle, การแยก seed train/calibration/test
ทั้งหมดออกแบบมาดี และ V3 ก็ทำงานได้จริง (evasive recall 100%, FPR 0.15%)

**ปัญหาอยู่ที่ข้อมูลจำลอง:** "normal" นิ่งเกินไป และ "attack" ถูกนิยามด้วย trend ที่เป็นระบบ
→ งานแยก 2 กลุ่มนี้ง่ายเกินกว่าความเป็นจริงมาก → ตัวเลข 90.9% วัดความง่ายของข้อมูล
ไม่ได้วัดความสามารถของโมเดล

**หลักฐานที่หนักแน่นที่สุด:** ROC-AUC 0.996 บนข้อมูลตัวเอง แต่ 0.64 บนข้อมูลที่สร้างจาก
generator คนละตัว — ต่างกัน 0.36 จุด

---

## 7. ข้อเสนอ

| # | งาน | เหตุผล |
|---|---|---|
| 1 | **ใช้แพตช์ `success_10m`** | บั๊กชัดเจน แม้ผลน้อยก็ควรถูกต้อง |
| 2 | **ทำ "normal" ให้แปรผันเท่าข้อมูลจริง** — duration σ, browser version, การล็อกอินถี่ | 5 ฟีเจอร์ยังหลุด support |
| 3 | **นิยาม attack ใหม่ อย่าใช้ ramp คงที่ต่อ phase** — สุ่มทิศ/ขนาด หรือให้ normal มี trend บ้าง | ตอนนี้ "มี trend = attack" |
| 4 | **เพิ่ม support check เข้า test** — normal ตอนเทรนต้องไม่มีฟีเจอร์ที่เป็นค่าเดียว | AUC จับ bug ประเภทนี้ไม่ได้ (สูงสุดแค่ 0.714) |
| 5 | **ให้ export คำนวณ release_gate ใหม่** ไม่ใช่ copy จาก V6 | ตอนนี้เทรนใหม่แล้วตัวเลขยังเท่าเดิม |
| 6 | **ทุกเวอร์ชันต่อไปต้องรายงานผลบนชุดข้อมูลนอก** ไม่ใช่แค่ test split ของตัวเอง | gate ปัจจุบันผ่านได้แม้ generalize ไม่ได้ |
| 7 | **ห้ามเปิด enforcement** | ROC-AUC 0.64 นอกชุดเทรน |

---

## 8. รันซ้ำ

```bash
# รันทุกเวอร์ชัน 2 ต้นไม้
bash scripts/sweep_versions.sh          # (ใน scratchpad)

# หรือทีละเวอร์ชัน
python scripts/run_supervised_sequence_v6.py \
    --sizes 5000 --seeds 42 --scenarios normal_staggered --output out_v6

# วัดบนชุด V2
py ml-service/scripts/eval_v7_on_v2.py --bundle <path>/sequence_model_v7.joblib --runtime <path>/scripts
```

เอกสารที่เกี่ยวข้อง:
- [`v7_generator_fix_2026-08-21.md`](v7_generator_fix_2026-08-21.md) — รายละเอียดการแก้ + ผลบนชุด V2
- [`rba_4layer_v2_2026-08-21.md`](rba_4layer_v2_2026-08-21.md) — ผล 4-Layer บนชุดเดียวกัน (เทียบได้)
