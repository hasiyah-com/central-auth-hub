"""V6 isolated pilot of a preregistered L2 raw-score correction."""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import replace
from pathlib import Path

import exp_real_seeded_validation_v5 as V5

SEEDS = (751, 752, 753)
SIZES = (100, 2000)


def adjusted(ctx):
    reasons = ctx.behavior.reasons
    temporal = any(r.startswith("hours_diff=") for r in reasons) and any(
        r.startswith("hour_rarity=") for r in reasons
    )
    rare_device = any(r.startswith("signature_rarity=") for r in reasons)
    delta = (-0.30 if temporal else 0.0) + (0.20 if rare_device else 0.0)
    behavior = replace(
        ctx.behavior,
        score=min(1.0, max(0.0, ctx.behavior.score + delta)),
        reasons=[*reasons, *( ["v6_temporal_dedup"] if temporal else [] ),
                 *( ["v6_signature_bonus"] if rare_device else [] )],
    )
    return replace(ctx, behavior=behavior)


def run(artifact: Path, frozen: Path, result_path: Path) -> dict:
    spec = json.loads((artifact / "population_spec.json").read_text())
    meta = json.loads((artifact / "population_summary.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v6.json").read_text())
    validation, holdout = set(meta["split"]["validation"]), set(meta["split"]["holdout"])
    if len(validation) != 32 or len(holdout) != 16 or validation & holdout:
        raise ValueError("V6 split invalid")
    records = {key: {} for key in ("control", "dedup_rare")}
    tuning = {key: {} for key in records}
    anomaly_rates = {}
    for seed in SEEDS:
        raw = V5.G5.build_seed(
            artifact / "synthetic_users.xlsx", seed,
            [p for p in spec if p["alias"] in validation],
            {alias: roster[alias] for alias in validation},
        )
        V5.V1._trim_dev_attacks(raw)
        if not V5.V1._feature_contract(raw)["passed"]:
            raise ValueError("feature contract invalid")
        anomaly_rates[str(seed)] = sum(len(u["dev_attacks"]) for u in raw.values()) / sum(
            505 + len(u["dev_attacks"]) for u in raw.values()
        )
        if anomaly_rates[str(seed)] > 0.07:
            raise ValueError("anomaly rate above 7 percent")
        for size in SIZES:
            cal, tune, ecdf = V5.V4._fit_contexts(raw, size, V5.A.GROUPS["behavioral"])
            for name, candidate_records in records.items():
                c_cal = cal if name == "control" else [adjusted(ctx) for ctx in cal]
                c_tune = tune if name == "control" else [adjusted(ctx) for ctx in tune]
                c_ecdf = copy.deepcopy(ecdf)
                if name != "control":
                    c_ecdf.fit("behavior", [ctx.behavior.score for ctx in c_cal])
                candidate_records[(seed, size)] = V5.X.build_records(
                    c_cal, c_ecdf, V5.CFG.CONFIGS["E"], V5.DEFAULT_GAMMA
                )
                tuning[name][(seed, size)] = (c_tune, c_ecdf)
            print(f"calculated seed={seed} size={size}", flush=True)
    thresholds, calibration = {}, {}
    for name, candidate_records in records.items():
        thresholds[name], calibration[name] = V5.V2.calibrate_thresholds(candidate_records)
    freeze = {
        "status": "v6_thresholds_frozen_before_tuning",
        "seeds": list(SEEDS), "sizes": list(SIZES), "thresholds": thresholds,
        "population_sha256": V5.V2._sha256(artifact / "population_spec.json"),
        "generator_sha256": V5.V2._sha256(Path(V5.G5.__file__)),
        "harness_sha256": V5.V2._sha256(Path(__file__)),
    }
    frozen.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_text(json.dumps(freeze, indent=2) + "\n")
    print("V6 THRESHOLDS FROZEN BEFORE TUNING", flush=True)
    result = {
        "status": "v6_offline_pilot_no_service_parity", "holdout_opened": False,
        "production_changed": False, "anomaly_rates": anomaly_rates,
        "thresholds": thresholds, "calibration": calibration, "candidates": {},
    }
    for name, threshold in thresholds.items():
        result["candidates"][name] = {}
        if threshold is None:
            continue
        for size in SIZES:
            rows_by, stats = {}, []
            for seed in SEEDS:
                ctx, ecdf = tuning[name][(seed, size)]
                rows = V5.X.apply_config(
                    ctx, V5.CFG.CONFIGS["E"], ecdf, V5.DEFAULT_GAMMA, threshold
                )
                rows_by[seed] = rows
                stats.append(V5.TU.cell_stat(seed, size, rows))
            report = V5.V1._history_report(rows_by, stats, ci_seed=60000 + size)
            report["normal_campaign_like_blocks"] = sum(
                not row.is_attack and row.family == "campaign_like_normal"
                and row.decision.removeprefix("would_") == "block"
                for rows in rows_by.values() for row in rows
            )
            result["candidates"][name][str(size)] = report
            print(f"tuning {name} size={size}", flush=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()
    run(args.artifact_dir, args.frozen, args.out_json)


if __name__ == "__main__":
    main()
