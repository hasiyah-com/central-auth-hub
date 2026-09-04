# Hybrid Risk — Round 2b Final (2026-09-04)

> ## สถานะ: `final_round_2b_failed_gate` (per-size) — B ใกล้ที่สุด แต่ยังไม่ผ่าน
>
> **การตัดสิน (2026-09-04): gate ใช้มาตรฐาน per-size** (ตรงกับที่ `tune` ใช้) ·
> ภายใต้ per-size **ไม่มี config ใดผ่าน** · **Config B ใกล้ที่สุด — ตกจุดเดียว
> challenge FPR @ size 50 (cold-start) = 1.23% > 1%** ทุก size×level อื่นผ่านหมด
> · warn fix (0.98) และ block fix (0.9999) **ได้ผลทั้งคู่** — ข้อจำกัดที่เหลือคือ
> cold-start challenge FPR ที่ผู้ใช้ประวัติน้อยสุด → **ไม่มี config ใหม่พร้อม deploy** ·
> fallback = current production / L3 shadow
>
> _(หมายเหตุ: ภายใต้ **macro** B ผ่านครบสามงบ แต่การตัดสินเลือก per-size เพราะเป็น
> มาตรฐานเดียวกับตอน tune — macro-only จะกลบภาระของผู้ใช้ cold-start)_

| | |
|---|---|
| รอบ | **Round 2b** |
| commit ที่ freeze | `8e6dc3f6d142` · scoring fingerprint 21/21 ตรง |
| candidate | Config B · γ=1.0 · **warn=0.98** · challenge=0.989833 · **block=0.9999** |
| fallback | current production / L3 shadow |
| holdout | `[106, 107, 108, 109, 110]` · 316,150 เหตุการณ์ · leakage 0 |
| **holdout open_count** | **1 (เปิดครั้งเดียว — สะอาด · ต่างจาก Round 2 ที่ >1)** |
| shortcut audit (holdout) | 0/23 |
| tail shift (deployed) | **False** (p99 exceedance 0.97% ≈ nominal 1%) |
| full pytest | 893 passed · 47 skipped · image `sha256:d140bf98e81d` · commit `8e6dc3f` |

---

## 1. ผล Final Gate บน holdout [106-110] — macro vs per-size

| cfg | recall | rec@ch | warn (macro) | ch (macro) | blk (macro) | macro | **per-size** |
|---|---|---|---|---|---|---|---|
| A legacy | 0.8916 | 0.7542 | 2.58% | 3.10% ✗ | 0.13% | ไม่ผ่าน | ไม่ผ่าน (ch ทุกขนาด) |
| **B** (candidate) | **0.8523** | 0.7099 | **2.71%** | **0.91%** | **0.07%** | ผ่าน | **ไม่ผ่าน (ch@50=1.23%)** |
| C +point | 0.8671 | 0.6853 | 4.99% | 1.15% ✗ | 0.13% | ไม่ผ่าน | ไม่ผ่าน (warn/ch/blk@50) |
| D +sequence | 0.7962 | 0.6618 | 2.96% | 1.49% ✗ | 0.17% | ไม่ผ่าน | ไม่ผ่าน (ch หลายขนาด) |
| E +ทั้งสอง | 0.8202 | 0.6132 | 3.83% | 1.46% ✗ | 0.13% | ไม่ผ่าน | ไม่ผ่าน (ch/blk) |
| F weighted sum | 0.7597 | 0.4787 | 2.85% | 0.72% | 0.19% | ผ่าน | ไม่ผ่าน (blk@50=0.22%) |

งบ: warn ≤ 5% · challenge ≤ 1% · block ≤ 0.2%

**per-size (มาตรฐานที่ตัดสินใช้): ไม่มี config ใดผ่าน** · แม้ F ที่ผ่าน macro ก็ตกที่
block@50 (0.22%) · **B ตกน้อยที่สุด — จุดเดียว challenge@50 = 1.23%** ขณะที่ size
100/500/1000/5000 ทุกระดับผ่าน · warn/block ของ B ผ่านทุกขนาด

---

## 2. ⚠️ เงื่อนไข per-size — B ตกที่ size 50 (cold-start)

Config B per-size บน holdout [106-110]:

| size | warn FPR | ch FPR | blk FPR | per-size |
|---|---|---|---|---|
| **50** | 2.15% ✓ | **1.23% ✗** | 0.18% ✓ | **ch เกิน 1%** |
| 100 | 2.90% ✓ | 0.91% ✓ | 0.10% ✓ | OK |
| 500 | 3.00% ✓ | 0.84% ✓ | 0.04% ✓ | OK |
| 1000 | 2.73% ✓ | 0.83% ✓ | 0.03% ✓ | OK |
| 5000 | 2.78% ✓ | 0.76% ✓ | 0.01% ✓ | OK |
| **macro** | 2.71% | 0.91% | 0.07% | ผ่าน |

**warn fix ทำงานทุกขนาด** (2.15-3.00% ทุก size, worst 3.0% ที่ 500 — ใต้ 5% สบาย) ·
**challenge เกิน 1% เฉพาะ size 50** (1.23%) ซึ่งเป็นผู้ใช้ประวัติน้อยสุด (cold-start)

**ทำไมเป็นปัญหา:** `tune` (ตอนเลือก threshold) ใช้เกณฑ์ **per-size** (`sweep.eligible()`
ตรวจทุกขนาด) แต่ `_final_gate()` ตรวจเฉพาะ **macro** → มาตรฐานไม่ตรงกัน · ถ้าใช้
มาตรฐานเดียวกับตอน tune (per-size) **B จะไม่ผ่านที่ size 50** · การประกาศงบใน protocol
(§3) ไม่ได้ระบุ macro หรือ per-size → **ต้องตัดสินก่อนสรุปว่าพร้อม deploy**

**บริบท:** size 50 = ผู้ใช้ที่มีประวัติ ~50 login (cold-start) · challenge FPR 1.23%
แปลว่า 1.23% ของ login ปกติของผู้ใช้ใหม่โดน step-up · เป็น product decision ว่ารับได้ไหม

---

## 3. warn fix — ได้ผลตามที่ออกแบบ (เทียบ 3 รอบ, คนละ holdout)

| Config B | holdout | warn | warn FPR | ch FPR | blk FPR | recall | gate |
|---|---|---|---|---|---|---|---|
| Round 1 | [42-46] | 0.9417 | 4.03% | 0.93% | **0.25% ✗** | 0.9068 | ไม่ผ่าน (block) |
| Round 2 | [101-105] | 0.9417 | **5.26% ✗** | 0.77% | 0.04% ✓ | 0.9178 | ไม่ผ่าน (warn) |
| **Round 2b** | [106-110] | **0.98** | **2.71% ✓** | 0.91% | 0.07% ✓ | 0.8523 | **ผ่าน macro** |

- **block fix (R2, →0.9999)** และ **warn fix (R2b, →0.98)** ได้ผลทั้งคู่บน holdout ใหม่
- recall (warn+) ลดจาก 0.9178 → 0.8523 (−6.6pp) ตามที่ประกาศไว้ — เป็นต้นทุน soft warn
  ที่แลกกับ warn FPR ที่ทน (recall@challenge 0.7026 → 0.7099 แทบไม่เปลี่ยน)
- warn=0.98 เลือกด้วยเกณฑ์ worst-seed บน validation (2.88%) · holdout จริง 2.71% —
  ต่ำกว่าที่ประเมิน (margin ทำงาน)

---

## 4. Provenance — สะอาดในรอบนี้ (ต่างจาก Round 2)

| | Round 2 [101-105] | Round 2b [106-110] |
|---|---|---|
| holdout open_count (ledger) | **>1** (เปิดซ้ำระหว่าง optimize · B68) | **1** (เปิดครั้งเดียว) |
| scoring fingerprint | 21/21 | 21/21 |
| full pytest ก่อน final | ไม่ได้ทำแยก | **893 passed** บันทึก image/commit |
| single-open guarantee | เสีย | **รักษาไว้** |

Round 2b ทำตามลำดับ protocol ครบ: pre-register candidate → commit → parity →
freeze → **full pytest** → final ครั้งเดียว · B68 ledger บันทึก [106-110] open_count=1
· holdout guard ทำงาน (ถ้ารัน final ซ้ำจะถูกปฏิเสธ)

---

## 5. paired hierarchical bootstrap — B เทียบ L3 configs

ΔRecall / ΔRecall@challenge (B − config) บน holdout เดียวกัน · paired:

| เทียบ | ΔRecall | 95% CI | ΔRecall@ch | ΔCampaignRecall | sign |
|---|---|---|---|---|---|
| B − C | −0.0146 | [−0.0297, +0.0001] | **+0.0246** | +0.0000 | 0.97 |
| B − D | +0.0563 | [+0.0366, +0.0786] | +0.0481 | −0.0024 | 1.00 |
| B − E | +0.0326 | [+0.0078, +0.0593] | +0.0967 | −0.0016 | 0.99 |

- **B − C:** C (point-all L3) มี recall แบบ warn+ สูงกว่า B เล็กน้อย (−0.0146, CI แตะ 0)
  **แต่** ที่ระดับ enforcement B สูงกว่า (ΔRec@ch +0.0246) · และ **C ไม่ผ่าน gate**
  (challenge 1.15%) → ในกลุ่มที่ผ่าน gate B คือผู้นำ recall
- **B − D, B − E:** B สูงกว่าชัดทั้ง recall และ recall@challenge (CI ไม่คร่อม 0)
- **ΔCampaignRecall ≈ 0 ทุกคู่** → L3 ไม่เพิ่มการจับระดับแคมเปญ (ยืนยัน Round 1)

**หมายเหตุ metric (กันอ่านสับสน):** `campaign_l3_only_hierarchical_ci` ของ C/D/E =
0.25-0.27 (CI hierarchical) คือ **within-config counterfactual** — "L3 เปลี่ยนผลบาง
event ใน 25-27% ของแคมเปญ (ภายใน config นั้นเอง)" · **ไม่ใช่** "L3 จับแคมเปญที่ B พลาด"
ซึ่งวัดด้วย ΔCampaignRecall = ~0 · สองค่านี้ต่างกัน: L3 ขยับ event ในหลายแคมเปญ แต่
แคมเปญเหล่านั้น B ก็จับได้อยู่แล้ว (event อื่น / ระดับ challenge-block) → net = 0

---

## 6. tail calibration (deployed B, validation → holdout)

| ระดับ | nominal | observed (holdout) | ratio |
|---|---|---|---|
| p95 | 5.0% | 6.52% | 1.30 |
| p99 | 1.0% | 0.97% | 0.97 |
| p99.9 | 0.1% | — | — |

- `tail_shift_detected = False` · p99 (ตรงกับ challenge) ที่ 0.97% ≈ nominal → challenge
  ระดับ macro ไม่ shift · p95 (ตรงกับ warn) shift ขึ้น 1.30× แต่ warn threshold ตั้งเผื่อ
  ไว้แล้ว (0.98) จึงยังใต้งบ
- **ไม่ใช้ ECE** — ค่านี้เป็น percentile evidence ไม่ใช่ probability (ดู B67/tailcal)

---

## 7. สรุปและสิ่งที่ต้องตัดสิน

**สิ่งที่สำเร็จ (ยืนยันบน holdout ใหม่ที่เปิดครั้งเดียว):**
1. warn fix (0.98) + block fix (0.9999) **ได้ผลทั้งคู่** — warn 5.26%→2.71%, block 0.25%→0.07%
2. provenance สะอาด — single-open (ledger open_count=1), full pytest 893 passed, integrity 21/21
3. paired bootstrap: B เป็นผู้นำ recall ในกลุ่ม + L3 ไม่เพิ่ม campaign recall (ΔCampaign≈0)
4. B ใกล้ผ่าน per-size ที่สุดใน 3 รอบ — เหลือ **จุดเดียว** (challenge@50)

**การตัดสิน (2026-09-04): gate = per-size** — `_final_gate()` แก้ให้ตรวจ per-size
ตรงกับ `sweep.eligible()` ที่ใช้ตอน tune · protocol §3 อัปเดตระบุ per-size ชัดเจน

**ผลภายใต้ per-size: `final_round_2b_failed_gate`**
- **ไม่มี config ใดผ่าน** (ทุกตัวตกที่ cold-start size 50 อย่างน้อยหนึ่งระดับ · แม้ F ที่
  ผ่าน macro ก็ตก block@50=0.22%)
- **B ตกน้อยที่สุด** — challenge@50 = 1.23% (overshoot 0.23pp ที่ประวัติน้อยสุด) ·
  ทุก size×level อื่นผ่าน
- **ไม่ deploy** ตาม fallback · ระบบ production ไม่เปลี่ยน · L3 ยัง shadow

**ทำไม cold-start challenge แก้ยากกว่า warn/block:**
- block คันโยกฟรี (block→challenge ไม่กระทบ recall) · warn แลกแค่ soft-warn recall
- **challenge ผูกกับ enforcement** — ยก challenge threshold ที่ size 50 ลด challenge FPR
  ได้ แต่ก็ลด recall@challenge (attack ที่ step-up ได้จะหลุด) ที่ผู้ใช้ cold-start ·
  เป็น warm-up ของ behavior profiling เดียวกับ warn แต่ที่ระดับ challenge

**Round 2c (ถ้าจะทำต่อ):** แก้ cold-start challenge ที่ size 50 — อาจเป็น maturity-tier
challenge threshold หรือแก้ warm-up ที่ต้นเหตุ · งานออกแบบใหม่ (ไม่ใช่คันโยกฟรี) ·
ต้อง **holdout ชุดใหม่อีก** (ไม่ใช่ 106-110 spent, ไม่ใช่ 201-205 ของ Round 3) ·
ก่อนทำควรวิเคราะห์บน validation ว่าแก้ได้โดยไม่เสีย recall@challenge มากไหม

## 8. ทำซ้ำ

```bash
# frozen commit 8e6dc3f · holdout [106-110] เปิดแล้ว (ledger open_count=1)
# final ซ้ำจะถูกปฏิเสธ (B68 ledger + fingerprint)
cd hub/backend
PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py parity --seed 42 --size 500
```

artifact (gitignored): `final_result.json` · `holdout_ledger.json` · `frozen_config.json`
