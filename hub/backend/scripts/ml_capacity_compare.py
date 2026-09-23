"""เทียบสองฝั่งของ ML Capacity Gate ตามวิธีวัด v2 (กฎกำหนดก่อนวัด — รายงาน §13).

    python -m scripts.ml_capacity_compare <โฟลเดอร์ฝั่ง A> <โฟลเดอร์ฝั่ง B> [--out file.json]

แต่ละโฟลเดอร์มีโฟลเดอร์ย่อยต่อครั้ง ภายในมี `workers_4.json` จาก `ml_capacity_gate`

กฎ:
  - ฝั่งผ่าน = P1 v2 ผ่าน (median ของ p95 รวมต่อครั้ง <= 225 ms และ >= 90% ของครั้ง
    <= 250 ms ทุกระดับ concurrency) และ P2–P4 ผ่านทุกครั้ง
  - ผลต่างระหว่างฝั่ง: permutation test แบบ exact สองทางบน p95 รวมต่อครั้ง · ระดับหลัก c=20
    (p < 0.05) · ระดับอื่นเป็นข้อมูลสำรวจ (ไม่ได้ปรับ multiple comparison)
  - ขนาดผล: median(A) − median(B) พร้อม bootstrap 95% CI (10,000 รอบ, seed คงที่)
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

from scripts.ml_capacity_gate import CONCURRENCY, p1_v2_pass, permutation_p_value

PRIMARY_LEVEL = "20"
ALPHA = 0.05
BOOTSTRAP_ROUNDS = 10_000
OTHER_CHECKS = ("P2_fit_storm", "P3_score_agreement", "P4_memory")


def median(values) -> float:
    return float(statistics.median(values))


def bootstrap_median_diff_ci(
    a, b, seed: int = 20260922, rounds: int = BOOTSTRAP_ROUNDS
):
    rng = random.Random(seed)
    diffs = []
    for _ in range(rounds):
        ra = [rng.choice(a) for _ in a]
        rb = [rng.choice(b) for _ in b]
        diffs.append(median(ra) - median(rb))
    diffs.sort()
    return diffs[int(0.025 * rounds)], diffs[int(0.975 * rounds) - 1]


def _load(arm_dir: Path) -> list[dict]:
    runs = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(Path(arm_dir).glob("*/workers_4.json"))
    ]
    if not runs:
        raise ValueError(f"ไม่พบผลใน {arm_dir}")
    return runs


def _arm_summary(runs: list[dict]) -> dict:
    per_level = {}
    for lvl in (str(c) for c in CONCURRENCY):
        vals = [r["pooled"][lvl]["p95_ms"] for r in runs if lvl in r.get("pooled", {})]
        if vals:
            per_level[lvl] = vals
    p1 = bool(per_level) and all(p1_v2_pass(v) for v in per_level.values())
    others = all(r["checks"][k]["pass"] for r in runs for k in OTHER_CHECKS)
    return {
        "runs": len(runs),
        "per_run_p95": per_level,
        "median_p95": {k: median(v) for k, v in per_level.items()},
        "p1_v2_pass": p1,
        "p2_to_p4_all_runs": others,
        "passed": p1 and others,
        "high_score_share": runs[0].get("high_score_share"),
    }


def compare(dir_a, dir_b) -> dict:
    ra, rb = _load(Path(dir_a)), _load(Path(dir_b))
    shares = {r.get("high_score_share") for r in ra + rb}
    if len(shares) != 1:
        raise ValueError(
            f"high_score_share ไม่เท่ากันระหว่างฝั่ง: {sorted(map(str, shares))}"
        )
    arms = {"A": _arm_summary(ra), "B": _arm_summary(rb)}
    effect = {}
    for lvl in arms["A"]["per_run_p95"]:
        a = arms["A"]["per_run_p95"][lvl]
        b = arms["B"]["per_run_p95"].get(lvl)
        if not b:
            continue
        lo, hi = bootstrap_median_diff_ci(a, b)
        p = permutation_p_value(a, b)
        effect[lvl] = {
            "median_diff_ms": median(a) - median(b),
            "ci95_ms": [lo, hi],
            "p_value": p,
            "primary": lvl == PRIMARY_LEVEL,
            "significant": p < ALPHA if lvl == PRIMARY_LEVEL else None,
        }
    return {
        "arms": arms,
        "effect": effect,
        "alpha": ALPHA,
        "primary_level": PRIMARY_LEVEL,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm_a")
    ap.add_argument("arm_b")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = compare(a.arm_a, a.arm_b)
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
