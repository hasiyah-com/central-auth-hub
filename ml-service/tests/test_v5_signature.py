"""Regression checks for V5's production-compatible synthetic signatures."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BACKEND = Path(__file__).resolve().parents[2] / "hub" / "backend"
for path in (SCRIPTS, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import gen_v5_signature as G5
import population_real_seeded_v5 as P5


def test_canonical_signature_matches_production_for_every_synthetic_device():
    from build_profiles_v2 import DEVICES

    for _, _, _, _, ua_template, version in DEVICES.values():
        ua = ua_template.format(v=version)
        row = {"user_agent": ua, "device_signature": "legacy"}
        G5.canonicalize([row])
        assert row["device_signature"] == G5._device_signature(ua)
        assert row["device_signature"] != "legacy"


def test_v5_population_is_independent_and_holdout_closed():
    from test_real_seeded_population import PROTOTYPES

    profiles = P5.generate_population(PROTOTYPES)
    validation, holdout = P5.split_population(profiles)
    assert [p["alias"] for p in profiles] == [f"Y{i:02d}" for i in range(1, 49)]
    assert len(validation) == 32 and len(holdout) == 16
    assert {p["alias"] for p in validation}.isdisjoint(
        {p["alias"] for p in holdout}
    )
