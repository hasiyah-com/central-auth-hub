# Round 2b — หลักฐานก่อน Freeze (2026-09-04)

> candidate ยืนยันแล้ว: **Config B · warn=0.98 · block=0.9999 · holdout [106-110]**
> · ทุกตัวเลขในนี้วัดบน **validation เท่านั้น** (cells seed 42-46) · ยังไม่เปิด holdout ใหม่

## 1. ปัญหาที่ต้องแก้ (จาก Round 2)

Config B ผ่าน challenge/block บน holdout `[101-105]` แต่ **warn FPR 5.26% > 5%**
(ขนาด 500/1000 → ~6.8%) · ต้องยก warn threshold ให้ทน แต่ warn **ไม่ใช่คันโยกฟรี**
เหมือน block (ยก warn → ลด recall แบบ warn+)

## 2. ค้นพบสำคัญ — shift มาจาก population variance ไม่ใช่ in-sample optimism

**วัด validation-internal shift** (calib split = reference → tuning split = out-of-sample
ภายใน validation) ด้วย `tailcal.benign_exceedance`:

| ระดับ | nominal | observed (tuning) | ratio |
|---|---|---|---|
| p95 | 5.0% | 4.54% | 0.91 |
| p99 | 1.0% | 0.98% | 0.98 |
| p99.9 | 0.1% | 0.10% | 1.03 |

→ **shift ภายใน validation ≈ 0** (tuning exceedance ต่ำกว่า nominal ด้วยซ้ำ) ·
per-size p95 ratio 0.79-0.91 ทุกขนาด · calib และ tuning มาจาก seed เดียวกัน (42-46)
จึง exchangeable ไม่มี optimism

**แต่ validation→holdout shift ใหญ่** (+2.3pp) → สรุป: shift มาจาก **ความแปรปรวน
ระหว่าง seed (ประชากรผู้ใช้)** ไม่ใช่ in-sample optimism · holdout ใช้ seed ต่างชุด
= การสุ่มประชากรใหม่

## 3. ยืนยันด้วย per-seed — บาง population ทะลุ 5% บน validation อยู่แล้ว

warn FPR ราย seed ที่ขนาด 500/1000 (warn=0.9417 ของ Round 1):

| ขนาด | s42 | s43 | s44 | s45 | s46 |
|---|---|---|---|---|---|
| 500 | 2.6% | 2.9% | **5.2%** | **5.1%** | **6.2%** |
| 1000 | 2.6% | 3.1% | **6.2%** | **5.1%** | **6.1%** |

seed 44/45/46 ทะลุ 5% **บน validation** อยู่แล้ว · macro (3.76%) กลบไว้ →
Round 1 warn=0.9417 ไม่เคย robust ต่อ population variance

## 4. เลือก warn ด้วยเกณฑ์ worst-seed (max ข้าม seed×size, validation)

| warn | worst-seed warn FPR | recall (warn+) | recall@challenge |
|---|---|---|---|
| 0.9417 (R1) | **6.25% ✗** | 0.8961 | 0.7252 |
| 0.95 | 4.02% | 0.8684 | 0.7252 |
| 0.97 | 3.52% | 0.8676 | 0.7252 |
| **0.98** | **2.88%** | **0.8617** | **0.7252** |
| 0.985 | 2.02% | 0.8184 | 0.7252 |

- warn=0.98: worst-seed 2.88% → **margin ~2.1pp** ใต้งบ 5%
- **recall@challenge = 0.7252 นิ่งสนิททุก threshold** → enforcement (challenge/block)
  ไม่กระทบเลย · เสียแค่ recall แบบ warn+ (soft signal)
- การยก warn ไม่ใช่แค่ลดค่าเฉลี่ย แต่ **ยุบ variance** (seed 44/45/46 ลงมาเท่า 42/43)

## 5. อะไรที่เสียตอนยก warn 0.9417 → 0.98 (warn-only detection)

attack family ที่ "surface เฉพาะระดับ warn" แล้วหลุดเป็น allow:

| family | lost/total | % |
|---|---|---|
| campaign | 326/3000 | 10.9% |
| subtle_quiet_lateral | 26/600 | 4.3% |
| subtle_mild_offhour | 18/600 | 3.0% |
| subtle_rare_device | 6/250 | 2.4% |
| subtle_lowandslow | 12/600 | 2.0% |
| new_passkey | 6/600 | 1.0% |
| off_hours | 5/600 | 0.8% |
| subsystem_lateral | 1/300 | 0.3% |

- เกือบทั้งหมดเป็น **soft warn** บน attack เงียบ (subtle_*) และ campaign
- `campaign` เป็น multi-event — เสีย warn ที่ event เดียวไม่ได้แปลว่าพลาดแคมเปญ
  (event อื่น + ระดับ challenge/block ยังจับได้)
- family ที่เหลือ (combined_ato, new_device, failed_spike, velocity ฯลฯ) **ไม่เสียเลย**
  เพราะถูกจับที่ระดับ challenge/block อยู่แล้ว

## 6. เหตุผลเลือก 0.98 ไม่ใช่ 0.97

- 0.97 กับ 0.98 recall ต่างแค่ 0.6pp (soft warn) แต่ margin ต่างกัน 1.5pp vs 2.1pp
- holdout `[106-110]` เป็น **ประชากรชุดใหม่** ที่อาจแย่กว่า 5 seed ของ validation ·
  worst-of-5 ประเมิน worst-case ต่ำไป → margin กว้างปลอดภัยกว่า
- Round 2 สอนว่าการตึงงบเกินไปแตกบน holdout ใหม่ · จ่าย soft-warn 0.6pp เพื่อ margin
  คุ้มกว่า

## 7. candidate ที่จะ freeze

```
Config B · gamma=1.0 · warn=0.98 · challenge=0.989833 · block=0.9999
holdout_seeds: [106, 107, 108, 109, 110]
fallback: current production / L3 shadow
```

**คาดการณ์ holdout [106-110]** (คาดจากโครงสร้าง ไม่ใช่ผลจริง): warn FPR น่าจะ ~3-4%
(worst-seed validation 2.88% + population variance) · challenge/block/recall เหมือน
Round 2 (ไม่กระทบจาก warn) · **แต่ success ไม่การันตี** — ประชากรใหม่อาจ shift ต่างไป
