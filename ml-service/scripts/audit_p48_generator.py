"""ขั้นที่ 5 — ตรวจ shortcut / leakage ของ generator บนประชากร P48.

**เปิดเฉพาะ P48-validation (32 โปรไฟล์) และเฉพาะ split `tune`**
โปรไฟล์ holdout ทั้ง 16 คนและ split `test` ไม่ถูกอ่านค่าใด ๆ ในสคริปต์นี้

ทำไมต้องตรวจก่อนวัดผล: ถ้า generator รั่ว (มีฟีเจอร์เดียวที่แยก attack/normal ได้
เกือบสมบูรณ์) ตัวเลข recall ที่ได้จะเป็นการเรียนทางลัด ไม่ใช่ความสามารถจริง
เคยเกิดมาแล้วกับ `success_10m` ที่ทำให้ recall พุ่งไป 90.9%

เกณฑ์ที่ใช้ (เหมือนรอบก่อนทุกประการ เพื่อให้เทียบกันได้):
  * separation AUC > 0.99  (Mann-Whitney แบบ mid-rank จัดการค่าเสมอ)
  * coverage < 0.05        (ช่วงค่าของ attack แทบไม่ทับกับ normal)

    python audit_p48_generator.py --seeds 301 302 303
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ML = Path(__file__).resolve().parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

import build_profiles_v2 as BP  # noqa: E402
import gen_v3 as G3  # noqa: E402
import population_p48 as P48  # noqa: E402
import population_p48_t2 as P48T2  # noqa: E402
from hybrid_experiment import audit as AU  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402

try:
    import features_v2 as FE  # noqa: E402

    FEATURES = FE.FEATURES
except Exception:  # noqa: BLE001
    import lc_run_4layer as LC  # noqa: E402

    FEATURES = LC.FEATURES

SEEDS_P48 = [301, 302, 303, 304, 305]
SIZES = [50, 100, 500, 1000, 5000]


def run(args) -> int:
    pop_mod = P48T2 if args.population == "p48t2" else P48
    roster_path = BP.DATA / (
        "roster_p48_t2.json" if args.population == "p48t2" else "roster_p48.json"
    )
    if not roster_path.exists():
        print(f"ยังไม่มี {roster_path} — รัน population_p48.py ก่อน")
        return 1
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    pop = pop_mod.generate_population()
    val_profiles, hold_profiles = pop_mod.split_population(pop)
    held_aliases = {p["alias"] for p in hold_profiles}

    print(
        f"AUDIT P48 — validation {len(val_profiles)} โปรไฟล์ x {len(args.seeds)} seeds"
    )
    print(f"  โปรไฟล์ holdout {len(held_aliases)} คนไม่ถูกแตะในสคริปต์นี้\n")

    runs: list[dict] = []
    leak_total = {"overlapping_rows": 0, "holdout_rows": 0}
    for seed in args.seeds:
        t0 = time.perf_counter()
        raw = G3.build_seed(args.users, seed, spec=val_profiles, roster=roster)
        assert not (set(raw) & held_aliases), "หลุดไปสร้างโปรไฟล์ holdout — หยุดทันที"

        for size in args.sizes:
            splits = DS.build(args.users, seed, size, raw=raw)
            leak = DS.check_leakage(splits)
            leak_total["overlapping_rows"] += leak["overlapping_rows"]
            leak_total["holdout_rows"] += leak["holdout_rows"]

            # ใช้ **validation-tuning** เท่านั้น — ไม่แตะ u.holdout_* ในการตรวจ shortcut
            atk = [v for u in splits.values() for _, v in u.tune_attacks]
            nor = [v for u in splits.values() for v in u.tune_normal_ft]
            rows = AU.feature_report(atk, nor, FEATURES)
            for r in rows:
                r["_seed"], r["_size"], r["_split"] = seed, size, "validation_tuning"
            runs.append(
                {
                    "seed": seed,
                    "size": size,
                    "split": "validation_tuning",
                    "n_attack": len(atk),
                    "n_normal": len(nor),
                    "features": rows,
                }
            )
        print(f"  seed {seed} -> {time.perf_counter() - t0:.0f}s", flush=True)

    summary = AU.summarize_audit(runs)
    summary["splits_audited"] = ["validation_tuning"]
    summary["leakage"] = {**leak_total, "clean": leak_total["overlapping_rows"] == 0}
    summary["population"] = {
        "population": args.population,
        "pop_seed": pop_mod.POP_SEED,
        "validation_profiles": [p["alias"] for p in val_profiles],
        "holdout_profiles_untouched": sorted(held_aliases),
    }
    summary["conclusion"] = (
        "ไม่พบ single-feature shortcut บน P48-validation ตามเกณฑ์ที่กำหนด"
        if summary["n_flagged_features"] == 0
        else (
            f"พบ {summary['n_flagged_features']} ฟีเจอร์ที่เข้าเกณฑ์ "
            "— ต้องแก้ generator ก่อนวัดผลใด ๆ"
        )
    )

    out = args.out
    out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nleakage: {summary['leakage']}")
    print(f"shortcut: {summary['conclusion']}")
    for f in summary.get("flagged", [])[:10]:
        print(f"  - {f}")
    print(f"\nเขียนผลลง {out}")
    return (
        0 if summary["n_flagged_features"] == 0 and summary["leakage"]["clean"] else 2
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=SEEDS_P48)
    ap.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument("--population", choices=("p48", "p48t2"), default="p48")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    if a.out is None:
        a.out = BP.DATA / "hybrid_experiment" / f"audit_{a.population}.json"
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
