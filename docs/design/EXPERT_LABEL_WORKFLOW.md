# ออกแบบ Expert Label Workflow

ร่าง 9 ก.ย. 2569 · ขั้นที่ 4 ของแผนก่อน deploy Shadow
**เอกสารออกแบบ — ยังไม่สร้าง** ต้องตกลงก่อนลงมือ

---

## 0. ทำไมต้องมี และทำไมของเดิมไม่พอ

ตาราง `ml_feedback` มีอยู่แล้ว (8 แถว) ใช้ผ่าน `routers/ml_admin.py`

```
session_id · label (false_positive | true_positive | normal_confirmed)
note · marked_by · created_at
```

มีจุดอ่อนที่ตรงกับสิ่งที่งานนี้ต้องเลี่ยงพอดี

| จุดอ่อน | ทำไมสำคัญ |
|---|---|
| คำศัพท์ label อิงผลของโมเดล (`false_positive`) | ผู้ตรวจต้องรู้ว่าโมเดลตัดสินอะไรก่อนจึงจะตอบได้ → **blind review เป็นไปไม่ได้โดยโครงสร้าง** |
| ไม่มี `insufficient_context` | บังคับให้ผู้ตรวจเลือกข้างแม้ข้อมูลไม่พอ |
| ไม่มี confidence / reason codes | เอาไปวิเคราะห์ต่อไม่ได้ ได้แค่นับ |
| ไม่มี config / calibration / commit | พิสูจน์ย้อนหลังไม่ได้ว่า label นั้นตรวจโมเดลรุ่นใด |
| ผู้ตรวจคนเดียวต่อ session | วัด inter-rater agreement ไม่ได้ |
| หน่วยเป็น session เดี่ยว | alert 10 ครั้งจากผู้ใช้คนเดียวใน 5 นาทีถูกนับเป็น 10 เหตุการณ์อิสระ |

**ข้อเสนอ:** สร้างชุดตารางใหม่และ **ไม่แก้ `ml_feedback`** · คงของเดิมไว้เพื่อไม่ให้
ตัวเลขที่เคยรายงานเปลี่ยน แต่ประกาศเลิกใช้สำหรับงานนี้ พร้อมบันทึกว่า 8 แถวเดิม
**ไม่ถูกนำมารวม** เป็นหลักฐานของรอบใหม่

---

## 1. หน่วยที่ตรวจ — alert group ไม่ใช่ login event เดี่ยว

**ปัญหา:** ถ้าให้ตรวจทีละ login event ผู้ใช้ที่ทริกเกอร์ 10 ครั้งจากเหตุเดียวกัน
(เช่น เปลี่ยนเครื่องแล้ว login ซ้ำ) จะกินเวลาผู้เชี่ยวชาญ 10 เท่าโดยได้ข้อมูลเท่าเดิม
และทำให้สถิติเอนไปทางผู้ใช้ที่ login ถี่

**ปัญหาตรงข้าม:** ถ้าตรวจเป็น incident อย่างเดียว จะคำนวณ per-event FPR ไม่ได้

**ทางออก — เก็บทั้งสองระดับ**

```
alert_group          หน่วยที่ผู้เชี่ยวชาญตรวจ (1 label ต่อ 1 group)
  └── login_session   ทุก event ที่อยู่ในกลุ่มนั้น (label ตกทอดลงมา)
```

กติกาการจัดกลุ่ม (deterministic ทำซ้ำได้)

```
group_key = (user_id, สัญญาณหลักที่ทริกเกอร์, หน้าต่างเวลา 30 นาที)
```

- "สัญญาณหลัก" = `resolver.primary_layer` + reason code แรกที่เรียงแล้ว
- event ที่เกิดในหน้าต่างเดียวกันและมี key เดียวกัน = กลุ่มเดียว
- **บันทึกทุก `session_id` ที่อยู่ในกลุ่มไว้** เพื่อกระจาย label กลับลงระดับ event

**ผลต่อการคำนวณ**

| ตัวชี้วัด | คำนวณที่ระดับ |
|---|---|
| alert yield · precision · inter-rater agreement | alert group |
| per-user FPR (เทียบงบ 1%) | login event หลังกระจาย label ลงมาแล้ว |

---

## 2. ข้อมูลที่ผู้เชี่ยวชาญเห็น

### 2.1 รอบแรก — blind

| แสดง | ซ่อน |
|---|---|
| เวลา (เขตเวลาไทย) และวันในสัปดาห์ | `final_risk_score` |
| อุปกรณ์: ชนิด / OS / browser family | `decision` และ `would_*` |
| subsystem ที่เข้าถึง | คะแนนรายชั้น L1/L2/L3 |
| ประเทศ (ถ้า resolve ได้) | `evidence_level` |
| **สัญญาณเชิงพรรณนา** ของ L1/L2/L3 | เกณฑ์ที่ใช้ |
| ประวัติย่อของผู้ใช้ 90 วัน | — |

**"สัญญาณเชิงพรรณนา" คืออะไร** — ข้อความที่บอก *ข้อเท็จจริงที่สังเกตได้* ไม่ใช่คะแนน

```
แสดง:   "อุปกรณ์นี้ไม่เคยพบในประวัติ 90 วัน"
        "เข้าใช้ SUB_A ครั้งแรก (ก่อนหน้านี้ใช้ HUB 142 ครั้ง)"
        "ห่างจากช่วงเวลาที่ใช้ประจำ 6 ชั่วโมง"
ห้าม:   "rule evidence = 1.0 (extreme)"
        "final_risk_score = 0.9955"
```

**ประวัติย่อ 90 วัน** — จำนวน login, อุปกรณ์ที่เคยใช้, subsystem ที่เคยใช้,
ช่วงเวลาที่ใช้บ่อย · เพียงพอให้ตัดสินว่า "ผิดปกติสำหรับคนนี้ไหม" โดยไม่ต้องเห็นคะแนน

### 2.2 รอบสอง — unblinded (ทางเลือก)

หลังบันทึก label รอบแรกแล้ว **ล็อกไม่ให้แก้** จึงเปิดคะแนนให้ดูเพื่อคุยเรื่อง
calibration ได้ · ความเห็นรอบสองเก็บเป็น record แยก `round = 2` ไม่ทับของเดิม

---

## 3. Schema

### 3.1 `alert_review_queue` — หน่วยที่ตรวจ

```json
{
  "id": "uuid",
  "group_key": "user:1a2b|rule:impossible_travel|w:2026-09-09T14:00",
  "user_id": "uuid",
  "session_ids": ["uuid", "..."],
  "n_events": 3,
  "first_seen_at": "2026-09-09T14:03:11Z",
  "last_seen_at": "2026-09-09T14:21:44Z",

  "shadow_epoch_id": "config-b-shadow-v1",
  "risk_config_id": "config-b-shadow-v1",
  "calibration_version": "calibration-v1",
  "calibration_sha256": "...",
  "scoring_commit": "...",
  "feature_snapshot_sha256": "...",

  "system_disposition": "would_challenge",
  "provenance": "external | local | demo | unknown",
  "eligible_for_production_metrics": true,
  "created_at": "..."
}
```

### 3.2 `alert_review_label` — คำตอบของผู้ตรวจ (append-only)

```json
{
  "id": "uuid",
  "queue_id": "uuid",
  "reviewer_id": "uuid",
  "round": 1,
  "model_output_visible": false,
  "reviewed_at": "...",
  "time_spent_sec": 47,

  "verdict": "benign | suspicious | confirmed_attack | insufficient_context",
  "confidence": "low | medium | high",
  "reason_codes": ["expected_new_device", "legitimate_subsystem_use"],
  "comment": "...",

  "supersedes_id": null
}
```

**append-only** — การแก้ label สร้างแถวใหม่ที่ชี้ `supersedes_id` กลับไปยังของเดิม
ประวัติจึงตรวจย้อนได้ครบตามที่กำหนด

### 3.3 `reason_codes` ที่ประกาศไว้ล่วงหน้า

| กลุ่ม | รหัส |
|---|---|
| อธิบายได้ว่าปกติ | `expected_new_device` · `expected_new_location` · `legitimate_subsystem_use` · `known_travel` · `shared_workstation` · `routine_off_hours` |
| น่าสงสัย | `impossible_travel` · `credential_abuse` · `unusual_sequence` · `unexpected_privilege_use` · `velocity_anomaly` · `device_farm_pattern` |
| ข้อมูลไม่พอ | `no_user_history` · `ambiguous_context` · `missing_geo` |

รายการนี้ **ปิด** — เพิ่มรหัสใหม่ต้องเป็นการตัดสินใจที่บันทึกไว้ ไม่ใช่พิมพ์เอง
(ถ้าปล่อยให้พิมพ์อิสระ จะรวมสถิติข้ามผู้ตรวจไม่ได้)

---

## 4. สองระดับที่ห้ามเขียนทับกัน

```
reviewer_verdict    สิ่งที่ผู้เชี่ยวชาญวินิจฉัยว่าเหตุการณ์นั้นคืออะไร
system_disposition  สิ่งที่ระบบทำ (หรือจะทำ) กับเหตุการณ์นั้น
```

**บังคับด้วยโครงสร้าง:** อยู่คนละตาราง · `system_disposition` เขียนโดยระบบตอนสร้าง
คิว และ **ไม่มี API ให้ผู้ตรวจแก้** · `reviewer_verdict` เขียนโดยผู้ตรวจเท่านั้น
และระบบไม่อ่านไปเปลี่ยนการตัดสินใด ๆ อัตโนมัติ

**ห้ามนำ label กลับไป train อัตโนมัติ** — การนำ label ไปใช้ปรับโมเดลต้องเป็น
รอบทดลองใหม่ที่ประกาศล่วงหน้า มี holdout ของตัวเอง

---

## 5. ผู้ตรวจหลายคนและการตัดสินกรณีเห็นต่าง

### 5.1 การสุ่มจ่ายงาน

- **ทุกรายการมีผู้ตรวจอย่างน้อย 1 คน**
- **สุ่ม 30% ให้ผู้ตรวจคนที่สอง** (double-review pool) — ใช้วัด agreement
- ผู้ตรวจคนที่สองไม่เห็นคำตอบของคนแรก

### 5.2 กติกาตัดสิน

| กรณี | ผลที่ใช้ |
|---|---|
| ตรงกัน | ใช้ค่านั้น |
| ต่างกันแต่ทั้งคู่อยู่ในกลุ่ม "ปกติ" หรือทั้งคู่ "น่าสงสัย" | ใช้ค่าที่อนุรักษ์กว่า |
| ต่างข้ามกลุ่ม (เช่น `benign` vs `confirmed_attack`) | **ส่งให้ผู้ตรวจคนที่สาม** ตัดสิน · บันทึกว่าเป็น adjudicated |
| ฝ่ายใดตอบ `insufficient_context` | รายการนั้น **ออกจากชุดคำนวณ FPR** แต่ยังนับใน alert yield |

### 5.3 วัด agreement

- **Cohen's kappa** บน double-review pool (รายงานพร้อม CI)
- ถ้า kappa < 0.4 ให้ถือว่านิยาม label ยังไม่ชัด **ต้องแก้คู่มือก่อนเก็บข้อมูลต่อ**
  ไม่ใช่เดินหน้าเก็บแล้วค่อยแก้ทีหลัง

---

## 6. Privacy

| หลักการ | การนำไปใช้ |
|---|---|
| แสดงเท่าที่จำเป็น | ผู้ตรวจเห็น **alias** ไม่เห็นอีเมล/ชื่อ/รหัสนักศึกษา |
| IP | แสดงแบบ mask (`203.0.113.x`) + ประเทศ · เห็นเต็มได้เมื่อกดขอพร้อมบันทึก audit |
| User agent | แสดง OS + browser family ไม่แสดงสตริงเต็ม |
| อายุข้อมูล | คิวที่ปิดแล้วเก็บ 180 วัน จากนั้นเหลือเฉพาะ label + สถิติ ลบรายละเอียดเหตุการณ์ |
| การเข้าถึง | ต้องเป็น `is_hub_admin` และบันทึก `log_action` ทุกครั้งที่เปิดดูรายการ |

**ห้ามส่งข้อมูลจริงออกนอกระบบเพื่อให้ตรวจ** — ถ้าผู้เชี่ยวชาญเป็นบุคคลภายนอก
ต้องเข้ามาตรวจในระบบ ไม่ใช่ export ไฟล์ออกไป

---

## 7. Metrics ที่จะคำนวณ และเงื่อนไขของแต่ละตัว

| ตัวชี้วัด | นิยาม | เงื่อนไข |
|---|---|---|
| **alert yield** | จำนวน alert group ต่อ 1,000 login | ใช้ได้ทันที ไม่ต้องมี label |
| **precision** | `confirmed_attack + suspicious` ÷ alert ที่ถูก label แล้ว | ต้องมี label ครบ · ไม่รวม `insufficient_context` |
| **per-user FPR** | สัดส่วน login ปกติที่ถูก flag — นับเฉพาะที่ผู้ตรวจยืนยันว่า `benign` | ต้องมี label + ผู้ใช้พอ (ดู §8) |
| **inter-rater agreement** | Cohen's kappa บน double-review pool | ต้องมี ≥ 30 รายการที่ตรวจซ้ำ |
| **false incident** | `confirmed_attack` ที่ภายหลังพิสูจน์ว่าไม่ใช่ | ต้องมีการติดตามผลย้อนหลัง |

**FPR คำนวณจากรายการที่ยืนยันว่า `benign` เท่านั้น** — alert ที่ยังไม่ตรวจหรือ
`insufficient_context` **ห้ามนับเป็น false positive** เพราะยังไม่รู้ว่าผิดจริงไหม

---

## 8. Exclusion — อะไรที่ไม่นับเป็นผล production

ทุกรายการมี `eligible_for_production_metrics` คำนวณตอนสร้างคิว

| ตัด | เหตุผล |
|---|---|
| `provenance = demo` | marker `RiskDemo` หรือ IP ตาม RFC 5737 |
| `provenance = local` | IP ภายในเครื่อง/Docker — **ระบุที่มาไม่ได้** ไม่ใช่ "สังเคราะห์" |
| `provenance = unknown` | ไม่มี IP หรือแยกไม่ได้ |
| `shadow_epoch_id` ไม่ตรงกับ epoch ที่กำลังวิเคราะห์ | คนละคอนฟิก |
| ไม่มี `risk_config_id` / `scoring_commit` | พิสูจน์ที่มาไม่ได้ |

**บันทึกจำนวนที่ถูกตัดออกทุกครั้งที่รายงาน** ไม่ใช่ตัดเงียบ

### เงื่อนไขก่อนอ้างตัวเลข production

จากข้อจำกัดที่วัดไว้แล้ว (2 ผู้ใช้ที่มี IP ภายนอก · หนึ่งคนครอง 89%) ต้อง**ประกาศ
ล่วงหน้า**ว่าจะเริ่มคำนวณ per-user FPR ก็ต่อเมื่อถึงเกณฑ์ขั้นต่ำ เช่น

```
ผู้ใช้ที่มี provenance = external          >= 20 คน
ไม่มีผู้ใช้คนใดครองเหตุการณ์เกิน           40%
alert ที่ถูก label แล้ว                     >= 100 รายการ
double-review pool                          >= 30 รายการ
```

ตัวเลขเหล่านี้เป็นข้อเสนอ ต้องตกลงและล็อกก่อนเริ่มเก็บ — ไม่ใช่ปรับตามผลที่ได้

---

## 9. ขั้นตอนการทำงานจริง

```
1. ระบบสร้าง alert group จาก shadow decision (would_*) ในหน้าต่างเวลาที่กำหนด
2. คำนวณ provenance + eligible flag + ผูก config/calibration/commit
3. เข้าคิว blind review
4. ผู้ตรวจเปิดรายการ -> เห็นเฉพาะข้อมูลใน §2.1 -> ให้ verdict + confidence + reason codes
5. 30% ถูกสุ่มให้ผู้ตรวจคนที่สอง
6. กรณีเห็นต่างข้ามกลุ่ม -> ผู้ตรวจคนที่สาม
7. label ถูกกระจายลงระดับ login event
8. คำนวณ metrics ตาม §7 โดยตัดตาม §8
```

---

## 10. สิ่งที่ต้องสร้าง (ถ้าอนุมัติแบบนี้)

| ส่วน | ไฟล์โดยประมาณ |
|---|---|
| ตาราง + migration | `models.py` เพิ่ม 2 ตาราง |
| การจัดกลุ่ม alert | `services/alert_grouping.py` |
| provenance | `services/provenance.py` (ใช้กติกาเดียวกับสคริปต์เทียบ distribution) |
| API | `routers/review.py` — คิว, ให้ label, สถิติ |
| UI | หน้าใหม่ใน console (blind โดยค่าเริ่มต้น) |
| Metrics | `services/review_metrics.py` — kappa, precision, FPR |
| เทส | จัดกลุ่ม deterministic · blind ไม่รั่ว · label ไม่ทับ disposition · exclusion ถูกต้อง · kappa |

**ประเมินขนาดงาน:** ส่วน backend + เทส เป็นงานหลัก · UI ทำเป็นหน้าเดียวแบบ minimal
ก่อนได้ เพราะผู้ตรวจมีไม่กี่คน

---

## 11. คำถามที่ต้องตัดสินก่อนสร้าง

1. **ใครคือผู้เชี่ยวชาญ** และมีกี่คน — กำหนดว่าจะทำ double review ได้จริงไหม
   ถ้ามีคนเดียว ต้องยอมรับว่าวัด agreement ไม่ได้ และบันทึกเป็นข้อจำกัด
2. **หน้าต่างจัดกลุ่ม 30 นาที เหมาะไหม** — ยาวไปจะรวมเหตุการณ์คนละเรื่อง สั้นไปจะแตกเป็นหลายกลุ่ม
3. **เกณฑ์ขั้นต่ำใน §8** ยอมรับได้ไหม หรือจะตั้งต่างจากนี้
4. **จะเก็บ `ml_feedback` เดิมไว้เฉย ๆ หรือ migrate** 8 แถวเข้ามาในโครงใหม่
   (ผมเสนอให้เก็บไว้เฉย ๆ และไม่นำมารวม เพราะ label เดิมไม่ได้ผ่าน blind review)
5. **รอบสอง unblinded จะทำไหม** — มีประโยชน์เรื่อง calibration แต่เพิ่มงานผู้ตรวจเท่าตัว
