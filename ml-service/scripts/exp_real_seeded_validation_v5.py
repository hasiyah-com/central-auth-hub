"""V5 isolated pilot: canonical synthetic device signatures, no holdout."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "hub" / "backend"))
sys.path.insert(1, str(HERE))
sys.path.insert(2, str(HERE.parent))

import ablate_v4_behavior as A
import exp_hybrid_gate as X
import exp_real_seeded_validation as V1
import exp_real_seeded_validation_v2 as V2
import exp_real_seeded_validation_v4 as V4
import gen_v5_signature as G5
from app.security.risk_fusion import DEFAULT_GAMMA
from hybrid_experiment import configs as CFG
from hybrid_experiment import tune as TU

SEEDS = (741, 742, 743)
SIZES = (100, 2000)


def run(args) -> dict:
    artifact = args.artifact_dir
    profiles = json.loads((artifact / "population_spec.json").read_text())
    meta = json.loads((artifact / "population_summary.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v5.json").read_text())
    val, hold = set(meta["split"]["validation"]), set(meta["split"]["holdout"])
    if len(val) != 32 or len(hold) != 16 or val & hold:
        raise ValueError("V5 validation/holdout split invalid")
    raw_by_seed = {}
    for seed in args.seeds:
        raw = G5.build_seed(
            artifact / "synthetic_users.xlsx", seed,
            [p for p in profiles if p["alias"] in val],
            {alias: roster[alias] for alias in val},
        )
        V1._trim_dev_attacks(raw)
        assert V1._feature_contract(raw)["passed"]
        assert sum(len(u["dev_attacks"]) for u in raw.values()) / (
            sum(505 + len(u["dev_attacks"]) for u in raw.values())
        ) <= 0.07
        for user in raw.values():
            rows = (user["train_raw"] + [r for r, _ in user["test"]]
                    + [r for r, _ in user["dev_attacks"]]
                    + [r for r, _ in user["camp_like"]])
            assert all(
                row["device_signature"] == G5._device_signature(row["user_agent"])
                for row in rows
            )
        raw_by_seed[seed] = raw

    records, tuning = {}, {}
    for group, names in A.GROUPS.items():
        records[group], tuning[group] = {}, {}
        for seed in args.seeds:
            for size in args.sizes:
                started = time.perf_counter()
                cal, tune, ecdf = V4._fit_contexts(raw_by_seed[seed], size, names)
                records[group][(seed, size)] = X.build_records(
                    cal, ecdf, CFG.CONFIGS["E"], DEFAULT_GAMMA
                )
                tuning[group][(seed, size)] = (tune, ecdf)
                print(f"calculated {group} {seed}:{size} "
                      f"seconds={time.perf_counter()-started:.1f}", flush=True)
    thresholds, details = {}, {}
    for group in A.GROUPS:
        thresholds[group], details[group] = V2.calibrate_thresholds(records[group])
        print(f"calibrated {group}: {thresholds[group]}", flush=True)
    frozen = {
        "status": "v5_pilot_holdout_closed",
        "thresholds": thresholds,
        "targets": V2.CAL_TARGETS,
        "sizes": list(args.sizes), "seeds": list(args.seeds),
        "generator_sha256": V2._sha256(Path(G5.__file__)),
        "population_sha256": V2._sha256(artifact / "population_spec.json"),
        "harness_sha256": V2._sha256(Path(__file__)),
    }
    args.frozen.parent.mkdir(parents=True, exist_ok=True)
    args.frozen.write_text(json.dumps(frozen, indent=2) + "\n")
    print("V5 THRESHOLDS FROZEN BEFORE TUNING", flush=True)
    result = {
        "status": "v5_offline_pilot_no_service_parity",
        "holdout_opened": False,
        "production_changed": False,
        "thresholds": thresholds,
        "calibration": details,
        "results": {},
    }
    for group in A.GROUPS:
        result["results"][group] = {}
        if thresholds[group] is None:
            continue
        for size in args.sizes:
            rows_by, stats, attribution = {}, [], Counter()
            for seed in args.seeds:
                contexts, ecdf = tuning[group][(seed, size)]
                rows = X.apply_config(
                    contexts, CFG.CONFIGS["E"], ecdf,
                    DEFAULT_GAMMA, thresholds[group],
                )
                rows_by[seed] = rows
                stats.append(TU.cell_stat(seed, size, rows))
                for ctx, outcome in zip(contexts, rows):
                    action = outcome.decision.removeprefix("would_")
                    if ctx.is_attack and ctx.family == "subtle_rare_device":
                        attribution["rare_total"] += 1
                        attribution[f"rare_{action}"] += 1
                        if any("signature_rarity" in x for x in ctx.behavior.reasons):
                            attribution["rare_signature_rarity_present"] += 1
                    if not ctx.is_attack and action == "block":
                        attribution["normal_block"] += 1
                        if ctx.family == "campaign_like_normal":
                            attribution["normal_campaign_like_block"] += 1
                        if ctx.policy.denied:
                            attribution["normal_policy_denied_block"] += 1
            report = V1._history_report(rows_by, stats, ci_seed=59000 + size)
            summary = report["summary"]
            result["results"][group][str(size)] = {
                "recall": summary["recall"], "precision": summary["precision"],
                "warn_fpr": summary["warn_fpr"],
                "challenge_fpr": summary["challenge_fpr"],
                "block_fpr": summary["block_fpr"],
                "family_recall": {
                    key: value["recall"] for key, value in report["family_recall"].items()
                },
                "cluster_fpr_passed": report["cluster_fpr_passed"],
                "all_seeds_passed": report["all_seeds_passed"],
                "pilot_quality_passed": report["history_gate_passed"],
                "service_parity_passed": False,
                "attribution": dict(attribution),
            }
            print(f"tuning {group} size={size}", flush=True)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "holdout_opened": False}))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    args = parser.parse_args()
    if not set(args.seeds) <= set(SEEDS) or not set(args.sizes) <= set(SIZES):
        raise ValueError("V5 pilot must use frozen seeds/sizes")
    run(args)


if __name__ == "__main__":
    main()
