# L3 ที่ "ได้ผลจริง" — sequence residual + surfacing channel (config F)

**วันที่:** 26 ส.ค. 2026
**ต่อจาก:** [`l3_campaign_2026-08-26.md`](l3_campaign_2026-08-26.md) (campaign ทำให้ D>C>B แต่ยังเล็ก)
**seeds:** 42–46 (mean ± 95% CI) · sizes 10–5000 · per-user IForest · W=5
**configs:** A=L1+L2 · D=L3 point-residual · E=L3 sequence-residual · **F=E แต่เป็น surfacing channel**

---

## ผลชี้ขาด

> **F คือ config แรกที่ผลชัดเจนและ CI ไม่คร่อม 0**
> L3-unique (campaign) = **16.3 ± 4.4%** ที่ size 5000 · campaign surfaced **41.3% → 57.7% (+16.4pp)**
> ต้นทุน: warn FPR +0.8pp · **challenge FPR ไม่ขยับเลย (1.6%)** = ผู้ใช้ไม่ถูกรบกวนเพิ่ม

### L3 unique detection เฉพาะ campaign (attack ที่ L3 ทำให้ surfaced แต่ L1+L2 พลาด)

| config | 50 | 100 | 500 | 1000 | 5000 |
|---|---|---|---|---|---|
| D: point-residual | 0.0±0.0 | 1.0±1.6 | 0.8±0.9 | 0.3±0.7 | 0.2±0.3 |
| E: sequence-residual | 0.0±0.0 | 0.8±1.0 | 0.2±0.3 | 0.2±0.3 | 0.2±0.3 |
| **F: sequence + channel** | **4.7±2.2** | **6.3±3.2** | **9.7±4.3** | **12.5±5.2** | **16.3±4.4** |

**F เพิ่มขึ้นตามปริมาณข้อมูล** (4.7 → 16.3) — สมเหตุผลกับโมเดลรายคนที่เรียน baseline ได้แม่นขึ้น

### ต้นทุน / ผลรวม (size 5000)

| | A (L1+L2) | F | ต่าง |
|---|---|---|---|
| campaign surfaced (warn+) | 41.3±11.1% | **57.7±7.3%** | **+16.4pp** |
| L3-unique (attack ทั้งหมด) | 0 | **5.1±1.3%** | **+5.1pp** |
| **challenge FPR** | 1.6±0.2% | **1.6±0.2%** | **+0.0** ✅ |
| warn FPR | 2.8±0.1% | 3.6±0.4% | +0.8pp |
| recall รวม (challenge+) | 58.6±2.0% | 58.6±2.0% | +0.0 |

---

## เหตุผลที่ F ต่างจาก D/E — diagnostic ชี้คอขวด

วัดบน campaign ที่ L1+L2 พลาด (71 ตัว, seed 42 size 5000):

| ข้อเท็จจริง | ค่า |
|---|---|
| L3-E anomaly: campaign-miss vs normal | **0.573 vs 0.452** (แยกได้) |
| campaign-miss ที่เกิน normal p95 / p99 | **66.2% / 33.8%** ← **L3 rank ถูกต้อง** |
| base_total ของ campaign-miss | mean **0.23** · max **0.45** |
| ตัวที่ bonus 0.15 ดันถึง warn ได้ (base ≥0.35) | **2/71** ← **คอขวด** |

> **คอขวดคือวิธี integrate ไม่ใช่ ranking ของ L3** — L3 จัดอันดับ campaign ถูก (66% เกิน normal p95)
> แต่ bounded bonus +0.15 บวกเข้ากับคะแนนที่ต่ำมาก (0.23) แล้วไม่มีทางถึง warn (0.5)
> → เปลี่ยนเป็น **surfacing channel** (L3 ยิง = warn ทันที) ปลดล็อกทันที: 0.2% → 16.3%

**ทำไม sequence (E) ไม่ชนะ point (D) ตอนใช้ bonus:** เพราะทั้งคู่ติดคอขวดเดียวกัน —
พอปลดคอขวด (F ใช้ window model) ถึงเห็นค่าที่แท้จริงของ sequence framing

---

## เกณฑ์ตัดสิน (ตาม spec) → ผล

| เกณฑ์ | ผล |
|---|---|
| +recall ≥3–5pp ที่ FPR เท่าเดิม → L3 มีประโยชน์ | ✅ **L3-unique +5.1±1.3pp** ที่ challenge-FPR **ไม่ขยับ** |
| CI คร่อม 0 → shadow-only | ✅ **CI ไม่คร่อม 0** (16.3±4.4 และ 5.1±1.3) |
| FPR เพิ่ม > recall → ปิด L3 | ❌ ไม่เข้าเงื่อนไข (warn +0.8pp แลก campaign +16.4pp) |
| D ดีกว่า C → ปัญหาคือ feature design | เพิ่มเติม: **ปัญหาคือ integration ด้วย** |

---

## ข้อสรุปเชิงสถาปัตยกรรม (เปลี่ยนจากเดิม)

**เดิม:** "L3 ไม่มีค่า เก็บ shadow-only"
**ใหม่:** **L3 มีค่าจริง ถ้าใช้ให้ถูกบทบาท**

| บทบาท | เหมาะไหม | เหตุผล |
|---|---|---|
| L3 บวกคะแนนเข้า aggregate (D/E) | ❌ | คะแนน stealth ต่ำเกิน bonus จะดันไหว |
| **L3 เป็น monitoring/surfacing channel (F)** | ✅ | ยก warn ตรง — จับ campaign ที่ L1/L2 มองไม่เห็น |
| L3 ตัดสิน challenge/block | ❌ | ไม่ควร — precision ไม่พอ, ปล่อยให้ L1/L2 ตัดสิน friction |

**คำแนะนำ:** ให้ L3 ทำหน้าที่ **"ธงเฝ้าระวัง" (warn = SOC monitoring, ไม่รบกวนผู้ใช้)**
ไม่ใช่ผู้ร่วมตัดสิน friction — challenge FPR คงที่ 1.6% ยืนยันว่าไม่กระทบ UX

## ⚠️ ข้อจำกัด (ต้องระบุใน thesis)

1. campaign attack เป็น **synthetic ที่เราออกแบบเอง** — L3 จับได้เพราะเป็น joint-drift ที่เราใส่เข้าไป
2. ยังไม่ผ่าน **production replay** — ตัวเลขทั้งหมดบนข้อมูลจำลอง (anchor คนจริง)
3. ต้องมี **≥500 events/คน** ถึงเห็นผลชัด (16.3% ที่ 5000 vs 4.7% ที่ 50)
4. warn FPR +0.8pp = ภาระ SOC ที่ต้องยอมรับ

**สถานะที่เหมาะสม:** เปิด L3 เป็น **shadow/monitoring channel** ได้ (ไม่กระทบผู้ใช้)
แต่ยัง **ไม่ควรให้ตัดสิน enforcement** จนกว่าจะ production replay

**ไฟล์:** harness `ml-service/scripts/lc_l3_sequence.py` (configs A/D/E/F) ·
generator `build_profiles_v2.py:gen_campaign_attacks`
