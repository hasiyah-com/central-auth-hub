# L3 Feature-Ownership Experiment (ชุดไม่มี campaign) — L3 จับ 'anomaly ร่วม' ที่ L1/L2 พลาดไหม

**วันที่:** 25 ส.ค. 2026
**seeds:** 42–46 (mean ± 95% CI) · sizes 10–5000 · per-user IForest · bounded bonus ≤0.15
**ชุด attack:** obvious (11 scenario) + subtle (5 scenario) — **ยังไม่มี campaign**
**4 configs:** A=ไม่มี L3 · B=all-23 · C=continuous-owned · D=residual/interaction (per-user z)
**integration:** bonus เฉพาะเมื่อ L1+L2 ยัง < challenge · abstain ถ้า train < 50 ·
anomaly = −score_samples calibrate 99th pct (ไม่ใช้ sigmoid)

---

## ผลชี้ขาด

> **ทั้ง 4 config เหมือนกันเป๊ะ · L3-unique = 0.0 ± 0.0 ทุก size ทุก seed**
> แม้ config D (residual/interaction ตาม spec) ก็ไม่จับ attack ที่ L1/L2 พลาดเพิ่มเลย

| size | recall | subtle(warn+) | L3-unique (ทุก config) | cFPR | precision |
|---|---|---|---|---|---|
| 10 | 61±1 | 3±1 | 0.0±0.0 | 1.5±0.1 | 58±3 |
| 50 | 75±1 | 55±5 | 0.0±0.0 | 3.4±1.1 | 45±9 |
| 100 | 75±1 | 55±5 | 0.0±0.0 | 2.8±1.0 | 50±9 |
| 500 | 75±1 | 55±5 | 0.0±0.0 | 1.7±0.2 | 60±2 |
| 1000 | 75±1 | 55±5 | 0.0±0.0 | 1.6±0.2 | 62±3 |
| 5000 | 75±1 | 55±5 | 0.0±0.0 | 1.6±0.2 | 62±3 |

Marginal recall เหนือ A ที่ size 5000 = **+0.0 ± 0.0 pp** ทุก config · Δchallenge-FPR = +0.0

## Diagnosis — ทำไม 0 (ไม่ใช่บั๊ก · config D, size 5000, seed 42)

| ข้อเท็จจริง | ค่า |
|---|---|
| attack ที่ L1+L2 พลาด (base=allow) | 48 ตัว |
| base_total ของพวกที่พลาด | mean **0.10** · max **0.30** (ต่ำกว่า warn 0.5 มาก) |
| ตัวที่ base_total ≥ 0.35 (ระยะที่ +0.15 ดันถึง warn) | **0/48** |
| L3-D flag เป็น anomaly (bonus>0) | **3/48** (bonus 0.005–0.068, base_total=0.0) |

→ attack ที่ L1/L2 พลาดในชุดนี้ = พวกที่ **"เกือบปกติสนิทในทุก feature space" (รวม residual)**
→ ไม่ใช่ integration/feature-design ผิด แต่ **ไม่มีสัญญาณให้จับตั้งแต่แรก**

## เกณฑ์ตัดสิน → ผล

| เกณฑ์ | ผล |
|---|---|
| C/D +recall ≥3–5pp | ❌ ได้ 0pp |
| +1–2pp, CI คร่อม 0 → shadow-only | → **L3 shadow-only** |
| FPR เพิ่ม > recall → ปิดจาก online | FPR ไม่ขยับ |
| D ดีกว่า C ชัด → ปัญหาคือ feature design | ❌ **D ≈ C ≈ B ≈ 0** (ในชุดที่ไม่มี campaign) |

## ต่อยอด

ผลนี้นำไปสู่คำถาม "ถ้ามี attack แบบ joint-anomaly จริงล่ะ" → ดู
[`l3_campaign_2026-08-26.md`](l3_campaign_2026-08-26.md) ซึ่งพบว่า **D > C > B** เมื่อใส่ campaign

**harness:** `ml-service/scripts/lc_l3_ownership.py` (`LC.WITH_CAMPAIGN = False`)
