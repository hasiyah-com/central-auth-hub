"""Aggregate V5 validation failure paths without exporting user-level records."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import exp_real_seeded_validation_v5 as V5


def reason_kind(reason: str) -> str:
    return reason.split("=")[0].split(" ")[0]


def run(artifact: Path, frozen: Path) -> dict:
    meta = json.loads((artifact / "population_summary.json").read_text())
    profiles = json.loads((artifact / "population_spec.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v5.json").read_text())
    selected = set(meta["split"]["validation"])
    if len(selected) != 32 or len(meta["split"]["holdout"]) != 16:
        raise ValueError("invalid split")
    threshold = json.loads(frozen.read_text())["thresholds"]["behavioral"]
    result = Counter()
    for seed in V5.SEEDS:
        raw = V5.G5.build_seed(
            artifact / "synthetic_users.xlsx", seed,
            [p for p in profiles if p["alias"] in selected],
            {alias: roster[alias] for alias in selected},
        )
        V5.V1._trim_dev_attacks(raw)
        _, tune, ecdf = V5.V4._fit_contexts(raw, 2000, V5.A.GROUPS["behavioral"])
        for ctx in tune:
            decision = V5.CFG.evaluate(
                V5.CFG.CONFIGS["E"], ctx.policy, ctx.rule, ctx.behavior, ctx.l3,
                calibrate_fn=ecdf, gamma=V5.DEFAULT_GAMMA, thresholds=threshold,
            )
            action = decision.decision.removeprefix("would_")
            reasons = {reason_kind(reason) for reason in ctx.behavior.reasons}
            if not ctx.is_attack and action == "block":
                result["normal_block"] += 1
                result[f"primary_{decision.breakdown.get('primary_layer', 'policy')}"] += 1
                if ctx.family == "campaign_like_normal":
                    result["normal_campaign_like_block"] += 1
                for reason in reasons:
                    result[f"normal_block_reason_{reason}"] += 1
                if ctx.policy.denied:
                    result["policy_denied_block"] += 1
            if ctx.is_attack and ctx.family == "subtle_rare_device":
                result["rare_total"] += 1
                result[f"rare_{action}"] += 1
                if "signature_rarity" in reasons:
                    result["rare_signature_fires"] += 1
                    result[f"rare_signature_{action}"] += 1
                    result[f"rare_signature_behavior_score_{round(ctx.behavior.score, 1):.1f}"] += 1
    return {"status": "post_failure_diagnostic", "holdout_opened": False, "counts": dict(result)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.artifact_dir, args.frozen)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
