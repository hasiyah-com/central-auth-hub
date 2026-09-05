# Hybrid Risk — Round 2c Final (2026-09-04)

> ## สถานะ: `final_round_2c_failed_gate` — threshold tuning หมดทางกับ cold-start challenge
>
> **Config B ยังไม่ผ่าน per-size gate** — ตกจุดเดิม **challenge@size50 = 1.18%** (ดีขึ้น
> จาก Round 2b's 1.23% เพียง 0.05pp) · การยก challenge 0.9898→0.995 **จ่าย enforcement
> recall −0.7pp แต่ลด cold-start challenge FPR แทบไม่ได้** เพราะประชากร size-50 บน
> holdout ใหม่แย่กว่า worst-seed ของ validation · **ข้อสรุป: การจูน threshold แก้
> cold-start challenge ไม่ได้อย่างเชื่อถือได้ — ต้องแก้ที่ root cause (L1 login_velocity)**
> · ไม่มี config ใหม่พร้อม deploy · fallback = current production / L3 shadow

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

## 2. threshold tuning หมดทาง — หลักฐานข้ามรอบ

Config B challenge@size50 (cold-start) ข้ามรอบ:

| รอบ | holdout | challenge thr | ch@size50 | recall@challenge | ผ่าน size50 |
|---|---|---|---|---|---|
| Round 2b | [106-110] | 0.9898 | 1.23% | 0.7026 | ✗ |
| **Round 2c** | [111-115] | **0.995** | **1.18%** | **0.6952** | **✗** |

- ยก challenge 0.9898 → 0.995 (validation worst-seed 1.67% → 0.73%) แต่บน holdout
  ใหม่ size-50 ลดแค่ **1.23% → 1.18%** (−0.05pp)
- **จ่าย enforcement recall −0.7pp (0.7026 → 0.6952) เพื่อผลแทบเป็นศูนย์**
- สาเหตุ: cold-start challenge FPR ถูกขับด้วย **population variance ที่ size 50** ซึ่ง
  validation 5 seeds bound ไม่ได้ — holdout ใหม่ดึงประชากรที่แย่กว่า worst-seed เสมอ
- tail cal: p99 exceedance 1.19% (nominal 1%) — challenge-level tail ยกขึ้นเล็กน้อย
  สอดคล้องกับ size-50 ที่เกิน

> **บทสรุป:** การจูน global challenge threshold บน validation **ไม่สามารถแก้ cold-start
> challenge FPR ได้อย่างเชื่อถือได้** — ยกสูงเท่าไรก็เสีย enforcement ทั่วทั้งระบบ แต่
> tail ของประชากร cold-start ที่แย่สุดยังทะลุ เพราะ validation ประเมิน worst-case ต่ำไป

---

## 3. Root cause — login_velocity rule (L1) ไม่ personalize (จาก §2-3 ของ prefreeze)

s45 (validation) normal ที่ถูก challenge: **83% มาจาก `rule:login_velocity (+0.25)`** —
L1 rule flag velocity สูงว่าเสี่ยง ทั้งที่เป็น pattern ปกติของผู้ใช้ (ไม่ personalize)

- **ยก challenge เสีย step-up ของ login_velocity attack (−0.12)** ทั้งที่ต้นเหตุคือ
  login_velocity rule ยิง false positive → แก้ปลายเหตุทำร้าย signal เดียวกันสองทาง
- **ทางแก้จริง: personalize login_velocity** (velocity ที่ปกติของ user ไม่ถูก flag) →
  แก้ cold-start false positive **โดยไม่เสีย** velocity detection และไม่เสีย enforcement
  recall · แต่เป็นการแก้ **L1 scoring logic** (scope ใหญ่ ต้อง re-validate ทุก config)

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

**Round 2 (threshold tuning) ครบวงจรแล้ว:**
- block fix (0.9999) ✓ · warn fix (0.98) ✓ — ทั้งคู่คันโยกที่ทำได้ด้วย threshold
- **challenge cold-start (size 50) ✗** — threshold แก้ไม่ได้อย่างเชื่อถือได้ (2 รอบยืนยัน)
- ทุกรอบ: ไม่มี config ที่ประกาศไว้ผ่าน per-size gate · production ไม่เปลี่ยน · L3 shadow

**สิ่งที่เหลือเป็นทางเลือก (นอกขอบเขต threshold tuning ของ Round 2):**

1. **แก้ root cause — personalize login_velocity (L1)** · แก้ cold-start false positive
   โดยไม่เสีย enforcement · เป็น L1 scoring change (scope เท่า Round 3) · ต้อง validation
   ใหม่ + holdout ชุดใหม่ · **เป็นทางที่หลักฐานชี้ว่าถูกต้อง**
2. **ยอมรับว่า L1+L2 baseline ไม่ผ่าน per-size cold-start challenge ด้วย threshold** และ
   สรุป Round 2 ที่จุดนี้ — binding constraint คือ login_velocity ที่ไม่ personalize
3. (ไม่แนะนำ) ยก challenge สูงกว่านี้อีก — จ่าย enforcement recall มากขึ้นเพื่อผลเล็กน้อย

**ข้อเสนอ:** สรุป Round 2 ว่า threshold tuning ทำ block/warn ได้แต่ cold-start challenge
ต้องแก้ที่ L1 · งาน personalize login_velocity เป็นรอบใหม่ (คู่กับหรือก่อน Round 3) ที่มี
pre-registration + holdout ของตัวเอง

## 7. ทำซ้ำ

```bash
# frozen 950288b · holdout [111-115] เปิดแล้ว (open_count=1) · final ซ้ำถูกปฏิเสธ (B68)
cd hub/backend && PYTHONPATH=. python ../../ml-service/scripts/exp_hybrid_gate.py parity --seed 42 --size 500
```
