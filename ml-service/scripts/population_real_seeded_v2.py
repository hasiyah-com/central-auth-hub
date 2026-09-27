"""สร้างประชากรสังเคราะห์ V2: cadence จากค่ารวมจริงและ age carry แบบ opt-in.

ไฟล์นี้อ่านข้อมูลจริงเฉพาะจาก path ที่ผู้รันระบุ และส่งออกเฉพาะ alias/ค่าพารามิเตอร์
สังเคราะห์ตาม ``docs/design/REAL_SEEDED_POPULATION_V2_PREREG.md``
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import numpy as np

import population_real_seeded_v1 as V1

POP_SEED = 780927
N_TOTAL = 48
N_VALIDATION = 32
N_HOLDOUT = 16
ALIAS_PREFIX = "V"


def generate_population(
    prototypes: list[dict], seed: int = POP_SEED, n: int = N_TOTAL
) -> list[dict]:
    """Bootstrap ค่ารวม แต่ไม่ส่งออก observed rate ของบัญชีต้นแบบจริง."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        base = dict(rng.choice(prototypes))
        rate = max(float(base["observed_login_rate_per_day"]), 50.0 / 365.0)
        episode_days = int(np.clip(round(50.0 / rate), 25, 365))
        peaks = []
        for hour in base["hour_peaks"]:
            value = (int(hour) + rng.choice([-1, 0, 0, 0, 1])) % 24
            if value not in peaks:
                peaks.append(value)
        devices = V1._perturb_mix(base["devices"], rng) or {
            "win10_chrome151": 1.0
        }
        subsystems = V1._perturb_mix(base["subsystems"], rng) or {"HUB": 1.0}
        methods = V1._perturb_mix(base["methods"], rng) or {"google": 1.0}
        passkey = dict(base["passkey"])
        if passkey["count"]:
            passkey["age_days"] = int(
                np.clip(passkey["age_days"] * rng.uniform(0.7, 1.3), 7, 365)
            )
            passkey["last_used_days"] = int(
                np.clip(passkey["last_used_days"] + rng.randint(-3, 3), 0, 30)
            )
        out.append(
            {
                "alias": f"{ALIAS_PREFIX}{i + 1:02d}",
                "rows": int(
                    np.clip(base["rows"] * rng.uniform(0.75, 1.25), 40, 160)
                ),
                "hour_peaks": peaks or [12],
                "hour_spread": float(
                    np.clip(base["hour_spread"] * rng.uniform(0.8, 1.2), 1.5, 4.5)
                ),
                "weekend_rate": float(
                    np.clip(base["weekend_rate"] + rng.uniform(-0.05, 0.05), 0.0, 0.7)
                ),
                "devices": devices,
                "drift": float(
                    np.clip(base["drift"] * rng.uniform(0.8, 1.2), 0.05, 0.20)
                ),
                "subsystems": subsystems,
                "sticky": float(np.clip(max(subsystems.values()), 0.70, 1.0)),
                "dur": (
                    float(
                        np.clip(
                            base["dur"][0] + rng.uniform(-0.15, 0.15),
                            math.log(8),
                            math.log(45),
                        )
                    ),
                    float(np.clip(base["dur"][1] * rng.uniform(0.9, 1.1), 1.2, 2.2)),
                ),
                "overlap": float(
                    np.clip(base["overlap"] + rng.uniform(-0.02, 0.02), 0.0, 0.15)
                ),
                "active_sub": 2 if len(subsystems) > 1 else 1,
                "methods": methods,
                "passkey": passkey,
                "fail_rate": float(
                    np.clip(base["fail_rate"] * rng.uniform(0.7, 1.3), 0.0, 0.06)
                ),
                "scope": base["scope"],
                "perm_age": int(
                    np.clip(base["perm_age"] * rng.uniform(0.8, 1.2), 1, 365)
                ),
                "incidents": 0,
                "mfa_always": (
                    base["mfa_always"]
                    if rng.random() < 0.8
                    else not base["mfa_always"]
                ),
                "episode_days": episode_days,
                "episode_age_carry": True,
            }
        )
    return out


def split_population(
    profiles: list[dict], seed: int = POP_SEED
) -> tuple[list[dict], list[dict]]:
    rows = list(profiles)
    random.Random(seed).shuffle(rows)
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
    roster_json = args.out_dir / "roster_real_seeded_v2.json"
    V1.build_synthetic_identities(profiles, users_xlsx, roster_json)

    summary = {
        "population": "real_seeded_v2",
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
            "weekend_rate_range": [
                round(min(p["weekend_rate"] for p in profiles), 4),
                round(max(p["weekend_rate"] for p in profiles), 4),
            ],
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
