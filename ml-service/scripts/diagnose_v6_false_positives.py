"""Post-failure V6 attribution using aggregate counts only and unopened holdout."""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

import exp_real_seeded_validation_v6 as V6


def run(artifact: Path, frozen: Path) -> dict:
    profiles = json.loads((artifact / "population_spec.json").read_text())
    meta = json.loads((artifact / "population_summary.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v6.json").read_text())
    validation, holdout = set(meta["split"]["validation"]), set(meta["split"]["holdout"])
    if len(validation) != 32 or len(holdout) != 16 or validation & holdout:
        raise ValueError("split invalid")
    thresholds = json.loads(frozen.read_text())["thresholds"]
    counters = {name: Counter() for name in thresholds}
    for seed in V6.SEEDS:
        raw = V6.V5.G5.build_seed(
            artifact / "synthetic_users.xlsx", seed,
            [p for p in profiles if p["alias"] in validation],
            {alias: roster[alias] for alias in validation},
        )
        V6.V5.V1._trim_dev_attacks(raw)
        cal, tune, ecdf = V6.V5.V4._fit_contexts(
            raw, 2000, V6.V5.A.GROUPS["behavioral"]
        )
        for name, counts in counters.items():
            c_cal = cal if name == "control" else [V6.adjusted(c) for c in cal]
            c_tune = tune if name == "control" else [V6.adjusted(c) for c in tune]
            c_ecdf = copy.deepcopy(ecdf)
            if name != "control":
                c_ecdf.fit("behavior", [c.behavior.score for c in c_cal])
            for ctx in c_tune:
                if ctx.is_attack:
                    continue
                decision = V6.V5.CFG.evaluate(
                    V6.V5.CFG.CONFIGS["E"], ctx.policy, ctx.rule, ctx.behavior,
                    ctx.l3, calibrate_fn=c_ecdf, gamma=V6.V5.DEFAULT_GAMMA,
                    thresholds=thresholds[name],
                )
                action = decision.decision.removeprefix("would_")
                if action not in ("challenge", "block"):
                    continue
                counts[f"normal_{action}"] += 1
                counts[f"{action}_primary_{decision.breakdown.get('primary_layer', 'policy')}"] += 1
                if ctx.family == "campaign_like_normal":
                    counts[f"{action}_campaign_like"] += 1
                reasons = ctx.behavior.reasons
                for prefix in ("hours_diff=", "hour_rarity=", "cadence_fast",
                               "scope_escalation", "signature_rarity="):
                    if any(r.startswith(prefix) for r in reasons):
                        counts[f"{action}_reason_{prefix.rstrip('=')}"] += 1
    return {"status": "post_failure_diagnostic", "holdout_opened": False,
            "candidates": {name: dict(counts) for name, counts in counters.items()}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.artifact_dir, args.frozen)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
