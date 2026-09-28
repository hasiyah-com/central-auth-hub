"""Fresh aliases and seed for preregistered V6 synthetic validation."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import population_real_seeded_v1 as V1
import population_real_seeded_v2 as V2

SEED = 810929


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    prototypes, source = V1.derive_prototypes(args.input_dir)
    profiles = V2.generate_population(prototypes, seed=SEED, n=48)
    for index, profile in enumerate(profiles, 1):
        profile["alias"] = f"Z{index:02d}"
    split = list(profiles)
    random.Random(SEED).shuffle(split)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    spec = args.out_dir / "population_spec.json"
    summary = args.out_dir / "population_summary.json"
    roster = args.out_dir / "roster_real_seeded_v6.json"
    V1.build_synthetic_identities(profiles, args.out_dir / "synthetic_users.xlsx", roster)
    spec.write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + "\n")
    summary.write_text(json.dumps({
        "population": "real_seeded_v6", "population_seed": SEED,
        "source": source,
        "split": {
            "validation": [p["alias"] for p in split[:32]],
            "holdout": [p["alias"] for p in split[32:]],
        },
        "privacy": {"aliases_only": True, "real_values_exported": False},
    }, ensure_ascii=False, indent=2) + "\n")
    if not V1.privacy_scan([spec, summary, roster])["passed"]:
        raise RuntimeError("privacy scan failed")
    print(json.dumps({"profiles": 48, "validation": 32, "holdout": 16, "privacy": True}))


if __name__ == "__main__":
    main()
