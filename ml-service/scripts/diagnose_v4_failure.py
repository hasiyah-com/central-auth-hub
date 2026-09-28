"""Post-failure V4 attribution using synthetic validation only; no holdout."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "hub" / "backend"))
sys.path.insert(1, str(HERE))
sys.path.insert(2, str(HERE.parent))

import ablate_v4_behavior as A
import exp_real_seeded_validation as V1
import exp_real_seeded_validation_v4 as V4
from app.security.risk_fusion import DEFAULT_GAMMA
from hybrid_experiment import configs as CFG


def run(artifact: Path, frozen: Path) -> dict:
    meta = json.loads((artifact / "population_summary.json").read_text())
    profiles = json.loads((artifact / "population_spec.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v4.json").read_text())
    thresholds = json.loads(frozen.read_text())["thresholds"]
    val = set(meta["split"]["validation"])
    hold = set(meta["split"]["holdout"])
    if len(val) != 32 or len(hold) != 16 or val & hold:
        raise ValueError("validation/holdout split invalid")
    groups = ("all_23", "behavioral")
    counters = {g: Counter() for g in groups}
    for seed in V4.SEEDS:
        raw = V4.G4.build_seed(
            artifact / "synthetic_users.xlsx", seed,
            [p for p in profiles if p["alias"] in val],
            {alias: roster[alias] for alias in val},
        )
        V1._trim_dev_attacks(raw)
        for group in groups:
            _, contexts, ecdf = V4._fit_contexts(raw, 2000, A.GROUPS[group])
            counts = counters[group]
            for ctx in contexts:
                decision = CFG.evaluate(
                    CFG.CONFIGS["E"], ctx.policy, ctx.rule, ctx.behavior, ctx.l3,
                    calibrate_fn=ecdf, gamma=DEFAULT_GAMMA,
                    thresholds=thresholds[group],
                )
                actual = decision.decision.removeprefix("would_")
                source = "attack" if ctx.is_attack else "normal"
                counts[f"{source}_total"] += 1
                if ctx.is_attack and ctx.family == "subtle_rare_device":
                    counts["rare_total"] += 1
                    counts[f"rare_{actual}"] += 1
                    if any("signature_rarity" in reason for reason in ctx.behavior.reasons):
                        counts["rare_signature_rarity_present"] += 1
                if ctx.is_attack or actual != "block":
                    continue
                counts["normal_block"] += 1
                counts[f"block_primary_{decision.breakdown.get('primary_layer', 'policy')}"] += 1
                counts[f"block_fusion_{decision.breakdown.get('fusion')}"] += 1
                if ctx.policy.denied:
                    counts["block_policy_denied"] += 1
                if ctx.family == "campaign_like_normal":
                    counts["block_campaign_like_normal"] += 1
                if any("signature_rarity" in reason for reason in ctx.behavior.reasons):
                    counts["block_signature_rarity_present"] += 1
            print(f"attributed seed={seed} group={group}", flush=True)
    return {
        "status": "post_failure_diagnostic_not_a_new_gate",
        "holdout_opened": False,
        "groups": {group: dict(counts) for group, counts in counters.items()},
    }


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
