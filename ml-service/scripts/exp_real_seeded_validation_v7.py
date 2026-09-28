"""V7 frozen comparison of existing production L3 point/sequence views."""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

import exp_real_seeded_validation_v6 as V6

SEEDS = (761, 762, 763)
SIZE = 2000
CONFIGS = ("E", "G", "C", "D")


def run(artifact: Path, frozen: Path, output: Path) -> dict:
    spec = json.loads((artifact / "population_spec.json").read_text())
    meta = json.loads((artifact / "population_summary.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v7.json").read_text())
    val, hold = set(meta["split"]["validation"]), set(meta["split"]["holdout"])
    if len(val) != 32 or len(hold) != 16 or val & hold:
        raise ValueError("V7 split invalid")
    records = {key: {} for key in CONFIGS}
    tuning = {key: {} for key in CONFIGS}
    mix, family_counts = {}, Counter()
    for seed in SEEDS:
        raw = V6.V5.G5.build_seed(
            artifact / "synthetic_users.xlsx", seed,
            [p for p in spec if p["alias"] in val],
            {alias: roster[alias] for alias in val},
        )
        V6.V5.V1._trim_dev_attacks(raw)
        if not V6.V5.V1._feature_contract(raw)["passed"]:
            raise ValueError("23-feature contract invalid")
        n_attack = sum(len(u["dev_attacks"]) for u in raw.values())
        mix[str(seed)] = n_attack / (n_attack + 505 * len(raw))
        if mix[str(seed)] > 0.07:
            raise ValueError("anomaly budget exceeded")
        family_counts.update(
            str(row.get("scenario")) for user in raw.values()
            for row, _ in user["dev_attacks"]
        )
        cal, tune, ecdf = V6.V5.V4._fit_contexts(
            raw, SIZE, V6.V5.A.GROUPS["behavioral"]
        )
        c_cal, c_tune = [V6.adjusted(c) for c in cal], [V6.adjusted(c) for c in tune]
        c_ecdf = copy.deepcopy(ecdf)
        c_ecdf.fit("behavior", [c.behavior.score for c in c_cal])
        for key, candidate_records in records.items():
            cfg = V6.V5.CFG.CONFIGS[key]
            candidate_records[(seed, SIZE)] = V6.V5.X.build_records(
                c_cal, c_ecdf, cfg, V6.V5.DEFAULT_GAMMA
            )
            tuning[key][seed] = (c_tune, c_ecdf)
        print(f"calculated seed={seed}", flush=True)
    thresholds, calibration = {}, {}
    for key, candidate_records in records.items():
        thresholds[key], calibration[key] = V6.V5.V2.calibrate_thresholds(candidate_records)
    frozen.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_text(json.dumps({
        "status": "v7_frozen_before_tuning", "thresholds": thresholds,
        "population_sha256": V6.V5.V2._sha256(artifact / "population_spec.json"),
        "generator_sha256": V6.V5.V2._sha256(Path(V6.V5.G5.__file__)),
        "harness_sha256": V6.V5.V2._sha256(Path(__file__)),
        "seeds": list(SEEDS), "history": SIZE,
    }, indent=2) + "\n")
    print("V7 THRESHOLDS FROZEN BEFORE TUNING", flush=True)
    result = {
        "status": "v7_offline_pilot_no_service_parity", "holdout_opened": False,
        "production_changed": False, "anomaly_rates": mix,
        "family_counts": dict(family_counts),
        "rare_family_underpowered": family_counts["subtle_rare_device"] < 30,
        "thresholds": thresholds, "calibration": calibration, "candidates": {},
    }
    for key, threshold in thresholds.items():
        if threshold is None:
            result["candidates"][key] = {"status": "normal_calibration_infeasible"}
            continue
        rows_by, stats = {}, []
        for seed in SEEDS:
            ctx, ecdf = tuning[key][seed]
            rows = V6.V5.X.apply_config(
                ctx, V6.V5.CFG.CONFIGS[key], ecdf, V6.V5.DEFAULT_GAMMA, threshold
            )
            rows_by[seed] = rows
            stats.append(V6.V5.TU.cell_stat(seed, SIZE, rows))
        report = V6.V5.V1._history_report(rows_by, stats, ci_seed=61000)
        report["normal_campaign_like_challenges"] = sum(
            not r.is_attack and r.family == "campaign_like_normal"
            and r.decision.removeprefix("would_") in ("challenge", "block")
            for rows in rows_by.values() for r in rows
        )
        result["candidates"][key] = report
        print(f"tuning config={key}", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
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
