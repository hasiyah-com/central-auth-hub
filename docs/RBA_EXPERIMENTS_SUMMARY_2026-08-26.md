# สรุปการทดลอง 4-Layer RBA ทั้งหมด + ผลการวัดประสิทธิภาพ

**วันที่:** 26 ส.ค. 2026 · **แก้ไขล่าสุด:** 29 ส.ค. 2026 (final gate + service split)
**ขอบเขต:** การทดลองทั้งหมดตั้งแต่การสร้างชุดข้อมูลจำลอง → เลือกสถาปัตยกรรมโมเดล →
ปรับปรุงแต่ละชั้น → นำเข้า production
**ข้อจำกัดที่ยึดตลอด:** ข้อมูลจริงห้ามขึ้น git · deployment หลัง campus NAT (ไม่มี geo)
**ที่มาของตัวเลข:** ตัวเลข**ประสิทธิภาพโมเดล**ทุกตัวมาจากข้อมูลจำลองที่ anchor จากผู้ใช้จริง 12 คน ·
ส่วนตัวเลขที่มาจาก **traffic จริง** มีเพียง อัตรา login (1.65 ครั้ง/วัน/คน) และ replay 18 เหตุการณ์

> 📌 **ผลการทดลองถูก freeze แล้ว** — commit SHA · configuration · seeds · SHA-256 ของทุกรายงาน
> บันทึกไว้ที่ [`RBA_EVIDENCE_MANIFEST_2026-08-29.md`](RBA_EVIDENCE_MANIFEST_2026-08-29.md)
> ตัวเลขในเอกสารนี้จะไม่ถูกปรับจากการ tuning เพิ่ม — การเปลี่ยนแปลงใดๆ ต้องเป็นการทดลองรอบใหม่

> **สองแกนของการตัดสินใจ** (แยกขาดตั้งแต่ 29 ส.ค. 2026):
>
> ```text
> access_decision     = L1/L2/L4 -> allow | challenge | block   (ตัดสินสิทธิ์ผู้ใช้)
> monitoring_decision = L3        -> normal | l3_investigate    (ธงให้ SOC ดู)
> ```
>
> **L3 ไม่แตะ `access_decision` ทุกกรณี** — รวมถึงไม่ทำ `allow → warn`
> (เดิม L3 ยก decision เป็น `warn` ซึ่งอยู่ field เดียวกับ allow/challenge/block
> ทำให้ข้อความ "L3 ไม่เปลี่ยน access decision" ขัดกับพฤติกรรมจริง — แก้แล้ว
> บังคับด้วย `tests/test_l3_access_monitoring_split.py`)

---

## 0. บทสรุปผู้บริหาร

| หัวข้อ | ผลลัพธ์ |
|---|---|
| **ประสิทธิภาพบนชุดพัฒนา** (V2, ใช้ปรับจูน) | Recall **95.8%** · Precision **98.3%** · F1 **0.970** · Challenge FPR **2.11%** · Policy success **99.6%** |
| **ชั้นที่ขับเคลื่อนจริง** | L1 Rule + L2 Behavior (สถิติรายคน) — ไม่ใช่ ML |
| **สถานะ ML (L3)** | มีสัญญาณจริง (raw 16.3% บน campaign) · ออกทาง `monitoring_decision` เท่านั้น · **shadow-only** |
| **ผลบนชุดที่โมเดลไม่เคยเห็น** (final gate, seeds 101–105) | Recall **61.9%** · Precision **69.1%** · Challenge FPR **1.5%** · L3 FPR **0.7%** |
| **ความพร้อมใช้งาน** | ✅ Shadow Mode พร้อม + **เปิดใช้จริงแล้ว 29 ส.ค. 2026** · ⏳ Enforcement ต้องผ่าน production replay ก่อน |
| **การทดสอบ** | 808 passed / 53 skipped / 0 failed (full pytest, Docker) |

**ข้อค้นพบสำคัญที่สุด 3 ข้อ:**
1. **โมเดล supervised ที่ดูดีที่สุด (90.9% recall) เป็น artifact ทั้งหมด** — เรียน shortcut จาก generator
2. **สถิติรายคน (per-user rarity) เอาชนะ neural network** บนข้อมูลจริง — 95.8% vs FPR พุ่ง 8 เท่า
3. **L3 ไม่ได้ไร้ค่า แต่ถูกกลไกรวมคะแนนปิดกั้น** — raw 16.3% แต่ effective 0.2% จนแก้ integration
4. **SHAP พิสูจน์ว่า L3 บน 23 ฟีเจอร์ ซ้ำซ้อน** — unique 0.0% + DuplicateRatio 79.1% (สองวิธีตรงกัน)
5. **Generalization gap พบชัดกว่าใน L1/L2** — บน campaign family ที่ไม่เคยเห็น L1/L2 ตก
   38.8% → 20.7% ขณะที่ L3 (Config F) ขึ้น 3.6% → 5.1% · ตัวเลขชุดพัฒนา (95.8%) จึงเป็น
   เพดานบน ไม่ใช่ค่าที่คาดหวังจริง
   ⚠️ **ไม่ได้แปลว่า L3 ไม่ overfit** — ส่วนต่าง 3.6%→5.1% เล็กเกินกว่าจะสรุปอะไรได้
   สรุปได้แค่ว่า *วัด gap ได้ชัดในฝั่ง L1/L2* เท่านั้น

> ⚠️ **อ่านตัวเลขให้ถูก:** 95.8%/98.3% มาจากชุดที่ใช้ปรับจูน (V2) — ค่าที่ควรอ้างอิงเมื่อพูดถึง
> "ประสิทธิภาพที่คาดหวัง" คือ **final gate บน seeds 101–105 ที่โมเดลไม่เคยเห็น: recall 61.9% ·
> precision 69.1%** (§10.2) ส่วนต่างนี้คือขนาดของ optimism bias ที่วัดได้จริง

---

## 1. ชุดข้อมูลทดลอง (V2)

**สร้างจาก:** โปรไฟล์ผู้ใช้จริง 12 คน (users.xlsx + login_sessions + audit_logs)
→ generator จำลองพฤติกรรมรายคน (`build_profiles_v2.py`)

| พารามิเตอร์ | ค่า |
|---|---|
| ผู้ใช้ | 12 คน (U01–U12) แยกตามบทบาท/พฤติกรรมจริง |
| IP | `192.168.10.1` ทุกเหตุการณ์ (campus NAT) |
| Geo | ไม่มี → **5 ฟีเจอร์ geo เป็นค่าคงที่** (is_thailand, is_new_country, country_change, impossible_travel, is_attack_ip) |
| ฟีเจอร์ | 23 ตัว ตาม production contract (B49) |
| Attack | 3 กลุ่ม: **obvious** 11 scenario · **subtle** 5 scenario · **campaign** (low-and-slow multi-phase) |
| สัดส่วน attack ใน test | ~3.4% |

**PII:** `roster_v2.json` (alias→email จริง) gitignored · ทุก output เป็นตัวเลข/alias เท่านั้น ·
มี pre-commit hook `block-real-pii` กันหลุด

---

## 2. การทดลองเลือกสถาปัตยกรรมโมเดล (V2–V8)

### 2.1 Version sweep — จุดกระโดดอยู่ที่ไหน

| เวอร์ชัน | สถาปัตยกรรม | Event recall | Precision | ROC-AUC |
|---|---|---|---|---|
| V4 | sequence prototype | 7.29% | — | — |
| V5 | **one-class** IsolationForest | 8.65% | 76.28% | 82.08% |
| **V6** | **supervised** RandomForest | **90.90%** | 97.80% | 99.75% |
| V7 | V6 ห่อเป็น bundle (โมเดลเดิม) | 90.90% | 97.80% | 99.75% |

**สรุป:** จุดกระโดดคือ V5→V6 (one-class → supervised) ไม่ใช่ V7

### 2.2 ⚠️ ตรวจพบว่า 90.9% เป็น artifact ทั้งหมด

| การตรวจ | ผล |
|---|---|
| V7 artifact | joblib **เสีย** (zlib error, ขนาดไม่ตรง) → ต้อง rebuild |
| release_gate ของ V7 | **copy จาก V6** (เทรนใหม่ตัวเลขไม่ขยับเลย) |
| สาเหตุ recall สูง | ฟีเจอร์ `success_10m` ใน generator **normal = 0 เสมอ** → โมเดลเรียน "ตัวแยกปลอม" |
| หลังแก้ generator | recall **90.9% → ~0%** |

**บทเรียนเชิงวิธี:** AUC สูงไม่ได้แปลว่าโมเดลดี — ต้องทำ **support check** ว่า normal เคยมีค่าที่
โมเดลใช้แยกหรือไม่ (one-sided shortcut)

### 2.3 ตัดสินใจ: ไม่ใช้ supervised

production **ไม่มี attack label จริง** → เป็นปัญหา anomaly detection ไม่ใช่ classification
→ supervised ทุกตัว (RF/MLP) จะเรียน shortcut แทน

---

## 3. Learning curve — ต้องมีข้อมูลกี่แถวถึงนิ่ง

**วิธี:** 6 ขนาด (10/50/100/500/1000/5000 events/user) × 5 seeds · test ตรึงชุดเดียวกันทุกรอบ

### 3.1 รอบแรก (L1+L2, contract V2+)

| history/คน | Recall | Challenge FPR | Policy success |
|---|---|---|---|
| **10** | 87.0% ±1.0 | 3.3% ±1.7 | 90.8% ±1.2 |
| **50** | 88.9% ±0.3 | **1.2%** ±0.4 | 94.8% ±0.8 |
| 100 | 88.6% ±0.7 | 1.8% ±0.9 | 94.9% ±1.1 |
| 500 | 88.8% ±0.9 | 1.7% ±0.3 | 94.1% ±1.5 |
| 1000 | 89.4% ±0.2 | 1.6% ±0.3 | 94.6% ±0.7 |

**สรุป:** rule ให้ recall 87% ตั้งแต่ **10 login/คน** · FPR นิ่งที่ **~50** · เกิน 100 ไม่มี gain

### 3.2 รอบสอง (4 ชั้นครบ — per-user profile + IForest)

**วิธี:** train_pool | val (ตรึง) | test (ตรึง) แยกกัน · 3 config × 6 ขนาด × 5 seeds

| config | recall (นิ่ง) | subtle | Challenge FPR | L3 เพิ่ม |
|---|---|---|---|---|
| L1+L2 (ไม่มี L3) | 77% | 57% | 1.4% | baseline |
| +L3 per-user IForest | 78–79% | 58% | 1.5% | **+1–2%** |
| +L3 global IForest | 77% | 57% | 1.4% | **+0%** |

**ข้อค้นพบ:**
- **จุดนิ่ง ~50 แถว/คน** — recall 62%→77%, subtle 4%→57% แล้ว plateau
- **per-user > global** ตรงหลักการ "anomaly รายคนต้องใช้โมเดลรายคน"
- **L3 เพิ่มค่าน้อยมาก** แม้ที่ 5000 แถว

---

## 4. 🐞 บั๊กสำคัญที่พบระหว่างทดลอง

### 4.1 IForest anomaly sign กลับด้าน

```python
# ผิด: sigmoid(-score_samples) + map_score ของ production
#      -> attack ได้ anomaly ต่ำกว่า normal + scale ไม่เข้ากับช่วง offline
# ถูก: anomaly = -score_samples (สูง = ผิดปกติ) + calibrate จาก normal validation
```

| | attack ที่ L3 ยิง | normal ที่ยิง | ทิศทาง |
|---|---|---|---|
| **ก่อนแก้** | **0/240** | 0/190 | attack 0.067 **<** normal 0.097 ❌ |
| **หลังแก้** | **73/240** | 4/190 | attack 0.539 **>** normal 0.454 ✅ |

**ผลกระทบ:** L3 ไม่ทำงานเลยโดยไม่มีใครรู้ · **ไม่กระทบผลของ L1/L2** (ตัวเลข Tier reports ถูกต้อง)
**ป้องกัน:** เพิ่ม unit test ตรวจทิศทาง sign

### 4.2 หลังแก้ sign แล้ว L3 ยังไม่เพิ่ม recall

recall/FPR **ไม่ขยับเลย** → 73 attack ที่ L3 จับได้ L1/L2 จับไปหมดแล้ว = **สัญญาณซ้ำ ไม่ใช่สัญญาณใหม่**

---

## 5. เปรียบเทียบกับ Neural Network (V8 Temporal MLP)

**V8 คืออะไร:** NumPy-only Temporal MLP 64-32-12-1 · feature ownership · abstain <1000 events

### 5.1 ตรวจสอบ V8 (commit `f6b2839`)

| ตรวจ | ผล |
|---|---|
| sha256 artifact | ✅ ตรง |
| standalone (ไม่ import V2–V7) | ✅ |
| **reproduce ตัวเลขตัวเอง** | ✅ ROC-AUC 0.9976 → รันซ้ำได้ **0.9985** |
| ความซื่อสัตย์ | ✅ event recall **68.9%** (ไม่เฟ้อ) + caveat ครบ |

**V8 เป็นการยกระดับที่แท้จริงเทียบ V6/V7** — แต่ทดสอบบน generator ของตัวเองเท่านั้น

### 5.2 Ablation บนข้อมูล V2 (คนจริง)

| | Rule+Behavior | + V8 MLP | ต่าง |
|---|---|---|---|
| Recall | 82.9% | 86.2% | +3.3 |
| **Challenge FPR** | **1.7%** | **14.1%** | **+12.4** ⚠️ |
| Precision | 49.9% | 10.9% | −39.0 ⚠️ |

**หลัง recalibrate threshold บน normal ของ V2:**

| | threshold เดิม | recalibrate |
|---|---|---|
| challenge threshold | 0.9962 | **1.0000** |
| **V8 เพิ่ม recall** | +3.3% | **+0.0%** |
| Challenge FPR | 14.1% | 2.2% (ในงบ) |

**สรุปชี้ขาด:** +3.3% เดิมมาจาก over-flag ล้วน · **ปัญหาคือ ranking ไม่ใช่ threshold** →
V8 แยก normal/attack บน distribution จริงไม่ออก → **ไม่นำเข้า production**

---

## 6. การปรับปรุงที่ได้ผลจริง — เก็บ "แนวคิด" ของ V8 มาทำเป็นสถิติ

> ของดีของ V8 คือ **rarity รายคน** ไม่ใช่ neural net → เอาแนวคิดมาทำเป็นสถิติในชั้น L2

### 6.1 Tier 1 — hour_rarity + subsystem novelty

**A/B บนชุดเดียวกัน** (normal test 190 · attack 240):

| ตัวชี้วัด | baseline | **+Tier 1** | ต่าง |
|---|---|---|---|
| **Recall** | 85.0% | **95.8%** | **+10.8** |
| **Policy success** | 85.0% | **99.6%** | **+14.6** |
| **Challenge FPR** | 2.1% | **2.1%** | **+0.0** ✅ |
| Warn FPR | 2.1% | 5.8% | +3.7 |
| Precision | 98.1% | 98.3% | +0.2 |

**2 scenario ที่เคยได้ 0% แก้ได้:**

| scenario | ก่อน | หลัง |
|---|---|---|
| `subsystem_lateral` | 0% / 0% | **100% / 100%** |
| `off_hours` | 0% / 0% | **58% / policy 96%** |

**เทียบ V8 ตรงๆ:** V8 ได้ +3.3% recall แลก FPR 14.1% · **Tier 1 ได้ +10.8% โดย FPR ไม่ขยับ**

### 6.2 Tier 2 — cadence z-score + signature_rarity

| ตัวชี้วัด | Tier 1 | +Tier 2 |
|---|---|---|
| Recall / FPR / Precision | 95.8% / 2.1% / 98.3% | **เท่าเดิมทุกตัว** |

**= defense-in-depth ที่ไม่มีต้นทุน** · พิสูจน์คุณค่าด้วย probe test 4 ตัว (จับ stealth ที่หลบ rule
global ได้ผ่านการ converge ของสัญญาณอ่อนหลายตัว)

**เทคนิคที่ใช้ (สถิติล้วน):** `rarity = 1 − (count+1)/(total+buckets)` (Laplace) ·
`_robust_center_scale` = median + IQR (ทนกว่า mean/std) · policy floor จาก behavior layer

---

## 7. การกู้ L3 — จาก "ไร้ค่า" เป็น "ธงเฝ้าระวังที่ใช้ได้"

### 7.1 ทดลอง feature ownership (A/B/C/D × 6 ขนาด × 5 seeds)

**ชุดไม่มี campaign:** L3-unique = **0.0 ± 0.0 ทุก config** (แม้ D = residual/interaction)

**Diagnosis:** attack ที่ L1/L2 พลาด มี base_total เฉลี่ย **0.10** (max 0.30) — L3 flag ได้แค่ 3/48
→ **ไม่มีสัญญาณให้จับตั้งแต่แรก** ในชุด single-event

### 7.2 สร้าง campaign attack (low-and-slow multi-phase)

ทุก phase หลบ L1/L2 โดยตั้งใจ: เครื่องเดิม · subsystem เดิม · ชั่วโมงห่าง peak แค่ 3–4 ชม. ·
gap 35–45 นาที · **แต่ drift ร่วมกันหลายมิติ** (scope ไต่ + duration ไต่ + cadence เร็วขึ้น)

**ยืนยันว่าหลบได้จริง:** L1+L2 ให้ **allow 71/120** · base_total mean 0.38

**ผล:** L3-unique **D > C > B** (0.4 / 0.1 / 0.1) — ตรงทฤษฎีว่า feature design สำคัญ แต่ยังเล็ก

### 7.3 🔑 ค้นพบคอขวดจริง — raw vs effective

**Diagnostic:** L3 sequence จัดอันดับ campaign **ถูกต้อง** (66% เกิน normal p95) แต่
base_total ของพวกนี้แค่ 0.23 → **bonus +0.15 ดันถึง warn (0.5) ได้แค่ 2/71**

**แยกวัด raw vs effective (5 seeds, size 5000):**

| config | **raw** (L3 flag ได้) | **effective** (decision เปลี่ยน) | overlap |
|---|---|---|---|
| D: point-residual + bonus | 8.5±4.8 | 0.2±0.3 | 14.0±2.6 |
| E: sequence-residual + bonus | **16.3±4.4** | **0.2±0.3** | 11.3±3.1 |
| **F: sequence + surfacing channel** | **16.3±4.4** | **16.3±4.4** ✅ | 11.3±3.1 |

> **E กับ F ใช้โมเดลเดียวกันเป๊ะ ต่างแค่วิธีรวมผล**
> **⇒ คอขวดคือ L4 fusion ไม่ใช่ Isolation Forest**

**เจอเพิ่ม:** raw ของ E (16.3%) > D (8.5%) เกือบ 2 เท่า — **sequence framing มีค่าจริง**
ซึ่งการวัดด้วย effective อย่างเดียวมองไม่เห็น (เคยสรุปผิดว่า "sequence ไม่ช่วย")

### 7.4 ผลของ config F (size 5000, 5 seeds)

| | A (L1+L2) | F | ต่าง |
|---|---|---|---|
| campaign surfaced | 41.3±11.1% | **57.7±7.3%** | **+16.4pp** |
| L3-unique (attack ทั้งหมด) | 0 | **5.1±1.3%** | **+5.1pp** |
| **Challenge FPR** | 1.6±0.2% | **1.6±0.2%** | **+0.0** ✅ |
| warn FPR | 2.8±0.1% | 3.6±0.4% | +0.8pp |

**เพิ่มขึ้นตามข้อมูล:** 4.7% (50 events) → 16.3% (5000)

---

## 7.5 การทดลองรวม 4 ชั้น + SHAP (การทดลองชี้ขาด)

**วิธี:** รันทุก event ผ่านทั้ง 4 ชั้นพร้อมกัน · size 5000 · 5 seeds · attack 413 · normal 8,400
· L3 ใช้ IsolationForest 2 แบบเทียบกัน + SHAP วิเคราะห์ attribution

### ผลแยกชั้น (mean ± CI95)

| ชั้น | standalone | **unique** | overlap | FPR |
|---|---|---|---|---|
| **L1 Rule** | 43.6±0.5 | **36.4±1.5** | 7.3±1.2 | 1.5±0.2 |
| **L2 Behavior** | 33.5±3.3 | **21.1±2.7** | 12.4±2.0 | 1.3±0.1 |
| L3 IForest-sequence | 16.4±3.3 | **5.1±1.3** | 11.3±3.1 | 0.8±0.3 |
| **L3 IForest-23 ฟีเจอร์** | 13.3±1.4 | **0.0±0.1** ❌ | 13.2±1.4 | 1.3±0.3 |

**L4 รวม:** recall 58.6% · surfaced 76.4% · Challenge FPR 1.6% · Warn FPR 3.6% · precision 64.4%
*(ชุดนี้ยากกว่าชุดหลักเพราะรวม campaign attack ที่ออกแบบให้หลบ L1/L2 โดยเฉพาะ)*

### SHAP ยืนยันด้วยหลักฐานอิสระ

| วิธีวัด | ผล |
|---|---|
| unique detection (จาก decision) | L3-all23 = **0.0 ± 0.1%** |
| **SHAP DuplicateRatio** (จาก attribution) | **79.1%** ของ \|SHAP\| บน attack มาจากฟีเจอร์ของ L1/L2 |

เกณฑ์ >70% = "ตรวจซ้ำเป็นส่วนใหญ่" → **เกินเกณฑ์** · สองวิธีที่ไม่เกี่ยวกันสรุปตรงกัน

**Top features ของ L3-all23:** `active_subsystem_count` (1.591) · `concurrent_session_count` (1.194)
— **ทั้งคู่เป็นฟีเจอร์ที่ L1 มีกฎตรงๆ อยู่แล้ว** → L3 "ค้นพบ" สิ่งที่ rule ประกาศไว้ชัดเจนแล้ว

**geo = 0.0%** — 4 ฟีเจอร์ geo ไม่มีส่วนร่วมเลย = หลักฐานเชิงปริมาณว่าระบบทำงานบน **18 ฟีเจอร์**

### Methodology (SHAP กับ IsolationForest)

| explainer | parity กับ `-score_samples` | ใช้ทำอะไร |
|---|---|---|
| `TreeExplainer` | ❌ ไม่ additive · **rank-corr = 1.00** | จัดอันดับ attribution (เร็ว) |
| `PermutationExplainer` | ✅ **diff = 1.1e-15** | ตรวจ parity บน sample |

**รายงานเต็ม:** `tests/reports/exp_4layer_full_2026-08-26.md`


---

## 7.6 Config G — ทดสอบ "ใช้ทุกฟีเจอร์ที่มีข้อมูล" (5 seeds)

**คำถาม:** ถ้าให้ L3 ใช้ **ทุกฟีเจอร์ที่ eligible** (ไม่ใช่แค่ 6 ตัวที่ L1/L2 ไม่ถือ) แต่ยังแปลงเป็น
residual + sequence เหมือนเดิม — จะดีกว่าไหม

| metric | Config F (6→18) | Config G (10→30) | Δ (G−F) |
|---|---|---|---|
| **L3 unique** | **5.1±1.3** | 1.2±0.5 | **−3.9±1.2** ❌ |
| L3 unique (campaign) | **16.3±4.4** | 3.2±1.0 | **−13.2±4.2** ❌ |
| standalone | 16.4±3.3 | 11.9±3.0 | −4.5±2.3 |
| Challenge FPR | 1.6±0.2 | 1.6±0.2 | +0.0 ✅ |
| Warn FPR (รวม monitor) | 3.6±0.4 | 3.7±0.2 | +0.1 ✅ |
| latency (fit/คน) | 0.91s | 1.02s | +0.11s |

**ได้ 30 มิติไม่ใช่ 54** เพราะ variance ต้องมีต่อ *คนนั้น* — 4 ฟีเจอร์ (failed_logins, passkey_count,
new_passkey, confirmed_incident) คงที่ในข้อมูล normal ทุกคน · อีกหลายตัวคงที่เฉพาะบางคน

**สาเหตุที่แย่ลง — signal dilution:** IForest สุ่มเลือกฟีเจอร์มาแบ่ง ยิ่งมีมิติที่ไม่เกี่ยวมาก
โอกาสแบ่งด้วยมิติที่มีสัญญาณยิ่งน้อย · campaign drift อยู่เฉพาะ cadence/scope/subsystem-rarity
การเติม `hour_of_day`/`day_of_week`/`login_count_24h` ที่ไม่ drift จึงกลบระยะทางใน feature space

> **สรุป: คง Config F** — พิสูจน์ว่า feature ownership **ไม่ใช่การตัดข้อมูลทิ้ง แต่เป็นการตัด noise**
> (ตรงกับ SHAP ที่วัดได้ก่อนหน้าว่า L3 บนฟีเจอร์ครบชุดมี DuplicateRatio 79.1%)

**รายงานเต็ม:** `tests/reports/exp_l3_config_g_2026-08-26.md`


---

## 8. สิ่งที่นำเข้า production แล้ว

| ส่วน | ไฟล์ | สถานะ |
|---|---|---|
| L1 Rule (Phase 1 port) | `app/security/rule_engine.py` | ✅ ใช้งานจริง |
| L2 Tier 1 (rarity) | `app/security/behavior_profiling.py` | ✅ ใช้งานจริง |
| L2 Tier 2 (cadence/signature) | `app/security/behavior_profiling.py` | ✅ ใช้งานจริง |
| L4 policy floor (rule + behavior) | `app/security/risk_aggregator.py` | ✅ ใช้งานจริง |
| **L3 sequence channel** | `app/security/l3_sequence.py` + `ml-service/app/sequence.py` | ✅ **เปิดใช้จริง 29 ส.ค. 2026** (`L3_SEQUENCE_ENABLED=true`, shadow) |

**การออกแบบ L3 ใน production:**
- per-user IForest บน residual 6 มิติ × window 5 → 18 มิติ
- **abstention tiers:** abstain <100 · diagnostic 100–999 (log อย่างเดียว) · warn ≥1000 · challenge ≥2000
- **two-tier threshold:** 99th → anomaly · 99.9th → extreme
- **ไม่แตะ access decision เลย** — ออกทาง `monitoring_decision` (`normal` / `l3_investigate`)
  · `would_*` ใน `shadow_decision` เก็บวิเคราะห์เท่านั้น
- **data contract ต่อ login:** `eligible/eligibility/raw_score/percentile/decision/tier/score/model_version/n_history`
- history เก็บใน Redis (ไม่แตะ schema) · cache โมเดลรายคน TTL 1 ชม.
- fail-safe ตาม B21 — ML deps ไม่มี = abstain เงียบๆ

**การตัดสินใจสถาปัตยกรรม (29 ส.ค. 2026) — เลือกย้ายไป ml-service:**

hub-backend **ไม่มี numpy/sklearn โดยตั้งใจ** (ML แยกอยู่ ml-service ตั้งแต่ Week 5) ผลคือโค้ด L3
ที่เขียนไว้จะ abstain เงียบตลอดกาลถ้ารันจริง — ผ่านเทสบน host แต่ไม่เคยทำงานใน production

| ทาง | ผล | เลือก |
|---|---|---|
| เพิ่ม numpy+sklearn เข้า hub-backend image | image โต ~300MB · มี ML สองที่ · ขัดการแยก concern เดิม | ❌ |
| **ย้าย numeric core ไป ml-service** | สอดคล้องสถาปัตยกรรมเดิม · hub เบาเท่าเดิม | ✅ |
| ปิด L3 ถาวร | เสียงานทดลองทั้งหมด | ❌ |

```
hub-backend  residual_raw() → record_residual() → Redis      (pure python)
                    ↓ POST /v1/sequence-score (httpx, fail-safe B21)
ml-service   อ่าน Redis เอง → fit IForest รายคน → score W=5   (numpy/sklearn)
```

ml-service ต่อ Redis เอง (`cah-net` เดียวกัน) แทนการส่ง history 1,500 แถว (~70KB) ไปกับทุก request ·
hub ยังเป็นผู้เขียน history เจ้าเดียว · มี parity test กันค่าคงที่สองฝั่งเพี้ยน (บทเรียนเดียวกับ B49)
· รายละเอียด + ผลทดสอบ: `tests/reports/l3_service_split_2026-08-29.md` และ **B61**

---

## 9. การทดสอบ

> **หมายเหตุการอ่านตัวเลข:** ตัวเลขหลักสิบ (เช่น 57) คือ **เฉพาะชุดเทสของงานทดลอง RBA**
> ส่วนตัวเลข 700+ คือ **full system suite ทั้งโปรเจค** — คนละความหมาย อย่าสลับกัน

**ก. ชุดเทสของงานทดลอง RBA (subset)**

| ไฟล์ | จำนวน | ผล |
|---|---|---|
| `test_rule_engine_v2_signals.py` (L1) | 12 | ✅ |
| `test_behavior_rarity.py` (L2 Tier 1) | 9 | ✅ |
| `test_behavior_tier2.py` (L2 Tier 2) | 7 | ✅ |
| `test_behavior_scope_escalation.py` (L2 Tier 3) | 6 | ✅ |
| `test_tier2_catches_evasive.py` (probe) | 4 | ✅ |
| `test_l3_sequence.py` (L3 core) | 14 | ✅ (5 รันใน container / 9 ต้องมี numpy → skip) |
| `test_l3_window_integrity.py` (regression) | 5 | ✅ |
| `test_l3_contract_persisted.py` | 4 | ✅ |
| `test_l3_sequence_client.py` | 8 | ✅ (1 skip: parity ต้องมี repo root) |
| `test_l3_remote_e2e.py` (ข้ามคอนเทนเนอร์จริง) | 5 | ✅ |
| **รวมชุดทดลอง** | **74** | ✅ **64 passed / 10 skipped / 0 failed** (skip = ต้องมี numpy บน host) |

**ข. Full system suite (ทั้งโปรเจค)**

```
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
================= 772 passed, 53 skipped in 133.88s (0:02:13) ==================
```

⚠️ ต้อง `--ignore` สองไฟล์ — เป็น**สคริปต์ standalone** ที่มี `sys.exit()` ระดับ module
(ตาม docstring `Run: docker exec ...`) ไม่ใช่ pytest module · pytest collect แล้ว `SystemExit`
ทำให้ทั้ง suite ตายที่ `INTERNALERROR` · รันตามวิธีของมันเอง: `test_l1_oidc.py` 58/62 ·
`test_e2e_full_stack.py` 38/41 (fail ทั้งหมด = dorm/library stack ไม่ได้รัน + api_guard
ตัดวงจรจากสคริปต์ยิงรัวเอง — ไม่แตะ L3)

| อื่นๆ | ผล |
|---|---|
| pre-commit ทุก hook | ✅ ruff · format · secrets · PII · import-collect |

**ปัญหาชุดทดสอบที่แก้ไประหว่างทาง:**
- rate limiter ใช้โควตาร่วมกันทั้ง suite → test ท้ายๆ fail แบบสุ่ม → เพิ่ม autouse fixture ล้าง `LIMITS:*`
- `test_incidents` timeline ใช้ `order_by(asc).limit(40)` → audit สะสมทำแถวใหม่หลุด → ทำให้ hermetic
- `test_e2e_rba` fixture ไม่ตั้ง `permission_change_age` neutral
- `test_04_new_device` โดน impossible_travel จาก test ก่อนหน้า (**การประเมินใช้เวลาจริง ไม่ใช่ created_at**)

---

## 10. สรุปผลการวัดประสิทธิภาพ (ตัวเลขสุดท้าย)

### 10.1 บนชุดพัฒนา V2 (ใช้ปรับจูน — เป็นเพดานบน ไม่ใช่ค่าที่คาดหวัง)

| ตัวชี้วัด | ค่า |
|---|---|
| **Recall** (challenge+) | **95.8%** |
| **Precision** | **98.3%** |
| **F1** | **0.970** |
| **Policy success** | **99.6%** |
| **Challenge FPR** | **2.11%** (4/190) |
| Warn FPR | 5.79% |
| scenario ที่จับได้ 100% | 10/11 (off_hours = warn 96%) |

### 10.2 🎯 FINAL GATE — ชุดที่โมเดลไม่เคยเห็น (ตัวเลขที่ควรอ้างอิง)

**เงื่อนไข:** train/validation = seeds 42–46 (ชุดเดิม) · **evaluation = seeds 101–105
(normal + attack ใหม่ทั้งหมด)** · config ล็อก: sequence-residual W=5 · p99.9 · L3 = monitoring
เท่านั้น · ขนาด eval: attack 3,230 · normal 60,000 · campaign instance 300 · **รันครั้งเดียว
ไม่ปรับอะไรจากผลนี้**

**ตรวจก่อนเชื่อผล**

| การตรวจ | ผล |
|---|---|
| data leakage (eval ซ้ำ train, เทียบ 11 ฟิลด์) | **0 / 63,230** ✅ |
| generator shortcut (feature AUC>0.99 หรือ support<5%) | **0 feature** ✅ |
| L3 แตะ access decision (allow/challenge/block) | **0 ครั้ง** ✅ |

**ผลตามขนาดข้อมูลต่อคน** (Wilson CI95)

| size | recall (challenge+) | precision | Challenge FPR | L3 FPR |
|---|---|---|---|---|
| 50 | 63.3% [61.7, 65.0] | 53.0% [51.4, 54.6] | 3.0% [2.9, 3.2] | 0.0% |
| 100 | 62.7% [61.0, 64.4] | 61.1% [59.4, 62.7] | 2.2% [2.0, 2.3] | 0.9% [0.8, 1.0] |
| 500 | 61.7% [60.0, 63.4] | 69.0% [67.3, 70.7] | 1.5% [1.4, 1.6] | 0.8% [0.7, 0.9] |
| 1000 | 61.9% [60.2, 63.5] | 68.7% [67.0, 70.4] | 1.5% [1.4, 1.6] | 0.8% [0.7, 0.9] |
| **5000** | **61.9% [60.2, 63.6]** | **69.1% [67.4, 70.7]** | **1.5% [1.4, 1.6]** | **0.7% [0.6, 0.8]** |

**แยกชั้น (size 5000)**

| ชั้น | ค่า [Wilson CI95] |
|---|---|
| L1 Rule อย่างเดียว (warn+) | 50.5% [48.7, 52.2] |
| L2 Behavior อย่างเดียว (warn+) | 49.8% [48.0, 51.5] |
| L3 ยิง (event) | 5.7% [5.0, 6.6] |
| **L4 รวม (challenge+)** | **61.9% [60.2, 63.6]** |

**Campaign-level (n = 300 instance)**

| ตัวชี้วัด | ค่า [CI95] |
|---|---|
| **L1/L2 surfaced** | **96.7% [94.0, 98.2]** |
| L3 surfaced | 16.3% [12.6, 20.9] |
| **L3 only** (มีแต่ L3 ที่เห็น) | **0.7% [0.2, 2.4]** |
| event L3-unique | 1.0% [0.7, 1.4] |
| false incident / user-day | 1.4% [1.2, 1.5] |

**Latency & abstention**

| size | abstention | fit (วินาที/คน) | score (ms/event) |
|---|---|---|---|
| 50 | 100.0% | 0.00 | 0.000 |
| 100 | 0.0% | 0.39 | 4.286 |
| 500 | 0.0% | 0.48 | 4.655 |
| 1000 | 0.0% | 0.54 | 4.533 |
| 5000 | 0.0% | 0.87 | 4.361 |

**เกณฑ์ผ่าน/ไม่ผ่าน**

| เกณฑ์ | ผล |
|---|---|
| ไม่มี data leakage | ✅ |
| L3 ไม่แตะ access decision | ✅ |
| ไม่มี generator shortcut | ✅ |
| L3 FPR ≤ 1% | ✅ (0.7%) |
| Challenge FPR ≤ 3% | ✅ (1.5%) |
| L1/L2 campaign surfaced ≥ 90% | ✅ (96.7%) |
| L3 มีคุณค่าพอสำหรับ enforcement (unique ≥3%) | ❌ (1.0%) |

> **ข้อสรุป final gate:** พร้อมใช้แบบ shadow + พร้อมเข้าสู่ production replay
> — **ยังไม่พร้อม enforcement ด้วย L3**

รายงานเต็ม: `tests/reports/exp_final_gate_2026-08-26.md`

### 10.3 พัฒนาการตลอดการทดลอง

| จุด | Recall | Challenge FPR |
|---|---|---|
| ก่อน Phase 1 | 25% | — |
| Phase 1 (rule port) | 85.0% | 2.11% |
| **+Tier 1 (rarity)** | **95.8%** | **2.11%** |
| +Tier 2 (cadence/signature) | 95.8% | 2.11% |
| (ทางเลือกที่ปฏิเสธ) +V8 MLP | 86.2% | **14.1%** ❌ |

---

## 11. ข้อจำกัดที่ต้องระบุใน thesis

1. **ทุกตัวเลขบนข้อมูลจำลอง** (anchor จากผู้ใช้จริง แต่ generate เอง) — ยังไม่ผ่าน production replay
2. **Geo layer ใช้ไม่ได้** เพราะ campus NAT → 5/23 ฟีเจอร์เป็นค่าคงที่ · ระบบทำงานบน 18 ฟีเจอร์
3. **campaign attack ออกแบบเอง** — L3 จับได้เพราะเป็น joint-drift ที่เราใส่เข้าไป
4. **L3 ต้องมี ≥1000 events/คน** ถึงมีผลจริง (16.3% ที่ 5000 vs 4.7% ที่ 50)
5. **ยังไม่ทดสอบ enforcement** — ทุกอย่างวัดในโหมดประเมินผล ไม่ใช่ระบบที่บล็อกผู้ใช้จริง

---

## 12. ขั้นตอนต่อไป

| ลำดับ | งาน | สถานะ |
|---|---|---|
| 1 | ตัดสินใจสถาปัตยกรรม L3 (deps ที่ hub vs ย้ายไป ml-service) | ✅ **เสร็จ 29 ส.ค.** — ย้ายไป ml-service (§8) |
| 2 | เก็บ `l3_sequence` contract ลง audit/DB | ✅ **เสร็จ 29 ส.ค.** — `risk_breakdown` (JSON, ไม่ต้อง migration) |
| 3 | เปิด `L3_SEQUENCE_ENABLED=true` + verify | ✅ **เสร็จ 29 ส.ค.** — `--force-recreate` ตาม B36 |
| 4 | Freeze ผลการทดลอง (SHA · config · seed · hash) | ✅ **เสร็จ 29 ส.ค.** — `RBA_EVIDENCE_MANIFEST_2026-08-29.md` |
| 5 | **Stability test** (restart · cold profile · model หาย/เสีย · concurrency · latency · fail-safe) | ⏳ กำลังทำ |
| 6 | **Production shadow replay** (anonymized) | ⏳ ด่านชี้ขาดที่แท้จริง — ยืนยันทั้ง L1/L2 และ L3 |
| 7 | ส่งชุดหลักฐานให้ผู้เชี่ยวชาญตรวจ | ⏳ หลังมีข้อมูล replay |
| 8 | Release gate ครบ (precision จริง · rollback test) | ⏳ ก่อนพิจารณา enforcement |

**สิ่งที่ตกลงว่าจะไม่ทำ:** ไม่ปรับ threshold/โมเดล/ฟีเจอร์จากผล final gate หรือจากข้อมูล
production ใดๆ จนกว่าจะมี replay เพียงพอและออกแบบการทดลองรอบใหม่อย่างเป็นทางการ

---

## ภาคผนวก — รายงานฉบับเต็มแต่ละการทดลอง

| การทดลอง | รายงาน |
|---|---|
| สร้างโปรไฟล์ V2 | `tests/reports/profiles_v2_2026-08-21.md` |
| 4-layer บน V2 | `tests/reports/rba_4layer_v2_2026-08-21.md` |
| Learning curve (L1+L2) | `tests/reports/learning_curve_v2_2026-08-21.md` |
| Phase 1 production port | `tests/reports/phase1_production_port_2026-08-21.md` |
| V7 generator artifact | `tests/reports/v7_generator_fix_2026-08-21.md` |
| Version sweep V2→V7 | `tests/reports/v2_to_v7_version_sweep_2026-08-21.md` |
| ตัดสินใจเลือกเวอร์ชัน | `tests/reports/model_version_decision_2026-08-21.md` |
| ตรวจสอบ V8 | `tests/reports/v8_verification_2026-08-23.md` |
| Ablation V8 (+recalibrate) | `tests/reports/ablation_v8_vs_rule_2026-08-23.md` |
| **Tier 1 (rarity)** | `tests/reports/tier1_rarity_behavior_2026-08-25.md` |
| **Tier 2 (cadence/signature)** | `tests/reports/tier2_cadence_signature_2026-08-25.md` |
| Learning curve 4 ชั้น | `tests/reports/lc_4layer_2026-08-25.md` |
| L3 feature ownership | `tests/reports/l3_ownership_nocampaign_2026-08-25.md` |
| L3 + campaign attack | `tests/reports/l3_campaign_2026-08-26.md` |
| **L3 sequence + channel** | `tests/reports/l3_sequence_channel_2026-08-26.md` |
| **L3 raw vs effective** | `tests/reports/l3_raw_vs_effective_2026-08-26.md` |
| **รวม 4 ชั้น + SHAP** | `tests/reports/exp_4layer_full_2026-08-26.md` |
| **Config G (all-feature)** | `tests/reports/exp_l3_config_g_2026-08-26.md` |
| Learning curve V3 (episode-aware) | `tests/reports/exp_lc_v3_2026-08-26.md` |
| Threshold sweep + L2 fix | `tests/reports/exp_thr_and_l2_fix_2026-08-26.md` |
| Window sweep (W=5 vs 10 vs multi) | `tests/reports/exp_l3_window_2026-08-26.md` |
| Campaign-level metrics | `tests/reports/exp_campaign_level_2026-08-26.md` |
| Bootstrap/Wilson/cluster CI | `tests/reports/exp_final_synthetic_2026-08-26.md` |
| **🎯 FINAL GATE (seeds 101–105)** | `tests/reports/exp_final_gate_2026-08-26.md` |
| **Service split + เปิดใช้จริง** | `tests/reports/l3_service_split_2026-08-29.md` |

**สคริปต์การทดลอง:** `ml-service/scripts/` — `build_profiles_v2.py` · `features_v2.py` ·
`eval_production_v2.py` · `eval_tier1_ab.py` · `lc_run_4layer.py` · `lc_l3_ownership.py` · `lc_l3_sequence.py` · `exp_4layer_full.py` · `exp_l3_config_g.py`
