"""Validate the ignored local identity mapping without printing identities."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_ROOT / "src"))

from rba_experiment.contracts import (  # noqa: E402
    CONFIG_DIR,
    load_config,
    load_json,
    validate_local_mapping,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight the local-only experiment identity mapping."
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=CONFIG_DIR / "local_identity_mapping.json",
        help="local mapping JSON (default: config/local_identity_mapping.json)",
    )
    args = parser.parse_args()

    if not args.mapping.is_file():
        parser.error(
            f"mapping not found: {args.mapping}; copy "
            "config/local_identity_mapping.example.json first"
        )

    mapping = load_json(args.mapping)
    users = load_config("users")
    subsystems = load_config("subsystems")
    try:
        digest = validate_local_mapping(mapping, users, subsystems)
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        parser.error(f"mapping validation failed: {exc}")

    print(
        "mapping preflight ok: "
        f"profiles={len(mapping['profiles'])} "
        f"subsystems={len(mapping['subsystems'])} "
        f"sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
