# สืบเหตุการณ์ที่ถูก enforce ใน Shadow Mode + ตรวจที่มาของข้อมูล

วันที่ 9 ก.ย. 2569 · ขั้นที่ 1–2 ของแผนก่อน deploy Shadow
**ผลสรุป: ไม่พบ shadow safety bug ในเส้นทาง production — เป็นข้อมูล demo ที่ถูก insert ด้วยสคริปต์**

---

## 1. ที่มาของการตรวจ

ระหว่างสำรวจความพร้อมก่อน deploy Shadow พบว่าใน `login_sessions` มี decision ที่
**บังคับใช้จริง** (`challenge` / `block` ไม่ใช่ `would_*`) ทั้งที่ `ML_SHADOW_MODE=true`

คัดเฉพาะแถวที่มาจากเส้นทาง fusion ใหม่ (`risk_breakdown->>'fusion' = 'max_corroboration'`)
ได้ **3 แถว** ซึ่งต้องอธิบายให้ได้ก่อนไว้ใจข้อมูลชุดนี้

---

## 2. หลักฐานของทั้ง 3 แถว

| รายการ | แถว 1 | แถว 2 | แถว 3 |
|---|---|---|---|
| `created_at` | 2026-09-08 03:20:48 | 05:29:48 | 09:45:48 |
| `user_id` (ย่อ) | `70c839b5` | `70c839b5` | `70c839b5` |
| `decision` | block | block | challenge |
| `risk_score` | 1.000 | 1.000 | 0.500 |
| `anomaly_score` | 0.50 | — | — |
| `fusion` | `max_corroboration` | `max_corroboration` | `max_corroboration` |
| `policy.denied` | false | false | false |
| `policy.min_action` | null | challenge | challenge |
| `resolver.primary_layer` | rule | rule | rule |
| `gamma` (ใน breakdown) | 0.35 | 0.35 | 0.35 |
| `subsystem_id` | null (Hub-direct) | null | null |
| **`ip`** | **`203.0.113.10`** | **`192.0.2.55`** | **`203.0.113.10`** |
| **`user_agent`** | **`Mozilla/5.0 (RiskDemo; …)`** | `RiskDemo` | `RiskDemo` |

หลักฐานเพิ่มเติมจาก breakdown ของแถว 1

```
evidence.rule     raw=1.0  "impossible_travel: US -> TH in -4.0h (< 1h)"  level=extreme
evidence.behavior raw=0.2  "hours_diff=6.0 >= 6 (+0.20)"                  level=none
evidence.anomaly  raw=0.5019  abstain_reason="l3_mode=shadow"  eligible=false
resolver          final_score=1.0  policy_denied=false  primary_layer=rule
```

คะแนน 1.0 มาจากกฎ L1 (`impossible_travel`) ล้วน ไม่ใช่จาก Policy Gate

### ไทม์ไลน์ของผู้ใช้รายนี้ในวันเดียวกัน

```
03:20:48  block      score=1.000
05:19:48  allow      score=0.000
05:29:48  block      score=1.000
09:15:48  allow      score=0.000
09:45:48  challenge  score=0.500
```

ทุกแถวลงท้ายวินาที `:48` เหมือนกันหมด — ลายเซ็นของข้อมูลที่ถูก insert ด้วยสคริปต์
โดยตั้งเวลาฐานแล้วเลื่อนเป็นนาที ไม่ใช่การเข้าสู่ระบบจริง

---

## 3. การแยกหมวดตามที่กำหนดไว้

| หมวด | คำอธิบาย | สถานะ | เหตุผล |
|---|---|---|---|
| **A** | Hybrid model เปลี่ยน access decision จริง | **ตัดออก** | คะแนนมาจากกฎ L1 จริง แต่ทั้งเหตุการณ์เป็นข้อมูลสังเคราะห์ ไม่มีผู้ใช้จริงถูกกระทบ |
| **B** | Policy Gate บังคับตามนโยบาย | **ตัดออก** | `policy.denied = false` ทั้ง 3 แถว · แถว 1 ไม่มี `min_action` ด้วยซ้ำ |
| **C** | Caller ไม่ได้ส่ง `shadow_mode=True` | **ตัดออก** | ทั้ง 5 call site ส่ง `shadow_mode=settings.ml_shadow_mode` ครบ |
| **D** | Container โหลด environment เก่า | **ตัดออก** | container ปัจจุบันอ่าน `ml_shadow_mode = True` และไม่มีโค้ดแปลง `would_*` กลับเป็น enforced |
| **E** | คนละ code path / ข้อมูลเก่า | **ยืนยัน** | marker `RiskDemo` ใน user agent + IP ในช่วงสงวนตาม RFC 5737 |

### หลักฐานที่ตัดหมวด C และ D

**call site ทั้งหมดที่เรียก `evaluate_login_risk`**

```
routers/auth.py:472,983,1373   shadow_mode=settings.ml_shadow_mode
routers/passkey.py:152          shadow_mode=settings.ml_shadow_mode
routers/oauth.py:597            shadow_mode=settings.ml_shadow_mode
```

**การแปลงเป็น shadow ใน `risk_fusion.fuse`** ครอบคลุมทุกเส้นทางรวมถึง policy denial

```python
# policy denied
decision = "would_block" if shadow_mode else "block"
# score-driven
decision = f"would_{action}" if (shadow_mode and action != "allow") else action
```

`passkey.py:202` ยังบังคับ `would_block` ซ้ำอีกชั้นเป็นการป้องกันซ้อน

**ค่าที่ container อ่านได้จริง** (ตรวจตาม B36 — `restart` ไม่ re-read `.env`)

```
ML_SHADOW_MODE=true
ml_shadow_mode = True · l3_mode = shadow
l4_gamma = 0.35 · thresholds = 0.5 / 0.7 / 0.85
```

---

## 4. ตัวเขียนข้อมูล

| ไฟล์ | บทบาท |
|---|---|
| `hub/backend/tests/test_risk_live_demo.py` | สร้างแถว demo · ฝัง marker `RiskDemo` ใน user agent · มีคำสั่งลบข้อมูลของตัวเอง |
| `hub/backend/scripts/evaluate_real_logins.py:43` | มี `SYNTHETIC_UA_MARKERS = ("RiskDemo",)` และ `SYNTHETIC_EMAILS` อยู่แล้ว |

กลไกกันข้อมูล demo ปนจึง **มีอยู่ในโปรเจกต์แล้ว** แต่ใช้เฉพาะภายในสคริปต์นั้น
ไม่ได้บังคับที่ระดับฐานข้อมูลหรือที่ตัวอ่านอื่น ๆ

---

## 5. ประเด็นที่ค้นพบเพิ่มและควรบันทึก

สคริปต์ demo เขียนค่า `decision` เป็น `block` / `challenge` ตรง ๆ และ
**แยกจากข้อมูลจริงไม่ได้จากคอลัมน์ `decision` หรือ `risk_breakdown`** —
ต้องดู user agent หรือ IP เท่านั้น

ผลกระทบ: แดชบอร์ดหรือสถิติใดที่นับ `decision` จาก `login_sessions` โดยไม่กรอง
จะเห็น block ปลอม 2 ครั้งและ challenge ปลอม 1 ครั้งเป็นของจริง

**ข้อเสนอ** (ยังไม่ได้ทำ รอการตัดสินใจ): ทุกแถวที่เกิดหลังจากนี้ควรบันทึก
`risk_config_id`, `calibration_version`, `scoring_commit`, `shadow_mode`,
`access_decision_source` ลงไปด้วย เพื่อให้พิสูจน์ที่มาของแต่ละแถวย้อนหลังได้
โดยไม่ต้องเดาจาก IP

---

## 6. ตรวจที่มาของข้อมูลทั้งชุด (ขั้นที่ 2)

จัดกลุ่มทั้ง 1,704 แถวใน `login_sessions`

| ที่มา | มี `risk_breakdown` | ไม่มี | รวม |
|---|---|---|---|
| localhost / Docker internal (`127.0.0.0/8`, `172.16.0.0/12`) | 1,244 | 404 | **1,648** |
| synthetic — marker `RiskDemo` | 27 | 0 | 27 |
| synthetic — IP ตาม RFC 5737 (ไม่มี marker) | 1 | 0 | 1 |
| IP ภายนอกจริง | 17 | 11 | **28** |

**97% ของข้อมูลมาจาก IP ภายในเครื่องหรือ Docker**

corpus ที่มาจาก IP ภายนอกจริง

```
28 แถว · ผู้ใช้ 2 คน · 11 มิ.ย. – 18 ส.ค. 2569
มี risk_breakdown 17 แถว · มี geo_country 15 แถว
```

### ข้อควรระวังที่ต้องบันทึกไว้

IP `172.18.x` **ไม่ได้แปลว่าเป็นข้อมูลสังเคราะห์เสมอไป** — อาจเป็นการเข้าสู่ระบบจริง
ที่ผ่าน reverse proxy ซึ่งไม่ได้ตั้ง `X-Forwarded-For` (ตรงกับข้อควรรู้ข้อ 3–4 ใน
`CLAUDE.md`) จึงต้องจัดกลุ่มนี้เป็น **"ระบุที่มาไม่ได้"** ไม่ใช่ "สังเคราะห์"

นี่คือเหตุผลที่การบันทึก provenance ลงทุกแถวจำเป็น — ปัจจุบันพิสูจน์ที่มาของแถว
ย้อนหลังไม่ได้เลยนอกจากอนุมานจาก IP และ user agent

---

## 7. ข้อสรุปและสิ่งที่ทำต่อ

1. **ไม่มี shadow safety bug** — ไม่ต้องแก้โค้ดจากผลการสืบครั้งนี้
2. **ไม่มีผู้ใช้จริงถูก enforce โดยโมเดล** — ทั้ง 3 แถวเป็นข้อมูล demo
3. corpus ที่ใช้วิเคราะห์ traffic จริงได้มีขนาดเล็กมาก (2 ผู้ใช้ · 28 แถว) จึงต้อง
   รายงานแยกเป็นสอง stratum และประกาศว่าไม่มี stratum ใดเป็นตัวแทน production จริง
4. ยัง**ไม่**สร้าง `calibration_v1.json` และยัง**ไม่** deploy จนกว่าจะจบขั้นที่ 3

## 8. สิ่งที่ยังห้ามอ้างจากรายงานนี้

- ห้ามอ้างว่าระบบ "ไม่เคยมีความเสี่ยงเรื่อง shadow enforcement" — รายงานนี้ตรวจเฉพาะ
  แถวที่มี `fusion = max_corroboration` เท่านั้น แถวที่ไม่มี `risk_breakdown` อีก 415 แถว
  ยังระบุที่มาไม่ได้
- ห้ามอ้างว่า 1,648 แถวจาก IP ภายในเป็นข้อมูลสังเคราะห์ทั้งหมด
- ห้ามใช้จำนวน `decision` จาก `login_sessions` เป็นสถิติของระบบโดยไม่กรอง provenance
