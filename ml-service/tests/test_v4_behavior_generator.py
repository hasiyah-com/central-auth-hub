from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BACKEND = Path(__file__).resolve().parents[2] / "hub" / "backend"
for path in (SCRIPTS, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import gen_v4_behavior as G4  # noqa: E402
import population_real_seeded_v4 as P4  # noqa: E402


def test_existing_passkey_ages_from_previous_normal_state():
    prior = {
        "created_at": "2026-01-01 12:00:00",
        "passkey_age_days": 201,
        "passkey_last_used_days": 3,
    }
    attack = {
        "created_at": "2026-01-03 12:00:00",
        "passkey_age_days": 10,
        "passkey_last_used_days": 0,
        "new_passkey_recently_added": False,
    }
    corrected = G4._as_of_state(attack, prior)
    assert corrected["passkey_age_days"] == 203
    assert corrected["passkey_last_used_days"] == 5
    assert corrected["new_passkey_recently_added"] == "False"


def test_new_passkey_flag_survives_in_memory_generator():
    new = {
        "created_at": "2026-01-03 12:00:00",
        "passkey_age_days": 0,
        "passkey_last_used_days": 0,
        "new_passkey_recently_added": True,
    }
    corrected = G4._as_of_state(new, {"created_at": "2026-01-01 12:00:00"})
    assert corrected["passkey_age_days"] == 0
    assert corrected["new_passkey_recently_added"] == "True"


def test_v4_population_is_fresh_and_keeps_holdout_closed():
    from test_real_seeded_population import PROTOTYPES

    profiles = P4.generate_population(PROTOTYPES)
    validation, holdout = P4.split_population(profiles)
    assert [p["alias"] for p in profiles] == [f"X{i:02d}" for i in range(1, 49)]
    assert len(validation) == 32 and len(holdout) == 16
    assert {p["alias"] for p in validation}.isdisjoint(
        {p["alias"] for p in holdout}
    )


def test_campaign_uses_only_prior_phases_and_prior_normal(monkeypatch):
    captured = []

    def capture(row, trusted, observed):
        captured.append(
            (row["created_at"], [r["created_at"] for r in trusted],
             [r["created_at"] for r in observed])
        )
        return [len(observed)]

    monkeypatch.setattr(G4.FE, "compute", capture)
    normals = [
        {
            "created_at": when,
            "passkey_age_days": 100,
            "passkey_last_used_days": 2,
            "device_signature": "synthetic-device",
            "episode": 0,
        }
        for when in ("2026-01-01 08:00:00", "2026-01-01 11:00:00")
    ]
    attack = [
        {
            "created_at": when,
            "scenario": "campaign",
            "row_kind": "attack",
            "new_passkey_recently_added": False,
        }
        for when in ("2026-01-01 09:00:00", "2026-01-01 10:00:00")
    ]
    vectors = G4._recompute(attack, normals, last_episode=0)
    assert [v for _, v in vectors] == [[1], [2]]
    assert all("2026-01-01 11:00:00" not in earlier for _, earlier, _ in captured)
    assert captured[1][2] == ["2026-01-01 08:00:00", "2026-01-01 09:00:00"]
