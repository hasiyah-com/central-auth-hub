# แก้ generator ของ V7 แล้วเทรนใหม่ — ผลและข้อสรุป

**วันที่:** 21 ส.ค. 2026
**ฐาน:** `agent/rba-user-learning-curve-contracts` commit `b45c350`
**แพตช์:** [`ml-service/patches/v7_generator_success_10m.patch`](../../../../ml-service/patches/v7_generator_success_10m.patch)
**ทำใน scratchpad ไม่ได้ commit ทับ branch**

---

## สรุป

| | ผล |
|---|---|
| bug ใน generator | ✅ **ยืนยันว่ามีจริงและแก้แล้ว** — normal ไม่เคยมี `success_10m > 0` เลย |
| FPR บนชุด V2 (ที่ threshold ของ bundle เอง) | ✅ **38.4% → 0.53%** |
| Recall บนชุด V2 | ❌ **58.3% → 0.0%** |
| **ROC-AUC (ไม่ขึ้นกับ threshold)** | ⚠️ **0.617 → 0.641 แทบไม่ขยับ** |

> **ข้อสรุป:** การแก้ถูกต้องและจำเป็น แต่พอเอาสัญญาณปลอมออก
> **พบว่า V7 แทบไม่มีความสามารถแยก attack แบบชุด V2 มาตั้งแต่แรก**
> recall 58.3% ที่วัดได้ก่อนหน้า มาจาก artifact เกือบทั้งหมด

---

## 1. ก่อนแก้ — ผมสรุปรูปแบบ bug ผิดไปรอบก่อน ขอแก้ให้ถูก

รอบก่อนผมบอกว่า `success_10m` เป็น "one-hot ของ attack type" ซึ่ง**ไม่ถูกทั้งหมด**
ตรวจด้วยการวัด AUC ของทุกฟีเจอร์เดี่ยวบนข้อมูลเทรนของ V7 เอง:

```
sequence feature              AUC  normal mean  attack mean
duration_log_range          0.714        0.814        0.565   <- สูงสุด
scope_slope                 0.710       -0.000        0.022
gap_log_range               0.690        2.562        1.606
success_sum                 0.676        0.000        1.456
...
```

**ไม่มีฟีเจอร์ไหน AUC ใกล้ 1.0** → ไม่ใช่ shortcut แบบแยกขาด

**รูปแบบที่แท้จริงคือ "ทางลัดด้านเดียว"** — วัดด้วยการเทียบ *ช่วงค่าที่โมเดลเคยเห็น* (support):

| feature | ค่าสูงสุดตอนเทรน | normal ในชุด V2 ที่หลุดช่วง |
|---|---|---|
| `duration_log_range` | 2.509 | **62.1%** |
| `browser_version_slope` | 0.400 | **40.0%** |
| **`success_sum`** | **0.000** | **37.4%** |
| `duration_log_slope` | 0.756 | 26.8% |
| `scope_slope` | 0.080 | 11.6% |

`success_sum` คือกรณีรุนแรงสุด: **normal ตอนเทรน 35,964 window เป็น 0 ทั้งหมด**
โมเดลจึงเรียนว่า "ค่า > 0 = ไม่ใช่พฤติกรรมปกติแน่นอน"
พอเจอผู้ใช้จริงที่ล็อกอินซ้ำใน 10 นาที (เกิด 37.4% ของ window) → ตีเป็น attack

**ประเด็นเชิงวิธีการ:** AUC จับปัญหานี้ไม่ได้ เพราะ AUC วัดการจัดอันดับโดยรวม
ไม่ได้วัดว่ามี "โซนที่ข้อมูลเทรนไม่มี normal อยู่เลย" หรือไม่ → ต้องเทียบ support ด้วย

---

## 2. การแก้

**สาเหตุ:** `generate_normal()` ส่ง `failed_1h` และ `concurrent_sessions` เข้า `Event()`
แต่**ไม่เคยส่ง `success_10m`** จึงค้างที่ค่า default `0` ส่วนฝั่ง attack ตั้งเป็น 5

**วิธีแก้:** คำนวณจาก timeline จริงหลังสร้าง event ครบ (แบบเดียวกับที่ production ทำ)

```python
by_profile: dict[str, list[Event]] = defaultdict(list)
for row in rows:
    by_profile[row.profile_id].append(row)
for events in by_profile.values():
    events.sort(key=lambda x: x.timestamp)
    for position, event in enumerate(events):
        cutoff = event.timestamp - timedelta(minutes=10)
        event.success_10m = sum(
            1 for earlier in events[:position] if earlier.timestamp >= cutoff
        )
```

**ผล:** normal ที่มี `success_10m > 0` เปลี่ยนจาก **0.00% → 2.9%** (60,000 events)
→ support ทับกับข้อมูลจริงแล้ว

---

## 3. เทรนใหม่ + วัดผล

```bash
python scripts/export_shadow_bundle_v7.py --output results/fixed_v7 --dataset-size 5000 --seed 42
```
threshold ที่ calibrate ได้เปลี่ยน **0.5824 → 0.6778** (ยืนยันว่าโมเดลเทรนใหม่จริง)

### ผลบนชุด V2 (190 normal test + 240 attack)

| | ก่อนแก้ | หลังแก้ |
|---|---|---|
| Recall | 58.3% | **0.0%** |
| Challenge FPR | 38.42% | **0.53%** |
| F1 | 0.618 | 0.000 |
| **ROC-AUC** | 0.617 | **0.641** |
| **PR-AUC** | 0.666 | **0.670** |
| คะแนนเฉลี่ย normal / attack | 0.372 / 0.506 | 0.125 / 0.172 |

### Threshold sweep — พิสูจน์ว่าไม่ใช่แค่เกณฑ์เลื่อน

| threshold | ก่อนแก้ (recall / FPR) | หลังแก้ (recall / FPR) |
|---|---|---|
| 0.15 | 80.4% / 60.0% | 46.2% / 28.9% |
| 0.30 | 67.5% / 43.2% | 17.9% / **5.8%** |
| 0.45 | 61.3% / 40.0% | 2.1% / 1.6% |
| 0.60 | 57.5% / 38.4% | 0.0% / 0.5% |
| **F1 ดีสุดที่ทำได้** | 0.710 (FPR 90.5%) | 0.719 (FPR 77.9%) |

**ทั้งก่อนและหลัง ไม่มี threshold ไหนให้ทั้ง recall สูงและ FPR ต่ำพร้อมกัน**
ROC-AUC ~0.62–0.64 คือคำตอบที่ไม่ขึ้นกับ threshold: การจัดอันดับอ่อนทั้งคู่

---

## 4. ตีความ

**การแก้ทำงานถูกต้อง** — เอาสัญญาณปลอมออก FPR ตกจาก 38.4% เหลือ 0.53%

**แต่ recall ก็หายไปด้วย** เพราะ recall เดิมมาจากสัญญาณปลอมตัวเดียวกัน:
attack ที่เคยจับได้ 100% (`login_velocity`, `concurrent_sessions`, `combined_ato`)
ล้วนเป็นกลุ่มที่ generator ตั้ง `success_10m = 5` ไว้ให้ — ไม่ใช่การเรียนรู้รูปแบบจริง

**ROC-AUC ที่แทบไม่ขยับ (0.617 → 0.641) คือหลักฐานชี้ขาด:**
ความสามารถแยกแยะที่แท้จริงบนชุด V2 **ไม่ได้เพิ่มขึ้นเลย** การแก้แค่ย้ายคะแนนลงทั้งแผง

---

## 5. ปัญหาที่ยังเหลือ

### 5.1 แก้ได้ 1 ใน 5 ฟีเจอร์ที่หลุด support
`duration_log_range` (62%), `browser_version_slope` (40%), `duration_log_slope` (27%),
`scope_slope` (12%) ยังไม่ได้แก้ — ทั้งหมดชี้ปัญหาเดียวกันคือ
**"normal" ของ generator สม่ำเสมอเกินกว่าพฤติกรรมมนุษย์จริง**

| ตัวอย่างในโค้ด | ผลที่ตามมา |
|---|---|
| `duration = lognormvariate(log(18), 0.42)` — σ แคบมาก | ผู้ใช้จริงมี session ตั้งแต่ 0.1 ถึง 1,302 นาที (จากข้อมูล 62 sessions จริง) |
| `version = 149 + min(4, index // ...)` — ไต่ขึ้นช้าๆ ทางเดียว | เบราว์เซอร์จริงกระโดดข้ามเวอร์ชัน / มีหลายเครื่องคนละเวอร์ชัน |

> ผมไม่ได้แก้ 2 ข้อนี้ เพราะเป็น **การตัดสินใจเชิงสมมติฐานของการทดลอง** ไม่ใช่บั๊ก
> (ต่างจาก `success_10m` ที่เป็นการลืมส่งค่าชัดๆ) — ควรให้เจ้าของการทดลองตัดสิน

### 5.2 `release_gate` ไม่ได้คำนวณใหม่ตอน export
หลังเทรนใหม่ ตัวเลขใน `results/fixed_v7/release_gate.json` **เท่าเดิมทุกตัว**
(precision 0.978, recall 0.909, ROC-AUC 0.998, FPR 0.0025) เพราะ `export_shadow_bundle_v7.py`
**copy มาจาก `results/supervised_sequence_v6/release_gate.json`** ไม่ได้วัดใหม่

→ gate จะยังขึ้น `ready_for_system_shadow_load: True` แม้โมเดลเปลี่ยนไปแล้ว
→ ต้องรัน `run_supervised_sequence_v6.py` ใหม่ก่อน ถึงจะได้ตัวเลขที่ตรงกับ bundle

---

## 6. ข้อเสนอ

| # | งาน | เหตุผล |
|---|---|---|
| 1 | **ใช้แพตช์ `v7_generator_success_10m.patch`** | บั๊กชัดเจน แก้แล้วถูกต้องขึ้นแน่นอน |
| 2 | **รัน V6 ใหม่ก่อน export V7** หรือให้ export คำนวณ gate เอง | ตอนนี้ gate เป็นตัวเลขค้างจากรอบก่อน |
| 3 | **เพิ่ม support check เข้า test** — ยืนยันว่าไม่มีฟีเจอร์ไหนที่ normal ตอนเทรนมีค่าเดียว | ด่านที่จะจับ bug ประเภทนี้ (AUC จับไม่ได้) |
| 4 | **ขยายความแปรผันของ normal** (duration σ, browser version) ให้ใกล้ข้อมูลจริง | 4 ฟีเจอร์ยังหลุด support |
| 5 | **ห้ามเปิด enforcement** | ROC-AUC 0.64 บนข้อมูลนอกชุดเทรน |
| 6 | ถ้าจะใช้ V7 จริง — ทดสอบด้วย attack แบบ **หลาย event** ให้ตรงกับที่มันออกแบบมา | attack ในชุด V2 ส่วนใหญ่เป็น event เดียว |

---

## 7. รันซ้ำ

```bash
# 1. ใช้แพตช์
git apply ml-service/patches/v7_generator_success_10m.patch

# 2. เทรนใหม่
python experiments/rba_user_learning_curve/scripts/export_shadow_bundle_v7.py \
    --output results/fixed_v7 --dataset-size 5000 --seed 42

# 3. วัดผลบนชุด V2
py ml-service/scripts/eval_v7_on_v2.py \
    --bundle <path>/results/fixed_v7/sequence_model_v7.joblib \
    --runtime <path>/scripts
```

> หมายเหตุ: `export_shadow_bundle_v7.py` จะ error ถ้าไม่มี
> `results/supervised_sequence_v6/predictions.csv` (ไฟล์ถูกตัดออกจาก git เพราะใหญ่)
> — เกิดหลังเขียนโมเดลแล้ว จึงไม่กระทบ artifact แต่ควรทำให้ optional
