"""ประชากร V3: cadence/age-carry แบบ V2 แต่ bootstrap seed และ aliases ใหม่."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import population_real_seeded_v1 as V1
import population_real_seeded_v2 as V2

POP_SEED = 790927
N_TOTAL = 48
N_VALIDATION = 32
N_HOLDOUT = 16


def generate_population(prototypes: list[dict]) -> list[dict]:
    profiles = V2.generate_population(prototypes, seed=POP_SEED, n=N_TOTAL)
    for index, profile in enumerate(profiles, start=1):
        profile["alias"] = f"W{index:02d}"
    return profiles


def split_population(profiles: list[dict]) -> tuple[list[dict], list[dict]]:
    rows = list(profiles)
    random.Random(POP_SEED).shuffle(rows)
    return rows[:N_VALIDATION], rows[N_VALIDATION : N_VALIDATION + N_HOLDOUT]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--source-zip", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    prototypes, source_meta = V1.derive_prototypes(args.input_dir)
    profiles = generate_population(prototypes)
    validation, holdout = split_population(profiles)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    users_xlsx = args.out_dir / "synthetic_users.xlsx"
    roster_json = args.out_dir / "roster_real_seeded_v3.json"
    V1.build_synthetic_identities(profiles, users_xlsx, roster_json)

    summary = {
        "population": "real_seeded_v3",
        "population_seed": POP_SEED,
        "source": {
            **source_meta,
            "zip_sha256": V1._sha256(args.source_zip) if args.source_zip else None,
        },
        "split": {
            "validation": [p["alias"] for p in validation],
            "holdout": [p["alias"] for p in holdout],
        },
        "population_summary": {
            "n_profiles": len(profiles),
            "passkey_profiles": sum(p["passkey"]["count"] > 0 for p in profiles),
            "multi_device_profiles": sum(len(p["devices"]) > 1 for p in profiles),
            "multi_subsystem_profiles": sum(
                len(p["subsystems"]) > 1 for p in profiles
            ),
            "episode_days_range": [
                min(p["episode_days"] for p in profiles),
                max(p["episode_days"] for p in profiles),
            ],
            "age_carry_profiles": sum(p["episode_age_carry"] for p in profiles),
        },
        "privacy": {
            "raw_identifiers_in_output": False,
            "aliases_only": True,
            "real_values_exported": False,
            "per_account_observed_rate_exported": False,
        },
    }
    spec_path = args.out_dir / "population_spec.json"
    summary_path = args.out_dir / "population_summary.json"
    spec_path.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    scan = V1.privacy_scan([spec_path, summary_path, roster_json])
    if not scan["passed"]:
        raise RuntimeError(f"privacy scan failed: {scan}")
    print(
        json.dumps(
            {
                "profiles": len(profiles),
                "validation": len(validation),
                "holdout": len(holdout),
                "episode_days_range": summary["population_summary"][
                    "episode_days_range"
                ],
                "privacy_scan": scan,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
