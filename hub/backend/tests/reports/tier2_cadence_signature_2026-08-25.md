# Tier 2 — cadence z-score (velocity รายคน) + signature_rarity (device graded)

**วันที่:** 25 ส.ค. 2026
**ต่อจาก:** [`tier1_rarity_behavior_2026-08-25.md`](tier1_rarity_behavior_2026-08-25.md)
**ที่มา:** เก็บ 3 ของ V8 ที่เหลือ — `cadence_tail`, `signature_rarity`, `_robust_center_scale`
(สถิติล้วน ไม่ใช่ ML) มาเป็น **graded accumulator** เสริมชั้น behavior
**วิธี:** TDD (RED→GREEN→REFACTOR) + วัดบน V2 + probe test จำลอง attack เนียนที่ rule พลาด

---

## สรุป

> **Tier 2 = defense-in-depth ที่ "ฟรี" บน V2 (recall/FPR ไม่ขยับเลย) + จับ attack เนียนที่ rule global พลาด**
> V2 attack เป็น single-event แรง → rule จับหมดตั้งแต่ Tier 1 แล้ว → Tier 2 ไม่มีอะไรให้เพิ่ม *บน V2*
> คุณค่าจริงอยู่ที่ **stealth attack ที่หลบใต้ threshold ของ rule** ซึ่งพิสูจน์ด้วย probe test แยก

---

## 1. บน V2 — ไม่ regress ไม่มี FPR cost (defense-in-depth ฟรี)

| ตัวชี้วัด | Tier 1 | +Tier 2 | ต่าง |
|---|---|---|---|
| Recall | 95.8% | 95.8% | 0.0 |
| Challenge FPR | 2.1% | 2.1% | **0.0** ✅ |
| Warn FPR | 5.8% | 5.8% | 0.0 |
| Precision | 98.3% | 98.3% | 0.0 |

**cadence ไม่ยิง V2 normal เลย** (z ≤ −2.5 เข้มพอ) → เพิ่ม signal โดยไม่เพิ่ม false alarm
(signature เทสบน V2 ไม่ได้เพราะ features_v2.csv ไม่มี raw UA — เทสผ่าน probe unit แทน)

---

## 2. Probe — Tier 2 จับ attack เนียนที่ rule พลาด (`test_tier2_catches_evasive.py`)

soft signal เป็น **accumulator**: ตัวเดียวไม่ทะลุ threshold เอง (จงใจ กัน FPR) — ต้อง *converge*
กับ signal อื่น (+ iforest score เล็กน้อยที่ stealth attack มักมี) → ทะลุ `warn` เผยตัว

| probe | สถานการณ์ | ไม่มี Tier 2 | +Tier 2 |
|---|---|---|---|
| 1 | login ~20 นาที (เหนือ rule log_min≤2) + iforest อ่อน 0.25 | allow | **warn** (cadence tip) |
| 2 | fast cadence + iforest 0.15 + **rare-seen device** | allow | **warn** (signature เป็นตัวชี้ขาด) |
| 3 (control) | login ปกติทุกอย่าง | — | **allow** (ไม่มี false alarm) |
| 4 | soft signal เดี่ยว ไม่มี corroboration | — | **allow** (ไม่ทะลุเอง — กัน FPR) |

→ **personalized velocity ดีกว่า rule global:** คนที่ปกติ login ห่างเป็นวัน จู่ๆ login ทุก 20 นาที
= ผิดปกติสำหรับเขา แม้ 20 นาทีไม่ทริป rule (log_min≤2 ≈ 7 นาที) — z-score เทียบ distribution รายคนจับได้

---

## 3. สิ่งที่เพิ่ม (สถิติล้วน)

### cadence z-score (velocity รายคน)
- `get_user_profile` เก็บ gap distribution: `_robust_center_scale(gap_logs)` → median + IQR (มี floor)
- `evaluate_behavior`: `z = (gap ปัจจุบัน − median) / IQR` · `z ≤ −2.5` (เร็วกว่าปกติมาก) → **+0.25**
- **`_robust_center_scale`** = median + IQR (ทน outlier กว่า mean/std) — เก็บมาจาก V8 ตรงๆ
- ยัง **ไม่ทะลุ warn (0.5) เอง** — กัน FPR, เป็น accumulator

### signature_rarity (device graded)
- `get_user_profile` เก็บ `signature_counts` (จาก `_device_signature(user_agent)` ของ history)
- `evaluate_behavior(..., user_agent)`: เฉพาะ device ที่ **เคยเห็นแต่ rarity ≥ 0.90** → +0.15
- **เครื่องใหม่ล้วน (count=0) ไม่ยิง** — ปล่อยให้ `is_new_device` rule จัดการ (ไม่ทับซ้อน ตาม B56)
- ต้อง thread `user_agent` เข้า `evaluate_login_risk` → 5 call sites (auth×3, oauth, passkey)

---

## 4. ทำไม soft (0.15–0.25) ไม่ใช่ challenge floor

- Tier 1 (hour_rarity 0.30, subsystem novelty = **floor challenge**) จับเหตุการณ์ **แน่นอน**
  (เคย/ไม่เคยใช้ระบบ = deterministic) → เข้มได้
- Tier 2 (cadence/signature) เป็น **แนวโน้ม/ความน่าจะเป็น** (เร็วกว่าปกติแค่ไหน, device rare แค่ไหน)
  → soft accumulator ถูกต้องกว่า: ยิงเดี่ยว = allow (กัน FPR), converge = warn (เผย stealth)

---

## 5. ไฟล์

| ไฟล์ | เปลี่ยน |
|---|---|
| `app/security/behavior_profiling.py` | `_robust_center_scale`, `_quantile` · profile เก็บ gap stats + signature_counts · `evaluate_behavior(..., user_agent)` + cadence z + signature_rarity |
| `app/security/risk_engine.py` | `evaluate_login_risk(..., user_agent)` → ส่งเข้า behavior |
| `app/routers/{auth,oauth,passkey}.py` | ส่ง `user_agent=user_agent` (5 call sites) |
| `tests/test_behavior_tier2.py` | 7 unit tests (cadence/signature ยิง/ไม่ยิง, B56 defer, backward compat) |
| `tests/test_tier2_catches_evasive.py` | 4 probe tests (convergence จับ stealth, ไม่มี false alarm) |
| `ml-service/scripts/eval_production_v2.py` | profile เพิ่ม gap stats (cadence active บน V2) |

## 6. TDD log

```
RED    test_behavior_tier2.py  →  3/7  (evaluate_behavior ยังไม่รับ user_agent)
GREEN  implement + fix signature key casing  →  7/7
probe  test_tier2_catches_evasive.py  →  4/4 (หลังปรับ cadence 0.15→0.25 + reframe convergence)
REFACTOR  V2 metrics ไม่ขยับ · 32/32 offline tests · compile OK (5 ไฟล์)
```

## 7. สถานะ

- ✅ Tier 1 + Tier 2 เสร็จ — recall 85%→95.8%, 2 scenario 0% แก้แล้ว, Challenge FPR คงที่ 2.1%
- ✅ เก็บของดีของ V8 ครบ (hour/subsystem/cadence/signature rarity + robust scale) เป็นสถิติล้วน
- ⏳ ต้องรัน full pytest ใน docker ก่อน commit (test_risk_scenarios มี db fixture)
- ยังไม่ commit (รอ OK)
- **ต่อไปได้:** เขียน bug/lesson (B61: harvest V8's rarity ไม่ใช่ neural) + อัปเดต roadmap ·
  หรือทำ campaign-attack generator เพื่อทดสอบ Tier 2 + V8 อย่าง fair
