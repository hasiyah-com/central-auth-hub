"""Frozen V4 aliases and split; inherits V2 cadence/age-carry population rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random

import population_real_seeded_v1 as V1
import population_real_seeded_v2 as V2

POP_SEED = 800928
N_VALIDATION = 32


def generate_population(prototypes: list[dict]) -> list[dict]:
    profiles = V2.generate_population(prototypes, seed=POP_SEED, n=48)
    for index, profile in enumerate(profiles, start=1):
        profile["alias"] = f"X{index:02d}"
    return profiles


def split_population(profiles: list[dict]) -> tuple[list[dict], list[dict]]:
    rows = list(profiles)
    random.Random(POP_SEED).shuffle(rows)
    return rows[:N_VALIDATION], rows[N_VALIDATION:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--source-zip", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    prototypes, source_meta = V1.derive_prototypes(args.input_dir)
    profiles = generate_population(prototypes)
    validation, holdout = split_population(profiles)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    roster_path = args.out_dir / "roster_real_seeded_v4.json"
    V1.build_synthetic_identities(
        profiles, args.out_dir / "synthetic_users.xlsx", roster_path
    )
    spec_path = args.out_dir / "population_spec.json"
    summary_path = args.out_dir / "population_summary.json"
    spec_path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + "\n")
    summary_path.write_text(
        json.dumps(
            {
                "population": "real_seeded_v4",
                "population_seed": POP_SEED,
                "source": {
                    **source_meta,
                    "zip_sha256": V1._sha256(args.source_zip)
                    if args.source_zip
                    else None,
                },
                "split": {
                    "validation": [p["alias"] for p in validation],
                    "holdout": [p["alias"] for p in holdout],
                },
                "privacy": {"aliases_only": True, "real_values_exported": False},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    scan = V1.privacy_scan([spec_path, summary_path, roster_path])
    if not scan["passed"]:
        raise RuntimeError("V4 privacy scan failed")
    print(json.dumps({"profiles": 48, "validation": 32, "holdout": 16, "privacy": scan}))


if __name__ == "__main__":
    main()
