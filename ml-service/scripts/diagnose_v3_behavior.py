"""Post-failure V3 diagnostics; aggregate only, never a V4 validation gate."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for directory in (HERE, HERE.parent, ROOT / "hub" / "backend"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import exp_real_seeded_validation as V1  # noqa: E402
import exp_real_seeded_validation_v3 as V3  # noqa: E402

FAMILIES = ("campaign", "new_passkey", "subtle_rare_device")


def analyze(raw_cache: dict) -> dict:
    names = V1.FEATURE_NAMES
    families: dict[str, list[tuple[str, np.ndarray]]] = defaultdict(list)
    normals: dict[str, list[np.ndarray]] = defaultdict(list)
    campaign_like_count = 0
    for raw in raw_cache.values():
        for alias, user in raw.items():
            normals[alias].extend(np.asarray(v, dtype=float) for v in user["val_ft"][500:])
            campaign_like_count += len(user["camp_like"])
            for row, vector in user["dev_attacks"]:
                family = row.get("scenario")
                if family in FAMILIES:
                    families[family].append((alias, np.asarray(vector, dtype=float)))

    report: dict = {"status": "post_failure_exploratory_not_validation", "families": {}}
    for family in FAMILIES:
        attacks = families[family]
        stats = []
        for index, name in enumerate(names):
            weighted_auc = 0.0
            compared = 0
            within_range = 0
            for alias in normals:
                a = np.asarray([v[index] for who, v in attacks if who == alias])
                if not len(a):
                    continue
                n = np.asarray([v[index] for v in normals[alias]])
                auc = V1.DS._auc_with_ties(a, n)
                weighted_auc += auc * len(a)
                compared += len(a)
                within_range += int(((a >= n.min()) & (a <= n.max())).sum())
            if compared:
                stats.append(
                    {
                        "feature": name,
                        "direction_free_auc": round(weighted_auc / compared, 4),
                        "within_user_normal_range": round(within_range / compared, 4),
                    }
                )
        report["families"][family] = {
            "n_events": len(attacks),
            "top_features": sorted(
                stats, key=lambda item: item["direction_free_auc"], reverse=True
            )[:8],
            "all_feature_auc": stats,
        }
    report["campaign_like_normal_count_in_generator_output"] = campaign_like_count
    report["campaign_like_normal_count_in_v3_tuning"] = 0
    report["note"] = (
        "Per-user univariate AUC is descriptive and ignores feature interactions; "
        "V3 tuning uses val_ft normal and dev_attacks, not camp_like. "
        "Do not use this result to select a V3 threshold or open holdout."
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()
    profiles, meta, roster = V3._load_population(args.artifact_dir)
    validation = set(meta["split"]["validation"])
    holdout = set(meta["split"]["holdout"])
    if len(validation) != 32 or len(holdout) != 16 or validation & holdout:
        raise ValueError("V3 validation/holdout split invalid")
    raw = V3._generate_raw(args.artifact_dir, profiles, roster, validation, V3.SEEDS)
    for seed_raw in raw.values():
        V1._trim_dev_attacks(seed_raw)
    result = analyze(raw)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "families": {
                    key: {
                        "n_events": value["n_events"],
                        "top_features": value["top_features"][:4],
                    }
                    for key, value in result["families"].items()
                },
                "campaign_like_normal_count_in_generator_output": result[
                    "campaign_like_normal_count_in_generator_output"
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
