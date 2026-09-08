"""ขั้นที่ 6–7 — วัด Config B และ baseline บน **P48-validation เท่านั้น**.

โปรไฟล์ holdout ทั้ง 16 คนและ split `test` ไม่ถูกอ่านในสคริปต์นี้เลย
(มี assert กันไว้ และเขียน `holdout_opened: false` ลง artifact)

**เกณฑ์ที่ต้องรายงาน** (pre-registration §4 — ทุกค่าแยกตามขนาดประวัติ):

  1. mean user FPR ระดับประชากร
  2. median และ p90 ของ per-user FPR
  3. cluster-aware CI ของ mean
  4. จำนวนผู้ใช้ที่เกินงบ + รายชื่อเป็น outlier report แยก
  5. Recall@challenge แยก attack family
  6. การกระจายของ per-user FPR (min / q25 / median / q75 / p90 / max)

**`max user FPR <= 1%` ไม่ใช่ gate** — เป็น order statistic ที่โตตามจำนวนผู้ใช้
ทำให้เกณฑ์เข้มขึ้นเองเมื่อขยายประชากร · ใช้ mean + CI และ p90 เป็นเกณฑ์แทน
และรายงาน outlier แยกต่างหาก

    python exp_p48_validation.py --seeds 301 302 303 304 305
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ML = Path(__file__).resolve().parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))
REPO = ML.parent.parent
if str(REPO / "hub" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "hub" / "backend"))

import build_profiles_v2 as BP  # noqa: E402
import exp_hybrid_gate as X  # noqa: E402
import gen_v3 as G3  # noqa: E402
import population_p48 as P48  # noqa: E402
from hybrid_experiment import bootstrap as BS  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402
from hybrid_experiment import metrics as M  # noqa: E402
from hybrid_experiment import tune as TU  # noqa: E402

SEEDS_P48 = [301, 302, 303, 304, 305]
SIZES = [50, 100, 500, 1000, 5000]
BUDGETS = {"warn": 0.05, "challenge": 0.01, "block": 0.002}

# baseline = สถาปัตยกรรมเดิมก่อน hybrid (Config A) · candidate = Config B
BASELINE = "A"
CANDIDATE = "B"


def _q(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(p * len(s)))]


def per_user_fpr(rows, level: str = "challenge") -> dict[str, float]:
    """FPR ของผู้ใช้แต่ละคน — หน่วยทดลองจริงคือผู้ใช้ ไม่ใช่เหตุการณ์."""
    want = (
        M.CHALLENGED
        if level == "challenge"
        else (M.BLOCKED if level == "block" else {"warn"})
    )
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if r.is_attack:
            continue
        a = agg[r.user]
        a[0] += 1
        a[1] += r.decision.removeprefix("would_") in want
    return {u: k / n for u, (n, k) in agg.items() if n}


def distribution(vals: list[float]) -> dict:
    return {
        "n_users": len(vals),
        "mean": round(sum(vals) / len(vals), 6) if vals else 0.0,
        "min": round(min(vals), 6) if vals else 0.0,
        "q25": round(_q(vals, 0.25), 6),
        "median": round(_q(vals, 0.50), 6),
        "q75": round(_q(vals, 0.75), 6),
        "p90": round(_q(vals, 0.90), 6),
        "max": round(max(vals), 6) if vals else 0.0,
    }


def family_recall(rows) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        if not r.is_attack:
            continue
        d = out.setdefault(r.family or "unknown", {"n": 0, "ch": 0, "sf": 0})
        d["n"] += 1
        d["ch"] += r.decision.removeprefix("would_") in M.CHALLENGED
        d["sf"] += r.is_surfaced
    return {
        k: {
            "n": v["n"],
            "recall_challenge": round(v["ch"] / v["n"], 6),
            "recall_surfaced": round(v["sf"] / v["n"], 6),
        }
        for k, v in sorted(out.items())
    }


def size_report(
    rows_by_size: dict, cells_by_size: dict, level: str = "challenge"
) -> dict:
    """รายงานครบทุกเกณฑ์ §4 ต่อขนาดประวัติหนึ่งค่า."""
    out = {}
    for size, rows in sorted(rows_by_size.items()):
        pu = per_user_fpr(rows, level)
        over = {u: round(v, 6) for u, v in pu.items() if v > BUDGETS[level]}
        tree: dict[str, dict] = defaultdict(dict)
        for c in cells_by_size[size]:
            for u, cnt in (c.per_user_normal_counts or {}).items():
                tree[u][c.seed] = {"k": int(cnt[level]), "n": int(cnt["n"])}
        ci = BS.cluster_rate_ci(dict(tree), n_boot=2000, seed=17)
        out[str(size)] = {
            "user_fpr": distribution(list(pu.values())),
            "cluster_ci": {
                "point": ci["point"],
                "ci_low": ci["ci_low"],
                "ci_high": ci["ci_high"],
                "n_users": ci["n_users"],
                "n_events": ci["n_events"],
                "method": ci["upper_bound_method"],
            },
            "verdict": BS.rate_verdict(ci, BUDGETS[level]),
            "users_over_budget": {
                "budget": BUDGETS[level],
                "count": len(over),
                "share_of_users": round(len(over) / max(1, len(pu)), 4),
                # outlier report แยก — ไม่ใช้เป็นเกณฑ์ตัดสิน แต่ต้องเห็น
                "users": dict(sorted(over.items(), key=lambda kv: -kv[1])),
            },
            "family_recall": family_recall(rows),
        }
    return out


def run(args) -> int:
    roster_path = BP.DATA / "roster_p48.json"
    if not roster_path.exists():
        print(f"ยังไม่มี {roster_path} — รัน population_p48.py ก่อน")
        return 1
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    pop = P48.generate_population()
    val_profiles, hold_profiles = P48.split_population(pop)
    held = {p["alias"] for p in hold_profiles}

    if args.population == "l12":
        # stratum อ้างอิงตาม pre-registration §2 — วัดด้วยโค้ดชุดเดียวกันเป๊ะ
        # เพื่อให้เทียบกับ P48 ได้โดยไม่มีตัวแปรกวนจากวิธีวัด
        val_profiles = BP.SPEC
        roster = json.loads((BP.DATA / "roster_v2.json").read_text(encoding="utf-8"))
        held = set()

    fz = json.loads((X.ARTIFACTS / "frozen_config.json").read_text(encoding="utf-8"))
    gamma_map = fz["per_config_gamma"]
    thr_map = fz["per_config_thresholds"]
    keys = [BASELINE, CANDIDATE]

    print(
        f"P48 VALIDATION — {len(val_profiles)} โปรไฟล์ x {len(args.seeds)} seeds "
        f"x {len(args.sizes)} sizes · split=tune"
    )
    print(f"  holdout {len(held)} โปรไฟล์ไม่ถูกแตะ · config {keys}\n")

    rows_by: dict = {k: defaultdict(list) for k in keys}
    cells_by: dict = {k: defaultdict(list) for k in keys}

    for seed in args.seeds:
        raw = G3.build_seed(args.users, seed, spec=val_profiles, roster=roster)
        assert not (set(raw) & held), "หลุดไปสร้างโปรไฟล์ holdout — หยุดทันที"
        for size in args.sizes:
            t0 = time.perf_counter()
            splits = DS.build(args.users, seed, size, raw=raw)
            point_model, seq_models, ecdf = X.fit_all(splits, size, raw)
            ctxs = X.compute_layer_outputs(splits, point_model, seq_models, "tune")
            for k in keys:
                thr = thr_map[k]
                use_thr = X.PROBE_THR if thr in ("legacy_internal", None) else thr
                rows = X.apply_config(
                    ctxs, CFG.CONFIGS[k], ecdf, gamma_map.get(k) or 0.0, use_thr
                )
                rows_by[k][size].extend(rows)
                cells_by[k][size].append(TU.cell_stat(seed, size, rows))
            print(
                f"  seed {seed} size {size:>5} -> {time.perf_counter() - t0:.0f}s",
                flush=True,
            )

    results = {}
    for k in keys:
        results[k] = {
            "name": CFG.CONFIGS[k].name,
            "gamma": gamma_map.get(k),
            "thresholds": thr_map[k],
            "challenge": size_report(rows_by[k], cells_by[k], "challenge"),
            "block": size_report(rows_by[k], cells_by[k], "block"),
            "warn": size_report(rows_by[k], cells_by[k], "warn"),
        }

    out = args.out
    out.write_text(
        json.dumps(
            {
                "split": f"{args.population}_validation_tuning",
                "population": args.population,
                "holdout_opened": False,
                "holdout_profiles_untouched": sorted(held),
                "pop_seed": P48.POP_SEED,
                "seeds": args.seeds,
                "sizes": args.sizes,
                "budgets": BUDGETS,
                "baseline": BASELINE,
                "candidate": CANDIDATE,
                "gate_note": (
                    "max user FPR ไม่ใช่เกณฑ์ตัดสิน — เป็น order statistic ที่โต"
                    "ตามจำนวนผู้ใช้ · ใช้ mean + cluster CI และ p90 แทน"
                ),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _print(results, args.sizes)
    print(f"\nเขียนผลลง {out}")
    return 0


def _print(results: dict, sizes: list[int]) -> None:
    print(f"\n{'challenge FPR ระดับผู้ใช้ (mean [CI] · median · p90 · เกินงบ)':<70}")
    for k, r in results.items():
        print(f"\nConfig {k} — {r['name'][:40]}")
        print(
            f"  {'size':>6} {'mean':>8} {'CI':>18} {'median':>8} {'p90':>8} "
            f"{'เกินงบ':>8} {'verdict':>14}"
        )
        for s in sizes:
            c = r["challenge"][str(s)]
            d, ci, ov = c["user_fpr"], c["cluster_ci"], c["users_over_budget"]
            print(
                f"  {s:>6} {d['mean'] * 100:7.3f}% "
                f"[{ci['ci_low'] * 100:6.3f},{ci['ci_high'] * 100:6.3f}] "
                f"{d['median'] * 100:7.3f}% {d['p90'] * 100:7.3f}% "
                f"{ov['count']:>4}/{d['n_users']:<3} {c['verdict']['verdict']:>14}"
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=SEEDS_P48)
    ap.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    ap.add_argument("--users", type=Path, default=BP.DEFAULT_USERS_XLSX)
    ap.add_argument(
        "--population",
        choices=("p48", "l12"),
        default="p48",
        help="l12 = stratum อ้างอิง 12 โปรไฟล์เดิม (pre-registration §2)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=BP.DATA / "hybrid_experiment" / "p48_validation.json",
    )
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
