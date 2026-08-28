# Config G — All-eligible-feature Sequence-Residual IForest เทียบ Config F

**วันที่:** 26 ส.ค. 2026  
**seeds:** [42, 43, 44, 45, 46] (mean ± 95% CI) · size 5000 events/user · ชุดทดสอบเดียวกันทุก config  
**ขนาด:** attack 413 · normal 8400 (campaign 120)


## การออกแบบที่ทดสอบ

| | Config F (ปัจจุบัน) | Config G (ที่เสนอ) |
|---|---|---|
| ฟีเจอร์ต้นทาง | 6 (residual-owned) | ทุกฟีเจอร์ที่ eligible |
| inputs หลัง window | **18** | **30** |
| การแปลง | residual median/IQR | robust residual + rate-deviation ตามประเภท |
| window | 5 · [mean, slope, ptp] | 5 · [mean, slope, ptp] |
| threshold | p99 | p99 (investigate) + p99.9 (extreme) |
| ส่งให้ L4 | monitoring channel | monitoring channel |

## ผลเปรียบเทียบ

| metric | Config F | Config G | Δ (G−F) |
|---|---|---|---|
| **L3 unique** | 5.1±1.3 | 1.2±0.5 | -3.9±1.2 |
| L3 unique (campaign) | 16.3±4.4 | 3.2±1.0 | -13.2±4.2 |
| standalone | 16.4±3.3 | 11.9±3.0 | -4.5±2.3 |
| overlap | 11.3±3.1 | 10.7±2.6 | -0.6±1.7 |
| extreme rate | 4.6±2.2 | 2.6±1.7 | -2.1±1.4 |
| L3 FPR (normal) | 0.8±0.3 | 1.0±0.2 | +0.3±0.3 |
| Challenge FPR | 1.6±0.2 | 1.6±0.2 | +0.0±0.0 |
| Warn FPR (รวม monitor) | 3.6±0.4 | 3.7±0.2 | +0.1±0.3 |

## Latency

| | Config F | Config G |
|---|---|---|
| fit ต่อคน | 0.91s | 1.02s |
| score ต่อ event | 11.466ms | 11.291ms |

## เกณฑ์ตัดสิน

| เกณฑ์ | ผล |
|---|---|
| unique ไม่น้อยกว่า F (CI ไม่คร่อม 0) | Δ **-3.9 ± 1.2** pp |
| Challenge FPR ไม่เพิ่ม | Δ +0.0 pp |
| Warn FPR เพิ่มไม่เกินงบ (+2pp) | Δ +0.1 pp |
| latency รับได้ | fit 1.02s · score 11.291ms |

> **ข้อสรุป: คง Config F ไว้ — G ยังไม่ผ่านเกณฑ์**

---

## เหตุใด Config G ได้ 30 มิติ ไม่ใช่ 54

สเปคคาด 18 ฟีเจอร์ × 3 = 54 แต่ของจริงได้ **30** (10 ฟีเจอร์ × 3) เพราะ **variance ต้องมีต่อ "คนนั้น"**
ไม่ใช่ต่อชุดข้อมูลรวม:

| ฟีเจอร์ | มี variance กี่คน (จาก 12) | เหตุผล |
|---|---|---|
| hour_of_day · day_of_week · hours_from_typical · log_minutes · login_count_24h · concurrent · weekday_usage | **12/12** ✓ | แปรผันจริงทุกคน |
| active_subsystem_count | 11/12 | คนที่ใช้ระบบเดียวไม่แปรผัน |
| scope_sensitivity_score | 10/12 | คนที่เข้า subsystem เดียวคงที่ |
| is_new_device / passkey_age / passkey_last_used | 2–4/12 | ส่วนใหญ่ใช้เครื่องเดียว / ไม่มี passkey |
| ever_changed_permission · permission_change_age | 1/12 | แทบไม่มีใครเปลี่ยนสิทธิ์ |
| **failed_logins_24h · passkey_count · new_passkey · confirmed_incident** | **0/12** ✗ | **คงที่ในข้อมูล normal ทั้งหมด** |

**วิธีแปลงที่ใช้จริง:** robust residual (median/IQR) 86 ครั้ง · rate-deviation (mean/std) 35 ครั้ง

> 4 ฟีเจอร์ที่ได้ 0/12 คงที่ใน normal เพราะ generator V2 ไม่ได้จำลอง failed login / passkey event
> ในพฤติกรรมปกติ — เป็นข้อจำกัดของชุดข้อมูล ไม่ใช่ของ production (และทั้ง 4 ตัวเป็นของ **L1** อยู่แล้ว)

---

## อ่านผล — ทำไม G แย่กว่า F

**G ใช้ 30 มิติ ครอบคลุมทุกฟีเจอร์ที่มีข้อมูล แต่ unique ตกจาก 5.1% เหลือ 1.2% (−3.9 ± 1.2 pp)**
และบน campaign ตกหนักกว่า: **16.3% → 3.2% (−13.2 ± 4.2 pp)** — CI ไม่คร่อมศูนย์ทั้งคู่

สาเหตุคือ **signal dilution ใน Isolation Forest**:

1. IForest สุ่มเลือกฟีเจอร์มาแบ่ง — ยิ่งมีฟีเจอร์ที่ไม่เกี่ยวมาก โอกาสแบ่งด้วยฟีเจอร์ที่มีสัญญาณยิ่งน้อย
   (F มี 18 มิติที่ "ตั้งใจเลือกมา" ทุกตัวมีความหมาย · G มี 30 มิติที่ 12 ตัวเป็น noise สำหรับ campaign)
2. campaign drift อยู่ในมิติเฉพาะ (cadence/scope/subsystem-rarity) — การเติม `hour_of_day`,
   `day_of_week`, `login_count_24h` ที่ไม่ได้ drift ทำให้ระยะทางใน feature space ถูกกลบ
3. ฟีเจอร์ที่เพิ่มมาส่วนใหญ่ **L1/L2 เป็นเจ้าของอยู่แล้ว** → ไม่ได้เพิ่มข้อมูลใหม่ แต่เพิ่มมิติ

**ตรงกับที่ SHAP วัดไว้ก่อนหน้า:** L3 บนฟีเจอร์ครบชุดมี DuplicateRatio 79.1% และ unique 0.0% —
Config G คือเวอร์ชันที่ดีขึ้น (มี residual+sequence) แต่ยังคงมีปัญหาเดียวกันในระดับที่เบากว่า

**ค่าที่ไม่แย่ลง:** Challenge FPR ไม่ขยับ (+0.0) และ warn FPR เพิ่มแค่ +0.1pp — เพราะสถาปัตยกรรม
monitoring channel ป้องกันไว้แล้ว (L3 ไม่แตะ access decision)

**latency:** G ช้ากว่า F เล็กน้อย (fit 1.02s vs 0.91s ต่อคน) — ไม่ใช่ปัจจัยตัดสิน

---

## ข้อสรุปตามเกณฑ์ที่ตั้งไว้

| เกณฑ์ | ผล | ผ่าน? |
|---|---|---|
| unique ไม่น้อยกว่า F | **−3.9 ± 1.2 pp** (CI ไม่คร่อม 0 = แย่กว่าอย่างมีนัย) | ❌ |
| Challenge FPR ไม่เพิ่ม | +0.0 pp | ✅ |
| Warn FPR ในงบ (+2pp) | +0.1 pp | ✅ |
| latency รับได้ | fit 1.02s · score 11.3ms | ✅ |

> **คง Config F ไว้** — ตรงกับที่สเปคระบุ: "หากผลแย่กว่า แปลว่าฟีเจอร์ทั้งหมดเพิ่ม Noise
> และควรกลับมาใช้ Config F"

**สิ่งที่ยืนยันได้จากการทดลองนี้:** การเลือกฟีเจอร์แบบ ownership (6 ตัวที่ L1/L2 ไม่ถือ)
**ไม่ใช่การตัดข้อมูลทิ้ง แต่เป็นการตัด noise** — ให้ IForest โฟกัสมิติที่มีสัญญาณจริง

**ข้อจำกัด:** ชุดข้อมูล V2 มี 4 ฟีเจอร์คงที่ใน normal (failed/passkey/incident) ที่ production
จะแปรผันจริง — ถ้า production replay พบว่าฟีเจอร์เหล่านี้มี variance ควรทดลอง G ซ้ำ
