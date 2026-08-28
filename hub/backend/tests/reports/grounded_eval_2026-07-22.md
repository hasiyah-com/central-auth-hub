# Persona-Grounded Evaluation — Train/Test อ้างอิงผู้ใช้จริง 7 คน

**วันที่:** 2026-07-22
**สคริปต์:** `hub/backend/scripts/generate_grounded_data.py` → `ml-service/scripts/train_eval_grounded.py`
**โมเดล:** Isolation Forest (`n_estimators=100`, `contamination=0.02`) — บันทึกแยก `iforest_grounded.pkl`

---

## 1. แนวคิด (methodology)

แทนการสุ่มค่าลอย ๆ → สร้าง "พฤติกรรมปกติ" โดย**อ้างอิงข้อมูลจริง 3 แหล่ง**:

| แหล่ง | ใช้กับ feature ไหน |
|---|---|
| **โปรไฟล์จริงของ 7 users** (ประวัติ login) | `hour_of_day`, `day_of_week`, `hours_from_typical` |
| **invariant ของ login ปกติ** | `is_new_country=0`, `is_new_device=0`, `is_thailand=1`, `impossible_travel≈0` |
| **ช่วงค่าอิงงานวิจัย** (Wiefling 2023, Freeman 2016) | velocity, passkey, scope, permission |

### ชุดข้อมูล 2 ชุด (ตามที่ออกแบบ)
| ชุด | เนื้อหา | ใช้ทำอะไร |
|---|---|---|
| **train_grounded** | normal 3,000 | เทรน (IForest unsupervised — normal เท่านั้น) |
| **test_grounded** | normal 3,000 (held-out) + anomaly 600 | วัดประสิทธิภาพ |

> ขนาด 3,000 มาจาก learning curve (plateau) — ดู `learning_curve_2026-07-22.md`

### ⭐ Held-out split (สำคัญเชิง methodology)
normal ของ train กับ test **เป็นคนละชุดจริง** — สร้าง pool เดียว 6,000 แถวจาก
persona ชุดเดียวกัน แล้ว shuffle + แบ่ง train 3,000 / test 3,000 แบบ **disjoint**
(การันตีด้วย assertion ว่าไม่มี row ทับกัน) → ไม่มี data leakage ระหว่าง train/test
anomaly ในชุด test สร้างจาก normal base ฝั่ง test (ไม่อยู่ใน train)

---

## 2. Persona ที่ดึงได้ (ผู้ใช้จริง 7 คน)

| user | weight | typical_hour | มี TH |
|---|---|---|---|
| <U01> | 120 | 09:00 | ✓ |
| <U08> | 120 | 18:00 | · |
| <U03> | 84 | 16:00 | · |
| <U06> | 18 | 18:00 | · |
| risk-demo@uni.ac.th | 14 | 09:00 | ✓ |
| <U13> | 7 | 10:00 | · |
| <U14> | 5 | 09:00 | · |

> weight = จำนวน session จริง (cap 120 กันไม่ให้ user ที่มี test burst เยอะครอบงำ)
> typical_hour ต่างกันจริง (9/16/18/...) = persona มีความหลากหลายตามพฤติกรรมจริง

**Anomaly:** attacker model 4 ระดับ × 150 = 600 (สร้างจาก normal grounded base แล้วแปลง)

---

## 3. ผลการประเมิน ⭐

### Overall (test 3,600 — held-out split)
| Metric | ค่า |
|---|---|
| Precision | **0.8797** |
| Recall | **0.8167** |
| F1 | **0.8470** |
| ROC-AUC | **0.9597** |
| **FPR** | **67/3,000 = 2.2%** |

**Confusion Matrix:**
| | pred_normal | pred_anomaly |
|---|---|---|
| **true_normal** | 2,933 | 67 |
| **true_anomaly** | 110 | 490 |

### Recall แยกตาม attacker model
| Attacker model | n | detected | **Recall** |
|---|---|---|---|
| **very_naive** | 150 | 150 | **100.0%** |
| **naive** | 150 | 150 | **100.0%** |
| **vpn** | 150 | 145 | **96.7%** |
| **targeted** | 150 | 45 | **30.0%** |

```
very_naive  ████████████████████████ 100.0%
naive       ████████████████████████ 100.0%
vpn         ███████████████████████· 96.7%
targeted    ███████················· 30.0%
```

✅ **Sanity check ผ่าน:** recall ลดลงตามระดับความรู้ของผู้โจมตี

---

## 4. เปรียบเทียบกับ eval เดิม (attack_set บน model production)

| Metric | attack_set (production model) | **grounded (held-out)** |
|---|---|---|
| FPR | 14.0% | **2.2%** ↓ 11.8 จุด |
| Recall very_naive | 100% | 100% |
| Recall naive | 100% | 100% |
| Recall vpn | 100% | 96.7% |
| Recall targeted | 8.7% | **30.0%** ↑ |

### ทำไม FPR ต่ำลงมาก (14% → 2.2%)
- **เทรนและทดสอบบน distribution เดียวกัน** (persona-grounded ทั้งคู่) → โมเดลเห็น
  normal ที่ตรงกับ test → flag ผิดน้อย
- ต่างจาก production ที่เทรนบน synthetic เดิม แล้ววัดบน real traffic (มี test-burst ปน)

> ⚠️ **ข้อควรระวัง:** FPR 2.2% ที่ต่ำนี้ ส่วนหนึ่งเพราะ train/test มาจาก generator เดียวกัน
> (in-distribution) — ไม่ใช่การทดสอบ generalization ข้าม distribution
> **ตัวเลข FPR ที่สะท้อนความจริงมากกว่าคือ 14% จาก real traffic** (`ml_real_eval_2026-07-22.md`)

### ทำไม targeted recall ดีขึ้น (8.7% → 30.0%)
โมเดลใหม่เทรนบน normal ที่ "กระชับ" กว่า (persona-grounded, กระจายตัวแคบกว่า
synthetic เดิมที่สุ่มกว้าง) → boundary ของ normal แคบลง → targeted attack ที่เบี่ยง
เล็กน้อยถูกจับได้มากขึ้น **แต่แลกมาด้วยความเสี่ยง overfit กับ persona 7 คน**

---

## 5. ⚠️ ข้อจำกัด (ต้องเขียนในเล่ม — สำคัญมาก)

| ข้อจำกัด | รายละเอียด |
|---|---|
| **In-distribution evaluation** | train/test จาก generator เดียวกัน → FPR 2.2% มองโลกในแง่ดีเกินจริง สำหรับ generalization ต้องดู real traffic (14%) |
| **Persona จาก 7 คน** | ความหลากหลายของ normal จำกัด → เสี่ยง overfit; ผู้ใช้จริงที่พฤติกรรมต่างจาก 7 คนนี้อาจถูก flag |
| **ประวัติปน test noise** | hour histogram ของ persona รวม test burst (login ทุกชั่วโมง) → typical hour อาจไม่คมชัด |
| **Anomaly ยัง simulated** | recall จาก attacker model ไม่ใช่ attack จริง |

---

## 6. บทบาทของแต่ละ eval (ใช้ต่างกันในเล่ม)

| Eval | วัดอะไร | ตัวเลขที่ใช้อ้าง |
|---|---|---|
| `learning_curve` | ข้อมูลพอไหม | นิ่งที่ 3,000 |
| **`grounded` (นี้)** | ประสิทธิภาพบน controlled set (held-out) | P 0.88 / R 0.82 / F1 0.85 / AUC 0.96 · recall แยก 4 ระดับ |
| `ml_real_eval` | FPR บน traffic จริง | **14%** (ตัวเลขที่สะท้อนความจริง) |
| `attack_set` | recall บน production model | targeted 8.7% |

> 💡 **grounded = "controlled experiment"** — ใช้แสดงว่าโมเดลแยก normal/attack ได้ดีในเงื่อนไข
> ที่ควบคุม (P/R/F1/AUC ครบ + recall แยกระดับ) เหมาะกับตาราง performance หลักในเล่ม
> แต่**ต้องกำกับด้วย FPR จาก real traffic เสมอ** เพื่อความซื่อสัตย์

---

## 7. สรุปสำหรับ thesis

> "เพื่อประเมินประสิทธิภาพในเงื่อนไขที่ควบคุมได้ งานวิจัยนี้สร้างชุดข้อมูลแบบ
> persona-grounded โดยดึงรูปแบบเชิงเวลา (ชั่วโมงและวันที่ใช้งาน) จากประวัติการเข้าสู่
> ระบบจริงของผู้ใช้ 7 ราย มาเป็นฐานในการสังเคราะห์พฤติกรรมปกติ ร่วมกับช่วงค่าคุณลักษณะ
> ที่อ้างอิงจากงานวิจัย [1][10] ส่วนพฤติกรรมผิดปกติสร้างจากโมเดลผู้โจมตี 4 ระดับ [1]
>
> แบบจำลองที่ฝึกด้วยตัวอย่างปกติ 3,000 รายการ และทดสอบบนชุดทดสอบที่มีตัวอย่างปกติ
> **จำนวนเท่ากันซึ่งแยกจากชุดฝึกแบบ held-out (ไม่มีข้อมูลซ้ำ)** พร้อมแทรกตัวอย่างผิดปกติ
> 600 รายการ ให้ค่า Precision 0.88, Recall 0.82, F1 0.85 และ ROC-AUC 0.96 โดยตรวจจับ
> ผู้โจมตีระดับ naive ได้ 100%, VPN 96.7% และ targeted 30.0% ซึ่งลดหลั่นตามระดับความรู้
> ของผู้โจมตีตามที่ทฤษฎีคาดการณ์
>
> อย่างไรก็ตาม เนื่องจากชุดฝึกและชุดทดสอบมาจากการสังเคราะห์ด้วยกระบวนการเดียวกัน
> อัตรา false positive ที่ 2.2% จึงเป็นการประเมินแบบ in-distribution ค่าที่สะท้อนการ
> ใช้งานจริงมากกว่าคือ 14% ที่วัดจากทราฟฟิกจริง (ดูบท ...)"

---

## ไฟล์ผลลัพธ์
- `train_grounded.csv` (3,000) · `test_grounded.csv` (3,600) — gitignored, reproducible ด้วย `--seed 42`
- `ml-service/models/iforest_grounded.pkl` — โมเดลแยก ไม่ทับ production

## รันซ้ำ
```bash
docker compose exec hub-backend python -m scripts.generate_grounded_data
docker compose cp hub-backend:/app/tests/reports/train_grounded.csv - | docker compose cp - ml-service:/app/data/train_grounded.csv
docker compose cp hub-backend:/app/tests/reports/test_grounded.csv - | docker compose cp - ml-service:/app/data/test_grounded.csv
docker compose exec ml-service python -m scripts.train_eval_grounded
```
