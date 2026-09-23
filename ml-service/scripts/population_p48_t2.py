"""ประชากร **P48-T2** — รุ่นแก้ไขหลังแก้ความหมายของ `weekend_rate` (B71).

**P48 รุ่นเดิมไม่ถูกแตะ** — `population_p48.py` ยังให้ประชากรเดิมทุกประการ และ
tag `p48-validation-inconclusive` ยังตรวจย้อนได้ · ห้ามนำตัวเลขของสองรุ่นมารวมกัน

## ทำไมต้องมีรุ่นใหม่

`build_profiles_v2.spread_over_days()` เคยใช้ `weekend_rate` เป็น **น้ำหนักต่อวัน**
แทนที่จะเป็น **สัดส่วน** ทำให้สัดส่วนวันหยุดที่ generate ได้จริงต่ำกว่าที่ประกาศ
0.27–0.37 เท่า และมีเพดานที่ 0.267 แม้ตั้งค่าสูงสุด · ผู้ใช้จริงที่วัดได้มีสัดส่วน
0.381 ซึ่งประชากรรุ่นเดิม **สร้างไม่ได้เลย**

การแก้ generator เปลี่ยนพฤติกรรมของทุกโปรไฟล์ → เป็นคนละประชากร ต้องรันรอบใหม่ทั้งชุด

## สิ่งที่เปลี่ยนจาก P48

| รายการ | P48 | P48-T2 |
|---|---|---|
| ความหมาย `weekend_rate` | น้ำหนักต่อวัน (บั๊ก) | **สัดส่วนของ login วันหยุด** |
| `POP_SEED` | 480906 | **490909** |
| คำนำหน้า alias | `P01`–`P48` | **`T01`–`T48`** |
| การแจกแจงฟิลด์อื่น | — | **เหมือนเดิมทุกฟิลด์** |

`POP_SEED` และคำนำหน้าต่างกันโดยตั้งใจ เพื่อให้ไม่มีทางสับสนว่าตัวเลขไหนมาจากรุ่นใด
แม้จะหลุดไปอยู่ในตารางเดียวกันโดยบังเอิญ

## สิ่งที่ยังเหมือนเดิม

การแจกแจงทุกฟิลด์ · การแบ่ง 32/16 · ข้อบังคับโหมดรอง >= 0.03 · `incidents = 0`
(amendment #2) · การใช้เฉพาะบัญชี `@uni.ac.th`

    python population_p48_t2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ML = Path(__file__).resolve().parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

import build_profiles_v2 as BP  # noqa: E402
import population_p48 as P48  # noqa: E402

# ── ค่าที่ประกาศไว้สำหรับรุ่นนี้ ───────────────────────────────────────────────
POP_SEED = 490909
ALIAS_PREFIX = "T"
N_TOTAL = P48.N_TOTAL
N_VALIDATION = P48.N_VALIDATION
N_HOLDOUT = P48.N_HOLDOUT

# seed ของข้อมูล — ชุดใหม่ ไม่ทับกับรอบก่อน
#   [42-46]     Round 1        [101-115]  Round 2/2b/2c
#   [201-205]   จองให้ Round 3  [301-305]  P48
SEEDS_T2 = [401, 402, 403, 404, 405]


def generate_population(pop_seed: int = POP_SEED, n: int = N_TOTAL) -> list[dict]:
    """ประชากร P48-T2 — ใช้การแจกแจงชุดเดียวกับ P48 แต่คนละ seed และคนละคำนำหน้า."""
    return P48.generate_population(pop_seed=pop_seed, n=n, alias_prefix=ALIAS_PREFIX)


def split_population(
    profiles: list[dict], pop_seed: int = POP_SEED
) -> tuple[list[dict], list[dict]]:
    """แบ่ง validation / holdout ด้วย seed ของรุ่นนี้ — ล็อกก่อนวัดผลใด ๆ."""
    import random

    order = list(profiles)
    random.Random(pop_seed).shuffle(order)
    return order[:N_VALIDATION], order[N_VALIDATION:]


build_roster = P48.build_roster
population_summary = P48.population_summary


def weekend_profile(profiles: list[dict]) -> dict:
    """สรุป `weekend_rate` ที่ประกาศไว้ — ใช้เทียบกับค่าที่ generate ได้จริง (B71)."""
    vals = sorted(p["weekend_rate"] for p in profiles)
    return {
        "n": len(vals),
        "n_zero": sum(1 for v in vals if v == 0.0),
        "n_heavy_ge_0.15": sum(1 for v in vals if v >= 0.15),
        "min": round(min(vals), 4),
        "median": round(vals[len(vals) // 2], 4),
        "max": round(max(vals), 4),
    }


def _cli() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="สร้าง roster และสรุปประชากร P48-T2")
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--out", type=Path, default=BP.DATA / "roster_p48_t2.json")
    ap.add_argument("--summary-out", type=Path, default=None)
    a = ap.parse_args()

    pop = generate_population()
    val, hold = split_population(pop)
    roster = build_roster(pop, list(BP.load_identities(a.users)))

    a.out.write_text(
        json.dumps(roster, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"เขียน roster {len(roster)} รายการลง {a.out}")
    print(f"  validation {len(val)}: {' '.join(p['alias'] for p in val)}")
    print(f"  holdout    {len(hold)}: {' '.join(p['alias'] for p in hold)}")

    summary = {
        "population": "P48-T2",
        "pop_seed": POP_SEED,
        "data_seeds": SEEDS_T2,
        "supersedes": {"population": "P48", "pop_seed": P48.POP_SEED},
        "reason": "แก้ความหมาย weekend_rate จากน้ำหนักเป็นสัดส่วน (B71)",
        "split": {
            "validation": [p["alias"] for p in val],
            "holdout": [p["alias"] for p in hold],
        },
        "declared_weekend_rate": {
            "all": weekend_profile(pop),
            "validation": weekend_profile(val),
        },
        "summary_all": population_summary(pop),
        "summary_validation": population_summary(val),
    }
    if a.summary_out:
        a.summary_out.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"เขียนสรุปประชากรลง {a.summary_out}")
    else:
        print(
            json.dumps(summary["declared_weekend_rate"], ensure_ascii=False, indent=2)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
