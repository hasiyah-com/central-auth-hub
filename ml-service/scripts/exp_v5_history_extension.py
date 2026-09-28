"""Extend V5 training history using thresholds frozen before this experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import exp_real_seeded_validation_v5 as V5

SIZES = (2000, 3000, 4000, 5000)
GROUPS = ("all_23", "behavioral")


def stable_pair(left: dict, right: dict) -> bool:
    return (
        abs(left["recall"] - right["recall"]) < 0.01
        and abs(left["precision"] - right["precision"]) < 0.01
        and abs(left["block_fpr"] - right["block_fpr"]) < 0.0005
    )


def run(artifact: Path, frozen_path: Path, output: Path) -> dict:
    frozen = json.loads(frozen_path.read_text())
    if (frozen["seeds"] != list(V5.SEEDS) or frozen["sizes"] != list(V5.SIZES)
            or frozen["population_sha256"] != V5.V2._sha256(artifact / "population_spec.json")
            or frozen["generator_sha256"] != V5.V2._sha256(Path(V5.G5.__file__))):
        raise ValueError("V5 frozen inputs do not match; refusing extension")
    profiles = json.loads((artifact / "population_spec.json").read_text())
    meta = json.loads((artifact / "population_summary.json").read_text())
    roster = json.loads((artifact / "roster_real_seeded_v5.json").read_text())
    validation = set(meta["split"]["validation"])
    holdout = set(meta["split"]["holdout"])
    if len(validation) != 32 or len(holdout) != 16 or validation & holdout:
        raise ValueError("V5 split invalid")
    selected = [p for p in profiles if p["alias"] in validation]
    selected_roster = {alias: roster[alias] for alias in validation}
    result = {
        "status": "diagnostic_history_extension_no_service_parity",
        "holdout_opened": False,
        "seeds": list(V5.SEEDS), "sizes": list(SIZES),
        "stability_delta": {"recall": 0.01, "precision": 0.01, "block_fpr": 0.0005},
        "groups": {},
    }
    for group in GROUPS:
        result["groups"][group] = {"sizes": {}}
    for seed in V5.SEEDS:
        raw = V5.G5.build_seed(artifact / "synthetic_users.xlsx", seed, selected, selected_roster)
        V5.V1._trim_dev_attacks(raw)
        if not V5.V1._feature_contract(raw)["passed"] or min(
            len(u["train_ft"]) for u in raw.values()
        ) < 5000:
            raise ValueError("V5 feature contract or training history invalid")
        for size in SIZES:
            for group in GROUPS:
                thresholds = frozen["thresholds"][group]
                if not thresholds:
                    raise ValueError(f"No frozen threshold for {group}")
                _, tuning, ecdf = V5.V4._fit_contexts(raw, size, V5.A.GROUPS[group])
                rows = V5.X.apply_config(
                    tuning, V5.CFG.CONFIGS["E"], ecdf, V5.DEFAULT_GAMMA, thresholds
                )
                cells = result["groups"][group]["sizes"].setdefault(
                    str(size), {"rows_by_seed": {}, "cell_stats": []}
                )
                cells["rows_by_seed"][seed] = rows
                cells["cell_stats"].append(V5.TU.cell_stat(seed, size, rows))
                print(f"computed {group} seed={seed} size={size}", flush=True)
    for group in GROUPS:
        sizes = result["groups"][group]["sizes"]
        for size in SIZES:
            cell = sizes[str(size)]
            report = V5.V1._history_report(
                cell["rows_by_seed"], cell["cell_stats"], ci_seed=59000 + size
            )
            summary = report["summary"]
            cell["pooled"] = {name: summary[name] for name in (
                "recall", "precision", "warn_fpr", "challenge_fpr", "block_fpr"
            )}
            cell["family_recall"] = {
                name: stat["recall"] for name, stat in report["family_recall"].items()
            }
            cell["by_seed"] = {
                str(stat.seed): {key: stat.pooled[key] for key in (
                    "recall", "precision", "warn_fpr", "challenge_fpr", "block_fpr"
                )} for stat in cell["cell_stats"]
            }
            del cell["rows_by_seed"], cell["cell_stats"]
        result["groups"][group]["stable_windows"] = [
            list(SIZES[i:i + 3]) for i in range(len(SIZES) - 2)
            if all(
                stable_pair(sizes[str(SIZES[j])]["pooled"], sizes[str(SIZES[j + 1])]["pooled"])
                and all(
                    stable_pair(
                        sizes[str(SIZES[j])]["by_seed"][str(seed)],
                        sizes[str(SIZES[j + 1])]["by_seed"][str(seed)],
                    ) for seed in V5.SEEDS
                ) for j in (i, i + 1)
            )
        ]
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
