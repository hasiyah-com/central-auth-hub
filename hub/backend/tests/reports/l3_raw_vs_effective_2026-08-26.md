# L3 raw vs effective — พิสูจน์ว่าคอขวดคือ "การรวมผล" ไม่ใช่โมเดล

**วันที่:** 26 ส.ค. 2026
**ที่มา:** แผน `l3_isolation_forest_redesign.md` §7 (แยก raw / effective / overlap)
**seeds:** 42–46 (mean ± 95% CI) · sizes 10–5000 · per-user IForest · campaign attack ในชุดทดสอบ

---

## ผลชี้ขาด: raw สูง แต่ effective = 0 (D/E) → พอเปลี่ยนวิธีรวมผล (F) เท่ากันทันที

**L3 unique detection เฉพาะ campaign** (attack ที่ L1/L2 ปล่อยผ่าน) ที่ size 5000:

| config | **raw** (L3 flag ได้) | **effective** (decision เปลี่ยนจริง) | overlap (ซ้ำ L1/L2) |
|---|---|---|---|
| D: point-residual + bonus ≤0.15 | **8.5±4.8** | **0.2±0.3** | 14.0±2.6 |
| E: sequence-residual + bonus ≤0.15 | **16.3±4.4** | **0.2±0.3** | 11.3±3.1 |
| **F: sequence + surfacing channel** | **16.3±4.4** | **16.3±4.4** ✅ | 11.3±3.1 |

> **E กับ F ใช้โมเดลเดียวกันเป๊ะ — ต่างกันแค่วิธีรวมผล**
> E: raw 16.3% → effective **0.2%** (bonus +0.15 ดันคะแนน 0.23 ไม่ถึง warn 0.5)
> F: raw 16.3% → effective **16.3%** (ยก warn ตรง)
> **⇒ คอขวดคือ L4 fusion ไม่ใช่ Isolation Forest** — ตรงกับสมมติฐานของแผน §1

### เห็นชัดขึ้นตามปริมาณข้อมูล (raw ของ E/F)

| size | 50 | 100 | 500 | 1000 | 5000 |
|---|---|---|---|---|---|
| raw-campaign | 4.7±2.2 | 6.3±3.2 | 9.7±4.3 | 12.5±5.2 | **16.3±4.4** |

per-user model เรียน baseline ได้แม่นขึ้นเรื่อยๆ → สนับสนุน abstention tiers (แผน §5)

### E > D ที่ raw = sequence framing มีค่าจริง

raw-campaign ที่ 5000: **E 16.3% vs D 8.5%** — การมองเป็น window จับ campaign ได้เกือบ 2 เท่าของ point
(เดิมวัดด้วย effective อย่างเดียวจึงเห็นทั้งคู่เป็น ~0 และสรุปผิดว่า "sequence ไม่ช่วย")

### ต้นทุนของ F (size 5000)

| | A (L1+L2) | F | ต่าง |
|---|---|---|---|
| campaign surfaced | 41.3±11.1% | **57.7±7.3%** | **+16.4pp** |
| L3-unique (attack ทั้งหมด) | 0 | **5.1±1.3%** | **+5.1pp** |
| **challenge FPR** | 1.6±0.2% | **1.6±0.2%** | **+0.0** ✅ |
| warn FPR | 2.8±0.1% | 3.6±0.4% | +0.8pp |

**overlap 11.3%** = สัญญาณที่ L1/L2 จับอยู่แล้ว — มีอยู่จริงแต่ไม่ท่วม (ยืนยันว่า feature ownership
ที่ทำไว้ช่วยลดความซ้ำได้ผล โดยไม่ต้องพึ่ง SHAP duplicate ratio)

---

## สิ่งที่ implement ตามแผน (ผ่าน TDD 14/14)

| แผน | ทำอะไร |
|---|---|
| §4 two-tier threshold | `CAL_FPR=0.01` → anomaly · `EXTREME_FPR=0.001` → extreme · บันทึก `shadow_decision` = `would_warn`/`would_challenge` |
| §5 abstention tiers | `abstain <100` · `diagnostic 100–999` (ให้คะแนน+log แต่ห้ามเปลี่ยน decision) · `warn ≥1000` · `challenge ≥2000` |
| §7 metrics | `l3_raw_unique` · `l3_unique` (effective) · `l3_overlap` แยก campaign/ทั้งหมด |
| §9 data contract | `to_contract()` → `eligible/eligibility/raw_score/percentile/decision/tier/score/model_version/n_history` ส่งออกใน `evaluate_login_risk()["l3_sequence"]` + log |

**ความปลอดภัยที่ยึดไว้:** แม้ `tier=extreme` **decision จริงยกได้แค่ warn** — `would_challenge` เก็บไว้
วิเคราะห์เท่านั้น ยังไม่ enforce จนกว่าจะผ่าน production replay (แผน §10)

## ที่ไม่ทำ — SHAP duplicate ratio (§6)

คำถาม "L3 ตรวจซ้ำกับ L1/L2 แค่ไหน" ตอบได้แล้วด้วย **metric `overlap` (11.3%)** ซึ่งวัดจาก decision
จริง + การเทียบ config B/C/D (all-23 → continuous → residual) ที่แสดงว่าตัดฟีเจอร์ซ้ำแล้วดีขึ้น
→ SHAP บน per-user IForest (ต้องใช้ PermutationExplainer, ช้ามาก) ให้ข้อมูลเดิมด้วยต้นทุนสูงกว่า

---

## ข้อสรุป

> **แผนวินิจฉัยถูก: L3 มี raw signal จริง (16.3%) แต่กลไกรวมผลเดิมไม่ปล่อยให้สัญญาณนั้นเปลี่ยน decision**
> เมื่อแยกวัด raw/effective จึงเห็นชัด — และการแก้ที่ integration (config F) ปลดล็อกทั้งหมด
> โดย **challenge FPR ไม่ขยับเลย**

**ยังต้องทำก่อน enforce:** production replay · ยืนยัน precision บน traffic จริง · rollback test

**ไฟล์:** `app/security/l3_sequence.py` (tiers/two-tier/contract) · `tests/test_l3_sequence.py` (14 tests) ·
`ml-service/scripts/lc_l3_sequence.py` (configs A/D/E/F + raw/effective/overlap)
