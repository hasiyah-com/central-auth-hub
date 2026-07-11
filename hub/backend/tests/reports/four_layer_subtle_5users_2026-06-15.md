# รายงาน: 4-Layer RBA บนชุด "อีเมลจริง 5 คน + Attack เนียน"

- **วันที่:** 2026-06-15
- **เปลี่ยนจากเดิม:** ใช้ **อีเมลจริง 5 คนเท่านั้น (ไม่ clone)** + attack **เนียนล้วน** (subtle, ไม่มีสัญญาณง่าย)
- **Scripts:** `simulate_month.py` (ปรับใหม่), `simulate_features.py`, `four_layer_eval.py`

---

## 1. Dataset
- **505 แถว** · ผู้ใช้ **5 คนจริง** (U08, U01, U04, U06, U14)
- attack **39 (7.7%)** — subtle level-2 ล้วน: ประเทศเพื่อนบ้าน (SG/MY/VN/LA), เครื่องทั่วไป (ไม่ใช่ attacker),
  เวลาเพี้ยนเล็กน้อย (20-23), **ไม่มี is_attack_ip** (ไม่มีสัญญาณง่าย)
- **risky-own (label 0) = 32** — พฤติกรรมเสี่ยงของผู้ใช้เอง (เครื่องใหม่/เวลาเพี้ยน) เพื่อทดสอบ false positive
- scenario: subtle_failed_few, subtle_slow_travel, subtle_new_country, subtle_new_device_offhour

> เข้าได้เฉพาะ subsystem ที่มีสิทธิ์จริง; geo/scope อิงระบบจริง

---

## 2. ผล 4-Layer เต็ม (actionable = challenge+block ≥0.7)
| | level-2 (subtle) | level-1 (risky-own) | Recall | Precision | F1 | FP/466 |
|---|---|---|---|---|---|---|
| **4-layer เต็ม (มี L2)** | **26/39** | 6/32 | **0.667** | 0.703 | **0.684** | 11 |
| ตัด Layer 2 (L1+L3) | 16/39 | 5/32 | 0.410 | 0.762 | 0.533 | 5 |
| รวม warn (≥0.5, monitor) | 31/39 | 12/32 | 0.795 | 0.369 | 0.504 | 53 |

decision: allow 421 · warn 47 · challenge 12 · block 25

---

## 3. Layer 2 (Behavior) = พระเอกของ subtle attack
- subtle attack 16 → **26** (+10), recall 0.41 → 0.67, **F1 0.533 → 0.684**
- เคสที่ L2 ช่วย flag เพิ่ม: 16 แถว (จริง 10 + ปลอม 6) → คุ้ม

**ทำไมต่างจากชุดก่อน (attack โจ่งแจ้ง):**
- ชุดโจ่งแจ้ง: attack มี is_attack_ip/ต่างประเทศไกล → **Rule (L1) จับได้เอง** → L2 เพิ่มแค่ FP
- ชุดเนียนนี้: attack ไม่มีสัญญาณง่าย → **Rule จับไม่ได้** → **Layer 2 (Behavior) จับ subtle ที่เหลือ**

→ พิสูจน์ว่า **4-Layer RBA จำเป็นจริง**: ไม่มี layer ไหน layer เดียวพอ — Rule จับ hard-signal,
Behavior จับ subtle behavioral drift, ML จับ multi-signal, Aggregation รวมตัดสิน

---

## 4. ตอบคำถามที่ค้าง
- **44 vs 34 (level-2):** กฎคนละชุด — ขั้น 2 ใช้กฎ geo ที่เพิ่มเอง (geo_distance>2000) จับ country ได้;
  ขั้น 3/4 ใช้ `rule_engine.py` จริง (ไม่มีกฎ geo) → country_change_only score แค่ 0.4 < 0.7
  → **ถ้าจะให้ของจริงจับได้ ต้องเพิ่มกฎ geo เข้า rule_engine**
- **Layer 4 ใช้ครบ:** ผลทั้งหมดผ่าน L4 aggregation (total=L1+L2+L3, block/challenge/warn) แล้ว

## 5. ข้อจำกัด
- ผู้ใช้จริงมีแค่ 5 คน → 505 แถว (เล็ก แต่ anchor จริง 100% ไม่มี clone)
- attack ยัง "ออกแบบเอง" (subtle) — แต่ใกล้เคียงพฤติกรรมจริงมากกว่าชุดโจ่งแจ้ง
- ยังเหลือ 13/39 subtle ที่จับไม่ได้ = ความท้าทายจริง (เนียนเกินเกณฑ์)

## 6. งานต่อ
- เพิ่มกฎ geo (impossible-travel/geo-distance) เข้า `rule_engine.py` จริง
- calibrate น้ำหนัก L2 + threshold ลด FP บน risky-own
