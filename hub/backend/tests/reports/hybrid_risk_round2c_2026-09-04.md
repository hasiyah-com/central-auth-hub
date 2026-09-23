# Hybrid Risk — Round 2c Final (2026-09-04)

> ## สถานะ: `final_round_2c_failed_gate` — B ตก per-size ที่ challenge@size50 = 1.18%
>
> **⚠️ รายงานนี้ถูกแก้ไข 2026-09-04 (ดู §8 — บันทึกการแก้)** ฉบับแรกสรุปว่า
> "threshold tuning หมดทาง" และ "root cause = login_velocity" ซึ่ง**สรุปเกินหลักฐาน
> ทั้งสองข้อ** · ข้อสรุปที่ตรงหลักฐานคือ **validation 5 seeds ประเมิน population
> variance ของ cold-start ต่ำเกินไปอย่างเป็นระบบ** — ไม่ใช่ว่า threshold แก้ไม่ได้
>
> Config B ไม่ผ่าน per-size gate (challenge@size50 = 1.18% > 1%) · ขนาดอื่นผ่านหมด ·
> ไม่มี config ใหม่พร้อม deploy · fallback = current production / L3 shadow

| | |
|---|---|
| รอบ | **Round 2c** |
| commit ที่ freeze | `950288be044c` · fingerprint 21/21 |
| candidate | Config B · γ=1.0 · warn=0.98 · **challenge=0.995** · block=0.9999 |
| holdout | `[111-115]` · 316,150 เหตุการณ์ · leakage 0 · **open_count=1** (single-open) |
| shortcut audit | 0/23 |
| full pytest | ยกจาก Round 2b (hub-backend code byte-identical · image `d140bf98e81d`) — ดู §5 |

---

## 1. per-size gate บน holdout [111-115]

| cfg | recall | rec@ch | warn (macro) | ch (macro) | blk (macro) | per-size |
|---|---|---|---|---|---|---|
| A legacy | 0.9012 | — | 2.51% | 2.65% | 0.14% | ไม่ผ่าน (ch ทุกขนาด) |
| **B** (candidate) | 0.8324 | 0.6952 | **2.41%** | **0.77%** | **0.05%** | **ไม่ผ่าน (ch@50=1.18%)** |
| C +point | 0.8762 | — | 4.72% | 1.11% | 0.13% | ไม่ผ่าน (ch@50/100) |
| D +sequence | 0.7912 | — | 3.08% | 1.18% | 0.16% | ไม่ผ่าน (ch/blk หลายขนาด) |
| E +ทั้งสอง | 0.8227 | — | 3.85% | 1.19% | 0.12% | ไม่ผ่าน (ch หลายขนาด) |
| F weighted sum | 0.7802 | — | 2.78% | 0.68% | 0.17% | **ผ่าน** (comparator เท่านั้น) |

**B per-size:** size 100/500/1000/5000 ผ่านหมด (ch 0.55-0.87%) · **ตกเฉพาะ size 50
(ch 1.18%)** · warn/block ผ่านทุกขนาด

**F ผ่าน per-size** บน holdout นี้ แต่เป็น comparator — ไม่ใช่ candidate ที่ประกาศไว้
(post-hoc prohibited เหมือนทุกรอบ) และ recall ต่ำ (0.78 warn+)

---

## 2. cold-start challenge เกินงบทั้งสอง holdout — validation ประเมินต่ำเกินไป

Config B challenge@size50 (cold-start) ข้ามรอบ:

| รอบ | holdout | challenge thr | validation worst-seed | holdout ch@size50 | ผ่าน |
|---|---|---|---|---|---|
| Round 2b | [106-110] | 0.9898 | 1.67% | 1.23% | ✗ |
| Round 2c | [111-115] | 0.995 | **0.73%** | **1.18%** | ✗ |

**สิ่งที่สรุปได้:** ทั้งสองรอบ holdout cold-start challenge FPR **สูงกว่า validation
worst-seed อย่างมีนัย** (0.73% → 1.18%) → **validation 5 seeds bound worst-case ของ
ประชากรใหม่ไม่ได้** เป็นรูปแบบที่เกิดซ้ำ

**สิ่งที่สรุปไม่ได้ (แก้จากฉบับแรก):** ฉบับแรกเทียบ 1.23% (2b) กับ 1.18% (2c) แล้วสรุปว่า
"ยก threshold แล้วแทบไม่ขยับ → threshold หมดทาง" — **การเทียบนี้ confound** เพราะสอง
holdout เป็น **คนละประชากร** จึงแยกไม่ออกว่าส่วนไหนมาจาก threshold ส่วนไหนมาจากประชากร
(ข้อผิดพลาดแบบเดียวกับ B67: อนุมานสาเหตุจากสองจุดที่ต่างกันหลายอย่างพร้อมกัน)

**หลักฐานว่า threshold ยังมีผล** — องค์ประกอบของ challenged normal (validation,
challenge=0.995):

| size | chFPR | จาก policy floor | จาก score | %floor |
|---|---|---|---|---|
| 50 | 0.58% | 38 | 137 | 21.7% |
| 100 | 0.53% | 38 | 121 | 23.9% |
| 500 | 0.40% | 38 | 81 | 31.9% |
| 1000 | 0.46% | 38 | 99 | 27.7% |
| 5000 | 0.44% | 38 | 95 | 28.6% |

- **68–78% ของ challenged normal มาจาก score** ซึ่ง threshold ควบคุมได้ → threshold
  **ไม่ได้หมดทาง**
- policy floor คงที่ **38 เหตุการณ์ทุกขนาด** = 0.126% ตรงกับ `attainable_floor`
  0.127% ของ Round 1 · floor มาจาก `concurrent_session_count` (36) และ
  `active_subsystem_count` (2) — **ไม่ขึ้นกับขนาดประวัติ**
- `is_new_device` / `is_new_user_agent_family` / `is_new_country` **ไม่ปรากฏใน floor เลย**
  ที่ cold-start (หักล้างสมมติฐานว่า cold-start ทำให้ floor พวกนี้ยิงบ่อย)

---

## 3. บทบาทของ login_velocity — แก้จากฉบับแรก

ฉบับแรกระบุว่า root cause คือ `login_velocity` rule ที่ไม่ personalize **ซึ่งระบุบทบาทผิด**

- `login_velocity` (compound: gap ≤ 2.0 และ count_24h ≥ 5) ตั้ง `floor_rank = challenge`
  ใน `evaluate_rules` **แต่ `rule.min_action` ไม่ถูกส่งเข้า `fuse()`** ในสถาปัตยกรรมใหม่
  (`fuse` ใช้เฉพาะ `policy.min_action` จาก `evaluate_policy` ซึ่งมาจาก
  `SCORE_RULES_SPEC` ที่ `kind == "policy_floor"` — เป็น single-feature เท่านั้น)
- → login_velocity มีผลเป็น **+0.25 คะแนน** เท่านั้น **ไม่ใช่ policy floor**
  จึง**ถูกควบคุมด้วย threshold ได้** ต่างจากที่ฉบับแรกอ้าง
- ตัวเลข "83% ของ s45 challenged normal มาจาก login_velocity" คือ**ความถี่ในลิสต์
  `reasons`** ไม่ใช่การพิสูจน์ว่าเป็นปัจจัยตัดสิน (reason ปรากฏได้พร้อมกันหลายตัว)

**สรุป:** login_velocity เป็น *ส่วนหนึ่ง* ของ score-driven component แต่หลักฐานปัจจุบัน
**ไม่พอสรุปว่าเป็น root cause** และการ personalize มันไม่ใช่ทางแก้ที่หลักฐานชี้

---

## 4. paired hierarchical bootstrap (holdout [111-115])

| เทียบ | ΔRecall | 95% CI | ΔRec@ch | ΔCampaign | sign |
|---|---|---|---|---|---|
| B − C | −0.0436 | [−0.0592, −0.0293] | +0.0262 | +0.0000 | 1.00 |
| B − D | +0.0415 | [+0.0236, +0.0609] | +0.0484 | −0.0033 | 1.00 |
| B − E | +0.0102 | [−0.0141, +0.0359] | +0.0933 | −0.0041 | 0.78 |

- C มี warn+ recall สูงกว่า B (−0.0436) แต่ B สูงกว่าที่ enforcement (ΔRec@ch +0.026) ·
  C ไม่ผ่าน gate อยู่ดี
- **ΔCampaignRecall ≈ 0 ทุกคู่** → L3 ไม่เพิ่มการจับระดับแคมเปญ (ยืนยันทุกรอบ)

---

## 5. Provenance

- **single-open:** ledger [111-115] open_count = **1** · frozen fingerprint 21/21 ตรง
- **full pytest ยกจาก Round 2b:** hub-backend code **byte-identical** ระหว่าง Round 2b
  freeze (8e6dc3f) → Round 2c freeze (950288b) — `git diff` แสดงเปลี่ยนเฉพาะ
  `exp_hybrid_gate.py` (harness นอก container) + report .md · container test suite ทดสอบ
  โค้ด hub-backend ที่ไม่เปลี่ยน → ผล **893 passed** (image `sha256:d140bf98e81d`) คงเดิม
  · ณ เวลารายงาน container cah-hub หยุด (มี stack `cah-isolated-test` รันอยู่) จึงไม่ start
  ทับเพื่อไม่รบกวน — ยืนยันด้วย git diff + fingerprint แทน

---

## 6. สรุปและทางเลือก

**สถานะ Round 2 (threshold tuning):**
- block fix (0.9999) ✓ · warn fix (0.98) ✓ — ทั้งคู่ได้ผลบน holdout ใหม่
- **cold-start challenge (size 50) ✗** — ยังเกินงบทั้งสอง holdout
- ไม่มี config ที่ประกาศไว้ผ่าน per-size gate · production ไม่เปลี่ยน · L3 shadow

**ปัญหาที่แท้จริงตามหลักฐาน:** ไม่ใช่ "threshold แก้ไม่ได้" (score-driven 68–78%
ยังควบคุมได้ด้วย threshold) แต่คือ **เราเลือก threshold ที่ถูกไม่ได้จาก validation
5 seeds** เพราะ worst-of-5 ประเมิน worst-case ของประชากรใหม่ต่ำเกินไปอย่างเป็นระบบ
(เกิดซ้ำทั้ง 2b และ 2c)

**ทางที่หลักฐานชี้:**
1. **เพิ่มจำนวน validation seeds** (เช่น 15 seeds) แล้วเลือก threshold จาก **quantile
   สูงข้ามประชากร** (เช่น p90/p95 ของ per-seed FPR) แทน max-of-5 → ประมาณ worst-case
   ได้แม่นขึ้นและมี margin ที่มีเหตุผลรองรับ
2. เพดานที่ลดไม่ได้: policy floor 0.126% (`concurrent_session_count` /
   `active_subsystem_count`) — ถ้าจะลดต่ำกว่านี้ต้องแก้ที่ Policy Gate ไม่ใช่ threshold

**ยังไม่ทำ:** personalize `login_velocity` — หลักฐานไม่พอสนับสนุนว่าเป็น root cause (§3)

---

## 7. ทำซ้ำ

```bash
# frozen 950288b · holdout [111-115] เปิดแล้ว (open_count=1) · final ซ้ำถูกปฏิเสธ (B68)
cd hub/backend && PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py parity --seed 42 --size 500
```

---

## 8. บันทึกการแก้ไขรายงาน (2026-09-04)

ฉบับแรกของรายงานนี้ (commit `0cfd965`) มีข้อสรุปที่**เกินหลักฐาน 2 ข้อ** และถูกแก้แล้ว:

| ข้อสรุปเดิม | ปัญหา | แก้เป็น |
|---|---|---|
| "threshold tuning หมดทางกับ cold-start challenge" | เทียบ 1.23% (2b) กับ 1.18% (2c) ซึ่งมาจาก **คนละ holdout population** → confound ระหว่างผลของ threshold กับผลของประชากร | validation 5 seeds ประเมิน population variance ต่ำเกินไป · threshold ยังมีผล (score-driven 68–78%) |
| "root cause = login_velocity rule ไม่ personalize" | `rule.min_action` ถูก drop ใน fuse → login_velocity เป็น +0.25 คะแนน ไม่ใช่ floor · ตัวเลข 83% เป็นความถี่ใน reasons ไม่ใช่การพิสูจน์เชิงสาเหตุ | ยังไม่ทราบ root cause ที่แน่ชัด · login_velocity เป็นเพียงส่วนหนึ่งของ score |

**หลักฐานใหม่ที่ใช้แก้:** การวัดองค์ประกอบ floor vs score ของ challenged normal
(§2) — policy floor คงที่ 38 เหตุการณ์ทุกขนาด (0.126%) ส่วนที่เหลือเป็น score-driven

**บทเรียน (ตระกูลเดียวกับ B67):** การอนุมานว่า "การแก้ X ไม่ได้ผล" จากการเทียบสองรอบที่
**เปลี่ยนทั้ง X และข้อมูล**พร้อมกัน เป็นการอนุมานที่ทำไม่ได้ · ต้องแยกตัวแปร (วัดบน
ข้อมูลชุดเดียวกัน) หรือระบุให้ชัดว่าสรุปไม่ได้
