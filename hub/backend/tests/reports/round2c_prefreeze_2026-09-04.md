# Round 2c — หลักฐานก่อน Freeze (2026-09-04)

> candidate: **Config B · warn=0.98 · challenge=0.995 · block=0.9999 · holdout [111-115]**
> · ทุกตัวเลขวัดบน **validation เท่านั้น** (cells 42-46) · ยังไม่เปิด holdout ใหม่

## 1. ปัญหาจาก Round 2b

per-size gate: B ตกที่ cold-start **challenge@size50 = 1.23% > 1%** บน holdout [106-110]
· warn/block ผ่านทุกขนาด · ต้องแก้ challenge

## 2. ตัวขับคือ population variance ไม่ใช่ cold-start

challenge FPR ราย seed ที่ challenge=0.9898 บน validation:

| size | s42 | s43 | s44 | s45 | s46 | worst |
|---|---|---|---|---|---|---|
| 50 | 1.23% | 0.47% | 0.55% | **1.67%** | 0.73% | 1.67% |
| 500 | 0.48% | 0.38% | 1.02% | **1.47%** | 0.42% | 1.47% |
| 5000 | 0.48% | 0.38% | 0.32% | **1.48%** | 0.63% | 1.48% |

- **s45 ~1.5% ที่ทุกขนาด** (ไม่ใช่ cold-start-specific) · validation-internal shift ~0
- holdout [106-110] แค่บังเอิญมีประชากรแบบ s45 ที่ดัน size-50 macro ทะลุ
- → maturity-tier (แก้เฉพาะ size เล็ก) **ไม่ช่วย** เพราะ s45 แย่ทุกขนาด → ต้อง global

## 3. Root cause — login_velocity rule (L1) ยิง normal ของ s45

s45 normal ที่ถูก challenge (454 ตัว): **375 (83%) มาจาก `rule:login_velocity (+0.25)`**

- ไม่ใช่ behavior warm-up — เป็น **L1 rule** ที่ flag velocity สูงของ s45 ว่าเสี่ยง
  ทั้งที่เป็น pattern ปกติของเขา (rule ไม่ personalize velocity ต่อผู้ใช้)
- **ทางแก้ตรงต้นเหตุ:** personalize login_velocity → แก้ s45 false positive โดยไม่เสีย
  velocity detection · แต่เป็นการแก้ **L1 scoring** (scope ใหญ่ ต้อง re-validate ทุก config
  เหมือน Round 3) · **Round 2c เลือกแก้แบบ threshold ก่อน** (อยู่ใน scope)

## 4. เลือก challenge ด้วยเกณฑ์ worst-seed per-size (validation)

worst-seed = max challenge FPR ข้าม **ทุก seed × size**:

| challenge | worst-seed chFPR | ที่ | recall@challenge | ผ่าน ≤1% |
|---|---|---|---|---|
| 0.9898 (R2b) | 1.67% | s45·n50 | 0.7252 | ✗ |
| 0.992 | 1.02% | s44·n500 | 0.6969 | ✗ |
| 0.993 | 0.73% | s46·n50 | 0.6938 | ✓ |
| **0.995** | **0.73%** | s46·n50 | **0.6938** | ✓ (margin 0.27pp) |
| 0.996 | 0.63% | s46·n1000 | 0.6916 | ✓ |

- ขั้นต่ำที่ผ่าน = 0.993 · เลือก **0.995** (recall@ch เท่า 0.993 แต่ absolute threshold
  สูงกว่า → headroom ต่อประชากร holdout ใหม่มากกว่า)
- ยืนยัน per-size ทุกขนาดที่ challenge=0.995: worst-seed warn/challenge/block ≤ งบ ทุก size

## 5. ต้นทุน — enforcement recall (ต่างจาก warn/block)

- **recall@challenge 0.7252 → 0.6938 (−3.1pp)** = attack ที่เคย step-up จะเหลือแค่ warn
- recall แบบ warn+ **ไม่กระทบ** (challenge→warn ยัง surface) — ต่างจาก warn (soft) และ
  block (ฟรี) · challenge ผูกกับ enforcement จึงเป็นต้นทุน security จริง

family ที่เสีย step-up มากที่สุด (challenge 0.9898 → 0.995):

| family | Δ recall@challenge |
|---|---|
| new_passkey | −0.14 |
| subtle_slow_burst | −0.14 |
| login_velocity | −0.12 |
| subtle_rare_device | −0.10 |

ที่เสียคือ attack จับยากอยู่แล้ว (subtle/velocity/passkey) · attack ชัด (combined_ato,
failed_spike ฯลฯ) ยัง step-up 100% ไม่กระทบ · **ข้อสังเกต:** ยก challenge เสีย step-up
ของ login_velocity attack (−0.12) ทั้งที่ต้นเหตุคือ login_velocity rule ยิง false positive
— แก้ปลายเหตุทำให้ detection ของ signal เดียวกันแย่ลง (root-cause fix จะไม่มีปัญหานี้)

## 6. candidate ที่จะ freeze

```
Config B · gamma=1.0 · warn=0.98 · challenge=0.995 · block=0.9999
holdout_seeds: [111, 112, 113, 114, 115]
fallback: current production / L3 shadow
```

**คาดการณ์ holdout [111-115]** (คาดจากโครงสร้าง ไม่ใช่ผลจริง): challenge FPR ทุกขนาด
น่าจะ ≤ 1% (worst-seed validation 0.73% + margin) · recall@challenge ~0.69 ·
**success ไม่การันตี** — ประชากรใหม่อาจมี s45-like มากกว่า validation
