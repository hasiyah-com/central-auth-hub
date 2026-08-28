# ตรวจสอบ V8 บนโค้ดจริง (commit `f6b2839`) — ฉบับสมบูรณ์

**วันที่:** 23 ส.ค. 2026
**commit:** `f6b2839` "add standalone Temporal MLP V8 experiment" (push ขึ้น GitHub แล้ว)
**ต่อจาก:** [`v8_review_2026-08-23.md`](v8_review_2026-08-23.md) (รีวิวจาก DOCX ก่อนได้โค้ด)

---

## สรุปคำตัดสิน

**V8 ผ่านการตรวจสอบเชิงเทคนิคทุกข้อที่สำคัญ** — เป็นเวอร์ชันแรกที่ตัวเลขของตัวเอง
**reproduce ได้จริง** (ไม่ copy แบบ V6→V7) และ scope ตัวเองถูกต้อง (shadow-only, abstain cold-start)

> ⚠️ **แก้ข้อสรุปเบื้องต้นของผม:** ผมลองรัน V8 บนชุด V2 แล้วได้ ROC-AUC 0.454 —
> **แต่ตัวเลขนี้ใช้ตัดสินไม่ได้** เพราะ reconstruction ของผมไม่ตรง eval protocol ของ V8
> (พิสูจน์ว่าไม่ตรงด้านล่าง) → ถอนคำเทียบ "0.998 ตกเหลือ 0.454"

---

## 1. ✅ Integrity — sha256 ตรง

```
temporal_mlp_v8.npz  22,146 bytes
sha256 b1cc254f...c050d419  ==  ที่แจ้ง ✓  ==  model_contract_v8.json ✓
```
runtime (`shadow_temporal_runtime_v8.py`) เช็ค sha256 เองตอนโหลด → ถ้าไฟล์เสียจะ raise
(แก้บทเรียนจาก V7 ที่ไม่มีใครเช็ก manifest)

## 2. ✅ Standalone — ไม่ import โค้ด V2–V7

- `model_contract_v8.json`: `"imports_previous_experiment_code": false`
- อ่านโค้ด `run_temporal_mlp_v8.py` — import แค่ numpy/stdlib · สร้าง timeline/attack/feature/
  train/eval/artifact ใหม่ทั้งหมดจาก `config/users.json` เท่านั้น
- runtime เป็น **NumPy ล้วน** ไม่ต้องมี sklearn (แก้ปัญหา pickle เวอร์ชันของ V7)

## 3. ✅ ตัวเลขของตัวเอง reproduce ได้จริง — จุดสำคัญที่สุด

รัน runner ของ V8 เองใหม่ (`run_temporal_mlp_v8.py --sizes 5000 --seeds 42`) เทียบ release_gate ที่ commit:

| metric | official (60 runs) | รัน repro (1 config) |
|---|---|---|
| ROC-AUC | 0.9976 | **0.9985** ✓ |
| PR-AUC | 0.9611 | 0.9569 ✓ |
| unexpected_challenge_fpr | 0.0020 | **0.0018** ✓ |
| precision | 0.9636 | 0.9529 ✓ |
| event_challenge_recall | 0.6890 | 0.7913 (1 config สูงกว่าค่าเฉลี่ย) |
| sequence_detection | 0.9685 | 1.0000 (1 config = perfect) |

→ **runner คำนวณ gate ใหม่จริง ไม่ได้ copy จากเวอร์ชันก่อน** (ต่างจาก V6→V7 ที่ผมพบว่า copy)
→ ROC-AUC ~0.998 **เป็นของจริงบน generator ของ V8 เอง**

## 4. ✅ Design แก้ตรงทุกข้อกังวล V6/V7 (ยืนยันจากโค้ด)

| ข้อกังวลเดิม | โค้ด V8 |
|---|---|
| supervised เรียน shortcut `success_10m` | **Strict feature ownership** — `neural_features()` รับแค่ 4 continuous (gap/duration/scope/browser-drift) + delta + summary = 64 dim · **ไม่รับ hard counters** (comment ในโค้ดอ้างถึงปัญหา success_10m ตรงๆ) |
| browser version absolute เป็น shortcut | โค้ดใช้ **within-window drift** `(v - v[0])/scale` ไม่ใช่ค่า absolute (comment: "previously made the normal test tail look like an attack") |
| cold-start พัง | `score_shadow()` abstain เมื่อ `< 1000 event` → `shadow_abstain_cold_profile` |
| ตัวเลขเฟ้อ | event recall **68.9%** (ไม่ใช่ 90.9%) — ซื่อสัตย์ |
| ไม่มีตัวจับ artifact | มี `generator_support_audit.json` (1045 บรรทัด) + contract `test_attack_subtlety: 0.72` |

## 5. ⚠️ External generalization — ยังพิสูจน์ไม่ได้ (และเป็นเรื่องปกติ)

ผมเขียน `eval_v8_on_v2.py` (import `neural_features`/`fit_profile_baselines` ของ V8 เอง)
รันบนชุด V2 size-5000 → ได้ ROC-AUC 0.454 · FPR 12.66%

**แต่ตัวเลขนี้ใช้ตัดสินไม่ได้ — 2 เหตุผล:**

1. **reconstruction ไม่ตรง protocol** — ผมลอง reproduce V8 บนข้อมูล+attack **ของ V8 เอง**
   ด้วย harness ผม ได้ ROC-AUC แค่ **0.708** (ไม่ใช่ 0.998) → harness ผมไม่ตรงวิธีที่ V8 วัด
   (campaign phase structure + calibration + cohort prior ที่ผมไม่ได้ replicate)
2. **V2 attack เป็น single-event · V8 ออกแบบจับ multi-phase campaign** — โค้ด V8 สร้าง
   window โดยสะสม phase ของ campaign เอง (`history.append(phase.event)` วนทั้ง campaign)
   ส่วน V2 attack window = 5 normal + 1 attack (ไม่มี campaign build-up) → under-test V8 อย่างมาก

→ การทดสอบ external ที่ fair จริงต้องมี **attack แบบ multi-phase** ซึ่ง generator V2 ไม่มี
→ **V8 เขียนเองว่า "ห้ามอ้าง synthetic gate เป็น production readiness" ต้อง production replay ก่อน** — ถูกต้องแล้ว

---

## 6. ข้อสรุปเทียบ V7

| | V7 | V8 |
|---|---|---|
| ไฟล์ artifact | เสีย (zlib error) → fix รอบ 2 | ✅ ครบ sha256 ตรง |
| ตัวเลข gate | **copy จาก V6** (เทรนใหม่เลขไม่ขยับ) | ✅ **reproduce ได้จริง** |
| sklearn dependency | ผูกเวอร์ชัน (pickle พัง) | ✅ NumPy portable |
| shortcut `success_10m` | เรียนได้ (RF รับ hard counter) | ✅ feature ownership กัน |
| cold-start | พัง (recall ตก) | ✅ abstain |
| ความซื่อสัตย์ของรายงาน | เฟ้อ (90.9%) | ✅ 68.9% + caveat ครบ |

**V8 คือการยกระดับที่แท้จริง** — แก้ทุกปัญหาที่ผมพบใน V6/V7 ทั้งเชิงวิศวกรรมและเชิงความซื่อสัตย์

---

## 7. สิ่งที่ยังควรทำ (ตามที่ V8 เขียนเอง + ผมเสริม)

| # | งาน | ใคร |
|---|---|---|
| 1 | **production replay** (anonymized, ไม่ใช้ final labels) — external test ที่แท้จริง | ก่อน enforce |
| 2 | **ablation: Rule/Behavior เดี่ยว vs +MLP** ที่ ≥1,000 event | พิสูจน์ MLP คุ้ม complexity — learning curve ผมชี้ว่า Rule ให้ 87% ตั้งแต่ 10 event |
| 3 | ยืนยัน `generator_support_audit` จับ **two-sided ramp** (duration/scope) ไม่ใช่แค่ one-sided | เชิงวิธีการ |
| 4 | คงไว้ shadow-only จนกว่า 1–2 ผ่าน — **ห้าม enforce** | policy |

---

## 8. ไฟล์ที่เกี่ยวข้อง

| ไฟล์ | บทบาท |
|---|---|
| `ml-service/scripts/eval_v8_on_v2.py` | harness external (มีข้อจำกัด — ดูข้อ 5) |
| commit `f6b2839` | โค้ด V8 บน GitHub (verify แล้ว) |

**สถานะรวม: V8 verified ✅ สำหรับ shadow-only — reproduce ได้, standalone, artifact ครบ, design ถูก
ยังต้อง production replay ก่อน enforce (ตามที่ V8 กำหนดเอง)**
