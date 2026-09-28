"""Exploratory normal-only per-user point Isolation Forest feature ablation.

This is NOT the production fusion/sequence protocol or the V4 accuracy gate.
It never opens holdout; future V4 validation must freeze a full end-to-end setup.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np
from sklearn.ensemble import IsolationForest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for path in (HERE, HERE.parent, ROOT / "hub" / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import exp_real_seeded_validation as V1  # noqa: E402
import gen_v4_behavior as G4  # noqa: E402

ALL = tuple(V1.FEATURE_NAMES)
BEHAVIORAL = (
    "hour_of_day", "day_of_week", "hours_from_typical_login_time",
    "is_new_device", "is_new_user_agent_family", "log_minutes_since_last_login",
    "login_count_24h", "weekday_usage_score", "active_subsystem_count",
    "scope_sensitivity_score",
)
TRUST = (
    "passkey_count", "passkey_age_days", "new_passkey_recently_added",
    "passkey_last_used_days", "ever_changed_permission", "permission_change_age",
    "confirmed_incident_count",
)
GEO = (
    "is_thailand", "is_new_country", "country_change_count_30d",
    "impossible_travel_score",
)
GROUPS = {
    "all_23": ALL,
    "behavioral": BEHAVIORAL,
    "behavioral_trust": BEHAVIORAL + TRUST,
    "behavioral_geo": BEHAVIORAL + GEO,
}
SEEDS = (731, 732, 733)
SIZES = (100, 2000)
CAL_TAIL = 0.005


def _scores(model, vectors: list, indexes: list[int]) -> np.ndarray:
    if not vectors:
        return np.empty(0)
    return -model.score_samples(np.asarray(vectors, dtype=float)[:, indexes])


def run(artifact: Path, seeds: tuple[int, ...], sizes: tuple[int, ...]) -> dict:
    profiles = json.loads((artifact / "population_spec.json").read_text())
    meta = json.loads((artifact / "population_summary.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v4.json").read_text())
    val, hold = set(meta["split"]["validation"]), set(meta["split"]["holdout"])
    if len(val) != 32 or len(hold) != 16 or val & hold:
        raise ValueError("V4 split invalid; refuse to run")
    if len(ALL) != 23 or any(set(names) - set(ALL) for names in GROUPS.values()):
        raise ValueError("feature contract mismatch")
    selected = [p for p in profiles if p["alias"] in val]
    selected_roster = {alias: roster[alias] for alias in val}
    result = {
        "status": "exploratory_point_only_not_production_or_v4_gate",
        "normal_only_train_calibration": True,
        "holdout_opened": False,
        "sizes": list(sizes),
        "seeds": list(seeds),
        "calibration_tail_per_user": CAL_TAIL,
        "groups": {key: list(names) for key, names in GROUPS.items()},
        "cells": {},
    }
    for seed in seeds:
        raw = G4.build_seed(
            artifact / "synthetic_users.xlsx", seed, selected, selected_roster
        )
        V1._trim_dev_attacks(raw)
        for size in sizes:
            counts = {
                group: {"tp": 0, "fp": 0, "normal": 0, "attack": 0,
                        "family": defaultdict(lambda: [0, 0]),
                        "campaign_like_fp": 0, "campaign_like_normal": 0}
                for group in GROUPS
            }
            for user in raw.values():
                train, calibration, normal, attacks = G4.validation_split(user, size)
                assert len(calibration) == 500 and len(normal) == 505
                for group, names in GROUPS.items():
                    indexes = [ALL.index(name) for name in names]
                    model = IsolationForest(
                        n_estimators=100, contamination=0.02, random_state=42
                    ).fit(np.asarray(train, dtype=float)[:, indexes])
                    limit = float(np.quantile(_scores(model, calibration, indexes), 1 - CAL_TAIL))
                    normal_hits = _scores(model, normal, indexes) >= limit
                    attack_hits = _scores(model, [v for _, v in attacks], indexes) >= limit
                    row = counts[group]
                    row["fp"] += int(normal_hits.sum())
                    row["normal"] += len(normal)
                    row["tp"] += int(attack_hits.sum())
                    row["attack"] += len(attacks)
                    row["campaign_like_fp"] += int(normal_hits[-5:].sum())
                    row["campaign_like_normal"] += 5
                    for (attack, _), hit in zip(attacks, attack_hits):
                        family = row["family"][attack["scenario"]]
                        family[0] += int(hit)
                        family[1] += 1
            for group, row in counts.items():
                tp, fp = row["tp"], row["fp"]
                result["cells"][f"{seed}:{size}:{group}"] = {
                    "recall": tp / row["attack"],
                    "precision": tp / (tp + fp) if tp + fp else 0.0,
                    "fpr": fp / row["normal"],
                    "tp": tp, "fp": fp, "normal": row["normal"],
                    "attack": row["attack"],
                    "campaign_like_fp": row["campaign_like_fp"],
                    "campaign_like_normal": row["campaign_like_normal"],
                    "family_recall": {
                        key: hit / n for key, (hit, n) in row["family"].items()
                    },
                }
            print(f"exploratory seed={seed} history={size}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    parser.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    args = parser.parse_args()
    if not set(args.seeds) <= set(SEEDS) or not set(args.sizes) <= set(SIZES):
        raise ValueError("non-preregistered exploratory seed/history")
    result = run(args.artifact_dir, tuple(args.seeds), tuple(args.sizes))
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "cells": len(result["cells"])}))


if __name__ == "__main__":
    main()
