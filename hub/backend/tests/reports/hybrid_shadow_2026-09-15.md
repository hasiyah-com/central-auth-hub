# Hybrid Shadow — นำ L3 เข้า L4 โดยไม่แตะการตัดสินจริง (ขั้นที่ 3, 4, 10, 11)

วันที่ 15 ก.ย. 2569 · commit ฐาน `9dd2278` (งานนี้ยังไม่ commit ขณะเขียนรายงาน)

## สถานะ

| รายการ | ผล |
|---|---|
| ขั้นที่ 11 — เทสก่อน implementation | **เสร็จ** — RED 17 failed ก่อนแก้โค้ด |
| ขั้นที่ 3 — โหมด `shadow_hybrid` / `monitor_only` | **เสร็จ** |
| ขั้นที่ 4 — คำนวณผลสองชุดต่อหนึ่ง login | **เสร็จ** |
| ขั้นที่ 10 — ฟิลด์บันทึก + เกณฑ์ส่งเข้า Expert Review | **เสร็จ** — ครึ่งหลังทำ 17 ก.ย. (§10) |
| ชุดเทสเต็ม | **1221 passed · 21 skipped · 0 failed** (§6) |
| state รั่ว | ไม่มี |
| ขั้นที่ 7 — calibration artifact | **ยังไม่ทำ** — `calibrated=false` ทุกแถว |
| เปิด `shadow_hybrid` บนระบบจริง | **ยังไม่เปิด** — คอนเทนเนอร์ยังเป็น `l3_mode=shadow` |

---

## 1. ปัญหาที่แก้

แผนต้องการคำนวณ **hybrid เป็นผลจำลองควบคู่ baseline** แต่โค้ดเดิมเป็นสวิตช์สองทาง
ที่ไม่มีทางเลือกนั้นเลย

```python
if mode != "hybrid_stepup":
    anomaly.eligible = False   # L4 ไม่นับ L3 เลย
```

* `l3_mode=shadow` (ค่าที่รันอยู่) — L3 ถูกปิดไม่ให้เข้า L4 ผลคือ L1+L2 ล้วน
* `l3_mode=hybrid_stepup` — L3 เข้า L4 **และมีผลต่อผู้ใช้จริง**

ผลคือ `counterfactual` ที่มีอยู่เดิมเป็น no-op ในโหมดที่ใช้งานจริง (ทั้งสองข้าง
เหมือนกันเป๊ะ) จึงยังไม่เคยมีการคำนวณ hybrid บนเหตุการณ์จริงเลยแม้แต่ครั้งเดียว
และตอบไม่ได้ว่า Isolation Forest เพิ่มประโยชน์เท่าไร

---

## 2. ขั้นที่ 11 — เขียนเทสก่อน (RED)

`tests/test_shadow_invariant.py` เขียนเสร็จก่อนแตะ implementation

```
17 failed, 10 passed
KeyError: 'hybrid_shadow'
KeyError: 'baseline_shadow'
KeyError: 'combined_method'
```

10 ตัวที่ผ่านตั้งแต่ RED ไม่ใช่การผ่านแบบว่างเปล่า — เป็นกลุ่มที่ยืนยันพฤติกรรม
ที่ถูกอยู่แล้ว: โหมดที่ไม่รู้จักต้องไม่เปิดสิทธิ์เพิ่ม, router ไม่อ่านผลจำลอง
ไปตัดสิน, และจำนวนจุดเรียก risk engine ตรงกับรายชื่อในเทส

---

## 3. ขั้นที่ 3 — โหมดที่ประกาศชัด

| ค่า | L3 ถูกเรียก | เข้าผล hybrid | มีผลต่อผู้ใช้ |
|---|---|---|---|
| `off` | ไม่ | ไม่ | ไม่ |
| `monitor_only` | เรียก | **ไม่** | ไม่ |
| `shadow` | เรียก | ไม่ | ไม่ |
| `shadow_hybrid` | เรียก | **ใช่** | **ไม่** |
| `hybrid_stepup` | เรียก | ใช่ | ใช่ |

โหมดที่ไม่รู้จักได้สิทธิ์ต่ำสุดเสมอ — ยืนยันด้วย
`test_unknown_mode_never_lets_l3_into_l4` ที่ป้อนค่าปลอม `hybrid_block_someday`
แล้วผลต้องเท่ากับ `off` เป๊ะ

---

## 4. ขั้นที่ 4 — ผลสองชุดต่อหนึ่ง login

ทั้งสองชุดใช้ **Policy Gate เดียวกัน หลักฐาน L1/L2 เดียวกัน และ `fuse` ตัวเดียวกัน**
ความต่างจึงมาจาก L3 ล้วน

```python
baseline_shadow = fuse(policy, l1_l2, **kw)                  # L1 + L2
hybrid_shadow   = fuse(policy, [*l1_l2, anomaly_live], **kw) # L1 + L2 + L3
```

### จุดที่ต้องระวังและแก้ไว้แล้ว

**หลักฐาน L3 ต้องมีสองชุดจากผลเดียวกัน** — เดิมโค้ดแก้ `anomaly.eligible = False`
บน object เดิม ถ้าคงไว้แล้วเอา object เดียวกันไปคำนวณ hybrid ด้วย ผล hybrid
จะไม่นับ L3 ตามไปด้วยโดยไม่มีใครรู้ จึงสร้าง `anomaly_live` กับ `anomaly_muted`
แยกกัน

**คำของผลจำลองต้องขึ้นต้น `would_` ทุกตัวรวม allow** — `fuse(shadow_mode=True)`
เติม `would_` เฉพาะ action ที่ไม่ใช่ allow เพราะในโหมด shadow คำว่า "allow"
คือสิ่งที่ผู้ใช้ได้รับจริง ๆ แต่ `baseline_shadow`/`hybrid_shadow` เป็นผลจำลองล้วน
ถ้าใช้คำเดียวกันจะมีวันที่มีคนอ่านปนกัน จึงเติมผ่าน `_would()` ให้ขาดจากของจริง

**abstain ไม่ใช่ศูนย์** — มุมมองที่ประวัติไม่พอคืน `None` ไม่ใช่ `0.0`
มีเทสแยกสองกรณีนี้ออกจากกันโดยเฉพาะ (`test_zero_evidence_is_not_the_same_as_abstain`)

---

## 5. ขั้นที่ 10 — ฟิลด์บันทึก

migration `f6a7b8c9d0e1` เพิ่ม 16 คอลัมน์ + 2 index ลง `login_sessions`
ทุกคอลัมน์ nullable ไม่มี default (`NULL` = เกิดก่อนมีการบันทึกผลจำลอง
ไม่ใช่ "คำนวณแล้วได้ศูนย์" — B51)

```
แถวก่อน migrate 1856 -> หลัง migrate 1856
downgrade -1  -> คอลัมน์ตัวอย่างหายครบ (0/3)
upgrade head  -> กลับมาครบ (3/3)
alembic check -> drift เท่าเดิม ไม่มีรายการใหม่จาก migration นี้
```

### ทำไมต้องเป็นคอลัมน์จริง ไม่ใช่ JSON อย่างเดียว

`expert_alert_groups` มีคอลัมน์ provenance อยู่แล้ว แต่ `sync_groups()` เติมค่าจาก
settings **ตอน sync** ไม่ใช่ค่าที่ใช้จริงตอนเกิดเหตุ ถ้าคอนฟิกเปลี่ยนกลางหน้าต่าง
30 นาที กลุ่มจะถูกติดป้ายผิดโดยไม่มีอะไรฟ้อง — เก็บที่ระดับ login จึงเป็นที่เดียว
ที่พิสูจน์ที่มาได้จริง (B66)

ส่วนคะแนนรายมุมมองของ L3 ยังอยู่ใน `risk_breakdown["l3"]` ตามที่แผนอนุญาตให้เก็บ
เป็น JSON ในช่วงแรก

### จุดแปลงค่าเดียวในระบบ

`app/services/shadow_record.py:shadow_columns()` — ทั้ง 5 เส้นทาง login เรียก
ฟังก์ชันเดียวกัน ไม่คัดลอกตรรกะไปไว้ที่ router · มีเทสอ่านซอร์สนับจุดเรียกว่าครบ 5
(`test_every_login_session_site_records_shadow_columns`) ถ้ามีใครเพิ่มเส้นทาง
login ใหม่แล้วลืม เทสจะล้มทันที

---

## 6. ผลเทส

### ไฟล์ของงานนี้

```
tests/test_shadow_invariant.py — 34 passed
```

### ชุดเต็ม — สองรอบ ก่อนและหลังตัดสินใจเรื่อง freeze

| รอบ | ผล | หมายเหตุ |
|---|---|---|
| ก่อน re-freeze | **1 failed** · 1219 passed · 21 skipped (208.37 s) | ตัวกัน scoring freeze ล้มตามที่ควรล้ม |
| หลัง re-freeze | **0 failed** · 1221 passed · 21 skipped (205.82 s) | ไม่มี state รั่ว |

`1221 = 1187 เดิม + 34 ตัวใหม่` · manifest ของ seed `f7c41f7af1b07b93` เท่ากับ
ทุกรอบในรายงาน test isolation จึงเทียบกันได้โดยตรง

ตัวที่ล้มรอบแรกคือ `test_scoring_freeze.py::test_scoring_logic_unchanged_since_freeze`

```
scoring logic เปลี่ยนหลัง freeze (2026-09-07T17:09:13+00:00)
    เปลี่ยน: ['app/security/risk_engine.py']
    เพิ่ม: []   หายไป: []
```

**เป็นตัวกันที่ทำงานถูกต้อง ไม่ใช่บั๊ก** — บันทึก freeze ระบุเงื่อนไขปลดว่า
"รอบ P48 จบ หรือมีการตกลงร่วมกันให้เปลี่ยน scoring" ซึ่ง holdout ของ P48-T2
ยังไม่เปิด จึงเข้าเงื่อนไขที่สองเท่านั้น และต้องเป็นการตัดสินใจที่ตั้งใจ
ไม่ใช่การอัปเดต hash ให้เทสเขียว

สิ่งที่ตรวจก่อนเสนอให้ตัดสินใจ

| ข้อ | ผลตรวจ |
|---|---|
| ไฟล์ที่ freeze อีก 9 ไฟล์ | **ไม่เปลี่ยนเลย** — เปลี่ยนแค่ `risk_engine.py` |
| harness ของการทดลอง import `risk_engine` ไหม | **ไม่** — `ml-service/scripts/hybrid_experiment/` เรียก `risk_fusion`, `risk_evidence`, `policy_gate`, `iforest_scorer`, `risk_aggregator`, `evidence` โดยตรง |
| การตัดสินจริงในโหมด `shadow` เปลี่ยนไหม | **ไม่** — เทส 5 เส้นทางยืนยัน |

แปลว่าตัวเลข P48/P48-T2 ไม่ได้ไหลผ่านไฟล์ที่แก้

### การตัดสินใจ — re-freeze (อนุมัติแล้ว 15 ก.ย. 2569)

บันทึกใหม่ระบุเหตุผลและเงื่อนไขปลดไว้ครบ diff ยืนยันว่า **hash เปลี่ยนไฟล์เดียว**

```
frozen_at      2026-09-07T17:09:13Z  ->  2026-09-15T14:31:05Z
git_commit     unavailable           ->  9dd22787188a0c86362d83dc69078e05e4f71ce2
git_branch     unavailable           ->  feature/hybrid-risk-round2
unfreeze_when  รอบ P48 จบ            ->  รอบ Hybrid Shadow Pilot จบ (ขั้นที่ 14-16)

risk_engine.py  218291bb...  ->  ea762aa3...
อีก 9 ไฟล์      ไม่เปลี่ยน (ไม่ปรากฏใน diff)
```

บันทึกเดิมไม่ได้หายไป — อยู่ในประวัติ git และบันทึกใหม่เก็บ commit ต้นทางไว้
(ของเดิมบันทึกไม่ได้เพราะรันในคอนเทนเนอร์ที่ไม่มี `git` รอบนี้รันจาก host จึงได้ค่าจริง)

---

## 7. หลักฐานจากเส้นทางจริง

เรียก `passkey._build_login_session` **ตัวจริงที่ production เรียก** (ไม่ใช่สำเนา)
ด้วยผู้ใช้ที่ seed ไว้ แล้วอ่านแถวที่ได้ ตั้ง `l3_mode=shadow_hybrid` ชั่วคราว

```json
{
  "decision (จริง)": "allow",
  "risk_score (จริง)": 0.2,
  "baseline_shadow": [0.2, "would_allow"],
  "hybrid_shadow": [0.417634, "would_allow"],
  "l3_changed_shadow_decision": false,
  "l3_eligibility": "abstain",
  "l3_n_history": 0,
  "calibrated": false,
  "calibration_version": null,
  "shadow_epoch_id": null,
  "latency_total_ms": 105,
  "latency_l3_ms": 83,
  "actual_decision_source": "passkey_login"
}
```

อ่านได้ว่า

* การตัดสินจริง `allow` ที่ 0.200 **เท่ากับ baseline เป๊ะ** — L3 ไม่ได้ขยับอะไรของผู้ใช้
* hybrid ขึ้นไป 0.418 จากมุมมอง **point** ทั้งที่ sequence ยัง abstain
  (ประวัติ 0) — abstain เป็นราย *มุมมอง* ไม่ใช่ทั้งชั้น
* คะแนนขยับแต่ผลไม่เปลี่ยน จึงบันทึก `l3_changed_shadow_decision=false`
  ตรงตามหลักที่ตกลงไว้ว่า **คะแนนขยับเฉย ๆ ไม่นับเป็นคุณค่าของ L3**
* `calibrated=false` และ `calibration_version=null` — บันทึกตามจริง ไม่เดาค่า
* L3 ใช้เวลา 83 ms จาก 105 ms ของทั้งเส้นทาง

---

## 8. สิ่งที่ยังไม่ทำ

| งาน | สถานะ |
|---|---|
| ขั้นที่ 7 — calibration artifact + SHA + fail-closed | ยังไม่เริ่ม · ต้องตัดสินก่อนว่าจะสร้างจาก validation ชุดไหน (ห้ามสร้างจากผลเก่าที่ปะติดปะต่อ) |
| ขั้นที่ 6 — รายงานอัตรา abstain แยก 6 ช่วงประวัติ | ยังไม่มี (คอลัมน์ `l3_eligibility`/`l3_n_history` พร้อมแล้ว) |
| ขั้นที่ 9 — ยืนยันว่า SHAP ไม่ถูกคำนวณทุก login | ยังไม่ตรวจ |
| ขั้นที่ 12-17 | ยังไม่เริ่ม |
| เปิด `shadow_hybrid` บนคอนเทนเนอร์จริง | **ยังไม่เปิด** — ต้องมี calibration artifact ก่อน ไม่งั้นจะเก็บผลจำลองที่ยังไม่ calibrate |

---

## 9. วิธีรัน

```bash
bash scripts/test/setup_test_db.sh
bash scripts/test/run_tests.sh tests/test_shadow_invariant.py
bash scripts/test/run_tests.sh                        # ชุดเต็ม
```

ตรวจ migration ไป-กลับ

```bash
docker compose exec hub-backend alembic downgrade -1
docker compose exec hub-backend alembic upgrade head
```

---

## 10. ขั้นที่ 10 ครึ่งหลัง — เกณฑ์ส่งเข้า Expert Review (17 ก.ย. 2569)

### ปัญหา

sync เลือกเฉพาะ login ที่ `decision` เป็น `would_*` · ในโหมด `shadow_hybrid` การตัดสินจริง
ยังเป็น L1+L2 เหตุการณ์ที่ L3 เท่านั้นเห็นจึงไม่เคยถึงผู้เชี่ยวชาญ และที่มาของคอนฟิกของ
กลุ่มยังรับจาก settings ตอน sync ทั้งที่ตอนนี้ `login_sessions` มีค่าต่อแถวแล้ว

### ที่แก้

| จุด | เดิม | ใหม่ |
|---|---|---|
| เกณฑ์คัดเหตุการณ์ | `decision` เป็น `would_*` | `would_*` **หรือ** `l3_changed_shadow_decision` **หรือ** `l3.monitoring_decision == l3_investigate` |
| signal ของกลุ่ม | L1/L2 ของการตัดสินจริง | alert จริงใช้ของเดิม · เหตุการณ์ของ L3 อย่างเดียวได้ `anomaly:l3_changed_shadow` / `anomaly:l3_investigate` ไม่ปนกลุ่มกัน |
| ที่มาของคอนฟิก | settings ตอน sync | ค่าที่ทุกแถวในกลุ่มตรงกัน · ไม่ตรงกันหรือว่าง = None |
| `model_output` ของ disposition | ผลการตัดสินจริง | เพิ่ม `selected_because`, ผลจำลองสองชุด, `l3_monitoring_decision`, `shadow_epoch_id` |
| `POST /groups/sync` | คืน `epoch` | คืน `current_epoch` (ใช้ดูอย่างเดียว ไม่ถูกเขียนลงกลุ่ม) |

รอบ blind ยังไม่เห็นเหตุผลที่กลุ่มถูกสร้าง — `blind_payload` อ่านจากรายการที่อนุญาตเท่านั้น
และมีเทสยืนยันว่าคำอย่าง `l3_changed_shadow`, `hybrid`, `baseline`, `would_` ไม่หลุดออกไป

### ผล

```
RED    tests/test_expert_review_shadow_selection.py  14 failed
       (ไม่มี selection_reasons / signal_for / group_epoch · sync ยังบังคับ epoch)
GREEN  expert review ทั้ง 4 ไฟล์ 142 passed
ชุดเต็ม (Functional Gate) 1289 passed · 23 skipped · 3 deselected · 0 failed · ไม่มี state รั่ว
```

แถวที่เกิดก่อนมีการบันทึกที่มา (NULL) จะได้กลุ่มที่ `risk_config_id` / `scoring_commit`
เป็น None และ `eligible_for_production_metrics = false` — ไม่ถูกติดป้ายด้วยคอนฟิกที่รันอยู่
