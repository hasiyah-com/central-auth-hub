"""V2 validation: calibrate global thresholds on normal-only, freeze, then tune.

Protocol: ``docs/design/REAL_SEEDED_POPULATION_V2_PREREG.md``. Holdout profiles
are filtered before generation and are never evaluated by this script.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import time

ML = Path(__file__).resolve().parent
REPO = ML.parent.parent
for path in (ML, ML.parent, REPO / "hub" / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import exp_hybrid_gate as X  # noqa: E402
import exp_real_seeded_validation as V1E  # noqa: E402
import gen_v3 as G3  # noqa: E402
from app.security.risk_fusion import DEFAULT_GAMMA  # noqa: E402
from hybrid_experiment import configs as CFG  # noqa: E402
from hybrid_experiment import dataset as DS  # noqa: E402
from hybrid_experiment import tune as TU  # noqa: E402

SEEDS = [711, 712, 713]
SIZES = [5, 10, 20, 50, 100, 200, 500, 1000, 2000]
CONFIGS = ("B", "E")
CAL_TARGETS = {"warn": 0.025, "challenge": 0.005, "block": 0.001}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_thresholds(records_by_cell: dict) -> list[float]:
    """คะแนน fusion มี precision 6 ตำแหน่ง; +1e-6 คือขอบถัดจากค่า `>=`."""
    values = {0.0, 1.0}
    for records in records_by_cell.values():
        for record in records:
            resolver = record.resolver
            if resolver is None:
                continue
            numbers = (resolver.final_score, *resolver.other_evidence)
            for value in numbers:
                values.add(float(value))
                if value < 1.0:
                    values.add(min(1.0, round(float(value) + 0.000001, 6)))
    return sorted(values)


def _cell_rates(records_by_cell: dict, thresholds: dict) -> dict:
    out = {}
    for (seed, size), records in records_by_cell.items():
        stat = TU.stat_direct(records, seed, size, thresholds)
        out[f"{seed}:{size}"] = {
            "warn": stat.pooled["warn_fpr"],
            "challenge": stat.pooled["challenge_fpr"],
            "block": stat.pooled["block_fpr"],
        }
    return out


def _max_rate(rates: dict, level: str) -> float:
    return max((cell[level] for cell in rates.values()), default=0.0)


def _first_feasible(
    records_by_cell: dict,
    candidates: list[float],
    level: str,
    target: float,
    base_thresholds: dict,
    upper: float | None = None,
) -> tuple[float | None, dict | None]:
    eligible = [x for x in candidates if x > 0.0 and (upper is None or x < upper)]
    lo, hi = 0, len(eligible) - 1
    answer = None
    answer_rates = None
    while lo <= hi:
        mid = (lo + hi) // 2
        thresholds = {**base_thresholds, level: eligible[mid]}
        rates = _cell_rates(records_by_cell, thresholds)
        if _max_rate(rates, level) <= target:
            answer, answer_rates = eligible[mid], rates
            hi = mid - 1
        else:
            lo = mid + 1
    return answer, answer_rates


def calibrate_thresholds(records_by_cell: dict) -> tuple[dict | None, dict]:
    """เลือก block -> challenge -> warn โดยเรียก production resolver ทุกจุด."""
    candidates = _candidate_thresholds(records_by_cell)
    block, _ = _first_feasible(
        records_by_cell,
        candidates,
        "block",
        CAL_TARGETS["block"],
        {"warn": 0.0, "challenge": 0.0, "block": 1.0},
    )
    if block is None:
        return None, {"reason": "block_target_infeasible"}
    challenge, _ = _first_feasible(
        records_by_cell,
        candidates,
        "challenge",
        CAL_TARGETS["challenge"],
        {"warn": 0.0, "challenge": block / 2, "block": block},
        upper=block,
    )
    if challenge is None:
        return None, {"reason": "challenge_target_infeasible", "block": block}
    warn, _ = _first_feasible(
        records_by_cell,
        candidates,
        "warn",
        CAL_TARGETS["warn"],
        {"warn": challenge / 2, "challenge": challenge, "block": block},
        upper=challenge,
    )
    if warn is None:
        return None, {
            "reason": "warn_target_infeasible",
            "challenge": challenge,
            "block": block,
        }
    thresholds = {"warn": warn, "challenge": challenge, "block": block}
    rates = _cell_rates(records_by_cell, thresholds)
    maxima = {level: _max_rate(rates, level) for level in CAL_TARGETS}
    feasible = (
        0.0 <= warn < challenge < block <= 1.0
        and all(maxima[level] <= target for level, target in CAL_TARGETS.items())
    )
    return (thresholds if feasible else None), {
        "reason": None if feasible else "final_revalidation_failed",
        "targets": CAL_TARGETS,
        "max_point_rates": maxima,
        "cell_rates": rates,
        "candidate_count": len(candidates),
    }


def _markdown(result: dict) -> str:
    lines = [
        "# Real-seeded login-risk validation V2",
        "",
        f"สถานะรวม: **{result['status']}**",
        "",
        "Threshold ถูกเลือกจาก Calibration normal-only และ freeze ก่อนประเมิน Tuning; holdout profiles ยังปิดอยู่",
        "",
    ]
    thresholds = result.get("thresholds")
    if thresholds:
        lines += [
            f"Threshold: warn `{thresholds['warn']:.6f}`, challenge `{thresholds['challenge']:.6f}`, block `{thresholds['block']:.6f}`",
            "",
            "| History | Recall | Precision | Warn FPR | Challenge FPR | Block FPR | Gate |",
            "|---:|---:|---:|---:|---:|---:|:---:|",
        ]
        for size in result["sizes"]:
            row = result["results"]["E"][str(size)]
            summary = row["summary"]
            lines.append(
                f"| {size:,} | {summary['recall']:.3f} | {summary['precision']:.3f} | "
                f"{summary['warn_fpr']:.3%} | {summary['challenge_fpr']:.3%} | "
                f"{summary['block_fpr']:.3%} | "
                f"{'ผ่าน' if row['history_gate_passed'] else 'ไม่ผ่าน'} |"
            )
        sufficient = result["minimum_sufficient_history"]
        lines += [
            "",
            (
                f"จำนวนประวัติต่ำสุดที่ผ่านทุก gate ครบสาม seed คือ **{sufficient:,} ครั้ง**"
                if sufficient
                else "ไม่พบจำนวนประวัติที่ผ่านทุก gate ในช่วง 5–2,000 ครั้ง"
            ),
        ]
    else:
        lines.append(
            f"Calibration infeasible: `{result['calibration']['reason']}`; ไม่ได้เปิด Tuning"
        )
    lines += [
        "",
        f"- Feature contract: {'ผ่าน' if result.get('feature_contract_passed') else 'ไม่ผ่าน'}",
        f"- Anomaly ratio สูงสุด: {result.get('max_anomaly_ratio', 0):.3%}",
        f"- Model/service parity max error: {result.get('model_parity_max_abs_error', 0):.3g}",
        "- Holdout profiles: ปิดอยู่",
        "- Production policy/threshold: ยังไม่เปลี่ยน",
        "",
    ]
    return "\n".join(lines)


def run(args) -> int:
    artifact = args.artifact_dir
    profiles = json.loads((artifact / "population_spec.json").read_text(encoding="utf-8"))
    meta = json.loads((artifact / "population_summary.json").read_text(encoding="utf-8"))
    roster = json.loads(
        (artifact / "roster_real_seeded_v2.json").read_text(encoding="utf-8")
    )
    validation = set(meta["split"]["validation"])
    holdout = set(meta["split"]["holdout"])
    val_profiles = [p for p in profiles if p["alias"] in validation]
    assert len(val_profiles) == 32
    assert not ({p["alias"] for p in val_profiles} & holdout)
    roster = {key: value for key, value in roster.items() if key in validation}

    raw_cache = {}
    contracts, ratios = [], []
    for seed in args.seeds:
        raw = G3.build_seed(
            artifact / "synthetic_users.xlsx",
            seed,
            spec=val_profiles,
            roster=roster,
        )
        assert not (set(raw) & holdout), "holdout profile entered validation generator"
        V1E._trim_dev_attacks(raw)
        contract = V1E._feature_contract(raw)
        ratio = V1E._attack_ratio(raw)
        assert contract["passed"], contract
        assert ratio["passed"], ratio
        raw_cache[seed] = raw
        contracts.append(contract)
        ratios.append(ratio)

    records_by_cell = {}
    print("CALIBRATION NORMAL-ONLY", flush=True)
    for seed in args.seeds:
        raw = raw_cache[seed]
        for size in args.sizes:
            started = time.perf_counter()
            splits = DS.build(artifact / "synthetic_users.xlsx", seed, size, raw=raw)
            point, sequence, ecdf = X.fit_all(splits, size, raw)
            contexts = X.compute_layer_outputs(splits, point, sequence, "calib")
            assert all(not context.is_attack for context in contexts)
            records_by_cell[(seed, size)] = X.build_records(
                contexts, ecdf, CFG.CONFIGS["E"], DEFAULT_GAMMA
            )
            print(
                f"cal seed={seed} size={size} n={len(contexts)} "
                f"seconds={time.perf_counter() - started:.1f}",
                flush=True,
            )

    thresholds, calibration = calibrate_thresholds(records_by_cell)
    frozen = {
        "experiment": "real_seeded_population_v2",
        "normal_only": True,
        "candidate_config": "E",
        "gamma": DEFAULT_GAMMA,
        "seeds": args.seeds,
        "sizes": args.sizes,
        "targets": CAL_TARGETS,
        "thresholds": thresholds,
        "calibration": calibration,
        "population_spec_sha256": _sha256(artifact / "population_spec.json"),
        "records": sum(len(value) for value in records_by_cell.values()),
    }
    args.frozen_thresholds.parent.mkdir(parents=True, exist_ok=True)
    args.frozen_thresholds.write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if thresholds is None:
        result = {
            "experiment": "real_seeded_population_v2_validation",
            "status": "calibration_infeasible_tuning_unopened_holdout_closed",
            "holdout_opened": False,
            "thresholds": None,
            "calibration": calibration,
            "feature_contract_passed": all(x["passed"] for x in contracts),
            "max_anomaly_ratio": max(x["anomaly_ratio"] for x in ratios),
            "model_parity_max_abs_error": 0.0,
        }
        args.out_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        args.out_md.write_text(_markdown(result), encoding="utf-8")
        return 2

    del records_by_cell
    gc.collect()
    print(f"FROZEN THRESHOLDS {thresholds}", flush=True)

    rows_by = {cfg: {size: {} for size in args.sizes} for cfg in CONFIGS}
    cells_by = {cfg: {size: [] for size in args.sizes} for cfg in CONFIGS}
    leakage, shortcuts, parity = [], [], []
    print("TUNING VALIDATION", flush=True)
    for seed in args.seeds:
        raw = raw_cache[seed]
        for size in args.sizes:
            started = time.perf_counter()
            splits = DS.build(artifact / "synthetic_users.xlsx", seed, size, raw=raw)
            leak = DS.check_leakage(splits)
            leakage.append({"seed": seed, "size": size, **leak})
            attack = [v for user in splits.values() for _, v in user.tune_attacks]
            normal = [v for user in splits.values() for v in user.tune_normal_ft]
            shortcut = DS.check_shortcut(attack, normal, V1E.FEATURE_NAMES)
            shortcuts.append({"seed": seed, "size": size, "findings": shortcut})
            point, sequence, ecdf = X.fit_all(splits, size, raw)
            parity.append(V1E._model_parity(point, normal, artifact))
            contexts = X.compute_layer_outputs(splits, point, sequence, "tune")
            for config in CONFIGS:
                rows = X.apply_config(
                    contexts,
                    CFG.CONFIGS[config],
                    ecdf,
                    DEFAULT_GAMMA,
                    thresholds,
                )
                rows_by[config][size][seed] = rows
                cells_by[config][size].append(TU.cell_stat(seed, size, rows))
            print(
                f"tune seed={seed} size={size} seconds={time.perf_counter() - started:.1f}",
                flush=True,
            )

    results = {config: {} for config in CONFIGS}
    for config in CONFIGS:
        for size in args.sizes:
            results[config][str(size)] = V1E._history_report(
                rows_by[config][size],
                cells_by[config][size],
                ci_seed=27000 + size,
            )
    sufficient = [
        size for size in args.sizes if results["E"][str(size)]["history_gate_passed"]
    ]
    shortcut_passed = all(not row["findings"] for row in shortcuts)
    parity_error = max(parity, default=0.0)
    global_gates = (
        all(row["passed"] for row in contracts)
        and all(row["clean"] for row in leakage)
        and shortcut_passed
        and parity_error <= 1e-12
    )
    result = {
        "experiment": "real_seeded_population_v2_validation",
        "status": (
            "validation_passed_holdout_closed"
            if sufficient and global_gates
            else "validation_failed_holdout_closed"
        ),
        "holdout_opened": False,
        "validation_profiles": 32,
        "holdout_profiles": 16,
        "seeds": args.seeds,
        "sizes": args.sizes,
        "configs": {key: CFG.CONFIGS[key].name for key in CONFIGS},
        "gamma": DEFAULT_GAMMA,
        "thresholds": thresholds,
        "calibration": calibration,
        "normal_only_train_calibration": True,
        "max_anomaly_ratio": max(x["anomaly_ratio"] for x in ratios),
        "feature_contract_passed": all(x["passed"] for x in contracts),
        "leakage_passed": all(x["clean"] for x in leakage),
        "shortcut_passed": shortcut_passed,
        "shortcut_findings": shortcuts if not shortcut_passed else [],
        "model_parity_max_abs_error": parity_error,
        "model_parity_passed": parity_error <= 1e-12,
        "minimum_sufficient_history": min(sufficient) if sufficient else None,
        "results": results,
        "limitations": [
            "real source contained no confirmed attacks; attack recall is synthetic",
            "threshold calibration used normal data only",
            "validation is not permission to enable production enforcement",
            "expert-labeled shadow traffic and capacity gate remain required",
        ],
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.out_md.write_text(_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "minimum_sufficient_history",
                    "max_anomaly_ratio",
                    "model_parity_max_abs_error",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    parser.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    parser.add_argument("--frozen-thresholds", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
